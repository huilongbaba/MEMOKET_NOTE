"""**那把量「知识库搜索框」的尺**（P79 ②）。仓库里在这之前一把都没有。

    .venv/bin/python scripts/kb_search_ruler.py          # 反例两头 + 真库解剖，对不上 exit 9
    .venv/bin/python scripts/kb_search_ruler.py --list   # 顺带把 110 条逐条打出来

---

## 为什么要造它：**唯一真摆 `display_terms` 的那条路，今天一把尺都量不到**

P77 ② 把渲染那一层量清楚了（765 条实测）：

| 右栏「记忆」那一行走哪一支 | 条数 |
|---|---:|
| `facts=0` → 那一行压根不渲染 | 424 |
| `evidence` 有东西 → 摆 chip，`terms` 用不上 | 335 |
| `evidence=[]` → 「这一段没有可摆出来的证据」 | 6 |
| **`evidence=null` → 退回 `terms`** | **0** |

**⇒ 右栏那一行一条都走不到 `terms`。** 真摆 `display_terms` 的只剩一处：
`frontend/src/components/kb/KbDashboard.tsx` 的

    {hits.terms.length ? ' · 命中词：' + hits.terms.slice(0, 6).join('、') : ''}   ← P79 那天
    {hits.terms.length ? (hits.facts.length ? ' · 命中词：' : ' · 找过：')
                         + hits.terms.slice(0, 6).join('、') : ''}                 ← P81 ③ 之后

**而那条路的查询是用户手打的搜索词**——短、常常就一两个词、没有上下文，
跟 `recall_ruler` 那 765 条（自动召回，光标段 + 前一段，中位数三位数字）**完全不是一个形状**。
拿 765 那把尺去判这条路就是 P4 那一跤（**判据宁可窄**）。这一份是来补那个量程的。

## 110 条怎么来的：**五档，全部从这个人自己的库里长出来**

档位不是拍脑袋分的，是**产品自己写在搜索框里的那一句**——
`placeholder="搜知识库：人、事、数字、日期…"`——加上唯一一条真会把词送进来的路
（侧栏搜笔记没搜到 → `kb-search` 事件 → 同一个词转到知识库）。

| 档 | 条 | 从哪儿长出来 |
|---|---:|---|
| 实体 | 40 | `FactRecord.entities` 里出现 ≥3 次、≤10 字、**不带 `_` / `-`**（带的是内部码，没人手打）|
| 数字日期 | 20 | 事实原文里 ≥5 次的数字串（`\\d+` + 可选的 `年月号日%万亿台个人`）|
| 英文 | 20 | 事实原文里 ≥10 次的纯 ASCII token（**含口水词**：搜索框拦不住用户打什么）|
| 两个词 | 20 | **同一条事实里共现**的两个实体，中间一个空格 |
| 库里没有 | 10 | 一张钉死的表，**每一条都断言过库里真的 0 条**（绿有个数的那个绿）|

种子 79，均匀随机打散、不分层（按任何一个判据分层就等于先看了尺子的判）。

## 量四条，**四条都是机械判据，不掺人读**

1. **0 条结果还摆命中词** —— `facts == 0` 而那一行照摆。
   ⚠️ P48 ③ 判过这条路「今天 0 个用户看得见」，**P69 已经更正为「不成立」**；
   这一份再核一遍，**今天仍然成立**：`KbSection` 的 `extra` 只看 `hits.terms.length`，
   `hits.facts.length` 一个字都没问（`KbDashboard.tsx` 那一行）。
2. **摆了用户没打过的词** —— 摆出来的串不是 `squeeze(查询)` 的子串。
   （这一条对 765 那把尺不成立：那边查询几百字，摆的词当然都在里面。
   这边查询就几个字，摆一个不在里面的词 = 用户看不懂它从哪儿来。）
3. **跨过用户自己打的空白合出来的词** —— P79 ② 那一刀的靶子。
   判法是**把 `search.squeezed_gaps` 打成空集再跑一遍**（= 逐字退回改之前那一版）再比。
   **旋钮得证明自己在动**：改之前 3 条、改之后 0 条。
4. **打了的词一个都没摆出来** —— 按**空格切出来的每个 token** 判，不按整串
   （整串判的话两个词的查询必然全红，那是判据的错不是产品的错）。

## 它答不了什么

* **召回本身对不对**——这把尺只量那一行「命中词：」。
  顺手量出来的 `facts` 条数只当分母用，别拿它读相关性。
* **别人的库**——五档全是从 terrence 这一个库长出来的，换个语料这 110 条就得重长
  （`corpus_tag` 跟着数一起打出来，同 `recall_ruler` 那条规矩）。
* **真用户打的词**——这一批没有搜索日志。这五档是**库自己的形状**，不是行为数据；
  它挡得住「摆出一个库里没有的词」这类错，挡不住「用户想搜的东西这个库压根没有」。

## 顺手量到、**这一批没修**的两格（账在台账 P79 ②）

* **数字日期那一档 20/20 全 0 条结果**——搜索框自己写着「数字、日期」，
  可 `9月` / `30%` / `150` 打进去一条都搜不到。根因没查，**判据宁可窄，这一批不动。**
* **「库里没有」那一档 10 条里 9 条 0 结果、却照样摆着「命中词：潜水艇」**——
  那一行摆的是**找过的词**，不是**命中的词**。跟第 1 条是同一件事的两半。

---

## P81 在这把尺上加了什么（**只加不改**，P79 钉死的九个数一个没动）

* **上面第二格修了**（P81 ③）：`KbDashboard` 那一行 0 召回时改口「找过：」。
  `check_source()` 跟着钉新的三段（两个标签的字面 + `facts.length` 那个判据）；
  `--line` 把**用户眼前那一行的前后对比**原样打出来，两个标签**从 `.tsx` 里现读**，
  这儿不另抄一份（抄一份就是两把尺，P67 ② 那一课）。
  ⚠️ `EXPECT_EMPTY_WITH_LINE = 9` **这个数没动**——**摆不摆是一件事，摆的叫什么是另一件。**
* **上面第一格量完了、判「不修」**（P81 ②）：数字日期那 20 条的解剖进了这把尺，
  五个数钉死（库里真有 20/20 · 没通道 9 · 切不出词 11 = 两位数 4 + 日期量词 7）。
  理由整段在 `EXPECT_NUMDATE_IN_CORPUS` 那几行上面。
"""

