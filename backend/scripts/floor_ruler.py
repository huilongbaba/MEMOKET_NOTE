"""**那把看着「下限自己被调低」的尺**（P80 B）。仓库里在这之前一把都没有。

    .venv/bin/python scripts/floor_ruler.py            # 对不上 exit 9
    .venv/bin/python scripts/floor_ruler.py --list     # 顺带把登记表逐条打出来

它**不读语料、不起进程**：只把几份闸门 / 尺子的源码解出来，跟一张登记表对。
所以 `KITE_DATA_DIR` 给不给都一样。

---

## 为什么要造它：`MIN_*` / `>= N` 挡得住「东西被砍」，挡不住「下限自己被调低」

两次实拍，两批各一次：

* **P78 第 ⑦ 刀**：`check-walkthrough-fakeshell.mts` 的 `MIN_STEPS` **8 → 3**，
  闸**没红**。那一行的注释里逐字写着「别把这个数字改小」——注释不是闸。
* **P79 第 ⑨ 刀**：`test_p79` 第四条c 第一版写的是 `sum(变差) >= 1`，
  把 i=79 那条标注从「变差」改成「变好」，剩 7 条仍然 ≥1，**闸不红**；
  改成钉死 `{变好 11 / 变差 8 / 中性 6}` 之后才红。

两次是**同一个形状**：一条 `X >= N` 的断言，`N` 自己也在仓库里、也改得动，
而**没有任何东西在看着 `N`**。

## 判据：**两档，分开判，理由各自写在登记表里**

| 档 | 判法 | 什么该进这一档 |
|---|---|---|
| `floor` | 源码里的值 **≥** 登记的基线（**往上调是绿的**） | 「扫不到东西的闸门会一直是绿的」那一类下限：步数、类名数、发身份的量具份数。它们**本来就该随代码涨**，钉死等于每加一份量具就红一次——那样的闸会被人改成不红，洞就又回来了 |
| `pinned` | 源码里的值 **==** 登记的值 | **实测结论**：各把尺钉死的量程（`EXPECT_*`）、以及**抄产品的那几个数**（`SHOW` = `KbDashboard` 的 `slice(0, 6)`、`MIN_CHARS` = `marginParagraphs` 的 `length >= 8`）。这些一动，靠它们得出的那条结论就得重读——**该红** |

**为什么不是「改了就红」挪个地方**（P76 在截图前缀那笔账上判过这个）：

1. `floor` 那一档**往上调是绿的**。真正的合法方向不受阻，被阻的只有「调低」这一个方向。
2. `pinned` 那一档红出来的话说的不是「你改了」，是**「这条结论现在得重读，去读 X」**
   ——每一条登记都带着那句话（`why`），红的时候原样打出来。
3. **登记表自己有完整性闸**：被看着的那几份文件里，凡是名字落在 `WATCHED_NAME` 上的
   模块级常数**必须登记**。加一个新的下限而不登记 = 当场红。
   这一条才是「洞挪个地方」真正的出口，它被堵在这儿。

## 它答不了什么（照 P72 的规矩，写在闸自己身上）

* **改了登记表本身**：把基线跟着调低，两处一起改，这把尺当然绿。
  它能做到的是让这件事**在 diff 里是一行数据**，而不是藏在一句「顺手把 8 改成 3」里。
  最后一只乌龟是人读 diff——但读的是一行写着「这个数只准往上」的数据行。
* **这个下限该不该是这个数**：一条都答不了。它只管「谁在动它、往哪个方向动」。
* **`npm test` 那条链**：这把尺跑在 `pytest` 上。前端单跑 `npm test` 看不见它
  （这个仓每批两条链都跑，所以够用；换个工作流要另外接一条）。
* **非模块级的常数**：函数体里 `min_steps = 3` 这种它扫不到（`ast` 只走 `tree.body`）。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent

# ── 看着哪几份 ────────────────────────────────────────────────────────────
# 挑的是**闸门和尺子**，不是产品源码：产品里的常数（`RECALL_LIMIT` / `IDLE_MS`…）
# 本来就该随产品改，把它们圈进来只会让这把尺天天误报，而**天天误报的闸等于没有闸**。
WATCHED: tuple[str, ...] = (
    "backend/scripts/en_gate_ruler.py",
    "backend/scripts/kb_search_ruler.py",
    "backend/scripts/recall_ruler.py",
    "backend/scripts/card_origin_ruler.py",
    "backend/scripts/margin_dot_ruler.py",
    "backend/scripts/topic_spread_ruler.py",
    "backend/scripts/journey_fixture.py",
    "frontend/scripts/check-walkthrough-fakeshell.mts",
    "frontend/scripts/check-walkthrough-selectors.mts",
    "frontend/scripts/check-components-gate.mts",
    "frontend/scripts/check-walkthrough-diff.mts",
)
# 哪些名字算「闸门常数」。**宁可窄**：只认这几个前缀，别的名字（`SEED` / `LIMIT` /
# `USER`…）不进登记表，也就不受这把尺管——它们不是「下限」也不是「实测结论」。
WATCHED_NAME = re.compile(r"^(MIN_[A-Z0-9_]*|MAX_[A-Z0-9_]*|EXPECT[A-Z0-9_]*|SHOW|SPREAD_[A-Z0-9_]*)$")

# ⚠️ 登记表自己有多大，也是一个「随代码涨」的数（第 810 轮合并时学到的）：
# P84 和 P85 各自在自己那条测试里把 `len(REGISTRY)` / `check()` 的共核数**钉死**了，
# 两批并行各加各的，合并后两条一起红——而两批都没做错任何事。
# **一条在每次正当改动上都会红的闸，迟早会被人不假思索地改成不红的那个数。**
# 所以这两个数按「只准往上」记在这儿，各批的测试去问它，别各自钉一份。
# 它挡得住的是「有人把登记删了」；挡不住「加了一条没登记」——那是 `check()` 的完整性闸的活。
REGISTRY_SIZE_FLOOR = 121  # 第 818 轮 P96 在自己 worktree 里实测（+7 条：拆账/半屏/泛 obj 那一组）；817 轮是 114、816 轮是 104、814 轮是 95、813 轮是 85
# ⚠️ 合并时记得抬到**合并后**那个数：两批各自在自己 worktree 里抬到 84 / 79，
# 合并后真值是 85——取任一边都会让「删掉一条登记」不红（这个数只准往上，抬是绿的）。
CHECKED_COUNT_FLOOR = 133  # 同上；共核 = 登记表 + 例反例；817 轮是 126、816 轮是 116、814 轮是 107、813 轮是 97、811 轮是 90


FLOOR = "floor"      # 只准往上调
PINNED = "pinned"    # 钉死，改了就红（红的意思是「这条结论得重读」）

# ── 登记表 ────────────────────────────────────────────────────────────────
# 一行一条：(文件, 名字) -> (档, 基线, **这个数一动要去重读什么**)
REGISTRY: dict[tuple[str, str], tuple[str, object, str]] = {
    # —— `floor`：三条「扫不到东西的闸门会一直是绿的」的下限 ——
    ("frontend/scripts/check-walkthrough-fakeshell.mts", "MIN_STEPS"): (
        FLOOR, 8, "假壳那条闸扒出来的步数。调低 = 把走查的步砍了还让闸绿着（P78 第 ⑦ 刀实拍）"),
    ("frontend/scripts/check-walkthrough-selectors.mts", "MIN_CLASSES"): (
        FLOOR, 30, "走查量具里选到的类名数。调低 = 量具被掏空了，选择器闸照样绿"),
    ("frontend/scripts/check-walkthrough-selectors.mts", "MIN_SENDERS"): (
        FLOOR, 17, "发 `X-User-Id` 的量具份数（P78 A ⑤）。调低 = 身份那条契约扫不到人了"),
    ("frontend/scripts/check-components-gate.mts", "MIN_COMPONENT_TESTS"): (
        FLOOR, 5, "**vitest 真要跑的** `src/components/` 底下的测试文件数（P85 A 开的那条路）。"
                  "调低 = 那条路被关掉了还让闸绿着——而「不跑」和「跑绿了」在终端里长得一模一样。"
                  "它一动去重读 P87 B / P91 A / P93 A 三节：**P85 开路时 1 份，P87 抬到 2 份，"
                  "P91 抬到 3 份**（`p91.test.tsx` 真 `createRoot` 挂 `RightPane`，"
                  "钉的是「`alwaysShown` 的页签**那一格**空了得说话」那条路）；"
                  "**P93 抬到 4 份**（`p93.test.tsx` 把它做成通用的：`alwaysShown` 的页签"
                  "**都**不许留白，名单从 `App.tsx` 现解、逐格真挂一次）；"
                  "**P95 抬到 5 份**（`p95.test.tsx`：P93 那条闸抓不到「那一格有字、"
                  "只不过字是别人的」——轮次卡按 note id 存那一刀的闸）"
                  "（70 个源文件今天 5 份，离「够」远得很），这个数**只准往上**"),
    ("frontend/scripts/check-walkthrough-diff.mts", "MIN_WHY"): (
        FLOOR, 4, "跨批 diff 归类表里「为什么」那一列至少几个字（P89 B）。"
                  "调低 = 一行写个 `-` 就算归过类了，那张表就退回成一张打勾表，"
                  "而这条闸的全部价值就在于**每一行都带着一句能读的理由**。"
                  "它一动去重读 P89 B 那一节 + `check-walkthrough-diff.mts` 的「它答不了什么」——"
                  "这把尺管不了「归得对不对」，它唯一管得住的就是「有没有人写下为什么」。"
                  "这个数**只准往上**（写得更长不是坏事）"),

    # —— `pinned`：P85 A 那条新闸抄产品的两个数 ——
    ("frontend/scripts/check-components-gate.mts", "EXPECT_LABEL_HITS"): (
        PINNED, 1, "`KbDashboard.tsx` 代码行里 `' · 命中词：'` / `' · 找过：'` **各**出现几次。"
                   "这两个标签是 P81 ③ 落的那一刀（0 条结果时那几个词是「找过的」不是「命中的」）。"
                   "一动去重读 P81 ③ 和 P82 ③ 两节：那一行是不是被抄了第二份、或者哪一支被删了"),
    ("frontend/scripts/check-components-gate.mts", "SHOW"): (
        PINNED, 6, "**产品这一侧**的 `hits.terms.slice(0, 6)`——跟 `kb_search_ruler.SHOW` 是同一个 6，"
                   "但那一份是尺子抄的、这一份钉的是源码本身。P79 第 ⑤ 刀实拍过「6 → 3 那把尺自己量不到」，"
                   "P85 A 补上的正是这一头。一动 = 摆几串换了，`kb_search_ruler` 那 108 / 0 两个数一起重读"),

    # —— `pinned`：抄产品的那几个数。一动 = 尺子跟产品飘开了 ——
    ("backend/scripts/kb_search_ruler.py", "SHOW"): (
        PINNED, 6, "抄的是 `KbDashboard.tsx` 那一行 `hits.terms.slice(0, 6)`。"
                   "P79 第 ⑤ 刀实拍：把它 6 → 3，**那把尺自己量不到**，只有一条源码对拍红"),
    ("backend/scripts/margin_dot_ruler.py", "MIN_CHARS"): (
        PINNED, 8, "抄的是 `marginParagraphs` 的 `p.text.length >= 8`。一动，圆点那三个数换了口径"),
    ("backend/scripts/card_origin_ruler.py", "SHOW"): (
        PINNED, 5, "抄的是 `RelatedMemory.LIST_MAX`（屏幕上最多摆几张记忆卡）。"
                   "一动，P83 A 那 964 / 133 换了分母，那条「混着 29」的判要重跑"),
    ("backend/scripts/card_origin_ruler.py", "MAX_ASKED"): (
        PINNED, 8, "抄的是 `RelatedMemory.RECALL_LIMIT`（`out[:8]`，P80 / P83 都明写「一个字不许动」）。"
                   "一动就不只是尺子飘了——先去看召回那一层是不是真的改了口径"),
    ("backend/scripts/topic_spread_ruler.py", "SPREAD_MIN_HITS"): (
        PINNED, 20, "泛尺「够不够得着判」的门槛。一动，P75 那张 116 种逐种的表要重读"),
    ("backend/scripts/topic_spread_ruler.py", "SPREAD_GENERIC"): (
        PINNED, 0.75, "泛尺判「泛」的门槛。P79 ① 正是靠它判 `ai` 0.74「不泛」——差 0.01。一动，那条判就得重读"),

    # —— `pinned`：各把尺钉死的量程。一动 = 那一批的结论全部失效 ——
    ("backend/scripts/recall_ruler.py", "EXPECT_TOTAL"): (
        PINNED, 765, "离线那把尺的量程。P61 起每批都在拿这个 765 对账"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CURSOR"): (
        PINNED, 727, "离线那把尺的 cursor 档。765 = 727 + 38，三个数得一起对"),
    ("backend/scripts/recall_ruler.py", "EXPECT_TAIL"): (
        PINNED, 38, "离线那把尺的 tail 档。765 = 727 + 38，三个数得一起对"),
    ("backend/scripts/recall_ruler.py", "EXPECT_USERS"): (
        PINNED, 6, "语料摆齐了没有的自报数（P79 开工那一跤：没拷语料量成 3093 / 10 skipped）"),
    ("backend/scripts/recall_ruler.py", "EXPECT_PROD_TOTAL"): (
        PINNED, 780, "产品那一头能产生的查询数（P79 ③）"),
    ("backend/scripts/recall_ruler.py", "EXPECT_ONLY_OFFLINE"): (
        PINNED, 1, "**P79 ③ 那条判的全部分量**：离线有、产品产不出来的只有 1 条 / 765。"
                   "这个 1 一动，「过去所有离线数要不要打折扣」就得重判"),
    ("backend/scripts/recall_ruler.py", "EXPECT_ONLY_PRODUCT"): (PINNED, 16, "产品有、离线没有的那 16 条（P79 ③ 的反方向）。跟 EXPECT_ONLY_OFFLINE 一起读才是那条判"),

    # —— `pinned`：记忆卡那把尺（P83 A）。**六个数一动，A 那一节整节失效** ——
    ("backend/scripts/card_origin_ruler.py", "EXPECT_CARDS"): (
        PINNED, 979, "727 条 cursor 查询摆出来的卡总数（上界口径，见那把尺的文件头）。"
                     "它是 133 / 62 / 29 / 33 四个数共同的分母——一动，四条判全部重读。"
                     "⚠️ P84 把它从 964 抬到 977：那条「泛词 vs 主题词」的轴在小库上多摆出 13 张卡，"
                     "而**那四个数一格没动**——所以 P83 A 那一节的四条判不用重读，重读的是分母那一句。"
                     "⚠️ P88 从 977 抬到 979：新串的**主语面**轴让 i=26 / i=293 各多摆出一张卡，"
                     "**那四个数照旧一格没动**"),
    ("backend/scripts/card_origin_ruler.py", "EXPECT_MARKED"): (
        PINNED, 133, "会被盖上「前一段带进来的」的卡数。**这一批「该不该改」的全部依据**："
                     "133/964 不是个可以忽略的零头。一动就去重读 `cardFromBefore` 那两条判据"),
    ("backend/scripts/card_origin_ruler.py", "EXPECT_QUERIES_WITH_MARK"): (
        PINNED, 62, "屏幕上至少有一张卡被盖的查询数（= 混着 29 + 整屏 33）。"
                    "它跟那两个数是加法关系，只有一条动过它必然也动——一起重读"),
    ("backend/scripts/card_origin_ruler.py", "EXPECT_MIXED"): (
        PINNED, 29, "**两种卡混着摆的查询数**——P80 留给这一批的那句「卡还是混着的」就是这 29 条。"
                    "一动，这一批改的那件事本身得重新判一次值不值"),
    ("backend/scripts/card_origin_ruler.py", "EXPECT_ALL_MARKED"): (
        PINNED, 33, "整屏 5 张全是前一段带回来的查询数。最坏的那一档："
                    "标签写着「按光标这段找的」而底下一张都不是。一动去重读那条判据的第 ① 条"),
    ("backend/scripts/card_origin_ruler.py", "EXPECT_WITH_CARDS"): (
        PINNED, 315, "727 条里真摆出了卡的条数（其余 412 条一张都没有）。"
                     "它是「盖戳率」唯一正确的分母——拿 727 去除是把那几百条空屏也算进去了。"
                     "⚠️ P84 从 312 抬到 314：两条原来整屏空的小库查询现在摆得出卡了。"
                     "⚠️ P88 从 314 抬到 315：i=293 那条原来整屏是空的，现在摆得出那一张逐句出处了"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_MISSING_HIT"): (
        PINNED, 1, "「库里没有」那一档真有 1 条（`羽毛球`）。调成 0 = 把那条不好看的实测抹了"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_TOTAL"): (PINNED, 110, "知识库搜索框那把尺的量程（P79 ② 的 110 条手打搜索词）。五档之和，一动全表重排"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_EMPTY"): (PINNED, 30, "110 条里搜出来 0 条结果的那一档（P79 ② A 那条判的分母）"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_EMPTY_WITH_LINE"): (
        PINNED, 9, "**P79 ② A 那条判的全部分量**：0 条结果还摆命中词 9/10"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_UNASKED"): (PINNED, 0, "摆了用户根本没打过的词的条数。这个 0 是「命中词那一行没在瞎编」的全部依据"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_GAP_MERGED_HEAD"): (
        PINNED, 3, "**旋钮在动的那个证据**（改之前 3 条）。调成 0 这把尺就量不到 P79 ④ 那一刀了"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_GAP_MERGED_NOW"): (PINNED, 0, "P79 ④ 那一刀改之后跨空白合出来的词。跟 HEAD 那 3 条一起才分得开「旋钮在动」和「产出对了」"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_TOKEN_MISS"): (PINNED, 0, "用户打了的词一个都没摆出来的条数。这个 0 一动，搜索框那一行的判据就得重读"),
    # P81 ② 把 P79 那个「20/20 全搜不到」拆成了形状表：库里有没有、哪个洞挡的、各几条。
    # 五个数一起才说得清「产品 placeholder 答应了『数字、日期』而它做不到」是怎么个做不到，
    # 任何一个动了，P81 ② 那张「不修」的判据表就得整张重读（三个旋钮的爆炸半径至今没量）。
    ("backend/scripts/kb_search_ruler.py", "EXPECT_NUMDATE_IN_CORPUS"): (
        PINNED, 20, "P81 ②：那 20 条串**库里真的有**（= 全部）。这个 20 掉下来就不是「搜不到」是「没有」，整条结论换方向"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_NUMDATE_NO_CHANNEL"): (
        PINNED, 9, "P81 ② 第一个洞：`_terms` 切得出、`plan` 没通道 → 0 条。P79 只定位到这一个"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_NUMDATE_NO_TOKEN"): (
        PINNED, 11, "P81 ② 第二个洞：`_NUM` 连词都切不出来。P79 漏了这一个，9 + 11 = 20 才是全账"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_NUMDATE_TWO_DIGIT"): (
        PINNED, 4, "第二个洞里的两位数裸数字那一族。跟下面那 7 条分开记，是因为两族要动的是不同的东西"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_NUMDATE_DATE_UNIT"): (
        PINNED, 7, "第二个洞里 `月`/`号`/`日`/`年` 那一族——**产品自己写的「日期」两个字，正是量词表里没有的那个形状**"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_NUMDATE_EMPTY"): (
        PINNED, 20, "P79 ② C：数字日期那一档 20/20 全 0 条（量到了没修，这个 20 是那条账的分量）"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_BLOCKED_OCC"): (PINNED, 583, "P77 那道英文 ≥3 的门挡掉的串次。"
                                                                         "⚠️ P84 抬了它（那条「泛词 vs 主题词」的轴在小库上多放了 63 个串进证人名单，这道门就多被问了几趟）；比率没变。568 → 583"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_BLOCKED_KINDS"): (PINNED, 14, "那道英文 ≥3 的门挡掉了多少**种**串。跟 583 串次一起读（P77 ①；P84 抬了串次，**种数一格没动**）"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_TOP_BLOCKED"): (
        PINNED, ("ai", 466), "**P79 ① 那条判的全部分量**：`ai` 被挡 466 串次。"
                              "⚠️ P84 抬了它（那条「泛词 vs 主题词」的轴在小库上多放了 63 个串进证人名单，这道门就多被问了几趟）；比率没变。451 → 466，而 466/583 = 79.9% ≈ P77 量的 79.4%——**形状没变**"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_FLIP_AT_2"): (PINNED, 11, "英文门放宽到 2（= 不设门）会翻盘的调用数。P77 「这道门该不该换轴」架在这上面"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_FLIP_QUERIES_AT_2"): (PINNED, 7, "放宽到 2 时会翻盘的查询条数（11 次调用落在 7 条查询上）"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_FLIP_AT_4"): (PINNED, 211, "英文门收紧到 4 会翻盘的调用数。跟放宽那一档的 11 是同一条判的两头（P84：213 → 211，条数 100 没动）"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_FLIP_QUERIES_AT_4"): (PINNED, 100, "收紧到 4 时会翻盘的查询条数（211 次调用落在 100 条查询上）"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_CF"): (
        PINNED, {2: (342, 1353, 2), 1: (342, 1353, 2), 4: (317, 1225, 67)},
        "三档门槛各自的全库对拍。P77 「这道门该不该换轴」那条判就架在这张表上"),
    # —— P82 ①：`common_term()` 那个旋钮的全库对拍 + 按库分的分母 ——
    # ⚠️ 这一组的「一动要重读什么」全部指向同一处：`kb/relations.COMMON_DF_MIN` 上面
    # 那段注释里 P82 判「换不了」的那几行，以及 `memory_sample.jsonl` 的 `p82-off333-49`。
    ("backend/scripts/recall_ruler.py", "EXPECT_BY_LIB"): (
        PINNED, {("fresh678", "fixture"): 6, ("fresh678b", "fixture"): 6,
                 ("fresh678c", "fixture"): 6, ("shot-demo", "fixture"): 20,
                 ("terrence", "script"): 92, ("terrence", "user"): 549,
                 ("terrence-rewrite", "script"): 86},
        "**按库分的分母**（P81 ① 那一课：`common_term()` 是按人建的，按血缘分会把 62.8% 平成 6.9%）。"
        "一动 = 语料换人了，所有「某个库上翻了百分之几」的数当场失效，49 条标注跟着重读"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_COMMON_CHANGED"): (
        PINNED, 49, "**P82 ① 那条判的分量**：把「小库不启用 `common`」真做出来，765 里变 49 条。"
                    "这 49 条逐条读完才得出「变好 16 / 变差 23 / 中性 10 → 退回」。一动就得重读那 49 条"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_COMMON_DROP"): (
        PINNED, 52, "那 49 条里掉了多少召回对。跟 ADD 的 140 一起读才分得清「捞回来的多了」和「捞对了」（P73 那一课）"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_COMMON_ADD"): (
        PINNED, 140, "那 49 条里进来多少召回对。净 +88 看着是好事，逐条读下来 23 条变差——**别拿聚合分当判据**"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_COMMON_HIT"): (
        PINNED, (341, 347), "有召回的查询数 HEAD → 反事实。341 是 P77 起每批都在对的那个数，"
                            "它一动说明的不是这个旋钮，是 765 那把尺本身"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_COMMON_LIBS"): (
        PINNED, (("terrence-rewrite", 49),),
        "**这个旋钮只够得着一个库**。一旦够得着第二个库，「按库分」那张表和 49 条标注的分母全部换人——"
        "也就是说 `COMMON_DF_MIN` / `COMMON_DF_RATIO` 或者某个库的大小变了"),

    # —— P84：那条「泛词 vs 主题词」的轴（`kb/topic_face`）接进 `common_term()` 之后的全库对拍 ——
    # ⚠️ 这一组的「一动要重读什么」全部指向同一处：`kite_memory.common_term()` 那段注释里
    # P84 判「接」的那几行、`kb/topic_face` 文件头那三格「够不着哪里」，
    # 以及 `memory_sample.jsonl` 的 `p84-spread-28`。
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_SPREAD_CHANGED"): (
        PINNED, 28, "**P84 那条判的分量**：拆掉这条轴，765 里变 28 条。"
                    "这 28 条逐条读完才得出「变好 14 / 变差 7 / 中性 7 → 接」。一动就得重读那 28 条"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_SPREAD_ADD"): (
        PINNED, 36, "HEAD 比「没有这条轴」多进来多少召回对。跟 DROP 的 16 一起读才分得清"
                    "「捞回来的多了」和「捞对了」（P73 那一课）——净 +20 不是判据，那 28 条读下来才是"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_SPREAD_DROP"): (
        PINNED, 16, "HEAD 比「没有这条轴」少掉多少召回对。**这 16 条里有 7 条判了变差**"
                    "（i=293 那条逐句出处就在里面）——它一动，「变好 14 / 变差 7」那一栏要重读"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_SPREAD_HIT"): (
        PINNED, (345, 341), "有召回的查询数 HEAD → 反事实。341 是 P77 起每批都在对的那个数，"
                            "**它现在在反事实那一头**；345 一动说明的不是这条轴，是 765 那把尺本身"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_SPREAD_LIBS"): (
        PINNED, (("terrence-rewrite", 28),),
        "**这条轴只够得着小库那一档**（`total * COMMON_DF_RATIO < COMMON_DF_MIN`）。"
        "一旦够得着 `terrence`，四栏就不再是「对这一刀是瞎的」而是真被动过了——"
        "197/195/96、192/190/92、166/137/33、46/36/4/6 四栏得整批重读"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_SPREAD_RESCUED"): (
        PINNED, 63, "这条轴真从 `common` 手里捞回来的串数（`terrence-rewrite` 上）。"
                    "一动说明语料、`SPREAD_GENERIC`(0.75) 或者「只问汉字」那一条变了，"
                    "28 条标注的分母跟着换人——先去读 `kb/topic_face` 文件头第 ① 格"),

    # —— P88 ①：那条主语面轴（2 条逐条读完，判**接**）——
    # 六个数答的是**一个**问题：「话题面之后再问一句主语面，代价是多少」。
    # 它跟上面 P84 那六个是**两个旋钮**，`--cf-spread` 的左边已经钉在「只有 topics 轴」
    # 那一版上，所以那六个数继续是 `p84-spread-28` 的分母，不受这一刀影响。
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_WHO_CHANGED"): (
        PINNED, 2, "只拆主语面那一档全库变了几条（i=26 · i=293）。它是 `p88-whoaxis-2` "
                   "那两条标注的来源，一动那两条（变好 1 / 中性 1）的分母就换人，"
                   "「接」这个判得整条重读——先去读 `kb/topic_face` 文件头第 ⑥⑦ 格"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_WHO_ADD"): (
        PINNED, 2, "HEAD 比「没有主语面」多出来的召回对。跟 DROP 一起读才看得出这一刀是"
                   "「换」还是「白送」"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_WHO_DROP"): (
        PINNED, 0, "**这个 0 是这一刀答应的那句话**：「只做减法、不挤掉任何人」。"
                   "它一旦不是 0，`kite_memory.common_term` 里 P88 ① 那段和两条标注**全部**重读"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_WHO_HIT"): (
        PINNED, (346, 345), "有召回的查询数 HEAD → 反事实。345 是 P84 那一版的数"
                            "（= `EXPECT_CF_SPREAD_HIT` 的左边），两边对不上就是两支接错层了"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_WHO_LIBS"): (
        PINNED, (("terrence-rewrite", 2),),
        "**这条轴够得着的库跟 P84 那条一样只有一个**。一旦够得着第二个库，"
        "四栏（197/195/96、192/190/92、166/137/33、46/36/4/6）就不再是「对这一刀是瞎的」，"
        "得整批重读"),
    # —— P90：那两道闸今天各自还挡着什么（**量完了，产品一个字节没改**）——
    # 六个数答的是**两个**问题：「库大小闸还是不是必需的」和「拆汉字闸通不通」。
    # ⚠️ 它们跟上面 P84 / P88 那两组**不是同一个旋钮**：那两组的左边分别钉在
    # 「没有这条轴」和「只有 topics 轴」上，而这一组的左边一律是**今天的 HEAD**。
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_SIZE_CHANGED"): (
        PINNED, 0, "拆掉库大小闸、主语面照问，全库变了几条。**这个 0 是「两道闸今天冗余」那句话本身**"
                   "——大库的 `who` 93.8% 是说话人标签，主语面在那儿回 `None`，"
                   "而 `None is not False` 为真 = 判「是 common」= 不捞回来。"
                   "它一旦不是 0，说明**主语面在大库上开始说话了**，"
                   "`kb/topic_face` 文件头第 ⑧ 格整节 + P88 ① 那条判都得重读。"
                   "⚠️ **别把它读成「那道闸可以拆」**——下面 TAG 那个 24 就是来堵这条误读的"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_TAG_CHANGED"): (
        PINNED, 24, "库大小闸拆着、**再把 `SPEAKER_TAG_MAX` 也摘掉**之后全库变了几条。"
                    "它跟上面那个 0 是一对：**0 说的是冗余，24 说的是那道闸真在挡东西**。"
                    "一动去重读第 ⑧ 格里那四个串的主语面分数"
                    "（`用户`.460 / `需要`.473 / `产品`.559 / `手机`.534）"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_TAG_607"): (
        PINNED, (1, 0), "i=607 的召回条数：HEAD → 摘闸后。**左边那个 1 是 P90 ① 更正 P88 的全部分量**"
                        "（P88 写「i=607 没治好」，而它在 HEAD 上是好的）；"
                        "右边那个 0 说明它跟 i=293 是同一条链。任一格动了，P90 ① 整节重读"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_EN_CHANGED"): (
        PINNED, 6, "拆掉汉字闸全库变了几条。它是 `p90-engate-6` 那 6 条标注的来源，"
                   "一动那 6 条（变好 0 / 中性 2 / 变差 4）的分母就换人，"
                   "「拆汉字闸不通」这个判得整条重读——先去读 `kb/topic_face` 文件头第 ⑩ 格"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_EN_DROP"): (
        PINNED, 5, "拆汉字闸之后被挤掉的召回对。跟 ADD(25) 一起读才看得出这一刀是「换」还是「白送」"
                   "——今天是 25 进 5 掉，而逐条读下来**掉的那 5 对里 4 对是真沾边的**"
                   "（i=318 / i=319 那两条）。一动去重读 `p90-engate-6`"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_TAG_LIBS"): (
        PINNED, (("terrence", 24),),
        "摘掉说话人标签那道闸之后，变了的那 24 条落在哪几个库上。"
        "**只有大库**是应该的（小库的 `who` 本来就不是说话人标签，摘不摘一个样）。"
        "一旦多出第二个库，说明有别的库的 `who` 也过了 `SPEAKER_TAG_MAX` 那道线，"
        "第 ⑧ 格里六个库那一行（0.0/0.0/0.0/14.3/93.8/11.9）得重数"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_EN_ADD"): (
        PINNED, 25, "拆汉字闸之后多进来的召回对。跟 DROP(5) 一起读："
                    "25:5 看着像「多召回一点」，而**逐条读下来是 0 好 2 中 4 差**"
                    "——多进来的绝大多数是 `ai` 撞词和英文定位套话。"
                    "**这一对数正是「别拿聚合分当判据」的现钱**，一动去重读 `p90-engate-6`"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_EN_LIBS"): (
        PINNED, (("terrence-rewrite", 6),),
        "拆汉字闸变了的那 6 条落在哪几个库上。**只有一个库**——因为它是唯一一个"
        "三道闸（df-common / 库大小 / 汉字）都过得到的小库。"
        "一旦够得着第二个库，`p90-engate-6` 那句「它答不了什么」得重写"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_EN_IDX"): (
        PINNED, (295, 296, 316, 318, 319, 320),
        "拆汉字闸变了的**是哪 6 条**。`p90-engate-6` 那 6 行标注就是按这六个下标写的，"
        "下标一动标注就对不上人了（查询是按 note id 排的，语料一变下标就挪）。"
        "⚠️ **它跟条数那个 6 是两件事**：条数对得上、下标对不上，"
        "说明换了一批查询而不是没变——那时候 6 条标注全部作废"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_EN_EMPTY"): (
        PINNED, 0, "拆汉字闸之后「有→空」的条数。**这个 0 是主语面确实缩小了伤口的那半证据**"
                   "（P84 那一版不限汉字是 22 条变 / 有→空 1，带上主语面是 6 条变 / 有→空 0）。"
                   "⚠️ **但它不是「所以可以拆」**：方向没变，还是 0 好 4 差。"
                   "它一动，第 ⑩ 格里「缩小了伤口但方向没变」那句话得重读"),

    # —— P92：**P90 ① 留的那条路走完了**（`topics` 轴 + 英文专用低门槛 0.60），判「不接」——
    # 这七个数 + `EXPECT_CF_GATES_EN060_TH` 是那个判的全部分量。⚠️ 它们跟上面 P90 那组 `EN_*` **不是同一个旋钮**：
    # `EN_*` 是「拆汉字闸、英文照走 topics@0.75 + who@0.85」，`EN060_*` 是
    # 「拆汉字闸、英文改走 topics@0.60、不问主语面」。**两支不能对着读**。
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_EN060_TH"): (
        PINNED, 0.60, "P90 ① 点名的那个「英文专用低门槛 ≈0.60」。"
                      "它不是随手挑的：`p92-holdout-en-137` 的 tainted 栏（= 产品那 9 个串）上"
                      "人标「不泛」.450–.663 / 「泛」.708–.880，**缝是 (.663, .708)**，0.60 落在缝里。"
                      "它一动，`p92-en060-11` 那 11 条的分母就换人——先去读"
                      "`kb/topic_face` 文件头第 ⑪ 格那张门槛扫表"
                      "（0.45 变 0 条 / 0.50 变 5 / 0.60 变 11 / 0.70 变 18 / 0.80 变 22）"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_EN060_CHANGED"): (
        PINNED, 11, "英文改走 `topics`@0.60 之后全库变了几条。"
                    "**它是 `p92-en060-11` 那 11 条标注的来源**，一动那 11 条"
                    "（变好 0 / 中性 2 / 变差 9）的分母就换人，"
                    "「P90 ① 那条路也不通」这个判得整条重读——先读第 ⑪ 格"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_EN060_ADD"): (
        PINNED, 37, "这一刀多进来的召回对。**跟 DROP(26) 一起读才有意义**："
                    "37:26 看着像「多召回一点」，而逐条读下来是 **0 好 2 中 9 差**"
                    "——多进来的多数是那族「wearable AI agent powered by the user's own memory」"
                    "样板句。**这一对数是「别拿聚合分当判据」的第二笔现钱**（第一笔是 P90 的 25:5）"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_EN060_DROP"): (
        PINNED, 26, "这一刀挤掉的召回对。**掉的绝大多数是 `Ask Memory` 的具体事实**"
                    "（i=641 掉 5 条、i=645 掉 7 条，整屏换人）。"
                    "它一动去重读 `p92-en060-11` 里 i=641 / i=645 那两行"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_EN060_EMPTY"): (
        PINNED, 0, "「有→空」的条数。**这个 0 是「它没打空屏」那半事实**——"
                   "⚠️ **但它不是「所以可以接」**：11 条里 9 条变差，伤口的形状是**换人**不是**打空**。"
                   "它一动，第 ⑪ 格里「进 37 掉 26、有→空 0」那一行得重写"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_EN060_LIBS"): (
        PINNED, (("terrence-rewrite", 11),),
        "变了的 11 条落在哪几个库上。**只有一个库**——它是唯一一个"
        "「小库 ∧ 有 df 过 common 的英文串 ∧ `topics` 面判得了」的库。"
        "一旦出现第二个库，`p92-holdout-en-137` 那句「做厚的上限 = 9 个串、全在一个库里」"
        "就不成立了，整条「这个仓喂不饱产品那一格」得重数"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_EN060_IDX"): (
        PINNED, (32, 318, 319, 584, 585, 589, 593, 640, 641, 642, 645),
        "变了的**是哪 11 条**。`p92-en060-11` 那 11 行标注就是按这些下标写的，"
        "下标一动标注就对不上人（查询按 note id 排，语料一变下标就挪）。"
        "⚠️ **它跟条数那个 11 是两件事**：条数对得上、下标对不上 = 换了一批查询，"
        "那时候 11 条标注全部作废"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_EN060_TERMS"): (
        PINNED, (("agent", 0.450), ("memory", 0.592)),
        "**这一刀真正多放行的英文串——只有两个**，11 条全是它俩带出来的。"
        "⚠️ **这两个串人标都是「不泛」，尺子判对了，产出照样变差**——"
        "这正是第 ⑪ 格那句「**「不泛」≠「值得当证据」**」的全部分量。"
        "它一动（多出第三个串、或者分数变了）说明语料或 `SPREAD_MIN_HITS` 变了，"
        "「卡在第三格而不是门槛」这个判得重读"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_GATES_PURGES"): (
        PINNED, ("before", "after"),
        "`cf_gates` 每换一次 `common_term` 必须清两次类级缓存（前后各一次）的**账本**。"
        "P90 ④ 留的账：那两句 `purge()` 原来写成两份裸调用，**摘任一份都绿、两份都摘才红**，"
        "闸分不开是哪一份被摘了。现在两句各带 `when` 标签、各记一笔。"
        "它一动 = 有人动了那段缓存接线 —— 去读 `_swap_run` 顶上那段，"
        "以及 `cf_gates` 里「摘了闸的 `WhoFace` 一份都没建出来」那条自检"
        "（那条自检靠的正是「清干净了再建」，少清一次它会静静地量出「0 条变了」）"),

    # —— P94 `--cf-shape`：**「这几条事实彼此有没有区别」那把尺**（造出来了，判「不接」）——
    # 尺在 `app/database/kb/fact_distinct`，**没接进产品**。这十个数是那个判的全部分量。
    # ⚠️ 它们跟上面 `EN060_*` 那组**不是同一件事**：`EN060_*` 量的是「产出变了多少」，
    # 这一组量的是「变出来的是什么形状」。**两组要对着读**（en060 变 11 条 → 其中 3 条翻成灌屏）。
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_TOTAL"): (
        PINNED, 175, "765 屏里「量得了 ≥3 格」的有几屏——**这把尺的分母**。"
                     "它一动，下面按库那张表的每一个百分比都得重算；"
                     "先去读 `kb/fact_distinct` 第 ⑤ 格那张按库的表"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_BLIND"): (
        PINNED, 441, "**一个字都说不出来的屏**（`obj` 或 `topics` 空到量不了，= 57.6%）。"
                     "⚠️ **P96 ② 把它拆开了，别再拿它整笔归给 `obj`**："
                     "419 屏是空屏、3 屏没 topics、**真能归到没有 obj 头上的只有 19 屏**"
                     "（拆账钉在 `EXPECT_SHAPE_BLIND_WHY`）。"
                     "它一动先去读 `EXPECT_SHAPE_BLIND_WHY`，再去读 `kb/fact_distinct` 第 ⑦-c 格"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_BLIND_WHY"): (
        PINNED, (419, 3, 19),
        "441 屏「瞎掉」**拆成三笔**：(空屏, 有事实但无 topics, 有 topics 但一条 obj 都没有)。"
        "⚠️ **第三个数就是「补抽取那一头」的上限**——19 屏 = 765 的 2.5%，"
        "**不是 441 屏**。P94 ⑤-2 那句话方向对、量级错了两个数量级。"
        "它一动（尤其第三个），「补不补抽取」那个判得整条重读——去读 `kb/fact_distinct` 第 ⑦-c 格。"
        "⚠️ 三个数加起来必须等于 `EXPECT_SHAPE_BLIND`（`--cf-shape` 自己有这条自检）"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_HEAD"): (
        PINNED, 12, "HEAD 上判「半屏是同一句话的多种说法」的屏数（**判据 `M`**；`K` 那一版是 18）。"
                    "⚠️ **这 12 屏是 `p94-shape-18` 那 18 屏的子集**（`M` 严格比 `K` 窄），"
                    "所以不用重读标注。它一动说明子集关系破了——"
                    "先核 `flagged(M) ⊆ flagged(K)`，再去读 `kb/fact_distinct` 第 ⑦-b 格"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_EN060"): (
        PINNED, 14, "en060 那一刀之后的屏数。**跟 HEAD 那个 12 一起读才有意义**："
                    "12 → 14 = 那一刀**净造出 2 屏灌屏**。"
                    "⚠️ `K` 那一版是 18 → 21（净 3 屏）——**换 `M` 把这个用途钝了一格**，"
                    "钝掉的那一屏是 i=642（钉在 `EXPECT_SHAPE_FLIP_ON_K`）。它一动去读 `EXPECT_SHAPE_FLIP_ON`"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_FLIP_ON"): (
        PINNED, (640, 645),
        "**从「不是这形状」翻成「是」的是哪两屏**（判据 `M`）。⚠️ 这两个下标必须落在 "
        "`EXPECT_CF_GATES_EN060_IDX` 那 11 条里面（`--cf-shape` 自己有这条自检）——"
        "掉出去就说明这一刀没落在被测分支里，数作废。"
        "它一动，P92 ① 那句「i=645 最清楚」就换了实拍，得重读第 ⑪ 格"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_FLIP_ON_K"): (
        PINNED, (640, 642, 645),
        "**`K` 那一版翻的是哪三屏**——留着当 `M` 的代价的凭据（第 ⑦-b 格代价第 3 条）。"
        "⚠️ 它是**冻死的历史读数**，不是今天跑出来的：`--cf-shape` 今天跑的是 `M`。"
        "它跟 `EXPECT_SHAPE_FLIP_ON` 的差就是 i=642 那一屏；两个一起读才知道换判据钝了多少。它一动去读 `kb/fact_distinct` 第 ⑦-b 格代价第 3 条"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_FLIP_OFF"): (
        PINNED, (), "**反向一屏都没有**——en060 没有把任何一屏从灌屏改成不灌屏。"
                    "⚠️ 这个空元组是「这一刀方向单一」的证据；它一动说明那一刀开始有两个方向的效果，"
                    "「11 条里 0 好 9 差」那个逐条读的结论得重读"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_LIBS"): (
        PINNED, (("fresh678", 0, 2), ("fresh678b", 0, 4), ("fresh678c", 0, 2),
                 ("shot-demo", 2, 14), ("terrence", 6, 97), ("terrence-rewrite", 4, 56)),
        "HEAD 那 12 屏**按库分**（库, 判「是」, 量得了>=3 的分母）。"
        "⚠️ **比率要按对的那条轴分**：三个 2 条语料的小库上分母是 2/4/2，"
        "拿它们算百分比没有意义。它一动去重读 `p94-shape-18` 里那个库的几行。"
        "⚠️ 第三个数（分母）是 `measurable` 决的，**换判据不该动它**——分母动了先查语料"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_READ"): (
        PINNED, (11, 1), "那 12 屏**逐条读完**的 (真, 假)。"
                         "⚠️ **别拿这一对读结论**——它是两笔账混成一笔，"
                         "拆开看是下面 `_BIGLIB` / `_SMALLLIB` 那两对"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_READ_BIGLIB"): (
        PINNED, (5, 1), "**大库 `terrence` 上真 5 / 假 1 = 假阳性 16.7%**（`K` 那一版是 6/6 = 50%），"
                        "而 641/765 = 83.8% 的查询落在大库。"
                        "**这一对就是「治那 6 屏」治到哪儿的读数**，它一动那个判直接翻——"
                        "去读 `kb/fact_distinct` 第 ⑦-b 格"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_READ_SMALLLIB"): (
        PINNED, (6, 0), "两个小库（`terrence-rewrite` 4 屏 + `shot-demo` 2 屏）上真 6 / 假 0。"
                        "⚠️ **它跟上面那一对方向相反，这正是「按库分」的现钱**。"
                        "它一动说明小库那一头也开始误判，去重读 `p94-shape-18` 里那六行，"
                        "「这把尺至少在小库上能用」那句话作废"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_LEFTOVER"): (
        PINNED, (388,),
        "**P96 这一批没治好的那一屏**：i=388（`手环` 五条各说各的手环事，"
        "**出自五场不同的录音**，所以「不同 unit」那条轴拦不住）。"
        "⚠️ 它是「治好了 5/6，不是 6/6」的**凭据本身**，"
        "被写成空元组之前得先有一屏真的被治好——去读 `kb/fact_distinct` 第 ⑦-b 格代价第 2 条"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_HALF"): (
        PINNED, (65, 587, 588, 590, 595, 596, 597),
        "**半屏那道门自己拦下来的是哪 7 屏**（团 ≥3、只差「≥ 半屏」那一格）。"
        "⚠️ **它推翻的是 P94 ⑤ 那句「半屏在正反例上一格都没承重」**——"
        "那句话是在**十组手挑的正反例**上量的，换成全库 765 屏它拦着 7 屏。"
        "**一条在正反例上没承重的门 ≠ 一条永远绿的闸**，这一格就是那个反例。"
        "它一动去重读 `p96-halfdoor-7` 那 7 条标注"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_HALF_READ"): (
        PINNED, (6, 1),
        "那 7 屏**逐条读完**的 (该放, 该拦)。**6 屏该放 / 1 屏该拦（i=65）**。"
        "⚠️ 它说的是**这道门拦错了 6/7**，不是「这道门没用」——"
        "两句话差得很远，动门之前先把这一对和 `EXPECT_SHAPE_NOHALF` 一起读；它一动去重读 `p96-halfdoor-7` 那 7 条标注"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_NOHALF"): (
        PINNED, (19, 17, 2),
        "**摘掉半屏那道门的读数**（判「是」屏数, 真, 假）= 12 → 19 屏、真 11 → 17、假 1 → 2。"
        "⚠️ 它是**钉着的、没落地的读数**：P96 一刀只动一处（已经动了 `same_thing`），"
        "**这一批没摘那道门**。哪天要摘，第一步是核这三个数今天还成不成立，再去读 `kb/fact_distinct` 第 ⑦-d 格"),
    ("backend/scripts/recall_ruler.py", "EXPECT_SHAPE_OBJFACE"): (
        PINNED, ((0.440, 0.752), (0.361, 0.764)),
        "**稀疏化那条量法量 `obj` 的读数**（人读真的那批 min/max, 人读假的那批 min/max）。"
        "⚠️ **两头完全重叠，而且方向是反的**——P94 点名的泛 obj `广告` 打 0.361（全场最低 = 最不泛）。"
        "**这一对就是「不能用这条轴治那 6 屏」的全部依据**，也是「别再造第二把泛尺」的依据。"
        "它一动（比如两头分开了）说明 `topics` 的分布或 `obj` 的抽取变了，"
        "「稀疏化量不了 obj」那个判得整条重读——去读 `kb/fact_distinct` 第 ⑦-a 格"),

    ("backend/scripts/recall_ruler.py", "EXPECT_CF_WHO_BLOCKED"): (
        PINNED, 9, "被主语面挡回去、不再捞回来的串数（价格/公司/反馈/客户/收到/更新/能力/自动/连接）。"
                   "一动说明 `WHO_GENERIC`(0.85)、`SPEAKER_TAG_MAX`(0.5) 或者语料变了——"
                   "先去读 `kb/topic_face` 文件头第 ⑦ 格那段门槛扫（[0.80,0.90] 那个平台）"),

    # —— P86 ①：大库那一档接不接（175 条逐条读完，判**不接**）——
    # **八个数分两组**，因为它们答的是**两个**问题，混着读就判错（P84 ⑤ 那个 175
    # 正是两道闸一起拆量出来的）：`SIZE` 只拆库大小闸 → 判「大库接不接」；
    # `BOTH` 两道闸全拆 → 它是上界，顺带复现 P84 ⑤ 记的那个 175。
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_BIG_SIZE_CHANGED"): (
        PINNED, 53, "只拆库大小闸那一档全库变了几条。它是 `p86-bigsize-25` 那 25 条的来源，"
                    "一动那 25 条标注（变好 8 / 中性 7 / 变差 10）的分母就换人，"
                    "「大库不接」这个判得整条重读——先去读 `kb/topic_face` 文件头第 ④ 格"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_BIG_SIZE_ADD"): (
        PINNED, 108, "它比「没有这条轴」多进来的召回对。跟 DROP 一起读才看得出是「多召回」还是「灌满」"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_BIG_SIZE_DROP"): (
        PINNED, 33, "它比「没有这条轴」少掉的召回对。**掉的那一侧是代价**，一动去重读 "
                    "`p86-bigsize-25` 里 i=1 / i=2 / i=35 / i=607 那四格"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_BIG_SIZE_LIBS"): (
        PINNED, (("terrence", 25), ("terrence-rewrite", 28)),
        "**这一条是「两个旋钮真的分开了」的全部证据**：小库那一行必须逐条等于 "
        "`EXPECT_CF_SPREAD_CHANGED`(28)——拆库大小闸不该动小库。对不上就是量具接错层了，"
        "上面三个数当场作废；大库那 25 一动，`p86-bigsize-25` 整组重读"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_BIG_BOTH_CHANGED"): (
        PINNED, 175, "**两道闸全拆那一档 = P84 ⑤ 记的那个 175**（这一批把它跑出来并逐条读完）。"
                     "一动，`p86-bigcorpus-175` 那 175 条标注整组失效"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_BIG_BOTH_ADD"): (
        PINNED, 577, "**进 577 / 掉 80 这个 7:1 的不对称本身就是判据**：它说明那不是"
                     "「多召回一点」，是把空屏灌满（134 条里 93 条变差）。这个比例一塌，"
                     "「不接」的理由就少了一半"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_BIG_BOTH_DROP"): (
        PINNED, 80, "两闸全拆少掉的召回对。一动去重读 i=78 / i=407（掉的是「公司专注的领域"
                    "主要是ICT」那条逐字出处）和 i=293 / i=607（1→0，整屏变空）"),
    ("backend/scripts/recall_ruler.py", "EXPECT_CF_BIG_BOTH_LIBS"): (
        PINNED, (("terrence", 134), ("terrence-rewrite", 41)),
        "175 = 134 + 41。`terrence` 那 134 是这一批的正题（**真实用户那条路**，血缘 user 124 / "
        "script 10）；`terrence-rewrite` 那 41 就是 P84 ② 读过的那一组"
        "（P84 读成 17:17，这一批重读 10:18，口径差在哪写在 `p86-bigcorpus-175` 的 `_meta` 里）。"
        "**一旦够得着第三个库，按库分那张表和两组标注的分母全部换人**"),

    # —— P82 ②：quorum 有多脆（量了没改，这四个数就是那个「多脆」）——
    ("backend/scripts/en_gate_ruler.py", "EXPECT_QUORUM_CALLS"): (
        PINNED, 375959, "`_strong_enough` 在 765 上被问了多少次。它是下面三个数的分母，一动三个数一起废。"
                        "⚠️ P84 抬了它（那条「泛词 vs 主题词」的轴在小库上多放了 63 个串进证人名单，这道门就多被问了几趟）；比率没变。375864 → 375963。"
                        "⚠️ P88 又退了 4（新串的主语面轴把 9 个串挡回 `common`，这道门就少被问了几趟）；比率还是没变。375963 → 375959"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_QUORUM_TRUE"): (
        PINNED, 1816, "其中判 True 的次数。EDGE / TRUE = **84.0%** 是 P82 ② 的结论本身（P82 1771 / 84.0% → P84 1821 / 84.1% → P88 1816 / 84.0%，**分母来回动了三次，形状没动**）"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_QUORUM_EDGE"): (
        PINNED, 1526, "**P82 ② 那条判的全部分量**：判 True 里证人正好两条的有 1526 次 = **84.0%**，"
                      "少一条证人就翻 False。这个数一动，「quorum 有多脆」就得重量。"
                      "⚠️ P84 抬了它（那条轴多放了 63 个串进证人名单）：1488 → 1531，比率 84.0% → 84.1%；"
                      "⚠️ P88 又退回去（主语面轴挡回 9 个串）：1531 → 1526，比率回到 **84.0%**。**三次都没动形状**"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_QUORUM_REJECT_AT_2"): (
        PINNED, 11, "够了 quorum 又被后面那道 `≥3 字 / 实词` 判回去的次数——**只有 len(cl)==2 这一档有**。"
                    "它一动说明后面那道门的量程变了（那是 `EN_STRONG_MIN` / `STRONG_CJK_MIN` 的事）"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_QUORUM_SHOWN"): (
        PINNED, (1369, 302, 793, 1067),
        "**用户眼前**那 1369 条召回对里，这道门管着 1067 条、其中 793 条靠正好两条证人撑着（**74.3%**）。"
        "⚠️ P84 把召回对从 1347 抬到 1367（那条轴在小库上多捞回 20 对），比率 74.2% → 74.3%；"
        "⚠️ P88 再 +2（主语面轴让 i=26 / i=293 各多摆一条），比率 **74.3% 逐位相同**"
        "——**说明的正是召回本身变了，而 quorum 那个形状没变**"),

    # —— P82 ③：屏幕上写的串 ≠ 用户打的串 ——
    ("backend/scripts/kb_search_ruler.py", "EXPECT_SHOWN_TOTAL"): (
        PINNED, 108, "110 条手打搜索词一共摆出来几串——**下面那个 `EXPECT_PARTIAL_SHOWN = 0` 的分母**。它一动说明 `display_terms` 摆出来的东西整体变了，那个 0 就不是在同一批串上数的了"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_PARTIAL_SHOWN"): (
        PINNED, 0, "**「屏幕上写的是用户打的那个 token 的一截」在 110 条上是 0 条**。"
                   "这个 0 是 P82 ③ 判「不修」的依据之一；它一动说明 `display_terms` / "
                   "`recall()` 回的 `terms` 换了口径，那一行的诚实度要重判"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_DATEWRITE_SHOWN"): (
        PINNED, 2, "**20 种用户真会打的日期 / 数字写法，屏幕上一共只摆出 2 串**——"
                   "P81 ② 记的 `9月14日 → 摆 9月14` 在渲染那条路上一次都没发生过。"
                   "这个 2 一动说明 `recall()` 开始收数字了，P81 ② / P82 ③ 两笔账一起重读"),
    ("backend/scripts/kb_search_ruler.py", "EXPECT_DATEWRITE_PARTIAL"): (
        PINNED, 2, "那 2 串**两串都是只摆了一截**（`179美元`→`美元`、`1万台`→`万台`，数字被整个丢掉）。"
                   "跟上面那个 2 一起读：摆出来的每一串都名不副实，但总共只有两串"),

    # —— P85 C②：走查第 ⑧ 步那个夹具（`--variant synthetic`）逐格钉死 ——
    ("backend/scripts/journey_fixture.py", "EXPECT_SYNTHETIC"): (
        PINNED, {"days": 3, "segs": (4, 2, 0), "desc": (2, 2, 0), "frames": (1, 0, 0),
                 "thumbs": 6, "reports": 1, "bytes_norm": 4198},
        "**走查第 ⑧ 步唯一可复现的那份夹具**（P83 留的第 ④ 条）。屏幕上那五行"
        "（「3 天的记录 / 6 段，其中 4 段有描述 / 6 张缩略图 / 1 份写好的日报 / 一共 5 KB」）"
        "逐格就是这张表。一动，⑧ 那一格跟 P83 / P85 的逐格对账当场作废——"
        "先去重读走查表第 ⑧ 行和 `backend/tests/test_p85.py` 那四条。"
        "⚠️ 钉的是**归一之后**的字节数：真字节数会随「造在哪个目录」变（`segments.json` 里 7 个绝对路径）。"
        "P85 连栽两次才定下来——先钉 5066 换个目录红成 5073，退到「折成 KB」pytest 里又红成 4 KB。"
        "**「粗一点」不等于「跟路径无关」**"),

    ("backend/scripts/margin_dot_ruler.py", "EXPECT"): (
        PINNED, {"dots": {"segments": 166, "judged": 137, "drawn": 33},
                 "walk": {"segments": 3, "judged": 2, "drawn": 2},
                 "tableb": {"facts": 8}},
        "圆点那一栏的四栏留下率。P70 起每批都在拿 166/137/33 对账"),
}


class Unreadable(Exception):
    """扒不出一个字面量。**当场红，不许静默跳过**——看不懂的那一条正是最该看的那一条。"""


def _py_constants(src: str) -> dict[str, object]:
    """.py 的模块级常数。用 `ast`，不用正则（注释 / 缩进 / 多行字面量全是正则的坑）。"""
    out: dict[str, object] = {}
    for node in ast.parse(src).body:
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and WATCHED_NAME.match(t.id):
                try:
                    out[t.id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError) as e:      # noqa: PERF203
                    raise Unreadable(f"{t.id} 不是字面量，这把尺读不懂：{e}") from e
    return out


# `const NAME = 123` 顶格那一行。**顶格**是有意的：函数体里的局部变量不是闸门常数，
# 而缩进的那一行进来只会让这把尺去管它管不了的东西。
_TS_DECL = re.compile(r"^const ([A-Za-z_][A-Za-z0-9_]*) = (.+?)\s*$")


def _ts_constants(src: str) -> dict[str, object]:
    """.mts / .mjs 的顶层常数。只认整数 / 小数字面量，**别的当场抛**。"""
    out: dict[str, object] = {}
    for line in src.split("\n"):
        m = _TS_DECL.match(line)
        if not m:
            continue
        name, raw = m.group(1), m.group(2).rstrip(";")
        if not WATCHED_NAME.match(name):
            continue
        if not re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
            raise Unreadable(f"{name} 的值 {raw!r} 不是一个数字字面量，这把尺读不懂")
        out[name] = float(raw) if "." in raw else int(raw)
    return out


def read_constants(rel: str) -> dict[str, object]:
    p = REPO / rel
    if not p.is_file():
        raise Unreadable(f"{rel} 不在了")
    src = p.read_text(encoding="utf-8")
    return _py_constants(src) if rel.endswith(".py") else _ts_constants(src)


# ── 例 / 反例：**先喂它一个该红 / 该绿的**（每批的规矩）────────────────────
BATTERY: tuple[tuple[str, str, object], ...] = (
    # (怎么写的, 该扒出什么 —— "!" 开头 = 该抛)
    ("py", "MIN_STEPS = 8", {"MIN_STEPS": 8}),
    ("py", "# MIN_STEPS = 8", {}),                                  # 整行注释不算
    ("py", "def f():\n    MIN_STEPS = 3", {}),                      # 函数体里的不算
    ("py", "SEED = 79", {}),                                        # 名字不在看着的那几个前缀上
    ("py", "EXPECT_CF = {2: (1, 2)}", {"EXPECT_CF": {2: (1, 2)}}),  # 字典 / 元组照扒
    ("py", "MIN_X = 3 if flag else 4", "!"),                        # 不是字面量 → 当场抛，不许静默跳过
    ("ts", "const MIN_STEPS = 8", {"MIN_STEPS": 8}),
    ("ts", "// const MIN_STEPS = 3", {}),                           # 注释掉的不算
    ("ts", "  const MIN_STEPS = 3", {}),                            # 缩进的不是顶层常数
    ("ts", "const SPREAD_GENERIC = 0.75", {"SPREAD_GENERIC": 0.75}),
    ("ts", "if (plan.length < MIN_STEPS) {", {}),                   # 用到它不是声明它
    ("ts", "const MIN_STEPS = someCall()", "!"),                    # 读不懂 → 抛
)


def run_battery() -> list[str]:
    bad: list[str] = []
    for kind, src, want in BATTERY:
        fn = _py_constants if kind == "py" else _ts_constants
        try:
            got: object = fn(src)
        except Unreadable:
            got = "!"
        if got != want:
            bad.append(f"例 / 反例对不上：[{kind}] {src!r} → {got!r}，该是 {want!r}")
    return bad


def check() -> tuple[list[str], int, list[str]]:
    """回 (对不上的话, 核了几条, 基线落后的那几条)。

    第三样是**慢漏**那一格：`floor` 那一档往上调是绿的，可要是登记的基线没跟着抬，
    下一批把它调回旧的低值照样绿——**松动是一点点攒出来的**。
    这一条不算「对不上」（往上调是合法的），但 `pytest` 那边钉着它是 0：
    抬了下限就顺手把登记一起抬上来。
    """
    bad = run_battery()
    behind: list[str] = []
    checked = len(BATTERY)
    seen: set[tuple[str, str]] = set()
    for rel in WATCHED:
        try:
            consts = read_constants(rel)
        except Unreadable as e:
            bad.append(f"{rel}：{e}")
            continue
        for name, value in consts.items():
            key = (rel, name)
            seen.add(key)
            checked += 1
            if key not in REGISTRY:
                # **登记表的完整性**：这一条才是「把洞挪个地方」真正的出口
                bad.append(f"{rel} 的 `{name}` 没登记 —— 新加一个闸门常数就得在 "
                           "`floor_ruler.REGISTRY` 里写清楚它是「只准往上」还是「钉死」，"
                           "以及**它一动要去重读什么**")
                continue
            kind, base, why = REGISTRY[key]
            if kind == FLOOR:
                if not isinstance(value, (int, float)) or value < base:  # noqa: UP038
                    bad.append(f"{rel} 的 `{name}` = {value!r}，**比登记的下限 {base!r} 还低**"
                               f" —— {why}。往上调是绿的，往下调得连这张登记表一起改")
                elif value > base:
                    behind.append(f"{rel} 的 `{name}` 已经抬到 {value!r}，登记还停在 {base!r}"
                                  " —— 抬了就顺手把登记一起抬上来，不然下一批调回去是绿的")
            elif value != base:
                bad.append(f"{rel} 的 `{name}` = {value!r} ≠ 登记的 {base!r}"
                           f" —— **这条结论现在得重读**：{why}")
    for key in REGISTRY:
        if key not in seen:
            checked += 1
            bad.append(f"登记了 {key[0]} 的 `{key[1]}`，而源码里扒不到它 —— "
                       "要么被删了（那条结论谁在守？），要么改了名（登记表没跟上）")
    return bad, checked, behind


def main(argv: list[str]) -> int:
    bad, checked, behind = check()
    floors = sum(1 for v in REGISTRY.values() if v[0] == FLOOR)
    if "--list" in argv:
        for (rel, name), (kind, base, why) in sorted(REGISTRY.items()):
            print(f"    [{kind:6}] {rel.split('/')[-1]:34} {name:28} = {base!r}")
            print(f"             ↳ {why}")
    print(f"下限那把尺：看着 {len(WATCHED)} 份 / 登记 {len(REGISTRY)} 条"
          f"（只准往上 {floors} · 钉死 {len(REGISTRY) - floors}）/ 例反例 {len(BATTERY)} 条"
          f"；共核 {checked} 条；基线落后 {len(behind)} 条；对不上 {len(bad)} 条")
    for b in behind:
        print("  · " + b)
    if bad:
        for b in bad:
            print("  ✗ " + b, file=sys.stderr)
        print("**下限自己被调低，或者新加的下限没人登记**——"
              "先读上面那几句「一动要去重读什么」，别直接把登记表改成现在这个数。", file=sys.stderr)
        return 9
    print("OK: 每个下限都还在它该在的地方（往上调是绿的；钉死那一档一动就红）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
