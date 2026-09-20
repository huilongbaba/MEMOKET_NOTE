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

# 连着这么多轮一次真打分都没有，下一轮无论哪条判据命中都不再短路（P24 #5）。
#
# P22 实拍：18 轮里只有 6 轮真打过分，`e78306202d78` 和 `a941efecd390` 两篇
# **一轮都没有**。后果不是「少花了几次打分调用」，是三件事一起失效：
#   ① `complete` 结构上到不了（短路那一份 `Evaluation` 的 status 恒为 continue）；
#   ② `st.best` 从头到尾是空的，`SHIP_BEST_ON` 没有「最好的一轮」可交，
#      于是 `stalled` 只能把最后一轮原样交出去——那正是 P22 留下率最低的那一篇（35%）；
#   ③ 打分器的诊断一次都没进过下一轮的 prompt，模型只被同一条判据的同一句话推着走。
# 上面 `STUCK_ROUNDS` 那段讲的是「同一条判据卡死」；这一条讲的是**不同判据轮流短路**，
# 每一条各自都没卡满两轮，合起来照样把整趟打分饿死。
#
# 放行那一轮**照样报**（事件照发，用户看得见），只是不短路；而且
# `after_judge` 会把这一轮的 `complete` 压回 `continue`——
# 一条代码判据还在响的时候，不许判「写完了」。
JUDGE_FLOOR = 2

# **放行一轮值多少钱，取决于这一跑手上有没有东西可交**（P26 #2）。
#
# P24 加了 `JUDGE_FLOOR = 2`，真打分轮 33% → 53%，代价是 0.41M → 0.78M。P24 自己
# 留了话：下一批该量「放行那一轮的分有没有改变停机决策」，只是把 `complete` 往后
# 推的话就提到 3。P26 在 P24 那 5 跑（30 轮）上逐轮读完，**3 个放行轮**：
#
#   | 跑 | 放行轮 | 成了 best 吗 | 是这一跑第一份真分吗 | status |
#   |---|---|---|---|---|
#   | `e78306202d78` | r3 | **是** | **是** | continue |
#   | `603dca25403a` | r4 | 否（当时 best 已更高） | 否（r1 就有） | continue |
#   | `a941efecd390` | r7 | 否（当时 best 已更高） | 否（r3 就有） | continue |
#
# 三条结论，都是数出来的：
#   ① **一条也没改变交付轮**。把放行轮按「floor=3 会怎样」带 streak 级联重放一遍
#      （放行不是消失，是往后挪一轮），5 跑交的还是同一轮。P24 的猜想成立。
#   ② **`after_judge` 那条 `complete` → `continue` 的压制一次都没派上用场**（0/3，
#      三个放行轮的 status 本来就是 continue）。留着，但它挡的是别的局面。
#   ③ **可是有价值的那一个，价值全在「第一份」上**：`e78306` r3 是那一跑第一份真分，
#      在它之前 `st.best` 里只有短路伪造的 `(0, 0.0)`——真停在那儿，`stalled`
#      只能把最后一轮原样交出去，那正是 P22 留下率 35% 那一篇的来历。
#
# 所以不是 2 也不是 3，是**两段**：手上还没有真分的时候按 2（保住 ①，`check_stuck`
# 最早在 r3 停，floor=2 保证 r3 一定放行，那一跑至少有一份真分可交）；已经有过真分
# 之后按 3（砍掉 ②③ 之外那两轮纯花钱的）。同一套 5 跑上重放：省下 3 个放行轮里的 2 个，
# 交付轮一轮没变。**平白提到 3 是不安全的**——全轮命中的跑在 floor=3 下要到 r4 才放行，
# 而 `check_stuck` 最早 r3 就停，那种跑会一份真分都拿不到，正好踩回 JUDGE_FLOOR 要修的那个病。
JUDGE_FLOOR_AFTER_FIRST = 3

# 「最近几轮」的窗口。`modes.check_stuck` 读这一份（P24 #3）。
CHECK_WINDOW = 4


