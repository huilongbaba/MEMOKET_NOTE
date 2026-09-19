"""P23（`docs/TRACELOG-product.md` P23 节）：P19 / P21 的遗留 + 剩下的临界条件。

  1. `done_criteria` 日期那一侧：说第二遍就别再说了，判据自己把「（日期待补）」补上
     （`Verdict.fix` + `fix_done`）。
  8. 临界条件表剩下的 ？：写作计划生成无停止 / 引用补一条·改 空文本 / 导入页超时。

每条断言的量程写在 docstring 里（撤掉哪一行它红）。
"""

from __future__ import annotations

import asyncio
import pathlib
import struct
import sys
from unittest import mock

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.editor import vision                                          # noqa: E402
from app.harness.checks import done as D                               # noqa: E402
from app.harness.middleware.checks import Checks                       # noqa: E402
from app.harness.state import State                                    # noqa: E402
from app.harness.types import Verdict                                  # noqa: E402
from app.routers import settings as settings_router                    # noqa: E402
from app.util import probe_image                                       # noqa: E402


# ============================================ 1. 日期那一侧：判据自己补「（日期待补）」

INTENT = "目标：周报；完成标准：每个节点有日期、有出处"

# 两段没日期（一段有）。跟 p18b / p19hint 真跑里被点名三轮的那两段同一个形状：
# 「回看这一年…」「下一步还需要把…」——回顾 / 展望句，材料里本来就没有日期可给。
DATED = "4月16日，EVT 进入硬件检查节点：计划 4 台主板 [fact-000000000001-a]。"
NO_DATE_1 = "回看这一年，真正被重新确认的不是某一个产品计划，而是一种面对不确定性的工作方式。"
NO_DATE_2 = "下一步还需要把“可理解”变成团队可以直接检查的交付物：任何动效提案都要配一段静止演示。"
BODY = f"{DATED}\n\n{NO_DATE_1}\n\n{NO_DATE_2}"


def _st(content: str, streak: int = 0, start: str = "") -> State:
    st = State(mode=type("M", (), {"checks": (D.done_criteria,), "dims": ()})(),   # type: ignore[arg-type]
               ctx=type("C", (), {"intent": INTENT, "intent_checked": ()})(),      # type: ignore[arg-type]
               content=content)
    st.bag["content_at_start"] = start
    st.bag["check_name_streak_prev"] = {"done_criteria": streak}
    st.round = streak + 1
    return st


def test_第一轮只说不动手():
    """模型得先有一整轮按提示写**真日期**的机会——第一次就替它写「（日期待补）」是误伤。
    量程：把 `streak >= 2` 改成 `>= 1`，这条红。"""
    v = D.done_criteria(_st(BODY, streak=0))
    assert v is not None and "没有日期" in v.message, v
    assert v.fix is None, "第一轮不该动手"


def test_连响第二轮判据自己把日期待补补上():
    """**这条是 P23 #1 的正题**。P19 把「怎么落到字面上」写清之后，出处那一侧逐轮在补
    （3/3 → 8/6），日期那一侧 p15 / p18b / p19hint 三批真跑重放：9 次命中、8 个不同的段，
    连着点名 ≥2 轮的 6 个里 **0 个**被补上过真日期。求不动就别求了，判据自己贴记号。
    量程：把 `Verdict(..., fix=fix)` 那一行的 fix 去掉，这条红。"""
    v = D.done_criteria(_st(BODY, streak=1))
    assert v is not None and v.fix is not None, v
    fixed = v.fix(BODY)
    assert fixed.count(D.DATE_PENDING) == 2, fixed
    assert DATED in fixed, "有日期的那一段不许动"
    assert v.fix_done is not None and v.fix_done(fixed), "补完之后日期那一侧就该过了"


def test_有日期的那一行不会被贴记号():
    """量程：把 `mark_date_pending` 里 `_R["date"].search(line)` 那个跳过删掉，这条红。"""
    out = D.mark_date_pending(BODY, [DATED, NO_DATE_1])
    assert D.DATE_PENDING not in out.split("\n\n")[0], out


