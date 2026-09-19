"""Run the Mode's deterministic checks, before paying for a scoring call.

Ordering matters here and it used to be backwards: scoring ran first, then
the checks, so whenever a check fired the scoring call had been wasted. A
scoring call is tens of seconds against a local model.

(PydanticAI does the same thing for the same reason: schema validation is
free and runs first, semantic validation costs I/O and runs second.)
"""

from __future__ import annotations

from typing import AsyncIterator

import dataclasses

from ..types import DimensionScore, Evaluation

from ..checks import claims
from ..events import CUSTOM_CHECK_HIT, Event
from ..state import State


# 同一条判据原样卡住几轮之后就不再拦路。第 601 轮真跑读出来的死锁：
# `no_placeholder` 每一轮都拿正文**第一段**（这次续写根本没碰的旧文字）
# 打回，4 轮全打回，`scores` 里从头到尾只有 `factual_grounding` 一项——
# 打分器一次都没跑起来，`complete` 结构上就到不了，只能空转到轮数用尽。
# 而修订那一步是试过的：`dropped` 事件显示模型第 2/3/4 轮都提了针对那一段
# 的修订，每次都被「只是换了措辞」的空改守卫丢掉。判据说改、模型改、守卫
# 丢，三方各自都对，合起来是个谁也出不去的环。
#
# 拦两轮是给修订的机会；第三轮还一字不差，就说明这一轮的写作动不了它，
# 再拦下去只是把剩下的轮数烧掉。事件照发（用户仍然看得见这条没解决），
# 但不再短路——让打分器跑起来，其余维度有机会被看见，这一轮也能结束。
STUCK_ROUNDS = 2