class Checks:
    """First failing check wins; the rest don't run.

    Why stop at the first: the model gets one clear instruction for the next
    round. Handing it five complaints at once produces a round that addresses
    none of them properly.
    """

    name = "checks"
    hooks = ("before_judge", "after_judge", "after_run")
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
            "note": f"「{name}」这条判据最近 {CHECK_WINDOW} 轮里响了 {n} 轮，"
                    "模型一次都没照做——停下，交最好的一轮",
            "stuck_rounds": n,
            "stopped": True,
        })

    @staticmethod
    def _fix_events(st: State, fired: str, ran: int, verdict) -> list[Event]:
        """判据自己动手改了正文：**记一句给下一轮的提示，同时发一个事件给用户**（P26 #3）。

        两个读者，一份措辞：
          · `bag["auto_fixes"]` → `prompts/note.note_harness_continue_user` 的
            「上一轮我替你改了正文」那一块（下一轮写作时读，读完在下一轮的
            `before_judge` 里被换掉）；
          · `CUSTOM_CHECK_HIT` 事件（带 `auto_fixed`）→ 前端那一栏，
            用户原来只能从正文里的记号猜。

        **`fix_note` 空着的判据一个字都不说**，两个读者都不写。不是偷懒：
        说不出「改了什么」的时候，「我改了正文」这半句只会让模型去猜哪儿变了，
        比不说更糟。仓里三处真的 `fix` 都填了 `fix_note`（`tests/test_p26.py`
        那条把它们逐个数过来），没填的只可能是新加判据时漏了——
        那种情况保持 P23 那版的老行为（静默），由那条闸去红，而不是在这里
        发一句半截话。
        """
        note = (verdict.fix_note or "").strip()
        if not note:
            return []
        st.bag.setdefault("auto_fixes", []).append(note)
        return [Event.custom(CUSTOM_CHECK_HIT, {
            "round": st.round,
            "check": fired,
            "ran": ran,
            "dimension": verdict.dimension,
            "note": note,
            # 这一条跟别的 check_hit 不是一回事：**正文已经被改好了**，
            # 不是「请你改」。前端拿它换一句话说。
            "auto_fixed": True,
        })]

    async def after_judge(self, st: State) -> None:
        """判据响了、但这一轮被**放行**（照常打分）时，不许判「写完了」（P24 #5）。

        **今天有两条路写这个键**：`JUDGE_FLOOR` 饿死放行、判据自己声明
        `advisory`（P58 A）。键因此从 `judge_floor_released` 改名叫
        `check_released`——名字里挂着其中一条，会让另一条看起来是在蹭别人的开关。

        **`STUCK_ROUNDS` 卡死放行那一支到今天仍然不写它**（P58 走查 #5 记了这条）：
        它同样是「判据还在响、这一轮照常打分」，按上面那句话本该一样压制。
        这一批**没改**——按 P28 那一节的读数，这条压制实测一次都没开过火，
        手上没有一个能复现的局面，照铁律「先复现再修」留给下一批带素材来改。

        放行的本意是「让打分器跑起来」，不是「把这条毛病一笔勾销」。
        这一轮的分数照样进 `st.best` 的排名（那正是要它的原因），
        只有 `complete` 这一档被压回 `continue`——判据还在响，就不算写完。
        不发事件，所以是普通协程不是 async generator（`loop._fire` 两种都认，
        `Repeats.before_judge` 是同一个形状）。
        """
        if not st.bag.pop("check_released", False):
            return
        if st.ev is not None and st.ev.status == "complete":
            st.ev = dataclasses.replace(st.ev, status="continue")

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
        # 最近 `CHECK_WINDOW` 轮各自报了哪几条（P24 #3）。**存的是 `cur_name` 这个对象本身**，
        # 不是它的快照：判据循环还没跑，现在它还是空的，等 `modes.check_stuck` 读它的时候
        # 这一轮已经填完了。上面那份「连续」的语义一个字不改（`citations_present` 的
        # 「连响 N 轮」还要它），这份只回答「最近 N 轮里同一条响过几次」。
        window: list[dict[str, int]] = st.bag.get("check_name_rounds") or []
        window.append(cur_name)
        st.bag["check_name_rounds"] = window[-CHECK_WINDOW:]
        # 连着几轮一次真打分都没有（P24 #5）。这一轮先读，轮末再写。
        sc_streak = int(st.bag.get("short_circuit_streak", 0) or 0)
        # 放行的门槛分两段（P26 #2，依据在 `JUDGE_FLOOR_AFTER_FIRST` 上面那段）：
        # 这一跑还一份真分都没有 → 按 2（保住「至少有一轮可交」）；已经有过 → 按 3。
        floor = (JUDGE_FLOOR_AFTER_FIRST if st.bag.get("had_real_judge")
                 else JUDGE_FLOOR)
        # 上一轮的放行标记不许跨轮活着：`after_judge` 正常会 `pop` 它，但那一轮要是
        # 在 `after_judge` 之前就出错了，标记会留下来，下一轮的 `complete` 被无辜压掉。
        st.bag.pop("check_released", None)
        # 上一轮判据自己动手改的那几处，**这一轮写作的提示已经读过了**（`hooks/note`
        # 在 `before_judge` 之前跑）——到这儿就该换掉，不然下一轮会把上上轮的也一起说
        # 一遍（P26 #3）。跟上面 `check_streak` 那两份「轮末整只换掉」同一个套路。
        st.bag["auto_fixes"] = []
        # 同上，advisory 那一份（P58 A）：`hooks/note.prepare` 跑在 `before_judge` 之前，
        # 读到的是上一轮攒的那份；到这儿就该换掉，不然下一轮会把上上轮的也一起说一遍。
        st.bag["advisories"] = []

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

        # ---- 引用覆盖：换掉「引用处数」那一格（P30 #1）----
        #
        # 旧的那格是「这次跑写进终稿的引用**处数**」，P28 #4 量完判它坏：它的方差
        # 主要由「这一跑抽到哪几篇」决定（四批 51 处新引用里一篇占 53%），
        # 而且它把模型自己敲的、修订带进去的、判据 fix 带进去的混成一个数。
        # 换成有分母的那个：`located` = 这一轮写的字里**有多少句本来就该贴编号**
        # （能逐字定位到材料），`marked` = 其中真贴了的。
        #
        # **算在这儿而不是 `Provenance`**：`round_summary` 发在 `after_prepare`，
        # 那时这一轮一个字都还没写。`st.fresh` 只有到 `before_judge` 才是满的。
        #
        # 取值表（§21「每个取值都真写得进去吗」，落库的是 `Ledger.after_judge`）：
        #   located>0 —— 正常的续写轮。**写得出**（四批 20 跑终稿上 52 句）。
        #   0         —— 这一轮没写字（打磨 / 只清理轮，`st.fresh` 空）、手上没材料、
        #                 或者写的那几句一条材料都对不上（**这是常态**：四批终稿
        #                 623 句里 571 句是这一档，可引率只有 7.7–9.1%）。**写得出**。
        #   键不在    —— 这一行无条件写，所以只有「这一轮压根没走到 `before_judge`」
        #                 那一档（中途出错 / 模式的中间件链里没有 `Checks`）才没有；
        #                 `Ledger` 那边拿不到就记 **-1**，跟「算了、0 句」严格分开
        #                 （`claim_atoms` 是同一条处理）。
        from ..checks.citations import citation_coverage
        cov = citation_coverage(st.fresh or "", list(st.facts or []))
        st.bag["cite_cover"] = (cov.located, cov.marked, cov.matched)
        # 这次跑到目前为止的累计，给 `round_summary` 用（面板那一格要的是「这次跑
        # 写的东西整体上有几句该贴、贴了几句」，不是最后一轮那几句）。**跟上面
        # 逐轮那份是同一个口径的加总**，不是第二套算法——两套口径混着读正是被
        # 换掉的那一格的死因。
        run = st.bag.setdefault("cite_cover_run", [0, 0, 0])
        run[0] += cov.located
        run[1] += cov.marked
        run[2] += cov.matched

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
                    # **动了手就得说一句**（P26 #3）：这一支原来直接 `continue`——
                    # 正文被改了，事件不发、下一轮的提示里也不提，模型下一轮看到的
                    # 正文里少了/多了自己没写过的东西，而没有任何一句话告诉过它。
                    for ev in self._fix_events(st, fired, ran, verdict):
                        yield ev
                    continue
                # **一条判据管着不止一件事**（P23 #1）：`fix_done` 说「我管的那件事修好了」，
                # 那正文就留下，剩下没好的按**新的那条**说——不然修好的正文被整个丢掉，
                # 而模型下一轮看到的还是同一句话（P18/P19 日期那一侧连响三轮的一半原因）。
                if verdict.fix_done is not None and verdict.fix_done(probe.content):
                    st.content = probe.content
                    # 半修这一支同样动了正文，只是下面还会按**剩下没好的那条**再报一次。
                    # 那条说的是「还差什么」，不是「我改了什么」——两件事，各说各的（P26 #3）。
                    for ev in self._fix_events(st, fired, ran, verdict):
                        yield ev
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

            if verdict.advisory:
                # **这一条只是提个醒，不收这一轮**（P58 A，理由在 `types.Verdict.advisory`）。
                # 位置在 `JUDGE_FLOOR` 那一支**之前**：两支做的事一样（报 + 放行），
                # 但走到这儿就不该再去动 `short_circuit_streak` 的账——
                # advisory 轮本来就会真打分，把它记成「又饿了一轮」会让下一轮的
                # 门槛凭空降一格。（`continue` 之后循环底下那两行会把 streak 归零、
                # 记上 `had_real_judge`，那正是对的。）
                st.bag["check_released"] = True
                # **判词得自己找条路进下一轮的 prompt**（P58 A）：steer 只从 `st.ev` 来
                # （`loop.py:157-158`），而这一轮的 `st.ev` 马上会被打分器的六维真分占掉。
                # 不写这一行，「说话但不收轮子」就等于「闭嘴、还多花一次打分调用」——
                # 比原来更糟。读者是 `prompts/note.advisory_block`（经 `hooks/note` 那一行），
                # 攒 / 换的时机跟上面 `auto_fixes` 逐字同一条。
                st.bag.setdefault("advisories", []).append(verdict.message)
                yield Event.custom(CUSTOM_CHECK_HIT, {
                    "round": st.round,
                    "check": fired,
                    "ran": ran,
                    "dimension": verdict.dimension,
                    "note": verdict.message,
                    # 面板要靠它说对话：没有这个键的那一档写的是「这一轮没再花模型调用
                    # 去打分」，而 advisory 轮**是打了分的**（P58 走查 #1 那个接线洞）。
                    "advisory": True,
                })
                continue

            if sc_streak >= floor:
                # 连着 `floor` 轮一次真打分都没有了（P24 #5）：报，但不短路。
                # 跟上面那条放行的差别是「谁卡住了」：那条是**同一条判据**原样卡满两轮，
                # 这条是**不同判据轮流**把打分饿死——P22 的 `e78306202d78` 正是后者，
                # `citations_present`(r2/r3/r5) 和 `no_repeated_lists`(r4/r6) 交替，
                # 每一条的 streak 都不超过 2，六轮一次分都没打上。
                st.bag["check_released"] = True
                yield Event.custom(CUSTOM_CHECK_HIT, {
                    "round": st.round,
                    "check": fired,
                    "ran": ran,
                    "dimension": verdict.dimension,
                    "note": verdict.message,
                    "judge_floor": sc_streak,
                    # 放行用的是哪一档（P26 #2）：两段的分界是「这一跑有没有过真分」，
                    # 事件里带上它，免得读台账的人得回去猜当时走的是 2 还是 3。
                    "judge_floor_bar": floor,
                })
                continue

            st.ev = Evaluation(
                scores={verdict.dimension: DimensionScore(level=0, note=verdict.message)},
                status="continue",
                weakest=verdict.dimension,
            )
            st.skip_judge = True        # explicit, not "ev happens to be set"
            st.bag["short_circuit"] = fired
            st.bag["short_circuit_streak"] = sc_streak + 1
            yield Event.custom(CUSTOM_CHECK_HIT, {
                "round": st.round,
                "check": fired,
                "ran": ran,
                "dimension": verdict.dimension,
                "note": verdict.message,
            })
            return

        # 没有任何一条短路：这一轮打分器会真的跑，计数归零。
        # **走到这儿的两条路都会真打分**：一条是没有判据命中，一条是被 `floor` 放行了
        # （放行那一支 `continue`，不 `return`）——短路是唯一会 `return` 的出口。
        # 所以这里顺手记下「这一跑已经有过真分」，放行门槛据此从 2 抬到 3（P26 #2）。
        st.bag["short_circuit_streak"] = 0
        st.bag["had_real_judge"] = True
