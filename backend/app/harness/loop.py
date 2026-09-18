"""The loop. One copy, hardcoded, shared by every harness.

All 12 frameworks surveyed hardcode their loop; none makes the step sequence
configurable. We had three hand-copied loops and paid for it four times with
"one harness has it, the other doesn't" bugs.

Read the loop and you'll notice two absences, both deliberate:

* **No middleware is named in here.** The chain is data; the loop only knows
  hook names. Adding a capability never touches this file.
* **No ``if mode.xxx``.** Differences are expressed as Mode fields, hooks and
  middleware. The first branch on a mode key means the design failed.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
from typing import AsyncIterator, Sequence

from .checks.rubric import evaluate

from . import adapter as harness_adapter
from . import score_context
from .events import CUSTOM_DEDUP, CUSTOM_EVALUATE, CUSTOM_INSERT_AT, CUSTOM_SCRUB, CUSTOM_WARNING, Event
from .middleware import BASE, verify
from .state import State
from .types import Hooks, Middleware



async def run(st: State, hooks: Hooks,
              mw: Sequence[Middleware] | None = None) -> AsyncIterator[Event]:
    """Drive one run to completion.

    Yields AG-UI events throughout; the caller turns them into SSE frames.
    """
    chain = tuple(mw if mw is not None else BASE) + tuple(st.mode.extra_mw)
    chain = tuple(m for m in chain
                  if getattr(m, "name", "") not in st.mode.rails_off)
    verify(chain)       # declared ordering deps hold; fails loudly if not
    reason, committed = "max_rounds", False

    yield Event.run_started(st.mode.key, st.mode.label)
    try:
        async for e in _fire(chain, "before_run", st):
            yield e
        # 开跑时正文里已经有什么。**判据看的是整篇正文**，而整篇里有很多东西
        # 不是这次跑写的——用户自己写的、上一次跑留下的。分不清这两者的判据
        # 会去打自己没做过的事（第 601 轮的占位符、第 604 轮被删掉的两张图）。
        st.bag["content_at_start"] = st.content

        # 门槛：规则就能判「现在做不了」的，别让模型试三轮
        pre_blocked = ""
        if st.round == 0 and st.mode.precheck is not None:
            pre_blocked = st.mode.precheck(st) or ""
        if pre_blocked:
            reason = "blocked"

        # **Counts on from where the run left off**, not from 1. ``st.round``
        # is rounds completed, which is zero for a fresh State and non-zero
        # for a resumed one. Restarting at 1 would re-arm every guard that
        # asks "is this the first round" -- Revise skips round 1 because
        # nothing is written yet, and on a resumed run that is false.
        for st.round in range(st.round + 1, 0 if pre_blocked else st.mode.max_rounds + 1):
            if st.request is not None and await st.request.is_disconnected():
                raise asyncio.CancelledError
            yield Event.step_started(st.round, st.mode.label)
            async for e in _fire(chain, "before_round", st):
                yield e

            # -- 1. gather -------------------------------------------------
            # Each step announces itself. The tool loop and the scoring call
            # each take tens of seconds, and without this the label sits on
            # "writing" through all of it -- the interface looks hung exactly
            # when the run is doing its slowest work.
            yield Event.activity(f"{_who(st)}：在看要用哪些材料…")
            with _step("tools"):
                st.facts_new, st.trace = await _wrap_prepare(chain, hooks.prepare, st)
            async for e in _fire(chain, "after_prepare", st):
                yield e

            # -- 2. produce ------------------------------------------------
            # One message per round, START/CONTENT*/END strictly paired: the
            # AG-UI state machine rejects two STARTs in a row, and a retrying
            # wrap_produce has to open a *new* message rather than continue
            # the old one (deltas already sent can't be taken back).
            async for e in _fire(chain, "before_produce", st):
                yield e
            yield Event.activity(f"{_who(st)}：{st.mode.verb}…")
            st.fresh = ""
            mid = f"r{st.round}"
            yield Event.text_start(mid)
            announced = False
            async for piece in _wrap_produce(chain, hooks.produce, st):
                # 定向续写：produce 在第一个 delta 之前就把落点写进 bag，这里先
                # 告诉前端往哪插，再发正文——不然它只能追加到文末再等轮末对齐跳一下。
                if not announced:
                    announced = True
                    placed = st.bag.get("insert_at")
                    if placed and placed.get("pos") is not None:
                        yield Event.custom(CUSTOM_INSERT_AT, placed)
                st.fresh += piece
                yield Event.text_content(mid, piece)
            yield Event.text_end(mid)
            # 续写收尾时服务端删掉的元话语句子（hooks/note._scrub_and_record）：告诉客户端，它本地也删同一句
            for sentence in st.bag.pop("scrubbed", None) or []:
                yield Event.custom(CUSTOM_SCRUB, {"round": st.round, "sentence": sentence, "why": "元话语"})
            # 流给客户端之后又被剥掉的段落 / 标题行（重复、模型自己写的标题）：客户端删同一段
            for para in st.bag.pop("dedup", None) or []:
                yield Event.custom(CUSTOM_DEDUP, {"round": st.round, "paragraph": para})
            async for e in _fire(chain, "after_produce", st):
                yield e

            # -- 3. judge: cheap first ------------------------------------
            # Checks run in before_judge and may set skip_judge. A scoring
            # call costs tens of seconds; if a deterministic rule already
            # knows the answer, paying for it is pure waste.
            async for e in _fire(chain, "before_judge", st):
                yield e
            if not st.skip_judge:
                yield Event.activity(f"{_who(st)}：在核对…")
                with _step("judge"):
                    st.ev = await _score(st)
                if st.ev is None:
                    # An unjudged round counts towards the stall net. A
                    # one-off scoring failure recovers next round; repeated
                    # failure is indistinguishable from being stuck, and one
                    # safety net for both beats inventing a second policy.
                    st.bag["no_change_rounds"] = st.bag.get("no_change_rounds", 0) + 1
            yield Event.custom(CUSTOM_EVALUATE, _ev_payload(st))
            async for e in _fire(chain, "after_judge", st):
                yield e
            async for e in _fire(chain, "after_round", st):
                yield e

            yield Event.step_finished(st.round, st.content)

            hit = _stop(st)
            if hit:
                reason = hit
                # 这一轮比最好的那轮差、提前停：交的得是最好的那轮，不是这一轮
                if hit == "regressed" and st.best is not None:
                    st.content = st.best[1]
                break
            st.steer = _steer(st)
            # The next round needs last round's diagnosis, and ``st.ev`` is
            # about to be cleared so no stop condition can act on a stale
            # score. Keeping the weak dimension **and the scorer's own words**
            # matters: passing only the name tells the revision pass "watch
            # for repetition" without saying what is repeating, and repetition
            # here is semantic -- difflib finds nothing, so the pass would
            # have no candidate at all.
            st.bag["focus"] = st.ev.weakest if st.ev else ""
            st.bag["focus_note"] = _weak_note(st)
            # **这里曾经还写过一个 `last_scores`（上一轮每个维度的分数），
            # 全仓没有任何一处读它——第 765 轮删掉了。** 留个注释在原地，
            # 是因为下一个看到「打分器不知道上一轮打了多少」的人，很可能会
            # 好心地把它接上去。
            #
            # **不要把上一轮的分数喂给这一轮的打分器。** LLM 评委有实测的
            # anchoring bias（Anchoring Bias in LLM-as-a-Judge）：先给一个
            # 参考分，评委的判断会被那个数拖过去，而不是重新读一遍正文。
            # 那会毁掉两件我们正在依赖的事：① `_no_progress` / `_regressed`
            # 都在比「这一轮 vs 最好那一轮」的排名，锚定之后分数只会平滑地
            # 跟着上一轮走，两条停机规则同时失灵；② `Repair` 判「修完动没动
            # 分」靠的正是两轮之间独立打出来的分，锚上了就永远读成「修复
            # 有效」，一路修到轮数用完。
            #
            # 要传给下一轮的是**诊断**（`focus`/`focus_note` 那两行，进修订
            # prompt），不是**分数**。诊断说的是「哪里坏了」，分数说的是
            # 「上次判了几分」——只有前者能让下一轮做事。
            st.ev, st.skip_judge = None, False
        else:
            # Ran out of rounds without ever meeting the bar. "Never met the
            # bar" is precisely when the last round is least likely to be the
            # best one -- ship the best instead.
            if st.best is not None:
                st.content = st.best[1]

        st.stopped = reason
        await hooks.commit(st)
        committed = True
        async for e in _fire(chain, "after_run", st):
            yield e
        yield Event.run_finished(
            st.content, reason,
            pre_blocked or (st.ev.blocked_reason if st.ev and reason == "blocked" else ""),
            _pause(st, reason))

    except asyncio.CancelledError:
        raise                       # persistence happens in finally
    except Exception as exc:        # noqa: BLE001
        yield Event.run_error(f"{type(exc).__name__}: {exc}")
    finally:
        # Losing five rounds of writing because round six blew up is the
        # worst possible failure. Shield it: after a CancelledError, a plain
        # ``await`` can be cancelled again before it finishes.
        if not committed and st.content:
            with contextlib.suppress(Exception):
                await asyncio.shield(_commit(hooks, st))


async def _commit(hooks: Hooks, st: State) -> None:
    await hooks.commit(st)


@contextlib.contextmanager
def _step(name: str):
    """把这一步的模型调用单独记账。

    `main.py` 按 HTTP 路由打 `ctx_feature` 标，于是一次跑里的续写、打分、
    工具规划、修订**全叫同一个名字**（`note-harness/run`）——
    「打分占了多少预算」这个问题因此答不出来
    （docs/harness-effect-plan.md ⑤）。这里在原标签后面缀一段步骤名，
    退出时还原，所以嵌套和异常都不会串味。
    """
    from ..util import llm as _llm
    base = _llm.ctx_feature.get() or ""
    token = _llm.ctx_feature.set(f"{base}:{name}" if base else name)
    try:
        yield
    finally:
        _llm.ctx_feature.reset(token)


def _who(st) -> str:
    """活动条的主语：第二轮起带轮次。实拍数据可视化跑到第 2 轮又显示「在看要用哪些材料…」，
    看起来像卡在开头没动。"""
    return st.mode.label if st.round <= 1 else f"{st.mode.label} · 第 {st.round} 轮"


def _pause(st: State, reason: str) -> str:
    """Freeze the run if it stopped to wait for the user; return the run id.

    Everything the next round needs is in ``State``, so pausing is one write
    and resuming is one read -- the loop itself has no idea this happened.
    """
    if reason != "awaiting_review":
        return ""
    from ..database import store
    from . import snapshot

    run_id = store.save_snapshot(st.ctx.user, st.ctx.note_id, st.mode.key,
                                 st.round, snapshot.dumps(st))
    store.prune_snapshots(st.ctx.user)
    return run_id


async def _score(st: State):
    """Score the round, or give up on scoring it.

    **A failed scoring call must not end the run.** Measured under sustained
    load on the local model: a single call passed the 300s timeout, the
    exception escaped the SSE generator, and the client saw the connection
    cut rather than an error event -- with every round written so far still
    unsaved on that path. Returning ``None`` means the round is simply
    unjudged: no stop condition fires, BestOf ranks it below everything, and
    the next round proceeds.

    **解析失败走的是同一条路**（第 766 轮）。在那之前它是条静默的岔路：
    `_extract_json` 解析不出来 → 每个维度 `level=0` → 一份"全 0 分"的
    `Evaluation` 照常返回，这里一个异常都没有，于是下游把它当真分数用
    （`Repair` 排 `cleanup_only`、`BestOf` 按 `(0, 0.0)` 排名、`_regressed`
    读成质量跌到谷底）。`evaluate()` 现在为这一档抛 `ScoreParseError`，
    被下面这个 `except` 接住 → `None`。**「没打上分」只有一种表示法。**
    """
    try:
        return await _evaluate(st)
    except Exception:                                  # noqa: BLE001
        # ScoreParseError（解析失败）和超时/连接断在这里是同一件事：
        # 这一轮没有分数可用。不分开处理是有意的——上层要是拿到两种
        # "没判"，`rank()` / 停机 / 记账每一处都得各判一次。
        return None


async def _evaluate(st: State):
    """把这一轮该看的东西交给打分器。

    `context` 是两部分拼的：**这次跑的 `score_context`**（长文两条 harness 由
    router 装，六个 block 模式由 `score_context.for_block` 装——批 8 之前它们
    一个都没有）**加上这次跑累积的材料 `st.facts`**。

    材料这一份在批 8 之前**从来没传过**，而 `material_use` /
    `factual_grounding` / `data_grounding` / `numbers_from_tools` 四条判词都
    明写着对着材料判——`_MATERIAL_USE` 甚至写着「没给材料就算达标」，所以它
    在生产里打的满分是判词规定的正确行为，说明不了这一维灵不灵
    （台账批 6 ②、批 7 下一步①）。

    传的必须是 `st.facts`（这次跑累积的那一份），**不是在这儿重新检索一遍**：
    重新检索出来的是第三批事实，打分器会拿它去判正文，报「知识库里查无此事」，
    而那一句正是写作那一步刚用过的材料。

    **材料走 `tail_context`，排在 `[Content]` 之后**（批 16 / 计划外发现 ①）。
    它每一轮都在长，排在正文前面会让前缀缓存的断点落在正文之前——批 15 实测
    judge 那一路命中率恒 **0.0%**。拆成前后两份的是
    `score_context.split_for_prompt`，**生产和灵敏度 bench 共用它**。
    """
    ctx, tail = score_context.split_for_prompt(
        score_context.with_material(st.bag.get("score_context"), st.facts))
    return await evaluate(
        harness_adapter.AppLLMClient(),
        content=st.content,
        dimensions=list(st.mode.dims),
        dup_hints=st.bag.get("dup_hints") or [],
        context=ctx,
        tail_context=tail,
    )


def _ev_payload(st: State) -> dict:
    if not st.ev:
        return {"round": st.round, "status": "unknown", "scores": {}}
    return {
        "round": st.round,
        "status": st.ev.status,
        "weakest": st.ev.weakest,
        "scores": {k: {"level": s.level, "note": s.note}
                   for k, s in st.ev.scores.items()},
    }


def _weak_note(st: State) -> str:
    """The scorer's sentence about the weakest dimension, on its own."""
    if not st.ev or not st.ev.weakest:
        return ""
    score = st.ev.scores.get(st.ev.weakest)
    return score.note if score else ""


