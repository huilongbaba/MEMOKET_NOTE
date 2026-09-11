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
from .events import CUSTOM_EVALUATE, CUSTOM_INSERT_AT, CUSTOM_WARNING, Event
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

        # **Counts on from where the run left off**, not from 1. ``st.round``
        # is rounds completed, which is zero for a fresh State and non-zero
        # for a resumed one. Restarting at 1 would re-arm every guard that
        # asks "is this the first round" -- Revise skips round 1 because
        # nothing is written yet, and on a resumed run that is false.
        for st.round in range(st.round + 1, st.mode.max_rounds + 1):
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
            yield Event.activity(f"{st.mode.label}：在看要用哪些材料…")
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
            yield Event.activity(f"{st.mode.label}：在写…")
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
            async for e in _fire(chain, "after_produce", st):
                yield e

            # -- 3. judge: cheap first ------------------------------------
            # Checks run in before_judge and may set skip_judge. A scoring
            # call costs tens of seconds; if a deterministic rule already
            # knows the answer, paying for it is pure waste.
            async for e in _fire(chain, "before_judge", st):
                yield e
            if not st.skip_judge:
                yield Event.activity(f"{st.mode.label}：在核对…")
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
            st.bag["last_scores"] = ({n: s.level for n, s in st.ev.scores.items()}
                                     if st.ev else {})
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
            st.ev.blocked_reason if st.ev and reason == "blocked" else "",
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
    """
    try:
        return await _evaluate(st)
    except Exception:                                  # noqa: BLE001
        return None


async def _evaluate(st: State):
    return await evaluate(
        harness_adapter.AppLLMClient(),
        content=st.content,
        dimensions=list(st.mode.dims),
        dup_hints=st.bag.get("dup_hints") or [],
        context=st.bag.get("score_context") or {},
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


BUILTIN_STOPS = (_complete, _blocked, _no_progress)


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
