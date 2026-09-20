"""P45 #1：**编辑器里没有 ≠ 库里没有**——判据 `fix` 改过的正文得真的落进库。

P44 走查最重的那条（问题 #1）：智能续写跑完，探针逐 `.cm-line` 读到 119 → 119、
面板上写着「已经从正文里撤掉了」、⚑ `output_not_json` ×3，**可 `notes.content`
是 166**，尾巴就是那一整串 `{"text": …, "reason": "假模型"}`——重开 app 它就摆在正文里。

根因是**落库那一下的时机**，不是判据本身：

    save.after_produce   UPDATE notes len=101      ← 库里落的是这一份
    checks.before_judge  101 → 53                  ← `Verdict.fix` 在这儿把 JSON 摘掉
    STEP_FINISHED        len=53                    ← 前端按这一份对齐
    == memory=53  db=101

（`$S/p45/probe45.py` 的逐 hook 实拍，修之前。）

所以这不是 `output_not_json` 一条的事，是**一个类**：`note` / `section` 两个会
写库的模式上带 `fix` 的判据一共 **7 条**——`chart_restates_list` /
`charts_from_tools` / `citations_exist` / `no_echoed_text` / `no_foreign_script` /
`no_junk_tail` / `output_not_json`，条条都在 `before_judge` 里改正文。

**还有第二半**：`loop.py` 在最后一轮的 `after_round` **之后**还会动一次
`st.content`——`SHIP_BEST_ON`（`regressed` / `cost_cap` / `check_stuck`）和轮数
用尽那个 `else:` 都把正文换成 `st.best[1]`。实拍（假模型 `/regress` 档，两轮）：
交出去的是第 1 轮的 139 字，库里躺的是被明确丢掉的第 2 轮那 228 字。
那一下只有 `hooks.commit` 接得住（它在 `after_run` 之前跑，所以
`Edits.after_run` 那版 `note_revisions` 快照也跟着对）。

闸分三层（P38 / P42 / P44 一条不变）：**行为闸**跑一趟真循环读「库里那一份」，
**接线闸**单独一条断言钉住「谁在什么时候写」，**类闸**钉住那 7 条不许漏。
"""

from __future__ import annotations

import asyncio

import pytest

from app.harness import State
from app.harness.checks import shape
from app.harness.hooks.note import NoteHooks
from app.harness.hooks.section import SectionHooks
from app.harness.loop import run
from app.harness.middleware import BASE, Save
from app.harness.middleware import save as save_mod
from app.harness.tools import ToolContext
from app.harness.types import Dimension, DimensionScore, Evaluation, Mode

JSON_PARA = '{"text": "（假模型改写）这一段由假模型返回。", "reason": "假模型"}'
SEED = "这周把众筹页面的文案定稿了，3月12号上线。"


# ------------------------------------------------------------ 量具 ---

class _Writes:
    """`store.update_note` 的每一次调用，按顺序。**读库不读内存**的那个「库」。"""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, user, note_id, title, content, **kw):
        self.calls.append(content)
        return None

    @property
    def last(self) -> str:
        return self.calls[-1] if self.calls else ""


@pytest.fixture
def db(monkeypatch) -> _Writes:
    w = _Writes()
    monkeypatch.setattr(save_mod.store, "update_note", w)
    return w


class _Hooks:
    """`produce` 把这一轮的字接到正文后面——跟 `hooks/note` 的契约同一条。"""

    def __init__(self, texts: list[str], commit=None):
        self.texts = texts
        self._commit = commit

    async def prepare(self, st):
        return [], _Trace()

    async def produce(self, st):
        text = self.texts[min(st.round, len(self.texts)) - 1]
        yield text
        st.fresh = text
        st.content = (st.content + "\n\n" + text) if st.content else text

    async def commit(self, st):
        if self._commit is not None:
            await self._commit(st)


class _Trace:
    calls: list = []
    used = False
    iters = 0


def _mode(**kw) -> Mode:
    kw.setdefault("dims", (Dimension("mechanics", "..."),))
    kw.setdefault("extra_mw", (Save(),))
    return Mode(key="t", label="test", skill_scope="test_scope", **kw)