from __future__ import annotations

import hashlib
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database.kb import search as kb_search  # noqa: E402

SEED = 79
USER = os.environ.get("KBQ_USER", "terrence")
SHOW = 6          # `KbDashboard` 那一行 `slice(0, 6)`
LIMIT = 20        # `recall(q, 20)`，同 `KbDashboard`

_NUM = re.compile(r"(?<![0-9A-Za-z])[0-9][0-9]{0,5}(?:年|月|号|日|%|万|亿|台|个|人)?")
_EN = re.compile(r"(?<![0-9A-Za-z])[A-Za-z][A-Za-z0-9]{1,11}(?![0-9A-Za-z])")
_CODEY = re.compile(r"[_\-]")

# 「库里没有」那一档。**每一条都在 `measure()` 里断言过真的 0 条**——
# 一张没人核的对照表就是一张假对照表。
MISSING = ("潜水艇", "小提琴", "马尔代夫", "考古", "鲸鱼",
           "地铁票", "牙医", "火山", "橄榄油", "羽毛球")
# ⚠️ `羽毛球` 在 terrence 的库里**真有 1 条**（逐条读出来的，照实记）——
# 它留在这一档里，`EXPECT_MISSING_HIT` 钉着这个 1。**别为了让表好看把它换掉。**
EXPECT_MISSING_HIT = 1

STRATA = (("实体", 40), ("数字日期", 20), ("英文", 20), ("两个词", 20), ("库里没有", 10))

# 真库 terrence 上钉死的量程（P79 ② 实测）。对不上 = 语料或口径变了，那一刻这几个数全废。
EXPECT_TOTAL = 110
EXPECT_EMPTY = 30              # 0 条结果
EXPECT_EMPTY_WITH_LINE = 9     # 0 条结果**还摆着命中词**
EXPECT_UNASKED = 0             # 摆了用户没打过的词
EXPECT_GAP_MERGED_HEAD = 3     # 改之前：跨空白合出来的词
EXPECT_GAP_MERGED_NOW = 0      # 改之后
EXPECT_TOKEN_MISS = 0          # 打了的词一个都没摆出来
EXPECT_NUMDATE_EMPTY = 20      # 数字日期那一档全 0 条

