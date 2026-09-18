"""三列探针：`claim_atoms` / `fired_checks` / `abstained`（批 27 / §5 第 8、9 行）。

批 26 报的两行：

* 第 8 行「`factual_grounding` 候选原子率」——探针语料上量到了
  （`user` 0.89 个/篇），**真跑那一档量不了**；
* 第 9 行「这一节材料够不够写的照做率」——**量不了，分母 0**
  （299 个相邻轮对里能判定的是 0 对）。

缺的都是落库那一侧。所以这个文件钉的不是「列加上了」，是那条规矩：
**落库加字段之后要问一句「它的每个取值都真写得进去吗」**——批 22 的
`stopped` 那一列从加进来那天起就记不到 `max_rounds`，规矩就是那么来的。
下面每一个取值都有一条测试，里面构造的是**真能出现的那个局面**，
不是直接往 bag 里塞一个值。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.harness.checks import claims
from app.harness.middleware.checks import STUCK_ROUNDS, Checks
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.agent_loop import ToolTrace
from app.harness.types import Dimension, Mode, Verdict


_LONG = "这一轮新写的一段话，长度要过得了判据那道下限。" * 8


def _st(checks, *, fresh: str = _LONG, tools: bool = True) -> State:
    mode = Mode(key="t", label="t", skill_scope="test_scope",
                dims=(Dimension("factual_grounding", "..."),),
                checks=tuple(checks))
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n"))
    st.fresh = fresh
    st.content = fresh
    st.bag["content_at_start"] = ""
    st.trace = ToolTrace()
    if tools:
        st.facts = ["[f-1] 一条材料"]
        st.trace.calls.append(("filter_facts", {}, "[f-1] 一条材料"))
    return st


async def _round(st: State) -> list:
    st.ev, st.skip_judge = None, False
    return [e async for e in Checks().before_judge(st)]


def _run(st) -> list:
    return asyncio.run(_round(st))


# ---------------------------------------------- `abstained` 的五个取值 ---

def test_取值not_in_mode_由没有这条判据的模式写进去():
    """六个 block 模式的 `checks` 里没有 `unsupported_specifics`。
    **这一档必须跟「判了、0 个候选」分开**：记成同一个 0 的话，
    「这个模式压根不判」在库里就消失了。"""
    st = _st([])
    _run(st)
    assert st.bag["claim_abstained"] == claims.NOT_IN_MODE
    assert st.bag["claim_atoms"] == -1, "没量就该是 -1，不是 0"


def test_取值too_short_由新写的不够长那一轮写进去():
    st = _st([claims.unsupported_specifics], fresh="太短了。")
    _run(st)
    assert st.bag["claim_abstained"] == claims.TOO_SHORT


def test_取值no_oracle_由一次工具都没返回的轮写进去():
    st = _st([claims.unsupported_specifics], tools=False)
    _run(st)
    assert st.bag["claim_abstained"] == claims.NO_ORACLE


def test_取值no_atoms_由写了一大段却没有日期没有署名的轮写进去():
    st = _st([claims.unsupported_specifics])
    _run(st)
    assert st.bag["claim_abstained"] == claims.NO_ATOMS
    assert st.bag["claim_atoms"] == 0


def test_取值judged_由真的逐条比对过的轮写进去():
    st = _st([claims.unsupported_specifics],
             fresh=_LONG + "2026 年 3 月 15 日那一版定的口径就是这个。")
    _run(st)
    assert st.bag["claim_abstained"] == claims.JUDGED
    assert st.bag["claim_atoms"] >= 1


def test_五个取值一个不少_而且库里那个空串活着的跑写不出来():
    """**把取值列全再逐个问「真写得进去吗」**，就是这一条。
    库里还会有第六种——批 27 之前落的行的 `DEFAULT ''`；它**不在**这张表里，
    因为活着的跑一次都写不出它。混进来的话，「老行」和「这一轮没判」
    又会变成同一个值。"""
    live = {claims.NOT_IN_MODE, claims.TOO_SHORT, claims.NO_ORACLE,
            claims.NO_ATOMS, claims.JUDGED}
    got = set()
    for st in (_st([]),
               _st([claims.unsupported_specifics], fresh="太短了。"),
               _st([claims.unsupported_specifics], tools=False),
               _st([claims.unsupported_specifics]),
               _st([claims.unsupported_specifics],
                   fresh=_LONG + "2026 年 3 月 15 日那一版定的口径就是这个。")):
        _run(st)
        got.add(st.bag["claim_abstained"])
    assert got == live
    assert "" not in got


@pytest.mark.parametrize("fresh,tools,why", [
    (_LONG + "2026 年 3 月 15 日那一版定的口径就是这个。", False, claims.NO_ORACLE),
    ("2026 年 3 月 15 日那一版定的口径就是这个。", True, claims.TOO_SHORT),
])
def test_候选原子数不因为弃权就记成0(fresh, tools, why):
    """「这一轮没有候选原子」和「这一轮压根没去看」是两件事，
    而第 8 行问的正是前者。**两档弃权都要测**：只测一档的话，另一档
    改成记 0 闸照绿——第一版就是这么漏的（突变验 C5）。"""
    st = _st([claims.unsupported_specifics], fresh=fresh, tools=tools)
    _run(st)
    assert st.bag["claim_abstained"] == why
    assert st.bag["claim_atoms"] >= 1, "弃权了也得照实记候选数"


def test_探针跟判据共用同一段前置判断():
    """另写一份「跟判据一样的前置条件」，判据一改这一列量的就不是同一件事了
    ——跟 bench 那条「判据必须是生产那个函数」同一条纪律。"""
    import pathlib

    src = pathlib.Path(claims.__file__).read_text(encoding="utf-8")
    body = src[src.index("def unsupported_specifics"):]
    assert "cands, why = probe(st)" in body
    assert "MIN_FRESH_CHARS" not in body, "判据自己又抄了一遍前置条件"
    assert "has_tool_output" not in body, "判据自己又抄了一遍前置条件"


# ------------------------------------------------ `fired_checks` 的取值 ---

def _always(dimension: str, message: str):
    f = lambda st: Verdict(dimension, message)          # noqa: E731
    f.__name__ = message
    return f


def test_取值空数组_由一条判据都没命中的轮写进去():
    st = _st([lambda st: None])
    _run(st)
    assert st.bag["fired_checks"] == []


def test_取值单条_由正常短路的轮写进去():
    st = _st([_always("factual_grounding", "甲")])
    _run(st)
    assert st.bag["fired_checks"] == ["甲"]
    assert st.skip_judge


def test_取值多条_由卡死放行之后又命中一条的轮写进去():
    """**这个取值是数组而不是单值的全部理由。** `STUCK_ROUNDS` 之后前一条
    `continue`、后一条才短路——记成单值的话，卡死的那条从库里消失，
    而它恰恰是第 9 行最该看的一类。"""
    st = _st([_always("factual_grounding", "甲"), _always("style_fit", "乙")])
    for _ in range(STUCK_ROUNDS):
        _run(st)
        assert st.bag["fired_checks"] == ["甲"]
    _run(st)
    assert st.bag["fired_checks"] == ["甲", "乙"], st.bag["fired_checks"]


def test_当场被修好的那一条不算命中():
    """第 9 行问的是「上一轮提的要求，下一轮照做没有」。`verdict.fix` 那一档
    当场把正文改对了，对下一轮一个要求都没提——算进来是给分母灌水。"""
    seen = {"n": 0}

    def fixer(st):
        seen["n"] += 1
        if "已修" in (st.content or ""):
            return None
        return Verdict("factual_grounding", "丙", fix=lambda c: c + "已修")

    fixer.__name__ = "fixer"
    st = _st([fixer])
    _run(st)
    assert st.bag["fired_checks"] == []
    assert not st.skip_judge


# ------------------------------------------------- 真的落到那张表里 -------

@pytest.mark.parametrize("build,atoms_ok,want", [
    (lambda: _st([]), lambda n: n == -1, claims.NOT_IN_MODE),
    (lambda: _st([claims.unsupported_specifics], fresh="太短了。"),
     lambda n: n >= 0, claims.TOO_SHORT),
    (lambda: _st([claims.unsupported_specifics], tools=False),
     lambda n: n >= 0, claims.NO_ORACLE),
    (lambda: _st([claims.unsupported_specifics]), lambda n: n == 0, claims.NO_ATOMS),
    (lambda: _st([claims.unsupported_specifics],
                 fresh=_LONG + "2026 年 3 月 15 日那一版定的口径就是这个。"),
     lambda n: n >= 1, claims.JUDGED),
])
def test_五个取值真的各自落进harness_rounds(build, atoms_ok, want):
    """**建了列不等于写了列，能写进 bag 也不等于写得进库。** 中间隔着
    `Ledger.after_judge` 那一段参数，漏传一个的症状是那一列恒等于默认值
    ——跟没有这一列一模一样（§21 的 `check_citations` 就是这么躺了
    整个改造期）。所以这里**每个取值都真的走一遍再读回来**。"""
    from app.database import store as db
    from app.harness.middleware.ledger import Ledger

    st = build()
    st.round = 1
    st.bag["run_id"] = f"probe-{want}"
    _run(st)
    asyncio.run(Ledger().after_judge(st))

    rows = db.rounds_of_run(st.bag["run_id"])
    assert len(rows) == 1
    assert rows[0]["abstained"] == want
    assert atoms_ok(rows[0]["claim_atoms"]), rows[0]["claim_atoms"]
    # `judged` 那一档判据真的会开火（那个日期在材料里查无此事），
    # 其余四档判据根本没跑到——两件事本来就该分开记。
    fired = json.loads(rows[0]["fired_checks"])
    assert fired == (["unsupported_specifics"] if want == claims.JUDGED else [])


def test_命中的判据名真的落进harness_rounds():
    from app.database import store as db
    from app.harness.middleware.ledger import Ledger

    st = _st([_always("factual_grounding", "material_thin")])
    st.round = 1
    st.bag["run_id"] = "probe-fired"
    _run(st)
    asyncio.run(Ledger().after_judge(st))
    rows = db.rounds_of_run("probe-fired")
    assert json.loads(rows[0]["fired_checks"]) == ["material_thin"]


def test_读完就pop_下一轮不会静默继承这一轮的数():
    """bag 是跨轮活着的。`Provenance` 的 `steer_in_plan` 是同一条处理——
    **键不在**和**键是旧值**，只有前者说得出「这一轮没走到那一步」。"""
    import asyncio as _a

    from app.harness.middleware.ledger import Ledger

    st = _st([claims.unsupported_specifics])
    st.round = 1
    st.bag["run_id"] = "probe-pop"
    _run(st)
    _a.run(Ledger().after_judge(st))
    for key in ("claim_atoms", "fired_checks", "claim_abstained"):
        assert key not in st.bag, f"{key} 没 pop，会漏给下一轮"
