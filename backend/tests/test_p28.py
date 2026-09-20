"""P28（`docs/TRACELOG-product.md` P28 节）。

  1. `tool_calls` 在跑记录里残缺 —— `Provenance` 的游标长在 `st.bag` 上，而每轮新建
     `ToolTrace`（P26 留给下一批 #6）。**这一批最要紧的一条：它是观测性缺陷。**
  2. `relevance.gate` 的三条前置（P26 #5 / 留给下一批 #2）：确定性排序 · context 侧剥编号 ·
     夹逼回填换成另一次检索。**开关照旧默认关。**
  3. `after_judge` 那条 `complete` → `continue` 压制：分母数出来、局面构造出来、闸钉上。
  4. （只量不改，见台账）引用总量 20 → 10 的主因。
  5. 导入预算 3600 秒是拍的 → 按 `avg_chunk_ms × 块数` 算出来。

每条断言的量程写在 docstring 里（撤掉哪一行它红）。
"""

from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.harness.agent_loop import ToolTrace                           # noqa: E402
from app.harness.checks import relevance                               # noqa: E402
from app.harness.checks.grounding import citations_present             # noqa: E402
from app.harness.events import EventType                               # noqa: E402
from app.harness.middleware import BASE                                # noqa: E402
from app.harness.middleware.checks import (                            # noqa: E402
    JUDGE_FLOOR, JUDGE_FLOOR_AFTER_FIRST, Checks)
from app.harness.middleware.provenance import Provenance               # noqa: E402
from app.harness.state import State                                    # noqa: E402
from app.harness.tools import ToolContext                              # noqa: E402
from app.harness.types import (                                        # noqa: E402
    Dimension, DimensionScore, Evaluation, Mode, Verdict)


@pytest.fixture()
def anyio_backend():
    return "asyncio"


def _mode(**kw) -> Mode:
    base = dict(key="t", label="t", skill_scope="test_scope",
                dims=tuple(Dimension(d, "...") for d in
                           ("factual_grounding", "non_repetition")),
                checks=())
    base.update(kw)
    return Mode(**base)


def _st(**kw) -> State:
    st = State(mode=kw.pop("mode", None) or _mode(), ctx=ToolContext(user="u", note_id="n"))
    for k, v in kw.items():
        setattr(st, k, v)
    return st


def _drive(agen) -> list:
    async def go():
        return [e async for e in agen]
    return asyncio.run(go())


def _await(coro):
    return asyncio.run(coro)


def _tool_results(events) -> list[str]:
    return [e.data.get("toolName") for e in events
            if e.type is EventType.TOOL_CALL_RESULT]


def _summary(events) -> dict:
    for e in events:
        if e.type is EventType.CUSTOM and (e.data or {}).get("name") == "round_summary":
            return e.data["value"]
    raise AssertionError("这一轮一条 round_summary 都没发")


def _trace(*names) -> ToolTrace:
    t = ToolTrace()
    for n in names:
        t.calls.append((n, {"topic": n}, f"共 3 条，返回 3 条\n[terrence-1-{n}] 正文"))
    return t


# ============================================== 1. 每一轮的工具调用都要报全（P28 #1）
#
# 原来是 `already = st.bag.setdefault("traced", 0)` / 轮末 `st.bag["traced"] = len(calls)`：
# bag 跨轮活着、trace 每轮新建，于是第 2 轮起切的是**这一轮的尾巴**。
# 整库重放（`<scratch>/p28/m1_replay.py`，逐轮跟 P26 那 5 跑的真事件数 21/21 全同）：
# 1751 发真调用只报出 816 发，漏 53.4%；有调用的 409 轮里 249 轮报错数；175 次跑里 125 次受影响。