class Checks:
    """First failing check wins; the rest don't run.

    Why stop at the first: the model gets one clear instruction for the next
    round. Handing it five complaints at once produces a round that addresses
    none of them properly.
    """

    name = "checks"
    hooks = ("before_judge", "after_run")
    # Repeats fills dup_hints for the scoring call. Checks may
    # short-circuit scoring entirely, so it has to run second --
    # otherwise a fired check means dup_hints never gets computed,
    # and the next round wants it.
    after: tuple[str, ...] = ("repeats",)

    async def after_run(self, st: State) -> AsyncIterator[Event]:
        # 停机原因是「判据连响」时，把**哪条、连了几轮**发出去（P6 问题 4）。
        # `run_finished` 只带一个 reason 字符串，用户看到「check_stuck」不知道
        # 是谁；这条事件落在最后一轮的卡片上，前端拿它拼收工那句话。
        from ..modes import check_stuck_detail
        if st.stopped != "check_stuck":
            return
        name, n = check_stuck_detail(st)
        yield Event.custom(CUSTOM_CHECK_HIT, {
            "round": st.round,
            "check": name,
            "ran": 0,
            "dimension": "",
            "note": f"「{name}」这条判据连响 {n} 轮，模型一次都没照做——停下，交最好的一轮",
            "stuck_rounds": n,
            "stopped": True,
        })

    async def before_judge(self, st: State) -> AsyncIterator[Event]:
        # 上一轮报过什么 → 这一轮报了什么。**先攒后落**：一轮里可能有两条
        # 判据先后触发（前一条卡死了放行、后一条才短路），边算边写会把前一条
        # 的计数擦掉。轮末整只换掉，这一轮没报的键自然断掉。
        prev: dict[str, int] = st.bag.get("check_streak") or {}
        cur: dict[str, int] = {}
        st.bag["check_streak"] = cur
        # 同一件事按**判据名**再数一份（P6 问题 4）：上面那份的键带着原话，而
        # `citations_present` 的原话里有「这一轮写了 N 字」，每轮都不一样——
        # 按它数，连响 10 轮也永远是 1。停机规则 `modes.check_stuck` 读这份。
        prev_name: dict[str, int] = st.bag.get("check_name_streak") or {}
        cur_name: dict[str, int] = {}
        st.bag["check_name_streak"] = cur_name
        # **判据自己要知道「这是第几次报同一件事」**（P19 #6）：上面这一行刚把当轮那份换成空的，
        # 判据在它之后才跑，读 `check_name_streak` 只会读到 0——第一版就栽在这，真跑三轮
        # 一次都没升级措辞。上一轮那份单独留一个键给它们读。
        st.bag["check_name_streak_prev"] = prev_name

        # ---- 三列探针（批 27 / §5 第 8、9 行）。读者是 `Ledger.after_judge`，
        # 它读完就 `pop`——bag 是跨轮活着的，留着会让下一轮继承上一轮的数。
        #
        # **算在判据循环之前，不算在 `unsupported_specifics` 里面。** 循环是
        # 「第一条命中的赢，后面的不跑」——挂在那条判据里的话，只要有别的判据
        # 先短路，这一轮就什么都记不到，而**那正是第 9 行要看的那些轮**
        # （「上一轮判据报了材料不够，下一轮照做没有」）。
        # *同一件事挡住一半等于没挡。*
        if claims.unsupported_specifics in st.mode.checks:
            cands, why = claims.probe(st)
            st.bag["claim_atoms"] = len(cands)
            st.bag["claim_abstained"] = why
        else:
            # 六个 block 模式的 `checks` 里没有这一条。**这一档必须有自己的
            # 取值**：记成 0 的话，「这个模式压根不判」和「判了、一个候选原子
            # 都没有」在库里长得一模一样——批 22 的 `stopped` 就是这么坏的。
            st.bag["claim_atoms"] = -1
            st.bag["claim_abstained"] = claims.NOT_IN_MODE

        # 这一轮**哪几条判据命中了**（第 9 行要的）。是列表不是单值：卡死放行
        # 的那条 `continue` 之后，后面还可能再命中一条，两条都得在。
        fired_all: list[str] = []
        st.bag["fired_checks"] = fired_all
        # 这一轮是**哪一条**把打分短路掉的（P18 #1）。`fired_checks` 答不了：它连卡死放行的那条也记，
        # 而且 `Ledger.after_judge` 读完就 pop——`BestOf` 在它后面，想知道「这一轮是不是只差用户
        # 自己的完成标准」就得有自己的一份。每轮先清空，短路时再写。
        st.bag["short_circuit"] = ""

        for ran, check in enumerate(st.mode.checks, start=1):
            verdict = check(st)
            if not verdict:
                continue
            # **哪一条判据命中了**（计划 12.1）。`dimension` 答不了这个问题：
            # `no_placeholder` / `citations_hold` / `citations_exist` /
            # `material_thin` / `unsupported_specifics` 五条判据全都落在
            # `factual_grounding` 这一维上，用户看到的「事实依据 0 分」不知道
            # 是这五条里的哪一条判的。`ran` / `checks_total`（后者在
            # `round_summary` 里）一起说「这一轮跑到第几条、一共几条」。
            fired = getattr(check, "__name__", "") or str(check)

            if verdict.fix:
                # **Fixes are atomic**: apply to a copy, keep it only if the
                # check now passes. Without the copy, a fix that doesn't
                # actually fix anything still mutates the content -- and the
                # next round then builds on something that was edited and is
                # still wrong. (Found by running the prototype; three passes
                # of reading the design on paper had missed it.)
                probe = dataclasses.replace(st, content=verdict.fix(st.content))
                again = check(probe)
                if again is None:
                    st.content = probe.content
                    continue
                # **一条判据管着不止一件事**（P23 #1）：`fix_done` 说「我管的那件事修好了」，
                # 那正文就留下，剩下没好的按**新的那条**说——不然修好的正文被整个丢掉，
                # 而模型下一轮看到的还是同一句话（P18/P19 日期那一侧连响三轮的一半原因）。
                if verdict.fix_done is not None and verdict.fix_done(probe.content):
                    st.content = probe.content
                    verdict = again

            # **修好了的不算命中**：`verdict.fix` 那一档当场把正文改对了，
            # 对下一轮一个要求都没提——第 9 行问的是「上一轮提的要求，下一轮
            # 照做没有」，把它算进来会给分母灌一批没有要求的轮。
            fired_all.append(fired)
            cur_name[fired] = prev_name.get(fired, 0) + 1
            key = f"{verdict.dimension}\u0000{verdict.message}"
            streak = cur[key] = prev.get(key, 0) + 1
            if streak > STUCK_ROUNDS:
                # 卡死了，不短路。**继续往下看别的判据**：这一条动不了，不等于
                # 后面那条也动不了，短路本来就是为了「一次只给一个清楚的指令」。
                yield Event.custom(CUSTOM_CHECK_HIT, {
                    "round": st.round,
                    "check": fired,
                    "ran": ran,
                    "dimension": verdict.dimension,
                    "note": verdict.message,
                    "stuck_rounds": streak,
                })
                continue

            st.ev = Evaluation(
                scores={verdict.dimension: DimensionScore(level=0, note=verdict.message)},
                status="continue",
                weakest=verdict.dimension,
            )
            st.skip_judge = True        # explicit, not "ev happens to be set"
            st.bag["short_circuit"] = fired
            yield Event.custom(CUSTOM_CHECK_HIT, {
                "round": st.round,
                "check": fired,
                "ran": ran,
                "dimension": verdict.dimension,
                "note": verdict.message,
            })
            return