# ── 数字日期那一档**为什么**全 0（P81 ②，只加不改：这几个数是 P79 ② 留的账的量化）──
#
# 那 20 条是从**这个库自己的事实原文**里长出来的（`_NUM` 找 ≥5 次的串），所以
# 「库里有没有」这件事本来就该是 20/20。量下来正是：**20 条串库里全都有，20 条全搜不到。**
# 产品搜索框写着 `placeholder="搜知识库：人、事、数字、日期…"`——**答应了的事它做不到。**
#
# 根因**是两个洞，不是一个**（P79 ② 只定位到前一个）：
#   · `plan` 没有数字通道 —— `_number_terms` 只喂 `_terms`（那一行「命中词：」），
#     `search.plan` 的三条通道（symbolic / 英文词 / 中文 grep）和 `_recall_via_lines`
#     的两条（`_cjk_terms` + `_candidate_terms`）**都不收数字**。
#     `_terms` 认得出 `150` / `30%` / `8个`，`plan` 回空 → 候选池空 → 0 条。
#   · `_NUM` 自己就切不出来 —— `\d+月\d+|\d+(\.\d+)?[台套个件人次轮版元万亿%]|\d{3,}`：
#     两位数的裸数字（`11` `13` `42` `95`）过不了 `\d{3,}`；
#     而那张量词表里**没有 `月` / `号` / `日` / `年`**，于是 `9月` `23号` `19号` `30号`
#     `29号` `4号` `23年` 连 `_terms` 都是空的——**产品自己写的「日期」那两个字，
#     是这一档里连词都切不出来的那个形状。**
#
# 能搜到的「数字」全是**别的通道顺带救的**，不是数字通道（P81 ② 逐条量过）：
# `Q3` / `T0` / `DVT` 走英文词通道、`950` 走 symbolic（`950 超节点` 是实体）。
#
# **这一批量完判「不修」**，理由在台账 P81 ②：补 `plan` 那个洞的反事实
# 在 765 那把尺上爆炸半径确实是 0，但逐条读那 9 条捞回来的——
# `600` 命中 `60000000` / `4600万` / `1,600毫米`、`8个` 命中 `18个` / `128个`
# ——因为 `_hits` 对数字是**去空白后子串匹配**（注释里写着理由：事实原文写成「4 月 16 号」）。
# 要它不噪就得给数字加数位边界，而 `_hits` 同时喂着 765 条自动召回的排序和命中词行。
# **一刀只动一处**，这一批先把量程钉下来。
# ── **「屏幕上写的串 ≠ 用户打的串」**（P82 ③，量完判「不修」）──────────────────
#
# P81 ② 顺手记了一笔：「`9月14日` → 命中词摆 `9月14`；`2026-09` → 摆 `2026`」。
# ⚠️ **那笔账记的是 `search._number_terms` 的产出，不是屏幕上那一行**（P82 ③ 重量的）。
# 唯一真渲染那一行的那条路是 `/recall` → `RecallOut.terms` → `display_terms`，
# 而 `UserMemory.recall()` 回的 `terms` 是 **`surfaces`（词表表层词）+ `_cjk_terms(query)[:3]`**
# ——`_number_terms` 一个字都进不去。实测 20 种用户真会打的日期 / 数字写法：
#
#   打「9月14日」   → `_number_terms=['9月14']`  **屏幕：一个字都不摆**（0 条结果）
#   打「2026-09」  → `_number_terms=['2026']`   **屏幕：一个字都不摆**
#   打「2026-03-10」`2025/10/27` `3月15日` `4月16号` `8月5日` `150` `30%` `500台` … 同上
#   打「179美元」   → 屏幕「**美元**」（0 条结果）   ← 数字被整个丢掉
#   打「1万台」     → 屏幕「**万台**」（15 条结果）  ← 同上
#
# **所以 `9月14` 那个截断串在用户眼前一次都没出现过。** 20 条里屏幕上一共只摆出 **2 串**，
# 两串都是**前面那截数字被整个丢掉**，不是「后面的 `日` 被吃掉」。
# 110 条那一档更干净：摆出来 108 串，**「只摆了一截」0 条**
# （`极梦ai` → 摆 `ai`、`极梦ai`——**整串跟它同行摆着**，那不是没打完，
# 是多摆了一个更泛的命中词，而那 20 条结果里确实有 16 条是靠 `ai` 进来的，**它没说谎**）。
#
# **「找过：9月14」跟「找过：9月14日」哪个更诚实？——都不诚实，今天这样最诚实**（P82 ③ 判的）：
# 这条路上 `terms` 是**空的**，那一行整段不渲染。摆 `9月14` 是假的（用户没打过这一截，
# 后端也没拿它去找过）；摆 `9月14日` 也是假的（后端从头到尾没拿这一串找过任何东西）。
# **「什么都没找过」的诚实说法就是什么都不说。**
# 真正名不副实的是搜索框自己那句 `placeholder="…数字、日期…"`——那笔账在 P81 ② 判过「不修」。
EXPECT_SHOWN_TOTAL = 108        # 110 条一共摆出来几串
EXPECT_PARTIAL_SHOWN = 0        # 其中「只摆了一截、整串又不在同一行上」的
EXPECT_DATEWRITE_SHOWN = 2      # 20 种日期 / 数字写法一共摆出来几串
EXPECT_DATEWRITE_PARTIAL = 2    # 其中「只摆了一截」的（两串都是数字被整个丢掉）

# 20 种**用户真会打的**日期 / 数字写法。跟上面那 20 条不是一回事：
# 那 20 条是从库里长出来的串，这 20 种是**产品 placeholder 答应的那两个字的形状**。
DATE_WRITINGS = ("9月14日", "2026-09", "2025/10/27", "3月15日", "2026年3月", "4月16号",
                 "2026-03-10", "第2款", "179美元", "30%", "150", "11", "9月", "23号",
                 "2026年", "2026.03.10", "3月15", "8月5日", "1万台", "500台")

EXPECT_NUMDATE_IN_CORPUS = 20   # 20 条串，库里真的有的（= 全部）
EXPECT_NUMDATE_NO_CHANNEL = 9   # `_terms` 切得出、`plan` 没通道 → 0 条
EXPECT_NUMDATE_NO_TOKEN = 11    # `_NUM` 连词都切不出来（4 条两位数 + 7 条日期量词）
EXPECT_NUMDATE_TWO_DIGIT = 4    # 其中：两位数裸数字
EXPECT_NUMDATE_DATE_UNIT = 7    # 其中：`月` / `号` / `日` / `年` 这张量词表外的