def _state(mode: Mode, content: str = SEED) -> State:
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="t"),
               request=None)
    st.content = content
    return st


def _scorer(levels_per_round):
    async def score(st):
        levels = levels_per_round[min(st.round, len(levels_per_round)) - 1]
        scores = {f"d{i}": DimensionScore(level=v, note="") for i, v in enumerate(levels)}
        status = "complete" if all(v >= 2 for v in levels) else "continue"
        return Evaluation(scores=scores, status=status,
                          weakest=None if status == "complete" else "d0")
    return score


def _drive(st, hooks, scorer, mw):
    import app.harness.loop as loop_mod
    original, loop_mod._score = loop_mod._score, scorer
    try:
        return asyncio.run(_collect(st, hooks, mw))
    finally:
        loop_mod._score = original


async def _collect(st, hooks, mw):
    return [e async for e in run(st, hooks, mw=mw)]


def _step_finished(events) -> list[str]:
    return [e.data["content"] for e in events if e.type.value == "STEP_FINISHED"]


def _run_finished(events) -> str:
    return next(e.data["content"] for e in events if e.type.value == "RUN_FINISHED")


# ------------------------------------------ A. 行为闸：库里那一份 ---

def test_判据把JSON摘掉之后_库里那一份也跟着干净(db):
    """P44 问题 #1 的定点复现，**用的是真判据 `shape.output_not_json`**。

    修之前这条断言读出来的是 `SEED + "\\n\\n" + JSON_PARA`：编辑器干净、库里脏。
    """
    mode = _mode(checks=(shape.output_not_json,), max_rounds=2)
    st = _state(mode)
    events = _drive(st, _Hooks([JSON_PARA, JSON_PARA]), _scorer([[2], [2]]),
                    mw=BASE)

    assert st.content == SEED, "内存里那份该是干净的（这一步修之前就是对的）"
    assert _step_finished(events) == [SEED, SEED], "前端按 STEP_FINISHED 对齐"
    assert JSON_PARA not in db.last, (
        "库里那一份还带着整串 JSON——重开 app 它就摆在正文里（P44 问题 #1）")
    assert db.last == st.content, "库里那一份必须跟交出去的那一份逐字相同"


def test_判据没动过的轮次_一轮只写一次库(db):
    """`after_round` 那一下**只在真的不一样时才写**。

    无条件再 `UPDATE` 一次会让 `notes.updated_at` 每轮白动两次、
    `harness_edits` 那边「用户改了没有」也跟着糊掉。
    """
    mode = _mode(checks=(), max_rounds=2)
    st = _state(mode)
    _drive(st, _Hooks(["第一轮写的字", "第二轮写的字"]), _scorer([[1], [1]]), mw=BASE)
    assert len(db.calls) == 2, f"两轮该写两次，实际 {len(db.calls)} 次：{db.calls}"


def test_写出来的字先落一次_判分那几十秒里关掉标签页不会丢(db):
    """**`after_produce` 那一下不许拿掉**（`middleware/save.py` 开头那段）。

    补 `after_round` 是为了「定稿之后再落一次」，不是为了把「先落一次」换掉：
    判分要几十秒，用户在这中间关掉标签页，这一轮写的字得还在。
    """
    mode = _mode(checks=(shape.output_not_json,), max_rounds=1)
    st = _state(mode)
    _drive(st, _Hooks([JSON_PARA]), _scorer([[2]]), mw=BASE)
    assert len(db.calls) == 2, f"该是「先落原样、再落定稿」两下，实际：{db.calls}"
    assert JSON_PARA in db.calls[0], "第一下落的就该是这一轮原样流出来的字"
    assert JSON_PARA not in db.calls[1], "第二下落的该是判据修完的那份"


def test_跑批脚本那条路一个字都不写(db):
    """`rails_off=("save",)` 照旧全挡住——新加的那一下也走同一个出口（批 16）。"""
    mode = _mode(checks=(shape.output_not_json,), max_rounds=2, rails_off=("save",))
    st = _state(mode)
    _drive(st, _Hooks([JSON_PARA, JSON_PARA]), _scorer([[2], [2]]), mw=BASE)
    assert db.calls == [], f"rails_off 的跑写了库：{db.calls}"


