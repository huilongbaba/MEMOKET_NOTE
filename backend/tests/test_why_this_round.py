"""「这一轮为什么这么跑」——面板上看得见的那几样（计划 12.1）。

面板此前显示的是检索预算和温度，而那两个是 `policy.adjust()` 的**结果**。
缺的两样：

① **`_steer` 这一轮诊断出了什么、有没有真的改到检索计划。** 那句自然语言
   诊断才是真正决定这一轮去查什么的东西，而它此前一个字都没露过面；更要紧
   的是「进没进去」——`policy.steer` 被 `MATERIAL_DIMS` 过滤过（批 22），
   重复 / 不连贯 / 跑题那三维按设计走修订那条线，不进检索计划。
   界面上不说这件事，用户只会看到「它说了重复，然后什么都没变」。

② **这一轮哪几条判据命中了。** `dimension` 答不了这个问题：五条判据同时
   落在 `factual_grounding` 上。而且原来前端的 `checkHit` 是单数，一轮里
   后到的把先到的盖掉——**判据命中了，界面上看不见，等于没建**。
"""

from __future__ import annotations

import asyncio
import pathlib
import re

import pytest

from app.harness import modes
from app.harness.middleware.checks import Checks, STUCK_ROUNDS
from app.harness.middleware.provenance import Provenance
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Mode, Dimension, Verdict

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _st(mode: Mode, *, focus: str = "", focus_note: str = "", **kw) -> State:
    """`focus` / `focus_note` 走 `bag`，**因为那是这句诊断唯一的载体**
    （批 25：`State.steer` 从一个字段变成了从这两个键算出来的只读属性）。

    原来这里写的是 `_st(mode, steer="material_use: …")` 再单独补一句
    `st.bag["focus"] = "material_use"`——那等于在用例里**手工维持**两份
    载体之间的一致，而生产里能不能维持住，这条用例一个字都没在查。
    """
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n"))
    for k, v in kw.items():
        setattr(st, k, v)
    if focus:
        st.bag["focus"] = focus
    if focus_note:
        st.bag["focus_note"] = focus_note
    return st


def test_面板上那句诊断跟修订那一步读的是同一份():
    """**一句诊断只许有一个载体**（批 25）。

    `st.steer` 以前是 `State` 上的一个字段，`loop.py` 每轮末尾算一次；
    紧挨着的两行把同一个 `st.ev` 的同一句话又存进了 `bag["focus"]` /
    `bag["focus_note"]`，而**修订那一步读的是后者**。两份存着的代价不是
    多占内存，是「面板上显示的诊断」和「真正喂回去的诊断」可以说两句话，
    而没有任何地方会发现。

    量过之后才这么定的：库里 380 个 note 轮次，这个值非空 351 轮（92.4%），
    落点 `factual_grounding` 226 / `non_repetition` 99 / … ——**不是一个空
    字段**，是一份**重复**的字段。分布和「为什么不接进 prompt」写在
    `State.steer` 的 docstring 里。
    """
    st = State(mode=_mode(), ctx=ToolContext(user="u", note_id="n"))
    assert st.steer == "", "什么都没诊断出来的时候不许编一句出来"
    st.bag["focus"] = "non_repetition"
    st.bag["focus_note"] = "同一件事说了两遍"
    assert st.steer == "non_repetition: 同一件事说了两遍"

    # 载体只有一个：把 `bag` 那份改掉，`st.steer` 必须跟着变
    st.bag["focus_note"] = "换了一句别的诊断"
    assert st.steer == "non_repetition: 换了一句别的诊断"

    # 而且它是只读的——谁想再存一份独立的，在这儿就被拦下
    try:
        st.steer = "自己编一句"
    except AttributeError:
        pass
    else:                                              # pragma: no cover
        raise AssertionError("`st.steer` 又变回一个存得住的字段了，"
                             "同一句诊断马上会有两份说法")