def corpus_tag(user: str = USER) -> str:
    root = Path(os.environ.get("KITE_DATA_DIR") or (BACKEND / "data"))
    cb = root / user / "codebook.xml"
    if not cb.is_file():
        return "no-codebook"
    return f"{cb.stat().st_size}B/{hashlib.sha256(cb.read_bytes()).hexdigest()[:8]}"


def queries(memory) -> list[tuple[str, str]]:
    """[(档, 手打的搜索词)]，种子固定、顺序稳定。"""
    store, _vocab = memory._index()
    facts = list(store.facts.values())

    ecount: Counter = Counter()
    for f in facts:
        for e in (getattr(f, "entities", None) or ()):
            ecount[e] += 1
    ents = sorted(n for n, c in ecount.items()
                  if c >= 3 and 1 <= len(n) <= 10 and not _CODEY.search(n))

    nums: Counter = Counter()
    ens: Counter = Counter()
    for f in facts:
        text = (f.text or "")
        for mm in _NUM.findall(text):
            if len(mm) >= 2:
                nums[mm] += 1
        for mm in _EN.findall(text):
            ens[mm.lower()] += 1
    numlist = sorted(t for t, c in nums.items() if c >= 5)
    enlist = sorted(t for t, c in ens.items() if c >= 10)

    pairs: set[tuple[str, str]] = set()
    for f in facts:
        es = [e for e in (getattr(f, "entities", None) or ())
              if ecount.get(e, 0) >= 3 and 1 <= len(e) <= 8 and not _CODEY.search(e)]
        for i in range(len(es)):
            for j in range(i + 1, len(es)):
                pairs.add(tuple(sorted((es[i], es[j]))))          # type: ignore[arg-type]
    pairlist = sorted(pairs)

    rnd = random.Random(SEED)

    def pick(xs, k):
        xs = list(xs)
        rnd.shuffle(xs)
        return xs[:k]

    out: list[tuple[str, str]] = []
    out += [("实体", t) for t in pick(ents, 40)]
    out += [("数字日期", t) for t in pick(numlist, 20)]
    out += [("英文", t) for t in pick(enlist, 20)]
    out += [("两个词", f"{a} {b}") for a, b in pick(pairlist, 20)]
    out += [("库里没有", t) for t in MISSING]
    return out


def _shown(memory, terms, q, *, gaps: bool) -> list[str]:
    """那一行真摆出来的前 6 个。`gaps=False` = 把 `squeezed_gaps` 打成空集
    （守卫恒不成立）= **逐字退回 P79 ② 改之前那一版**。"""
    real = kb_search.squeezed_gaps
    if not gaps:
        kb_search.squeezed_gaps = lambda _q: set()
    try:
        return kb_search.display_terms(terms, q, segment=memory.segment())[:SHOW]
    finally:
        kb_search.squeezed_gaps = real


def crosses_gap(term: str, squeezed: str, gaps: set[int]) -> bool:
    """这一串在查询里**跨过了一处被挤掉的空白**——它是两个词被接成的一个。

    **按串本身判，不按两版的差判**：差只说明「这一刀动了它」，
    这一条说明的是「它本身就是错的」。两个数都要，缺一个就分不清
    「旋钮在动」和「产出对了」。
    """
    start = 0
    while True:
        i = squeezed.find(term, start)
        if i < 0:
            return False
        if any(i < g < i + len(term) for g in gaps):
            return True
        start = i + 1


_DATE_UNIT = re.compile(r"^\d+[月号日年]$")


def numdate_shape(memory, q: str) -> str:
    """数字日期那一档的一条**为什么**搜不到——三选一，机械判据（P81 ②）。

    `no_token` = `_NUM` 连词都切不出来；`no_channel` = 切得出但 `plan` 没这条通道；
    `ok` = 真搜得到。判的是**今天的源码**，不是台账上的数。
    """
    if kb_search._number_terms(q):
        store, vocab = memory._index()
        plan = kb_search.plan(memory, q, vocab, segment=memory.segment(),
                              common=memory.common_term())
        return "no_channel" if not plan else "ok"
    return "no_token"


def partial_shown(shown: list[str], q: str) -> list[tuple[str, str]]:
    """摆出来的串里，哪几个**只是用户打的那个 token 的一截**（P82 ③）。

    判据：按空白切出用户打的每个 token，摆出来的串 `squeeze` 之后如果是某个 token 的
    **真子串**，而**那个 token 自己又没同行摆着**，就是「只摆了一截」。
    ⚠️ 「整串同行也摆着」那一档不算（`命中词：ai、极梦ai`）——那不是没打完，
    是多摆了一个更泛的命中词，读法完全不同。
    """
    toks = [kb_search.squeeze(t) for t in q.split() if kb_search.squeeze(t)]
    sq_shown = {kb_search.squeeze(x) for x in shown}
    out = []
    for t in shown:
        st = kb_search.squeeze(t)
        host = next((tk for tk in toks if st in tk), None)
        if host is None or st == host or host in sq_shown:
            continue
        out.append((host, t))
    return out


