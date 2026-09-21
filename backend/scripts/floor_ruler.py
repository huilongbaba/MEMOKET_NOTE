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
    "frontend/scripts/check-walkthrough-fakeshell.mts",
    "frontend/scripts/check-walkthrough-selectors.mts",
)
# 哪些名字算「闸门常数」。**宁可窄**：只认这几个前缀，别的名字（`SEED` / `LIMIT` /
# `USER`…）不进登记表，也就不受这把尺管——它们不是「下限」也不是「实测结论」。
WATCHED_NAME = re.compile(r"^(MIN_[A-Z0-9_]*|MAX_[A-Z0-9_]*|EXPECT[A-Z0-9_]*|SHOW|SPREAD_[A-Z0-9_]*)$")

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
        PINNED, 964, "727 条 cursor 查询摆出来的卡总数（上界口径，见那把尺的文件头）。"
                     "它是 133 / 62 / 29 / 33 四个数共同的分母——一动，四条判全部重读"),
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
        PINNED, 312, "727 条里真摆出了卡的条数（其余 415 条一张都没有）。"
                     "它是「盖戳率」唯一正确的分母——拿 727 去除是把 415 条空屏也算进去了"),
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
    ("backend/scripts/en_gate_ruler.py", "EXPECT_BLOCKED_OCC"): (PINNED, 568, "P77 那道英文 ≥3 的门挡掉的串次"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_BLOCKED_KINDS"): (PINNED, 14, "那道英文 ≥3 的门挡掉了多少**种**串。跟 568 串次一起读（P77 ①）"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_TOP_BLOCKED"): (
        PINNED, ("ai", 451), "**P79 ① 那条判的全部分量**：`ai` 被挡 451 串次"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_FLIP_AT_2"): (PINNED, 11, "英文门放宽到 2（= 不设门）会翻盘的调用数。P77 「这道门该不该换轴」架在这上面"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_FLIP_QUERIES_AT_2"): (PINNED, 7, "放宽到 2 时会翻盘的查询条数（11 次调用落在 7 条查询上）"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_FLIP_AT_4"): (PINNED, 213, "英文门收紧到 4 会翻盘的调用数。跟放宽那一档的 11 是同一条判的两头"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_FLIP_QUERIES_AT_4"): (PINNED, 100, "收紧到 4 时会翻盘的查询条数（213 次调用落在 100 条查询上）"),
    ("backend/scripts/en_gate_ruler.py", "EXPECT_CF"): (
        PINNED, {2: (342, 1353, 2), 1: (342, 1353, 2), 4: (317, 1225, 67)},
        "三档门槛各自的全库对拍。P77 「这道门该不该换轴」那条判就架在这张表上"),
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