def test_第二轮的工具调用一发都不许少():
    """**这一批的正题。** 第 1 轮发 3 发、第 2 轮发 3 发，第 2 轮必须也报 3 发。

    量程：把 `provenance.after_prepare` 的游标改回 `st.bag.setdefault("traced", 0)`
    + 轮末 `st.bag["traced"] = len(...)`，这条红（第 2 轮报 0 发）。"""
    st = _st()
    st.round, st.trace = 1, _trace("a", "b", "c")
    r1 = _tool_results(_drive(Provenance().after_prepare(st)))
    assert r1 == ["a", "b", "c"]

    st.round, st.trace = 2, _trace("d", "e", "f")       # 每轮新建一份，跟生产一样
    r2 = _tool_results(_drive(Provenance().after_prepare(st)))
    assert r2 == ["d", "e", "f"], f"第 2 轮漏了：{r2}"



def test_上一轮发得多这一轮发得少也一发不少():
    """真跑里最常见的形状（`da080ca847cf` r5：上一轮 4 发、这一轮 3 发 → 老代码报 0 发）。
    这条跟上一条不是同一个形状：上一条是「长度相等」，这条是「这一轮更短」，
    老代码在前者报 0、在后者也报 0，但**第三种形状（这一轮更长）它会报出错的那几发**
    ——下面那条专管它。

    量程：同上。"""
    st = _st()
    st.round, st.trace = 1, _trace("a", "b", "c", "d")
    _drive(Provenance().after_prepare(st))
    st.round, st.trace = 2, _trace("x", "y", "z")
    assert _tool_results(_drive(Provenance().after_prepare(st))) == ["x", "y", "z"]



def test_这一轮发得更多时报的也得是自己开头那几发():
    """**老代码在这一档不是「少报」，是「报错了哪几发」**：上一轮 1 发、这一轮 5 发，
    它报的是这一轮的第 2–5 发，第 1 发被当成「上一轮报过了」跳掉。
    用户那块面板于是显示着一轮里的一个残缺子集，而且没有任何提示说少了东西。
    （实测 `e78306202d78` r2 就是这个形状：库里 5 发，事件 4 发。）

    量程：同上。"""
    st = _st()
    st.round, st.trace = 1, _trace("a")
    _drive(Provenance().after_prepare(st))
    st.round, st.trace = 2, _trace("p", "q", "r", "s", "t")
    assert _tool_results(_drive(Provenance().after_prepare(st))) == ["p", "q", "r", "s", "t"]



def test_同一份trace不会被报两遍():
    """游标本身不是多余的：一轮里 `after_prepare` 要是被调两次（`wrap_prepare` 重试），
    已经报过的那几发不许再发一遍——AG-UI 那一侧是按事件追加的，重发等于面板上出现两份。

    量程：把 `st.trace.reported = len(st.trace.calls)` 那行删掉，这条红。"""
    st = _st()
    st.round, st.trace = 1, _trace("a", "b")
    assert _tool_results(_drive(Provenance().after_prepare(st))) == ["a", "b"]
    assert _tool_results(_drive(Provenance().after_prepare(st))) == [], "同一份 trace 报过就别再报"



def test_补图那一轮合进来的那几发也要报出去():
    """`hooks/block.prepare` 第二次工具循环走的是 `trace.merge(trace2)`——
    合进来的调用追加在 `calls` 尾部，游标不动，所以它们照样会被报出去。
    **游标放 bag 里的时候这件事是碰运气的**（要看上一轮发了几发）。

    量程：把 `ToolTrace.reported` 的声明删掉改回 bag，这条红。"""
    st = _st()
    st.round, st.trace = 1, _trace("a")
    assert _tool_results(_drive(Provenance().after_prepare(st))) == ["a"]
    st.trace.merge(_trace("b", "c"))
    assert _tool_results(_drive(Provenance().after_prepare(st))) == ["b", "c"]



