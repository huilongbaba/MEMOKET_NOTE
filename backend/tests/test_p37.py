"""P37（`docs/TRACELOG-product.md` P37 节）——P35 留下的三个 ❌ 的后端那一半。

  1. 智能续写「写」这一步吐 JSON，整串落进正文（P35 #2）→ `harness/checks/shape.output_not_json`
  2. 「校验」把「模型没按格式答」说成「知识库里没有相关信息」（P35 #3）→ `VerifyOut.checked/unparsed`
  3. 「来龙去脉」把脏内容说成「多半是模型没应答」+「打开设置」（P35 #4）→ `routers/memory.trace`
  4. 「扩展上下文」替模型说「认为不需要补充上下文」（P35 #5）→ `EditOut.unparsed`

每条断言的量程写在 docstring 里（撤掉哪一行它红）。
**每一条修法都配一条「真的接上了」的断言**——函数对了但没接上，规则层的单测一条
都抓不住（P32 / P34 / P36 各栽过一次）。
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.harness import modes                                          # noqa: E402
from app.harness.checks import shape                                   # noqa: E402
from app.harness.middleware.checks import Checks                       # noqa: E402
from app.harness.state import State                                    # noqa: E402
from app.harness.tools import ToolContext                              # noqa: E402
from app.harness.types import Dimension, Mode                          # noqa: E402


# ============================ 1. 整段吐 JSON 不许落进正文（P37 #1 / P35 #2）
#
# 素材是 P37 真跑里假模型逐字回的那一串（复现记录在台账 P37 节）：
# 修之前 53 → 169 字、两段整串留在正文里，当轮唯一响过的判据是 `no_echoed_text`
# （它说「这两段重复了」——**指错了地方**）。

DIRTY = '{"text": "（假模型改写）这一段由假模型返回，整串都是 JSON。", "reason": "假模型"}'
SEED = ("这周把众筹页面的文案定稿了，3月12号上线。\n\n"
        "预热名单还差一轮回收，节奏上要不要提前一周开放订阅还没定。")


def _st(checks=(), dims=("factual_grounding", "non_repetition")) -> State:
    mode = Mode(key="t", label="t", skill_scope="test_scope",
                dims=tuple(Dimension(d, "...") for d in dims),
                checks=tuple(checks))
    return State(mode=mode, ctx=ToolContext(user="u", note_id="n"))


def _round_st(fresh: str, content: str, before: str = SEED) -> State:
    st = _st((shape.output_not_json,))
    st.fresh = fresh
    st.content = content
    st.bag["content_at_start"] = before
    return st


def test_判据本身只认整串JSON这一档():
    """跟前端 `editor/blockShape.looksLikeJson` **逐字同一条**：`{…}` / `[…]` 且真能 parse。
    量程：把 `looks_like_json` 里的 `json.loads` 去掉、只看开头那个 `{`，
    「{产品名}…」那一行就红。"""
    assert shape.looks_like_json(DIRTY)
    assert shape.looks_like_json('```json\n{"a": 1}\n```')
    assert shape.looks_like_json('[{"a": 1}]')
    # **误伤那一侧**（P32 的突变验钉着同一条）：正常人话里的花括号不许被拦
    assert not shape.looks_like_json("{产品名} 的定价还没定，先看 {留存}")
    assert not shape.looks_like_json("这周把众筹页面的文案定稿了。")
    assert not shape.looks_like_json('{"text": "没闭合')
    assert not shape.looks_like_json('"就一个字符串"'), "JSON 字面量但不是对象/数组，不算"
    assert not shape.looks_like_json(""), "空产出另有一条路"


def test_撤正文只撤这次跑新写的那几段():
    """用户自己笔记里贴的一段 JSON 不许被这条判据吃掉。
    量程：把 `json_paragraphs` 的 `p not in old` 去掉，这条红。"""
    mine = '```json\n{"这是": "用户自己贴的"}\n```'
    content = f"{mine}\n\n{DIRTY}"
    assert shape.json_paragraphs(content, before=mine) == [DIRTY]
    assert shape.drop_json_paragraphs(content, before=mine) == mine
    # 不给 before 就什么都不排除——只用在单测里，真跑一定给得出来
    assert len(shape.json_paragraphs(content)) == 2


def test_判据在这一轮的产出上开火而不是整篇():
    """量程是 `st.fresh`，不是整篇正文。拿整篇判的话，用户笔记里那段 JSON 会让它
    每一轮都响，而模型一个字都改不动——第 601 轮 `no_placeholder` 那次死锁的形状。
    量程：把 `output_not_json` 里的 `st.fresh` 改成 `st.content`，这条红。"""
    st = _round_st(fresh="这一轮写的是正常人话。", content=f'{{"旧的": "JSON"}}\n\n这一轮写的是正常人话。',
                   before='{"旧的": "JSON"}')
    assert shape.output_not_json(st) is None


def test_命中时三样东西一起给():
    """`fix`（把它从正文里摘掉）+ `fix_done`（说「我管的那件事好了」）+ `fix_note`（一句人话）。
    三样缺一样，`middleware/checks.py` 走的就是另一条路：
      · 没 `fix` → 正文留着那串 JSON；
      · 没 `fix_done` → 摘完的正文被整个丢掉（P23 #1 那条）；
      · 没 `fix_note` → 静默改正文（P26 #3 那条）。
    量程：把 `Verdict(...)` 里任意一个参数删掉，这条红。"""
    st = _round_st(DIRTY, f"{SEED}\n\n{DIRTY}")
    v = shape.output_not_json(st)
    assert v is not None
    assert v.fix is not None and v.fix_done is not None and v.fix_note.strip()
    fixed = v.fix(st.content)
    assert DIRTY not in fixed and fixed.strip() == SEED.strip()
    assert v.fix_done(fixed) is True
    # 下一轮读到的就是这句：得说清「重写」，不然 steer 是句废话
    assert "重写" in v.message and "JSON" in v.message


def test_落在兜底桶上而不是某个内容维度():
    """形状是机械缺陷。落在 `factual_grounding` / `coherence` 上会被 `Repair` 读成
    「这一轮只修不写」，而这条判据要的恰恰是**下一轮重新写一遍**。
    量程：把 `pick_dimension(st, "mechanics")` 改成 `pick_dimension(st, "coherence")`，
    在带 coherence 维度的模式下这条红。"""
    from app.harness.checks.pick import MECHANICS
    st = _round_st(DIRTY, f"{SEED}\n\n{DIRTY}")
    st.mode = dataclasses.replace(st.mode, dims=tuple(
        Dimension(d, "...") for d in ("coherence", "factual_grounding")))
    v = shape.output_not_json(st)
    assert v is not None and v.dimension == MECHANICS
    from app.harness.middleware.repair import INNER_QUALITY
    assert MECHANICS not in INNER_QUALITY


# ----------------------------------------------------------------- 接线（P37 #1）

def test_接线_两个长文模式真的挂了这条判据():
    """**函数对了但没接上，上面每一条都照样绿。** 这条数的是「它在不在 `Mode.checks` 里」。
    量程：把 `modes.NOTE.checks` 里的 `output_not_json` 删掉，这条红。"""
    assert shape.output_not_json in modes.NOTE.checks, "智能续写这条路没挂上，P35 #2 原样还在"
    assert shape.output_not_json in modes.SECTION.checks, "分段写作是同一条流式路径"


def test_接线_它排在所有判据最前面():
    """整段是一串 JSON 的时候，后面每一条说的都是它的副作用——P37 复现实拍里唯一响过的
    是 `no_echoed_text`（「这两段重复了」）。而且它前面那几条会去自动修一串本来就不该
    落地的 JSON。
    量程：把它挪到 `no_foreign_script` 后面，这条红。"""
    for mode in (modes.NOTE, modes.SECTION):
        assert mode.checks[0] is shape.output_not_json, mode.key


@pytest.mark.anyio
async def test_接线_跑一轮真的把正文改回去了并且短路了打分():
    """**这一条是 P37 #1 的正题**，走的是真的 `Checks.before_judge`：
    正文回到开跑那版、⚑ 事件发出去、`st.ev` 被换成短路那份（于是 `State.steer` 有话说）。
    量程：把 `Verdict.fix_done` 那一行删掉，正文就被整个丢回 JSON 那版，这条红。"""
    st = _round_st(DIRTY, f"{SEED}\n\n{DIRTY}")
    st.bag["check_name_streak_prev"] = {}
    st.round = 1
    evs = [e async for e in Checks().before_judge(st)]
    assert st.content.strip() == SEED.strip(), "这一轮的产出不许落进正文"
    assert st.skip_judge is True, "判据已经知道答案了，不许再花一次打分调用"
    assert st.ev is not None and "JSON" in st.ev.scores[st.ev.weakest].note
    hits = [e.data["value"] for e in evs if (e.data or {}).get("name") == "check_hit"]
    assert [h["check"] for h in hits] == ["output_not_json", "output_not_json"]
    assert any(h.get("auto_fixed") for h in hits), "动了正文就得说一句（P26 #3）"
    # `State.steer` 就是下一轮 prompt 里那句「上一轮的问题，这一轮要解决」
    st.bag["focus"], st.bag["focus_note"] = st.ev.weakest, st.ev.scores[st.ev.weakest].note
    assert "重写" in st.steer


@pytest.mark.anyio
async def test_接线_正常产出照样落进正文():
    """**误伤那一侧**（P35 那句「闸没有把正常产出拦下来」的单测版）。
    量程：把 `looks_like_json` 放宽成「开头是 `{`」，这条红。"""
    normal = "众筹页面的文案这一周定稿，主视觉和三段文案都对齐了发布节奏。"
    st = _round_st(normal, f"{SEED}\n\n{normal}")
    st.bag["check_name_streak_prev"] = {}
    evs = [e async for e in Checks().before_judge(st)]
    assert st.content == f"{SEED}\n\n{normal}", "正常产出一个字都不许动"
    assert not [e for e in evs if (e.data or {}).get("name") == "check_hit"]
    assert st.skip_judge is False


# ==================== 2 / 4. 空手而归的三种来历，得分得开（P37 #2 #4 / P35 #3 #5）

def test_verify的三档在schema里分得开():
    """`VerifyOut` 原来只有 `findings`——空列表同时表示「没查到」「查到了没话说」
    「模型没按格式答」三件事，前端只能说其中一句，而 P35 实拍它说的是假话。
    量程：把 `VerifyOut` 的 `checked` / `unparsed` 删掉，这条红。"""
    from app.routers.schemas import VerifyOut
    f = VerifyOut.model_fields
    assert "checked" in f and "unparsed" in f
    # 老前端 / 老后端对得上：两格都有缺省
    assert VerifyOut(findings=[], took_ms=1.0).checked == 0
    assert VerifyOut(findings=[], took_ms=1.0).unparsed is False


def test_editout多一格说清模型没按格式答():
    """量程：把 `EditOut.unparsed` 删掉，这条红。"""
    from app.routers.schemas import EditOut
    assert "unparsed" in EditOut.model_fields
    assert EditOut(revisions=[], took_ms=1.0).unparsed is False


def test_抽不出建议的判据只看键在不在():
    """**`{"before": "", "after": ""}` 是模型按格式答的「两个方向都不用补」**
    （`EXPAND_SYSTEM` 明写着这条路），把它算成「没答上来」等于换个方向替模型说谎。
    量程：把 `_unparsed` 改成看值非空，第三条断言红。"""
    from app.routers.compose import _unparsed
    assert _unparsed("当然可以！以下是改写后的内容：…", "text") is True, "散文档：抽不出"
    assert _unparsed({"result": "x", "why": "y"}, "text") is True, "错键档：抽不出"
    assert _unparsed({"before": "", "after": ""}, "before", "after") is False, \
        "模型真的说了「不用补」——这一档不许算成没答上来"
    assert _unparsed({"text": "改好的一段"}, "text") is False
    assert _unparsed(["不是对象"], "text") is True


# ----------------------------------------------------------------- 接线（P37 #2 / #4）

def test_接线_verify那一支真的把两格填上了():
    """**函数对了但没接上**：`compose.verify` 的 `return` 少填一格，上面那条 schema
    断言照样绿。这条读源码钉住那一行真的传了。
    量程：把 `return VerifyOut(...)` 里的 `checked=len(facts)` 删掉，这条红。"""
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "app/routers/compose.py").read_text(encoding="utf-8")
    body = src.split('@router.post("/verify"', 1)[1]
    assert "checked=len(facts)" in body and "unparsed=unparsed" in body
    # 判据本身也钉一下：空列表 `[]` 是正当答案，不算「没按格式答」
    assert "bool(parsed) and not findings" in body


def test_接线_rewrite和expand两支都填了unparsed():
    """量程：把任意一支的 `unparsed=_unparsed(...)` 删掉，这条红。"""
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "app/routers/compose.py").read_text(encoding="utf-8")
    assert src.count("unparsed=_unparsed(") == 2, "重写 / 扩展上下文两支都得填"
    assert '_unparsed(parsed, "text")' in src
    assert '_unparsed(parsed, "before", "after")' in src


# ======================= 3. 「答得不合形状」≠「没应答」（P37 #3 / P35 #4）

def test_trace把no_JSON单独接成502():
    """KITE 的 `llm_json` 抛 `ProviderError("no JSON in llm output: …")`，原来**没人接**，
    500 原样透出去 → 前端说「多半是模型没应答」+「打开设置」，而供应商明明是通的。
    量程：把 `routers/memory.py` 里 `except ProviderError` 那一段删掉，这条红。"""
    from fastapi import HTTPException
    from memoket_kite.errors import ProviderError

    from app.routers import memory as memory_router
    from app.routers.schemas import TraceIn

    class _Mem:
        def __init__(self, *a, **kw):
            pass

        def ask(self, *a, **kw):
            raise ProviderError("no JSON in llm output: 当然可以！以下是这段内容的来龙去脉：…")

    real_mem, real_has = memory_router.UserMemory, memory_router._has_facts
    memory_router.UserMemory = _Mem                     # type: ignore[assignment]
    memory_router._has_facts = lambda _m: True          # type: ignore[assignment]
    try:
        with pytest.raises(HTTPException) as got:
            memory_router.trace(TraceIn(passage="5G切换2.4G带来约一至两周"), user="u")
    finally:
        memory_router.UserMemory = real_mem             # type: ignore[assignment]
        memory_router._has_facts = real_has             # type: ignore[assignment]
    assert got.value.status_code == 502
    detail = got.value.detail
    assert "不是没应答" in detail
    # **不许再指去设置页**：那是「连不上」那一档的出口，不是这一档的
    assert "设置" not in detail and "供应商是通的" in detail
    # 前端 `isLlmUnreachable` 认的是开头那几个词——这句一个都不许撞上
    for bad in ("模型连不上", "后端处理出错", "模型服务", "模型太久没应答"):
        assert not detail.startswith(bad), bad


def test_trace判据窄_别的ProviderError照旧透出去():
    """连不上 / 超时 / 401 本来就是「模型侧出了事」，「打开设置」对它们是对的出口。
    量程：把 `if "no JSON" not in str(exc): raise` 删掉，这条红。"""
    from memoket_kite.errors import ProviderError

    from app.routers import memory as memory_router
    from app.routers.schemas import TraceIn

    class _Mem:
        def __init__(self, *a, **kw):
            pass

        def ask(self, *a, **kw):
            raise ProviderError("Connection refused")

    real_mem, real_has = memory_router.UserMemory, memory_router._has_facts
    memory_router.UserMemory = _Mem                     # type: ignore[assignment]
    memory_router._has_facts = lambda _m: True          # type: ignore[assignment]
    try:
        with pytest.raises(ProviderError):
            memory_router.trace(TraceIn(passage="随便一段"), user="u")
    finally:
        memory_router.UserMemory = real_mem             # type: ignore[assignment]
        memory_router._has_facts = real_has             # type: ignore[assignment]
