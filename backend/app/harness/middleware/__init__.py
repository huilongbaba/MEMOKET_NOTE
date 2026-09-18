"""Capabilities, packaged one per file.

Each one is unaware of the loop and can be unit-tested by constructing a
``State`` and calling one hook. That isolation is the point: "one harness has
it, the other doesn't" happened four times (find_repeats, compact_context,
record_harness_run, material-exhausted) and every one was an oversight rather
than a decision.

``BASE`` is on by default. Opt-out has to be written down; opt-in is how
things get forgotten.
"""

from ._order import OrderError, describe, verify
from .best_of import BestOf
from .checks import Checks
from .checklist import Checklist
from .compact import Compact
from .cost import Cost
from .cross_run import CrossRun
from .edits import Edits
from .facts import Facts
from .history import History
from .ledger import Ledger
from .repair import Repair
from .replan import Replan
from .runtime import Runtime
from .repeats import Repeats
from .save import Save
from .sections import Sections
from .skills import Skills
from .supersede import Supersede
from .provenance import Provenance

# Where each one runs. Two on the same hook execute in list order, and that
# sometimes matters -- see the ``after`` declarations, which ``verify()``
# enforces rather than trusting.
#
#   middleware   hook              why there
#   ---------------------------------------------------------------------
#   Skills       before_round      the menu must exist before gather:
#                                  gather is the only call with tools
#   Facts        after_prepare     fold this round's haul into the run's
#   Provenance   after_prepare     after Facts: show what the tools returned
#   Supersede    after_prepare     after Ledger: 账本里哪条事实已经被取代了，
#                                  把取代它的那条一起补进材料（计划 2.2）
#   Repeats      before_judge      dup_hints is evidence for the scoring call
#   Checks       before_judge      after Repeats: it may skip scoring entirely,
#                                  and dup_hints is still wanted next round
#   Cost         before_run /      绑这次跑的用量账本；轮末结一次账，超了
#                after_round       发 `cost`（停机规则 `_over_budget` 跟着收工）
#   BestOf       after_judge       needs the score to rank the round
#   CrossRun     after_run         比上一次跑差就报一句。**必须在 History
#                                  前面**：History 这一步就把这次跑写进
#                                  harness_runs 了，之后读「最近一次」读到的
#                                  是自己（History 声明 after=("cross_run",)，
#                                  _order.verify 每次组链都验）
#   History      after_run         final scores only exist at the end
#   Edits        after_run         after History：跑完落一版正文 + 开一行采集
#                                  用户接下来对它做了什么（计划 9.1）。
#                                  **认 rails_off=("save",)**——不许写正文的
#                                  跑也不许往它的历史里塞版本
#   ---- not in BASE, attached per Mode via extra_mw ----
#   Checklist    before_run        用户那条指令 → 这一次专属的判据，整趟一次
#                                  （prompt / custom；计划 6.1 + 6.2）
#   Revise       before_produce    fix what's written before writing more
#   Sections     before_round /    小节索引发布给 read_section（before_round，
#                before_produce    因为工具循环在 prepare 里、比 before_produce 早）
#                                  + 拼续写 prompt 要看的正文（before_produce，
#                                  after Revise：Revise 刚就地改写过 st.content）
#   Save         after_produce     persist each round
#   Repair       after_judge       weak inner quality -> next round repairs
#                                  instead of writing more
#   Runtime      after_judge       feed the round's signals back into the
#                                  next round's run parameters
#   Replan       after_judge       adjust the skeleton, under constraints
BASE: tuple = (Cost(), Skills(), Facts(), Provenance(), Ledger(), Supersede(),
               Repeats(), Checks(), BestOf(), CrossRun(), History(), Edits())

# Not in BASE, attached per-Mode via extra_mw:
#   Revise  -- "fix what's already written before writing more"; only
#              long-form needs it. Block generation rewrites the whole block.
#   Sections -- 续写 prompt 的正文换成「小节索引 + 当前小节逐字」；只有长文
#              分得出小节。**批 15 它替掉了 Compact**（计划 3.1 / [CE] §7：
#              摘要是有损的替换，索引是无损的指针）。`compact_context` 那个
#              函数本身还在，magic tap 那条一次性路径仍然用它——那条路**没有
#              工具循环**，给指针它取不回来，所以摘要在那里仍然是较优的一档。
#   Checklist -- 从用户那条指令现场生成 checklist（[IND] §4 的 TICK / RaR）。
#              只有 prompt / custom 有"用户刚打进来的那条指令"这个原料；
#              别的模式挂上去，生成出来的只会是通用条目——正是 RaR 消融里
#              效果明显更差的 RaR-Predefined 那一档。
#   Save    -- persist every round; blocks aren't persisted at all.
#   Repair  -- repair-instead-of-continue; long-form only.
#   Runtime / Replan -- note_harness only.

__all__ = ["BASE", "BestOf", "Checklist", "Checks", "Compact", "Cost", "CrossRun",
           "Edits", "Facts", "History",
           "Ledger",
           "Sections",
           "OrderError", "Provenance", "Repair", "Replan", "Repeats",
           "Runtime", "Save", "Skills", "Supersede", "describe", "verify"]