def test_轮次摘要里要有这一轮真发了几发():
    """**事件的分母**（§21「落库加一列之后要问它的每个取值都真写得进去吗」）。
    P28 之前跑记录里只有事件、没有任何一个数说「本该有几条」，于是这个 bug
    漏了 13 批没人看见，P26 想数材料只能绕过去量。两个数对不上 = 事件漏了。

    取值表逐个构造（不是往 bag 里塞值）：
      · 有 trace、发了 N 发 → N
      · 有 trace、一发没发（打磨轮 / 只清理轮 / AGENT_TOOLS 关着）→ 0
      · 压根没有 trace（`State.trace` 默认 `None`）→ 也是 0，不是省略这个键

    量程：把 `round_summary` 里 `"tool_calls": …` 那一行删掉，这条红。"""
    st = _st()
    st.round, st.trace = 1, _trace("a", "b", "c")
    assert _summary(_drive(Provenance().after_prepare(st)))["tool_calls"] == 3

    st2 = _st()
    st2.round, st2.trace = 1, ToolTrace()               # 有 trace、零调用
    s2 = _summary(_drive(Provenance().after_prepare(st2)))
    assert s2["tool_calls"] == 0 and "tool_calls" in s2

    st3 = _st()
    st3.round = 1                                       # trace 是 None
    s3 = _summary(_drive(Provenance().after_prepare(st3)))
    assert s3["tool_calls"] == 0 and "tool_calls" in s3, "这一档也得写得出来，不能省略键"



def test_报出去的条数跟摘要里那个数永远对得上():
    """这两个数由**同一份 `calls`** 算出来，所以它们对不上只能是游标错了。
    这条是上面所有形状的总闸：三轮，每轮的事件条数 == 那一轮摘要里的 `tool_calls`。

    量程：把游标改回 bag，这条在第 2 轮红。"""
    st = _st()
    for rd, names in ((1, ("a", "b")), (2, ("c", "d", "e")), (3, ("f",))):
        st.round, st.trace = rd, _trace(*names)
        evs = _drive(Provenance().after_prepare(st))
        assert len(_tool_results(evs)) == _summary(evs)["tool_calls"] == len(names), \
            f"第 {rd} 轮：事件 {len(_tool_results(evs))} 条、摘要说 {_summary(evs)['tool_calls']} 发"


# ======================================= 2. relevance.gate 的三条前置（P28 #2，开关照旧关）

_CTX = "网页文案 交付节点 明确文案 设计 程序员"


def _sampled(n: int, bodies: list[str]) -> tuple[list[str], list]:
    """一批「从 >1000 条的主题里抽样回来」的材料 —— `sampled_ids` 认的就是这个返回头。"""
    lines = [f"[terrence-2046-12F{i}] {b}" for i, b in enumerate(bodies, start=1)]
    calls = [("filter_facts", {"topic": "work"}, "共 3167 条，返回 15 条\n" + "\n".join(lines))]
    return lines, calls


def test_夹逼回填的顺序不许跟着PYTHONHASHSEED走():
    """**P26 留给下一批 #2 的第一条，也是任何 A/B 的前置。**

    候选的 `scored` 全是 0（它们正是因为零重合才被剔的），只按 `-scored[i]` 排
    等于按 `set` 的迭代序。实测（`<scratch>/p28/m2_gate.py`，`facts_irrelevant`
    跟 P26 跑记录 5/5 全同）：同一篇 `3a3a96354546` r1，seed 0 塞回
    `{12F2, 12F8}`、seed 1 `{8F6, 12F8}`、seed 2 `{8F6, 12F9}` —— 三个 seed
    三套不同的 prompt。

    **hash seed 只能在进程启动时定**，所以这条闸真的起子进程，跟 P26 / P28 量它的
    办法一样（`<scratch>/p28/seedprobe.py` 先验过：这 6 个 id 在 8 个 seed 下
    有 **8 种不同的 `set` 迭代序**，所以撤掉修复它一定红，不是碰运气）。

    量程：把排序键的第二项（`order.get(i, …)`）删掉，这条红。"""
    got = {_gate_under_seed(s) for s in ("0", "1", "2", "7")}
    assert len(got) == 1, f"换个 PYTHONHASHSEED 塞回来的就换了一批：{got}"