def _steer(st: State) -> str:
    """The weakest dimension's own words, carried into the next round.

    Passing just the dimension *name* was tried and failed: the next round
    knows which axis is weak but not what's actually wrong with it.
    """
    if not st.ev or not st.ev.weakest:
        return ""
    score = st.ev.scores.get(st.ev.weakest)
    return f"{st.ev.weakest}: {score.note}" if score else ""


# -- stop conditions --------------------------------------------------------
# Composable and OR-ed, like Vercel AI SDK's ``stopWhen``. Pure functions,
# read-only -- a stop condition that mutates state would make "why did it
# stop" unanswerable.

def _complete(st: State) -> str | None:
    return "complete" if st.ev and st.ev.status == "complete" else None


def _blocked(st: State) -> str | None:
    return "blocked" if st.ev and st.ev.status == "blocked" else None


def _no_progress(st: State) -> str | None:
    """Nothing changed this round.

    A round can make progress without producing text: a cleanup round writes
    nothing and repairs what is already there. Counting that as no progress
    would stop the run exactly when the repair is working.
    """
    if st.fresh.strip() or st.bag.get("revisions_applied"):
        return None
    return "no_progress"


def _regressed(st: State) -> str | None:
    """已经接近合格，这一轮反而更差：别再跑了，交最好的那轮。

    实拍生成表格：第 1 轮出了一张完整的表（三个维度两个达标），第 2 轮模型写了句「[tool call
    needed]」没表，第 3 轮还是没表——后两轮各花一次模型调用，最后交的仍是第 1 轮。规则：最好的一轮
    只差一个维度没达标、且这一轮排名比它低，就停（reason=regressed，best_of 会把最好的那轮交出去）。
    第一轮不会触发（还没有「最好」可比）。

    **代码判据打回的那一轮不算「更差」。** 判据命中时会伪造一份只有一个维度、
    分数 0 的 Evaluation（middleware/checks.py），它的 `rank()` 是 (0, 0.0)——
    跟真打分出来的分数向量根本不可比。不排除它的话，任何一条判据在第二轮响一下，
    就会被读成「从接近合格跌到谷底」，整节当场收工。第 605 轮真跑实拍：硬件那一节
    第 1 轮六维只差一项，第 2 轮一张手写 mermaid 被判据拦下 → `regressed`，578 字
    交卷，剩下两轮没跑。判据说的是「这一轮有个确定的毛病要修」，不是「质量退步了」。
    """
    best = st.best
    if st.skip_judge:
        return None
    # **没打上分的一轮不算「更差」**（第 766 轮，计划 1.7 的另一半）。
    # 上面那行 `skip_judge` 挡的是「判据短路了，这一轮没打分」，而打分**调用
    # 失败**（超时 / 断连 / 返回体解析不出分数）走的是另一条路：`st.ev` 是
    # None，`rank()` 返回 `(-1, -1.0)`，一比就比最好那轮低 → 当场 `regressed`
    # 收工。同一件事（这一轮没判过）只挡住了一半。
    #
    # 后果跟 `skip_judge` 那条注释写的是同一种：最好那轮「只差一个维度」正是
    # 这条规则的武装条件，也正是**最不该在这时候收工**的时刻——一次接口抖动
    # 就把剩下的轮数全省掉了。`_score()` 的 docstring 里本来就写着「返回 None
    # 意味着这一轮只是没判：没有停机条件会触发」，这行让那句话真的成立。
    if st.ev is None:
        return None
    if _coverage_unmet(st):
        return None
    if best is None or not st.mode.dims or st.round >= st.mode.max_rounds:
        return None                      # 最后一轮本来就要交最好的，不用另起一个理由
    best_rank, _content = best
    if best_rank[0] < max(1, len(st.mode.dims) - 1):
        return None
    return "regressed" if st.rank() < best_rank else None


