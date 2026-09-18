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
from .state import COVERAGE_DIMS, State      # noqa: F401  （COVERAGE_DIMS 在这儿 re-export）
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
                # 停机的理由跟「这一轮写得好不好」无关时，交最好的那轮，
                # 不是这一轮（名单和理由见 SHIP_BEST_ON）。
                if hit in SHIP_BEST_ON and st.best is not None:
                    st.content = st.best[1]
                break
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
        # 给用户看的那句话由 `llm.describe_error` 统一翻（P3）：原来这里把
        # `HTTPStatusError: Server error '500 …' for url 'http://…'` 连模型地址
        # 一起写进了正文里的运行块和轮次卡片。
        from ..util import llm as _llm
        yield Event.run_error(_llm.describe_error(exc))
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

    **正文本身过 `body_for_scoring`**（批 19 / 计划 4.2 / [LONG] §3）：超过阈值
    的长文，更早的小节换成目录行，后面几节逐字。理由是**判得准**不是省钱
    ——lost-in-the-middle 实测掉 30%+，而我们正文的中段正是累积重复所在；
    省钱那一头批 16 已经量死了（这个端点的缓存按 message 算，judge 只有一条
    message，排布和长度买不到一个 token）。开关 `params.SECTION_SCORING`。

    **为什么这一行落在 `loop.py` 里**（这一批的铁律是「不改 `loop.py` 的循环
    结构」）：`content=` 是**按值**递给 `evaluate()` 的，produce 和 judge 之间
    没有任何钩子能替换它——要在 middleware 里做，就得给循环加一个新钩子，
    那才是改循环结构。改的是 `_evaluate` 这个装配函数的一个入参，循环体、
    钩子序列、停机规则一行没动；批 16 为同一类理由改过同一个函数。
    """
    ctx, tail = score_context.split_for_prompt(
        score_context.with_material(st.bag.get("score_context"), st.facts))
    return await evaluate(
        harness_adapter.AppLLMClient(),
        content=score_context.body_for_scoring(
            st.content, keep_last_chars=st.mode.context_keep_last),
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


# **这里以前还有一个 `_steer(st)`，每轮末尾算一次存进 `st.steer`。**
# 批 25 删掉了：它拼的是紧接着下面两行存进 `bag` 的同一句话
# （`focus` + ": " + `focus_note`），一句诊断两个载体，而其中一个在长文
# 两个模式里没有任何功能读者。现在 `State.steer` 是个只读属性，当场从
# `bag` 那份算出来——读的人一个字都没改。理由和量出来的分布写在
# `state.State.steer` 的 docstring 里。


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
    if st.coverage_unmet():
        return None
    # **「最好那轮」当时要是还没写够，它不配当这条规则的基准**（批 22）。
    # 上面那行挡的是「这一轮还没写够」，而同一件事有另一半：**上一轮之所以
    # 排名高，正因为它没写够**——短、干净、不重复的残篇在 `rank()` 眼里是
    # 一份好产出（`harness-framework.md` §20① 的第 605 轮：三节各跑一轮就
    # 全 2 分判完成，交出来 620 / 434 / 429 字）。于是刚把 `beat_coverage`
    # 从 1 写到 2 的那一轮，会因为「写长了所以 non_repetition 掉一档」被拿
    # 去跟那份残篇比，一比就输。
    #
    # 实拍（批 22，`harness_rounds` 447 轮 / 158 次跑）：全表只有 **2 次**
    # 走到「武装了且这一轮排名更低」，其中 **1 次**正是这个形状——
    # `note:309f19202309` 第 1 轮 `beat_coverage=1` 拿 (5, 1.83)、第 2 轮把
    # 它写到 2 但 `non_repetition` / `coherence` 各掉一档拿 (4, 1.67)，
    # `stopped=regressed`，**交出去的是第 1 轮的 537 字，第 2 轮的 1092 字
    # 整个扔掉**。那也是全表唯一一次真的按 `regressed` 收工的跑。
    if st.bag.get("best_coverage_unmet"):
        return None
    if best is None or not st.mode.dims or st.round >= st.mode.max_rounds:
        return None                      # 最后一轮本来就要交最好的，不用另起一个理由
    best_rank, _content = best
    if best_rank[0] < max(1, len(st.mode.dims) - 1):
        return None
    return "regressed" if st.rank() < best_rank else None


# 「还没写够」的那几个维度和它的判断都搬到了 `state.py`（批 22）——
# `middleware/best_of` 也要问同一个问题，两份会飘。这一行是给在停机规则
# 这儿找 `COVERAGE_DIMS` 的人留的路标，导入在文件顶上。


def _over_budget(st: State) -> str | None:
    """这次跑花超了（计划 12.3 / [MECH] §7「成本从不进入停机决策」）。

    判断和上限都在 `middleware/cost.py` / `params.RUN_TOKEN_CAP`，这里只有一
    行转发——**两处要问同一个问题，写两份会飘**（同 `State.coverage_unmet`
    搬进 `state.py` 的理由）。`Cost` 在 `after_round` 已经把数字发成一条
    `cost` 事件了，所以"停下来告诉用户"这件事的两半都在：事件说花了多少，
    停机原因说因此停了。

    **排在 `complete` / `blocked` 后面**：那两个是这次跑真正的结局，钱花到
    上限只是"没能在预算内做完"，不该盖掉一个好结局。**排在
    `_no_progress` / `_regressed` 前面**：那两个说的是质量，这一条说的是
    预算——两个都成立时，用户更需要知道的是后者（前者下一次跑还会再花一次
    同样的钱）。
    """
    from .middleware.cost import over_cap

    return "cost_cap" if over_cap(st) else None


# 收工时交「最好那一轮」而不是「这一轮」的几个原因。
#
# `regressed` 是老的那个：这一轮比最好那轮差才停的，交这一轮等于明知故犯。
# `cost_cap`（批 23）跟循环末尾那个 `else:` 是同一个形状——**停机的理由跟
# 这一轮写得好不好无关**，那正是「最后一轮最不可能是最好那轮」的时候
# （`else:` 分支的注释原话）。写成常量而不是 `hit in ("a","b")`：下一个加
# 停机原因的人得先决定自己属于哪一档，而不是顺手在条件里再或一个字符串。
SHIP_BEST_ON = ("regressed", "cost_cap")

BUILTIN_STOPS = (_complete, _blocked, _over_budget, _no_progress, _regressed)


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