def date_writings(memory) -> list[dict]:
    """那 20 种**用户真会打的**日期 / 数字写法，屏幕上到底摆出什么（P82 ③）。"""
    rows = []
    for q in DATE_WRITINGS:
        facts, terms, _ms = memory.recall(q, limit=LIMIT, evidence=True)
        shown = kb_search.display_terms(terms, q, segment=memory.segment())[:SHOW]
        rows.append({"q": q, "n": len(facts), "shown": shown,
                     "num": kb_search._number_terms(q),
                     "partial": partial_shown(shown, q)})
    return rows


def in_corpus(memory, q: str) -> int:
    """这一串在**事实原文**里出现在几条上——ground truth，跟召回那条路无关。"""
    store, _vocab = memory._index()
    return sum(1 for f in store.facts.values() if q in (f.text or ""))


def measure(memory) -> dict:
    qs = queries(memory)
    rows = []
    for stratum, q in qs:
        facts, terms, _ms = memory.recall(q, limit=LIMIT, evidence=True)
        now = _shown(memory, terms, q, gaps=True)
        head = _shown(memory, terms, q, gaps=False)
        sq = kb_search.squeeze(q)
        gaps = kb_search.squeezed_gaps(q)
        toks = [kb_search.squeeze(t) for t in q.split() if kb_search.squeeze(t)]
        rows.append({
            "档": stratum, "q": q, "n": len(facts), "shown": now, "head": head,
            "unasked": [t for t in now if kb_search.squeeze(t) not in sq],
            "gap_head": [t for t in head if crosses_gap(t, sq, gaps)],
            "gap_now": [t for t in now if crosses_gap(t, sq, gaps)],
            "moved": head != now,
            # 打了的词一个都没摆出来（有召回才问——一条都没召回时那一行本来就该是空的）
            "token_miss": bool(len(facts) and now
                               and not any(tk in kb_search.squeeze(t) or
                                           kb_search.squeeze(t) in tk
                                           for tk in toks for t in now)),
            # 数字日期那一档多带两格（P81 ②）：库里到底有没有，以及**为什么**搜不到。
            # 别的档不算（`in_corpus` 要扫两万条事实，只在这 20 条上花这个钱）。
            "in_corpus": in_corpus(memory, q) if stratum == "数字日期" else None,
            "shape": numdate_shape(memory, q) if stratum == "数字日期" else None,
            # 屏幕上写的串 ≠ 用户打的串（P82 ③）
            "partial": partial_shown(now, q),
        })
    return {"rows": rows, "writings": date_writings(memory)}


# ------------------------------------------------------------------ 反例两头
#
# **任何「核对」先喂它一个该红 / 该绿的反例。** 这一组喂的是**假的 terms + 假的切词器**
# （同 `topic_spread_ruler` 喂假事实表），不需要真语料。
#
# 每一格两个期望：`want_now`（今天）和 `want_head`（把 `squeezed_gaps` 打成空集
# = 逐字退回 P79 ② 改之前那一版）。**两个不一样的那几格证明这一刀在动，
# 一样的那几格是对照**——真重叠跨空格、标点隔开、纯英文串，三种都不许被它动到。
# 绿有个数：6 格里有 3 格必须**两档相同**。
BATTERY: tuple[tuple[str, list[str], str, tuple[str, ...], list[str], list[str]], ...] = (
    ("空格隔开的两个词",
     ["广州", "深圳"], "广州 深圳", ("广州", "深圳"), ["广州", "深圳"], ["广州深圳"]),
    ("换行隔开的两个词",
     ["周一", "你好"], "周一\n你好", ("周一", "你好"), ["周一", "你好"], ["周一你好"]),
    ("三个词、只隔一个空格：只断那一处",
     ["众筹", "页面", "改版"], "众筹页面 改版", ("众筹", "页面", "改版"),
     ["众筹页面", "改版"], ["众筹页面改版"]),
    ("对照·没有空格：照合（P71 ① 那一刀）",
     ["众筹", "筹页", "页面"], "众筹页面", ("众筹页面",), ["众筹页面"], ["众筹页面"]),
    ("对照·真重叠跨过空格：照合",
     ["华为"], "华 为", ("华为",), ["华为"], ["华为"]),
    ("对照·标点隔开：本来就不相邻",
     ["众筹", "页面"], "众筹，页面", ("众筹", "，", "页面"), ["众筹", "页面"], ["众筹", "页面"]),
)


def _fake_segment(toks: tuple[str, ...]):
    """假切词器：`squeezed` 正好切成这几个 token，别的串按字切。**测试替身，不是新口径。**"""
    joined = "".join(toks)

    def seg(s: str):
        return list(toks) if s == joined else list(s)
    return seg


