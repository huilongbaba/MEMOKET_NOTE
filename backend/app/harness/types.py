"""Every type a harness is built from, in one file.

Nothing here knows about writing, notes, or KITE. A harness is assembled by
picking a ``Mode`` and supplying three callbacks; the loop and the middleware
chain do the rest.

Two groups, and they used to live apart:

* **The framework**: ``Mode`` (what this run wants), ``Hooks`` (the three
  callbacks each harness writes), ``Middleware`` (capabilities), ``Check`` /
  ``Verdict`` (the code-judged half of 判据), ``StopCondition``.
* **Scoring**: ``Dimension`` / ``DimensionScore`` / ``Evaluation`` -- the
  model-judged half. These were in a separate installable package
  (``writer_harness``) built to be open-sourced one day. It had exactly one
  consumer, and the cost of the extra concept was that nobody could tell
  what it was. ``Mode.dims`` is a ``tuple[Dimension, ...]`` and ``State.ev``
  is an ``Evaluation`` -- they were always framework types, so they live
  with the rest of them now.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import (TYPE_CHECKING, AsyncIterator, Callable, Literal, Protocol,
                    runtime_checkable)


if TYPE_CHECKING:                       # pragma: no cover
    from ..agent_loop import ToolTrace
    from .events import Event
    from .state import State


class Hooks(Protocol):
    """The three things that genuinely differ between harnesses.

    Everything else -- accumulating facts, deduping, scoring, best-of,
    stopping -- is shared. If a fourth thing shows up here, stop and check
    whether it's really a hook or a middleware in disguise.

    **This is a contract, not an implementation.** The opposite of middleware:
    there, one written implementation is shared by every harness; here, every
    harness writes its own. That asymmetry is why middleware can default to
    on and hooks cannot -- an empty contract has no default to give.

    Implementations *may* still be shared. note_harness and writing_plan both
    fall back to keyword retrieval when the tool loop fails; if that turns out
    to be the only thing their ``prepare`` has in common, it belongs in one
    shared base rather than copied twice.
    """

    async def prepare(self, st: "State") -> tuple[list[str], "ToolTrace"]:
        """Gather material. Returns (facts found this round, tool trace).

        Accumulation and trimming are *not* this hook's job -- the ``Facts``
        middleware owns those, precisely so that no harness can accidentally
        do only half of it (that mistake shipped four separate times).
        """

    def produce(self, st: "State") -> AsyncIterator[str]:
        """Generate, streaming pieces, **and update ``st.content``**.

        Why updating content belongs here and not in the loop: the merge rule
        differs per harness.

          * block generation: ``st.content = <the new block>``  (replace)
          * long-form: ``st.content = join(st.content, <what was written>)``

        The loop only accumulates pieces into ``st.fresh`` (for events and the
        no-progress stop condition). Putting the merge in the loop would mean
        an ``if mode.xxx`` there, which is exactly what this design forbids.
        """

    async def commit(self, st: "State") -> None:
        """Finish the run. **Not per-round persistence** -- that's the ``Save``
        middleware. This is for run-level wrap-up, e.g. writing_plan updating
        its tracking note."""


class Middleware(Protocol):
    """A capability package. Implement the hooks you need, omit the rest.

    Hook names follow *our* loop's phases, not LangChain's ``before_model`` --
    their loop is model-centric, ours is produce-then-judge.

    **Two shapes are allowed**, decided by whether it emits events:

      * emits events -> ``async def hook(st) -> AsyncIterator[Event]`` (yield)
      * emits nothing -> ``async def hook(st) -> None`` (plain async def)

    ``_fire`` tells them apart with ``inspect.isasyncgen``. Without this, a
    middleware that emits nothing would be forced to write ``return; yield``
    just to become a generator.
    """

    name: str

    # lifecycle: once per run
    async def before_run(self, st: "State") -> AsyncIterator["Event"]: ...
    async def after_run(self, st: "State") -> AsyncIterator["Event"]: ...

    # lifecycle: once per round
    async def before_round(self, st: "State") -> AsyncIterator["Event"]: ...
    async def after_prepare(self, st: "State") -> AsyncIterator["Event"]: ...
    async def before_produce(self, st: "State") -> AsyncIterator["Event"]: ...
    async def after_produce(self, st: "State") -> AsyncIterator["Event"]: ...
    async def before_judge(self, st: "State") -> AsyncIterator["Event"]: ...
    async def after_judge(self, st: "State") -> AsyncIterator["Event"]: ...
    async def after_round(self, st: "State") -> AsyncIterator["Event"]: ...

    # interception: can call the handler more than once (retry), skip it
    # (short-circuit), or rewrite request/response around it
    async def wrap_prepare(self, st: "State", handler) -> tuple[list[str], "ToolTrace"]: ...
    def wrap_produce(self, st: "State", handler) -> AsyncIterator[str]: ...


@dataclass(frozen=True)
class Verdict:
    """What a ``Check`` says when it fires.

    ``fix`` is the linter's ``--fix``: when the repair is unambiguous and
    needs no semantic judgement, just do it. Heading depth is fixable (sink
    everything one level, text untouched); "too many subheadings" is not
    (which one to drop is a judgement call). That boundary was established by
    running both against real failing output, not by reasoning about it.
    """

    dimension: str                                  # which dimension to fail
    message: str                                    # what the model is told
    fix: Callable[[str], str] | None = None         # pure function, or None
    # **一条判据管着不止一件事时，「这个 fix 管用了没有」不能拿整条判据来问**（P23 #1）。
    # `done_criteria` 一条「每个节点有日期、有出处」同时判两件事：`fix` 把没日期的句子标上
    # 「（日期待补）」之后，日期那件事好了、出处那件事还欠着——整条判据照样命中，
    # 原来那句 `if not check(probe)` 就把标好的正文整个丢掉了（P18/P19 三批真跑里每一轮都会这样）。
    # 给了这个的，就用它判「我管的那件事修好了没有」，**别的没好照旧按新的那条说**。
    # 仍然是纯函数（吃修完的正文），所以「fix 没真修好就不许改正文」这条纪律一个字没松。
    fix_done: Callable[[str], bool] | None = None


# Code decides. Pure function, read-only, no I/O -- so it can be unit-tested
# by constructing a string, and so a Check can never be the thing that breaks
# a run.
Check = Callable[["State"], Verdict | None]

# Returns a stop reason, or None to keep going. Composable: the loop ORs a
# built-in set with Mode.stop_when (Vercel AI SDK's ``stopWhen`` shape).
StopCondition = Callable[["State"], str | None]


@dataclass(frozen=True)
class Mode:
    """Everything that makes one feature different from another.

    Must stay pure data: skills get layered on top at runtime by producing a
    modified copy, so a Mode can't hold anything only code could supply.
    """

    key: str
    label: str
    task: str = ""
    # 产出阶段活动条上的动词：实拍「智能插图：在写…」——画图不是写。默认「在写」。
    verb: str = "在写"

    # Tool authorisation. A ``group`` bundles tools by domain; ``exclude``
    # removes individual ones. If the same tool keeps getting excluded by
    # several Modes, the grouping is wrong -- fix the group, don't patch it
    # here (there's a test for that).
    groups: tuple[str, ...] = ("memory",)
    # A second gather round restricted to these groups, run only when the
    # first round produced nothing from them.
    #
    # Measured: on a note containing a table, the model spent all three tool
    # iterations on list_tables / aggregate_table / correlate_columns. It
    # found every number and drew no chart, then wrote "the chart code was not
    # returned by the tools". The iteration budget is shared and exploration
    # naturally comes first, so charting is always the thing that gets
    # squeezed out. A dedicated round does not compete for that budget.
    focus_groups: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    # Judgement, two kinds. Both are the system's -- skills cannot touch them.
    dims: tuple[Dimension, ...] = ()
    checks: tuple[Check, ...] = ()

    # Which skill scope matches here. Empty means user skills never auto-inject
    # for this feature -- which is a bug waiting to happen, so a test asserts
    # every Mode fills it in.
    skill_scope: str = ""

    stop_when: tuple[StopCondition, ...] = ()
    extra_mw: tuple[Middleware, ...] = ()
    # 跑之前的确定性门槛：返回一句「为什么现在做不了」就直接 blocked，一次模型调用都不花。
    # 实拍数据可视化：光标那段没有数字也没有表，模型硬画了三轮用户序号 / 0-1 状态图，89 秒。
    precheck: Callable[["State"], str | None] | None = None

    # Turning off a BASE capability has to be written down. Not because it is
    # never right, but because the four times a harness ended up missing one,
    # nobody had decided anything -- it was simply never wired in. A test
    # asserts this stays empty, so switching one off means arguing for it in
    # a pull request.
    rails_off: tuple[str, ...] = ()

    # Pause at the end of each round so the user can accept or reject what
    # was just written. Off by default and set per request, not per feature:
    # whether to review is the user's call, and the same person wants it on a
    # document that matters and off on a scratch note.
    review_each_round: bool = False
    max_rounds: int = 3
    fact_budget: int = 40             # how many accumulated facts to keep
    context_keep_last: int = 4000     # chars of content kept verbatim for continuation
    max_tokens: int = 1400


# ------------------------------------------------------------ 打分 ---
# 判据的模型判那一半用到的类型。代码判的那一半是上面的 Check / Verdict。

Status = Literal["continue", "complete", "blocked"]


@dataclass(frozen=True)
class Dimension:
    """One scored axis of "what good means here", supplied by the caller.

    ``guidance`` is rendered directly into the scoring prompt -- write it as
    a sentence describing what a low vs. high score looks like for this
    dimension, not as a bare label. The model scores against this text, not
    against any assumption baked into this package.

    ``binary`` 把这一维压成两档（0 / 2），判词和解析两侧一起管
    （`checks/rubric.py`）。**只有现场生成的 checklist 条目在用它**
    （计划 6.1 / [IND] §6②）：二元 pass/fail 逼着先定义清楚「什么叫可以接受」，
    而我们的反面证据是 `non_repetition` 九批 2160 次实测**稳在 1.3 下不来**
    ——中间那档吸收了所有说不清的情况，既不推动修改也不放行。
    **写死的那 25 维一维都没改**：计划 7.4 写着「先按维度量一致率再决定改
    哪几维」，那一步（阶段 9.2）还没做。
    """

    name: str
    guidance: str
    binary: bool = False


@dataclass(frozen=True)
class DimensionScore:
    """One dimension's result for one evaluate() call.

    ``level`` is 0 (insufficient) / 1 (partial) / 2 (meets the bar) -- coarse
    on purpose. A finer scale invites false precision from a single LLM call;
    three levels is enough to drive "what's weakest" without pretending the
    judgment is more exact than it is.
    """

    level: int
    note: str


@dataclass(frozen=True)
class Evaluation:
    """Result of one evaluate() call."""

    scores: dict[str, DimensionScore]
    status: Status
    weakest: str | None = None
    blocked_reason: str | None = None


@dataclass(frozen=True)
class DupHint:
    """One candidate near-duplicate pair found by find_repeats()."""

    a: str
    b: str
    similarity: float


@dataclass(frozen=True)
class RunRecord:
    """One completed (or abandoned) harness run, for RunHistoryStore."""

    key: str
    status: Status
    rounds: int
    final_scores: dict[str, int]
    weak_dimensions: list[str] = field(default_factory=list)
    timestamp: str = ""
    # **怎么停的**（max_rounds / stalled / regressed / complete / blocked / …），
    # 跟 `status`（打分模型的裁决）是两个不同的问题。分开记之前，
    # 实测 39 次跑里 54% 的 `status` 都是 `continue`，而那是三种完全不同的失败混在一起。
    stopped: str = ""
    # 这次跑的 id（留空 = 存储层自己生成）。存在的理由是**让三张表能 join**：
    # `harness_runs` 和 `harness_rounds` 在这之前没有任何连接键。
    run_id: str = ""
    # 这次跑一共花了多少：入 + 出 token、几次调用（计划 12.3）。
    # 记在这儿而不是让分析侧拿时间窗口重建 `llm_usage`——那份重建在两次跑
    # 重叠时会把账算到隔壁（批 23 实测 158 次跑里 11 对相邻跑重叠）。
    tokens: int = 0
    calls: int = 0


@runtime_checkable
class LLMClient(Protocol):
    """Anything that can turn a chat-style message list into text. Matches
    the common OpenAI-compatible `complete(messages, **kw) -> str` shape
    closely enough that most existing app-side LLM wrappers satisfy this
    with a one-line adapter, without this package caring which provider,
    auth scheme, or model is behind it."""

    async def complete(self, messages: list[dict], **kwargs) -> str: ...


@runtime_checkable
class RunHistoryStore(Protocol):
    """Persists completed runs and retrieves recent ones for a given key
    (whatever the host app's model of "same recurring task" is -- a note
    id, a user id, a task type -- this package doesn't prescribe it).
    Optional: callers that don't care about cross-run history simply never
    construct one."""

    def record(self, run: RunRecord) -> None: ...

    def recent(self, key: str, limit: int = 3) -> list[RunRecord]: ...
