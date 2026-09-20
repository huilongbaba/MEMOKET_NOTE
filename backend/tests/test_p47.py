"""P47 A2：**一条结构性的闸**，管住 P45 那一整类——「编辑器里有的，库里也得有」。

P45 修的是机制，可它留下的闸有两层是**清单对清单**：一条钉「挂 Save 的模式是
`note` / `section` 这两个」，一条钉「带 `fix` 的判据是那 7 条」。名单式的闸只在
「有人偷偷改名单」时有用；**新加一个挂 `Save` 的模式、或者新加一条带 `fix` 的
判据，名单闸只会红一次、被人照着改掉，然后什么都没验**（P21 立的规矩：闸要判
性质，不判写法）。

所以这一份闸一条名单都不抄，它问的是一个**性质**：

    凡是挂了 `Save` 的模式，只要 `fix` / `fix_done` 动过正文，
    `STEP_FINISHED` / `RUN_FINISHED` 交出去的那一份，就必须跟 `notes.content`
    **逐字相同**。

三件事让它是「结构性」的，不是「又一张名单」：

  1. **被测的模式是数出来的**：`_save_modes()` 从 `modes.ALL` 里筛「`extra_mw`
     里有没有 `name == "save"`」。明天多一个挂 `Save` 的模式，它自动进这条闸——
     不改这个文件一个字。
  2. **hooks 是生产那条路造的**：`app.routers.harness._hooks_for`，不是测试自己
     new 一个。`commit` 落不落库正是被测的那一处，它必须来自真的接线。
  3. **判的是库，不是内存**（P44/P45 那条「编辑器里没有 ≠ 库里没有」）：
     `conftest` 给每个测试一份自己的 sqlite，这里真的 `create_note` / 真的落库 /
     真的 `SELECT content FROM notes` 读回来。

判据里**没有任何一条判据的名字**：正文被改的那一下由一条**合成的** `fix` 提供
（真判据那一侧 P45 的行为闸拿 `shape.output_not_json` 钉着，P47 A1 另外把剩下
5 条各自的形状在真跑上摆了一遍）。这条闸要守的不是「那 7 条」，是**那条路**。
"""

from __future__ import annotations

import asyncio
import dataclasses
import sqlite3

import pytest

from app.database import store
from app.harness import modes
from app.harness.loop import run
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Dimension, DimensionScore, Evaluation, Mode, Verdict

SEED = "这周把众筹页面的文案定稿了，3月12号上线。"
JUNK = "【这一段是要被 fix 摘掉的】"


# ------------------------------------------------------ 被测的模式是数出来的 ---

def _save_modes() -> list[Mode]:
    """所有**会把正文写进用户笔记**的模式。

    判的是「`extra_mw` 里有没有 `save`」，跟 `middleware/save.writes_note`
    同一句话——不是抄一张 `("note", "section")` 的名单。
    """
    return [m for m in modes.ALL
            if any(getattr(x, "name", "") == "save" for x in m.extra_mw)]


def _mode_ids() -> list[str]:
    return [m.key for m in _save_modes()]


# ------------------------------------------------------------------ 量具 ---

class _Trace:
    calls: list = []
    used = False
    iters = 0


class _StubbedProduce:
    """**真 hooks，假嘴巴**。

    `commit` 是被测的那一处，必须是生产那条路造出来的真货，所以这里不继承、
    不重写它——`__getattr__` 直接转给真 hooks。只有 `prepare` / `produce`
    被换掉：它们会打模型，而这条闸要量的事跟模型写了什么无关。
    """

    def __init__(self, real, texts: list[str]):
        self._real = real
        self._texts = texts

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def prepare(self, st):
        return [], _Trace()

    async def produce(self, st):
        text = self._texts[min(st.round, len(self._texts)) - 1]
        yield text
        st.fresh = text
        st.content = (st.content + "\n\n" + text) if st.content else text


def _hooks_for(mode: Mode, st: State):
    """**生产那条路**造 hooks（`app/routers/harness._hooks_for`）。"""
    from app.routers import harness as harness_router
    st.bag["profile"] = ["（测试）用户画像占位"]      # 别去查真的画像
    return harness_router._hooks_for(mode.key, st)


def _fix_check(st: State) -> Verdict | None:
    """合成判据：正文里有 `JUNK` 就摘掉。**跟仓里任何一条判据都没关系**——
    这条闸测的是「`fix` 改过的正文落不落库」那条路，不是某一条判据。"""
    if JUNK not in st.content:
        return None
    return Verdict("mechanics", "有要摘掉的东西",
                   fix=lambda text: text.replace(JUNK, "").rstrip())