# --------------------------------- B. 接线闸：谁在什么时候写 ---

def test_接线洞_落库那一下排在判据改正文之后():
    """**单独一条断言钉住接线**：`Save` 得在 `after_round` 上有一下。

    `Verdict.fix` 一律在 `Checks.before_judge` 里改 `st.content`，而 `loop.py`
    的钩子顺序是 `after_produce` → `before_judge` → `after_judge` → `after_round`。
    只有 `after_produce` 一下的话，写库永远排在 fix 前面——这就是 P44 问题 #1。
    """
    assert "after_produce" in Save.hooks
    assert "after_round" in Save.hooks, (
        "`Save` 没有 `after_round` 那一下 → 判据 fix 改的正文永远落不进库")
    # 钩子顺序是 `loop.py` 写死的（那个文件不许改循环结构），这里把它当契约钉一遍：
    import inspect

    import app.harness.loop as loop_mod
    body = inspect.getsource(loop_mod.run)
    i_produce = body.index('"after_produce"')
    i_judge = body.index('"before_judge"')
    i_round = body.index('"after_round"')
    i_step_finished = body.index("Event.step_finished")
    assert i_produce < i_judge < i_round < i_step_finished, (
        "循环的钩子顺序变了——`after_round` 不再是「这一轮定稿」那一下")


def test_接线洞_交最好那一轮发生在最后一个after_round之后(db):
    """**这一条证明 `after_round` 一个人接不住**（所以 `commit` 是承重的）。

    `loop.py` 轮数用尽那个 `else:` 把 `st.content` 换成 `st.best[1]`——
    那是**最后一轮 `after_round` 跑完之后**的事。这里用一份「第 2 轮比第 1 轮差」
    的假分数把它摆出来：`RUN_FINISHED` 交的是第 1 轮，最后一次 `after_round`
    写进库的是第 2 轮。
    """
    mode = _mode(checks=(), max_rounds=2)
    st = _state(mode)
    events = _drive(st, _Hooks(["第一轮", "第二轮"]), _scorer([[2, 1], [0, 1]]), mw=BASE)
    shipped = _run_finished(events)
    assert shipped != _step_finished(events)[-1], (
        "这份假分数没有把「交最好那一轮」摆出来，测的不是那条分支")
    assert db.last != shipped, (
        "`after_round` 居然接住了——那这条闸测的不是它该测的东西")


def test_交最好那一轮时_commit把它落进库(db):
    """接上一条：`hooks.commit` 把那一下补上。

    `NoteHooks.commit` 走的是 `save.persist_if_changed`，这里直接调它
    （`_Hooks` 是假的，没有 note 那一套）。
    """
    mode = _mode(checks=(), max_rounds=2)
    st = _state(mode)
    events = _drive(st, _Hooks(["第一轮", "第二轮"], commit=NoteHooks.commit.__get__(
        NoteHooks(polish=False, spine="", beats=[], profile=[]))),
        _scorer([[2, 1], [0, 1]]), mw=BASE)
    assert db.last == _run_finished(events), (
        "交出去的是最好那一轮，库里还是被丢掉的那一轮（P45 #1 的第二半）")


def _body_without_docstring(fn) -> str:
    """函数的**代码**，不含 docstring。

    **先证明量具在量它该量的东西**（P42 教训 #2）：这两处 commit 的注释里
    正好写着「不自己调 `store.update_note`」，拿整段源码去搜那个名字
    只会读出「它自己调了」——那是量具的毛病，不是产品的。
    """
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    fn_node = tree.body[0]
    stmts = fn_node.body
    if (stmts and isinstance(stmts[0], ast.Expr)
            and isinstance(stmts[0].value, ast.Constant)
            and isinstance(stmts[0].value.value, str)):
        stmts = stmts[1:]
    return "\n".join(ast.unparse(s) for s in stmts)


def test_量具自己先过一遍_docstring不算代码():
    """上面那把尺子的自检：把 docstring 摘掉之后，剩下的只有真的执行的那几行。"""
    def _样本():
        """这句注释里有 store.update_note，它不算代码。"""
        return 1
    body = _body_without_docstring(_样本)
    assert "store.update_note" not in body
    assert "return 1" in body