def test_贴过一次就不再贴第二次():
    """连响第 3、4 轮还会再算一次 fix，记号不能越贴越多。

    **两道闸各挡一种**：连着两次拿原话来贴，靠「贴完就不再以原话结尾」挡住；
    拿**已经带着记号的那一句**来贴（`mark_date_pending` 是个公开的纯函数，
    右栏那份数出来的 `bad` 就带记号），靠 `has_date_pending(line)` 挡住。
    量程：把 `has_date_pending(line)` 那个跳过删掉，第二段红。"""
    once = D.mark_date_pending(BODY, [NO_DATE_1, NO_DATE_2])
    twice = D.mark_date_pending(once, [NO_DATE_1, NO_DATE_2])
    assert once.count(D.DATE_PENDING) == 2 and twice.count(D.DATE_PENDING) == 2, twice
    marked = NO_DATE_1 + D.DATE_PENDING
    again = D.mark_date_pending(marked, [marked])
    assert again == marked, again


def test_两条撞同一行时一行只贴一个():
    """**两条不同的单位落在同一行**（正文里同一句出现两遍，`units()` 会数成两条）时，
    一条认一行，不能两条都往第一行上贴。靠的不是额外的守卫，是「贴在行尾」这件事本身：
    第一条贴完，那一行就不再以原话结尾了。
    量程：把 `lines[i] = line.rstrip() + DATE_PENDING` 改成往行首贴，这条红。"""
    dup = f"{NO_DATE_1}\n\n{NO_DATE_1}"
    out = D.mark_date_pending(dup, [NO_DATE_1, NO_DATE_1])
    assert out.count(D.DATE_PENDING) == 2, out
    for line in [l for l in out.split("\n") if l.strip()]:
        assert line.count(D.DATE_PENDING) == 1, out


def test_用户自己写的没日期的段一个字不碰():
    """量程（**这条是防误伤的那道闸**）：把 `done_criteria` 里的 `unit_filter=fresh_only`
    去掉，这条红——用户开跑前就写在那儿的段会被判据贴上记号。"""
    st = _st(BODY, streak=1, start=NO_DATE_1)       # 第一段是用户原文
    v = D.done_criteria(st)
    assert v is not None and v.fix is not None
    fixed = v.fix(st.content)
    assert fixed.count(D.DATE_PENDING) == 1, fixed
    first, *_ = [p for p in fixed.split("\n\n") if NO_DATE_1 in p]
    assert D.DATE_PENDING not in first, "用户原文被动了"


def test_标了记号的在harness里不再数成没日期_右栏照旧数():
    """记号是给**用户**看的「还欠着」，所以右栏那份（没有 `date_pending_ok`）照旧数它没日期；
    harness 那一侧不能跟自己的提示打架（跟出处那一侧的弃答句同一个形状，P15 #1）。
    量程：把 `date_pending_ok` 那个条件恒定成 True，后半条红。"""
    marked = D.mark_date_pending(BODY, [NO_DATE_1, NO_DATE_2])
    item = "每个节点有日期、有出处"
    harness = D.check_done_item(item, marked, date_pending_ok=True)
    panel = D.check_done_item(item, marked)
    assert harness and "都有日期" in harness["why"], harness
    assert panel and "没有日期" in panel["why"], panel


def test_半角括号也认():
    """模型爱写半角。量程：把 `_DATE_PENDING` 正则里的 `[(]`/`[)]` 去掉，这条红。"""
    assert D.has_date_pending("下一步…(日期待补)")
    assert D.has_date_pending("下一步…（日期待补）")
    assert not D.has_date_pending("下一步…（出处待补）")


# ---------------------------------------------- Verdict.fix_done 的接线（middleware）

def _run_checks(st: State) -> str:
    async def go():
        async for _ in Checks().before_judge(st):
            pass
    asyncio.run(go())
    return next(iter(st.ev.scores.values())).note if st.ev else ""


def test_一条判据管两件事时修好的正文要留下():
    """**没有这一条就白做**：`if not check(probe)` 是「整条判据都过了才留」，而
    「每个节点有日期、有出处」一条判两件事——贴完记号出处那件事还欠着，整条照样命中，
    贴好的正文会被原样丢掉（p15 / p18b / p19hint 三批每一轮都会这样）。
    量程：把 `middleware/checks.py` 里 `verdict.fix_done` 那一段删掉，这条红。"""
    st = _st(BODY, streak=1)
    # `Checks.before_judge` 自己把「上一轮那份」从 `check_name_streak` 搬过去，所以摆的是这个键
    st.bag["check_name_streak"] = {"done_criteria": 1}
    msg = _run_checks(st)
    assert st.content.count(D.DATE_PENDING) == 2, st.content
    assert "没有日期" not in msg and "没有出处" in msg, msg