def run_battery() -> list[str]:
    bad = []
    same = 0
    for name, terms, q, toks, want_now, want_head in BATTERY:
        seg = _fake_segment(toks)
        got_now = kb_search.display_terms(terms, q, segment=seg)
        real = kb_search.squeezed_gaps
        kb_search.squeezed_gaps = lambda _q: set()
        try:
            got_head = kb_search.display_terms(terms, q, segment=seg)
        finally:
            kb_search.squeezed_gaps = real
        if got_now != want_now:
            bad.append(f"{name}（今天）: {got_now} ≠ {want_now}")
        if got_head != want_head:
            bad.append(f"{name}（改之前）: {got_head} ≠ {want_head}")
        if want_now == want_head:
            same += 1
    if same != 3:
        bad.append(f"对照那几格 {same} ≠ 3——**这组反例成了恒红或恒绿**")
    # `squeezed_gaps` 本身也喂三格该红该绿的
    if kb_search.squeezed_gaps("广州 深圳") != {2}:
        bad.append("squeezed_gaps('广州 深圳') 不是 {2}")
    if kb_search.squeezed_gaps("广州深圳") != set():
        bad.append("squeezed_gaps 对没有空白的串不该回东西")
    if kb_search.squeezed_gaps("  a  b ") != {0, 1}:
        bad.append("squeezed_gaps 对连着的空白 / 开头的空白判错")
    return bad


def check_source() -> list[str]:
    """**那一行还在不在源文件里**：这把尺量的得是今天在跑的那条路。"""
    root = BACKEND.parent
    kb = root / "frontend" / "src" / "components" / "kb" / "KbDashboard.tsx"
    bad = []
    if not kb.is_file():
        return ["找不到 KbDashboard.tsx——这把尺量的那条路可能已经不在了"]
    src = kb.read_text(encoding="utf-8")
    # **P81 ③ 之后这一行是两个标签**：有召回 → 「命中词：」，0 召回 → 「找过：」。
    # 三段都钉着：两个标签的字面 + 那个三元的判据。
    # （P79 那版钉的是 `"命中词：' + hits.terms.slice(0, 6)"` 一整串——这一批改了口，
    #   所以这里跟着改；`SHOW=6` 仍然由 `slice(0, 6)` 那一段钉着。）
    if "hits.terms.slice(0, 6)" not in src:
        bad.append("`KbDashboard` 里那一行不再 `slice(0, 6)`（这把尺的 SHOW=6 跟着废）")
    if "' · 命中词：' : ' · 找过：'" not in src:
        bad.append("那一行的两个标签变了——P81 ③ 那一刀（0 召回时改口「找过：」）不在了")
    if "hits.facts.length ?" not in src:
        bad.append("那一行不再按 `facts.length` 分两支——P81 ③ 那一刀不在了")
    if "recall(q, 20)" not in src:
        bad.append("`KbDashboard` 不再按 limit=20 召回（这把尺的 LIMIT 跟着废）")
    # P69 更正过的那一格：那一行仍然先看 `terms.length` 决定摆不摆（P81 ③ 只改了标签）
    if "hits.terms.length ?" not in src:
        bad.append("那一行不再先看 `terms.length`——P48 ③ / P69 / P81 那笔账要重读")
    import inspect
    import textwrap
    dt = textwrap.dedent(inspect.getsource(kb_search.display_terms))
    if "squeezed_gaps(query)" not in dt:
        bad.append("`display_terms` 里 P79 ② 那条守卫不在了")
    return bad


