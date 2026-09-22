"""**那把 765 条查询的尺子**：全库每一段正文按前端的口径生成召回查询，去重之后当量程。

    .venv/bin/python scripts/recall_ruler.py            # 打出身 + 核对，对不上 exit 9
    .venv/bin/python scripts/recall_ruler.py --list 20  # 顺带看前 20 条长什么样

**为什么它必须在仓库里**（P63，这是第三次为同一件事付钱）：
P34 / P38 / P42 / P44 / P46 / P48 / P60 / P61 八批的「全库对拍」全是拿这把尺量的，
而这把尺每批都是各自在 scratch 里现写一份 `ruler.py`。scratch 每批都会被清掉，于是：

  · P60 记的「圆点 172 段 / 判出 140 / 真画 34」**下一批复现不出来**——
    量它的脚本跟着 `$S/p60/` 一起没了（P61 拿新写的尺量到的是 166 / 137 / 31）；
  · P34 那 47 条标注、P59 那 284 轮 run json，都是同一个形状。

**一把量具进不了仓库，它量出来的数下一批就复现不出来。** 所以这一份带三样东西：
**口径写死在代码里**、**出身跟着数一起打出来**、**对不上就 `exit 9`**。

---

## 口径（跟前端逐行对应）

`frontend/src/util/recallContext.ts` 的 `recallQuery`：

  · 光标所在段落（`clean_query` 之后）≥ `RECALL_MIN_CHARS` 字、且不是 `#` 标题 →
    **前一段最多 `RECALL_CONTEXT_BEFORE` 字 + 本段**，记 `cursor`；
  · 否则退回**正文末 `RECALL_TAIL_CHARS` 字**，记 `tail`。

段落 = 空行分隔。按 `(用户, 查询)` **全局去重**、顺序稳定（按 `notes.id`）。
**只算 `KITE_DATA_DIR` 下 codebook 非空的用户**——没有知识库的人召回恒空，
算进去只会把分母灌水。

## 血缘：**带着走，但不筛掉**

每一条查询都带一个 `origin`（`corpus_lineage` 判的 `user` / `script` / `fixture`）。
**为什么不筛**：这把尺的用途是**同一组查询上两版代码的对拍**——
「改完之后哪几条的 top-8 变了」。分母是查询集合本身，不是用户数据的分布，
所以筛掉夹具只会让这把尺跟 P34–P61 八批的数**对不上**，而那正是它存在的理由。

**为什么还是要带着**：`corpus_lineage` 顶上那两条教训
（批 4 的 33.3% → 8.3%、批 6 的四条结论翻转）说的是**另一件事**——
「**拿这些查询算出来的比例**」。所以凡是要从这把尺上读出一个**比率**的，
必须先按 `origin` 分开看；`identity()` 每次都把三类各几条打出来，
省得下一批忘了这回事。**尺子不筛，读数的人分。**

## 出身

每次都打一行：三个参数 + **笔记库指纹** + **每个用户的 codebook 指纹** + 血缘分布。
照 `recall_selfcheck.py` 那条规矩——「同样的参数在不同语料上是不同的数」，
所以**整行抄进台账，出身跟着走**。
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
# `corpus_lineage` 里是 `import db_guard`（裸的），直接跑脚本时 `scripts/` 是 sys.path[0]
# 所以碰巧能跑；被 `from scripts import recall_ruler` 导进来时就没有了。
# **「直接跑能过」不等于「能用」**——把 `scripts/` 显式摆上去。
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database.kb import search as kb_search  # noqa: E402
from scripts import corpus_lineage, db_guard  # noqa: E402

# 三个参数逐字抄自 `frontend/src/util/recallContext.ts`。**改那边就得改这边**，
# 闸在 `tests/test_p63.py::test_765条尺子的三个参数跟前端逐字一致`（读的是真源文件）。
RECALL_TAIL_CHARS = 500
RECALL_MIN_CHARS = 8
RECALL_CONTEXT_BEFORE = 200

# 钉死的量程。**这四个数是这把尺自己的身份**：对不上说明口径或语料变了，
# 那一刻台账上所有拿它当分母的数全部失效——所以宁可 `exit 9`，不许悄悄换一把尺继续量。
# 出处：P38 / P42 / P44 / P46 / P48 / P60 / P61 七批收尾**逐格相同**。
EXPECT_TOTAL = 765
EXPECT_CURSOR = 727
EXPECT_TAIL = 38
EXPECT_USERS = 6

# ── **按库 × 血缘的分母**（P82 ①，新加）────────────────────────────────────────
#
# **为什么这一格要单独存在**：P81 ① 那一跤是「比率按血缘分，把 62.8% 平成了 6.9%」。
# 血缘（`user` / `script` / `fixture`）说的是**这段文字谁写的**，
# 而 `UserMemory.common_term()` / `_grep_index` / `unit_df` 全是**按人**建的——
# 同一个旋钮在 2362 unit 的 `terrence` 上翻 6.9%、在 193 unit 的 `terrence-rewrite`
# 上翻 62.8%。**要读比率，先看这张表，不是上面那行血缘分布。**
EXPECT_BY_LIB = {
    ("fresh678", "fixture"): 6,
    ("fresh678b", "fixture"): 6,
    ("fresh678c", "fixture"): 6,
    ("shot-demo", "fixture"): 20,
    ("terrence", "script"): 92,
    ("terrence", "user"): 549,
    ("terrence-rewrite", "script"): 86,
}

# ── **`common_term()` 那个旋钮的全库对拍**（P82 ①，`--cf-common`）──────────────
#
# 反事实：`kb/relations.py` 那段注释原来写着「库不到 333 个 unit 时这条判据等于不启用」。
# 这一支**把它真的做出来**（`unit_count * COMMON_DF_RATIO < COMMON_DF_MIN` 就回 `None`），
# 然后跟 HEAD 逐条比 top-8。**产品代码一个字节没改**——这里是尺子，不是那一刀。
#
# **这几个数是 P82 ① 判「换不了」的全部分量**（49 条逐条读完：变好 16 / 变差 23 / 中性 10，
# 标注在 `tests/fixtures/memory_sample.jsonl` 的 `p82-off333-49`）。任何一个动了，
# 那条判就得重读——尤其 `EXPECT_CF_COMMON_LIBS`：它说的是**这个旋钮只够得着一个库**，
# 一旦够得着第二个库，「按库分」那张表和 49 条标注的分母全部换人。
EXPECT_CF_COMMON_CHANGED = 49       # top-8 变了的查询数
EXPECT_CF_COMMON_DROP = 52          # 掉了的召回对
EXPECT_CF_COMMON_ADD = 140          # 进来的召回对
EXPECT_CF_COMMON_HIT = (341, 347)   # 有召回的查询数：HEAD → 反事实
EXPECT_CF_COMMON_LIBS = (("terrence-rewrite", 49),)   # 变了的那几条落在哪几个库上

# ── **P84 那条轴的全库对拍**（`--cf-spread`）──────────────────────────────────
#
# 反事实：**把 P84 那一问拆掉**——`common_term()` 回到「只看 df」。
# 于是这几个数读的是「**P84 那条轴单独相对于没有这条轴的样子**」：
# `变了` = top-8 变了的查询数；`进` / `掉` = 它比反事实**多**了多少对 / **少**了多少对。
#
# ⚠️ **P88 起这一支的左边不再是 HEAD，是「只有 `topics` 那条轴」那个反事实**
# （`_axis_variant(True, True, ask_who=False)`）。理由是 P86 ① 那一课的原话：
# **两个旋钮别混成一个**。P88 在 `common_term()` 里串了第二条轴（主语面），
# 拿今天的 HEAD 去减「没有任何轴」量出来的是**两条轴一起拆**，
# 那张表就不是 P84 读过的那 28 条了（实测会变成 27 条 / 进 37 掉 15 / 捞回 54 种）。
# 左边钉在「P84 那一版」上，**这 6 个数才继续是 P84 那 28 条标注的分母**。
# P88 那条轴单独一支在 `--cf-whoaxis`，**接线自检在那儿**（复刻的 HEAD ≡ 产品）。
#
# **这几个数是 P84 判「接」的全部分量**（28 条逐条读完：变好 14 / 变差 7 / 中性 7，
# 标注在 `tests/fixtures/memory_sample.jsonl` 的 `p84-spread-28`）。任何一个动了，
# 那条判就得重读——尤其 `EXPECT_CF_SPREAD_LIBS`：它说的是**这条轴只够得着小库那一档**
# （`total * COMMON_DF_RATIO < COMMON_DF_MIN`），一旦够得着 `terrence`，
# **四栏那四个数就不再是「对这一刀是瞎的」，而是真被动过了**，得整批重读。
EXPECT_CF_SPREAD_CHANGED = 28       # top-8 变了的查询数
EXPECT_CF_SPREAD_ADD = 36           # 「只有 topics 轴」比「没有这条轴」多出来的召回对
EXPECT_CF_SPREAD_DROP = 16          # 「只有 topics 轴」比「没有这条轴」少掉的召回对
EXPECT_CF_SPREAD_HIT = (345, 341)   # 有召回的查询数：「只有 topics 轴」→ 反事实
EXPECT_CF_SPREAD_LIBS = (("terrence-rewrite", 28),)   # 变了的那几条落在哪几个库上
# 这条轴在 `terrence-rewrite` 上真的从 `common` 手里捞回来的串。**63 一动**说明
# 语料、`SPREAD_GENERIC` 或者「只问汉字」那一条变了，28 条标注的分母跟着换人。
EXPECT_CF_SPREAD_RESCUED = 63

# ── **P88 那条主语面轴的全库对拍**（P88 ①，`--cf-whoaxis`）───────────────────
#
# 反事实：**只把 P88 那一问拆掉**（`_axis_variant(True, True, ask_who=False)`
# = P84 那一版），左边是**今天的 HEAD**。**一刀只动一处**：库大小闸、汉字闸、
# `topics` 那条轴三样一个字不动，只差「问不问主语面」。
#
# **这几个数是 P88 ① 判「接」的全部分量**（2 条逐条读完：变好 1 / 中性 1 / 变差 0，
# 标注在 `tests/fixtures/memory_sample.jsonl` 的 `p88-whoaxis-2`）。
# 尤其 `EXPECT_CF_WHO_DROP` 那个 **0**：这一刀答应的是「**只做减法、不挤掉任何人**」，
# 它一旦不是 0，那句话就不成立了，两条标注和判都得重读。
# `EXPECT_CF_WHO_BLOCKED` 是「被主语面挡回去、不再捞回来的串」（63 − 54 = 9），
# 它一动说明 `WHO_GENERIC` 那个 0.85 或者语料变了。
EXPECT_CF_WHO_CHANGED = 2           # top-8 变了的查询数（i=26 · i=293）
EXPECT_CF_WHO_ADD = 2               # HEAD 比「没有主语面」多出来的召回对
EXPECT_CF_WHO_DROP = 0              # HEAD 比「没有主语面」少掉的召回对 —— **必须是 0**
EXPECT_CF_WHO_HIT = (346, 345)      # 有召回的查询数：HEAD → 反事实
EXPECT_CF_WHO_LIBS = (("terrence-rewrite", 2),)       # 只够得着这一个库
EXPECT_CF_WHO_BLOCKED = 9           # 被主语面挡回去的串（`公司` / `反馈` / `客户` …）

# ── **大库那一档到底接不接**（P86 ①，`--cf-bigcorpus`）────────────────────────
#
# P84 ⑤ 留的账：「大库上这条轴**一个反事实都没跑**……不限库大小那一版全库变 175 条
# （其中 `terrence` 134 条）——**量了形状，一条都没读**」。这一支把那 175 条**跑出来**，
# 而且把它**拆成两档**——因为「大库那一档接不接」和「英文那一半问不问」是**两个旋钮**，
# P84 那个 175 是**两个一起拆**量出来的，直接拿它去判大库会把两笔账混成一笔。
#
#   基准 V0 = 没有这条轴（`_df_only_common`，跟 `--cf-common` / `--cf-spread` 共用一份）
#   SIZE   = 只拆**库大小**那道闸，「只问汉字」那一条**原样留着** ← 判大库真正要看的那一档
#   BOTH   = 两道闸全拆                                        ← P84 ⑤ 记的那个 175
#
# 自检：`SIZE` / `BOTH` 在 `terrence-rewrite` 上必须跟 `EXPECT_CF_SPREAD_CHANGED`(28) /
# P84 ② 那个 41 各自对得上——小库那一档两支都不动它，对不上就是这一支接错层了。
#
# **这几个数是 P86 ① 判「大库不接」的全部分量**（175 条逐条读完，标注
# `tests/fixtures/memory_sample.jsonl` 的 `p86-bigcorpus-175`）：
# SIZE 那一档大库 25 条 **变好 8 / 中性 7 / 变差 10**（不是赢，是净亏，
# 跟小库那一档 14:7 的形状**相反**）；BOTH 那一档大库 134 条 **变好 14 / 中性 27 / 变差 93**。
EXPECT_CF_BIG_SIZE_CHANGED = 53      # 只拆库大小闸：top-8 变了的查询数
EXPECT_CF_BIG_SIZE_ADD = 108         # 它比「没有这条轴」多进来的召回对
EXPECT_CF_BIG_SIZE_DROP = 33         # 它比「没有这条轴」少掉的召回对
EXPECT_CF_BIG_SIZE_LIBS = (("terrence", 25), ("terrence-rewrite", 28))
EXPECT_CF_BIG_BOTH_CHANGED = 175     # 两闸全拆：**这就是 P84 ⑤ 记的那个 175**
EXPECT_CF_BIG_BOTH_ADD = 577         # 进 577 / 掉 80 —— 这个 7:1 的不对称本身就是判据：
EXPECT_CF_BIG_BOTH_DROP = 80         # 它不是「多召回一点」，是**把空屏灌满**（93/134 条变差）
EXPECT_CF_BIG_BOTH_LIBS = (("terrence", 134), ("terrence-rewrite", 41))

# ── **那两道闸今天各自还挡着什么**（P90，`--cf-gates`）─────────────────────────
#
# 左边一律是**今天的 HEAD**，右边三档各只动一处：
#
#   SIZE = 拆**库大小闸**，主语面照问
#   TAG  = 同 SIZE，**再**把 `SPEAKER_TAG_MAX` 那道闸摘掉（强行 `usable=True`）
#   EN   = 拆**汉字闸**，别的一个字不动
#
# **SIZE 那个 0 是这一支的正题**：库大小闸今天在这份语料上**一条产出都不改**——
# 因为唯一够得着它的大库是 `terrence`，而那个库的 `who` 93.8% 是说话人标签，
# `WhoFace` 在那儿 `usable=False` → `generic()` 回 `None` → `None is not False` 为真
# → **判「是 common」= 不捞回来**。也就是说 P88 那条主语面轴**不是在大库上什么都不做，
# 是把话题面那一问整个按住了**。
#
# ⚠️ **但这不等于那道闸可以拆**，`TAG` 那一档就是来证明这件事的：把说话人标签那道闸
# 一摘，同样的语料上立刻 **24 条变了、全在 `terrence`、i=607 从 1 条打成 0 条**。
# 所以**大库上的安全来自「这个库的 `who` 恰好装的不是主语」这个偶然，不是来自这条轴判得准**
# —— 实测 `用户`(.460) / `需要`(.473) / `产品`(.559) / `手机`(.534) 在主语面上全都远低于
# `WHO_GENERIC`(0.85)，真让它开口它会把这四个一起捞回来。
# **两道闸今天在这份语料上是冗余的，但它们挡的不是同一种库**，所以两道都留着。
#
# `EN` 那一档是 P88 ③ 留的「拆汉字闸通不通」：6 条逐条读完
# **变好 0 / 中性 2 / 变差 4**（标注 `p90-engate-6`）。判：**不通**。
EXPECT_CF_GATES_SIZE_CHANGED = 0     # 拆库大小闸 · 主语面照问：**一条都不变**
EXPECT_CF_GATES_TAG_CHANGED = 24     # 再摘掉说话人标签那道闸：24 条，全在大库
EXPECT_CF_GATES_TAG_LIBS = (("terrence", 24),)
EXPECT_CF_GATES_TAG_607 = (1, 0)     # i=607 的召回条数：HEAD → 摘闸后（**1 → 0，同 i=293 那条链**）
EXPECT_CF_GATES_EN_CHANGED = 6       # 拆汉字闸：top-8 变了的查询数
EXPECT_CF_GATES_EN_ADD = 25          # 它比 HEAD 多进来的召回对
EXPECT_CF_GATES_EN_DROP = 5          # 它比 HEAD 少掉的召回对
EXPECT_CF_GATES_EN_EMPTY = 0         # 「有→空」的条数（主语面把 `app`/`agent` 挡住了，没打空屏）
EXPECT_CF_GATES_EN_LIBS = (("terrence-rewrite", 6),)
EXPECT_CF_GATES_EN_IDX = (295, 296, 316, 318, 319, 320)   # `p90-engate-6` 那 6 条就是它们

# ⚠️ **这一支每跑一趟必须清两次缓存，前后各一次**（P92 ③，收 P90 ④）。
# P90 ④ 原话：那两句 `purge()` 写了两份、**摘任一份都绿、两份都摘才红**，闸分不开是哪一份被摘了。
# 现在两句各带一个 `when` 标签、各记一笔，`_swap_run` 顶上那段写着为什么两句都得留着。
# **它一动 = 有人动了那段缓存接线**，去读 `_swap_run` 的注释和 `cf_gates` 里那句
# 「摘了闸的 `WhoFace` 一份都没建出来」的自检——那条自检靠的正是「清干净了再建」。
EXPECT_CF_GATES_PURGES = ("before", "after")

# ── **`topics` + 英文专用低门槛那条路**（P92 ①，收 P90 ①）─────────────────────
#
# P90 ① 留的原话：「真要拆汉字闸，该走的是 `topics` 轴 + 一个英文专用的低门槛（≈0.60），
# 不是主语面。**这一批没接**」。这一批把这条路**走完了**，判**还是不接**，
# 但**卡的不是 P90 猜的那两格**——门槛和轴这两格今天都过得去：
#
#   · 留出集做厚了（P92 的 `p92-holdout-en-*`：**108 条真盲 + 29 条 tainted = 137**，
#     = 六个库上 `topics` 面判得了的英文串**全部**，不是抽样）；
#   · 产品那一堆（`terrence-rewrite` 上 df 过 common 的 9 个英文串）上 `topics` 轴
#     **有缝、无重叠**：人标「不泛」.450–.663 / 人标「泛」.708–.880，
#     假捞回 0.0% 的最高门槛是 **0.705**——0.60 稳稳落在缝里。
#
# **然后产出还是变差了**：EN@0.60 全库对拍变 11 条，逐条读完 **变好 0 / 中性 2 / 变差 9**。
# 根因是第三格，P90 / P86 / P84 都没量到过这一格：
# **「不泛」≠「值得当证据」**。这一刀真正放行的只有两个串（`agent` .450 / `memory` .592），
# 两个**人标都对**，可它们命中的是这个库里**同一句产品定位话的六种说法**
# （`MemuKet / MemoKet / MemoCat is presented as a wearable AI agent powered by the user's
# own memory` …），八格的屏一进就是半屏，把「Ask Memory 接 MCP 要明确授权」
# 这类**逐句沾边**的事实挤出去。**串指着一件具体的事，不等于命中它的那些事实彼此有区别。**
#
# ⚠️ **门槛扫出来产出真的在动**（不是「旋钮动完产出一样」那种退回）：
# 0.45 变 0 条 / 0.50–0.55 变 5 条 / **0.60–0.65 变 11 条** / 0.70 变 18 / 0.75 变 20 / 0.80 变 22。
# 也就是说这条路**有工作点可挑**，挑哪一档都只是决定伤多大——**方向没有一档是对的**。
EXPECT_CF_GATES_EN060_CHANGED = 11        # EN 走 topics@0.60：top-8 变了的查询数
EXPECT_CF_GATES_EN060_ADD = 37            # 它比 HEAD 多进来的召回对
EXPECT_CF_GATES_EN060_DROP = 26           # 它比 HEAD 少掉的召回对
EXPECT_CF_GATES_EN060_EMPTY = 0           # 「有→空」的条数
EXPECT_CF_GATES_EN060_LIBS = (("terrence-rewrite", 11),)
EXPECT_CF_GATES_EN060_IDX = (32, 318, 319, 584, 585, 589, 593, 640, 641, 642, 645)
# 这一刀真正多放行的英文串——**只有两个**，就是它俩把上面那 11 条全带出来的
EXPECT_CF_GATES_EN060_TERMS = (("agent", 0.450), ("memory", 0.592))
EXPECT_CF_GATES_EN060_TH = 0.60                           # P90 ① 点名的那个「英文专用低门槛 ≈0.60」

# ── `--cf-shape`：**P92 留的第三格，这一批造了尺**（P94）────────────────────────
#
# 上面那段说「八格的屏一进就是半屏」是**眼看出来的**。这一批把它量成数：
# `kb/fact_distinct` 判一屏里有没有半屏是**同一句话的多种说法**
# （判据 = `obj` 相交非空 ∧ `topics` 相交非空，然后取**最大团** ≥3 且 ≥ 半屏）。
#
# ⚠️ **这一支不是反事实的对照组，是给 en060 那一支配的量具**：左边一样是今天的 HEAD，
# 右边就是 `EXPECT_CF_GATES_EN060_TH` 那一刀，**产品逻辑一个字节没动**。
# 判「不接」的四条理由逐字在 `kb/fact_distinct` 文件头第 ⑤ 格。
EXPECT_SHAPE_TOTAL = 175          # 765 屏里「量得了 ≥3 格」的有几屏（这把尺的分母）
EXPECT_SHAPE_BLIND = 441          # 一个字都说不出来的屏（量得了 = 0）——57.6%
#
# ⚠️ **P96 ② 把 `EXPECT_SHAPE_BLIND` 那笔账拆开了，并排更正 P94 ⑤-2**：
# P94 把这 441 屏整笔归给「`terrence` 43.3% 的事实没有 `obj`」。**拆开是三笔**：
# **419 屏是空屏（`recall` 一条都没回）**、3 屏有事实但一条 `topics` 都没有、
# **真能归到「没有 obj」头上的只有 19 屏**（= 441 的 4.3% / 765 的 2.5%）。
# ⇒ 「补抽取那一头」这件事**的上限就是这 19 屏**，不是 441 屏（第 ② 条的判据）。
EXPECT_SHAPE_BLIND_WHY = (419, 3, 19)     # (空屏, 有事实但无 topics, 有 topics 但一条 obj 都没有)
#
# ⚠️ **P96 ① 把判据从 `K` 换成了 `M`**（`obj∩ ∧ topics∩ ∧ 不同 unit`），
# 下面这一组数**全部是在 `M` 上重量的**，不是 P94 那一组。改判的理由：
# P94 用的分母是**十组手挑的正反例**（`K` 和 `M` 在那十组上都全对），
# P96 换成**读过的那 18 屏**重量 —— `M` 把 6 屏假阳性治好 5 屏，代价 1 屏真的（i=94）。
#
# ⚠️ **P98 换了屏级那道门**（`团×2 ≥ n` **或** `这一族的话题码盖住 ×2 ≥ n`，
# `kb/fact_distinct.family_cover`），下面这一组数**又重量了一遍**。它**不是摘门**：
# 摘门按库拆开是亏的（大库假阳性 16.7% → 28.6%，全部收益都在小库），判「不摘」。
EXPECT_SHAPE_HEAD = 17            # HEAD 上判「是这形状」的屏数（`M` + 老门那一版是 12、`K` 是 18）
EXPECT_SHAPE_EN060 = 20           # en060 那一刀之后（`M` + 老门那一版是 14、`K` 是 21）
EXPECT_SHAPE_FLIP_ON = (640, 642, 645)    # 从「不是」翻成「是」的是哪几屏
EXPECT_SHAPE_FLIP_OFF = ()                # 反向一屏都没有
# ⚠️ **换 `M` 的代价照实记在这儿**：`K` 那一版翻的是 (640, 642, 645) **三屏**，
# `M` + 老门那一版只翻两屏 —— **i=642 在那一版上团 3 / 8 格，差半屏一格**。
# 这把尺第 ③ 个用途（当 en060 那一支的量具）因此**钝了一格**：3 屏 → 2 屏。
# ⚠️ **P98 换门之后翻回三屏，跟 `K` 那一版逐格相同** —— **这一条代价清了**
# （`M` 另外两条代价 i=94 / i=388 照旧欠着）。两个常数今天相等**不是巧合、也不是重复**：
# 一个是今天跑出来的，一个是冻死的历史读数，`test_p98::第一条f` 钉着它们相等这件事本身。
EXPECT_SHAPE_FLIP_ON_K = (640, 642, 645)
# HEAD 上判「是」的 17 屏落在哪几个库（库, 判「是」, 量得了>=3 的分母）
EXPECT_SHAPE_LIBS = (("fresh678", 0, 2), ("fresh678b", 0, 4), ("fresh678c", 0, 2),
                     ("shot-demo", 2, 14), ("terrence", 6, 97), ("terrence-rewrite", 9, 56))
# 那 17 屏**逐条读完**：(真, 假)。⚠️ **这 17 屏一屏都不用新读**：新门严格窄于
# 「摘掉门」，而摘掉门那 19 屏 P96 已经全读完了（12 屏在 `p94-shape-18`、
# 7 屏在 `p96-halfdoor-7`）——17 = 12 + 那 7 屏里的 5 屏（587/588/595/596/597）。
EXPECT_SHAPE_READ = (16, 1)
# ⚠️ **同一笔账按库拆开**：大库 `terrence` 上真 5 / 假 1 = **假阳性 16.7%**
# （`K` 那一版是 6/6 = 50%），而 641/765 = 83.8% 的查询落在大库。
# ⚠️ **P98 换门一格没动它**——换门多出来的 5 屏**全在小库**。**这正是「不摘门」那个判的凭据**：
# 摘光的话这一对会变成 (5, 2)，大库假阳性 16.7% → 28.6%。
EXPECT_SHAPE_READ_BIGLIB = (5, 1)
# 两个小库上真 11 / 假 0（`terrence-rewrite` 9 屏 + `shot-demo` 2 屏）。
# **别把这两对合成一个「真 16 假 1」去读**（那是两笔账混成一笔）。
EXPECT_SHAPE_READ_SMALLLIB = (11, 0)
# 剩下那一屏假阳性是 **i=388（`手环`）**：五条各说各的手环事，**五场不同的录音**，
# 所以 `M` 那一条也拦不住它。**照实记着，这一批没治好它。**
EXPECT_SHAPE_LEFTOVER = (388,)
#
# ── **半屏那道门**（P96 ③ 量清 / P98 换判据）──────────────────────────────
# P94 ⑤ 那一刀在**十组手挑的正反例**上量到「半屏一格都没承重」，并写下
# 「放宽它之前先看那一刀」。P96 把分母换成**全库 765 屏**重量：
# **它拦着 7 屏**（`K` 上是 13 屏）。⇒ **它不是「永远绿的闸」，它真拦东西。**
# ⚠️ **P96 那 7 屏 P98 复现过，逐格相同**，冻在下面这个常数里。
EXPECT_SHAPE_HALF_P96 = (65, 587, 588, 590, 595, 596, 597)
# **P98 换门之后它还拦着哪几屏**：只剩 2 屏。
# **i=65 仍然拦着**（该拦，这笔账一分没欠）、**i=590 仍然拦着**（该放，**没治好**，
# 那一族被 `topics` 劈成四个码，共同码只盖 3 格 —— 写在 `kb/fact_distinct` 第 ⑥ 格）。
EXPECT_SHAPE_HALF = (65, 590)
# 那 2 屏**逐条读完**：(该放, 该拦)。P96 那 7 屏的读数是 (6, 1)，冻在下面。
EXPECT_SHAPE_HALF_READ = (1, 1)
EXPECT_SHAPE_HALF_READ_P96 = (6, 1)
# **那 7 屏各自的「团自己那个话题码盖住几格」**（`i` 升序，跟 `EXPECT_SHAPE_HALF_P96` 对齐）。
# **这一列就是新门跟老门分开的地方**：i=65 和 i=590 盖 3 格（<半屏，仍然拦着），
# 另外 5 屏盖 6/6/8/7/7 格（≥半屏，放行）。
EXPECT_SHAPE_COVER7 = (3, 6, 6, 3, 8, 7, 7)
# ⚠️ **这是「把这道门整个摘光」的读数，不是今天在跑的那一版**：判「是」12 → 19 屏、
# 真 11 → 17、假 1 → 2。**P98 判「不摘」**——按库拆开，摘光多出来的 6 屏全在小库，
# 多出来的那 1 屏假阳性（i=65）在大库，大库假阳性 16.7% → 28.6%，而 83.8% 的查询落在大库。
EXPECT_SHAPE_NOHALF = (19, 17, 2)
# **摘光之后大库那一对**（真, 假）——**「不摘」那个判的数本身**。
EXPECT_SHAPE_NOHALF_BIGLIB = (5, 2)
#
# ── **稀疏化那条量法能不能直接量 `obj`**（P96 ①，判「不能」）────────────────
# P75/P88 那条 `spread = k / E(n)` 接得上 `obj`（只换一个「谁算命中」的口，
# 稀疏化数学一行都不用抄），**但量出来的数在读过的那 18 屏上正反例完全重叠**：
# 人读**真**的那几个撑团 obj：0.752(`product`) 0.728(`note`) 0.707(`ui`)
#   0.580(`tool`) 0.440(`memory`) + 4 个 `None`（`diploma`/`battery`/`slide` 命中不够 20 次）；
# 人读**假**的那几个：0.764(`agent`) 0.592(`手环`) **0.361(`广告`)** + 2 个 `None`(`chip`)。
# ⚠️ **方向还是反的**：P94 点名的泛 obj `广告` 打出全场最低分（= 最「不泛」）。
# ⇒ 卡的是同一格 P92 那句话：**「不泛」≠「挂它的两条事实说的是同一件事」**。
EXPECT_SHAPE_OBJFACE = ((0.440, 0.752), (0.361, 0.764))   # (真的那批 min/max, 假的那批 min/max)

# ── `--cf-hold`：**屏级判据的留出集**（P100，收 P98 ④）────────────────────────
#
# **为什么这一支必须在仓库里**：P98 量到「字面 3-gram 包含度」那条路在读过的 18 屏上
# **真活 12/12、假活 1/6**，比 `M` 还好，**但它卡在「没有留出集」那一格**。
# P90 给 `WHO_GENERIC=0.85` 造过两份留出集、204 条人标才敢定值——这一支就是那件事。
# 造法（口径写死在 `cf_hold()` 里，**改那儿就得改这几个数**）：
#
#   ① **换一族没人跑过的查询**：同一份 `recall_query3`、同一份语料、同一批段落，
#      只把 `RECALL_CONTEXT_BEFORE` 换成 `EXPECT_HOLD_WIDTHS` 那九个值
#      （**200 是 HEAD 那一套，不在里面**），按 `(用户, 查询)` 互相 + 跟 765 那套去重；
#   ② **防污染**：留出屏的 fact id 集合跟 `p94-shape-18` / `p96-halfdoor-7`
#      那 25 屏任意一屏 Jaccard ≥ 0.5 的**整屏剔掉**；池内同一条规则再去一次重；
#   ③ **分层**：A 层 = `K` 团 ≥3（**字面那条路唯一说得了话的那批屏**，主验面 =「判是」），
#      B 层 = 判得了但 `K` 团 <3（顺带验「判不是」），种子 `EXPECT_HOLD_SEED` 打乱；
#   ④ **盲标**：单子上只有槽位字母 + 正文，**没有分数 / 团 / fact id / 屏号**，
#      标完才揭晓（顺序见 `docs/TRACELOG-product.md` P100 §A）。
#
# ⚠️ **这不是 765 那套查询的 i.i.d. 抽样**：同一批语料、同一批段落、**换上下文宽度**，
# 分布偏短查询。留出集的读数只能说「**在这一族查询上**」，不能直接当 765 上的期望值。
EXPECT_HOLD_WIDTHS = (0, 40, 80, 120, 160, 300, 400, 600, 1000)
EXPECT_HOLD_SEED = 100100
EXPECT_HOLD_QUERIES = 2058          # 九个宽度合起来、去过重之后的留出查询条数
EXPECT_HOLD_POOL = (1233, 51, 532, 242)   # (空屏, 防污染剔掉, 池内重复剔掉, 留下)
EXPECT_HOLD_LAYERS = (7, 99)        # 判得了的留出屏分层（A 层全体, B 层全体），**抽之前**
EXPECT_HOLD_SHEET = (7, 20)         # 真上了盲标单的 (A, B)
EXPECT_HOLD_LIBS = (("terrence", 17), ("terrence-rewrite", 10))
# **A 层那 7 屏背后只有这么多个互不相同的团**——「7 屏」这个分母是虚的，
# 证据的单位是团。⚠️ 这个数就是这份留出集**分辨率的上限**。
EXPECT_HOLD_FAMS = 5
# **人标的原始读数**（`H01…H27` 顺序）：这一屏里说同一件事的那一族是哪几个槽位字母；
# `""` = 没有 ≥3 条的族；`"?"` = 拿不准（**不进分母**）。
# ⚠️ **只记原始读数，不记「这屏该不该判是」**——「够不够半屏」在揭晓那一步按
# 「量得了的格」算（`measurable` 本身是被测判据的一部分，盲标的人看不见）。
EXPECT_HOLD_FAM = ("abc", "", "", "", "cefg", "", "", "", "", "", "", "", "",
                   "?", "", "", "", "", "dgh", "", "", "", "", "", "", "", "")
EXPECT_HOLD_READ = (1, 25, 1)       # 人判「是这形状」/「不是」/ 拿不准（分母 = 量得了的格）
# —— 三条判据在 **A 层**（主验面）上的读数：(判「是」, 真, 假) ——
EXPECT_HOLD_A_K = (6, 0, 6)         # `K` + 今天这道门：**判是 6 屏，一屏真的都没有**
EXPECT_HOLD_A_M = (0, 0, 0)         # `M` + 今天这道门：**一次都没开口**（0 假阳性是空的，分母 0）
# **P98 那条路**（`K` + 门 + 团里两两字面 3-gram 包含度 mean ≥ cut），
# cut **用 P98 那一批定死的 0.07–0.10，一格都没按留出集调**：(cut×100, 判是, 真, 假)。
# ⚠️ **这一行就是「不接」那个判的全部分量**：in-sample 真 12/12、假 1/6，
# 换到 5 个没见过的团上**真 0 / 假 3–5**。
EXPECT_HOLD_A_GRAM = ((7, 5, 0, 5), (8, 3, 0, 3), (9, 3, 0, 3), (10, 3, 0, 3))
# **人读判「是」、而 `K` / `M` / 字面那条路三条都漏掉的那一屏**（B 层）。
# H05：四条「用 hello@memocat.ai 当对外联系邮箱」，`K` 团只打到 2（另两条 obj/topics 都不相交）。
EXPECT_HOLD_MISS = ("H05",)
# **防污染的基准是哪 25 屏**：`p94-shape-18` 那 18 屏（`K` + 老那道门判「是」）
# + `p96-halfdoor-7` 那 7 屏（= `EXPECT_SHAPE_HALF_P96`，`M` 团够了只差半屏）。
# ⚠️ 它一动，**这份留出集「没人读过」这句话就不成立了**，27 条人标连同下面所有读数一起作废。
EXPECT_HOLD_READ25 = (22, 40, 65, 94, 101, 273, 307, 337, 388, 427, 575, 587, 588,
                      590, 591, 595, 596, 597, 637, 638, 655, 656, 657, 677, 698)

# ── `--fam2`：**`FAMILY_MIN` 该不该是 2**（P104，收 P102 ①）────────────────────
#
# P102 判「合同义码不接」，留的第一条账是：`S` 那一支在 2463 对事实上翻了 4 对、
# **2 屏的团 1→2**，而 `FAMILY_MIN = 3` 够不着门 ⇒「开了口、顶不过门」。
# 它留的话是「**先量「团 == 2 的那 99 屏里有多少是真的」，别接着合码**」。这一支就是那件事。
#
# ⚠️ **台账上那个 99 是 `K` 的数**（P94 写下它的时候判据还是 `K`）。
# **HEAD 今天跑的是 `M`**（P96 换的，`K` ∧ 不同 `unit`），`M` 团 == 2 只有 37 屏。
# 两套**分开记，别混成一个数**——这一支两套都量。
#
# 人标那 111 条是**数据**（`tests/fixtures/memory_sample.jsonl` 的 `p104-fam2-111`，
# 盲标：单子上只有洗过的屏号 + 每格正文，没有团 / `cover` / 判据 / 库名 / 查询 / 原始序号），
# 这一支只负责**把机械的那一半重算一遍**，并且逐屏跟标注里存的机器读数对，对不上当场抛。
EXPECT_FAM2_POP = (99, 37, 25, 111)     # (`K` 团==2, `M` 团==2, 交, 并 = 这一批普查的屏数)
EXPECT_FAM2_LIBS_K = (("fresh678", 4), ("fresh678b", 2), ("fresh678c", 4),
                      ("shot-demo", 3), ("terrence", 41), ("terrence-rewrite", 45))
EXPECT_FAM2_LIBS_M = (("shot-demo", 2), ("terrence", 21), ("terrence-rewrite", 14))
# **机器在「团 == 2」上挑的那一对，人读判是不是「同一句话的多种说法」**：(分母, 真)。
# ⚠️ 判的是**机器挑的那一对**，不是「这一屏有没有真的一对」——挑错了就是假，
# 哪怕同一屏上另有一对是真的（实拍：Q047 / Q017 / Q057 三屏都是这个形状）。
EXPECT_FAM2_PAIR_K = (99, 32)           # 32/99 = 32.3%
EXPECT_FAM2_PAIR_K_LIBS = (("fresh678", 0, 4), ("fresh678b", 0, 2), ("fresh678c", 0, 4),
                           ("shot-demo", 0, 3), ("terrence", 8, 41),
                           ("terrence-rewrite", 24, 45))
EXPECT_FAM2_PAIR_M = (37, 8)            # 8/37 = 21.6%
EXPECT_FAM2_PAIR_M_LIBS = (("shot-demo", 2, 2), ("terrence", 2, 21),
                           ("terrence-rewrite", 4, 14))
# **屏级**：`FAMILY_MIN` 3→2 之后这 765 屏上判「是」从 17 涨到 37。
EXPECT_FAM2_FLAG = (17, 37)
# **新增的那 20 屏，人读判真的有几屏** —— `(新增, 其中真的)`。**这一行就是判的正文。**
EXPECT_FAM2_NEW = (20, 0)
EXPECT_FAM2_NEW_LIBS = (("shot-demo", 0, 2), ("terrence", 0, 13), ("terrence-rewrite", 0, 5))
EXPECT_FAM2_NEW_IDX = (24, 25, 27, 54, 67, 82, 88, 94, 101, 151, 273, 337,
                       412, 418, 427, 575, 603, 604, 662, 663)
EXPECT_FAM2_NEW_WHY = (16, 4)   # 新增里靠 `cover×2 ≥ n` 进来的 / 靠 `团×2 ≥ n` 进来的
# **这 111 屏里人读判「该判是」的**：(真@2, 真@3)。⚠️ 5 屏里**一屏都不在新增那 20 屏里**
# —— 放宽门槛买到的全是假的，而真的那 5 屏放宽了也照样捞不着。
EXPECT_FAM2_TRUE = (5, 4)
EXPECT_FAM2_TRUE_IDX = (45, 316, 320, 694, 696)
# **P102 那两屏（i=694 / 696）的解剖**：(量得了, 人读的族有几格, `M` 团, `M` 盖住)。
# ⚠️ **差的不是 1**：就算 `S` 把团合到 2，`2×2 = 4 < 8`、`盖住 2×2 = 4 < 8`，
# **半屏那道门照样不放行**；人读的族有 5 格，机器差的是 3 格，而且是**召回不到**，不是门槛高。
EXPECT_FAM2_S = (8, 5, 1, 2)
# ── 留出集那一面（P100 那 27 屏，**只会多判是的改动，要的正是假阳性那一面**）──
# 27 屏原样、人标原样，只把门从 3 放到 2 重算一遍：(判是, 真, 假)。
EXPECT_FAM2_HOLD_K = ((6, 0, 6), (8, 0, 8))     # `K`+门：fmin=3 → fmin=2
EXPECT_FAM2_HOLD_M = ((0, 0, 0), (0, 0, 0))     # `M`+门：两头都是 0
EXPECT_FAM2_HOLD_NEW = ("H13", "H15")           # `K` 那一头新增的两屏，**都是假的**
# ⚠️ **`M` 那两个 0 是空的**（跟 P100 记的 `EXPECT_HOLD_A_M` 同一个形状）：
# 留出集上 `M` 团 == 2 的屏有这么多，**放到 2 一屏都没进门**——半屏那道门先挡着。
EXPECT_FAM2_HOLD_M2 = 7

# ── `--fuse`：**一屏之内跨码拼族**（P106，收 P104 ①）+ **「拆汉字闸 / 屏级判据」这条线的结案账** ──
#
# ⚠️ **这一支不改产品，只读**；它跑一趟 765 屏召回 + 六个库的码表（约四分钟），**不进每批的例行清单**。
# ⚠️ 人标是**数据**（`p94-shape-18` / `p96-halfdoor-7` / `p102-merge-read-18` / `p104-fam2-111`
# / `p106-unread-59` / `p106-fuse-read-2`），这一支只重算机械那一半。
#
# **① 普查拼齐了**：`量得了 ≥3` 的 175 屏，P94–P104 读过 116 屏，
# 这一批把剩下 `K团 ≤1 ∧ M团 ≤1` 的 **59 屏**盲标普查完（`p106-unread-59`）⇒ **175/175 屏都有人读**。
# (屏, 人读出族的, 其中「该判是」= 族 ≥3 且 ≥ 半屏)
EXPECT_P106_UNREAD = (59, 12, 0)
EXPECT_P106_UNREAD_LIBS = (("fresh678b", "fixture", 2, 0, 0), ("shot-demo", "fixture", 7, 5, 0),
                           ("terrence", "script", 11, 2, 0), ("terrence", "user", 37, 5, 0),
                           ("terrence-rewrite", "script", 2, 0, 0))
# **② 「两条轴同时被劈开」的族全库有多少**：团 ≤2 那两档（`p104-fam2-111` ∪ `p106-unread-59`）里
# 人读的族 ≥3 且 ≥ 半屏的屏 → (屏, 其中族里至少一条对 `K` 团每条两轴都不沾的, P102 那把尺 R2/R1 够得着的劈开成员)。
# 4 屏 = **2 组事实**（i=694/696 同一批、i=316/320 同一批），按库 `terrence·user` 2 · `terrence-rewrite·script` 2。
# **团 ≤1 那档一屏都没有**（`EXPECT_P106_UNREAD` 第三格 = 0）；那一档里人读的 8 对两格族**8 对全是两轴同劈**。
EXPECT_P106_TWOAXIS = (4, 4, 0)
EXPECT_P106_TWOAXIS_PAIRS = (8, 8)       # 团≤1 那档人读的两格族：(对数, 其中两轴同劈)
# **③ 用户眼前的数**（这一条线结案的正文）：(量得了≥3, 其中有人读的, 人读「半屏同一句话」,
# 尺子判是, 其中真, 漏)。⚠️ **尺子判是 ≠ 用户看得见的变化**：`fact_distinct` 没接进产品
# （`test_p104::第六条b`），所以**这 22 屏今天在用户眼前一屏都没变过**。
EXPECT_P106_CENSUS = (175, 175, 22, 17, 16, 6)
EXPECT_P106_MISS = (94, 316, 320, 590, 694, 696)
# `user` 血缘那 549 屏：(屏, 空屏, 半屏同一句话)。⚠️ **空屏 64.7% vs 灌屏 1.3%**——
# 这条线七批都在第二个数上，第一个数它从来没碰过（拆汉字闸那一半量过：P90 变好 0/6、P92 变好 0/11）。
EXPECT_P106_USER = (549, 355, 7)
# i=94 两批读得不一样（P94 判真、P104 按族格数算不够半屏），**照实并排**，不挑一份：取「任一份判真」是 22，
# 只信 P104 那份是 21。
EXPECT_P106_DISAGREE = (94,)
# **④ 两条拼族判据**（都不是手写同义表 / 字面 / 拿目标那对反推的门槛）：
#   C1  **实体桥**：`(obj∩ ∨ ent∩) ∧ (topics∩ ∨ ent∩) ∧ unit≠` —— **先喂反例就死了**
#   C12 **码的分布互近邻**：每个库里 `topics` 码按挂在哪些 `obj` 上、`obj` 码按挂在哪些 `topics` 上
#       做分布向量，**互为最近邻**（余弦，**没有 cut**，df ≥2 才有向量）就并一类，`same_thing` 在并类后的码上算
# (765 屏判是, 新增, 新增里是**已读反例**的, 新增里人读真的, 4 屏两轴同劈正例修好了几屏, 8 对两格族拼上几对)
EXPECT_FUSE_C1 = (31, 14, 5, None, 0, 6)
EXPECT_FUSE_C12 = (19, 2, 0, 1, 0, 0)
EXPECT_FUSE_C12_NEW = (23, 590)
# 反例池：P94 判假 · P96 该拦 · P102 判假 · P104 放宽新增的 20 屏（逐屏读过全假），去重
EXPECT_FUSE_NEG = 33

_HEAD = re.compile(r"^#{1,6}\s")


def data_dir() -> Path:
    """`KITE_DATA_DIR`（实验语料）或 `backend/data`（真语料）。"""
    return Path(os.environ.get("KITE_DATA_DIR") or (BACKEND / "data"))


def corpus_tag(user: str) -> str:
    """这个人的 codebook 有多大、内容摘要是什么（同 `recall_selfcheck._corpus_tag`）。

    P29 抓到过一份「拷贝」里 codebook 是 718 字节的空壳，而那一批所有「全库」的数
    都建在它上面——**症状是静默变差不是报错**。所以语料指纹跟数字绑在一起。
    """
    cb = data_dir() / user / "codebook.xml"
    if not cb.is_file():
        return "no-codebook"
    return f"{cb.stat().st_size}B/{hashlib.sha256(cb.read_bytes()).hexdigest()[:8]}"


def notes_tag(db: Path | None = None) -> str:
    """笔记库的出身：篇数 / 正文总长 / 逐篇摘要的哈希（口径走 `db_guard.fingerprint`）。

    **不自己另拼一个哈希**——P62 踩过：随手拼的那个口径不同、跟台账对不上，
    看起来像库变了，其实只是两把尺。
    """
    fp = db_guard.fingerprint(db or (BACKEND / "data" / "notes.sqlite3"))
    import json
    h = hashlib.sha256(json.dumps(fp.digests, sort_keys=True,
                                  ensure_ascii=False).encode()).hexdigest()[:16]
    return f"{fp.rows['notes']}篇/{fp.chars}字/{h}"


def clean(s: str) -> str:
    """前端 `stripForRecall` 的对应物（同一份实现：后端 `kb.search.clean_query`）。"""
    return kb_search.clean_query(s or "")


def recall_query3(content: str, paragraph: str) -> tuple[str, str, str]:
    """`recallContext.recallQuery` 的逐行 Python 对应。

    返回 (查询, `'cursor' | 'tail'`, **这一趟真的拼进查询的那一截前一段**)。
    第三格逐字对应前端 `RecallQuery.before`（已 `clean` 过；`tail` 档恒为 `''`）。

    **为什么是三格而不是另写一份**（P83 A）：判「这张记忆卡是不是前一段带回来的」
    要的正是那一截前一段，而它原来只活在这个函数的局部变量里。再抄一份切法出去
    就是**同一个口径两份实现**——`corpus_lineage` 顶上那条「每个脚本各写一份正是
    批 6 出事的原因」说的就是这件事。所以这儿只多交出一格，`recall_query`
    原样保留（它的两格返回值有六处调用点在用，签名一个字没动）。
    """
    para = (paragraph or "").strip()
    p = clean(para).strip()
    if len(p) >= RECALL_MIN_CHARS and not _HEAD.match(p):
        idx = content.find(para)
        before = content[max(0, idx - RECALL_CONTEXT_BEFORE):idx] if idx > 0 else ""
        before = re.sub(r"\s+$", "", before)
        cut = before.rfind("\n\n")
        if cut >= 0:
            before = before[cut + 2:]
        before = before.strip()
        if _HEAD.match(before):
            before = ""
        return clean((before + "\n" if before else "") + para).strip(), "cursor", clean(before).strip()
    return clean(content[-RECALL_TAIL_CHARS:]).strip(), "tail", ""


def recall_query(content: str, paragraph: str) -> tuple[str, str]:
    """`recall_query3` 的前两格。**实现只有一份**，这里只是把第三格丢掉。"""
    q, mode, _before = recall_query3(content, paragraph)
    return q, mode


def users_with_codebook() -> list[str]:
    """`KITE_DATA_DIR` 下 codebook 像样的用户。1000 字节那道门槛挡的是 P29 那种空壳。"""
    root = data_dir()
    return sorted(d.name for d in root.iterdir()
                  if d.is_dir() and (d / "codebook.xml").is_file()
                  and (d / "codebook.xml").stat().st_size > 1000)


def queries_ctx(db: Path | None = None) -> list[tuple[str, str, str, str, str, str]]:
    """`queries()` 再多带两格：**发这一问时的那两段**。

    [(用户, 查询, 'cursor' | 'tail', 血缘, **光标这段（原样，没 clean）**, **前一段那一截（clean 过）**)]

    去重、顺序、筛不筛**跟 `queries()` 逐字同一条**——因为它就是这一份，
    `queries()` 只是把后两格丢掉。**一份走法，两个投影**（P83 A：
    两份走法一定会在某一批悄悄飘开，而那时两边的数谁也不知道该信哪个）。
    """
    conn = db_guard.readonly(db or (BACKEND / "data" / "notes.sqlite3"))
    users = set(users_with_codebook())
    lineage = corpus_lineage.load_lineage(conn)
    rows = conn.execute("SELECT id, user_id, title, content FROM notes ORDER BY id").fetchall()
    conn.close()
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str, str, str, str]] = []
    for nid, user, title, content in rows:
        if user not in users or not content:
            continue
        origin = corpus_lineage.classify(user, title or "", lineage.get(nid)).kind
        for para in re.split(r"\n\s*\n", content):
            q, mode, before = recall_query3(content, para)
            if not q:
                continue
            key = (user, q)
            if key in seen:
                continue
            seen.add(key)
            out.append((user, q, mode, origin, para, before))
    return out


def queries(db: Path | None = None) -> list[tuple[str, str, str, str]]:
    """[(用户, 查询, 'cursor' | 'tail', 血缘)]，按 (用户, 查询) 全局去重、顺序稳定。

    血缘走 `corpus_lineage.classify`（**不另写一份夹具名单**——每个脚本各写一份
    正是批 6 出事的原因）。**一条都不筛**，理由在模块注释里。

    **它是 `queries_ctx()` 的前四格**——走法只有一份（P83 A）。
    """
    return [(u, q, m, o) for u, q, m, o, _p, _b in queries_ctx(db)]


def by_origin(qs: list[tuple[str, str, str, str]]) -> dict[str, int]:
    from collections import Counter
    c = Counter(o for *_r, o in qs)
    return {k: c.get(k, 0) for k in corpus_lineage.ORIGINS}


def by_lib(qs: list[tuple[str, str, str, str]]) -> dict[tuple[str, str], int]:
    """**(库, 血缘) -> 条数**（P82 ①）。要从这把尺上读比率，分母在这儿。"""
    from collections import Counter
    c = Counter((u, o) for u, _q, _m, o in qs)
    return dict(sorted(c.items()))


def identity(qs: list[tuple[str, str, str, str]]) -> str:
    """出身 + 量程，一行。**整行抄进台账。**"""
    users = sorted({u for u, *_r in qs})
    cur = sum(1 for _u, _q, m, _o in qs if m == "cursor")
    corp = " ".join(f"{u}={corpus_tag(u)}" for u in users)
    lin = " ".join(f"{k} {v}" for k, v in by_origin(qs).items())
    return (f"ruler=recall tail={RECALL_TAIL_CHARS} min={RECALL_MIN_CHARS} "
            f"before={RECALL_CONTEXT_BEFORE} notes={notes_tag()} corpus[{corp}]: "
            f"queries {len(qs)} (cursor {cur} / tail {len(qs) - cur}) users {len(users)} "
            f"血缘[{lin}]  ⚠️ 要算比率先按血缘分开")


# ---------------------------------------------------------------- 这把尺跟产品差在哪（P79 ③）
#
# **P78 ⑤ 留的那笔账**：「产品窗口是光标段 + 前一段约 200 字，而离线尺子喂的是整段 300 字
# ——两头量的不是同一条」。**这件事影响的是过去所有离线数**，所以它得先被量出来。
#
# 量法：两处**分段**口径逐行摆出来比。
#   · 离线（`queries()`）：`re.split(r"\n\s*\n", content)` ——**只按空行分段**；
#   · 产品（`frontend/src/components/MarkdownEditor.paragraphAt`）：光标那一行往上往下走到
#     空行为止，**标题行也算边界，而且标题行自己单独算一段**。
# 分完段两边喂的都是同一个 `recall_query`（三个参数逐字一致，`test_p63` 钉着）。
#
# ⚠️ **量出来跟 P78 ⑤ 的判断相反，照实记**（P79 ③）：
# 765 条里产品**产不出来的只有 1 条**（i=630：离线把一个前面没空行的 `### 标题`
# 粘进了段里）；剩下 764 条产品**原样产得出来**。P78 点名的 i=80 那 300 字
# **产品照样产得出来**，壳上读到的那条「约 200 字」是**下一段**（i=81）的查询
# ——同 P78 自己问题 #3 那个「右栏读回来的是上一段」的形状。**是量具，不是两把尺。**
# 反过来产品能产出 16 条离线没有的（全是「标题分节」那一档 + 3 条 tail 档）。
EXPECT_PROD_TOTAL = 780
EXPECT_ONLY_OFFLINE = 1
EXPECT_ONLY_PRODUCT = 16


def paragraph_at(lines: list[str], n: int) -> str:
    """`MarkdownEditor.paragraphAt` 的逐行 Python 对应（行号 1-based）。

    **改那边就得改这边**——闸在 `tests/test_p79.py`，读的是真源文件。
    """
    cur = lines[n - 1]
    if not cur.strip():
        return ""
    if _HEAD.match(cur):
        return cur.strip()
    a = b = n
    while a > 1 and lines[a - 2].strip() and not _HEAD.match(lines[a - 2]):
        a -= 1
    while b < len(lines) and lines[b].strip() and not _HEAD.match(lines[b]):
        b += 1
    return "\n".join(lines[a - 1:b]).strip()


def product_queries(db: Path | None = None) -> set[tuple[str, str]]:
    """产品那一头**光标停在任何一行**都能产生的 (用户, 查询)，同样全局去重。"""
    conn = db_guard.readonly(db or (BACKEND / "data" / "notes.sqlite3"))
    users = set(users_with_codebook())
    rows = conn.execute("SELECT user_id, content FROM notes ORDER BY id").fetchall()
    conn.close()
    out: set[tuple[str, str]] = set()
    for user, content in rows:
        if user not in users or not content:
            continue
        lines = content.split("\n")
        for n in range(1, len(lines) + 1):
            q, _mode = recall_query(content, paragraph_at(lines, n))
            if q:
                out.add((user, q))
    return out


def window_gap(db: Path | None = None) -> dict:
    """离线这把尺和产品那一头**差在哪几条**。"""
    off = {(u, q) for u, q, _m, _o in queries(db)}
    prod = product_queries(db)
    return {"offline": len(off), "product": len(prod),
            "only_offline": sorted(off - prod), "only_product": sorted(prod - off)}


def check_paragraph_at_source() -> list[str]:
    """产品那个 `paragraphAt` 还是不是我们抄的这一份（同 `test_p63` 那三个参数的做法）。"""
    src = (BACKEND.parent / "frontend" / "src" / "components" / "MarkdownEditor.tsx")
    if not src.is_file():
        return ["找不到 MarkdownEditor.tsx——`paragraph_at` 抄的那一份没法核"]
    t = src.read_text(encoding="utf-8")
    bad = []
    for need in ("export function paragraphAt(",
                 "if (!cur.text.trim()) return ''",
                 "if (/^#{1,6}\\s/.test(cur.text)) return cur.text.trim()",
                 "while (a > 1 && doc.line(a - 1).text.trim() && !/^#{1,6}\\s/.test(doc.line(a - 1).text)) a--",
                 "while (b < doc.lines && doc.line(b + 1).text.trim() && !/^#{1,6}\\s/.test(doc.line(b + 1).text)) b++"):
        if need not in t:
            bad.append(f"`paragraphAt` 里找不到 `{need[:60]}`")
    return bad


# ---------------------------------------------------------------- `common_term()` 反事实（P82 ①）

def _df_only_common(self):
    """**P84 之前那一版 `common_term()`：只看 df，一个字不多问。**

    P84 给 `UserMemory.common_term()` 加了第二段（小库那一档问一句「泛词还是主题词」），
    于是 `--cf-common` 的基准不能再是 HEAD——**P82 那 49 条量的是「只看 df」对「整条关掉」**，
    拿今天的 HEAD 当基准会把两条判据的差混进去，那 49 就不是 P82 那个 49 了。
    所以两支反事实共用这一份，P82 的数**逐格复现**。
    """
    from app.database.kb import relations as R

    store, _v = self._index()
    idx = self._grep_index(store)
    if idx is None or not idx.unit_count:
        return None
    total = idx.unit_count

    def is_common(term: str) -> bool:
        n = idx.unit_df(term, floor=R.COMMON_DF_MIN)
        return (n is not None and n >= R.COMMON_DF_MIN
                and n / total >= R.COMMON_DF_RATIO)
    return is_common


def cf_common_off(qs: list[tuple[str, str, str, str]] | None = None) -> dict:
    """「库不到 `COMMON_DF_MIN / COMMON_DF_RATIO` 个 unit 就不启用 `common`」的全库对拍。

    **两趟都是反事实、同一组查询、同一份索引缓存**：基准是 `_df_only_common`
    （P84 之前那一版），对照是「小库整条关掉」。**P84 之后基准不再是 HEAD**——
    理由逐字写在 `_df_only_common` 上面。
    回的是逐条的 top-8 差，读数的人按 `by_lib` 分（**别按血缘分**，理由在 `EXPECT_BY_LIB`）。
    """
    from collections import Counter

    from app.database.kb import relations as R
    from app.database.kite.kite_memory import UserMemory

    qs = qs or queries()
    mems: dict[str, UserMemory] = {}

    def run() -> list[list[str]]:
        out = []
        for user, q, _m, _o in qs:
            m = mems.get(user) or mems.setdefault(user, UserMemory(user))
            facts, _t, _ms = m.recall(q, limit=8, evidence=True)
            out.append([f.get("id") for f in facts])
        return out

    orig = UserMemory.common_term
    # **还原只写一份**（P92 ③ 顺手收的）：这儿原来是两段一模一样的
    # `try: … finally: UserMemory.common_term = orig`，摘掉**前面那一段**的 `finally`
    # 在正常路径上一个字都看不出来（下一句马上又把它覆盖掉了）——
    # 跟 `cf_gates` 那两份 `purge()` 是**同一课**。走 `_swap_run` 之后实现只剩一份。
    ledger: list[str] = []
    swap = _swap_ledger(UserMemory, orig, run, ledger)

    head = swap(_df_only_common)

    def patched(self):
        fn = _df_only_common(self)     # ← 基准也是「只看 df」，两边只差「小库关不关」这一条
        if fn is None:
            return None
        store, _v = self._index()
        idx = self._grep_index(store)
        # **注释原来答应的那件事**：小到 6% 那条线够不着 `COMMON_DF_MIN` 时，整条判据不启用
        if idx is None or idx.unit_count * R.COMMON_DF_RATIO < R.COMMON_DF_MIN:
            return None
        return fn

    cf = swap(patched)

    changed, drop, add = [], 0, 0
    for i, (a, b) in enumerate(zip(head, cf)):
        if a == b:
            continue
        changed.append(i)
        drop += sum(1 for x in a if x not in b)
        add += sum(1 for x in b if x not in a)
    libs = Counter(qs[i][0] for i in changed)
    return {"changed": changed, "drop": drop, "add": add,
            "hit": (sum(1 for x in head if x), sum(1 for x in cf if x)),
            "libs": tuple(sorted(libs.items()))}


def cf_spread_off(qs: list[tuple[str, str, str, str]] | None = None) -> dict:
    """「把 P84 那一问拆掉，`common_term()` 回到只看 df」的全库对拍。

    **两趟都是反事实，同一组查询、同一份索引缓存**，只换 `UserMemory.common_term`。
    `add` / `drop` 读的是 **「只有 topics 轴」那一版相对反事实**：多进来多少对、少掉多少对。
    读数的人按 `by_lib` 分（**别按血缘分**，理由在 `EXPECT_BY_LIB`）。

    ⚠️ **P88 起左边不再是 HEAD**，是 `_axis_variant(True, True, ask_who=False)`
    （= P84 那一版）。理由写在 `EXPECT_CF_SPREAD_CHANGED` 上面那段：
    **两个旋钮别混成一个**，这 6 个数得继续是 `p84-spread-28` 那 28 条标注的分母。
    """
    from collections import Counter

    from app.database.kb import relations as R
    from app.database.kite.kite_memory import UserMemory

    qs = qs or queries()
    mems: dict[str, UserMemory] = {}
    rescued: set[tuple[str, str]] = set()

    def run() -> list[list[str]]:
        out = []
        for user, q, _m, _o in qs:
            m = mems.get(user) or mems.setdefault(user, UserMemory(user))
            facts, _t, _ms = m.recall(q, limit=8, evidence=True)
            out.append([f.get("id") for f in facts])
        return out

    orig = UserMemory.common_term
    # **左边是「只有 topics 轴」那一版，不是 HEAD**（P88；理由见 EXPECT_CF_SPREAD_* 那段）
    spread_only = _axis_variant(True, True, ask_who=False)

    def watched(self):
        """那一趟：顺手记下**哪些串真的被这条轴从 `common` 手里捞回来了**。"""
        fn = spread_only(self)
        if fn is None:
            return None
        store, _v = self._index()
        idx = self._grep_index(store)
        if idx is None or idx.unit_count * R.COMMON_DF_RATIO >= R.COMMON_DF_MIN:
            return fn
        total = idx.unit_count

        def wrap(term: str) -> bool:
            r = fn(term)
            if not r:
                n = idx.unit_df(term, floor=R.COMMON_DF_MIN)
                if (n is not None and n >= R.COMMON_DF_MIN
                        and n / total >= R.COMMON_DF_RATIO):
                    rescued.add((self.user_id, term))
            return r
        return wrap

    df_only = _df_only_common      # 反事实：P84 之前那一版（跟 `--cf-common` 共用一份）

    # **还原只写一份**（同 `cf_common_off`，P92 ③）
    ledger: list[str] = []
    swap = _swap_ledger(UserMemory, orig, run, ledger)
    head = swap(watched)
    cf = swap(df_only)

    changed, drop, add = [], 0, 0
    for i, (a, b) in enumerate(zip(head, cf)):
        if a == b:
            continue
        changed.append(i)
        add += sum(1 for x in a if x not in b)     # HEAD 多出来的
        drop += sum(1 for x in b if x not in a)    # HEAD 少掉的
    libs = Counter(qs[i][0] for i in changed)
    return {"changed": changed, "drop": drop, "add": add,
            "hit": (sum(1 for x in head if x), sum(1 for x in cf if x)),
            "libs": tuple(sorted(libs.items())),
            "rescued": tuple(sorted(rescued))}


def _axis_variant(ask_size: bool, ask_cjk: bool, ask_who: bool = True):
    """`common_term()` 的一个反事实版本：那几道闸**各开各关**。

    `ask_size=True` = 只在小库问（HEAD 今天的样子）；`ask_cjk=True` = 只对汉字串问（同）；
    `ask_who=True` = 话题面判「不泛」之后再问一句主语面（P88 ①，也是 HEAD 今天的样子）。

    **三个都 `True` 时必须跟产品那一份逐条同结果**——`cf_bigcorpus()` / `cf_whoaxis()`
    每次跑都拿这个自检，对不上就是这一支复刻错了，下面所有数当场作废
    （P84 那一课：接错层的量具会静静地给出漂亮的数）。

    `ask_who=False` = **P84 那一版**（P88 之前的产品）。`--cf-spread` 的左边用它，
    `--cf-whoaxis` 的右边也用它——**两个旋钮分开跑**（P86 ① 那一课）。
    """
    from app.database.kb import relations as R
    from app.database.kb import topic_face as TF

    def common_term(self):
        store, _v = self._index()
        idx = self._grep_index(store)
        if idx is None or not idx.unit_count:
            return None
        total = idx.unit_count
        small = total * R.COMMON_DF_RATIO < R.COMMON_DF_MIN

        def is_common(term: str) -> bool:
            n = idx.unit_df(term, floor=R.COMMON_DF_MIN)
            if not (n is not None and n >= R.COMMON_DF_MIN
                    and n / total >= R.COMMON_DF_RATIO):
                return False
            if ask_size and not small:
                return True
            if ask_cjk and not TF.has_cjk(term):
                return True
            face = self._topic_face(store, idx)
            if face is None:
                return True
            if face.generic(term) is not False:
                return True
            if not ask_who:
                return False
            who = self._who_face(store, idx)
            if who is None:
                return False
            return who.generic(term) is not False
        return is_common
    return common_term


def cf_whoaxis(qs: list[tuple[str, str, str, str]] | None = None) -> dict:
    """**只拆 P88 那条主语面轴**的全库对拍（P88 ①）。

    左边是**今天的 HEAD**，右边是 `_axis_variant(True, True, ask_who=False)`
    （= P84 那一版）。**一刀只动一处。**

    先跑一遍**接线自检**：`_axis_variant(True, True, True)` 必须跟产品那一份逐条相同，
    对不上下面所有数当场作废。
    """
    from collections import Counter

    from app.database.kb import relations as R
    from app.database.kite.kite_memory import UserMemory

    qs = qs or queries()
    mems: dict[str, UserMemory] = {}
    blocked: set[tuple[str, str]] = set()

    def run() -> list[list[str]]:
        out = []
        for user, q, _m, _o in qs:
            m = mems.get(user) or mems.setdefault(user, UserMemory(user))
            facts, _t, _ms = m.recall(q, limit=8, evidence=True)
            out.append([f.get("id") for f in facts])
        return out

    orig = UserMemory.common_term
    no_who = _axis_variant(True, True, ask_who=False)

    def watched(self):
        """HEAD 那一趟：顺手记下**哪些串被主语面挡回去了**（话题面放行、主语面按住）。"""
        fn = orig(self)
        if fn is None:
            return None
        store, _v = self._index()
        idx = self._grep_index(store)
        if idx is None or idx.unit_count * R.COMMON_DF_RATIO >= R.COMMON_DF_MIN:
            return fn
        prev = no_who(self)

        def wrap(term: str) -> bool:
            r = fn(term)
            if r and prev is not None and not prev(term):
                blocked.add((self.user_id, term))
            return r
        return wrap

    def swap(fn):
        UserMemory.common_term = fn
        try:
            return run()
        finally:
            UserMemory.common_term = orig

    head = swap(watched)
    copy = swap(_axis_variant(True, True, True))
    mismatch = sum(1 for a, b in zip(head, copy) if a != b)
    cf = swap(no_who)

    changed, drop, add = [], 0, 0
    for i, (a, b) in enumerate(zip(head, cf)):
        if a == b:
            continue
        changed.append(i)
        add += sum(1 for x in a if x not in b)     # HEAD 多出来的
        drop += sum(1 for x in b if x not in a)    # HEAD 少掉的
    libs = Counter(qs[i][0] for i in changed)
    return {"changed": changed, "drop": drop, "add": add,
            "hit": (sum(1 for x in head if x), sum(1 for x in cf if x)),
            "libs": tuple(sorted(libs.items())),
            "blocked": tuple(sorted(blocked)),
            "selfcheck_mismatch": mismatch}


def cf_bigcorpus(qs: list[tuple[str, str, str, str]] | None = None) -> dict:
    """**大库那一档接不接**的全库对拍（P86 ①）。

    基准是 `_df_only_common`（没有这条轴），对照两档：只拆库大小闸 / 两道闸全拆。
    读数的人按 `by_lib` 分（**别按血缘分**，理由在 `EXPECT_BY_LIB`）。

    ⚠️ **两个旋钮别混成一个**：P84 ⑤ 记的那个 175 是**两闸全拆**量出来的，
    而「大库接不接」只该看 `size` 那一档。这也正是这一支要拆开跑的理由。
    """
    from collections import Counter

    from app.database.kite.kite_memory import UserMemory

    qs = qs or queries()
    mems: dict[str, UserMemory] = {}

    def run() -> list[list[str]]:
        out = []
        for user, q, _m, _o in qs:
            m = mems.get(user) or mems.setdefault(user, UserMemory(user))
            facts, _t, _ms = m.recall(q, limit=8, evidence=True)
            out.append([f.get("id") for f in facts])
        return out

    orig = UserMemory.common_term
    runs: dict[str, list[list[str]]] = {}
    for name, fn in (("v0", _df_only_common),
                     ("head_copy", _axis_variant(True, True)),
                     # ⚠️ **这两档故意 `ask_who=False`**（P88）：它们问的是
                     # 「**P84 那条轴**拆掉库大小闸 / 两道闸会怎样」，而 `p86-bigcorpus-175`
                     # 那 175 条就是在这个形状上读完的。带上 P88 那条主语面轴的话，
                     # 大库那一档会整片塌掉（`terrence` 的 `who` 93.8% 是说话人标签，
                     # 主语面在那个库上一律回 `None` = 一个串都不捞回来），
                     # 这张表就不再是 P86 读过的那 175 条了。
                     # **接线自检不受影响**：`head_copy` 是三个闸全开那一版，仍然 ≡ 产品。
                     ("size", _axis_variant(False, True, ask_who=False)),
                     ("both", _axis_variant(False, False, ask_who=False)),
                     ("head", orig)):
        UserMemory.common_term = fn
        try:
            runs[name] = run()
        finally:
            UserMemory.common_term = orig

    # **接线自检**：复刻的 HEAD 必须跟产品那一份逐条同结果。
    mismatch = sum(1 for a, b in zip(runs["head_copy"], runs["head"]) if a != b)

    out: dict = {"selfcheck_mismatch": mismatch}
    for name in ("size", "both"):
        changed, drop, add = [], 0, 0
        for i, (a, b) in enumerate(zip(runs["v0"], runs[name])):
            if a == b:
                continue
            changed.append(i)
            add += sum(1 for x in b if x not in a)     # 对照多进来的
            drop += sum(1 for x in a if x not in b)    # 对照少掉的
        out[name] = {"changed": changed, "add": add, "drop": drop,
                     "libs": tuple(sorted(Counter(qs[i][0] for i in changed).items()))}
    return out


def _swap_ledger(UserMemory, orig, run, ledger: list):
    """给 `cf_common_off` / `cf_spread_off` 用的 `swap`：**还原只有一份实现**（P92 ③）。

    这两支原来各自写了**两段一模一样**的 `try: … finally: UserMemory.common_term = orig`。
    摘掉前面那一段的 `finally` **在正常路径上看不出来**（下一句马上又覆盖了它），
    于是任何闸都是绿的——**跟 `cf_gates` 那两份 `purge()` 是同一课**（P90 ④）。
    这儿不改行为、只把实现收成一份：两次调用走同一个 `_swap_run`，
    `ledger` 留下 `("before", "after") × 趟数` 的脚印。

    ⚠️ **这两支故意不清缓存**（`mems` 跨两趟共用，`--cf-common` / `--cf-spread`
    的数就是在这个形状上量出来的）。所以这儿的 `purge` **只记账、不动缓存**——
    真去清一遍会把那两支钉死的数全改掉。
    """
    def swap(fn):
        return _swap_run(
            fn,
            install=lambda f: setattr(UserMemory, "common_term", f),
            restore=lambda: setattr(UserMemory, "common_term", orig),
            run=run,
            purge=ledger.append,      # **只记账**：见上面那段 ⚠️
        )
    return swap


def _en_low_variant(en_th: float):
    """HEAD 逐字不动，**只把「英文串一律 `return True`」那一格换掉**（P92 ①）。

    英文串改问 `topics` 面、门槛 `en_th`：`spread < en_th` 才捞回来；
    `None`（判不了）照旧算 common。**不问主语面**（那条轴在英文串上没有信号）。

    ⚠️ 汉字串那一整条链（`topics@SPREAD_GENERIC` → `who@WHO_GENERIC`）**一个字不动**——
    这就是 P90 ① 那句「一个门槛服两个 population = 一刀动两处」的解法：
    **英文单独一个常数**。它是**第二个旋钮**，所以这一支只用来量，没进产品。
    """
    from app.database.kb import relations as R
    from app.database.kb import topic_face as TF

    def common_term(self):
        store, _v = self._index()
        idx = self._grep_index(store)
        if idx is None or not idx.unit_count:
            return None
        total = idx.unit_count
        small = total * R.COMMON_DF_RATIO < R.COMMON_DF_MIN

        def is_common(term: str) -> bool:
            n = idx.unit_df(term, floor=R.COMMON_DF_MIN)
            if not (n is not None and n >= R.COMMON_DF_MIN
                    and n / total >= R.COMMON_DF_RATIO):
                return False
            if not small:
                return True
            face = self._topic_face(store, idx)
            if face is None:
                return True
            if not TF.has_cjk(term):
                s = face.spread(term)
                return not (s is not None and s < en_th)
            if face.generic(term) is not False:
                return True
            who = self._who_face(store, idx)
            if who is None:
                return False
            return who.generic(term) is not False
        return is_common
    return common_term


def _en_low_rescued(en_th: float) -> tuple:
    """`_en_low_variant(en_th)` 比 HEAD **真正多放行的那些英文串**，(串, spread) 排好序。

    **反例得真的落在被测分支里**（P89 第 ⑧ 刀那一课）：这一支的「变了 N 条」只有在
    确实多放行了串的时候才算数。候选串不是手挑的，是这个库那几条查询切出来的全部
    （分词器 + `_candidate_terms` 两路都要——只取分词器那一路会漏掉 `speaker` / `memory`，
    **P90 那张「英文串一共 7 个」的表就是这么漏的，P92 重数是 9 个**）。
    """
    from app.database.kb import relations as R
    from app.database.kb import search as S
    from app.database.kb import topic_face as TF
    from app.database.kite.kite_memory import UserMemory

    qs = queries()
    got: list[tuple[str, float]] = []
    for user in sorted({u for u, *_r in qs}):
        m = UserMemory(user)
        store, _v = m._index()
        idx = m._grep_index(store)
        if idx is None or not idx.unit_count:
            continue
        total = idx.unit_count
        if not (total * R.COMMON_DF_RATIO < R.COMMON_DF_MIN):
            continue                       # 大库：这一刀够不着
        face = TF.TopicFace(store.facts.values(), units_for=idx.units_for)
        seg = m.segment()
        cand: set[str] = set()
        for u, q, _mo, _o in qs:
            if u != user:
                continue
            cand |= set(seg(S.squeeze(S.clean_query(q))))
            cand |= set(m._candidate_terms(S.clean_query(q)))
        for t in sorted(cand):
            if TF.has_cjk(t) or len(t) < 2:
                continue
            n = idx.unit_df(t, floor=R.COMMON_DF_MIN)
            if not (n is not None and n >= R.COMMON_DF_MIN
                    and n / total >= R.COMMON_DF_RATIO):
                continue
            s = face.spread(t)
            if s is not None and s < en_th:
                got.append((t, round(s, 3)))
    return tuple(sorted(got))


def _swap_run(fn, *, install, run, restore, purge):
    """换一份 `common_term` 跑一趟：**装上 → 清一次 → 跑 → 还原 → 再清一次**。

    ## 为什么它是个模块级函数而不是 `cf_gates` 里的闭包（P92 ③）

    P90 ④ 留的账，原话：

    > `cf_gates` 的 `purge()` **写了两份**（`try:` 前面一次、`finally:` 里一次），
    > 而**任何一份单独就够清干净缓存**。所以 ⑥（只摘前面那份）绿、⑥″（只摘 `finally`
    > 那份）也绿、⑥′（两份都摘）才红。**闸分不开「是哪一份被摘了」。**
    > 要分开就得让那两处**各自可观测**（比如各记一次），**这一批没做**。

    这一批做了，做法就是这个函数：

    * 两次 `purge` 各带一个 `when`（`"before"` / `"after"`），调用方把它**各记一笔**；
    * `cf_gates` 每跑完一趟就断言那本账等于 `EXPECT_CF_GATES_PURGES`；
    * `test_p92::第三条` 拿**假的 install/run/restore/purge** 直接测这个函数
      （不要真语料、不要 `UserMemory`），所以**摘掉任何一句 `purge(...)` 都红，
      而且红的是能指出「少的是哪一句」的那条**。

    ⚠️ **那份冗余本身不是错**——「前面先清一次」是防御性写法（缓存是类级的，
    上一趟别的支路可能留了脏东西）。这儿收紧的是**闸的分辨率**，不是把一句删掉：
    两句都还在，只是现在各自留了脚印。
    """
    install(fn)
    purge("before")
    try:
        return run()
    finally:
        restore()
        purge("after")


def cf_shape(qs: list[tuple[str, str, str, str]] | None = None) -> dict:
    """**一屏里有没有半屏是同一句话的多种说法**，HEAD 和 en060 各量一遍（P94）。

    尺在 `app/database/kb/fact_distinct`（**没接进产品**）。这儿只是把它套在
    `cf_gates` 那同一个 `recall(limit=8, evidence=True)` 上跑两趟。

    ⚠️ **换 `common_term` 一样要清那两份脸的类级缓存**，理由逐字同 `cf_gates`：
    不清的话右边那趟量的还是 HEAD 的屏，于是「翻了 3 屏」会静静地量成 **0**，
    而 0 看上去恰好像个漂亮的结论（「en060 没造出灌屏」），**正好是反的**。
    这儿用的就是 `_swap_run` 那一份实现，账本一样断言 `EXPECT_CF_GATES_PURGES`。
    """
    from collections import Counter

    from app.database.kb import fact_distinct as FD
    from app.database.kite.kite_memory import UserMemory

    qs = qs or queries()
    mems: dict[str, UserMemory] = {}
    ledger: list[str] = []

    def purge(when: str) -> None:
        ledger.append(when)
        mems.clear()
        for k in list(UserMemory._cache):
            if k.endswith("#whoface") or k.endswith("#topicface"):
                UserMemory._cache.pop(k, None)

    def run() -> list[dict]:
        out = []
        for user, q, _m, _o in qs:
            m = mems.get(user) or mems.setdefault(user, UserMemory(user))
            facts, _t, _ms = m.recall(q, limit=8, evidence=True)
            store, _v = m._index()
            recs = [store.facts[f["id"]] for f in facts if f.get("id") in store.facts]
            s = FD.screen_shape(recs)
            # **「瞎掉」那一栏为什么瞎，当场记下来**（P96 ②）：P94 把 441 屏整笔
            # 归给「43.3% 的事实没有 `obj`」，拆开看**只有 19 屏**真能归到 obj 头上。
            s["why_blind"] = ("空屏" if not recs
                              else "无topics" if not any(f.topics for f in recs)
                              else "只缺obj" if not any(f.obj for f in recs)
                              else "能说话")
            out.append(s)
        return out

    orig = UserMemory.common_term

    def swap(fn):
        mark = len(ledger)
        out = _swap_run(fn, install=lambda f: setattr(UserMemory, "common_term", f),
                        restore=lambda: setattr(UserMemory, "common_term", orig),
                        run=run, purge=purge)
        got = tuple(ledger[mark:])
        if got != EXPECT_CF_GATES_PURGES:
            raise AssertionError(
                f"缓存该清两次（{EXPECT_CF_GATES_PURGES}），这一趟清的是 {got} —— 这一支的数当场作废")
        return out

    head = swap(orig)
    en = swap(_en_low_variant(EXPECT_CF_GATES_EN060_TH))
    den = [i for i, s in enumerate(head) if s["measurable"] >= 3]
    fh = [i for i in den if head[i]["flagged"]]
    fe = [i for i, s in enumerate(en) if s["measurable"] >= 3 and s["flagged"]]
    libs = Counter(qs[i][0] for i in fh)
    dens = Counter(qs[i][0] for i in den)
    # **半屏那道门自己拦下来的是哪几屏**（P96 ③）：团够了（≥ `FAMILY_MIN`）、
    # 只差「≥ 半屏」那一格。P94 ⑤ 那一刀在**十组手挑的正反例**上量到「一格都没承重」，
    # 换成**全库 765 屏**它拦着 7 屏 —— 逐条读完 **1 屏该拦 / 6 屏该放**。
    # ⚠️ **P98 换了门的判据**（`团×2 ≥ n` **或** `这一族的话题码盖住 ×2 ≥ n`），
    # 于是这一档从 7 屏掉到 2 屏（`65` / `590`）。**老门那 7 屏冻在 `EXPECT_SHAPE_HALF_P96`**，
    # 下面 `nohalf` / `cover7` 两档让「换门」和「摘门」两个读数一趟里都拿得到。
    half = tuple(i for i in den
                 if head[i]["family"] >= FD.FAMILY_MIN and not head[i]["flagged"])
    # **摘光那道门**是什么读数（团 ≥ `FAMILY_MIN` 就算），**不落地，只当对照**
    nohalf = tuple(i for i in den if head[i]["family"] >= FD.FAMILY_MIN)
    # 老门那 7 屏各自的「团自己那个话题码盖住几格」——**新门跟老门分开的就是这一列**
    cover7 = tuple(head[i]["cover"] for i in EXPECT_SHAPE_HALF_P96)
    wb = Counter(s["why_blind"] for s in head)
    return {"total": len(den), "blind": sum(1 for s in head if s["measurable"] == 0),
            "head": tuple(fh), "en060": tuple(fe), "half": half,
            "nohalf": nohalf, "cover7": cover7,
            "blind_why": (wb["空屏"], wb["无topics"], wb["只缺obj"]),
            "flip_on": tuple(i for i in fe if i not in set(fh)),
            "flip_off": tuple(i for i in fh if i not in set(fe)),
            "libs": tuple(sorted((u, libs.get(u, 0), dens.get(u, 0)) for u in dens))}


def _hold_clique(facts, same) -> list[int]:
    """一屏里最大的团，**在量得了的格之间**算。

    ⚠️ 这是 `fact_distinct.largest_family` 的**第二份实现**，存在只有一个理由：
    那一份把 `same_thing`（= `M`）写死了，而这一支要在**同一屏上同时量 `K` 和 `M`**。
    「同一个字面量有第二份」这一课在这个仓库里咬过六次，所以 `cf_hold()` 顶上有一条
    **强制自检**：喂 `FD.same_thing` 的时候这一份必须跟那一份**逐屏相同**，
    对不上当场抛、整支的数作废。
    """
    from itertools import combinations

    from app.database.kb import fact_distinct as FD

    idx = [i for i, f in enumerate(facts) if FD.measurable(f)]
    for size in range(len(idx), 0, -1):
        for combo in combinations(idx, size):
            if all(same(facts[a], facts[b]) for a, b in combinations(combo, 2)):
                return list(combo)
    return []


def _hold_grams(s: str, n: int = 3) -> set[str]:
    s = "".join((s or "").lower().split())
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def _hold_containment(a: str, b: str) -> float:
    """**字面 3-gram 包含度**（交 / 两边较小的那个）——P92 量过、P98 拿它走第四条路的那一版。

    ⚠️ 用**包含度**不是 Jaccard：P92 实测那一族样板句长短差一倍，Jaccard 量错了轴
    （34 条命中只认出 5.9%）。
    """
    ga, gb = _hold_grams(a), _hold_grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / min(len(ga), len(gb))


def cf_hold(qs: list[tuple[str, str, str, str]] | None = None) -> dict:
    """**屏级判据的留出集**（P100，收 P98 ④）。口径和理由写在 `EXPECT_HOLD_*` 上面那段。

    ⚠️ **这一支不改产品，只读**；它跑 `EXPECT_HOLD_QUERIES` + 25 趟召回，**约十分钟**。
    ⚠️ 人标那 27 条是**数据**（`EXPECT_HOLD_FAM`，同一份也在
    `tests/fixtures/memory_sample.jsonl` 的 `p100-holdout-27` 里，
    `test_p100::第三条a` 钉着两份逐格相同）——这一支只负责**把机械的那一半重算一遍**。
    """
    import random
    from collections import Counter

    from app.database.kb import fact_distinct as FD
    from app.database.kite.kite_memory import UserMemory

    qs = qs or queries()
    mems: dict[str, UserMemory] = {}

    def recall_recs(user: str, q: str) -> list:
        m = mems.get(user) or mems.setdefault(user, UserMemory(user))
        facts, _t, _ms = m.recall(q, limit=8, evidence=True)
        store, _v = m._index()
        return [store.facts[f["id"]] for f in facts if f.get("id") in store.facts]

    def same_k(a, b) -> bool:
        return bool(set(a.obj) & set(b.obj)) and bool(set(a.topics) & set(b.topics))

    # ① 防污染的基准：读过的那 25 屏各自的 fact id 集合
    read_sets = [{f.id for f in recall_recs(qs[i][0], qs[i][1])} for i in EXPECT_HOLD_READ25]

    # ② 留出查询：九个宽度，互相 + 跟 765 那套去重
    base = {(u, q) for u, q, _m, _o in qs}
    seen = set(base)
    hq: list[tuple[str, str, str, str]] = []
    old_before = RECALL_CONTEXT_BEFORE
    try:
        for w in EXPECT_HOLD_WIDTHS:
            globals()["RECALL_CONTEXT_BEFORE"] = w
            for u, q, m, o in queries():
                if (u, q) in seen:
                    continue
                seen.add((u, q))
                hq.append((u, q, m, o))
    finally:
        globals()["RECALL_CONTEXT_BEFORE"] = old_before
    if RECALL_CONTEXT_BEFORE != old_before:
        raise AssertionError("上下文宽度没还回去 —— 后面所有数作废")

    # ③ 跑召回 + 防污染 + 池内去重
    jac = 0.5
    kept: list[tuple[tuple, list]] = []
    kept_sets: list[set] = []
    empty = dirty = dup = 0
    for user, q, mode, origin in hq:
        recs = recall_recs(user, q)
        ids = {f.id for f in recs}
        if not ids:
            empty += 1
            continue
        if any(len(ids | rs) and len(ids & rs) / len(ids | rs) >= jac for rs in read_sets):
            dirty += 1
            continue
        if any(len(ids | ks) and len(ids & ks) / len(ids | ks) >= jac for ks in kept_sets):
            dup += 1
            continue
        kept.append(((user, q, mode, origin), recs))
        kept_sets.append(ids)

    # ④ 分层（**自检**：`_hold_clique` 喂 `same_thing` 必须跟产品那一份逐屏相同）
    A, B = [], []
    for meta, recs in kept:
        n = sum(1 for f in recs if FD.measurable(f))
        if n < FD.FAMILY_MIN:
            continue
        fm = _hold_clique(recs, FD.same_thing)
        if fm != FD.largest_family(recs):
            raise AssertionError("`_hold_clique` 跟 `largest_family` 对不上 —— 第二份实现飘了，数作废")
        fk = _hold_clique(recs, same_k)
        row = {"meta": meta, "recs": recs, "meas": n, "famK": fk, "famM": fm,
               "coverK": FD.family_cover(recs, fk), "coverM": FD.family_cover(recs, fm)}
        (A if len(fk) >= FD.FAMILY_MIN else B).append(row)

    rnd = random.Random(EXPECT_HOLD_SEED)
    a_cap, b_n = 40, 20
    sheetA = A if len(A) <= a_cap else rnd.sample(A, a_cap)
    sheetB = B if len(B) <= b_n else rnd.sample(B, b_n)
    pool = [(r, "A") for r in sheetA] + [(r, "B") for r in sheetB]
    rnd.shuffle(pool)

    # ⑤ 逐屏对上人标
    if len(pool) != len(EXPECT_HOLD_FAM):
        raise AssertionError(f"单子 {len(pool)} 屏，人标 {len(EXPECT_HOLD_FAM)} 条 —— 对不上，数作废")
    rows = []
    for n, ((r, layer), fam_s) in enumerate(zip(pool, EXPECT_HOLD_FAM), 1):
        recs, meas = r["recs"], r["meas"]

        def door(f: int, c: int, meas: int = meas) -> bool:
            return (meas >= FD.FAMILY_MIN and f >= FD.FAMILY_MIN
                    and (f * 2 >= meas or c * 2 >= meas))

        flag_m = door(len(r["famM"]), r["coverM"])
        if flag_m != FD.screen_shape(recs)["flagged"]:
            raise AssertionError("这一支的门跟 `screen_shape` 对不上 —— 第二份实现飘了，数作废")
        letters = [chr(ord("a") + j) for j in range(len(recs))]
        unsure = fam_s == "?"
        human = [] if unsure or not fam_s else [letters.index(x) for x in fam_s]
        human_meas = [j for j in human if FD.measurable(recs[j])]
        真 = len(human_meas) >= FD.FAMILY_MIN and len(human_meas) * 2 >= meas
        contK = [_hold_containment(recs[a].text, recs[b].text)
                 for k, a in enumerate(r["famK"]) for b in r["famK"][k + 1:]]
        rows.append({"hid": f"H{n:02d}", "layer": layer, "user": r["meta"][0],
                     "K": door(len(r["famK"]), r["coverK"]), "M": flag_m,
                     "cont": (sum(contK) / len(contK)) if contK else 0.0,
                     "真": 真, "拿不准": unsure})

    def tally(pop, pick):
        hit = [r for r in pop if pick(r)]
        return (len(hit), sum(1 for r in hit if r["真"]),
                sum(1 for r in hit if not r["真"] and not r["拿不准"]))

    Arows = [r for r in rows if r["layer"] == "A"]
    gram = tuple((int(round(c * 100)), *tally(Arows, lambda r, c=c: r["K"] and r["cont"] >= c))
                 for c in (0.07, 0.08, 0.09, 0.10))
    return {"queries": len(hq), "pool": (empty, dirty, dup, len(kept)),
            "layers": (len(A), len(B)), "sheet": (len(sheetA), len(sheetB)),
            "libs": tuple(sorted(Counter(r["user"] for r in rows).items())),
            "fams": len({frozenset(r["recs"][j].id for j in r["famK"]) for r, _l in pool
                         if _l == "A"}),
            "read": (sum(1 for r in rows if r["真"]),
                     sum(1 for r in rows if not r["真"] and not r["拿不准"]),
                     sum(1 for r in rows if r["拿不准"])),
            "a_k": tally(Arows, lambda r: r["K"]), "a_m": tally(Arows, lambda r: r["M"]),
            "a_gram": gram,
            "miss": tuple(r["hid"] for r in rows
                          if r["真"] and not r["K"] and not r["M"])}


def _fam_door(fam: int, cover: int, meas: int, fmin: int) -> bool:
    """`screen_shape` 那道门，**只是把 `FAMILY_MIN` 拎出来当参数**（P104）。

    ⚠️ 这是 `fact_distinct.screen_shape` 里那半句的**第二份实现**，存在只有一个理由：
    这一支要在**同一屏上同时量 `FAMILY_MIN = 3` 和 `= 2`**，而产品那一份把它写死了。
    所以 `cf_fam2()` 顶上有一条**强制自检**：`fmin = FD.FAMILY_MIN` 的时候这一份
    必须跟 `FD.screen_shape(...)["flagged"]` **逐屏相同**，对不上当场抛、整支的数作废。
    """
    return meas >= fmin and fam >= fmin and (fam * 2 >= meas or cover * 2 >= meas)


def _fam2_rows() -> list[dict]:
    """人标那 111 条（`p104-fam2-111`）。**这是数据，不是这一支算出来的**。"""
    import json

    fix = BACKEND / "tests" / "fixtures" / "memory_sample.jsonl"
    rows = [json.loads(line) for line in fix.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r.get("set") == "p104-fam2-111" and "sid" in r]


def fam2_holdout() -> dict:
    """**把门从 3 放到 2，在 P100 那 27 屏留出集上多判了几屏「是」、真不真**（P104）。

    ⚠️ **不重造留出集、不重跑召回、不改人标**：27 屏的机器读数（`量得了` / `K团` / `M团`
    / `盖住`）和人标（`人读的族里量得了的`）原样取自 `p100-holdout-27`，
    这儿只把**门**换一个参数重算。**先自检**：`fmin = 3` 必须逐屏复现那 27 行里存着的
    `K判是` / `M判是`，对不上当场抛。

    ⚠️ **为什么这一面够得着**：`FAMILY_MIN` 放宽是**只会多判「是」**的改动
    （一屏都不会掉），而这份留出集自己写着「量得了假阳性、量不了召回」——**要的正是那一面**。
    ⚠️ **为什么它答不满**：`M` 那一头判「是」的分母是 **0**（`M` 团 == 2 的 7 屏
    全被半屏那道门挡在外面），**0 假阳性是空的**，跟 P100 记的 `EXPECT_HOLD_A_M` 同一个形状。
    """
    rows = _fam2_holdout_rows()
    for r in rows:
        for axis in ("K", "M"):
            if _fam_door(r[f"{axis}团"], r[f"{axis}盖住"], r["量得了"], 3) != r[f"{axis}判是"]:
                raise AssertionError(
                    f"{r['hid']} 的 {axis} 门跟仓库里存的读数对不上 —— 这一支的数作废")

    def 真(r: dict, fmin: int) -> bool:
        h = r["人读的族里量得了的"]
        return h >= fmin and h * 2 >= r["量得了"]

    def tally(axis: str, fmin: int) -> tuple[int, int, int]:
        hit = [r for r in rows if _fam_door(r[f"{axis}团"], r[f"{axis}盖住"], r["量得了"], fmin)]
        return (len(hit), sum(1 for r in hit if 真(r, fmin)),
                sum(1 for r in hit if not 真(r, fmin) and r["判"] != "?"))

    new = tuple(r["hid"] for r in rows
                if _fam_door(r["K团"], r["K盖住"], r["量得了"], 2)
                and not _fam_door(r["K团"], r["K盖住"], r["量得了"], 3))
    return {"screens": len(rows), "k": (tally("K", 3), tally("K", 2)),
            "m": (tally("M", 3), tally("M", 2)), "new_k": new,
            "m2": sum(1 for r in rows if r["M团"] == 2)}


def _fam2_holdout_rows() -> list[dict]:
    import json

    fix = BACKEND / "tests" / "fixtures" / "memory_sample.jsonl"
    rows = [json.loads(line) for line in fix.read_text(encoding="utf-8").splitlines() if line.strip()]
    out = [r for r in rows if r.get("set") == "p100-holdout-27" and "hid" in r]
    if len(out) != sum(EXPECT_HOLD_SHEET):
        raise AssertionError(f"留出集 {len(out)} 行，不是 {sum(EXPECT_HOLD_SHEET)} —— 数作废")
    return out


def cf_fam2(qs: list[tuple[str, str, str, str]] | None = None) -> dict:
    """**`FAMILY_MIN` 该不该是 2**（P104，收 P102 ①）。口径和理由写在 `EXPECT_FAM2_*` 上面那段。

    ⚠️ **这一支不改产品，只读**；它跑一趟 765 屏召回（约三分半），**不进每批的例行清单**。
    ⚠️ 人标那 111 条是**数据**（`p104-fam2-111`），这一支只把**机械的那一半**重算一遍，
    并且逐屏跟标注里存着的机器读数对，对不上当场抛。
    """
    from collections import Counter

    from app.database.kb import fact_distinct as FD
    from app.database.kite.kite_memory import UserMemory

    qs = qs or queries()
    mems: dict[str, UserMemory] = {}

    def same_k(a, b) -> bool:
        return bool(set(a.obj) & set(b.obj)) and bool(set(a.topics) & set(b.topics))

    def cover(facts, fam) -> int:
        """`family_cover` 的口径，**但不带 `FAMILY_MIN` 那道早退**——这一批要在团 == 2 上读它。"""
        if not fam:
            return 0
        common: set | None = None
        for i in fam:
            t = set(facts[i].topics)
            common = t if common is None else (common & t)
        idx = [i for i, f in enumerate(facts) if FD.measurable(f)]
        best = 0
        for t in (common or set()):
            best = max(best, sum(1 for i in idx if t in facts[i].topics))
        return best

    shots = []
    for i, (user, q, _m, _o) in enumerate(qs):
        m = mems.get(user) or mems.setdefault(user, UserMemory(user))
        facts, _t, _ms = m.recall(q, limit=8, evidence=True)
        store, _v = m._index()
        recs = [store.facts[f["id"]] for f in facts if f.get("id") in store.facts]
        fm = _hold_clique(recs, FD.same_thing)
        if fm != FD.largest_family(recs):
            raise AssertionError("`_hold_clique` 跟 `largest_family` 对不上 —— 数作废")
        fk = _hold_clique(recs, same_k)
        meas = sum(1 for f in recs if FD.measurable(f))
        cm, ck = cover(recs, fm), cover(recs, fk)
        if _fam_door(len(fm), cm, meas, FD.FAMILY_MIN) != FD.screen_shape(recs)["flagged"]:
            raise AssertionError("`_fam_door` 跟 `screen_shape` 对不上 —— 第二份实现飘了，数作废")
        shots.append({"i": i, "lib": user, "meas": meas, "famK": fk, "famM": fm,
                      "coverK": ck, "coverM": cm})

    k2 = [s for s in shots if len(s["famK"]) == 2]
    m2 = [s for s in shots if len(s["famM"]) == 2]
    sel = {s["i"] for s in k2} | {s["i"] for s in m2}

    # **逐屏对上人标**（标注里存着机器那几列，飘了当场抛）
    annot = {r["i"]: r for r in _fam2_rows()}
    if set(annot) != sel:
        raise AssertionError(f"标注 {len(annot)} 屏、这一趟选出 {len(sel)} 屏 —— 对不上，数作废")
    for s in shots:
        r = annot.get(s["i"])
        if r is None:
            continue
        got = (s["meas"], len(s["famK"]), s["coverK"], len(s["famM"]), s["coverM"])
        want = (r["量得了"], r["K团"], r["K盖住"], r["M团"], r["M盖住"])
        if got != want:
            raise AssertionError(f"i={s['i']} 的机器读数 {got} ≠ 标注里存的 {want} —— 数作废")

    def pair_true(s: dict, axis: str) -> bool:
        """机器挑的那一对**整对**落在人读的某一族里（并列的族用 `|` 分开存）。"""
        fam = set(s["fam" + axis])
        if len(fam) < 2:
            return False
        letters = annot[s["i"]]["人读的族"]
        return any(fam <= {ord(ch) - ord("a") for ch in part}
                   for part in letters.split("|") if part)

    def 真(s: dict, fmin: int) -> bool:
        h = annot[s["i"]]["人读的族里量得了的"]
        return h >= fmin and h * 2 >= s["meas"]

    def by_lib(pop, pick):
        d: dict[str, list[int]] = {}
        for s in pop:
            row = d.setdefault(s["lib"], [0, 0])
            row[1] += 1
            row[0] += 1 if pick(s) else 0
        return tuple(sorted((u, n, m) for u, (n, m) in d.items()))

    head = {s["i"] for s in shots
            if s["meas"] >= 3 and _fam_door(len(s["famM"]), s["coverM"], s["meas"], 3)}
    two = {s["i"] for s in shots
           if s["meas"] >= 3 and _fam_door(len(s["famM"]), s["coverM"], s["meas"], 2)}
    new = sorted((s for s in shots if s["i"] in two - head), key=lambda s: s["i"])
    s694 = [s for s in shots if s["i"] == 694][0]
    return {
        "pop": (len(k2), len(m2), len({s["i"] for s in k2} & {s["i"] for s in m2}), len(sel)),
        "libs_k": tuple(sorted(Counter(s["lib"] for s in k2).items())),
        "libs_m": tuple(sorted(Counter(s["lib"] for s in m2).items())),
        "pair_k": (len(k2), sum(1 for s in k2 if pair_true(s, "K"))),
        "pair_k_libs": by_lib(k2, lambda s: pair_true(s, "K")),
        "pair_m": (len(m2), sum(1 for s in m2 if pair_true(s, "M"))),
        "pair_m_libs": by_lib(m2, lambda s: pair_true(s, "M")),
        "flag": (len(head), len(two)),
        "new": (len(new), sum(1 for s in new if 真(s, 2))),
        "new_libs": by_lib(new, lambda s: 真(s, 2)),
        "new_idx": tuple(s["i"] for s in new),
        "new_why": (sum(1 for s in new if not len(s["famM"]) * 2 >= s["meas"]),
                    sum(1 for s in new if len(s["famM"]) * 2 >= s["meas"])),
        "true": (sum(1 for s in shots if s["i"] in sel and 真(s, 2)),
                 sum(1 for s in shots if s["i"] in sel and 真(s, 3))),
        "true_idx": tuple(sorted(s["i"] for s in shots if s["i"] in sel and 真(s, 2))),
        "s694": (s694["meas"], annot[694]["人读的族里量得了的"],
                 len(s694["famM"]), s694["coverM"]),
        "hold": fam2_holdout(),
    }


def _fixture(which: str) -> list[dict]:
    import json

    fix = BACKEND / "tests" / "fixtures" / "memory_sample.jsonl"
    return [r for r in (json.loads(line) for line in fix.read_text(encoding="utf-8").splitlines()
                        if line.strip())
            if r.get("set") == which and "_meta" not in r]


def _fuse_truth() -> dict[int, list[bool]]:
    """175 屏的人读：各批标注拼起来（**每一份都是人读的，这儿一个字都不判**）。"""
    out: dict[int, list[bool]] = {}
    for r in _fixture("p94-shape-18"):
        out.setdefault(r["i"], []).append(r["判"] == "真")
    for r in _fixture("p96-halfdoor-7"):
        out.setdefault(r["i"], []).append(r["判"] == "该放")
    for r in _fixture("p102-merge-read-18"):
        out.setdefault(r["i"], []).append(r["verdict"] == "真")
    for which in ("p104-fam2-111", "p106-unread-59"):
        for r in _fixture(which):
            out.setdefault(r["i"], []).append(bool(r["判@3"]))
    return out


def _fuse_merge(lib: str) -> tuple[dict, dict]:
    """C12：一个库里 `obj` / `topics` 两张码表各自按**分布互近邻**并类（**没有 cut**）。"""
    import math
    from collections import Counter, defaultdict

    from scripts import code_pair_ruler as CP

    obj_vec: dict[str, Counter] = defaultdict(Counter)
    top_vec: dict[str, Counter] = defaultdict(Counter)
    df: Counter = Counter()
    for f in CP.tables(lib)["facts"]:
        objs = (f.get("obj") or "").split()
        tops = (f.get("topics") or "").split()
        for o in objs:
            df[("obj", o)] += 1
            obj_vec[o].update(tops)
        for t in tops:
            df[("topics", t)] += 1
            top_vec[t].update(objs)

    def cos(a: Counter, b: Counter) -> float:
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return sum(a[k] * b[k] for k in a if k in b) / (na * nb) if na and nb else 0.0

    def mutual(vecs: dict[str, Counter], axis: str) -> dict[str, str]:
        codes = [c for c in vecs if df[(axis, c)] >= 2 and vecs[c]]
        nn: dict[str, str] = {}
        for c in codes:
            best, bs = None, 0.0
            for d in codes:
                if d != c:
                    s = cos(vecs[c], vecs[d])
                    if s > bs:
                        best, bs = d, s
            if best is not None:
                nn[c] = best
        par: dict[str, str] = {}

        def find(x: str) -> str:
            par.setdefault(x, x)
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x
        for c, d in nn.items():
            if nn.get(d) == c and c < d:
                par[find(c)] = find(d)
        return {c: find(c) for c in par}

    return mutual(obj_vec, "obj"), mutual(top_vec, "topics")


def cf_fuse(qs: list[tuple[str, str, str, str]] | None = None) -> dict:
    """**一屏之内跨码拼族**（P106）+ 这条线结案那张账。口径和理由写在 `EXPECT_P106_*` / `EXPECT_FUSE_*` 上面。

    ⚠️ **这一支不改产品，只读**，只在 `--fuse` 底下跑。
    """
    from app.database.kb import fact_distinct as FD
    from app.database.kite.kite_memory import UserMemory

    qs = qs or queries()
    mems: dict[str, UserMemory] = {}
    shots = []
    for i, (user, q, _m, origin) in enumerate(qs):
        m = mems.get(user) or mems.setdefault(user, UserMemory(user))
        facts, _t, _ms = m.recall(q, limit=8, evidence=True)
        store, _v = m._index()
        recs = [store.facts[f["id"]] for f in facts if f.get("id") in store.facts]
        shots.append({"i": i, "lib": user, "origin": origin, "recs": recs, "shape": FD.screen_shape(recs)})

    def same_k(a, b) -> bool:
        return bool(set(a.obj) & set(b.obj)) and bool(set(a.topics) & set(b.topics))

    # ── ① / ③ 普查 + 用户眼前的数 ─────────────────────────────────────────
    truth = _fuse_truth()
    den = [s for s in shots if s["shape"]["measurable"] >= 3]
    true = {s["i"] for s in den if any(truth.get(s["i"], ()))}
    head = {s["i"] for s in den if s["shape"]["flagged"]}
    census = (len(den), sum(1 for s in den if s["i"] in truth), len(true),
              len(head), len(head & true), len(true - head))
    user = [s for s in shots if s["origin"] == "user"]
    user_row = (len(user), sum(1 for s in user if not s["recs"]), sum(1 for s in user if s["i"] in true))
    disagree = tuple(sorted(i for i, v in truth.items() if len(set(v)) > 1))
    ur = _fixture("p106-unread-59")
    tab: dict[tuple[str, str], list[int]] = {}
    for r in ur:
        row = tab.setdefault((r["user"], r["血缘"]), [0, 0, 0])
        row[0] += 1
        row[1] += bool(r["人读的族"])
        row[2] += bool(r["判@3"])
    unread = (len(ur), sum(1 for r in ur if r["人读的族"]), sum(1 for r in ur if r["判@3"]))
    # 自检：这 59 屏正好就是 `K团≤1 ∧ M团≤1` 那一档
    zone = {s["i"] for s in den
            if len(_hold_clique(s["recs"], same_k)) <= 1 and len(s["shape"]["family_idx"]) <= 1}
    if zone != {r["i"] for r in ur}:
        raise AssertionError("`p106-unread-59` 不是 `K团≤1 ∧ M团≤1` 那一档了 —— 数作废")

    # ── ② 两轴同劈 ───────────────────────────────────────────────────────
    by_i = {s["i"]: s for s in shots}

    def split_members(s, letters: str) -> tuple[list[int], list[int]]:
        recs = s["recs"]
        F = [j for j in (ord(ch) - ord("a") for ch in letters) if FD.measurable(recs[j])]
        ck = _hold_clique([recs[j] for j in F], same_k)
        ck = [F[j] for j in ck]
        neither = [j for j in F if j not in ck and all(
            not (set(recs[j].obj) & set(recs[c].obj)) and not (set(recs[j].topics) & set(recs[c].topics))
            for c in ck)]
        return ck, neither

    from scripts import code_pair_ruler as CP

    def lit(xs, ys) -> bool:
        return any(CP.flat(a) != CP.flat(b) and CP.flat(a) and CP.flat(b)
                   and (CP.flat(a) in CP.flat(b) or CP.flat(b) in CP.flat(a)) for a in xs for b in ys) \
            or any(a != b and CP.tokens(a) & CP.tokens(b) for a in xs for b in ys)

    pos = {}
    for r in _fixture("p104-fam2-111"):
        if r["判@3"]:
            pos[r["i"]] = max(r["人读的族"].split("|"), key=len)
    two = [i for i, fam in pos.items() if split_members(by_i[i], fam)[1]]
    reach = 0
    for i in two:
        ck, nei = split_members(by_i[i], pos[i])
        recs = by_i[i]["recs"]
        reach += sum(1 for j in nei if any(lit(recs[j].obj, recs[c].obj) and lit(recs[j].topics, recs[c].topics)
                                           for c in ck))
    pairs = {r["i"]: r["人读的族"] for r in ur
             if r["人读的族里量得了的"] == 2 and len(r["人读的族"]) == 2 and "|" not in r["人读的族"]}
    pairs_split = sum(1 for i, fam in pairs.items() if split_members(by_i[i], fam)[1])

    # ── ④ 两条拼族判据 ────────────────────────────────────────────────────
    merges = {lib: _fuse_merge(lib) for lib in sorted({s["lib"] for s in shots})}

    def canon(lib: str, axis: int, codes) -> set:
        mp = merges[lib][axis]
        return {mp.get(c, c) for c in codes}

    def c12(lib):
        def f(a, b):
            return (bool(canon(lib, 0, a.obj) & canon(lib, 0, b.obj))
                    and bool(canon(lib, 1, a.topics) & canon(lib, 1, b.topics)) and a.unit != b.unit)
        return f

    def c1(lib):
        def f(a, b):
            e = bool(set(a.entities) & set(b.entities))
            return ((bool(set(a.obj) & set(b.obj)) or e)
                    and (bool(set(a.topics) & set(b.topics)) or e) and a.unit != b.unit)
        return f

    def flagged(s, same, topics_of) -> bool:
        recs = s["recs"]
        idx = [j for j, f in enumerate(recs) if FD.measurable(f)]
        fam = [idx[j] for j in _hold_clique([recs[j] for j in idx], same)]
        n = len(idx)
        cov = 0
        if len(fam) >= FD.FAMILY_MIN:
            common = set.intersection(*(topics_of(recs[j]) for j in fam))
            cov = max((sum(1 for j in idx if t in topics_of(recs[j])) for t in common), default=0)
        return n >= FD.FAMILY_MIN and len(fam) >= FD.FAMILY_MIN and (len(fam) * 2 >= n or cov * 2 >= n)

    neg = ({r["i"] for r in _fixture("p94-shape-18") if r["判"] == "假"}
           | {r["i"] for r in _fixture("p96-halfdoor-7") if r["判"] == "该拦"}
           | {r["i"] for r in _fixture("p102-merge-read-18") if r["verdict"] == "假"}
           | set(EXPECT_FAM2_NEW_IDX))
    fread = {r["i"]: r["判"] == "真" for r in _fixture("p106-fuse-read-2")}

    def branch(make, canon_topics: bool):
        got = set()
        for s in den:
            lib = s["lib"]
            tof = (lambda f, lib=lib: canon(lib, 1, f.topics)) if canon_topics else (lambda f: set(f.topics))
            if flagged(s, make(lib), tof):
                got.add(s["i"])
        new = got - head
        fixed = sum(1 for i in two if len(_hold_clique(
            [by_i[i]["recs"][ord(ch) - ord("a")] for ch in pos[i]], make(by_i[i]["lib"]))) >= FD.FAMILY_MIN)
        bridged = sum(1 for i, fam in pairs.items()
                      if make(by_i[i]["lib"])(by_i[i]["recs"][ord(fam[0]) - 97], by_i[i]["recs"][ord(fam[1]) - 97]))
        new_true = (sum(1 for i in new if fread.get(i)) if new and new <= set(fread) else None)
        return (len(got), len(new), len(new & neg), new_true, fixed, bridged), tuple(sorted(new))

    fc1, _n1 = branch(c1, False)
    fc12, n12 = branch(c12, True)
    if head != {s["i"] for s in den if flagged(s, FD.same_thing, lambda f: set(f.topics))}:
        raise AssertionError("这一支复刻的门跟 `screen_shape` 对不上 —— 数作废")
    return {"unread": unread, "unread_libs": tuple(sorted((u, o, *v) for (u, o), v in tab.items())),
            "census": census, "miss": tuple(sorted(true - head)), "user": user_row, "disagree": disagree,
            "twoaxis": (len(pos), len(two), reach), "pairs": (len(pairs), pairs_split),
            "c1": fc1, "c12": fc12, "c12_new": n12, "neg": len(neg)}


def cf_gates(qs: list[tuple[str, str, str, str]] | None = None) -> dict:
    """**库大小闸和汉字闸今天各自还挡着什么**（P90）。

    左边一律是今天的 HEAD，右边三档各只动一处（理由和三个判逐字写在
    `EXPECT_CF_GATES_*` 上面那段）。先跑**接线自检**：
    `_axis_variant(True, True, True)` 必须跟产品那一份逐条相同，对不上下面所有数作废。

    ⚠️ **这一支必须自己清 `UserMemory._cache` 里的 `#whoface` / `#topicface`**。
    那个缓存是**类级**的，而 `TAG` 那一档换的是 `WhoFace.__init__` 本身——
    不清缓存的话摘了闸的那一份**根本不会被建出来**，于是「24 条」会静静地量成
    **「0 条变了」**。这不是假设：这一批第一遍就是这么量出来的，
    而 0 看上去恰好像个漂亮的结论（「那道闸拆了也没事」），**正好是反的**。
    所以 `TAG` 那一档还带一条自检：**强行 `usable=True` 的 `WhoFace` 必须真的被建出来过，
    而且必须有一份是说话人标签过半的**——建不出来就是这一刀没落在被测分支里，当场抛。
    """
    from collections import Counter

    from app.database.kb import topic_face as TF
    from app.database.kite.kite_memory import UserMemory

    qs = qs or queries()
    mems: dict[str, UserMemory] = {}

    ledger: list[str] = []

    def purge(when: str) -> None:
        """清掉类级缓存里那两份脸，**并记一笔**（`when` = `"before"` / `"after"`）。

        `when` 不是装饰：P92 ③ 之前这儿是**两句一模一样的裸 `purge()`**，
        摘任何一句都还绿（另一句把活干了），闸分不开是哪一句被摘了。
        记了这一笔之后，两处各自可观测——见 `_swap_run` 那段和 `EXPECT_CF_GATES_PURGES`。
        """
        ledger.append(when)
        mems.clear()
        for k in list(UserMemory._cache):
            if k.endswith("#whoface") or k.endswith("#topicface"):
                UserMemory._cache.pop(k, None)

    def run() -> list[list[str]]:
        out = []
        for user, q, _m, _o in qs:
            m = mems.get(user) or mems.setdefault(user, UserMemory(user))
            facts, _t, _ms = m.recall(q, limit=8, evidence=True)
            out.append([f.get("id") for f in facts])
        return out

    orig = UserMemory.common_term

    def swap(fn):
        mark = len(ledger)
        out = _swap_run(
            fn,
            install=lambda f: setattr(UserMemory, "common_term", f),
            restore=lambda: setattr(UserMemory, "common_term", orig),
            run=run,
            purge=purge,
        )
        got = tuple(ledger[mark:])
        if got != EXPECT_CF_GATES_PURGES:
            raise AssertionError(
                f"缓存该清两次（{EXPECT_CF_GATES_PURGES}），这一趟清的是 {got} —— "
                "少清一次，摘了闸的那份脸就可能没被重建，这一支的数当场作废")
        return out

    head = swap(orig)
    mismatch = sum(1 for a, b in zip(head, swap(_axis_variant(True, True, True))) if a != b)

    def diff(cf: list[list[str]]) -> dict:
        changed = [i for i, (a, b) in enumerate(zip(head, cf)) if a != b]
        return {"changed": tuple(changed),
                "add": sum(sum(1 for x in cf[i] if x not in head[i]) for i in changed),
                "drop": sum(sum(1 for x in head[i] if x not in cf[i]) for i in changed),
                "empty": sum(1 for i in changed if head[i] and not cf[i]),
                "libs": tuple(sorted(Counter(qs[i][0] for i in changed).items()))}

    out: dict = {"selfcheck_mismatch": mismatch}
    out["size"] = diff(swap(_axis_variant(False, True, ask_who=True)))
    out["en"] = diff(swap(_axis_variant(True, False, ask_who=True)))

    # —— TAG：**只摘 `SPEAKER_TAG_MAX` 那一档**，别的一个字不动 ——
    real_init = TF.WhoFace.__init__
    built: list[tuple[int, float]] = []

    def forced(self, facts, units_for=None):
        real_init(self, facts, units_for)
        self.usable = self.filled > 0
        built.append((self.filled, self.speaker_share))

    TF.WhoFace.__init__ = forced
    try:
        tag = swap(_axis_variant(False, True, ask_who=True))
    finally:
        TF.WhoFace.__init__ = real_init
    # **反例得真的落在被测分支里**（P89 第 ⑧ 刀那一课）
    if not built:
        raise AssertionError("摘了闸的 `WhoFace` 一份都没建出来 —— 这一刀没落在被测分支里，数作废")
    if not any(s > TF.SPEAKER_TAG_MAX for _n, s in built):
        raise AssertionError(f"没建出说话人标签过半的那一份（建出来的是 {built}）—— 数作废")
    out["tag"] = diff(tag)
    out["tag"]["i607"] = (len(head[607]), len(tag[607]))

    # —— EN060：**P90 ① 留的那条路**（`topics` 轴 + 英文专用低门槛），P92 ① 走完它 ——
    # 一刀只动一处：汉字闸那一格换成「英文串改问 `topics` 面、门槛 `EXPECT_CF_GATES_EN060_TH`」，
    # 大库那道闸、汉字串那一整条链（topics@0.75 → who@0.85）**逐字不动**。
    # 英文那一半**不问主语面**——P90 的 `p90-holdout-en-60` 量过它在英文串上没有信号
    # （`ai` / `agent` 两个最要紧的判反），P92 的 137 条又量了一遍（见 `EXPECT_CF_GATES_EN060_*`）。
    out["en060"] = diff(swap(_en_low_variant(EXPECT_CF_GATES_EN060_TH)))
    # **反例得真的落在被测分支里**：这一刀必须真的多放行了串，否则「变了 11 条」是别处来的
    rescued = _en_low_rescued(EXPECT_CF_GATES_EN060_TH)
    if not rescued:
        raise AssertionError("EN060 这一刀一个英文串都没多放行 —— 没落在被测分支里，数作废")
    out["en060"]["terms"] = rescued
    return out


def check(qs: list[tuple[str, str, str, str]]) -> list[str]:
    """量程对不对。返回对不上的那几条（空 = 对得上）。"""
    cur = sum(1 for _u, _q, m, _o in qs if m == "cursor")
    users = len({u for u, *_r in qs})
    bad = []
    for name, got, want in (("queries", len(qs), EXPECT_TOTAL), ("cursor", cur, EXPECT_CURSOR),
                            ("tail", len(qs) - cur, EXPECT_TAIL), ("users", users, EXPECT_USERS)):
        if got != want:
            bad.append(f"{name}: {got} ≠ {want}")
    got_lib = by_lib(qs)
    if got_lib != EXPECT_BY_LIB:
        bad.append(f"按库分的分母变了: {got_lib} ≠ {EXPECT_BY_LIB}")
    return bad


def main(argv: list[str]) -> int:
    qs = queries()
    print(identity(qs))
    if "--list" in argv:
        i = argv.index("--list")
        n = int(argv[i + 1]) if len(argv) > i + 1 else 10
        for user, q, mode, origin in qs[:n]:
            print(f"  [{mode}/{origin}] {user} {q[:90]!r}")
    bad = check(qs)
    if "--by-lib" in argv:
        print("  按库 × 血缘（**要读比率就看这张，别看上面那行血缘分布**）：")
        for (u, o), n in by_lib(qs).items():
            print(f"    {u:18s}/{o:8s} {n:4d}")
    if "--cf-common" in argv:
        g = cf_common_off(qs)
        print(f"  `common` 小库不启用 那个反事实：top-8 变了 {len(g['changed'])} 条 / {EXPECT_TOTAL}"
              f"；掉 {g['drop']} 进 {g['add']}；有召回 {g['hit'][0]} → {g['hit'][1]}")
        print(f"    变了的落在：{g['libs']}  ⚠️ **这个旋钮只够得着这几个库**")
        print("    （49 条逐条读完：变好 16 / 变差 23 / 中性 10 → P82 ① 判「换不了」，"
              "理由在 `kb/relations.COMMON_DF_MIN` 那段注释）")
        for name, got, want in (("变了", len(g["changed"]), EXPECT_CF_COMMON_CHANGED),
                                ("掉", g["drop"], EXPECT_CF_COMMON_DROP),
                                ("进", g["add"], EXPECT_CF_COMMON_ADD),
                                ("有召回", g["hit"], EXPECT_CF_COMMON_HIT),
                                ("落在哪几个库", g["libs"], EXPECT_CF_COMMON_LIBS)):
            if got != want:
                bad.append(f"cf-common {name}: {got} ≠ {want}")
    if "--cf-whoaxis" in argv:
        g = cf_whoaxis(qs)
        if g["selfcheck_mismatch"]:
            bad.append(f"cf-whoaxis 接线自检: 复刻的 HEAD 跟产品那一份差了 "
                       f"{g['selfcheck_mismatch']} 条 —— **下面的数全部作废**")
        print(f"  P88 那条主语面轴（只拆它）那个反事实：top-8 变了 {len(g['changed'])} 条"
              f" / {EXPECT_TOTAL}；HEAD 多进 {g['add']} 少掉 {g['drop']}"
              f"；有召回 {g['hit'][0]} → {g['hit'][1]}")
        print(f"    变了的是：{g['changed']}，落在：{g['libs']}"
              "  ⚠️ **这条轴串在 topics 那条后面，只做减法**")
        print(f"    被主语面挡回去的串 {len(g['blocked'])} 种："
              f"{'、'.join(t for _u, t in g['blocked'])}")
        print("    （2 条逐条读完：变好 1（i=293 那条逐句出处回来了）/ 中性 1 / **变差 0**"
              " → P88 ① 判「接」，理由在 `kite_memory.common_term` 和 `kb/topic_face` 两段注释）")
        for name, got, want in (("变了", len(g["changed"]), EXPECT_CF_WHO_CHANGED),
                                ("多进", g["add"], EXPECT_CF_WHO_ADD),
                                ("少掉", g["drop"], EXPECT_CF_WHO_DROP),
                                ("有召回", g["hit"], EXPECT_CF_WHO_HIT),
                                ("落在哪几个库", g["libs"], EXPECT_CF_WHO_LIBS),
                                ("挡回去的串", len(g["blocked"]), EXPECT_CF_WHO_BLOCKED)):
            if got != want:
                bad.append(f"cf-whoaxis {name}: {got} ≠ {want}")
    if "--cf-spread" in argv:
        g = cf_spread_off(qs)
        print(f"  P84 那条轴（拆掉它）那个反事实：top-8 变了 {len(g['changed'])} 条 / {EXPECT_TOTAL}"
              f"；HEAD 多进 {g['add']} 少掉 {g['drop']}；有召回 {g['hit'][0]} → {g['hit'][1]}")
        print(f"    变了的落在：{g['libs']}  ⚠️ **这条轴只够得着小库那一档**")
        print(f"    真被捞回来的串 {len(g['rescued'])} 种："
              f"{'、'.join(t for _u, t in g['rescued'][:12])}…")
        print("    （28 条逐条读完：变好 14 / 变差 7 / 中性 7 → P84 判「接」，"
              "理由在 `kite_memory.common_term` 和 `kb/topic_face` 两段注释）")
        for name, got, want in (("变了", len(g["changed"]), EXPECT_CF_SPREAD_CHANGED),
                                ("多进", g["add"], EXPECT_CF_SPREAD_ADD),
                                ("少掉", g["drop"], EXPECT_CF_SPREAD_DROP),
                                ("有召回", g["hit"], EXPECT_CF_SPREAD_HIT),
                                ("落在哪几个库", g["libs"], EXPECT_CF_SPREAD_LIBS),
                                ("捞回来的串", len(g["rescued"]), EXPECT_CF_SPREAD_RESCUED)):
            if got != want:
                bad.append(f"cf-spread {name}: {got} ≠ {want}")
    if "--cf-bigcorpus" in argv:
        g = cf_bigcorpus(qs)
        if g["selfcheck_mismatch"]:
            bad.append(f"cf-bigcorpus 接线自检: 复刻的 HEAD 跟产品那一份差了 "
                       f"{g['selfcheck_mismatch']} 条 —— **下面的数全部作废**")
        print("  大库那一档（P86 ①）—— 基准都是「没有这条轴」，**两个旋钮分开跑**：")
        for name, label in (("size", "只拆库大小闸（汉字闸留着）← 判大库要看的就是这一档"),
                            ("both", "两道闸全拆 ← P84 ⑤ 记的那个 175")):
            d = g[name]
            print(f"    {label}")
            print(f"      变了 {len(d['changed'])} 条 / {EXPECT_TOTAL}；"
                  f"多进 {d['add']} 少掉 {d['drop']}；落在：{d['libs']}")
        print("    （175 条逐条读完 → **P86 ① 判「大库不接」**：`size` 那一档大库 25 条"
              " 变好 8 / 中性 7 / 变差 10（净亏，跟小库 14:7 形状相反）；"
              "`both` 那一档大库 134 条 变好 14 / 中性 27 / **变差 93**。"
              "理由在 `kb/topic_face` 文件头第 ④ 格）")
        for name, got, want in (
                ("size 变了", len(g["size"]["changed"]), EXPECT_CF_BIG_SIZE_CHANGED),
                ("size 多进", g["size"]["add"], EXPECT_CF_BIG_SIZE_ADD),
                ("size 少掉", g["size"]["drop"], EXPECT_CF_BIG_SIZE_DROP),
                ("size 落在哪几个库", g["size"]["libs"], EXPECT_CF_BIG_SIZE_LIBS),
                ("both 变了", len(g["both"]["changed"]), EXPECT_CF_BIG_BOTH_CHANGED),
                ("both 多进", g["both"]["add"], EXPECT_CF_BIG_BOTH_ADD),
                ("both 少掉", g["both"]["drop"], EXPECT_CF_BIG_BOTH_DROP),
                ("both 落在哪几个库", g["both"]["libs"], EXPECT_CF_BIG_BOTH_LIBS)):
            if got != want:
                bad.append(f"cf-bigcorpus {name}: {got} ≠ {want}")
    if "--cf-gates" in argv:
        g = cf_gates(qs)
        if g["selfcheck_mismatch"]:
            bad.append(f"cf-gates 接线自检: 复刻的 HEAD 跟产品那一份差了 "
                       f"{g['selfcheck_mismatch']} 条 —— **下面的数全部作废**")
        print("  那两道闸今天各自还挡着什么（P90）—— 左边一律是今天的 HEAD：")
        print(f"    拆库大小闸 · 主语面照问：变了 {len(g['size']['changed'])} 条 / {EXPECT_TOTAL}"
              "  ⚠️ **0 = 今天这两道闸在这份语料上是冗余的**"
              "（大库的 `who` 93.8% 是说话人标签 → 主语面回 `None` → 判「是 common」）")
        print(f"    再摘掉 `SPEAKER_TAG_MAX`：变了 {len(g['tag']['changed'])} 条，"
              f"落在 {g['tag']['libs']}；**i=607 {g['tag']['i607'][0]} → {g['tag']['i607'][1]} 条**"
              "  ⚠️ **所以大库上的安全来自「那个库的 `who` 恰好不是主语」，不是来自这条轴判得准**")
        print(f"    拆汉字闸 · 别的不动：变了 {len(g['en']['changed'])} 条 {g['en']['changed']}，"
              f"多进 {g['en']['add']} 少掉 {g['en']['drop']}，有→空 {g['en']['empty']}，"
              f"落在 {g['en']['libs']}")
        print("    （6 条逐条读完：**变好 0 / 中性 2 / 变差 4** → P90 判「拆汉字闸不通」。"
              "卡在两格：门槛（`ai` 主语面 .819 < 0.85，被当成「不泛」放进来）"
              "和轴（主语面在英文串上没有信号，`p90-holdout-en-60` 量过）。"
              "理由在 `kb/topic_face` 文件头第 ⑧ 格）")
        print(f"    英文改走 `topics`@{EXPECT_CF_GATES_EN060_TH}（P90 ① 留的那条路，P92 ① 走完）："
              f"变了 {len(g['en060']['changed'])} 条 {g['en060']['changed']}，"
              f"多进 {g['en060']['add']} 少掉 {g['en060']['drop']}，"
              f"有→空 {g['en060']['empty']}，落在 {g['en060']['libs']}")
        print(f"      真正多放行的串只有 {g['en060']['terms']} —— "
              "**两个人标都对**（`p92-holdout-en-137` 里 `agent`/`memory` 都标「不泛」），"
              "而 11 条逐条读完 **变好 0 / 中性 2 / 变差 9**。")
        print("      ⇒ **卡的不是门槛也不是轴，是第三格**：「不泛」≠「值得当证据」。"
              "这两个串命中的是同一句产品定位话的六种说法，一进就是半屏，"
              "把逐句沾边的事实挤出去。全文在 `kb/topic_face` 文件头第 ⑪ 格")
        for name, got, want in (
                ("size 变了", len(g["size"]["changed"]), EXPECT_CF_GATES_SIZE_CHANGED),
                ("tag 变了", len(g["tag"]["changed"]), EXPECT_CF_GATES_TAG_CHANGED),
                ("tag 落在哪几个库", g["tag"]["libs"], EXPECT_CF_GATES_TAG_LIBS),
                ("tag i=607", g["tag"]["i607"], EXPECT_CF_GATES_TAG_607),
                ("en 变了", len(g["en"]["changed"]), EXPECT_CF_GATES_EN_CHANGED),
                ("en 多进", g["en"]["add"], EXPECT_CF_GATES_EN_ADD),
                ("en 少掉", g["en"]["drop"], EXPECT_CF_GATES_EN_DROP),
                ("en 有→空", g["en"]["empty"], EXPECT_CF_GATES_EN_EMPTY),
                ("en 落在哪几个库", g["en"]["libs"], EXPECT_CF_GATES_EN_LIBS),
                ("en 是哪几条", g["en"]["changed"], EXPECT_CF_GATES_EN_IDX),
                ("en060 变了", len(g["en060"]["changed"]), EXPECT_CF_GATES_EN060_CHANGED),
                ("en060 多进", g["en060"]["add"], EXPECT_CF_GATES_EN060_ADD),
                ("en060 少掉", g["en060"]["drop"], EXPECT_CF_GATES_EN060_DROP),
                ("en060 有→空", g["en060"]["empty"], EXPECT_CF_GATES_EN060_EMPTY),
                ("en060 落在哪几个库", g["en060"]["libs"], EXPECT_CF_GATES_EN060_LIBS),
                ("en060 是哪几条", g["en060"]["changed"], EXPECT_CF_GATES_EN060_IDX),
                ("en060 放行了哪几个串", g["en060"]["terms"], EXPECT_CF_GATES_EN060_TERMS)):
            if got != want:
                bad.append(f"cf-gates {name}: {got} ≠ {want}")
        if 607 not in g["tag"]["changed"]:
            bad.append("cf-gates: i=607 不在摘闸后变了的那批里 —— "
                       "**P90 ① 那条链的落点变了**，整节重读")
    if "--cf-shape" in argv:
        g = cf_shape(qs)
        print(f"  **这几条事实彼此有没有区别**（P94，尺在 `kb/fact_distinct`，**没接进产品**）："
              f"量得了 ≥3 格的屏 {g['total']} / {EXPECT_TOTAL}"
              f"（一个字都说不出来的 {g['blind']} 屏 = {g['blind'] / EXPECT_TOTAL * 100:.1f}%）")
        print(f"    判「半屏是同一句话的多种说法」：HEAD **{len(g['head'])}** 屏 → "
              f"en060 **{len(g['en060'])}** 屏；翻成「是」的 {g['flip_on']}、反向 {g['flip_off']}")
        print(f"    HEAD 那 {len(g['head'])} 屏是：{g['head']}")
        print(f"    按库（库, 判「是」, 量得了>=3）：{g['libs']}")
        print(f"    ⚠️ **逐条读完按库分**：大库 `terrence` 真 {EXPECT_SHAPE_READ_BIGLIB[0]} / "
              f"假 {EXPECT_SHAPE_READ_BIGLIB[1]}（假阳性 16.7%，而 83.8% 的查询落在大库）；"
              f"两个小库真 {EXPECT_SHAPE_READ_SMALLLIB[0]} / 假 {EXPECT_SHAPE_READ_SMALLLIB[1]}"
              f"；**没治好的那一屏是 i={EXPECT_SHAPE_LEFTOVER[0]}（`手环`）**"
              " → 判仍然是「不接」，理由在 `kb/fact_distinct` 第 ⑤⑦ 格")
        print(f"    **半屏那道门自己拦下来的**：{g['half']}（{len(g['half'])} 屏），"
              f"逐条读完 该放 {EXPECT_SHAPE_HALF_READ[0]} / 该拦 {EXPECT_SHAPE_HALF_READ[1]}"
              f" —— **P96 那一版是 {len(EXPECT_SHAPE_HALF_P96)} 屏 "
              f"（该放 {EXPECT_SHAPE_HALF_READ_P96[0]} / 该拦 {EXPECT_SHAPE_HALF_READ_P96[1]}）**；"
              f"**P98 换的是判据不是摘门**，老那 7 屏的「这一族的话题码盖住几格」= {g['cover7']}")
        print(f"    ⚠️ **摘光那道门**是 {len(g['nohalf'])} 屏"
              f"（真 {EXPECT_SHAPE_NOHALF[1]} / 假 {EXPECT_SHAPE_NOHALF[2]}），"
              f"**大库那一对会变成 {EXPECT_SHAPE_NOHALF_BIGLIB}（假阳性 16.7% → 28.6%）**"
              " —— **判「不摘」**，理由在 `kb/fact_distinct` 第 ⑧-b 格")
        print(f"    **那 {g['blind']} 屏「瞎掉」拆开是**：空屏 {g['blind_why'][0]} / "
              f"有事实但无 topics {g['blind_why'][1]} / **真能归到没有 obj 头上的 "
              f"{g['blind_why'][2]} 屏**（= {g['blind_why'][2] / g['blind'] * 100:.1f}% of 瞎掉）"
              " ⚠️ P94 ⑤-2 把这 441 屏整笔归给 obj，**那是两笔账混成一笔**")
        for name, got, want in (("量得了>=3 的屏", g["total"], EXPECT_SHAPE_TOTAL),
                                ("瞎掉的屏", g["blind"], EXPECT_SHAPE_BLIND),
                                ("瞎掉为什么", g["blind_why"], EXPECT_SHAPE_BLIND_WHY),
                                ("HEAD 判是", len(g["head"]), EXPECT_SHAPE_HEAD),
                                ("en060 判是", len(g["en060"]), EXPECT_SHAPE_EN060),
                                ("翻成是", g["flip_on"], EXPECT_SHAPE_FLIP_ON),
                                ("反向翻", g["flip_off"], EXPECT_SHAPE_FLIP_OFF),
                                ("半屏拦下", g["half"], EXPECT_SHAPE_HALF),
                                ("摘光那道门", len(g["nohalf"]), EXPECT_SHAPE_NOHALF[0]),
                                ("老那 7 屏各自盖住几格", g["cover7"], EXPECT_SHAPE_COVER7),
                                ("按库", g["libs"], EXPECT_SHAPE_LIBS)):
            if got != want:
                bad.append(f"cf-shape {name}: {got} ≠ {want}")
        if sum(g["blind_why"]) + g["total"] < 0 or sum(g["blind_why"]) != g["blind"]:
            bad.append(f"cf-shape 瞎掉拆账对不上：{sum(g['blind_why'])} ≠ {g['blind']} —— 这一支的数作废")
        if set(g["head"]) & set(g["half"]):
            bad.append("cf-shape: 判「是」和「被半屏拦下」出现同一屏 —— 两档互斥，这一支的数作废")
        # ⚠️ **换门那一刀的自检**（P98）：「换判据」和「摘门」是两回事，
        # 两档得严格套着 —— 判「是」⊊ 摘光，而且两档加起来正好是摘光那一档。
        if not set(g["head"]) < set(g["nohalf"]):
            bad.append("cf-shape: 判「是」不是「摘光那道门」的真子集 —— 那这道门就没在拦东西了，数作废")
        if set(g["head"]) | set(g["half"]) != set(g["nohalf"]):
            bad.append("cf-shape: 判「是」+ 被门拦下 ≠ 摘光那一档 —— 三档对不上，这一支的数作废")
        # **老那 7 屏今天还在不在摘光那一档里**（换门不许把它们从分母里弄丢）
        if not set(EXPECT_SHAPE_HALF_P96) <= set(g["nohalf"]):
            bad.append("cf-shape: P96 那 7 屏有的掉出「摘光」那一档了 —— "
                       "**换门不该动团，先去查 `same_thing` 或语料**，数作废")
        if set(g["flip_on"]) - set(EXPECT_CF_GATES_EN060_IDX):
            bad.append("cf-shape: 翻成「是」的屏里有不在 en060 变了的那 11 条里的 —— "
                       "**这一刀没落在被测分支里**，数作废")
    if "--cf-hold" in argv:
        g = cf_hold(qs)
        print(f"  **屏级判据的留出集**（P100，收 P98 ④）：留出查询 {g['queries']} 条 "
              f"（空屏 {g['pool'][0]} / 防污染剔 {g['pool'][1]} / 池内重复剔 {g['pool'][2]} "
              f"/ 留 {g['pool'][3]}）")
        print(f"    判得了的留出屏分层：A 层（`K` 团>=3）{g['layers'][0]} 屏 · "
              f"B 层 {g['layers'][1]} 屏；上单子的是 {g['sheet']}，按库 {g['libs']}")
        print(f"    ⚠️ **A 层那 {g['sheet'][0]} 屏背后只有 {g['fams']} 个互不相同的团**"
              " —— 屏是虚分母，**证据的单位是团**，这就是这份留出集分辨率的上限")
        print(f"    人标（分母 = 量得了的格）：判「是这形状」{g['read'][0]} 屏 / "
              f"「不是」{g['read'][1]} 屏 / 拿不准 {g['read'][2]} 屏")
        print(f"    **A 层上三条判据**（判是 / 真 / 假）：`K`+门 {g['a_k']} · "
              f"`M`+门 {g['a_m']} · 字面 3-gram 各档 {g['a_gram']}")
        print("    ⇒ **P98 那条路判「不接」，理由是效果不够、不是别的**："
              "in-sample 那 18 屏上真 12/12、假 1/6，"
              "换到 5 个没见过的团上 **真 0 / 假 3–5**；"
              "而它过滤的那个底（`K`+门）在留出集上 **判是 6、一屏真的都没有**。"
              "⚠️ 门槛是 P98 定死的 0.07–0.10，**一格都没按留出集调**")
        print(f"    ⚠️ **`M` 那个 0 假阳性是空的**：它在这份留出集上一次都没开口（分母 0）。"
              f"真正量到的是漏那一头 —— {g['miss']} 那一屏人读判「是」，"
              "四条「用 hello@memocat.ai 当对外联系邮箱」，`K` 团只打到 2："
              "漏掉的两条**被抽成了另一个码，而且两条轴同时**"
              "（`e_mail` ↔ `e_mail_address`、`work` ↔ `work_marketing`）"
              " —— 三条路一条都没捡到，去读 `kb/fact_distinct` 第 ⑨-c 格")
        for name, got, want in (("留出查询条数", g["queries"], EXPECT_HOLD_QUERIES),
                                ("池子拆账", g["pool"], EXPECT_HOLD_POOL),
                                ("分层", g["layers"], EXPECT_HOLD_LAYERS),
                                ("上单子的", g["sheet"], EXPECT_HOLD_SHEET),
                                ("按库", g["libs"], EXPECT_HOLD_LIBS),
                                ("独立的团", g["fams"], EXPECT_HOLD_FAMS),
                                ("人标", g["read"], EXPECT_HOLD_READ),
                                ("A 层 K", g["a_k"], EXPECT_HOLD_A_K),
                                ("A 层 M", g["a_m"], EXPECT_HOLD_A_M),
                                ("A 层 3gram", g["a_gram"], EXPECT_HOLD_A_GRAM),
                                ("三条都漏的", g["miss"], EXPECT_HOLD_MISS)):
            if got != want:
                bad.append(f"cf-hold {name}: {got} ≠ {want}")
        # **分层是分割**（每一屏只能落一层），而且上单子的不许多于分层的
        if g["sheet"][0] > g["layers"][0] or g["sheet"][1] > g["layers"][1]:
            bad.append("cf-hold: 上单子的比分层的还多 —— 抽样飘了，这一支的数作废")
        if sum(g["read"]) != sum(g["sheet"]):
            bad.append(f"cf-hold: 人标 {sum(g['read'])} 条 ≠ 单子 {sum(g['sheet'])} 屏 —— 数作废")
        if sum(n for _u, n in g["libs"]) != sum(g["sheet"]):
            bad.append("cf-hold: 按库那一行加起来 ≠ 单子屏数 —— 数作废")
        # **字面那条路必须严格窄于它过滤的那个底**（它只会把「判是」翻成「判不是」）
        for cut, n, _t, _f in g["a_gram"]:
            if n > g["a_k"][0]:
                bad.append(f"cf-hold: cut={cut/100} 判是 {n} 屏 > `K`+门 的 {g['a_k'][0]} 屏 —— "
                           "它是套在 `K` 上的过滤器，只该更窄，数作废")
    if "--fam2" in argv:
        g = cf_fam2(qs)
        print(f"  **`FAMILY_MIN` 该不该是 2**（P104，收 P102 ①）：团 == 2 的屏 "
              f"`K` {g['pop'][0]} 屏 · `M`（HEAD 判据）{g['pop'][1]} 屏 · 交 {g['pop'][2]} · "
              f"并 {g['pop'][3]} 屏（**全普查，没抽样**）")
        print(f"    ⚠️ **台账上那个 99 是 `K` 的数**（P94 那会儿判据是 `K`）；"
              f"HEAD 今天跑的是 `M`，同一格只有 {g['pop'][1]} 屏。按库：`K` {g['libs_k']}；`M` {g['libs_m']}")
        print(f"    机器挑的那一对人读判真：`K` {g['pair_k'][1]}/{g['pair_k'][0]} "
              f"= {g['pair_k'][1] / g['pair_k'][0] * 100:.1f}%（按库 {g['pair_k_libs']}）；"
              f"`M` {g['pair_m'][1]}/{g['pair_m'][0]} = {g['pair_m'][1] / g['pair_m'][0] * 100:.1f}%"
              f"（按库 {g['pair_m_libs']}）")
        print(f"    ⚠️ **大库那一档单独看**：`terrence` 上 `K` 只有 "
              f"{dict((u, (n, m)) for u, n, m in g['pair_k_libs'])['terrence']} —— "
              "小库读数不等于全库读数")
        print(f"    屏级：`FAMILY_MIN` 3 → 2，判「是」{g['flag'][0]} → {g['flag'][1]} 屏；"
              f"**新增 {g['new'][0]} 屏，人读判真 {g['new'][1]} 屏**（按库 {g['new_libs']}）")
        print(f"      新增是哪几屏：{g['new_idx']}；"
              f"靠 `cover×2≥n` 进来的 {g['new_why'][0]} 屏 / 靠 `团×2≥n` 的 {g['new_why'][1]} 屏")
        print(f"    这 {g['pop'][3]} 屏里人读判「该判是」的只有 {g['true'][0]} 屏 "
              f"（{g['true_idx']}），**一屏都不在新增那 {g['new'][0]} 屏里**")
        print(f"    **P102 那两屏（i=694/696）**：量得了 {g['s694'][0]} 格、人读的族 {g['s694'][1]} 格、"
              f"`M` 团 {g['s694'][2]}、盖住 {g['s694'][3]} ⇒ **差的不是 1**："
              "就算合码把团顶到 2，`2×2 < 8`、`盖住 2×2 < 8`，**半屏那道门照样不放行**；"
              "缺的是**召回不到那另外 3 格**（两条轴同时被劈开），不是门槛高")
        h = g["hold"]
        print(f"    **留出集那一面**（P100 那 {h['screens']} 屏，只会多判是的改动 ⇒ 要的正是假阳性）："
              f"`K`+门 {h['k'][0]} → {h['k'][1]}（新增 {h['new_k']}，**都是假的**）；"
              f"`M`+门 {h['m'][0]} → {h['m'][1]}")
        print(f"      ⚠️ **`M` 那两个 0 是空的**：留出集上 `M` 团 == 2 的有 {h['m2']} 屏，"
              "**放到 2 一屏都没进门**（半屏那道门先挡着）—— 分母 0，不许读成「放宽了也没事」")
        print("    ⇒ **判「不动」**：旋钮拧到 2，买来的 20 屏一屏真的都没有，"
              "而真的那 5 屏一屏都没捡到 —— 且这 111 屏是 in-sample，**别拿它当验收尺**")
        for name, got, want in (("population", g["pop"], EXPECT_FAM2_POP),
                                ("K 按库", g["libs_k"], EXPECT_FAM2_LIBS_K),
                                ("M 按库", g["libs_m"], EXPECT_FAM2_LIBS_M),
                                ("K 那一对真不真", g["pair_k"], EXPECT_FAM2_PAIR_K),
                                ("K 那一对按库", g["pair_k_libs"], EXPECT_FAM2_PAIR_K_LIBS),
                                ("M 那一对真不真", g["pair_m"], EXPECT_FAM2_PAIR_M),
                                ("M 那一对按库", g["pair_m_libs"], EXPECT_FAM2_PAIR_M_LIBS),
                                ("3→2 判是", g["flag"], EXPECT_FAM2_FLAG),
                                ("新增", g["new"], EXPECT_FAM2_NEW),
                                ("新增按库", g["new_libs"], EXPECT_FAM2_NEW_LIBS),
                                ("新增是哪几屏", g["new_idx"], EXPECT_FAM2_NEW_IDX),
                                ("新增靠哪一半", g["new_why"], EXPECT_FAM2_NEW_WHY),
                                ("人读判真的", g["true"], EXPECT_FAM2_TRUE),
                                ("人读判真的是哪几屏", g["true_idx"], EXPECT_FAM2_TRUE_IDX),
                                ("i=694 解剖", g["s694"], EXPECT_FAM2_S),
                                ("留出集 K", h["k"], EXPECT_FAM2_HOLD_K),
                                ("留出集 M", h["m"], EXPECT_FAM2_HOLD_M),
                                ("留出集新增", h["new_k"], EXPECT_FAM2_HOLD_NEW),
                                ("留出集 M 团==2", h["m2"], EXPECT_FAM2_HOLD_M2)):
            if got != want:
                bad.append(f"fam2 {name}: {got} ≠ {want}")
        # **新增那一档必须是「只多不少」**：放宽门槛一屏都不许掉
        if not set(g["new_idx"]) or len(g["new_idx"]) != g["flag"][1] - g["flag"][0]:
            bad.append("fam2: 3→2 新增的屏数跟两档差对不上 —— 有屏掉了？这一支的数作废")
        if set(EXPECT_FAM2_TRUE_IDX) & set(g["new_idx"]):
            bad.append("fam2: 人读判真的屏里有落在「新增」那一档的 —— "
                       "那判就得重读（今天这一格是 0），数作废")
    if "--fuse" in argv:
        g = cf_fuse(qs)
        c = g["census"]
        print(f"  **一屏之内跨码拼族 + 这条线的结案账**（P106）：量得了≥3 的 {c[0]} 屏里有人读的 {c[1]} 屏"
              f"（这一批补读 `K团≤1 ∧ M团≤1` 那 {g['unread'][0]} 屏：人读出族 {g['unread'][1]}、该判是 {g['unread'][2]}）")
        print(f"    **用户眼前**：人读「半屏同一句话」{c[2]} 屏；尺子判是 {c[3]}（真 {c[4]}）、漏 {c[5]} {g['miss']}"
              f"；⚠️ 尺子没接进产品 ⇒ **这 {c[2]} 屏今天在用户眼前一屏都没变过**")
        print(f"    `user` 血缘：{g['user'][0]} 屏 · **空屏 {g['user'][1]}** · 半屏同一句话 {g['user'][2]}"
              f"；两批判得不一样的：{g['disagree']}")
        print(f"    两轴同劈：团≤2 那档人读族≥3 且≥半屏 {g['twoaxis'][0]} 屏，两轴同劈 {g['twoaxis'][1]}，"
              f"P102 那把尺字面口径够得着的劈开成员 {g['twoaxis'][2]}；团≤1 那档两格族 {g['pairs']}")
        print(f"    拼族两条（判是, 新增, 新增里是已读反例, 新增里真, 正例修好, 两格族拼上）："
              f"C1 实体桥 {g['c1']} · C12 分布互近邻 {g['c12']}（新增 {g['c12_new']}）；反例池 {g['neg']} 屏")
        print("    ⇒ **C1 先喂反例就死（新增 14 里 5 屏是读过的假）；C12 两轴同劈那 4 屏一屏没修好、8 对一对没拼上，"
              "新增 2 屏真 1 假 1 —— 判「不接」；这条线结案，理由在 `docs/product-readiness-plan.md` §4**")
        for name, got, want in (("补读那一档", g["unread"], EXPECT_P106_UNREAD),
                                ("补读按库", g["unread_libs"], EXPECT_P106_UNREAD_LIBS),
                                ("两轴同劈", g["twoaxis"], EXPECT_P106_TWOAXIS),
                                ("两格族", g["pairs"], EXPECT_P106_TWOAXIS_PAIRS),
                                ("普查", g["census"], EXPECT_P106_CENSUS),
                                ("漏", g["miss"], EXPECT_P106_MISS),
                                ("user 血缘", g["user"], EXPECT_P106_USER),
                                ("两批判得不一样", g["disagree"], EXPECT_P106_DISAGREE),
                                ("C1", g["c1"], EXPECT_FUSE_C1),
                                ("C12", g["c12"], EXPECT_FUSE_C12),
                                ("C12 新增", g["c12_new"], EXPECT_FUSE_C12_NEW),
                                ("反例池", g["neg"], EXPECT_FUSE_NEG)):
            if got != want:
                bad.append(f"fuse {name}: {got} ≠ {want}")
    if "--window" in argv:
        bad += check_paragraph_at_source()
        g = window_gap()
        idx = {(u, q): i for i, (u, q, _m, _o) in enumerate(qs)}
        print(f"  离线 {g['offline']} 条 · 产品那一头 {g['product']} 条"
              f"（离线覆盖 {(g['offline'] - len(g['only_offline'])) / g['product'] * 100:.1f}%）")
        print(f"  **离线有、产品产不出来的：{len(g['only_offline'])} 条**"
              f"（该打折扣的就这几条）")
        for u, q in g["only_offline"]:
            print(f"    i={idx.get((u, q))} user={u} {q[:120]!r}")
        print(f"  产品有、离线没有的：{len(g['only_product'])} 条（离线**少覆盖**的那一档）")
        for u, q in g["only_product"][:6]:
            print(f"    user={u} len={len(q)} {q[:90]!r}")
        for name, got, want in (("产品条数", g["product"], EXPECT_PROD_TOTAL),
                                ("只在离线", len(g["only_offline"]), EXPECT_ONLY_OFFLINE),
                                ("只在产品", len(g["only_product"]), EXPECT_ONLY_PRODUCT)):
            if got != want:
                bad.append(f"{name}: {got} ≠ {want}")
    if bad:
        print("尺子对不上钉死的量程：" + "；".join(bad), file=sys.stderr)
        print("**这一刻台账上所有拿它当分母的数都失效了**——先查口径 / 语料，别换尺子继续量。",
              file=sys.stderr)
        return 9
    print(f"ruler OK = {EXPECT_TOTAL} 条那把尺（P38–P61 逐格相同）"
          + ("；窗口口径 OK（P79 ③ 逐格相同）" if "--window" in argv else "")
          + ("；`common` 反事实 OK（P82 ① 逐格相同）" if "--cf-common" in argv else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
