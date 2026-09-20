"""P26（`docs/TRACELOG-product.md` P26 节）。

  1. `max_tokens` / `max_completion_tokens`：同一件事仓里有三处在做，P23 只修了看图那处，
     设置页那条纯文字探针还原样发着 `max_tokens=1`。
  3. 判据自己动手那一轮，下一轮的提示里要说一句「上一轮我替你把 X 补上了」。
  4. 导入 job 的整体预算：N 个子任务各有超时，整体没有上限。

每条断言的量程写在 docstring 里（撤掉哪一行它红）。
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import pathlib
import sys
from unittest import mock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.editor import vision                                          # noqa: E402
from app.harness.middleware.checks import (                            # noqa: E402
    JUDGE_FLOOR, JUDGE_FLOOR_AFTER_FIRST, Checks)
from app.harness.state import State                                    # noqa: E402
from app.harness.tools import ToolContext                              # noqa: E402
from app.harness.types import Dimension, Mode, Verdict                 # noqa: E402
from app.routers import settings as settings_router                    # noqa: E402
from app.util import llm                                               # noqa: E402


# ==================================== 1. 端点不收 max_tokens 时，按对方的回话改一次再来

# 真发出去量到的那一份（gpt-5.6-luna @ api.openai.com，P26 #1 实测原文）
REAL_400 = json.dumps({"error": {
    "message": "Unsupported parameter: 'max_tokens' is not supported with this model. "
               "Use 'max_completion_tokens' instead.",
    "type": "invalid_request_error", "param": "max_tokens", "code": "unsupported_parameter",
}}).encode()
REAL_400_OBJ = json.loads(REAL_400)


def test_认得出那个特定的400():
    """量程：把 `rejects_max_tokens` 里 `err.get("param") == "max_tokens"` 改成恒 False，这条红。"""
    assert llm.rejects_max_tokens(400, REAL_400) is True


def test_不吞别的参数的400():
    """同样是 400、同样是「参数不支持」，但说的是别的参数——换字段重试一次
    只会再失败一次，还把真正的错因盖掉。
    量程：把判据放宽成「400 里提到了 max_completion_tokens」（P23 那一版的口径），
    这条红——因为这一份 message 里也带着那个词。"""
    body = json.dumps({"error": {
        "message": "Unsupported value: 'temperature' does not support 0.3 with this model. "
                   "Consider max_completion_tokens instead.",
        "type": "invalid_request_error", "param": "temperature", "code": "unsupported_value",
    }}).encode()
    assert llm.rejects_max_tokens(400, body) is False


def test_网关只回一句白话时退回原话里找():
    """有些网关不回结构化 error。这是 P23 给看图写的那一版的口径，保住它。
    量程：把 `return b"max_completion_tokens" in body` 那一行删掉，这条红。"""
    assert llm.rejects_max_tokens(400, b"use max_completion_tokens instead") is True
    assert llm.rejects_max_tokens(400, b"not json at all") is False


def test_非400一律不算():
    """量程：把 `if status_code != 400` 那一行删掉，这条红。"""
    assert llm.rejects_max_tokens(500, REAL_400) is False
    assert llm.rejects_max_tokens(200, REAL_400) is False


def test_换字段只在真有max_tokens时才算换():
    """没得换还回 True 的话，调用方会做一次一模一样的重试——白花一次调用。
    量程：把 `swap_to_max_completion_tokens` 的 `if "max_tokens" not in payload` 删掉，这条红。"""
    body = {"model": "m", "max_tokens": 7}
    assert llm.swap_to_max_completion_tokens(body) is True
    assert body == {"model": "m", "max_completion_tokens": 7}
    assert llm.swap_to_max_completion_tokens({"model": "m"}) is False


# ---- 两个调用点各守一条：判据对了不等于接上了 ----

class _Resp:
    def __init__(self, code, payload=None, text=""):
        self.status_code, self._payload, self.text = code, payload, text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    @property
    def content(self) -> bytes:
        return json.dumps(self._payload).encode() if self._payload is not None else self.text.encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"没重试就 raise 了：{self.status_code}")


class _ScriptedClient:
    """`/models` 回 404（网关不实现列表），POST 按脚本回。记下每一份发出去的 body。"""

    def __init__(self, codes):
        self.codes, self.sent = list(codes), []

    async def get(self, url, **kw):
        return _Resp(404, text="nope")

    async def post(self, url, json=None, headers=None, **kw):
        self.sent.append(dict(json or {}))
        if self.codes.pop(0) == 400:
            return _Resp(400, REAL_400_OBJ)
        return _Resp(200, {"choices": [{"message": {"content": "hi"}}]})


def test_设置页纯文字探针撞上那个400会换字段再来一次():
    """**这条是 P26 #1 的正题**。这一支只在 `/models` 列不出来时才走到，可一旦走到，
    「测一下」就会对着一份完全正常的配置说「返回 400」——而写作那条路是通的。
    量程：把 `probe_endpoint` 里那两行 `llm.rejects_max_tokens(...)` / 重试删掉，这条红
    （只发一次、拿着 400 回「返回 400」）。"""
    c = _ScriptedClient([400, 200])
    r = asyncio.run(settings_router.probe_endpoint(
        kind="llm", base_url="http://h/v1", model="gpt-5.6-luna", client=c))
    assert r.ok, r.message
    assert len(c.sent) == 2, c.sent
    assert c.sent[0].get("max_tokens") == 1, c.sent[0]
    # 第二份：字段换了，值原样带过去，别的一个字没动
    assert "max_tokens" not in c.sent[1], c.sent[1]
    assert c.sent[1].get("max_completion_tokens") == 1, c.sent[1]
    assert c.sent[1]["model"] == "gpt-5.6-luna" and c.sent[1]["messages"] == c.sent[0]["messages"]


def test_设置页探针不认的400照旧原样报出来():
    """只该吞这一种。别的 400 还得让用户看见原话。
    量程：把判据放宽成「status == 400」，这条红（会重试一次然后说 ok）。"""
    c = _ScriptedClient([400])

    async def post(url, json=None, headers=None, **kw):
        c.sent.append(dict(json or {}))
        return _Resp(400, {"error": {"param": "model", "code": "model_not_found",
                                     "message": "no such model"}})

    c.post = post
    r = asyncio.run(settings_router.probe_endpoint(
        kind="llm", base_url="http://h/v1", model="nope", client=c))
    assert not r.ok and "400" in r.message, r.message
    assert len(c.sent) == 1, c.sent


def test_看图那条路走的是同一个判据():
    """P23 修的是这一处，改成共用判据之后它不能变。
    量程：把 `vision.py` 里那两行重试删掉，这条红。"""
    sent: list[dict] = []

    class _Cli:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            sent.append(dict(json or {}))
            if len(sent) == 1:
                return _Resp(400, REAL_400_OBJ)
            return _Resp(200, {"choices": [{"message": {"content": "42"}}]})

    with mock.patch.object(vision.httpx, "AsyncClient", _Cli), \
         mock.patch.object(vision.store, "get_active_vision_config",
                           lambda: {"base_url": "http://h/v1", "model": "vl", "api_key": "k"}):
        out = asyncio.run(vision.ask_image("读图", b"\x89PNG", max_tokens=24))
    assert out == "42", out
    assert len(sent) == 2, sent
    assert sent[0].get("max_tokens") == 24 and "max_completion_tokens" not in sent[0]
    assert sent[1].get("max_completion_tokens") == 24 and "max_tokens" not in sent[1]
    # 图还在（换的是 token 字段，不是重新拼一份 body）
    assert any(p.get("type") == "image_url" for p in sent[1]["messages"][-1]["content"])


def test_写作那条线一个字都不发max_tokens():
    """**P26 #1 量出来的结论**：`_payload` 那条线（写作 / 打分 / 工具循环全走它）
    本来就统一在 `max_completion_tokens` 上，所以「写作那档看起来是好的」不是因为
    它没传这个参数，而是因为它传的本来就是对的那个。这条把那个结论钉住。
    量程：把 `_payload` 里的字段名改回 `max_tokens`，这条红。

    **P30 #5 之后这条只说 `provider="gpt"` 那一档**（真库里配的正是它）：
    本地那一档现在两个都发——Ollama / LM Studio 只认 `max_tokens`，
    而且不认的字段是安静忽略的，只发 `max_completion_tokens` 等于没有上限
    （假端点实测：要 700 回 4096）。这条守的性质一个字没变：
    **生产那条路一个字节都不多发、一次多余往返都不多**。"""
    with mock.patch.object(llm.store, "get_active_llm_config",
                           lambda: {"base_url": "http://x", "api_key": "k",
                                    "model": "gpt-5.6-luna", "provider": "gpt"}):
        body = llm._payload([{"role": "user", "content": "hi"}], stream=False,
                            max_tokens=100, temperature=0.3, effort="low")
    assert "max_tokens" not in body
    assert llm.rejects_max_tokens(400, REAL_400) and not llm.swap_to_max_completion_tokens(body), \
        "这条线没有 max_tokens 可换，所以它根本走不到那次重试"


# ============================================ 2. 放行的门槛分两段（P26 #2）
#
# 依据是 P24 那 5 跑 30 轮逐轮读出来的（表在 `middleware/checks.py`
# `JUDGE_FLOOR_AFTER_FIRST` 上面）：3 个放行轮，一条也没改变交付轮；
# 唯一有价值的那个（`e78306202d78` r3）价值全在「它是这一跑第一份真分」上。

def _st(checks=(), dims=("factual_grounding", "non_repetition")) -> State:
    mode = Mode(key="t", label="t", skill_scope="test_scope",
                dims=tuple(Dimension(d, "...") for d in dims),
                checks=tuple(checks))
    return State(mode=mode, ctx=ToolContext(user="u", note_id="n"))


async def _round(st: State) -> list:
    st.ev, st.skip_judge = None, False
    return [e async for e in Checks().before_judge(st)]


@pytest.mark.anyio
async def test_两档门槛的数值本身():
    """两段就是两段：没真分之前按 2（P24 量出来的那档，别动），有了之后按 3。
    量程：把 `JUDGE_FLOOR_AFTER_FIRST` 改回 2，下面那条「有过真分之后要饿满三轮」红。"""
    assert JUDGE_FLOOR == 2 and JUDGE_FLOOR_AFTER_FIRST == 3


@pytest.mark.anyio
async def test_还没有真分时第三轮必须放行():
    """**这一条是 P26 #2 不许动的那一半**：`check_stuck` 最早在 r3 停，
    手上一份真分都没有的跑必须在 r3 就拿到一份，否则 `stalled` 只能把最后一轮
    原样交出去——P22 留下率 35% 那一篇就是这么来的。
    量程：把 `floor` 那个三元表达式改成恒 `JUDGE_FLOOR_AFTER_FIRST`，这条红。"""
    msgs = iter(["甲", "乙", "丙", "丁"])
    st = _st([lambda s: Verdict("factual_grounding", next(msgs))])
    for k in range(JUDGE_FLOOR):
        await _round(st)
        assert st.skip_judge, f"第 {k + 1} 轮照旧先判后花钱"
    evs = await _round(st)
    assert not st.skip_judge, "一份真分都还没有，第三轮必须让打分器跑"
    assert evs[-1].data["value"]["judge_floor_bar"] == JUDGE_FLOOR


@pytest.mark.anyio
async def test_有过真分之后要饿满三轮才放行():
    """**这一条是省下来的那两次调用**：`603dca25403a` r4 和 `a941efecd390` r7
    都是这个形状——这一跑早有真分了，放行那一轮的分既没进 `best` 也没改停机。
    量程：把 `floor` 那个三元表达式改成恒 `JUDGE_FLOOR`（= 退回 P24 那版），这条红。"""
    # **每轮换一句**：同一句连报 `STUCK_ROUNDS`(=2) 轮之后走的是「卡死了，不短路」
    # 那一支，测的就不是放行门槛了（P24 那几条用 `iter(["甲","乙"...])` 也是为这个）。
    # `citations_present` 的原话里带着「这一轮写了 N 字」，真跑里本来就每轮都不一样。
    fires = iter([False, True, True, True, True])
    msgs = iter(["甲", "乙", "丙", "丁", "戊"])
    st = _st([lambda s: Verdict("factual_grounding", next(msgs)) if next(fires) else None])
    await _round(st)                                    # r1 没报 → 真打分
    assert st.bag["had_real_judge"] is True, "没报的那一轮就是真打分，得记下来"
    for k in range(JUDGE_FLOOR_AFTER_FIRST):
        await _round(st)
        assert st.skip_judge, f"有过真分了，第 {k + 1} 轮该照旧短路（P24 那版在第 3 轮就放行了）"
    evs = await _round(st)
    assert not st.skip_judge, "饿满三轮，这一轮得放行"
    assert evs[-1].data["value"]["judge_floor_bar"] == JUDGE_FLOOR_AFTER_FIRST


@pytest.mark.anyio
async def test_放行那一轮本身也算有过真分():
    """放行那一支是 `continue` 不是 `return`，走到循环末尾 → 这一轮真打分。
    漏了这一步的话，被放行过的跑会一直按 2 走，等于没改。
    量程：把循环末尾那行 `st.bag["had_real_judge"] = True` 删掉，这条红。"""
    msgs = iter(["甲", "乙", "丙", "丁", "戊", "己", "庚"])
    st = _st([lambda s: Verdict("factual_grounding", next(msgs))])
    for _ in range(JUDGE_FLOOR):
        await _round(st)
    await _round(st)                                    # 放行
    assert not st.skip_judge and st.bag["had_real_judge"] is True
    # 从这里起按 3：连着两轮还得短路
    for _ in range(JUDGE_FLOOR_AFTER_FIRST):
        await _round(st)
        assert st.skip_judge, "放行过一次之后就该按 3 走了"


# ============================== 3. 判据自己动手那一轮，得对模型说一句（P26 #3）
#
# 素材是**真的**：`e78306202d78` 在 p22（那时 `fix` 还不存在）终稿里的那一段，
# 逐字。它在 p22 的 r4/r5/r6 连着三轮原样活着，p24（`fix` 在了）同一篇里两处都没了
# ——动手是真的，而那三轮里模型一句话也没被告知。

P22_PARA = (
    "试点不应从细碎功能清单开始，而应先串起几个大节点。"
    "项目本身包含硬件、嵌入式和 APP，并按 KO、EVT、T0、DVT、PVT、MP 推进；"
    "其中 T0 预计到 5 月 15 日左右，"
    "项目本身包含硬件、嵌入式和 APP，并按 KO、EVT、T0、DVT、PVT、MP 推进；"
    "这一节点划分来自项目原有排期，其中 T0 预计到 5 月 15 日左右，"
    "[terrence-1833-8F6]因此午餐会上应把录后数据流作为独立的 APP/服务侧验证项，"
    "避免把它继续混在硬件节点里。[terrence-1833-8F6]"
)


def _echo_st(content: str) -> State:
    st = _st(dims=("non_repetition", "factual_grounding"))
    st.content = content
    st.bag["content_at_start"] = ""
    return st


# `done_criteria` 那一档的素材原样照 `test_p23.py`（同一份 BODY、同一个 streak=1），
# 免得这条闸测的是「我新编的素材到没到门槛」而不是 `fix_note` 填没填。
_DATED = "4月16日，EVT 进入硬件检查节点：计划 4 台主板 [fact-000000000001-a]。"
_ND1 = "回看这一年，真正被重新确认的不是某一个产品计划，而是一种面对不确定性的工作方式。"
_ND2 = "下一步还需要把“可理解”变成团队可以直接检查的交付物：任何动效提案都要配一段静止演示。"
_BODY = f"{_DATED}\n\n{_ND1}\n\n{_ND2}"


def _date_verdict_with_fix():
    """把 `done_criteria` 驱动到「日期那一侧、连响第 2 轮、有 fix」那一档。"""
    from app.harness.checks.done import done_criteria
    st = State(mode=type("M", (), {"checks": (), "dims": ()})(),       # type: ignore[arg-type]
               ctx=type("C", (), {"intent": "目标：周报；完成标准：每个节点有日期、有出处",
                                  "intent_checked": ()})(),            # type: ignore[arg-type]
               content=_BODY)
    st.bag["content_at_start"] = ""
    st.bag["check_name_streak_prev"] = {"done_criteria": 1}            # 连响第 2 轮
    st.round = 2
    return done_criteria(st)


def test_3_素材真的能让那两条fix开火():
    """**先证明素材到得了门槛**，否则下面测的是门槛不是这条守卫（§21 那条「素材得真的
    过得了门槛」）。这一段是 p22 `e78306202d78` 终稿里的原文，逐字。"""
    from app.harness.checks import blockcheck
    assert blockcheck.echoed_sentence(P22_PARA, "") is not None
    assert (blockcheck.repeated_citation(P22_PARA, "") or ("",))[0] == "terrence-1833-8F6"


def test_3_三处fix全都说得出自己改了什么():
    """**一个信号有几个来源就得逐个数过来**（§21）。这三处每一处都得填 `fix_note`
    ——漏填的那处会退回 P23 那版的静默，而静默正是这一条要修的病。
    量程：把任意一处的 `fix_note=` 删掉，这条红。

    ⚠️ **这条原来的抬头写着「仓里带 `fix` 的判据就这三处」，那句话是假的**（P58 走查 #2）。
    它只构造了自己点名的三处，一次都没去数仓里到底有几处——而 P58 静态扫出来是
    **12 处 `Verdict(... fix=...)`，其中只有 5 处填了 `fix_note`**。
    「逐个数过来」得真的数，数的那条闸在下面 `test_3_仓里每一处fix_note都得是数出来的`。"""
    from app.harness.checks import structure
    seen = {}

    v = structure.no_echoed_text(_echo_st(P22_PARA))
    assert v is not None and v.fix is not None
    seen["句内回声"] = v.fix_note

    # 回声修掉之后，同一条判据接着报同段重编号——第二处 fix
    v2 = structure.no_echoed_text(_echo_st(v.fix(P22_PARA)))
    assert v2 is not None and v2.fix is not None
    seen["同段重编号"] = v2.fix_note

    # 第三处：`done_criteria` 的日期 fix
    v3 = _date_verdict_with_fix()
    assert v3 is not None and v3.fix is not None
    seen["日期待补"] = v3.fix_note

    assert len(seen) == 3, seen
    for name, note in seen.items():
        assert note and note.strip(), f"{name} 这处 fix 说不出自己改了什么"
        # 说的是**做了什么**，不是「哪里错了」——后者是 message 的活
        assert ("删掉" in note or "去掉" in note or "贴了" in note), (name, note)


# **动了正文却一个字不说**的那几处（`Verdict(... fix=...)` 但没有 `fix_note`）。
# 白名单不是「这样是对的」，是「这是今天的实情，别再悄悄多一处」（P58 走查 #2）。
#
# **P59 ② 把它清空了**：P58 留下的那 7 处逐处判过「该不该说」，7 处**全都说得清**，
# 所以 7 条各配了一句 `fix_note`，一条都没留在白名单里。逐处的落点和措辞理由
# 写在各自的源码注释里（`charts.py:120/227`、`grounding.py:182`、
# `language.py:241/258`、`structure.py:85/118`）。
#
# 改之前先量过射程（`<scratch>/p59/silent9.py`，15 批 / 61 份跑 / 284 轮）：
# **这 7 条判据在真跑语料里一次都没响过（0/284）**——唯一真开过火的 `fix` 是
# `no_echoed_text`（响 4 次、其中 3 次走全修那一支），而它本来就有 `fix_note`。
# 所以这一改在已量到的语料上**动不了任何一轮的产出**；它补的是「哪天响了，
# 用户和模型能知道正文被改了什么」这个洞。
#
# 留一个空集合而不是删掉它：下一个加静默 `fix` 的人得在这儿写明理由，
# 下面那条闸会按它的长度对数。
SILENT_FIXES: set[tuple[str, str]] = set()


def test_3_仓里每一处fix_note都得是数出来的():
    """**「逐个数过来」得真的数**（P58 走查 #2）。

    上面那条的抬头原来写着「仓里带 `fix` 的判据就这三处」，而它只构造了自己点名的三处，
    一次都没扫过。静态一扫：`app/harness/checks/**` 里 `Verdict(...)` 带 `fix=` 的有
    **12 处**，填了 `fix_note` 的只有 **5 处**——剩下 7 处动了正文、对模型和用户都不说话，
    正是 P26 #3 要修的那个形状，只是当时没看见它们。

    **P59 ② 把那 7 处配上了措辞**：逐处判过「说不说得清我替你改了什么」，
    7 处全都说得清（各自的理由写在源码注释里），于是 12 处现在**处处都说话**。
    改之前量过射程：`<scratch>/p59/silent9.py` 扫 15 批 / 61 份跑 / 284 轮，
    **这 7 条一次都没响过**，唯一真开过火的 `fix` 是 `no_echoed_text`（4 次 / 3 次全修），
    而它本来就有 `fix_note`——所以这一改在已量到的语料上动不了任何一轮的产出。

    这条闸钉的是**分母**：三个数（12 / 12 / 0）都断言，数对不上就红，
    新加一处静默的 `fix` 当场被抓。

    量程：往任意一条判据上加一个不带 `fix_note` 的 `fix=`，这条红；
    把任意一处的 `fix_note=` 删掉，这条也红。
    """
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app/harness/checks"
    with_fix: list[tuple[str, int, bool]] = []
    for f in sorted(root.glob("*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Verdict":
                kw = {k.arg for k in node.keywords}
                if "fix" in kw:
                    with_fix.append((f.name, node.lineno, "fix_note" in kw))
    spoken = [x for x in with_fix if x[2]]
    silent = [x for x in with_fix if not x[2]]
    assert len(with_fix) == 12, f"带 fix 的 Verdict 变成 {len(with_fix)} 处了：{with_fix}"
    assert len(spoken) == 12, (
        f"填了 fix_note 的从 12 处变成 {len(spoken)} 处了：{spoken}\n"
        f"静默的那几处：{silent}")
    assert len(silent) == len(SILENT_FIXES) == 0, (
        f"静默的 fix 从 {len(SILENT_FIXES)} 处变成 {len(silent)} 处："
        f"{silent}\n新加一处静默的 fix 就得在 SILENT_FIXES 里写明它摘的是什么，"
        f"或者给它配一句 fix_note。")
    assert {x[0] for x in silent} == {n for n, _ in SILENT_FIXES}


# **`fix` 有两条出口，得各测各的**（§21「同一件事挡住一半等于没挡」）。第一版只写了
# 一条，拿 `P22_PARA` 当素材——那一段里回声和重编号同时在，`drop_echo` 修完回声之后
# 判据**接着报重编号**（`again is not None`），走的是 `fix_done` 那一支。于是把全修
# 那一支的两行整个删掉，那条断言照样绿：**它从来没走过那条路**。突变验抓出来的。
# 把段尾那个重复的 `[terrence-1833-8F6]` 去掉就只剩回声，`again` 才是 None。
P22_ECHO_ONLY = P22_PARA.rsplit("[terrence-1833-8F6]", 1)[0]


def test_3_两条出口的素材各自到得了位():
    """先证明两份素材分别走的是哪一支，否则下面两条测的是同一支。
    量程：这条守的是素材本身，`P22_ECHO_ONLY` 的切法改错就红。"""
    from app.harness.checks import blockcheck, structure
    # 全修那一支：修完之后判据整个闭嘴
    v = structure.no_echoed_text(_echo_st(P22_ECHO_ONLY))
    assert v is not None and v.fix is not None
    assert structure.no_echoed_text(_echo_st(v.fix(P22_ECHO_ONLY))) is None, "这份该走全修那一支"
    assert blockcheck.repeated_citation(P22_ECHO_ONLY, "") is None
    # 半修那一支：修完回声还剩重编号
    v2 = structure.no_echoed_text(_echo_st(P22_PARA))
    assert structure.no_echoed_text(_echo_st(v2.fix(P22_PARA))) is not None, "这份该走 fix_done 那一支"


@pytest.mark.anyio
async def test_3_全修那一轮会留下一句给下一轮():
    """**这条是 P26 #3 的正题**：`fix` 全修那一支原来直接 `continue`，
    正文被改了、事件不发、下一轮的提示里也不提。
    量程：把那一支的 `for ev in self._fix_events(...)` 两行删掉，这条红。"""
    from app.harness.checks import structure
    st = _echo_st(P22_ECHO_ONLY)
    st.mode = dataclasses.replace(st.mode, checks=(structure.no_echoed_text,))
    evs = await _round(st)
    assert st.content != P22_ECHO_ONLY, "正文该被改了"
    assert not st.skip_judge, "全修那一支不算命中，不该短路打分"
    assert st.bag["auto_fixes"], "改了正文，就得留一句给下一轮"
    assert any(e.data["value"].get("auto_fixed") for e in evs), "也得发一个事件给用户"
    assert "删掉" in "\n".join(st.bag["auto_fixes"])


@pytest.mark.anyio
async def test_3_半修那一轮也留一句_并且照旧报剩下的():
    """`fix_done` 那一支动了正文、又接着按**剩下没好的那条**报——两件事各说各的。
    量程：把那一支的 `for ev in self._fix_events(...)` 两行删掉，这条红。"""
    from app.harness.checks import structure
    st = _echo_st(P22_PARA)
    st.mode = dataclasses.replace(st.mode, checks=(structure.no_echoed_text,))
    evs = await _round(st)
    assert st.content != P22_PARA, "正文该被改了"
    assert st.bag["auto_fixes"], "改了正文，就得留一句给下一轮"
    said = "\n".join(st.bag["auto_fixes"])
    assert "删掉" in said and "重编号" not in said, said
    # 剩下那条（同段重贴编号）照旧报出来，而且是普通命中、照旧短路
    assert st.skip_judge, "剩下没好的那条还得按老规矩短路"
    hits = [e.data["value"] for e in evs]
    assert any(h.get("auto_fixed") for h in hits), "动手那一条要发 auto_fixed"
    assert any(not h.get("auto_fixed") and "贴了两次" in h.get("note", "") for h in hits), hits


@pytest.mark.anyio
async def test_3_那一句进得了下一轮的提示():
    """留在 bag 里没人读等于没留（§21「建了判据不等于用了判据」）。
    量程：把 `hooks/note.py` 那行 `auto_fixes=st.bag.get("auto_fixes")` 删掉，这条红。"""
    import inspect
    from app.harness.hooks import note as note_hooks
    src = inspect.getsource(note_hooks.NoteHooks)
    assert 'auto_fixes=st.bag.get("auto_fixes")' in src, "续写那一发没把它递进提示"
    from app.harness.prompts.note import note_harness_continue_user
    out = note_harness_continue_user(
        "", [], "正文", [], [], auto_fixes=["把重复抄了一遍的「甲乙丙」删掉了一份（原句留着）"])
    assert "上一轮我替你改了正文" in out and "甲乙丙" in out, out
    assert "别再改回去" in out, "不说这句，模型的默认动作就是把正文恢复成它记得的样子"


def test_3_上一轮没动手就一个字都不说():
    """反向：没改过正文的轮不许平白多出一块。
    量程：把 `auto_fix_block` 的 `if not lines: return ""` 删掉，这条红。"""
    from app.harness.prompts.note import auto_fix_block, note_harness_continue_user
    assert auto_fix_block(None) == "" and auto_fix_block([]) == "" and auto_fix_block([" "]) == ""
    out = note_harness_continue_user("", [], "正文", [], [])
    assert "上一轮我替你改了正文" not in out


@pytest.mark.anyio
async def test_3_只说上一轮的不把上上轮的又说一遍():
    """`auto_fixes` 跨轮活着的话，第 3 轮会把第 1 轮改的也再说一遍——
    模型会去找一处早就不在那儿的改动。
    量程：把 `before_judge` 里 `st.bag["auto_fixes"] = []` 那一行删掉，这条红。"""
    from app.harness.checks import structure
    st = _echo_st(P22_PARA)
    st.mode = dataclasses.replace(st.mode, checks=(structure.no_echoed_text,))
    await _round(st)
    assert st.bag["auto_fixes"]
    st.content = "这一轮干干净净，什么都没重复。"       # 下一轮没得修
    await _round(st)
    assert st.bag["auto_fixes"] == [], f"上一轮那句该换掉了，实际还留着 {st.bag['auto_fixes']}"


@pytest.mark.anyio
async def test_3_说不出改了什么的fix照旧静默():
    """没填 `fix_note` 的判据保持 P23 那版的老行为——「我改了正文」这半句
    只会让模型去猜哪儿变了，比不说更糟（`test_harness_loop` 那条老闸守的就是它）。
    量程：把 `_fix_events` 里 `if not note: return []` 删掉，这条红。"""
    import re

    def sink(s: State):
        if re.search(r"^#{1,2}\s", s.content, re.M):
            return Verdict("non_repetition", "标题太浅",
                           fix=lambda t: re.sub(r"^(#{1,5})(\s)", r"#\1\2", t, flags=re.M))
        return None

    st = _st(checks=(sink,))
    st.content = "## 标题"
    evs = await _round(st)
    assert st.content == "### 标题", "fix 照样生效"
    assert not st.bag.get("auto_fixes"), "说不出改了什么就别说"
    assert not any(e.data["value"].get("auto_fixed") for e in evs)


# ==================================== 4. 导入 job 的「整体最坏多久」（P26 #4）
#
# P23 临界条件表 #5/#6 量的是 **provider 那一层**的超时（`timeout=300 / retries=2`），
# 每个子任务各有闸——**整体一个上限都没有**。一千篇 × 每篇 M 块 × ≈13 s/块，
# 界面上只有一个「取消」。这一组钉住：到点停 · 说清已完成多少 · 剩下的还能续跑。

class _FakeMem:
    """零 LLM 的 `UserMemory` 替身。

    **替的是 `import_sources.UserMemory` 这个名字，不是 `kite_memory.UserMemory` 这个类。**
    第一版 `monkeypatch.setattr(UserMemory, "remember", ...)` 单跑绿、全量跑红
    （`AttributeError: has no attribute 'remember'`）——全量跑里排在前面的别的测试
    已经把 `kite_memory.UserMemory` 整个换成了自己的替身，那个替身没有 `remember`。
    `_land` 里解析的本来就是 `import_sources` 模块全局的那个名字，替它既准确又不受别人影响。
    """

    def __init__(self, user):
        self.user = user

    def remember(self, messages, *, session_id, date=None, title="", profile=None):
        return 1

    def remove_sessions(self, prefix):
        return None


@pytest.fixture()
def _iso(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.database import store as _store
    from app.routers import import_sources as _imp
    monkeypatch.setattr(_store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    monkeypatch.setattr(_imp, "get_settings", lambda: SimpleNamespace(
        kite_data_dir=tmp_path, kite_extract_model="fake", whisper_base_url="http://x"))
    monkeypatch.setattr(_imp, "UserMemory", _FakeMem)
    return tmp_path


def _imported(n: int):
    from app.database.ingest import importers
    body = "\n\n".join(f"{t} " + ("内容 " * 220) for t in ("A", "B", "C"))
    return [importers.ImportedNote(title=f"第{i}篇", content=body, date="2026-01-01",
                                   source="obsidian", source_id=f"s{i}") for i in range(n)]


def test_4_到了整体上限就停下来说清楚已完成多少(_iso, monkeypatch):
    """**这条是 P26 #4 的正题**：跑满预算之后不再开新的子任务，剩下的每一条都带一句
    「已完成 A/B，点继续」。
    量程：把 `_land` 里 `if over_budget(): stopped_at = pos; break` 那两行删掉，这条红
    （三篇全跑完，一条 failed 都没有）。"""
    from app.database import store as _store
    from app.routers import import_sources as _imp

    # 预算设成「第一篇跑完就到点」：用一个可控的时钟，不靠 sleep
    clock = iter([0.0] + [100.0] * 200)
    monkeypatch.setattr(_imp.time, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(_imp, "JOB_BUDGET_SECONDS", 50.0)

    job_id, items = _store.create_batch_job(
        "u1", [{"filename": f"{i}.md", "kind": "obsidian"} for i in range(3)])
    _imp._land("u1", _imported(3), "kb", job_id, items)

    got = [it["status"] for it in _store.get_items(job_id)]
    assert got == ["failed", "failed", "failed"], got   # 第一篇进循环前时钟已经到点
    detail = _store.get_items(job_id)[0]["detail"]
    assert "时间上限" in detail, detail
    assert "已完成 0 篇" in detail and "剩下 3 篇" in detail, detail
    assert "点「继续」" in detail, "不说怎么接着跑，这个闸就只是把活丢了"


def test_4_停下来的那些还续得了跑(_iso, monkeypatch):
    """**`cancelled` 会让 `resume_job` 跳过它们**——标错一个状态，这条闸就从
    「到点先停」变成「到点把活丢掉」。
    量程：把 `_land` 那句 `store.set_item(item["id"], "failed", ...)` 改成 `"cancelled"`，这条红。"""
    from app.database import store as _store
    from app.routers import import_sources as _imp
    # `resume_job` 的续跑集：不在 ("done","cancelled") 里的才会被重新排队
    src = inspect.getsource(_imp.resume_job)
    assert '("done", "cancelled")' in src, "续跑集的形状变了，这条闸得跟着重读一遍"
    job_id, items = _store.create_batch_job("u1", [{"filename": "a.md", "kind": "obsidian"}])
    _store.set_item(items[0]["id"], "failed", detail="整批已经跑满这次导入的时间上限（60 分钟）")
    it = _store.get_items(job_id)[0]
    assert it["status"] not in ("done", "cancelled"), "标成这两个就再也续不了了"


def test_4_没跑满预算的照旧一篇不落(_iso, monkeypatch):
    """反向：这条闸只该在真跑满时开火，别把正常的导入拦腰砍了。
    量程：把 `over_budget()` 改成恒 True，这条红。"""
    from app.database import store as _store
    from app.routers import import_sources as _imp
    monkeypatch.setattr(_imp, "JOB_BUDGET_SECONDS", 3600.0)
    job_id, items = _store.create_batch_job(
        "u1", [{"filename": f"{i}.md", "kind": "obsidian"} for i in range(3)])
    _imp._land("u1", _imported(3), "kb", job_id, items)
    assert [it["status"] for it in _store.get_items(job_id)] == ["done"] * 3
    assert _store.get_job(job_id)["status"] == "done"


def test_4_预算关掉时一个都不拦(_iso, monkeypatch):
    """`0` / 负数 = 不设上限（部署方想跑通宵就让它跑）。
    量程：把 `budget > 0 and` 那半句删掉，这条红（预算 0 会把所有 job 当场判死）。"""
    from app.database import store as _store
    from app.routers import import_sources as _imp
    monkeypatch.setattr(_imp, "JOB_BUDGET_SECONDS", 0.0)
    job_id, items = _store.create_batch_job(
        "u1", [{"filename": f"{i}.md", "kind": "obsidian"} for i in range(2)])
    _imp._land("u1", _imported(2), "kb", job_id, items)
    assert [it["status"] for it in _store.get_items(job_id)] == ["done", "done"]


def test_4_块与块之间也看预算():
    """一篇几百块的大笔记，只在篇与篇之间看预算的话会整整超一篇。
    量程：把 chunk 循环里的 `or over_budget()` 删掉，这条红。"""
    import inspect as _i
    from app.routers import import_sources as _imp
    src = _i.getsource(_imp._land)
    assert "if store.is_cancel_requested(job_id) or over_budget():" in src, \
        "块与块之间没看预算"