def _half_fix_check(st: State) -> Verdict | None:
    """`fix_done` 那一支：fix 改了正文，可复判**还在响**（管着不止一件事），
    `fix_done` 说「我管的那件修好了」——正文照样留下（`middleware/checks` 那段）。
    这一支同样动了正文，同样得落库。"""
    if JUNK not in st.content and "【第二件事】" not in st.content:
        return None
    return Verdict("mechanics", "两件事，只修得掉一件",
                   fix=lambda text: text.replace(JUNK, "").rstrip(),
                   fix_done=lambda text: JUNK not in text,
                   fix_note="把要摘掉的那一段摘了")


def _scorer(levels_per_round):
    async def score(st):
        levels = levels_per_round[min(st.round, len(levels_per_round)) - 1]
        scores = {f"d{i}": DimensionScore(level=v, note="") for i, v in enumerate(levels)}
        status = "complete" if all(v >= 2 for v in levels) else "continue"
        return Evaluation(scores=scores, status=status,
                          weakest=None if status == "complete" else "d0")
    return score


def _read_db(note_id: str) -> str:
    """**读库**。不读 `st.content`、不读事件、不读任何内存里的东西。"""
    conn = sqlite3.connect(store._db_path())
    try:
        row = conn.execute("SELECT content FROM notes WHERE id=?", (note_id,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else ""


def _drive(mode: Mode, texts: list[str], levels, checks, stops=None) -> dict:
    """真跑一趟，**每发一次 `STEP_FINISHED` / `RUN_FINISHED` 就读一次库**。

    `stops=()` 是给「交最好那一轮」那条闸用的：这些假跑手上一条材料都没有，
    真的 `stop_when` 里 `material_used_up` 第一轮就命中，而它**不在
    `SHIP_BEST_ON` 里**——循环 `break` 出去，正文根本不会被换掉，那条闸就
    测不到它要测的分支了（第一版实拍：`stopped=material_used_up`，
    `st.best` 是第 1 轮而 `st.content` 还是第 2 轮，两边一样长，断言当场说
    「这份假分数没把那条分支摆出来」——**闸自己把「没测到」说出来了**）。
    """
    note = store.create_note("u1", "P47", SEED)
    note_id = note["id"] if isinstance(note, dict) else note
    m = dataclasses.replace(
        mode, checks=tuple(checks), max_rounds=len(texts), dims=(Dimension("mechanics", "..."),),
        # `revise` 会打模型（这条闸不测它）。**`save` 一个字都不许摘**。
        rails_off=("revise",),
        **({} if stops is None else {"stop_when": tuple(stops)}))
    st = State(mode=m,
               ctx=ToolContext(user="u1", note_id=note_id, scope="all",
                               note_title="P47", content=SEED),
               content=SEED)
    st.bag["polish"] = False
    hooks = _StubbedProduce(_hooks_for(mode, st), texts)

    import app.harness.loop as loop_mod
    original, loop_mod._score = loop_mod._score, _scorer(levels)
    try:
        events = asyncio.run(_collect(st, hooks))
    finally:
        loop_mod._score = original

    steps, run_fin = [], None
    for kind, content, db in events:
        if kind == "STEP_FINISHED":
            steps.append((content, db))
        elif kind == "RUN_FINISHED":
            run_fin = (content, db)
    return {"note_id": note_id, "steps": steps, "run": run_fin,
            "memory": st.content, "db": _read_db(note_id)}


async def _collect(st, hooks):
    out = []
    async for e in run(st, hooks):
        if e.type.value in ("STEP_FINISHED", "RUN_FINISHED"):
            # **事件发出来的那一刻**就读库：事后再读会把后面那些落库也算进来，
            # 于是「这一轮漏了一次落库」被下一轮补上的写遮掉（P45 #1 正是每轮漏一次）。
            out.append((e.type.value, str(e.data.get("content") or ""),
                        _read_db(st.ctx.note_id)))
    return out


# -------------------------------------------------- A. 性质闸：逐轮 ---

@pytest.mark.parametrize("mode", _save_modes(), ids=_mode_ids())
def test_挂了Save的模式_每一轮交出去的正文都跟库里逐字相同(mode):
    """P45 #1 的**性质**版：`fix` 在 `before_judge` 里改正文，改在
    `after_produce` 那一下之后。少了 `Save.after_round` 那一下，
    `STEP_FINISHED` 和 `notes.content` 就会分家——**这条闸不问是哪条判据**。
    """
    got = _drive(mode, [f"第{i}轮写的字{JUNK}" for i in (1, 2)],
                 [[1], [1]], checks=(_fix_check,))
    assert got["steps"], "一轮都没跑起来，这条闸什么都没验"
    for i, (shown, db) in enumerate(got["steps"], start=1):
        assert JUNK not in shown, f"第 {i} 轮交出去的正文里还留着要摘的东西"
        assert db == shown, (
            f"[{mode.key}] 第 {i} 轮：交出去 {len(shown)} 字，库里 {len(db)} 字——"
            f"重开 app 用户看到的是库里那一份\n  库里：{db[-60:]!r}")


@pytest.mark.parametrize("mode", _save_modes(), ids=_mode_ids())
def test_挂了Save的模式_fix_done那一支改过的正文也落库(mode):
    """`fix` 改了、复判还响、`fix_done` 说「我这件好了」——正文照样被换掉
    （`middleware/checks` 里那一支），所以同样得落库。"""
    got = _drive(mode, [f"第{i}轮写的字{JUNK}【第二件事】" for i in (1, 2)],
                 [[1], [1]], checks=(_half_fix_check,))
    for i, (shown, db) in enumerate(got["steps"], start=1):
        assert JUNK not in shown, f"第 {i} 轮的半修没生效，这条闸测的不是那一支"
        assert db == shown, f"[{mode.key}] 第 {i} 轮：半修改过的正文没落库"


@pytest.mark.parametrize("mode", _save_modes(), ids=_mode_ids())
def test_挂了Save的模式_交最好那一轮时库里也是交出去的那一份(mode):
    """P45 #1 的第二半：`loop.py` 在最后一个 `after_round` **之后**把
    `st.content` 换成 `st.best[1]`。只有 `hooks.commit` 接得住——
    而 `commit` 是**生产那条路**造出来的那一个（`_hooks_for`）。
    """
    got = _drive(mode, ["第一轮写的字", "第二轮写的字"], [[2, 1], [0, 1]],
                 checks=(), stops=())
    shown, db = got["run"]
    assert shown != got["steps"][-1][0], (
        "这份假分数没有把「交最好那一轮」摆出来，测的不是那条分支")
    assert db == shown, (
        f"[{mode.key}] 交出去的是最好那一轮，库里躺的是被丢掉的那一轮："
        f"交 {len(shown)} 字 / 库 {len(db)} 字")
    assert got["db"] == got["memory"], "收工时库里那一份跟交出去的那一份对不上"


# --------------------------------------- B. 接线闸：commit 是承重的 ---

def _body_without_docstring(fn) -> str:
    """函数的**代码**，不含 docstring（P45 那把尺子，理由同 P42 教训 #2：
    那几处 `commit` 的注释里正好写着 `store.update_note`）。"""
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    stmts = tree.body[0].body
    if (stmts and isinstance(stmts[0], ast.Expr)
            and isinstance(stmts[0].value, ast.Constant)
            and isinstance(stmts[0].value.value, str)):
        stmts = stmts[1:]
    return "\n".join(ast.unparse(s) for s in stmts)


@pytest.mark.parametrize("mode", _save_modes(), ids=_mode_ids())
def test_挂了Save的模式_它的commit走的是唯一那个写库出口(mode):
    """**名单是数出来的**：模式从 `modes.ALL` 里筛，hooks 从生产那条路造。

    两句断言守两件事：落库那一下在（不是 no-op），而且走的是
    `save.persist_if_changed` 这**一个**出口——不是自己调 `store.update_note`
    （批 16：出口自己认 `rails_off`）。
    """
    st = State(mode=mode, ctx=ToolContext(user="u1", note_id="n", note_title="t"),
               content=SEED)
    body = _body_without_docstring(type(_hooks_for(mode, st)).commit)
    assert "persist_if_changed" in body, (
        f"{mode.key} 的 commit 又变回 no-op 了——交最好那一轮落不进库")
    assert "store.update_note" not in body, (
        f"{mode.key} 的 commit 自己调 `store.update_note` 了——写库只许一个出口")


def test_数出来的那几个模式里至少有一个_不然这条闸整条是空跑():
    """**量具自检**（P42 教训 #2）：`_save_modes()` 要是筛空了，上面每一条
    参数化的测试都会变成 0 个用例——**全绿，一件事都没验**。"""
    keys = _mode_ids()
    assert keys, "一个挂 Save 的模式都没数出来，这个文件是空跑的"
    assert "note" in keys and "section" in keys, (
        f"数出来的是 {keys}——`note` / `section` 是会写用户笔记的那两个，不该漏")


def test_量具自检_读的是库不是内存():
    """**先证明尺子在量它该量的东西**：`_read_db` 得读得出「内存改了、库没改」。"""
    note = store.create_note("u1", "P47 尺子", SEED)
    note_id = note["id"] if isinstance(note, dict) else note
    assert _read_db(note_id) == SEED
    st = State(mode=modes.NOTE,
               ctx=ToolContext(user="u1", note_id=note_id, note_title="P47 尺子"),
               content=SEED + "只改内存")
    assert _read_db(note_id) == SEED, "改了 `st.content` 库里就跟着变，那读的不是库"
    from app.harness.middleware import save as save_mod
    save_mod.persist(st)
    assert _read_db(note_id) == st.content, "落库之后读回来对不上，这把尺子读错了地方"