_SEED_SNIPPET = r'''
import sys
sys.path.insert(0, %r)
from app.harness.checks import relevance
bodies = ["EVT 准备 4 台主机", "T0 基本要到 5 月 15 号", "4 月 16 号的 EVT 是纯主机的",
          "包装尚未进入这一节点", "手表手环还是手板", "机甲项链还是手板"]
facts = ["[terrence-2046-12F%%d] %%s" %% (i, b) for i, b in enumerate(bodies, start=1)]
calls = [("filter_facts", {"topic": "work"}, "共 3167 条，返回 15 条\n" + "\n".join(facts))]
kept, _ = relevance.gate(facts, calls, %r, apply=True, min_kept=3)
print("|".join(kept))
'''


def _gate_under_seed(seed: str) -> str:
    import os
    import subprocess
    root = str(pathlib.Path(__file__).resolve().parent.parent)
    out = subprocess.run([sys.executable, "-c", _SEED_SNIPPET % (root, _CTX)],
                         capture_output=True, text=True,
                         env=dict(os.environ, PYTHONHASHSEED=seed))
    assert out.returncode == 0, out.stderr[-800:]
    return out.stdout.strip()


def test_塞回来的是检索给的次序里靠前的那几条():
    """确定性不等于**说得出理由**：并列时按材料自己在 `facts` 里的位置（检索给的次序）
    补回来，而不是 id 字典序——后者跟「哪条更该留」一点关系都没有。

    量程：把第二个排序键换成 `i`（id 字典序），这条红。"""
    bodies = ["丙丙 EVT", "甲甲 EVT", "乙乙 EVT"]
    facts = ["[terrence-2046-12F9] 丙丙 EVT", "[terrence-2046-12F1] 甲甲 EVT",
             "[terrence-2046-12F5] 乙乙 EVT"]
    calls = [("filter_facts", {"topic": "work"},
              "共 3167 条，返回 15 条\n" + "\n".join(facts))]
    kept, _ = relevance.gate(facts, calls, _CTX, apply=True, min_kept=1)
    assert kept == [facts[0]], f"该留检索排第一那条（12F9），实际 {kept}"


def test_context侧的事实编号要剥掉再抽词元():
    """**P26 留给下一批 #2 的第二条。** 材料那一侧 `fact_body()` 早就剥了，
    context 这一侧一直没剥，于是 `_NUM`（`\\d{2,}`）从 `[terrence-1844-16F2]`
    里抽出 `16`，材料里那句「4 月 16 号…」跟它「重合」就被判成相关留下来。

    实测（`<scratch>/p28/m2_terms.py`，P24 那跑的 `a941efecd390` r1）：context 里
    9 个编号贡献 11 个纯数字词元（`16` / `1844` / `50` / `380`…），**没有一个在
    剥完编号的正文里还出现过**；剥完 would-drop 6 → 10 行，两条「4 月 16 号…」
    的硬件材料不再靠编号活着。

    量程：把 `gate` 里的 `strip_ids(...)` 去掉，这条红。"""
    ctx = "这一年的回顾 [terrence-1844-16F2] 团队怎么走过来的"
    facts = ["[terrence-2046-12F1] 4 月 16 号的 EVT 是纯主机的"]
    calls = [("filter_facts", {"topic": "work"},
              "共 3167 条，返回 15 条\n" + facts[0])]
    _kept, dropped = relevance.gate(facts, calls, ctx, apply=False)
    assert len(dropped) == 1, "「16」是从编号里抽出来的，不该算正文跟它有重合"
    # 反向：正文里**真的**写着 16 的时候，照旧算重合
    _k2, d2 = relevance.gate(facts, calls, "这一年的回顾 4 月 16 号那次", apply=False)
    assert d2 == [], "正文里真有的那个 16 不许跟着一起被剥掉"


