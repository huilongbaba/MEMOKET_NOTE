"""架构原型：验证类型和循环真能跑通。假 LLM、假工具，零依赖。"""
from __future__ import annotations
import asyncio, contextlib, functools, inspect
import dataclasses
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Protocol

# ── types ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Event:
    type: str; data: dict
    @staticmethod
    def custom(name, value): return Event("CUSTOM", {"name": name, "value": value})
    @staticmethod
    def step_started(n): return Event("STEP_STARTED", {"step": n})
    @staticmethod
    def text_content(mid, d): return Event("TEXT_MESSAGE_CONTENT", {"id": mid, "delta": d})
    @staticmethod
    def run_finished(c, r): return Event("RUN_FINISHED", {"content": c, "reason": r})
    @staticmethod
    def run_error(m): return Event("RUN_ERROR", {"message": m})

@dataclass(frozen=True)
class Score: level: int; note: str = ""
@dataclass(frozen=True)
class Evaluation:
    scores: dict; status: str; weakest: str | None = None
@dataclass(frozen=True)
class Verdict:
    dimension: str; message: str; fix: Callable[[str], str] | None = None

@dataclass(frozen=True)
class Mode:
    key: str; label: str = ""
    dims: tuple = (); checks: tuple = (); stop_when: tuple = (); extra_mw: tuple = ()
    max_rounds: int = 3; fact_budget: int = 5

@dataclass
class State:
    mode: Mode
    round: int = 0
    content: str = ""; fresh: str = ""
    facts: list = field(default_factory=list); facts_new: list = field(default_factory=list)
    ev: Evaluation | None = None
    best: tuple | None = None
    steer: str = ""; skip_judge: bool = False
    bag: dict = field(default_factory=dict)
    disconnected: bool = False
    def rank(self):
        if not self.ev: return (-1, -1.0)
        lv = [s.level for s in self.ev.scores.values()]
        return (sum(1 for v in lv if v >= 2), sum(lv) / max(1, len(lv)))

# ── middleware ───────────────────────────────────────────────────────
class Facts:
    name = "facts"
    async def after_prepare(self, st) -> None:          # 不发事件：普通 async def
        fresh = [f for f in st.facts_new if f not in st.facts]
        st.facts = (st.facts + fresh)[-st.mode.fact_budget:]   # 累积+压缩绑死
        st.bag["dry"] = 0 if fresh else st.bag.get("dry", 0) + 1

class Checks:
    name = "checks"
    async def before_judge(self, st):                    # 发事件：async generator
        for check in st.mode.checks:
            v = check(st)
            if not v: continue
            if v.fix:
                # **fix 必须原子**：修完让 check 通过才采纳，否则回滚。
                # 不回滚的话，一次没修好的 fix 留下副作用——content 被改了
                # 但还是不合格，下一轮基于被改坏的内容继续，可能更糟。
                probe = dataclasses.replace(st, content=v.fix(st.content))
                if not check(probe):
                    st.content = probe.content
                    continue
            st.ev = Evaluation({v.dimension: Score(0, v.message)}, "continue", v.dimension)
            st.skip_judge = True
            yield Event.custom("check_hit", {"dimension": v.dimension})
            return

class BestOf:
    name = "best_of"
    async def after_judge(self, st) -> None:
        r = st.rank()
        if st.best is None or r > st.best[0]: st.best = (r, st.content)

class Boom:
    """故意抛异常，验证隔离。"""
    name = "boom"
    async def after_round(self, st) -> None: raise RuntimeError("我坏了")

BASE = (Facts(), Checks(), BestOf())

# ── loop ─────────────────────────────────────────────────────────────
async def _fire(mw, hook, st):
    for m in mw:
        fn = getattr(m, hook, None)
        if fn is None: continue
        try:
            r = fn(st)
            if inspect.isasyncgen(r):
                async for e in r: yield e
            else:
                await r
        except Exception as exc:
            yield Event.custom("warning", {"middleware": m.name, "hook": hook,
                                           "error": str(exc)})

async def _wrap(mw, hook, handler, st):
    call = handler
    for m in reversed([x for x in mw if hasattr(x, hook)]):
        call = functools.partial(getattr(m, hook), handler=call)
    return await call(st)

def _complete(st): return "complete" if st.ev and st.ev.status == "complete" else None
def _blocked(st):  return "blocked"  if st.ev and st.ev.status == "blocked"  else None
def _no_progress(st): return "no_progress" if not st.fresh.strip() else None

def _stop(st):
    for c in (_complete, _blocked, _no_progress, *st.mode.stop_when):
        if r := c(st): return r
    return None

async def run(st, hooks, evaluate) -> AsyncIterator[Event]:
    mw = BASE + st.mode.extra_mw
    reason, committed = "max_rounds", False
    try:
        async for e in _fire(mw, "before_run", st): yield e
        for st.round in range(1, st.mode.max_rounds + 1):
            if st.disconnected: raise asyncio.CancelledError
            yield Event.step_started(st.round)
            st.facts_new, _ = await _wrap(mw, "wrap_prepare", hooks.prepare, st)
            async for e in _fire(mw, "after_prepare", st): yield e

            async for e in _fire(mw, "before_produce", st): yield e
            st.fresh, mid = "", f"r{st.round}"
            async for piece in hooks.produce(st):
                st.fresh += piece
                yield Event.text_content(mid, piece)
            async for e in _fire(mw, "after_produce", st): yield e

            async for e in _fire(mw, "before_judge", st): yield e
            if not st.skip_judge:
                st.ev = await evaluate(st)
            yield Event.custom("evaluate", {"round": st.round,
                                            "status": st.ev.status,
                                            "rank": st.rank()})
            async for e in _fire(mw, "after_judge", st): yield e
            async for e in _fire(mw, "after_round", st): yield e

            if hit := _stop(st):
                reason = hit; break
            st.ev, st.skip_judge = None, False
        else:
            st.content = st.best[1] if st.best else st.content
        await hooks.commit(st); committed = True
        yield Event.run_finished(st.content, reason)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        yield Event.run_error(str(exc))
    finally:
        if not committed and st.content:
            with contextlib.suppress(Exception):
                await asyncio.shield(hooks.commit(st))