def test_note和section的commit都不是no_op了():
    """**类闸**：两个会写库的 hooks 一个都不许漏。

    这两处原来的 docstring 写着「Save handles per-round persistence…
    What is left is nothing」——P45 实拍出来那句话不成立。
    """
    for hooks_cls in (NoteHooks, SectionHooks):
        body = _body_without_docstring(hooks_cls.commit)
        assert "persist_if_changed" in body, (
            f"{hooks_cls.__name__}.commit 又变回 no-op 了——交最好那一轮落不进库")
        assert "store.update_note" not in body, (
            f"{hooks_cls.__name__}.commit 自己调 `store.update_note` 了——"
            "写库只许有一个出口，由它自己认 rails_off（批 16）")


def test_commit那一下也认rails_off(db):
    mode = _mode(checks=(), rails_off=("save",))
    st = _state(mode)
    st.content = "换过的正文"
    asyncio.run(NoteHooks(polish=False, spine="", beats=[], profile=[]).commit(st))
    assert db.calls == [], "rails_off 的跑在 commit 里写了库"


def test_没变就不写(db):
    st = _state(_mode(checks=()))
    st.bag["saved_content"] = st.content
    assert save_mod.persist_if_changed(st) is False
    assert db.calls == []
    st.content = st.content + "又写了一句"
    assert save_mod.persist_if_changed(st) is True
    assert db.calls == [st.content]


# --------------------------------------------- C. 类闸：那 7 条 ---

def _checks_with_fix(mode: Mode) -> set[str]:
    import inspect
    out = set()
    for chk in mode.checks:
        try:
            src = inspect.getsource(chk)
        except (OSError, TypeError):            # pragma: no cover - 内建 / lambda
            continue
        if "fix=" in src or "fix_done=" in src:
            out.add(getattr(chk, "__name__", str(chk)))
    return out


def test_会写库的模式上带fix的判据是这7条_一条都不许静默多出来():
    """**这是个类，不是一条**（P44 那句话）。

    `note` / `section` 是仅有的两个挂了 `Save` 的模式；它们的 `checks` 里
    带 `fix` 的判据全都在 `before_judge` 里改正文，也就全都吃 P45 #1 这个洞。
    这张名单变了，得有人重新想一遍「落库那一下够不够晚」——而不是悄悄多一条。
    """
    from app.harness import modes
    expected = {
        "chart_restates_list", "charts_from_tools", "citations_exist",
        "no_echoed_text", "no_foreign_script", "no_junk_tail", "output_not_json",
    }
    saving = [m for m in (modes.NOTE, modes.SECTION)
              if any(getattr(x, "name", "") == "save" for x in m.extra_mw)]
    assert len(saving) == 2, "挂 Save 的模式不再是 note / section 那两个了"
    for m in saving:
        assert _checks_with_fix(m) == expected, (
            f"{m.key} 上带 fix 的判据名单变了：{sorted(_checks_with_fix(m))}")


def test_每一条fix判据修完的正文都落得进库(db):
    """名单上那 7 条走的是**同一条** `middleware/checks` 路径——这里用一条
    合成判据把那条路径本身测死：`fix` 改了什么，库里就得是什么。

    合成而不是把 7 条真判据各造一份素材：那条路径只有一条，而素材造七份
    只会测出「我会不会造素材」。真判据那一侧由上面
    `test_判据把JSON摘掉之后_库里那一份也跟着干净` 用 `output_not_json` 钉着。
    """
    from app.harness.types import Verdict

    def 砍掉尾巴(st):
        if "垃圾尾巴" not in st.content:
            return None
        return Verdict("mechanics", "尾巴是垃圾",
                       fix=lambda text: text.replace("垃圾尾巴", "").rstrip())

    mode = _mode(checks=(砍掉尾巴,), max_rounds=1)
    st = _state(mode)
    _drive(st, _Hooks(["正经内容垃圾尾巴"]), _scorer([[2]]), mw=BASE)
    assert "垃圾尾巴" not in db.last, "fix 改完的正文没落进库"
    assert db.last == st.content