def test_剥编号只剥编号那种形状():
    """窄在「方括号里至少三段、段间连字符」上：`[备注]` / `[Note](note://x)` 不许被剥掉，
    否则这道筛会把用户正文里的词也一起抽没。

    量程：把 `_CITE_IN_TEXT` 放宽成 `\\[[^\\]]+\\]`，这条红。"""
    keep = "[备注] 这是 [Note](note://abc123) 的正文 [2026] 年"
    assert relevance.strip_ids(keep) == keep
    assert relevance.strip_ids("前 [terrence-1844-16F2] 后").split() == ["前", "后"]


def test_剔到下限时先再检索一次而不是把刚剔掉的塞回来():
    """**P26 留给下一批 #2 的第三条。** P26 实拍 `e78306202d78` 夹逼拉回 3 条里
    一条是「Speaker D: 对，好理解，」——下限保的是**条数不是可用材料**。
    换成再检索一次：补够了就一条旧的都不塞回去。

    量程：把 `gate` 里那段 `if total - gone_items < min_kept and refill is not None:` 删掉，这条红。"""
    facts, calls = _sampled(3, ["EVT 4 台主机", "T0 5 月 15", "对，好理解，"])
    fresh = ["[terrence-9-1F1] 首页文案要说清交付节点", "[terrence-9-1F2] 设计稿周五给"]
    kept, dropped = relevance.gate(facts, calls, _CTX, apply=True, min_kept=2,
                                   refill=lambda: fresh)
    assert len(dropped) == 3, "该剔的一条都没少剔"
    assert kept == fresh, f"留下的该只有新检索回来的那两条，实际 {kept}"


def test_再检索也空手时才退回旧的兜底():
    """P8b 那条命不能撤：第 1 轮空手 → `material_thin` 弃答，代价比材料脏大。
    所以 `refill` 空手时照旧把刚剔掉的按重合度塞回来（顺序已经确定了）。

    量程：把兜底那个 `for fid in sorted(drop_ids, …)` 循环删掉，这条红。"""
    facts, calls = _sampled(3, ["EVT 4 台主机", "T0 5 月 15", "对，好理解，"])
    kept, _ = relevance.gate(facts, calls, _CTX, apply=True, min_kept=2, refill=lambda: [])
    assert len(kept) == 2, f"空手时还得保住 min_kept 条，实际留了 {len(kept)}"
    kept2, _ = relevance.gate(facts, calls, _CTX, apply=True, min_kept=2, refill=None)
    assert kept2 == kept, "`refill` 没给和它空手，走的该是同一条兜底"


def test_只记不剔那一档一个字都没变():
    """**开关照旧默认关**（P8b 的教训 + 要等 `harness_edits` 的「用户留没留」）。
    `apply=False` 时 `refill` 一次都不许被调用——只记不剔那一档不该花任何检索。

    量程：把 `gate` 里的 `if apply and drop_ids:` 放宽成 `if drop_ids:`
    （= 把 refill 那段挪到 `if apply` 外面），这条红。"""
    from app.harness import params
    assert params.RELEVANCE_FILTER is False, "这一批不许把开关打开"
    called = []
    facts, calls = _sampled(3, ["EVT 4 台主机", "T0 5 月 15", "对，好理解，"])
    kept, dropped = relevance.gate(facts, calls, _CTX, apply=False,
                                   refill=lambda: called.append(1) or [])
    assert kept == facts and len(dropped) == 3
    assert called == [], "只记不剔那一档不许去检索"


def test_prepare里真的把refill接上了():
    """**建了判据不等于用了判据**（§21）：上面那几条测的是 `gate` 这个纯函数，
    生产那一侧有没有把 `refill` 传进去，它们一个字都没在查。

    量程：把 `hooks/note.prepare` 里 `refill=_refill` 那个实参删掉，这条红。"""
    from app.harness.hooks import note as note_hooks
    src = inspect.getsource(note_hooks.NoteHooks.prepare)
    assert "refill=_refill" in src, "gate 的第三条前置没接到生产那条线上"
    assert "_retrieve(" in src.split("def _refill")[1].split("return facts")[0], \
        "_refill 得真去检索一次，不能返回一个空列表充数"


