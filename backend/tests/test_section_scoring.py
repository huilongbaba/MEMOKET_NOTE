"""打分器读的正文：按小节判（计划 4.2 / [LONG] §3）。

`loop._evaluate` 递给 `evaluate()` 的 `content` 从「整篇逐字」换成
「更早的小节用目录行代替 + 后面几节逐字」。理由是 **lost in the middle**：
长上下文里模型对开头和结尾注意得好、中间明显更差（实测掉 30%+），而我们的
正文结构恰好是「第 1 轮的开头 + 第 N 轮的结尾 + 中间夹着第 2–3 轮累积的
重复」——**判据最该看的地方，正是打分器最看不清的地方**。

**理由不是省钱。** 批 16 的受控实验已经量死了：这个端点的前缀缓存按 message
为单位，judge 只有一条 user message、整段每轮重拼，排布和长度买不到一个 token
（命中率恒 0.0%）。

这一份钉四件事：切分本身、三条兜底（短文 / 分不出节 / 压缩不许压大）、
**接线真的接上了**（生产和 bench 走同一个函数），以及**确定性判据照旧看整篇**
——后面这一条是整个取舍能成立的前提。
"""

from __future__ import annotations

import asyncio

from app.harness import loop, modes, score_context
from app.harness.agent_loop import ToolTrace
from app.harness.state import State
from app.harness.tools import ToolContext

# 填充小节**自己的段内查重比例必须是 0**，不然这份 fixture 量的是它自己而不是
# 被植入的那几句。前两版都栽在这上面：「这一节写了很多内容。」×100 是 0.96，
# 换成「第 n 节的第 i 句…」还是 0.96，再换成十个模板轮着填仍然有 0.62
# ——`restated_ratio` 比的是**字面**相似度，同模板换词的两句能到 0.8。
# 突变验两次都当场露馅（把判据改成只看切过那一份，全套一条没红）。
#
# 治本的办法不是把句子写得更不一样，是**让每一段只有一句话**：段内查重按段
# 分组，一段一句就根本配不出句对。判据要抓的那个形状（同一段里说了两遍）
# 于是只可能来自下面故意植入的那一段。
# *造语料的时候，「看起来像正文」和「统计性质像正文」是两件事。*
_WORDS = ("排期 预算 样机 结构 电池 通信 渠道 报价 验收 固件 模具 包装 物流 售后 "
          "定价 投放 转化 留存 复购 退款 合规 授权 认证 良率 产能 备料 关务 汇率 "
          "选型 调优 灰度 回滚 埋点 告警 巡检 演练 复盘 归因 拆解 对齐").split()


def _section(n: int) -> str:
    """一节填充正文：**一段一句**，所以这一节自己的段内查重比例恒为 0。"""
    paras = [f"关于{_WORDS[(n * 7 + i * 3) % len(_WORDS)]}，"
             f"{_WORDS[(n * 11 + i * 5 + 1) % len(_WORDS)]}那一侧的结论要等"
             f"{_WORDS[(n * 13 + i * 7 + 2) % len(_WORDS)]}落定之后才写得下来。"
             for i in range(20)]
    return f"## 第 {n} 节 · 标题{n}\n\n" + "\n\n".join(paras) + "\n"


LONG = "".join(_section(i) for i in range(1, 9))      # 8 节、约 6800 字


def test_短文一字不动():
    """对一篇 2000 字的笔记来说，目录只是噪声。"""
    short = _section(1) + _section(2)
    assert len(short) < 4000, len(short)
    assert score_context.body_for_scoring(short, keep_last_chars=4000) == short


def test_长文把更早的小节换成目录行():
    body = score_context.body_for_scoring(LONG, keep_last_chars=4000)
    assert body != LONG and len(body) < len(LONG)
    # 目录行：标题 + 第一句 + 字数
    assert "第 1 节 · 标题1" in body and "（" in body
    # 最后几节必须逐字——**这一轮写的东西不能只剩一行目录**
    assert _section(8).strip() in body
    # 而被换成目录行的那几节，正文不再逐字出现
    assert body.count("那一侧的结论要等") < LONG.count("那一侧的结论要等")