# 「还没写够」的那几个维度。跟 middleware/repair.py 的 INNER_QUALITY 正好相对：
# 那边是「已经写的东西有毛病，别再加了」，这边是「东西还不够，得接着写」。
COVERAGE_DIMS = ("beat_coverage", "section_coverage", "material_use")


def _coverage_unmet(st: State) -> bool:
    """这一轮还有「写得不够」的维度没达标。

    第 607 轮真跑实拍：分段第 1 轮六维里五维达标、差的正是 `section_coverage`
    ——而 `_regressed` 的武装条件恰好是「最好那轮只差一个维度」。于是第 2 轮
    接着写，正文长了，`non_repetition` 暂时掉到 1，排名一低就被判成「退步」、
    整节 570 字交卷。**要求它多写，又因为多写而判它退步**，两条规则打架。
    覆盖没满足就说明活还没干完，这时候的波动是干活的代价，不是退步。
    """
    return any((s := st.ev.scores.get(d)) and s.level < 2
               for d in COVERAGE_DIMS) if st.ev else False


BUILTIN_STOPS = (_complete, _blocked, _no_progress, _regressed)


def _stop(st: State) -> str | None:
    for cond in (*BUILTIN_STOPS, *st.mode.stop_when):
        reason = cond(st)
        if reason:
            return reason
    return None