# ================================ 3. after_judge 那条 complete → continue 压制（P28 #3）
#
# **先把分母数出来**（`<scratch>/p28/m3.py`）：这条压制只可能在一种轮上开火——
# 判据命中了、而且这一轮真打了六维分（放行轮 / 卡死轮）。普通命中轮走短路，
# `st.ev` 是伪造的单维 continue。库里带 `fired_checks`（批 27 才加的列）+ ≥5 维分的行：
# **p28data 5 行、主仓 0 行，其中 status=complete 的 0 行**。P26 数的 0/3 是同一件事的子集。

def _release_st(check) -> State:
    """把「判据连响 floor 轮 → 这一轮被放行」这个局面**跑出来**，不是往 bag 里塞键。

    素材是 `citations_present` 真正要的那一份：手上有材料、这一轮写了整整一段
    （≥ `MIN_CITED_ROUND_CHARS`）、正文里一个编号都没有。

    **P58 A 之后这份素材多了一个硬要求：得落在 `located > 0` 那一档。**
    `located == 0` 那两档现在是 `advisory`（报了不短路，`types.Verdict.advisory`），
    永远攒不满 `JUDGE_FLOOR`，这个局面就跑不出来了。所以每一轮的正文里都带一句
    **逐字**抄材料的话（`locate_sources` 能唯一定位到 `terrence-2046-12F1`），
    判据走的是「编号照抄在句末就行」那一档——照旧短路。
    **顺带**：那一档是 P58 量出来 17 批 / 268 轮**一次都没开火过**的三档之一，
    这里等于给它补了一份能跑的素材（假模型造形状）。
    """
    from app.harness.checks.grounding import MIN_CITED_ROUND_CHARS
    st = _st(mode=_mode(checks=(check,)))
    st.facts = ["[terrence-2046-12F1] EVT 准备 4 台主机，15 套 PCBA"]
    # 这一句逐字含着材料里的数字锚，`locate_sources` 定得到它，且只定得到这一条。
    anchored = "这一轮把 EVT 准备 4 台主机，15 套 PCBA 这件事写清楚。"
    for k in range(JUDGE_FLOOR):
        st.round = k + 1
        st.fresh = anchored + f"这一段是第 {k + 1} 轮写的。" + "把节奏讲清楚。" * MIN_CITED_ROUND_CHARS
        st.ev, st.skip_judge = None, False
        evs = _drive(Checks().before_judge(st))
        assert st.skip_judge, f"第 {k + 1} 轮该照旧短路，实际 {[e.data for e in evs]}"
    st.round = JUDGE_FLOOR + 1
    st.fresh = anchored + "这一段是放行轮写的。" + "把节奏讲清楚。" * MIN_CITED_ROUND_CHARS
    st.ev, st.skip_judge = None, False
    _drive(Checks().before_judge(st))
    assert not st.skip_judge, "第 floor+1 轮该放行，让打分器真跑"
    assert st.bag.get("check_released") is True, \
        "这个键得是 before_judge 自己写的（往 bag 里塞一个是在测自己编的局面）"
    return st


def _six_dim(status: str) -> Evaluation:
    """打分器真给的那种：六维、每维一个 level。"""
    dims = ("factual_grounding", "non_repetition", "coherence",
            "structure", "material_use", "readability")
    return Evaluation(scores={d: DimensionScore(level=2, note="够了") for d in dims},
                      status=status, weakest="readability")



