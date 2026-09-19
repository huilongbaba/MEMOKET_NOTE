"""P25（`docs/TRACELOG-product.md` P25 节）：P22 复测读出来的记忆 / 目录 / 圆点三条 + 骨架半句的收尾。

  1. 骨架半句：判据挪进 `store.truncated_beats`，`hooks/note.skeleton` 读出来就提醒；
     `verify_beats` 贴完标签**再收一次上限**（不然正好卡 200 的那条落库会抛）。
  3. `relations._NUM` 开 `re.IGNORECASE`：`567kwh` / `10KV` 抽得出量，而且**大小写归一到单位表的写法**
     （不归一的话 `9kWh` 和 `567kwh` 落进两个桶，同一个单位互相印证不了）。
  4. 「缺依据」分两档（`why`）：`no_record`（库里连沾边的都没有）/ `no_value`（沾边但没带这段的量）。

每条断言的量程写在 docstring 里（撤掉哪一行它红）。
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.database import store                                         # noqa: E402
from app.database.kb import relations as R                             # noqa: E402


# ==================================================== 1. 骨架半句：判据 + 读出来就提醒

def test_1_半句判据_正好六十字且不以句读收尾():
    """撤掉 `len(b) == LEGACY_BEAT_MAX` 或那个句读表，这条红。

    真库实拍的两条：`e78306202d78` 的 B1（60 字，收在「并把午餐」）是半句；
    `a941efecd390` 的 B1（42 字，收在「。」）不是。"""
    half = "已写：以陈校从招生策略转向课程本土化、行业案例和师资协作为切入口，建立合作方向已被认可、但仍需机制化落地的处境，并把午餐"
    whole = "先将快速推进与热情、希望尽快进入下一步联系起来，建立“速度并非纯粹缺点”的正面动机。"
    assert len(half) == store.LEGACY_BEAT_MAX
    assert store.truncated_beats([whole, half]) == [2]
    # 61 字的整句不是被 60 切的——长度要**正好**等于老上限
    assert store.truncated_beats([half + "会"]) == []
    # 收在句读上的 60 字是自己写成这样的，不是被切的
    assert store.truncated_beats([half[:59] + "。"]) == []


def test_1_续写读到半句骨架就在面板上出声():
    """`hooks/note.skeleton` 拿笔记里存着的骨架（router 传进来的）时要发一条 warning。
    撤掉那个 `if half := store.truncated_beats(...)` 这条红。"""
    import asyncio

    from app.harness.events import CUSTOM_WARNING
    from app.harness.hooks.note import NoteHooks
    from app.harness.state import State

    half = "已写：以陈校从招生策略转向课程本土化、行业案例和师资协作为切入口，建立合作方向已被认可、但仍需机制化落地的处境，并把午餐"

    class _Ctx:
        user = "t"
        note_title = "标题"
        intent = ""

    async def run(beats):
        st = State.__new__(State)
        st.content = "正文正文正文正文正文正文正文正文。\n\n第二段也有一些字，凑够长度。"
        st.bag = {}
        st.ctx = _Ctx()
        hooks = NoteHooks(spine="核心张力一句话。", beats=beats)
        return [e async for e in hooks.skeleton(st)]

    def warns(events):
        return [e.data["value"] for e in events
                if e.data.get("name") == CUSTOM_WARNING and "半句" in (e.data.get("value") or {}).get("error", "")]

    warn = warns(asyncio.run(run([half])))
    assert len(warn) == 1 and "第 1 条" in warn[0]["error"]
    # 整句的骨架不该冒这条
    assert not warns(asyncio.run(run(["一条写完的节拍。"])))


# 一条「模型给了超长节拍」的骨架：`verify_beats` 会在句首加「已写（正文第 N 行起）：」十几个字，
# 先 clamp 再贴标签，正好卡在 `BEAT_MAX` 的那条贴完就超上限；而 P7 之后 `set_skeleton`
# 不再静默截断、改成抛 `ValueError`（router 回 400）——于是「所见即所存」在最后一步上不成立。
_LONG_BODY = "这一段正文把报价、依据、买家反馈和时间范围都写清楚了。" * 20
_LONG_BEAT = "待补：" + _LONG_BODY[:store.BEAT_MAX * 2]


def test_1_贴完待补标签确实会超上限():
    """量程：这条钉住「问题存在」——撤掉它上面那两条就成了无的放矢的测试。"""
    from app.harness.checks.skeleton import verify_beats

    _s, clamped = store.clamp_skeleton("", [_LONG_BEAT])
    assert len(clamped[0]) <= store.BEAT_MAX                       # 收过了，落得了库
    assert len(verify_beats(clamped, _LONG_BODY)[0]) > store.BEAT_MAX   # 贴完标签又超了


def test_1_生成骨架那两条路交出来的都落得了库(monkeypatch):
    """`POST /api/skeleton`（router）和续写里的 `hooks/note.skeleton` 两条路，
    交出来的 beats 都必须 ≤ `BEAT_MAX`——否则前端拿去 `PUT /notes/{id}/skeleton` 回 400。
    撤掉这两处尾部的 `clamp_skeleton`（任一处），这条红。"""
    import asyncio

    from app.harness.hooks.note import NoteHooks
    from app.harness.state import State
    from app.routers import compose
    from app.routers.schemas import SkeletonIn
    from app.util import llm

    parsed = {"spine": "一句话的核心张力。", "beats": [_LONG_BEAT]}

    async def fake_raw(messages, **kw):
        return parsed, ""

    async def fake_json(messages, **kw):
        return parsed

    monkeypatch.setattr(compose.llm, "complete_json_raw", fake_raw, raising=False)
    monkeypatch.setattr(llm, "complete_json", fake_json, raising=False)
    monkeypatch.setattr(compose, "_profile", lambda _u: [], raising=False)

    out = asyncio.run(compose.skeleton(SkeletonIn(title="标题", content=_LONG_BODY), user="t"))
    assert out.beats and all(len(b) <= store.BEAT_MAX for b in out.beats), [len(b) for b in out.beats]
    assert out.beats[0].startswith("已写（正文第 1 行起）：")   # 标签在头上，收的是尾巴

    class _Ctx:
        user = "t"
        note_title = "标题"
        intent = ""

    st = State.__new__(State)
    st.content = _LONG_BODY
    st.bag = {}
    st.ctx = _Ctx()

    async def drain():
        return [e async for e in NoteHooks().skeleton(st)]

    asyncio.run(drain())
    assert st.bag["beats"] and all(len(b) <= store.BEAT_MAX for b in st.bag["beats"])


# ============================================ 3. `_NUM` 开 IGNORECASE + 单位大小写归一

def test_3_小写单位抽得出量():
    """`567kwh` / `10KV` / `600kw`：撤掉 `re.IGNORECASE` 这条红。
    真库 482 篇上量过：`_NUM` 命中 2053 → 2059，新增 6 处全部是 `KV` / `kwh`，误伤 0 处。"""
    v = R.extract_values("单个电池容量是 567kwh，站点是 10KV，充电主机 600kw。")
    assert (567.0, "kWh") in v["nums"]
    assert (10.0, "kV") in v["nums"]
    assert (600.0, "kW") in v["nums"]


def test_3_大小写归一到单位表的写法():
    """不归一的话 `by_unit` 把 `9kWh` 和 `567kwh` 分到两个桶，同一个单位互相印证不了。
    撤掉 `_UNIT_CANON` 那一行这条红。"""
    assert R.extract_values("567kwh")["nums"] == R.extract_values("567kWh")["nums"] == [(567.0, "kWh")]
    facts = [{"id": "f1", "text": "电池容量是 567kWh。", "date": "2026-01-01"}]
    rels = R.detect("单个电池容量是 567kwh，是徐工和国网一起做的。", facts)
    assert any(r["relation"] == "corroborated" and r["unit"] == "kWh" for r in rels)


def test_3_开了大小写不敏感也不多认别的单位():
    """误伤那一侧：**单位表以外的字母组合照旧不算量**。`KB` / `Kb` 表里没有 → 0 个量；
    紧跟字母的（`5kgs`）被 `(?![A-Za-z])` 挡着；人名里的字母不参与。
    真库 482 篇上量过：新增命中只有 `KV` / `kwh` 两个单位，别的一处都没多出来。"""
    assert R.extract_values("这个文件 3KB")["nums"] == []
    assert R.extract_values("重 5kgs")["nums"] == []
    assert R.extract_values("会员 Kevin 有 5 个项目")["nums"] == [(5.0, "个")]


# ================================================ 4. 「缺依据」分两档：no_record / no_value

_QTY = "本季度新增用户 4300 人，客单价 129 元。"


def test_4_库里连沾边的都没有_是_no_record():
    """撤掉 `"why": ...` 那一行，或把两档合成一档，这条红。"""
    facts = [{"id": "f1", "text": "今天下午的会改到明天上午。", "date": "2026-01-01"}]
    rels = R.detect(_QTY, facts)
    un = [r for r in rels if r["relation"] == "unsupported"]
    assert len(un) == 1 and un[0]["why"] == "no_record"


def test_4_沾边但没带这段的量_是_no_value():
    """沾边（重合 ≥0.12 且共用 ≥2 个词元）却没有一条对上量 → `no_value`，这一档**要画点**。"""
    facts = [{"id": "f1", "text": "本季度新增用户的客单价还没有统计出来。", "date": "2026-01-01"}]
    rels = R.detect(_QTY, facts)
    un = [r for r in rels if r["relation"] == "unsupported"]
    assert len(un) == 1 and un[0]["why"] == "no_value"


def test_4_对上了量就不报缺依据():
    """印证 / 冲突 / 延续任一成立时根本没有 unsupported，也就没有 `why`。"""
    facts = [{"id": "f1", "text": "本季度新增用户 4300 人。", "date": "2026-01-01"}]
    rels = R.detect(_QTY, facts)
    assert not [r for r in rels if r["relation"] == "unsupported"]
