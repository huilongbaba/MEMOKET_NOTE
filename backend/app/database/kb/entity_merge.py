"""实体合并的**候选生成**：纯代码、零模型调用、一次跑全量。

## 为什么要合并

实体页是**按事实数排序**的，而真库里那些数字全是真值的一部分（第 659 轮实测）：

    MemoCat（自家产品）  memo cat 93 + MemoCat 81 + MemoCad 15 = 189，列表上显示 93
    Anker               Anker 37 + 安克莱 37 + 安克 29 + 安科 6 = 109，显示 37
    惠龙（用户本人）      Hui Long / 慧龙 / 惠龙 / 汇龙 / Huilong 五份 = 31，显示 10

**一个按错的数字排的列表，排序本身就是错的。**

## 为什么是「一次全量后处理」而不是「增量」

用户定的（第 659 轮）。两条理由：

* 增量要维护「新实体 vs 已有全部」的状态，而合并结果会变得**跟实体出现的顺序有关**；
* 全量根本不贵：**候选生成不进 prompt**，是字符串 + 拼音比对，1239 个实体
  两两比 76 万对，代码几秒钟。贵的只有「让模型排序」那一步，而它喂的是
  筛完的几十对，不是全部实体。

所以这个模块的形状是：**给我全部实体，还你一份候选清单**。重跑一次就是一份新的。

## 三条信号，以及它们各自有多准（真库实测，247 个 ≥5 次的实体 → 97 对）

* `initials` 首字母缩写 —— `united states`~`US`、`Bill Browder`~`BB`：**2/2 全对**
* `translit` 音译 —— 中文转拼音跟拉丁串比：`安克`~`Anker`、`广州`~`guangzhou`、
  `德惠达`~`德威达`。**约七成**；错的长这样：`阿里巴巴`~`Ali Abdul`、`白老师`~`庞老师`
* `substring` 子串 —— `广州`~`广州市`、`安克`~`安克莱`。**约四成**；
  错的长这样：`pro`~`prod`、`plus`~`US`、`gemini`~`gem`

**四到七成远不够自动合并**，所以这个模块只出候选，不做决定。
试过而否掉的两个过滤条件也记在这儿，省得以后有人再试一遍：

* 「两个实体从不在同一条事实里出现」—— 候选里几乎全成立，**分不开真假**；
* 上下文分布余弦 ≥0.80 —— `安克`~`Anker` 确实排上来了，但同一档里还有
  `Donald Trump`~`Ukraine`、`gpt`~`apple`、`elisa`~`亚马逊`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .entities import norm_key
from .who import is_speaker_tag

# 事实数低于这个的不参与：上下文太少，而且它们本来就不影响列表顶部。
# 全量重跑时可以调低——这是速度和覆盖的取舍，不是正确性的取舍。
MIN_FACTS = 5

# 音译判同的门槛。0.62 是拿真库调的：再低就开始收 `阿里巴巴`~`Ali Abdul`，
# 再高就漏掉 `德惠达`~`德威达`。
TRANSLIT_MIN = 0.62

# 拉丁文之间的近似拼写。**比音译严得多**：同一套字母表里随便两个短词都很像，
# 而音译跨了字母表，本身就是个很强的巧合。0.85 是拿真库调的（见模块头）。
SPELL_MIN = 0.85

# 子串这条信号的两条闸门（见 `_pair` 里那段注释）。**一个汉字的信息量远大于一个字母**。
MIN_SUB_CJK = 2
MIN_SUB_LATIN = 5
MIN_SUB_RATIO = 0.5

_CJK = re.compile(r"[一-鿿]")
_SPLIT = re.compile(r"[\s_\-.·]+")


def has_cjk(s: str) -> bool:
    return bool(_CJK.search(s or ""))


def initials(s: str) -> str:
    return "".join(w[0] for w in _SPLIT.split(s or "") if w).lower()


def roman(s: str, pinyin=None) -> str:
    """中文转拼音、其它原样归一。`pinyin` 可注入（测试不依赖 pypinyin）。"""
    s = s or ""
    if not has_cjk(s):
        return norm_key(s)
    if pinyin is None:
        from pypinyin import lazy_pinyin      # KITE 已经带了这个依赖
        pinyin = lazy_pinyin
    return "".join(pinyin(s)).lower()


@dataclass(frozen=True)
class Candidate:
    """一对**可能**是同一个东西的实体。`why` 是哪条信号点出来的，`score` 是它有多像。"""

    a: str
    b: str
    why: str
    score: float
    facts_a: int
    facts_b: int

    @property
    def facts_total(self) -> int:
        return self.facts_a + self.facts_b


def _pair(a_name: str, b_name: str, pinyin=None) -> tuple[str, float] | None:
    na, nb = norm_key(a_name), norm_key(b_name)
    if not na or not nb or na == nb:
        return None
    if na in nb or nb in na:
        short, long_ = sorted((na, nb), key=len)
        ratio = len(short) / len(long_)
        # **子串是最弱的那条信号，门槛要高**。第一版只要「一个包含另一个」就算，
        # 于是 `app` 一个人配出 7 对（apple / zappos / whatsapp / AppLovin / AppStore /
        # Apple Watch / AppleWatch），`Ai` 配出 5 对（Gmail / Ukraine / hotmail…），
        # `US` 配出 4 对（Russia / plus / TrustCenter / Stanford Business School）。
        # 用户看到 `app ~ apple` 第一反应是「这怎么会是一个」——**对的，它不是**。
        #
        # 两条闸门，按字母表分开定：
        #   · 短的那个要够长才算得上证据。**一个汉字的信息量远大于一个字母**，
        #     所以中文 2 个字就够（安克 / 广州），拉丁要 5 个（app / gem / pro / memo 全挡掉）。
        #   · 短的要占长的大半：`安克`/`安克莱` 0.67、`广州`/`广州市` 0.67 是真的；
        #     `app`/`Apple Watch` 0.3、`Ai`/`Ukraine` 0.29 是巧合。
        min_len = MIN_SUB_CJK if (has_cjk(short) or has_cjk(long_)) else MIN_SUB_LATIN
        if len(short) >= min_len and ratio >= MIN_SUB_RATIO:
            return "substring", round(ratio, 3)
    if (len(na) >= 2 and na == initials(b_name)) or (len(nb) >= 2 and nb == initials(a_name)):
        return "initials", 1.0
    # 音译：一中一西比（安克~Anker），**两个中文之间也比**——同音不同字在真库里
    # 就是重复：`惠龙 / 汇龙 / 慧龙` 是同一个人（用户本人）、`德惠达 / 德威达` 是同一家。
    # 代价是会凑出 `白老师`~`庞老师` 这种，交给人一眼否掉。
    if has_cjk(a_name) or has_cjk(b_name):
        ra, rb = roman(a_name, pinyin), roman(b_name, pinyin)
        if ra and rb:
            r = SequenceMatcher(None, ra, rb).ratio()
            if r >= TRANSLIT_MIN:
                return "translit", round(r, 3)
    # 拉丁文之间的近似拼写：`MemoCat`~`MemoCad`、`Edo`~`Eddo`。
    # 门槛比音译高得多（0.85）而且要求够长——短词之间随便两个都很像。
    elif len(na) >= 4 and len(nb) >= 4:
        r = SequenceMatcher(None, na, nb).ratio()
        if r >= SPELL_MIN:
            return "spelling", round(r, 3)
    return None


def find_candidates(entities: list[tuple[str, str, int]], *, min_facts: int = MIN_FACTS,
                    pinyin=None, limit: int = 400) -> list[Candidate]:
    """`entities` 是 (code, 显示名, 事实数)。返回按「值不值得先看」排好序的候选。

    排序 = **涉及的事实数 × 信号可靠度**：先给 `MemoCat`（189 条）这种，
    用户点头一下就修好一大块；`pro`~`prod`（115 条但信号最弱）排后面。
    """
    # **说话人标签不参与**。它们不是实体（`speaker a` 是「谁说的」），而且彼此只差
    # 一个字母、事实数又最多——不挡的话候选表最前面 36 对全是 `Speaker A`~`Speaker B`
    # 这种，用户翻不到真正要看的那几对（第 659 轮读产出当场抓到的）。
    rows = [(c, n, f) for c, n, f in entities
            if f >= min_facts and (n or "").strip() and not is_speaker_tag(n)]
    weight = {"initials": 1.0, "translit": 0.8, "spelling": 0.7, "substring": 0.5}
    out: list[Candidate] = []
    for i, (ca, na, fa) in enumerate(rows):
        for cb, nb, fb in rows[i + 1:]:
            hit = _pair(na, nb, pinyin)
            if not hit:
                continue
            why, score = hit
            out.append(Candidate(a=ca, b=cb, why=why, score=score, facts_a=fa, facts_b=fb))
    out.sort(key=lambda c: -(c.facts_total * weight.get(c.why, 0.5) * c.score))
    return out[:limit]


def pair_key(a: str, b: str) -> tuple[str, str]:
    """一对的稳定主键——**跟谁在左谁在右无关**，不然同一对会被问两遍。"""
    return (a, b) if a <= b else (b, a)
