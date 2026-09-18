"""Record how the run went, for cross-run learning.

Deliberately in BASE even though nothing reads it yet: it was missing from
compose_block entirely, which is exactly the class of omission that made
"capabilities are middleware, on by default" a rule.

（今天有读者了：`policy.from_history` 拿这篇笔记最近 3 次的
`weak_dimensions` 给下一次跑的第一轮定初始参数。）

**批 22 在这儿查出两处「同一件事只挡住一半」，都是这个文件独有的：**

① **跑满轮数的跑，一行都不记。** 原来开头写的是 `if not st.ev: return`，
   而 `st.ev is None` 在这个位置有**两个**互不相干的含义：一个是「打分调用
   失败了」（批 3 修的就是这一半——`loop._regressed` 现在会放过它），另一个
   是「循环在每轮末尾把 `st.ev` 清空了，而这一轮没触发任何停机条件，于是
   `for` 正常走完进了 `else`」。后者就是 `max_rounds`。
   实测（`harness_rounds` 158 次跑）：**17 次跑满轮数（10.8%），
   `harness_runs` 里 `stopped='max_rounds'` 的行数是 0**。
   逐条读得更难看：`analysis` 模式 6 次跑全都跑满 3 轮，历史里只有 **1 行**
   （那一行是唯一一次靠 `tools_ran_dry` 停的）；`eda` 6 次跑全跑满，
   历史里 **0 行**。而 `stopped` 这一列是计划 0.3 专门为了把「跑满轮数」
   从「continue」里拆出来才加的——**它想记的那个值结构上记不到。**
   更要命的是方向：跑满轮数 = 从头到尾没达标，**那正是下一次跑最该学的
   一类**，却恰好是唯一学不到的一类。

② **判据短路那一轮的伪造分数，被当成这次跑的终评记了下来。** 判据命中时
   `middleware/checks.py` 会伪造一份只有一个维度、分数 0 的 `Evaluation`，
   `Ledger`（不记进 `score_vectors`）、`Repair`（开头 `skip_judge` 分支）、
   `loop._regressed` 三处都明写着要排除它，只有这里照单全收。
   实测 `harness_runs` 103 行里 **14 行（13.6%）的 `final_scores` 只有一维
   且分数为 0**（`factual_grounding` 11 / `non_repetition` 2 /
   `numbers_from_tools` 1）——那一次跑真正打出来的分数向量被整个丢掉，
   换成了「某条代码判据在最后一轮响了一下」。往下一传就是
   `from_history` 的 `chronic`：15 个可比的 key 里 5 个会推出 chronic 维度，
   其中 **1 个**是靠这种伪造分数撑起来的。
"""

from __future__ import annotations

from ..types import RunRecord

from .. import adapter as harness_adapter
from ..state import State


def records_this_run(st: State) -> bool:
    """这次跑算不算「一次跑」。

    **一份实现，三个读者**（`History` 自己、`CrossRun`、`Edits`）。抄一份的
    代价是量出来的：§21 那条「同一件事挡住一半等于没挡」在这个文件里已经栽
    过两次，而「记不记这一次」是最容易各写各的一句 `if`。

    两档不算：
    * **一轮都没跑过**——`precheck` 挡下来的那一档（`reason=blocked`，循环体
      一次都没进）没有任何关于写作的信息，记下来只会在 `from_history` 的分母
      里加噪声；
    * **停下来等用户处置**——A paused run has not finished. Recording it would
      tell the next run "this note reached round 2 and stopped", which is a
      lesson about the user stepping away, not about the writing.
    """
    return st.round >= 1 and st.stopped != "awaiting_review"


class History:
    name = "history"
    hooks = ("after_run",)
    # `CrossRun` 要读「上一次跑」，而这一步就把这次跑写进去了——读到的会是
    # 自己。这条依赖由 `_order.verify` 每次组链时验，不靠注释。
    after: tuple[str, ...] = ("cross_run",)

    async def after_run(self, st: State) -> None:
        if not records_this_run(st):
            return
        scores = final_scores(st)
        cost = st.bag.get("cost") or {}
        harness_adapter.SqliteRunHistoryStore().record(RunRecord(
            key=f"{st.mode.key}:{st.ctx.note_id}",
            # 三张表共用同一个 id（计划 12.3）：`harness_runs.id` =
            # `harness_rounds.run_id` = `harness_edits.run_id`。在这之前
            # `harness_runs` 和 `harness_rounds` 没有任何 join 键，于是
            # 「这次跑花了多少 / 哪几轮」只能靠时间窗口拼。
            run_id=str(st.bag.get("run_id") or ""),
            tokens=int(cost.get("prompt_tokens", 0)) + int(cost.get("completion_tokens", 0)),
            calls=int(cost.get("calls", 0)),
            # 没打上分的收尾（跑满轮数 / 打分调用失败）照 `continue` 记：
            # 它确实没到 `complete`，而 `Status` 只有三档。**「怎么停的」在
            # `stopped` 那一栏**，两栏合起来才说得清，这也正是 0.3 加那一列
            # 的理由。
            status=(st.ev.status if st.ev and not st.skip_judge else "continue"),
            # **怎么停的，跟打分模型怎么裁决不是一回事。** 只记 status 的时候
            # 54% 的跑都是 `continue`，而那里面混着「跑满轮数」「连着几轮没动静」
            # 「比最好那轮更差主动停」三种完全不同的情况。
            stopped=st.stopped,
            rounds=st.round,
            final_scores=scores,
            weak_dimensions=[n for n, lv in scores.items() if lv < 2],
        ))


def final_scores(st: State) -> dict[str, int]:
    """这次跑最后一份**真打出来的**分数向量。

    三档，从最可信往下退：

    1. 收尾那一轮真打过分（`st.ev` 在、且不是判据短路伪造的）——用它；
    2. 否则退回 `Ledger` 攒的 `score_vectors` 的最后一条。那份清单**只收真
       打过分的轮次**（`middleware/ledger.py` 的 `after_judge` 里写着理由），
       所以它天然就是「这次跑最后一次真正的裁决」；
    3. 一轮都没真打上分（判据从头短路到尾、或者打分一直失败）——给空的。
       空的 `weak_dimensions` 在 `from_history` 里什么都不推，这是对的：
       **没判过就是没判过，不是「这一维不达标」**（批 3 的 `_regressed` 栽的
       正是把「没判过」读成「变差了」）。

    依赖 `Ledger` 在 BASE 里（两个 middleware 挂的是不同钩子，谁先谁后不影响）。
    把 `Ledger` 摘掉的模式退到第 3 档，不会报错也不会记错。
    """
    if st.ev is not None and not st.skip_judge:
        return {name: s.level for name, s in st.ev.scores.items()}
    vectors = st.bag.get("score_vectors") or []
    return dict(vectors[-1]) if vectors else {}