def test_分不出小节就退回原文():
    """几千字一整块（真库上 `715266c1fcb4` 就是这样，26714 字 0 个 `##`）。
    这时候目录只有一行，等于没有目录，而正文一个字都省不掉——
    **退回原文比硬切诚实**。"""
    blob = "没有任何标题的一大段。" * 600
    assert len(blob) > 4000
    assert score_context.body_for_scoring(blob, keep_last_chars=4000) == blob


def test_压缩不许把东西压大():
    """`sections.content_for_continue` 撞出来的那一条：真库上
    `92d07b760f1e` 正文 4889 字 17 节，`keep_last=4000` 之下逐字尾巴几乎是
    整篇，再加 17 行目录反而多花 600 字。"""
    # **fixture 得真的踩到那条兜底**（第一版没踩到，突变验当场露馅）：小节要多到
    # 逐字尾巴装不下（于是真的有小节被换成目录行），而每一节又短到「一行目录
    # 比那一节原文还长」。真库上 `92d07b760f1e` 就是这个形状：4889 字 17 节。
    many = "".join(f"## 第 {i} 节 · 一个长得过分的小节标题用来把目录行撑大{i}\n\n短。\n"
                   for i in range(1, 200))
    out = score_context.body_for_scoring(many, keep_last_chars=4000)
    # 先确认这个 fixture 真的走到了拼目录那一步
    sections = __import__("app.harness.middleware.sections", fromlist=["x"]).split_sections(many)
    assert len(sections) > 100 and len(many) > 4000
    assert len(out) <= len(many), "压缩把东西压大了"
    assert out == many, "拼出来比原文还长时必须原样退回原文"


def test_全都逐字给得下时不加目录():
    """阈值放得比正文还宽的时候，目录是纯开销。"""
    assert score_context.body_for_scoring(LONG, keep_last_chars=99999) == LONG


def test_开关关掉就是批19之前一字不差(monkeypatch):
    monkeypatch.setattr(score_context, "SECTION_SCORING", False)
    assert score_context.body_for_scoring(LONG, keep_last_chars=4000) == LONG


def test_生产真的走了这个函数(monkeypatch):
    """**建了判据不等于用了判据。** 这条盯的是接线：`loop._evaluate` 递给
    `evaluate()` 的 `content` 必须是切过的那一份，不是 `st.content`。

    词法查不住这一档（`body_for_scoring` 的名字出现在 `loop.py` 里就算绿了，
    而它可能被拼在别的地方），所以拦一次真的调用，把 `content=` 读出来。
    """
    seen: dict = {}

    async def fake_evaluate(_llm, **kw):
        seen.update(kw)
        from app.harness.types import DimensionScore, Evaluation
        return Evaluation(scores={"coherence": DimensionScore(2, "")},
                          status="complete")

    monkeypatch.setattr(loop, "evaluate", fake_evaluate)
    st = State(mode=modes.for_run(modes.NOTE), ctx=ToolContext(user="u", note_id="n"))
    st.content = LONG
    st.trace = ToolTrace()
    asyncio.run(loop._evaluate(st))
    assert seen["content"] != LONG, "打分器还是在读整篇"
    assert seen["content"] == score_context.body_for_scoring(
        LONG, keep_last_chars=modes.NOTE.context_keep_last)