def test_fix没真修好就不许改正文():
    """P19 之前那条纪律（原注释：一个没修好的 fix 照样把正文改了，下一轮就建在改坏的东西上）
    一个字没松：`fix_done` 说没好，正文原样。
    量程：把 `if verdict.fix_done is not None and verdict.fix_done(...)` 的判断去掉，这条红。"""
    calls: list[str] = []

    def never_fixes(st: State):
        return Verdict(dimension="mechanics", message="改不动",
                       fix=lambda c: c + "\n被改过了",
                       fix_done=lambda c: bool(calls.append(c)))      # append 回 None → False
    st = State(mode=type("M", (), {"checks": (never_fixes,), "dims": ()})(),   # type: ignore[arg-type]
               ctx=type("C", (), {"intent": "", "intent_checked": ()})(),      # type: ignore[arg-type]
               content="原样")
    st.round = 1
    msg = _run_checks(st)
    assert st.content == "原样", st.content
    assert msg == "改不动", msg
    assert calls, "fix_done 压根没被问过"


def test_日期记号不进共享规则表():
    """`RULES` / `WHY` 两边一字不差（`tests/test_p13.py` 集合相等地盯着）——记号只有 harness
    用得上，塞进 `RULES` 会把前端那份也改掉、右栏就不数了。
    量程：把 `DATE_PENDING` 挪进 `RULES`，`test_p13` 那两条红。"""
    assert "date_pending" not in D.RULES and "date_pending" not in D.WHY


# ============================================ 4. 看图那一栏：真发一张图，读不出数字不算过

class _FakeResp:
    def __init__(self, code: int, payload=None, text=""):
        self.status_code, self._payload, self.text = code, payload, text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FakeClient:
    """`/models` 那一段按脚本回，不连网。"""

    def __init__(self, gets=None):
        self.gets = gets or {}

    async def get(self, url, **kw):
        r = self.gets.get(url)
        if isinstance(r, Exception):
            raise r
        return r


class _FakeAsyncClient:
    """记下 `ask_image` 真发出去的那一份 body，按脚本回。"""

    last: dict | None = None
    code: int = 200
    answer: str = ""
    text: str = ""

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        type(self).last = {"url": url, "json": json, "headers": headers}
        cls = type(self)
        return httpx.Response(cls.code,
                              json={"choices": [{"message": {"content": cls.answer}}]},
                              text=None if cls.code < 400 else cls.text,
                              request=httpx.Request("POST", url))


def _vision_probe(answer: str = "", *, code: int = 200, text: str = ""):
    _FakeAsyncClient.code, _FakeAsyncClient.answer, _FakeAsyncClient.text = code, answer, text
    _FakeAsyncClient.last = None
    c = _FakeClient(gets={"http://h/v1/models": _FakeResp(200, {"data": [{"id": "vl"}]})})
    with mock.patch.object(vision.httpx, "AsyncClient", _FakeAsyncClient):
        return asyncio.run(settings_router.probe_endpoint(
            kind="vision", base_url="http://h/v1", model="vl", client=c))


def test_看图测一下真把一张图发出去():
    """**这条是 P23 #4 的正题**：P19 之后看图那一栏走的还是写作模型那条探针（`/models`
    或一次纯文字 completion），那句「连上了」证明不了它带视觉。
    量程：把 `probe_endpoint` 里 `kind == "vision"` 那两处 `vision_ok` 去掉，这条红。"""
    r = _vision_probe(f"图上是 {probe_image.PROBE_NUMBER}")
    assert r.ok and probe_image.PROBE_NUMBER in r.message, r.message
    body = _FakeAsyncClient.last
    assert body and body["url"] == "http://h/v1/chat/completions", body
    parts = body["json"]["messages"][-1]["content"]
    assert any(p.get("type") == "image_url" for p in parts), parts
    assert "data:image/png;base64," in parts[-1]["image_url"]["url"]