def test_判据还在响的时候不许判写完了():
    """**P26 留给下一批 #1：给这条压制一份能证明它在挡什么的素材。**

    局面是跑出来的：真判据 `citations_present`（这一轮写了整段、手上有材料、
    一个编号都没有）连响 `JUDGE_FLOOR` 轮把打分饿死 → 第三轮被放行 → 打分器真跑，
    六维全够、判 `complete`。**代码判据说「一个出处都没有」，而这一档正是产品
    承诺的那一条**（`citations_present` 的 docstring：零引用的产出等于通用 LLM 写的）。
    六维是模型对文字的判断，`citations_present` 是代码对编号的判断，两者互不相干
    ——所以这个局面是真能出现的，只是实测 5 个机会里没出现过。

    量程：把 `Checks.after_judge` 里那两行（`if st.ev … status == "complete"` /
    `st.ev = dataclasses.replace(...)`）删掉，这条红。"""
    st = _release_st(citations_present)
    st.ev = _six_dim("complete")
    _await(Checks().after_judge(st))
    assert st.ev.status == "continue", "判据还在响，就不算写完"
    assert len(st.ev.scores) == 6 and st.ev.scores["factual_grounding"].level == 2, \
        "分数一分都不许动——这一轮的排名照样进 st.best，那正是放行的目的"



def test_没被放行的那一轮complete照旧是complete():
    """反向：这条压制只该在**放行轮**开火。挡住一切的守卫跟没有守卫一样坏
    ——每一轮都压回 continue 的话，这条 harness 就再也停不下来了。

    量程：把 `if not st.bag.pop("check_released", False): return` 那两行删掉，这条红。"""
    st = _st(mode=_mode(checks=()))
    st.ev, st.skip_judge = None, False
    _drive(Checks().before_judge(st))                    # 一条判据都没命中 → 真打分
    assert st.bag.get("check_released") is None
    st.ev = _six_dim("complete")
    _await(Checks().after_judge(st))
    assert st.ev.status == "complete", "没判据在响，写完了就是写完了"



def test_放行标记用完就没了():
    """标记跨轮活着的话，下一轮一个无辜的 `complete` 会被压掉。
    `before_judge` 开头那句 `pop` 是一道保险，这里查的是 `after_judge` 自己那一道。

    量程：把 `after_judge` 里的 `st.bag.pop(…)` 改成 `st.bag.get(…)`，这条红。"""
    st = _release_st(citations_present)
    st.ev = _six_dim("complete")
    _await(Checks().after_judge(st))
    st.ev = _six_dim("complete")
    _await(Checks().after_judge(st))
    assert st.ev.status == "complete", "标记该在第一次用完就没了"


def test_库里那一行记的是压制之前的分():
    """**这条压制唯一的计数口径，而它是靠中间件次序保住的**——`BASE` 里
    `Ledger` 排在 `Checks` 前面，两者都挂 `after_judge`，所以
    `harness_rounds.status` 记的是**压制之前**那个 `complete`。
    于是「库里 (判据命中 + 六维分 + complete) 的行数」= 这条压制开过几次火，
    P28 拿它数出来：分母 5 行、**0 次**（`<scratch>/p28/m3.py`）。

    这不是设计出来的，是次序碰巧给的——所以钉一条闸，免得下一个人对调两者、
    让台账里那个 0 悄悄变成另一件事的 0。
    量程：把 `BASE` 里 `Ledger()` 和 `Checks()` 的次序对调，这条红。"""
    names = [getattr(m, "name", "") for m in BASE]
    assert names.index("ledger") < names.index("checks"), \
        "次序反了：库里 status 记的就成了压制之后的，台账那个 0 得重数"


# ==================================== 5. 导入预算：算出来的，不是拍的（P28 #5）