# -- middleware plumbing ----------------------------------------------------

async def _fire(chain: Sequence[Middleware], hook: str,
                st: State) -> AsyncIterator[Event]:
    """Run one hook across the chain.

    **One middleware failing must not kill the run** -- that's the whole
    isolation benefit of packaging capabilities separately. But it must not
    be silent either: a failure becomes a CUSTOM warning event.
    """
    for m in chain:
        fn = getattr(m, hook, None)
        if fn is None:
            continue
        try:
            result = fn(st)
            if inspect.isasyncgen(result):
                async for event in result:
                    yield event
            else:
                await result
        except Exception as exc:                       # noqa: BLE001
            yield Event.custom(CUSTOM_WARNING, {
                "middleware": getattr(m, "name", type(m).__name__),
                "hook": hook,
                "error": f"{type(exc).__name__}: {exc}"[:200],
            })


async def _wrap_prepare(chain: Sequence[Middleware], handler, st: State):
    """Onion: the first middleware in the list wraps all the others.

    A wrapper can call the handler more than once (retry), not at all
    (short-circuit with a cached result), or rewrite what goes in and comes out.
    """
    call = handler
    for m in reversed([x for x in chain if hasattr(x, "wrap_prepare")]):
        call = functools.partial(m.wrap_prepare, handler=call)
    return await call(st)


def _wrap_produce(chain: Sequence[Middleware], handler, st: State) -> AsyncIterator[str]:
    """Same onion, for the streaming step.

    **A retry here has to be decided before the first delta goes out.** Once
    text has streamed to the client it can't be recalled; the only honest
    recovery is to end that message and open a new one.
    """
    call = handler
    for m in reversed([x for x in chain if hasattr(x, "wrap_produce")]):
        call = functools.partial(m.wrap_produce, handler=call)
    return call(st)