def test_收下了图却读不出数字就不算过():
    """纯文字模型会原样收下请求、回一句没用的话。**猜中的概率是 1/900**，所以读不出就判不过。
    量程：把 `PROBE_NUMBER in answer` 那个判断改成恒 True，这条红。"""
    r = _vision_probe("这是一张图片。")
    assert not r.ok and "没读出" in r.message and "不带视觉" in r.message, r.message


def test_模型不收图片时说人话():
    """量程：把 `except vision.VisionError` 那一支删掉，这条红（异常直接冒到接口上）。"""
    r = _vision_probe("", code=400, text="this model does not support images")
    assert not r.ok and "发一张图过去失败" in r.message and "带视觉" in r.message, r.message


def test_探针走的是真正看图那条路():
    """**闸要守来源**（P21）：探针自己拼一份请求的话，`ask_image` 改了（比如 data URI 的
    拼法、system 的位置）探针照样绿，而真路径已经坏了。
    量程：把 `vision_ok` 改成自己 `c.post` 一份 body，这条红。"""
    called: list[dict] = []

    async def spy(prompt, image, mime="image/png", **kw):
        called.append({"prompt": prompt, "image": image, "kw": kw})
        return probe_image.PROBE_NUMBER

    c = _FakeClient(gets={"http://h/v1/models": _FakeResp(200, {"data": [{"id": "vl"}]})})
    with mock.patch.object(vision, "ask_image", spy):
        r = asyncio.run(settings_router.probe_endpoint(
            kind="vision", base_url="http://h/v1", model="vl", api_key="k", client=c))
    assert r.ok, r.message
    assert called and called[0]["image"][:8] == b"\x89PNG\r\n\x1a\n", called
    # 输入框里那份（还没保存）要原样递进去
    assert called[0]["kw"]["cfg"] == {"base_url": "http://h/v1", "model": "vl", "api_key": "k"}


def test_探针图上的数字认得出来():
    """图是现画的（`util/probe_image`），不截用户的屏、也不塞进仓库——截屏会把用户桌面上的
    东西发出去，而这一栏正是「截图发到哪」那条承诺的入口。
    量程：这条守形状（PNG 头 + 三位数 + 长边够大），`_SCALE` 改小到 2 它红。"""
    png = probe_image.probe_png()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", png[16:24])
    assert w >= 200 and h >= 100, (w, h)
    assert len(probe_image.PROBE_NUMBER) == 3 and probe_image.PROBE_NUMBER.isdigit()


def test_写作那一栏不发图():
    """看图那条探针贵一点（一次带图的调用），写作 / 语音两栏不该跟着变。
    **两条路都要挡**：`/models` 列得出来的那条，和列不出来、退回发一次最小 completion 的那条
    （后者正是 `kind == "vision"` 的第二个岔口）。
    量程：把 `probe_endpoint` 里任意一处 `if kind == "vision"` 的条件去掉，这条红。"""
    _FakeAsyncClient.last = None
    _FakeAsyncClient.code, _FakeAsyncClient.answer = 200, ""
    c = _FakeClient(gets={"http://h/v1/models": _FakeResp(200, {"data": [{"id": "m"}]})})
    with mock.patch.object(vision.httpx, "AsyncClient", _FakeAsyncClient):
        r = asyncio.run(settings_router.probe_endpoint(kind="llm", base_url="http://h/v1",
                                                       model="m", client=c))
    assert r.ok and _FakeAsyncClient.last is None, r.message

    # 列不出模型的那条路（有些网关不实现 /models）：照旧发一次纯文字 completion，不发图
    class _C(_FakeClient):
        def __init__(self):
            super().__init__(gets={"http://h/v1/models": _FakeResp(404)})
            self.posted: list[str] = []

        async def post(self, url, **kw):
            self.posted.append(str((kw.get("json") or {}).get("messages")))
            return _FakeResp(200, {"choices": [{"message": {"content": "hi"}}]})

    c2 = _C()
    with mock.patch.object(vision.httpx, "AsyncClient", _FakeAsyncClient):
        r2 = asyncio.run(settings_router.probe_endpoint(kind="llm", base_url="http://h/v1",
                                                        model="m", client=c2))
    assert r2.ok, r2.message
    assert c2.posted and "image_url" not in c2.posted[0], c2.posted
    assert _FakeAsyncClient.last is None, "写作那一栏走了看图那条路"