def test_预算按这一批自己的块数算():
    """P26 #4 自己写着「3600 秒是拍的，等有 `avg_chunk_ms` × 块数再换成算出来的」。
    一个拍死的常数两头都错：412 篇的正常导入（≈ 268 分钟）会被 60 分钟拦腰砍断，
    3 篇的导入卡住了又要等满一小时。

    量程：把 `job_budget_seconds` 里 `n_chunks * store.avg_chunk_ms(...)` 那一行
    换回常数 3600，这条红。"""
    from app.routers import import_sources as imp
    from unittest import mock
    with mock.patch.object(imp, "JOB_BUDGET_SECONDS", None), \
         mock.patch.object(imp.store, "avg_chunk_ms", lambda u: 13000):
        small = imp.job_budget_seconds("u", 6)
        big = imp.job_budget_seconds("u", 1236)
    assert big > small, "块数多的那一批得拿到更长的预算"
    assert big == pytest.approx(1236 * 13 * imp.BUDGET_SLACK), \
        "就是 块数 × avg_chunk_ms × BUDGET_SLACK"
    assert big > 3600, "412 篇 × 3 块的正常导入不许再被 3600 拦腰砍断"


def test_小批有个下限不会被自己的预算拦下():
    """3 篇 × 2 块 × 13 s × 2 = 156 秒——一次网络抖动就到点了。

    量程：把 `max(BUDGET_FLOOR_SECONDS, …)` 里的 `max(...)` 去掉，这条红。"""
    from app.routers import import_sources as imp
    from unittest import mock
    with mock.patch.object(imp, "JOB_BUDGET_SECONDS", None), \
         mock.patch.object(imp.store, "avg_chunk_ms", lambda u: 13000):
        assert imp.job_budget_seconds("u", 6) == imp.BUDGET_FLOOR_SECONDS


def test_环境变量仍然一票否决():
    """部署方设了就按设的走，`0` / 负数 = 不设上限（P26 #4 定的约定，一个字不改）。

    量程：把 `if JOB_BUDGET_SECONDS is not None: return JOB_BUDGET_SECONDS` 删掉，这条红。"""
    from app.routers import import_sources as imp
    from unittest import mock
    with mock.patch.object(imp, "JOB_BUDGET_SECONDS", 120.0):
        assert imp.job_budget_seconds("u", 99999) == 120.0
    with mock.patch.object(imp, "JOB_BUDGET_SECONDS", 0.0):
        assert imp.job_budget_seconds("u", 99999) == 0.0


def test_续跑算的是剩下那几篇():
    """`_land` 自己数 `notes`，所以 `resume_job` 传进来的尾巴拿到的是尾巴的预算。
    由调用方传一个数进来的话，续跑要么拿整批的预算跑一个尾巴（拦不住），
    要么反过来（当场到点）。

    量程：把 `_land` 里 `job_budget_seconds(user, sum(len(_chunks(...))))` 换成
    读模块常量，这条红。"""
    from app.routers import import_sources as imp
    src = inspect.getsource(imp._land)
    assert "job_budget_seconds(user," in src and "_chunks(n.content)" in src, \
        "预算得在 _land 里按这一批的 notes 算"


def test_有历史数据就用历史数据():
    """`store.avg_chunk_ms` 读这个用户最近 5 个任务的每块均值，没跑过才用
    `DEFAULT_CHUNK_MS`。库里实测 9 个任务 11 块：均值 16.8 s、最慢 27.2 s、
    最慢/均值 = 1.62——`BUDGET_SLACK = 2.0` 的余量就是从这儿来的。

    量程：把 `job_budget_seconds` 里的 `store.avg_chunk_ms(user)` 换成
    `store.DEFAULT_CHUNK_MS`，这条红。"""
    from app.routers import import_sources as imp
    from unittest import mock
    with mock.patch.object(imp, "JOB_BUDGET_SECONDS", None), \
         mock.patch.object(imp.store, "avg_chunk_ms", lambda u: 30000):
        slow = imp.job_budget_seconds("u", 100)
    with mock.patch.object(imp, "JOB_BUDGET_SECONDS", None), \
         mock.patch.object(imp.store, "avg_chunk_ms", lambda u: 5000):
        fast = imp.job_budget_seconds("u", 100)
    assert slow > fast, "这台机器慢，预算就该跟着长"
    assert imp.BUDGET_SLACK >= 1.62, "余量不能小于实测的「最慢一块 / 均值」"