def test_长文两个模式的_prompt_不许自己去读_st_steer():
    """批 22 划的线：**只有 material 类诊断能进检索规划**，而那道过滤在
    `policy.steer` 上（`MATERIAL_DIMS`）。`st.steer` 是没过滤的那一份——
    `hooks/note` / `hooks/section` 谁把它接进 prompt，就等于从旁边绕过了
    那道过滤，把「再查十条事实也修不好」的诊断（重复 / 不连贯 / 跑题，
    实测占 29.1%）当成检索方向递出去。

    唯一该读它的是 `hooks/block.produce`：块模式每轮整块重写，没有
    `policy`、也没有修订那条线，这句诊断是它唯一的回路。
    """
    hooks = ROOT / "backend" / "app" / "harness" / "hooks"
    readers = {f.name for f in hooks.glob("*.py")
               if "st.steer" in f.read_text(encoding="utf-8")}
    assert readers == {"block.py"}, (
        f"`st.steer` 的读者变了：{sorted(readers)}。长文两个模式要接诊断的话，"
        "走 `policy.steer`（过滤过的）或者 `bag['focus_note']`（修订那条线）")


def _round_payload(st: State) -> dict:
    async def go():
        return [e async for e in Provenance().after_prepare(st)]
    events = asyncio.run(go())
    return next(e.data["value"] for e in events
                if e.data.get("name") == "round_summary")


def _mode(**kw) -> Mode:
    kw.setdefault("dims", (Dimension("d0", "..."),))
    return Mode(key="t", label="test", skill_scope="test_scope", **kw)


# ------------------------------------------------------------------ ① steer

def test_诊断原话和它去了哪儿都在轮次载荷里():
    st = _st(_mode(), focus="material_use",
             focus_note="查到的材料一条都没写进正文")
    st.bag["steer_in_plan"] = True
    v = _round_payload(st)
    assert v["steer"].startswith("material_use:")
    assert v["steer_dim"] == "material_use"
    assert v["steer_material"] is True, "material_use 是检索改善得了的那一类"
    assert v["steer_in_plan"] is True


def test_内在质量那几维报的是不进检索计划而不是没有诊断():
    """重复 / 不连贯 / 跑题：`policy.adjust` 按设计不给它们生成 steer
    （批 22 的 `MATERIAL_DIMS`）。界面要说得出这是设计不是丢失。"""
    st = _st(_mode(), focus="non_repetition", focus_note="同一件事说了两遍")
    st.bag["steer_in_plan"] = False
    v = _round_payload(st)
    assert v["steer_material"] is False
    assert v["steer_in_plan"] is False


def test_没有检索规划那一步和有但没进去是两回事():
    """打磨 / 只清理轮根本走不到 `hooks/note` 那段，`steer_in_plan` 这个键
    **不存在**——报成 `False` 会让用户以为诊断被丢掉了。"""
    st = _st(_mode(), focus="coherence", focus_note="标题层级乱了")
    v = _round_payload(st)
    assert v["steer_in_plan"] is None


def test_上一轮的判据结论不许漏给下一轮():
    """`bag` 是跨轮活着的。上一轮记的 `steer_in_plan` 留着不 pop 的话，
    打磨轮会顶着上一轮的答案报「进了检索计划」——而它压根没有那一步。"""
    st = _st(_mode(), focus="material_use", focus_note="x")
    st.bag["steer_in_plan"] = True
    assert _round_payload(st)["steer_in_plan"] is True
    assert _round_payload(st)["steer_in_plan"] is None, "读完必须 pop"


def test_steer有没有进检索计划是回头在真消息里找的_不是自报():
    """`hooks/note.prepare` 不许写成「我传了所以算进了」：
    `prompts.retrieval_plan_user` 那一句是 `if steer:` 才加的。"""
    src = (ROOT / "backend" / "app" / "harness" / "hooks" / "note.py").read_text(encoding="utf-8")
    assert 'st.bag["steer_in_plan"] = bool(plan_steer) and plan_steer in msgs[-1]["content"]' in src, \
        "这一行改成自报（比如直接写 True）就没有在证明任何事"


def test_检索计划真的带上诊断时那个键才为真():
    from app.harness import prompts
    text = prompts.retrieval_plan_user("标题", "主旨", ["节拍"], "正文",
                                       steer="material_use: 写进去")
    assert "material_use: 写进去" in text
    empty = prompts.retrieval_plan_user("标题", "主旨", ["节拍"], "正文", steer="")
    assert "material_use" not in empty


# ----------------------------------------------------------------- ② 判据

def test_命中事件带得出判据自己的名字():
    """五条判据都落在 `factual_grounding` 上，光有维度名答不了
    「哪条判据命中了」。"""
    def no_placeholder(st):
        return Verdict("d0", "有占位句")

    st = _st(_mode(checks=(no_placeholder,)))

    async def go():
        return [e async for e in Checks().before_judge(st)]
    events = asyncio.run(go())
    v = events[0].data["value"]
    assert v["check"] == "no_placeholder"
    assert v["ran"] == 1
    assert v["round"] == st.round