def test_确定性判据照旧看整篇():
    """**这条是整个取舍能成立的前提。**

    交给模型的那一份变短了，中间那几节没有因此变成盲区——段内查重、
    跨段查重、引用比对这几条一律读 `st.content`（整篇）。铁律原话：
    **能用代码判准的，不交给模型**。

    盯法是行为的不是词法的：把重复植在**最靠前那一节**（正是会被目录行
    代替掉的位置），判据必须照样抓到。
    """
    from app.harness.checks.structure import no_restated_paragraph

    # **重复要落在「既被目录行代替、又不会被目录行那句提示带出来」的位置**
    # ——第一版把它放在第 1 节的**第一句**上，而目录行恰好会摘那一节的第一句
    # （`score_context._first_line`，60 字），于是切过的那一份里重复还在，
    # 判据照样命中，突变验一声不吭。所以引子要长过那 60 字。
    dup = ("这句话会被原样再说一遍，用来验证段内查重看的到底是整篇正文，还是那份已经"
           "被目录行换掉了一半的、只交给打分器看的短正文。")
    lead = ("这一节先写了一段完全正常的引子，里面没有任何重复，它的作用只是把后面那几句"
            "重复推到目录行摘不到的位置上去，免得这条测试自己骗自己。")
    assert len(lead) > 60
    poisoned = ("## 第 1 节 · 开头\n\n" + lead + dup * 4 + "\n\n"
                + "\n\n".join(_section(i) for i in range(2, 9)))
    st = State(mode=modes.for_run(modes.NOTE), ctx=ToolContext(user="u", note_id="n"))
    st.content = st.fresh = poisoned
    st.trace = ToolTrace()
    # 交给打分器的那一份里，第 1 节已经只剩一行目录了
    body = score_context.body_for_scoring(poisoned, keep_last_chars=4000)
    assert body.count(dup) < poisoned.count(dup)
    # 而判据读的是整篇，照样抓得到
    assert no_restated_paragraph(st) is not None


def test_bench和生产共用同一个切分():
    """`as-deployed` 这一列的全部意义就是"跟生产一样"。bench 自己写一份切分
    就又是一处会漂的分支——`split_for_prompt` 当年是同一条纪律。"""
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1]
           / "scripts" / "dimension_sensitivity_bench.py").read_text(encoding="utf-8")
    assert "score_context.body_for_scoring(" in src
    assert "WHOLE_PIECE_CONDITION" in src, "旧行为得留一条可比的对照臂"


def test_bench的格子指纹认的是切过的那一份():
    """**断点续跑会拿旧数据当新数据**——批 7 撞过一模一样的一次
    （`cell_key` 的 docstring 记着）。

    这一批的形状更隐蔽：`as-deployed` 和 `whole-piece` 两档的 `text`
    **一模一样**，交给打分器的东西却完全不同。指纹要是还认 `text`，
    续跑会把「整篇判出来的旧分数」当成「按小节判的新分数」接着用，
    而整张表一声不吭。
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import dimension_sensitivity_bench as bench

    # 挑 `heading_levels` 这一对：它只要求正文里有标题，而这份 fixture 的
    # 每一节都带标题。（`duplicate_paragraph` 要求有够长的段落可复制，
    # 这份填充语料是一段一句，它会直接跳过。）
    note = {"id": "n", "user_id": "u", "title": "t", "content": LONG,
            "spine": "", "beats": None}
    probes = tuple(p for p in bench.PROBES
                   if p.injector == "heading_levels" and p.mode == "note")
    assert len(probes) == 2, "as-deployed / whole-piece 两档都要在"
    tasks, _skips = bench.build_tasks([note], probes, repeats=1, done=set())
    by_cond = {t.probe_id.rsplit("/", 1)[1]: t for t in tasks if t.arm == "clean"}
    assert by_cond["as-deployed"].text == by_cond["whole-piece"].text
    assert by_cond["as-deployed"].body != by_cond["whole-piece"].body
    # **比的是指纹段，不是整串 key**：整串里有 `probe_id`，两档本来就不同，
    # 拿它做断言等于什么都没查（第一版就是这么写的，突变验当场露馅）。
    # 要守的性质是「切过那一份变了，格子就得重跑」。
    fp = lambda task: task.key.rsplit("|", 1)[1]
    assert fp(by_cond["as-deployed"]) != fp(by_cond["whole-piece"]), (
        "两档的格子指纹撞在一起了——续跑会把整篇判的旧分数当成按小节判的新分数")
    assert fp(by_cond["as-deployed"]) == bench.cell_fingerprint(
        by_cond["as-deployed"].body, by_cond["as-deployed"].context)
