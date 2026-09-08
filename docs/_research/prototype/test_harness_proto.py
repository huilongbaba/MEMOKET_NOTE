"""对原型跑六个场景，验证架构的关键行为。"""
import asyncio
from harness_proto import *

class Hooks:
    """假 harness：produce 负责更新 content（架构定的契约）。"""
    def __init__(self, texts): self.texts, self.saved = texts, []
    async def prepare(self, st): return [f"事实{st.round}"], None
    async def produce(self, st):
        for ch in self.texts[st.round - 1]:
            yield ch
        st.content = self.texts[st.round - 1]      # 块生成：整块替换
    async def commit(self, st): self.saved.append(st.content)

def evaluator(seq):
    async def ev(st):
        lv = seq[st.round - 1]
        status = "complete" if all(v >= 2 for v in lv) else "continue"
        return Evaluation({f"d{i}": Score(v) for i, v in enumerate(lv)}, status)
    return ev

async def drive(st, hooks, ev):
    return [e async for e in run(st, hooks, ev)]

async def main():
    ok = []

    # ① 正常完成：第 2 轮全达标就停
    h = Hooks(["a", "b", "c"])
    st = State(Mode("t"))
    evs = await drive(st, h, evaluator([[1,2],[2,2],[2,2]]))
    fin = [e for e in evs if e.type == "RUN_FINISHED"][0]
    ok.append(("① complete 提前停", fin.data["reason"] == "complete"
               and fin.data["content"] == "b" and st.round == 2))

    # ② 跑满轮数：交付 best 而不是最后一轮（第 2 轮最好）
    h = Hooks(["a", "bb", "c"])
    st = State(Mode("t"))
    evs = await drive(st, h, evaluator([[1,1],[2,1],[0,1]]))
    fin = [e for e in evs if e.type == "RUN_FINISHED"][0]
    ok.append(("② 跑满取 best 不是最后一轮",
               fin.data["reason"] == "max_rounds" and fin.data["content"] == "bb"))

    # ③ 检查命中 → 跳过打分
    calls = []
    def bad_chart(st):
        return Verdict("has_charts", "没画图") if "图" not in st.content else None
    async def counting(st):
        calls.append(st.round)
        return Evaluation({"d": Score(2)}, "complete")
    h = Hooks(["无", "无", "无"])
    st = State(Mode("t", checks=(bad_chart,)))
    evs = await drive(st, h, counting)
    hits = [e for e in evs if e.data.get("name") == "check_hit"]
    ok.append(("③ 检查命中跳过打分", len(hits) == 3 and calls == []))

    # ④ auto-fix：修好了就不打回
    import re
    def needs_fix(st):
        """标题层级过浅：整体下沉一级。修法唯一，不需要语义判断。"""
        return Verdict("fmt", "标题太浅",
                       fix=lambda s: re.sub(r"^(#{1,5})(\s)", r"#\1\2", s, flags=re.M)) \
            if re.search(r"^#{1,2}\s", st.content, re.M) else None
    h = Hooks(["## 标题"])
    st = State(Mode("t", checks=(needs_fix,), max_rounds=1))
    evs = await drive(st, h, evaluator([[2]]))
    ok.append(("④ auto-fix 修好后不打回",
               st.content == "### 标题" and not any(e.data.get("name") == "check_hit" for e in evs)))

    # ④b fix 没修好 → 回滚，不留副作用
    def bad_fix(st):
        return Verdict("fmt", "改不好", fix=lambda s: s + "（乱改）") \
            if "坏" in st.content else None
    h = Hooks(["坏内容"])
    st = State(Mode("t", checks=(bad_fix,), max_rounds=1))
    evs = await drive(st, h, evaluator([[2]]))
    ok.append(("④b fix 没修好就回滚",
               st.content == "坏内容"
               and any(e.data.get("name") == "check_hit" for e in evs)))

    # ⑤ middleware 抛异常：隔离，不炸整个 run
    h = Hooks(["a"])
    st = State(Mode("t", extra_mw=(Boom(),), max_rounds=1))
    evs = await drive(st, h, evaluator([[2]]))
    warn = [e for e in evs if e.data.get("name") == "warning"]
    ok.append(("⑤ middleware 异常被隔离",
               len(warn) == 1 and warn[0].data["value"]["middleware"] == "boom"
               and any(e.type == "RUN_FINISHED" for e in evs)))

    # ⑥ 取消：已有内容仍然落盘
    class Cancels(Hooks):
        async def produce(self, st):
            async for p in super().produce(st): yield p
            st.disconnected = True                 # 第 1 轮写完就断
    h = Cancels(["写了一半", "x", "y"])
    st = State(Mode("t"))
    try:
        await drive(st, h, evaluator([[1],[1],[1]]))
    except asyncio.CancelledError:
        pass
    ok.append(("⑥ 取消后已有内容落盘", h.saved == ["写了一半"]))

    # ⑦ Facts：累积 + 压缩绑死，有上限
    h = Hooks(["a"] * 8)
    st = State(Mode("t", max_rounds=8, fact_budget=3))
    await drive(st, h, evaluator([[1]] * 8))
    ok.append(("⑦ 材料累积且有上限", len(st.facts) == 3 and st.facts[-1] == "事实8"))

    # ⑧ wrap：取材料失败时重试（DSPy fail_count / 我们的"工具失败退回检索"）
    tries = []
    class Retry:
        name = "retry"
        async def wrap_prepare(self, st, handler):
            for i in range(3):
                r = await handler(st)
                tries.append(i)
                if r[0]: return r           # 查到了就收工
            return ([], None)               # 三次都空，放弃
    class Flaky(Hooks):
        def __init__(self, texts): super().__init__(texts); self.n = 0
        async def prepare(self, st):
            self.n += 1
            return ([f"第{self.n}次才查到"], None) if self.n >= 2 else ([], None)
    h = Flaky(["a"])
    st = State(Mode("t", extra_mw=(Retry(),), max_rounds=1))
    await drive(st, h, evaluator([[2]]))
    ok.append(("⑧ wrap 能重试 handler", tries == [0, 1] and st.facts == ["第2次才查到"]))

    # ⑨ wrap：短路（不调 handler，直接给结果）
    class Short:
        name = "short"
        async def wrap_prepare(self, st, handler):
            return (["缓存命中"], None)      # 根本不调 handler
    class Never(Hooks):
        async def prepare(self, st): raise AssertionError("不该被调到")
    h = Never(["a"])
    st = State(Mode("t", extra_mw=(Short(),), max_rounds=1))
    await drive(st, h, evaluator([[2]]))
    ok.append(("⑨ wrap 能短路", st.facts == ["缓存命中"]))

    # ⑩ 多个 wrap 洋葱嵌套：第一个包住其余
    order = []
    def mk(tag):
        class W:
            name = tag
            async def wrap_prepare(self, st, handler):
                order.append(f"{tag}-in")
                r = await handler(st)
                order.append(f"{tag}-out")
                return r
        return W()
    h = Hooks(["a"])
    st = State(Mode("t", extra_mw=(mk("A"), mk("B")), max_rounds=1))
    await drive(st, h, evaluator([[2]]))
    ok.append(("⑩ 洋葱：第一个包住其余",
               order == ["A-in", "B-in", "B-out", "A-out"]))

    for name, passed in ok:
        print(f"  {'✓' if passed else '✗ 失败'}  {name}")
    print(f"\n{sum(1 for _, p in ok if p)}/{len(ok)} 通过")

asyncio.run(main())