def test_一轮里命中好几条时每一条都发得出来():
    """卡满放行的那几条 + 最后短路的那一条，可以在同一轮里先后到达。
    前端原来是单数字段，后到的把先到的盖掉。"""
    def stuck(st):
        return Verdict("d0", "改不动的老问题")

    def later(st):
        return Verdict("d0", "另一条")

    st = _st(_mode(checks=(stuck, later)))
    # 把第一条的连击数垫到「已经卡满」，这一轮它会放行并继续往下看
    st.bag["check_streak"] = {"d0" + chr(0) + "改不动的老问题": STUCK_ROUNDS}

    async def go():
        return [e async for e in Checks().before_judge(st)]
    events = asyncio.run(go())
    hits = [e.data["value"] for e in events if e.data.get("name") == "check_hit"]
    assert [h["check"] for h in hits] == ["stuck", "later"], \
        "一轮里两条判据都命中了，两条都得发出来"
    assert hits[0]["stuck_rounds"] == STUCK_ROUNDS + 1
    assert hits[1]["ran"] == 2


def test_分母在轮次载荷里():
    """没有分母，「这一轮判据全过了」跟「判据根本没跑」在界面上一模一样。"""
    v = _round_payload(_st(modes.NOTE))
    assert v["checks_total"] == len(modes.NOTE.checks) > 0


@pytest.mark.parametrize("mode", modes.ALL, ids=lambda m: m.key)
def test_每条判据在前端都有中文名(mode):
    """后端挂上去的判据名会原样进 `check_hit` 事件。前端没有对应的中文名时，
    界面上会蹦出 `no_same_sources_twice` 这种字样——而这是用户看的地方。"""
    src = (ROOT / "frontend" / "src" / "editor" / "dimLabel.ts").read_text(encoding="utf-8")
    labelled = set(re.findall(r"^  (\w+): '", src, re.M))
    missing = {c.__name__ for c in mode.checks} - labelled
    assert not missing, f"{mode.key} 这几条判据前端没有中文名：{sorted(missing)}"


def test_动态挂上去的那条判据也有中文名():
    """`instruction_constraints` 不写在任何 `Mode.checks` 里，是
    `middleware/checklist` 开跑时挂上去的——上面那条 parametrize 看不见它。"""
    src = (ROOT / "frontend" / "src" / "editor" / "dimLabel.ts").read_text(encoding="utf-8")
    assert re.search(r"^  instruction_constraints: '", src, re.M)


# --------------------------------------------------- ③ 深度门丢掉的那几发

def test_深度门丢掉几发也在轮次载荷里():
    from app.harness.agent_loop import ToolTrace
    st = _st(_mode())
    st.trace = ToolTrace(dropped_depth=3)
    st.trace.stopped_all_dropped = True
    v = _round_payload(st)
    assert v["depth_dropped"] == 3
    assert v["depth_dropped_all"] is True


def test_没有trace时不许炸也不许瞎报():
    v = _round_payload(_st(_mode()))
    assert v["depth_dropped"] == 0 and v["depth_dropped_all"] is False


def test_深度门那个数真的落进库里():
    """§21：**落库加字段之后要问一句「它的每个取值都真写得进去吗」。**
    批 22 的 `stopped` 就是从加进来那天起记不到 `max_rounds`。

    所以不是 grep 源码里有没有那个列名——真的走一遍 `Ledger` 再把行读回来。
    """
    from app.database import store as db
    from app.harness.agent_loop import ToolTrace
    from app.harness.middleware.ledger import Ledger

    st = _st(modes.NOTE, round=2)
    st.trace = ToolTrace(calls=[("search_memory", {}, "[f-1] x")],
                         iters=1, dropped_depth=4)
    st.bag["run_id"] = "probe-depth-run"
    asyncio.run(Ledger().after_prepare(st))
    asyncio.run(Ledger().after_judge(st))

    rows = db.rounds_of_run("probe-depth-run")
    assert len(rows) == 1
    assert rows[0]["depth_dropped"] == 4, \
        "深度门丢掉几发，得真的写得进 harness_rounds——否则「它是不是太狠」永远答不出来"