def main(argv: list[str]) -> int:
    bad = check_source() + run_battery()
    if bad:
        print("反例 / 源文件那一头对不上：" + "；".join(bad), file=sys.stderr)
        return 9
    print(f"ruler=kb-search user={USER} corpus={corpus_tag()} seed={SEED} show={SHOW}："
          f"反例 {len(BATTERY)} 格 + 3 格 gaps 全对上（有红有绿，对照那三格这一刀动不到）")

    if "--battery-only" in argv:
        return 0

    from app.database.kite.kite_memory import UserMemory
    m = UserMemory(USER)
    got = measure(m)
    rows = got["rows"]

    empty = [r for r in rows if r["n"] == 0]
    empty_line = [r for r in empty if r["shown"]]
    unasked = [r for r in rows if r["unasked"]]
    gap_head = [r for r in rows if r["gap_head"]]
    gap_now = [r for r in rows if r["gap_now"]]
    moved = [r for r in rows if r["moved"]]
    tmiss = [r for r in rows if r["token_miss"]]
    numdate_empty = [r for r in rows if r["档"] == "数字日期" and r["n"] == 0]
    missing_hit = [r for r in rows if r["档"] == "库里没有" and r["n"]]

    print(f"  {len(rows)} 条手打搜索词，字数中位数 "
          f"{sorted(len(r['q']) for r in rows)[len(rows) // 2]}")
    for stratum, _n in STRATA:
        g = [r for r in rows if r["档"] == stratum]
        print(f"    [{stratum:5}] {len(g):3} 条 · 0 结果 {sum(1 for r in g if r['n'] == 0):3}"
              f" · 0 结果还摆命中词 {sum(1 for r in g if r['n'] == 0 and r['shown']):3}"
              f" · 摆了没打的词 {sum(1 for r in g if r['unasked']):3}"
              f" · 跨空白合出来的（改之前）{sum(1 for r in g if r['gap_head']):3}")
    print(f"  **0 条结果还摆着那一行：{len(empty_line)} 条**"
          f"（P48 ③ 判过「今天 0 个用户看得见」，P69 更正为不成立，P79 第三次核实仍在摆；"
          f"**P81 ③ 落刀**：这 {len(empty_line)} 条今天的标签是「找过：」不是「命中词：」，"
          f"`--line` 打前后对比。**这个数本身没动**——摆不摆是一件事，摆的叫什么是另一件。）")
    print(f"  摆了用户没打过的词：{len(unasked)} 条")
    print(f"  跨空白合出来的词：改之前 {len(gap_head)} 条 → 改之后 {len(gap_now)} 条"
          f"；两版不一样的 {len(moved)} 条（**旋钮在动**）"
          f"  改之前那几条：{[r['gap_head'] for r in gap_head]}"
          f" → 今天 {[r['shown'] for r in gap_head]}")
    print(f"  打了的词一个都没摆出来：{len(tmiss)} 条")

    # ── 数字日期那一档的解剖（P81 ②，只加不改）────────────────────────────
    nd = [r for r in rows if r["档"] == "数字日期"]
    nd_in = [r for r in nd if (r["in_corpus"] or 0) > 0]
    nd_nochan = [r for r in nd if r["shape"] == "no_channel"]
    nd_notok = [r for r in nd if r["shape"] == "no_token"]
    nd_2d = [r for r in nd_notok if r["q"].isdigit() and len(r["q"]) <= 2]
    nd_date = [r for r in nd_notok if _DATE_UNIT.match(r["q"])]
    print(f"  ⚠️ 数字日期那一档 {len(numdate_empty)}/20 条 **0 结果**"
          f"——搜索框自己写着「数字、日期」。**P81 ② 量完判「不修」，账在台账。**")
    print(f"     库里真的有这一串的：{len(nd_in)}/20 条"
          f"（这一档本来就是从事实原文里长出来的——**有，但搜不到**）")
    print(f"     `_terms` 切得出、`plan` 没通道：{len(nd_nochan)} 条 "
          f"{[r['q'] for r in nd_nochan]}")
    print(f"     `_NUM` 连词都切不出来：{len(nd_notok)} 条"
          f"（两位数裸数字 {len(nd_2d)} {[r['q'] for r in nd_2d]}"
          f" · `月/号/日/年` 不在量词表里 {len(nd_date)} {[r['q'] for r in nd_date]}）")
    print(f"  「库里没有」那一档真有命中的：{len(missing_hit)} 条"
          f"（{[r['q'] for r in missing_hit]}）")

    # ── 屏幕上写的串 ≠ 用户打的串（P82 ③，量完判「不修」）──────────────────
    shown_total = sum(len(r["shown"]) for r in rows)
    partial = [r for r in rows if r["partial"]]
    wr = got["writings"]
    wr_shown = sum(len(r["shown"]) for r in wr)
    wr_partial = [r for r in wr if r["partial"]]
    print(f"  屏幕上一共摆出 {shown_total} 串，**「只摆了一截」{len(partial)} 条**"
          f"{[(r['q'], r['partial']) for r in partial]}")
    print(f"  那 {len(wr)} 种用户真会打的日期 / 数字写法：屏幕上一共只摆出 **{wr_shown} 串**，"
          f"其中只摆了一截的 {len(wr_partial)}"
          f"{[(r['q'], r['shown']) for r in wr_partial]}")
    print(f"     ⚠️ **`_number_terms` 切出来的那个截断串（`9月14日` → `9月14`）"
          f"在用户眼前一次都没出现过**——`recall()` 回的 `terms` 根本不收数字。"
          f"（P81 ② 记的那笔是 `_number_terms` 的产出，不是屏幕上那一行；P82 ③ 重量的。）")
    if "--writings" in argv:
        for r in wr:
            print(f"     打「{r['q']:11s}」_number_terms={str(r['num']):14s} "
                  f"屏幕 {str(r['shown']):20s} {r['n']:2d} 条结果")

    if "--line" in argv:
        # **用户眼前那一行，改之前 / 改之后**（P81 ③）。
        # 两个标签的字面**从 `KbDashboard.tsx` 里读出来**，不在这儿另抄一份——
        # 抄一份就是两把尺，产品改了口这儿还照旧印（P67 ② 那一课）。
        src = (BACKEND.parent / "frontend" / "src" / "components" / "kb"
               / "KbDashboard.tsx").read_text(encoding="utf-8")
        mm = re.search(r"\? '( · [^']+)' : '( · [^']+)'", src)
        if not mm:
            print("读不出那两个标签——`KbDashboard.tsx` 那一行的形状变了", file=sys.stderr)
            return 9
        hit_label, miss_label = mm.group(1), mm.group(2)
        print(f"\n  用户眼前那一行（标签从 `KbDashboard.tsx` 现读：命中={hit_label.strip()}"
              f" / 0 召回={miss_label.strip()}）：")
        for r in rows:
            if r["n"] or not r["shown"]:
                continue
            words = "、".join(r["shown"][:SHOW])
            print(f"    搜 {r['q']!r}")
            print(f"      改之前： {r['n']} 条结果{hit_label}{words}")
            print(f"      改之后： {r['n']} 条结果{miss_label}{words}")

    if "--list" in argv:
        for r in rows:
            print(f"    [{r['档']:5}] {r['q']!r:22} n={r['n']:3} 命中词={r['shown']}")

    bad = []
    if len(rows) != EXPECT_TOTAL:
        bad.append(f"条数 {len(rows)} ≠ {EXPECT_TOTAL}")
    if len(empty) != EXPECT_EMPTY:
        bad.append(f"0 结果 {len(empty)} ≠ {EXPECT_EMPTY}")
    if len(empty_line) != EXPECT_EMPTY_WITH_LINE:
        bad.append(f"0 结果还摆命中词 {len(empty_line)} ≠ {EXPECT_EMPTY_WITH_LINE}")
    if len(unasked) != EXPECT_UNASKED:
        bad.append(f"摆了没打的词 {len(unasked)} ≠ {EXPECT_UNASKED}")
    if len(gap_head) != EXPECT_GAP_MERGED_HEAD:
        bad.append(f"改之前跨空白 {len(gap_head)} ≠ {EXPECT_GAP_MERGED_HEAD}"
                   "——**旋钮没在动，这把尺量不到这一刀**")
    if len(gap_now) != EXPECT_GAP_MERGED_NOW:
        bad.append(f"改之后跨空白 {len(gap_now)} ≠ {EXPECT_GAP_MERGED_NOW}")
    if len(moved) != EXPECT_GAP_MERGED_HEAD:
        bad.append(f"两版不一样的 {len(moved)} ≠ {EXPECT_GAP_MERGED_HEAD}"
                   "——**动的那几条跟错的那几条不是同一批**")
    if len(tmiss) != EXPECT_TOKEN_MISS:
        bad.append(f"打了的词一个都没摆 {len(tmiss)} ≠ {EXPECT_TOKEN_MISS}")
    if len(numdate_empty) != EXPECT_NUMDATE_EMPTY:
        bad.append(f"数字日期档 0 结果 {len(numdate_empty)} ≠ {EXPECT_NUMDATE_EMPTY}")
    if len(nd_in) != EXPECT_NUMDATE_IN_CORPUS:
        bad.append(f"数字日期档库里真有的 {len(nd_in)} ≠ {EXPECT_NUMDATE_IN_CORPUS}")
    if len(nd_nochan) != EXPECT_NUMDATE_NO_CHANNEL:
        bad.append(f"数字日期档「没通道」{len(nd_nochan)} ≠ {EXPECT_NUMDATE_NO_CHANNEL}")
    if len(nd_notok) != EXPECT_NUMDATE_NO_TOKEN:
        bad.append(f"数字日期档「切不出词」{len(nd_notok)} ≠ {EXPECT_NUMDATE_NO_TOKEN}")
    if len(nd_2d) != EXPECT_NUMDATE_TWO_DIGIT:
        bad.append(f"数字日期档两位数裸数字 {len(nd_2d)} ≠ {EXPECT_NUMDATE_TWO_DIGIT}")
    if len(nd_date) != EXPECT_NUMDATE_DATE_UNIT:
        bad.append(f"数字日期档日期量词 {len(nd_date)} ≠ {EXPECT_NUMDATE_DATE_UNIT}")
    if len(missing_hit) != EXPECT_MISSING_HIT:
        bad.append(f"「库里没有」那一档命中 {len(missing_hit)} ≠ {EXPECT_MISSING_HIT}")
    for name, got_, want in (("摆出来的串数", shown_total, EXPECT_SHOWN_TOTAL),
                             ("只摆了一截", len(partial), EXPECT_PARTIAL_SHOWN),
                             ("日期写法摆出来的串数", wr_shown, EXPECT_DATEWRITE_SHOWN),
                             ("日期写法只摆了一截", len(wr_partial), EXPECT_DATEWRITE_PARTIAL)):
        if got_ != want:
            bad.append(f"{name} {got_} ≠ {want}")
    if bad:
        print("真库那一头对不上：" + "；".join(bad), file=sys.stderr)
        print("**这一刻 P79 ② 那几个数全部失效**——先查口径 / 语料，别换把尺继续量。",
              file=sys.stderr)
        return 9
    print("kb-search ruler OK（P79 ② 逐格相同）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
