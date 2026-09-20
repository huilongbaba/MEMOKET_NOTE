"""Ranking for the zero-LLM recall.

**The defect this fixes, measured.** ``recall`` matched the query against the
codebook's vocabulary, then ran one query: *this topic's facts, sorted by
time, take the top 8*. There was no relevance ordering at any point -- given
a query about storage pricing it returned the eight most recent facts filed
under storage, whatever they said. Two things followed from that:

* the Chinese n-grams the module already computed were used only for a
  line-level fallback, never to search facts, so a Chinese query with no
  English words had exactly one usable channel;
* even when the symbolic channel hit -- it did on 83% of a 60-fact sample --
  the wanted fact came back only 26% of the time, because "most recent in
  this topic" is unrelated to "what the query asked".

Measured on 60 random facts from the real writing codebook, querying with a
fact's own text:

| | 召回自己 | 同主题命中 |
|---|---|---|
| before | 22% | 38% |
| after | **90%** | **97%** |

And on the harder variants, which are closer to how it is actually used --
a writing prompt is a fragment of a subject, not a fact quoted verbatim:

| | before | after |
|---|---|---|
| 只给前 40% 文本，能否召回该事实 | 15% | **88%** |
| 排除该事实本身，能否召回同主题的别的事实 | 33% | **53%** |

Still zero model calls, still a few milliseconds. The fix is two changes:
**cast a wider net** (a large candidate pool, and the CJK n-grams used as
fact-level greps rather than only as a fallback) and then **rank what comes
back by how much of the query it actually contains**, instead of by date.
"""

from __future__ import annotations

import re

from .who import is_speaker_tag

# How many candidates each channel contributes before ranking. Measured to
# saturate here: 400 gives 62% self-retrieval, 800 gives 63%, 1500 gives 63%.
POOL = 800

# Chinese n-grams promoted to fact-level greps. Four is where the measured
# gain lands; 8 and 12 change nothing and only cost query slots.
CJK_GREPS = 4

# English terms used the same way. Unchanged from the original.
WORD_GREPS = 3

# Total query slots handed to the plan executor.
MAX_QUERIES = 8


def plan(memory, query: str, vocab, *, pool: int = POOL, segment=None,
         common=None) -> list[dict]:
    """The queries whose union forms the candidate pool.

    Three channels, deliberately overlapping: symbolic (topics and entities
    resolved from the query), English lexical, Chinese lexical. Overlap is
    fine -- ranking sorts it out, and a channel that returns nothing costs
    nothing.

    `segment`（P38 #5）：给了切词函数，中文那个通道就拿**分词出来的实词**当 grep 词，
    不拿 2–3 字滑窗。P34 量过这一处、没接，理由是「自召回跌了 1–2 条，换来的
    四十来条变动要逐条读才知道值不值，这一批没那个预算」。P38 把那 37 条读完了，
    结论和账在 `kite_memory.recall` 那段注释里。**只在拿给用户看的那条路上给**
    （`recall(evidence=True)`），候选池那条路不给——见那段注释里 N4 那个绿点。

    `common`（P42 A2）：跟着 `segment` 一起给，作用见 `_cjk_greps`。同一个闸，
    不另开一个——**一个闸别管所有调用方**在这条线上栽过三次（P32 / P34 / P38）。
    """
    topics, entities, _surfaces = memory._match_vocab(query, vocab)
    # 查询里认出的实体扩到同一组的所有写法：问「MemoCat」也要拿到挂在 memo_cat 上的事实（kb/entities.py）
    if entities and hasattr(memory, "_index"):
        try:
            from . import entities as entities_mod
            store, _ = memory._index()
            g = entities_mod.for_store(store, vocab)
            entities = list(dict.fromkeys(m for e in entities for m in g.members(e)))
        except Exception:      # noqa: BLE001 — 假的 memory / 没索引就按原样
            pass
    queries: list[dict] = []
    if topics or entities:
        queries.append({
            "select": "facts",
            "where": {"topics": topics, "entities": entities},
            "pipe": [{"op": "sort", "key": "t", "desc": True},
                     {"op": "head", "n": pool}],
        })
    # grep 的英文词也先剔虚词 / 说话人标签：英文事实前三个候选词常常是 it / speaker a / says，
    # 三个 grep 槽全浪费在它们身上，事实根本进不了候选池（第 527 轮自召回三条 miss 都不在池里）
    words = [t for t in memory._candidate_terms(query) if t.lower() not in _EN_STOP and not _is_speaker_word(t.lower())]
    for term in (words or memory._candidate_terms(query))[:WORD_GREPS]:
        queries.append({"select": "facts", "where": {"grep": term},
                        "pipe": [{"op": "head", "n": pool}]})
    # **The change that mattered most.** These n-grams were being computed
    # and then used only against raw lines when everything else had already
    # failed. Searching facts with them is what took same-topic recall from
    # 38% to 97%.
    for gram in _cjk_greps(memory, query, segment, common):
        queries.append({"select": "facts", "where": {"grep": gram},
                        "pipe": [{"op": "head", "n": pool}]})
    return queries[:MAX_QUERIES]


def _cjk_greps(memory, query: str, segment, common=None) -> list[str]:
    """中文通道拿哪几个词去 grep：滑窗（默认）还是分词出来的实词（P38 #5）。

    滑窗那份是「先 3 字后 2 字」，分词这份**按长度从长到短**取前 `CJK_GREPS` 个，
    同一个意思：长的那个更能把候选池收窄到真的相关的那几条。
    口水词 / 单字不算（`_is_cn_filler`）——它们当 grep 词等于不筛。
    切不出来（分词器没启用、或者这段里没有实词）就**原样退回滑窗**，不留空手。

    **`common`（P42 A2）：`_is_cn_filler` 挡的是口水词那张固定表，`common` 挡的是
    「在这个人的库里满库都是」的那一档**（`UserMemory.common_term`，df ≥ 6%）。
    后者原来只接在 `qualifies` / `_weigher` 两层上，取 grep 词这一处没接。
    全库量过（765 条查询）：接上之后 **4 条查询的 top-8 变了，掉 2 对 / 进 2 对**，
    四条**逐条读过**——进的两条是 `商业找人` 那条逐句对应的事实，掉的两条是
    `比如我`+`这个功能`（泛词各撞一次）和 `000`+`用户的`（数字碎片）。
    **0 条变差**；47 条抽样一条没动；「留下率不许跌」四栏里三栏逐条相同、
    同主题自召回 67 → 68。

    **P38「留给下一批」③ 那句话说错了一半，记在这儿**：它写的是
    「`希望通过` / `成功经验` 这类泛词靠 `common_term` 挡」——实测 `common_term`
    **认不出它们**（`希望` / `通过` / `成功经验` 在这个人 2362 个 unit 上的 df 都到不了 6%）。
    它认出来的是 `自己` / `一个` / `还有` / `之后` / `时候` / `包括` / `三个` 这一档。
    所以这一刀买到的是另外 4 条，**P38 点名那 9 条一条都没治**——
    那一类得换量程（`kb-entities-plan §17`）。

    **泛词剔光了要退回去**，跟「切不出实词退回滑窗」同一个理由：一段全是泛词时
    整条中文通道空手 = 把这条召回判死。先退回「只剔口水词」那一版，再退回滑窗。
    """
    grams = memory._cjk_terms(query)[:CJK_GREPS]
    if segment is None:
        return grams
    plain: list[str] = []          # 只剔口水词（P38 #5 那一版）
    words: list[str] = []          # 再剔「满库都是」的（P42 A2）
    for t in segment(_WS.sub("", (query or "").lower())):
        if len(t) >= 2 and _ALL_CJK(t) and not _is_cn_filler(t) and t not in plain:
            plain.append(t)
            if common is None or not common(t):
                words.append(t)
    keep = words or plain
    if not keep:
        return grams
    keep.sort(key=lambda w: -len(w))
    return keep[:CJK_GREPS]


# ---------------------------------------------------------------- P60 A：取词那一层，量完的账
#
# P57 把 `603dca25403a` 那篇「五轮 × 8 种 query 组合全部空手」的根因钉在
# 「`_cjk_terms` 挑 grep 词那一层」，并写下「要做就单独一批带全库对拍」。
# P60 量完了，**那句归因是错的**，改正写在这儿，省得下一批照着挖。
#
# ## 先量今天（真语料 `corpus=11429185B/403a1183`，765 条去重查询，P34 那把尺）
#
# `_cjk_terms` 有**两个**调用方，量程差 4 倍，P57 只点了第一个：
#
# | 处 | 名额 | 决定什么 | 拿到的是不是「整词」 | 一个整词都没有的查询 |
# |---|---:|---|---|---:|
# | ① `plan` → `_cjk_greps` | **4** | 候选**进不进得来** | 361/3006 = **12.0%** | **469/765** |
# | ② `rank` → `_terms` → `_hits` | **16** | 候选**留不留得下** + 面板「命中：」 | 1482/11374 = **13.0%** | 135/765 |
#
# （「整词」= 这个串正好是分词器在**这条查询上**切出来的一个 token；判据宁可窄。
#  ②那一栏还有一个更难看的数：分词切出来的实词 **96.2% 根本没当上查询词**，
#  402/765 条查询撞上 `_cjk_terms` 那个 **16** 的上限。）
#
# ## `603dca` 的真根因：不在 ①，在 ②
#
# 把那一篇的候选池剖开（`<scratch>/p60/why603.py`，五轮各跑一遍）：
#   · 池子**不空**——r1 滑窗 88 条 / 分词 81 条；
#   · `rank` 之后 **0**；
#   · **把人手写的实词（中介 / 报价 / 成交 / 卖房）直接当 grep 名额塞进去，池子 37 条，
#     排完还是 0**。
# 也就是说：**这一层就算给它一副完美的牌，结果一个字都不会变。**
# 往下一层数（`rank603.py`）：37 条里 35 条是「一个查询词都没命中」——
# 因为 `_terms` 拿到的 14 个词里**没有** `中介` / `报价` / `成交` / `卖房`：
# 那 16 个名额被「每个句段头三个字」轮转吃光了，而这些词在句子中段。
#
# ## 于是「接不接、接在哪」有了答案：**这一批一个字没改**
#
# · **接在 ①（`plan`）**：P38 #5 已经接了，只接在 `evidence=True` 那一列。
#   P60 补量了**第三条路**——写作取材料（`kb/recall.recall_clustered`，`evidence=False`）：
#   给它单开一个 `word_greps` 开关之后，P53 那 5 篇 20 轮的 grep 词 **20/20 轮全变了**
#   （旧 `['看清分','而是一','记录','最终产']` → 新 `['未命名','一般性','文字','分散']`，
#   `knobproof60.py` 钉死旋钮真的在开火），而**进 prompt 的材料 0/20 轮变化**。
#   **旋钮证明了自己在动，动完产出一模一样**——那就不要这个旋钮（已退回）。
# · **接在 ②（`_terms`）**：量过，**不能在这一批接**（`tryterms60.py`，765 条查询）：
#   「补」765 条里 **509 条 top-8 变了**、召回对 1282 → **2811（+119%）**；
#   「换」**489 条变了**、1282 → **2694**。这不是一刀，是把召回整体放松一倍。
#   而且有个更硬的理由：`_strong_enough` 要求「合出来的串里至少一条 ≥3 字」，
#   这个量程是**给滑窗定的**（3-gram 对上 = 两个窗口都对上）；中文**词**大多是 2 个字，
#   换成分词之后同一个阈值说的完全是另一件事——**先换量程，再谈接线**（P34 那一课）。
#
# ## P57 那句「材料都在」：读完 37 条，一半不算数
#
# 天花板那 37 条逐条读过并进了 `tests/fixtures/memory_sample.jsonl`（`set=p60-ceiling37`）：
# **hard 11 / meh 3 / bad 23**。`中介` / `报价` / `成交` 在这个库里大量落在
# **采购报价、供应商绳子报价、facebook 广告中介、留学中介、保险销售**上，跟卖房无关。
# 所以「够着了」也只有三成能用，剩下的正是 `_strong_enough` 存在的理由。
# **`603dca` 空手的代价比 P56/P57 估的小**，而代价大的是把它救回来要付的那一倍召回。


# 拿正文当查询之前要剥掉的东西（跟前端 util/wordCount.stripForRecall 同一条规则，
# scripts/check-regex-parity 对拍）：引用标记里的 id、整条图片、链接地址（只留链接文字）。
# 实拍：拖一张图进空笔记，右栏立刻冒出 Bill Browder / Russia 的英文事实——查询词就是那行
# `![probe](/api/assets/…png)`，「assets」撞上了「assets of Russia frozen」。
# 前端在发请求前剥过一遍，但**后端自己也拿正文查**（选中校验 compose、摄入冲突扫描 inbox、
# 写作取材料），那几条路原来是带着标记去查的（第 566 轮）。剥两次幂等，两边都留着。
_IMG_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_MD = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_CITE_MARK = re.compile(r"\[[A-Za-z][\w-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+\]")
# `<|start|>` 这种转写残留的乱码（P4 表 A #3）：`start` 被当成英文查询词，8 条候选全是 start-up。
_GARBAGE = re.compile(r"<\|[^|>]*\|>")


def clean_query(text: str) -> str:
    s = _IMG_MD.sub("", text or "")
    s = _LINK_MD.sub(r"\1", s)
    s = _CITE_MARK.sub("", s)
    s = _GARBAGE.sub(" ", s)
    return re.sub(r"[ \t]{2,}", " ", s)


def _terms(memory, query: str, weigh=None) -> list[str]:
    """查询词，去重、小写。英文候选词本来就是小写的，而模型抽出来的事实里 EVT / PCBA /
    APP 是大写——之前排序用大小写敏感的 `in` 比，英文词对这些事实永远不得分（第 191 轮
    真库实测：「4月16日的EVT准备4台主机…」召回不到「EVT 的大节点是 4 月 16 号」）。
    'evt' 出现两次也会算两次分，一并去重。

    **`weigh` 是取词那一层的排序依据（P65 ①）**，`_weigher(query, segment, common)` 的返回值
    原样往下递——`_cjk_terms` 那 16 个名额先给实词、再给滑窗碎片。**不给就是原样**
    （`matched_terms` 那条路今天不给，行为逐字不变）。"""
    out: list[str] = []
    for t in memory._candidate_terms(query) + memory._cjk_terms(query, weigh) + _number_terms(query):
        t = (t or "").lower()
        if t and t not in out:
            out.append(t)
    # 英文虚词和「speaker a」这种说话人标签不当查询词：英文事实几乎每条都是「Speaker B says …」，
    # 这些词一人一分把真正的内容词稀释掉——第 527 轮自召回复测三条 miss 全是这个样子
    # （terms= ['it', 'speaker a', 'speaker', 'says', 'can', …]）。全是虚词时退回原样，别搜不出东西。
    kept = [t for t in out if t not in _EN_STOP and not _is_speaker_word(t)
            and not _is_cn_filler(t)]
    # 全被剔光时怎么办，**分两种情况**（第 747 轮真库量出来的）：
    # · 查询很短（用户主动在搜「总结」这种词）→ 退回原样，别搜不出东西（第 527 轮那条）；
    # · 查询是一长句（跟着正文自动召回、或者一句任务指令）→ **就该什么都不返回**。
    #   实测「帮我总结一下」在两万条的真库里得分 **20**，比真正相关的命中（8 分）还高——
    #   因为整句口水话在会议记录里原样出现，还被切成 8 个重叠片段叠加。
    #   这种时候捞回来的每一条都是噪声，**宁可空着**。
    if kept:
        return kept
    return out if len(query.strip()) <= _SHORT_QUERY else []


# 这张表跟 `kb/relations._terms` **共用**（改它同时动召回排序和关系判据的 `overlap`，
# 所以 P27 没敢顺手补，留给了 P29 单独量）。
#
# **底表 = NLTK 的 english 停用词表**（179 条），不是谁手上顺口的那份（P29 #2 逐条对过：
# `<scratch>/p29/enstop29.py`）。第三块是这个库特有的：英文内容全是**访谈转写**，
# 「Speaker B says / talks / thinks / knows / wants …」几乎每条事实都有，
# 它们在标准表里不是虚词，在这个库里是脚手架（第 527 轮量的）。
#
# **P29 #2 补的三类，每类的理由**：
# · **`don` `doesn` `didn` `isn` `wasn` `haven` `wouldn` `shouldn` `couldn` `aren` `re` `ve` `ll`
#   （加上库里还没出现的 `hadn` `hasn` `weren` `mightn` `mustn` `needn` `shan` `ain`）——
#   **这些压根不是词**：`_EN` 的 `[A-Za-z][A-Za-z0-9_-]{1,}` 不收撇号，于是 `don't` 切成
#   `don` + `t`、`you're` 切成 `you` + `re`、`I've` 切成 `ve`。真库上 `re` 出现在 83 个 unit
#   （3.5%）、`don` 84 个——**一个转写库里最常见的「词」之一是个标点事故**。
#   （`re-email` / `re-registered` 这种带连字符的整词不受影响：`_EN` 把它们切成一个词。）
# · **反身 / 物主代词** `him` `himself` `herself` `hers` `itself` `myself` `ourselves`
#   `yourself` `yourselves` `themselves` `ours` `yours` `theirs`，和 **be / do 的剩余形式**
#   `am` `doing`——表里本来就有 he/she/his/her/they/them/we/us/our/is/are/do/does/did/done，
#   漏的这些是同一类，纯粹是当初手写漏了。
# · **介词 / 连词 / 限定词** `through` `between` `while` `until` `during` `once` `above`
#   `below` `further` `nor` `same` `own`，外加 **`yet`**（P27 #2 点名的那条）。
#   `yet` 不在 NLTK 表里，但它跟表里**已经有的** `still` / `already` / `ever` / `never`
#   是同一类语篇副词——漏的是它，不是它那一类。
#
# **逐条读过之后没补的两个**（这一步是必须的，不能照着标准表抄）：
# · `won`——标准表里它是 `won't` 的左半截，可真库 15 条里 **8 条是实义动词**
#   （「I won a silver medal」「Speaker B won the third prize」，用户孩子的获奖记录）。
#   补它等于把这 8 条的关键词剔掉。代价是 `won't` 仍然会留下一个 `won`，认了。
# · `ma`——标准表里是 `ma'am`，这个库里 4 条全是中文合同的「MA 条款」。
_EN_STOP = frozenset("""
a an the it its is are was were be been being can could will would shall should may might must
they them their he she his her we us our you your i me my this that these those there here
have has had having do does did done not no yes but and or so if then than too very really just
also about after before again against all any because both each few for from into of on off over
under to up down out with without at by as in what which who whom when where why how
say says said saying talk talks talking know knows knew think thinks like likes want wants
now later still already only ever never always some more most much many other another such
am doing him himself herself hers itself myself ourselves yourself yourselves themselves
ours yours theirs through between while until during once above below further nor same own yet
don doesn didn isn wasn haven wouldn shouldn couldn aren hadn hasn weren mightn mustn needn
shan ain re ve ll
""".split())


# 查询里的**指令 / 口水词**。只放两类：中文虚词，和「帮我 / 写一个 / 总结一下」这种
# **任务脚手架**。**不放领域词**——「需求」「功能」「产品」「目标用户」在这个库里是真内容，
# 剔掉它们等于把用户真正想查的东西也剔了（第 747 轮定这条边界时先量后定）。
_CN_FILLER = frozenset("""
的 了 在 是 和 与 及 或 把 被 对 到 从 这 那 就 也 都 还 又 很 不 没 有 个 着 过 为 以 及
我 你 他 她 它 我们 你们 他们 咱们 自己 什么 怎么 怎样 如何 为什么 哪些 哪个 多少
帮我 帮忙 请 麻烦 一下 一个 一些 这个 那个 这些 那些 现在 然后 所以 因为 但是 而且
写 写一 写一个 生成 做一 做一个 整理 梳理 总结 概括 归纳 列出 给出 给我 看看 说说
一下子 一点 可以 能否 是否 需要注意
""".split())


_FILLER_CHARS = frozenset("".join(_CN_FILLER))


def _is_cn_filler(t: str) -> bool:
    """`t` 是不是纯指令 / 口水词。

    CJK 查询会被切成**重叠的 n-gram**（「帮我总结一下」→ 帮我总 / 我总结 / 总结一 /
    结一下 …），而这些片段**跨在两个口水词之间**，整词比对抓不住
    （第 747 轮第一版就是这么漏的：剔完还剩 6 个片段，分数照样 20）。
    改成**按字符**判：整个片段的字全来自口水词表才算口水。
    「需求文」不会被误伤——需 / 求 / 文 都不在那张表的字里。
    """
    if t in _CN_FILLER:
        return True
    return bool(t) and all("\u4e00" <= c <= "\u9fff" and c in _FILLER_CHARS for c in t)


# 字符数：比这短才当成「用户主动搜的词」，剔光了退回原样。
# 主动搜的词一般就 2–4 个字（众筹 / 订金 / DVT）；「帮我总结一下」是 6 个字的**句子**，
# 第一版门槛设成 8，它正好落进兜底里，剔了等于没剔（第 747 轮量出来的）。
_SHORT_QUERY = 4


def _is_speaker_word(t: str) -> bool:
    """「speaker a」「说话人 2」走 who.is_speaker_tag（跟前端 kbNoise.SPEAKER_TAG 同一条正则），光秃秃的「speaker」也算。"""
    return t in ("speaker", "说话人", "发言人") or is_speaker_tag(t)


_NUM = re.compile(r"\d+月\d+|\d+(?:\.\d+)?[台套个件人次轮版元万亿%]|\d{3,}(?:\.\d+)?")


def _number_terms(query: str) -> list[str]:
    """数字也是查询词。英文候选词只认字母、中文候选词只认汉字，「4月16日的 EVT 准备 4 台
    主机和 15 套 PCBA」里最有区分度的 4月16 一分都不算，结果排在前面的全是提到 PCBA
    的别的会（第 191 轮真库实测）。光秃秃的一两位数太常见（「15」把「5 月 15 号」「15 分」
    全拉进来）：只认「月+日」、带量词的（15套）、三位以上的（380mAh 里的 380）。比对时两边都去掉空白（事实原文写成「4 月 16 号」）。"""
    return _NUM.findall(_WS.sub("", query))


_WS = re.compile(r"\s+")


def _hits(terms: list[str], text: str) -> list[str]:
    """查询词里哪些真的出现在这条事实里。ASCII 词按整词匹配（`md` 不能靠 SMDowner / B2ECMD
    得分——第 224 轮实拍拖一篇 .md 进来右栏全是不相干的英文事实；`ai` 不能靠 said 得分），
    比对时保留空格；中文 n-gram 和数字去空白后子串匹配（事实原文写成「4 月 16 号」）。"""
    low = (text or "").lower()
    squeezed = _WS.sub("", low)
    out = []
    for t in terms:
        if t.isascii() and t[0].isalpha():
            if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", low):
                out.append(t)
            elif len(t) >= 6 and t in squeezed:
                # 够长的词去掉空格再比一次：「memocat」要能命中写成「memo cat」的事实（第 293 轮）；
                # 六个字母以下不这么比，免得 md / api 这种撞回来
                out.append(t)
        elif t in squeezed:
            out.append(t)
    return out


def _clusters(hits: list[str]) -> list[str]:
    """命中的词里**互不包含**的那些：「华为」「华为的」是同一个词，「ui」「uiux」也是。
    P4 #6：查询退化到一个泛词（`记录`）时，5 条候选各自只靠这一个词得分——
    「至少命中 2 个不同内容词」要按这个数，不按 n-gram 片段数。"""
    hs = sorted(set(hits), key=lambda h: (-len(h), h))
    out: list[str] = []
    for h in hs:
        if not any(h in o for o in out):
            out.append(h)
    return out


# 自动召回（拿一段正文当查询）跟用户主动搜一个词不是一回事：查询 ≥ 这么多字就按「长查询」对待——
# 每条候选至少命中 2 个不同的内容词、且不能全靠 ≤2 字的碎片，不够就宁可空着（P4 #6：N5 末段只剩
# `记录` 一个词，凑出 Vlog / 日志 5 条不相干的；N3 末段讲学位，5 条全是 `ui`）。
LONG_QUERY = 100
LONG_QUERY_MIN_WORDS = 2

# 「这一条够硬」的那个量（P61 #1）。**换的是量程，不是阈值**——跟 P34 给 `_why` 换量程
# 是同一件事，这里把那一课用在 P4 立的这道门上。
#
# **P4 那个「≥3 字」是给滑窗定的**：`_cjk_terms` 的窗口最长 3，合出 3 个字意味着
# 两个窗口都对上了，不像是一个窗口撞出来的。可**中文词大多是 2 个字**，
# 于是分词切出来的**真词**——`华为` / `芯片` / `周敏` / `手环` / `合规` / `记忆`——
# 一个都过不了这道门。P60 量到头的那句「取词那一层已经量到头了」说的就是这里：
# 给上一层塞再好的牌，牌到了这道门前照样被字数挡回去。
#
# 换完之后问的是真正要问的那一句：**这一串在查询的分词里整词覆盖了几个字的实词**
# （`tokenize.content_chars`，跟 `_why` / `_weigher` **同一个函数、同一份口径**，
# 不另起一把尺子）。门槛 `STRONG_CJK_MIN = 2` = 「至少盖住一个实词」，
# 这正是 P4 那句「不能全靠 ≤2 字的碎片」在词这个量程上的原话——
# 碎片的实词字数是 **0**（`用户的` / `可以实` / `的数据` 全是 0），一个真词是 2。
#
# **门槛为什么不是 3 / 4**（全库 765 条量过，grid 在台账 P61 #1）：
# 实词字数 ≥3 会让 513/1086 串次**掉**资格、top-8 变 36 条里 **14 条整条变空**、召回对 1282 → 1245；
# ≥4 更狠（613 掉）。**那不是换量程，那是顺手把门抬高两档。**
#
# **`None` 那一档退回的是原样的 `len(h) >= 3`，不是新门槛**：`_weigher` 对英文 /
# 数字串一律回 `None`，拿 2 去套它就是**顺手把英文那一档从 3 降到 2**，而 P32 量过，
# 撞词的重灾区正是**两个字母**那一档（`ai` / `ui` / `os` / `md` / `pr`）。
# **第一版就是这么栽的**：24 条变动里一度混进 6 条全靠 `ui` / `os` 撞进来的
# （教室方案的项目表召回一屏 UI 设计讨论），逐条读的时候当场抓到。
# 这一行是**接线**，`test_p61` 单独钉了一条。
STRONG_CJK_MIN = 2


def _strong_enough(hits: list[str], query: str = "", segment=None, common=None) -> bool:
    """长查询（自动召回）那道门：至少两条不同的证据串，而且**至少一条站得住**。

    `segment` / `common` 由调用方注入（同 `qualifies` / `_why`）。**不给就是原样**
    ——`evidence=False` 那条路（候选池 / 写作取材料 / 关系判据）今天不注 `segment`，
    于是它在这条路上逐字等于 P4 那一版。「候选池宁可宽」那条没被这一批动过。
    """
    cl = _clusters(hits)
    if len(cl) < LONG_QUERY_MIN_WORDS:
        return False
    weigh = _weigher(query, segment, common)
    for h in cl:
        n = weigh(h) if weigh is not None else None
        if n is None:
            if len(h) >= 3:          # 英文 / 数字 / 定位不到：原样那把尺
                return True
            continue
        if n >= STRONG_CJK_MIN:
            return True
    return False


# ------------------------------------------------------------ 证据资格（P32 #1）
#
# **这一条修的是什么。** P31 实拍：正文「先把叙事和体感分开看，**再决定**这个动效要不要保留」，
# 右栏给出「Speaker B 问是否可以搜一下…然后根据情况**再决定**」，面板老老实实写着「命中：再决定」。
# **它说对了自己在干什么，干的这件事本身是错的**——那条召回的全部依据是一个 3 字滑窗
# （`_cjk_terms` 的窗口最长就是 3），而 `再决定` 跨在「再」和「决定」之间，根本不是一个词。
# P27 / P29 把**圆点**那侧（`kb/relations.detect`）收紧过两轮，召回这侧一直没跟着收。
#
# **跟那两轮的关系：同一套思路，不是同一条判据。**
# · P27 的 `evidence_runs` 是**按位置合并**证据串（重叠才合、相邻不合）——这里原样借过来，
#   因为召回这侧有一模一样的毛病：`_clusters` 的「互不包含」去重挡不住 `池容量` + `电池容`，
#   那是**同一个词「电池容量」被切成的两半**，却被 `_strong_enough` 数成两条证据。
# · P29 的 `common_term` 是**按 df 否掉资格**——这里也原样借过来当第一道闸（`ai` / `app` /
#   `第一` / `时间` 这种满库都是的词不算证据）。
# · **但 df 单独救不了 P31 那条**：`再决定` 在真库里 df=1，是个「稀有词」。
#   P27 早就写过「**『泛』是语义上的泛，不是字面上的常见**」。所以这一批加的是第三样东西——
#   **只剩一条证据串时，那条串得站得住**：
#     ① 它是**这个人词表里的表层词**（实体 / 主题），或
#     ② 它是 **≥4 个汉字**的串——`_cjk_terms` 最长的窗口是 3，合并出 ≥4 个字意味着
#        **两个窗口都对上了**，不可能是一个窗口撞出来的（P27 的 `LONG_RUN_CHARS` 同款理由，
#        只是那边的窗口是词元、门槛 5，这边的窗口是 3 字滑窗、门槛 4），或
#     ③ 它是 **≥3 个字母**的英文整词（英文本来就是整词切的，滑窗那个毛病它没有；
#        撞词的重灾区是**两个字母**那一档：`ai` / `ib` / `pr` / `mp` / `md` / `kv` / `sg`）。
#   **纯数字串（`90%` / `200` / `380`）永远不单独算证据**——P7 #5 早定过「一个词 + 同一天」
#   分不开「2月1号上线」和「2月1号发工资」；实测三条误判（病理诊断 90% / 交通 90% / ICT 90%
#   全都沾上「AI 写的代码现在 90% 以上」）的全部依据就是那个 `90%`。数字要配一个词才算数。
#   **再严一档（「只要含数字就不单独算」，那样 `3月15` / `10台到` 也进不来）量过、没要**：
#   全库只多砍 5 对，逐条读下来 3 条是撞的（`10台到货` 撞 `10台到20台`）、**2 条是真的**
#   （「3 月 15 日媒体及投资人版本」对上「2.0 版本…2026年3月15日」）。**误伤比漏报贵，不换。**
#   「是不是实体」在 P29 被否掉过，那是因为**它当时是唯一的闸、盖在所有对上**，
#   连 `cpu+npu` / `第二款产品` 这种真沾边一起砍（6/28）。这里它只当**单串那一档的放行条件**，
#   从不用来否掉任何东西——泛词那一关已经先过了。**判据宁可窄。**
#
# **量出来的**（全库 767 条自动召回查询 / 1888 对，抽样 47 对逐条读，见台账 P32 #1）：
# 「硬」16 → 14、「不硬」27 → 6（误判率 57% → 27%）。
# 汉字门槛 **4 比 5 好**：5 会多砍一条「硬」，一条「不硬」都不多砍。
# 英文门槛 **3 比 4 好**：4 只多砍 1 条标注过的「不硬」（`get`），代价是全库多砍 44 对，
# 里头 `ict` ×27 / `cpu` ×6 / `erp` ×5 都是这个库里实打实的专业词——**误伤比漏报贵**。
EVIDENCE_CJK_MIN = 4
EVIDENCE_EN_MIN = 3


def evidence_runs(hits: list[str], query: str) -> list[str]:
    """命中的词在**查询里**合并出来的证据串。**重叠才合、相邻不合**（同 P27）。

    相邻不合是有理由的：「成本高」紧跟着「效率低」是两个词，合成一串会把两条证据压成一条；
    反过来 `池容量` 和 `电池容` 重叠，它们是同一个词，不合就会被数成两条。

    **同一串在查询里出现两次只算一条**（P34 #2 读产出当场抓到的）。这里原来是按
    **位置**收的，于是「前提是」在查询里出现两次就回两串，`qualifies` 的
    `len(ev) >= 2` 当场放行——实拍：正文「先回答读者会追问的『为什么现在写』和
    『**前提是**什么』。**前提是**我承认在产品叙事上过度理想化」对上库里
    「你的第一步踩踏实的**前提是**你底层的逻辑…」，**全部依据是一个语篇词，被数成了两条**。
    `pro` 那条更夸张，一个词数出 6 条。
    **这是 P27「那个 2 数的是同一个词被切成的两半」的第三个变种**：
    P27 是一个词被切成两半，P32 是两个滑窗重叠，这次是同一个词出现两次。
    位置在这里的用处只有一个——把重叠的滑窗并起来；并完之后**证据是词，不是位置**。

    **第四个变种（P38 #2，逐条读 83 条时当场抓到的）：合并会把包含关系重新造出来。**
    `_clusters` 的「互不包含」去重是在**合并之前**做的，而合并按位置走：
    「…追问的『为什么现在写』和『**前提是**什么』。**前提是我**承认…」里，
    `前提是` 在第一处、`前提是我` 在第二处，两处不重叠，于是并完回两串——
    可 `前提是` 整个落在 `前提是我` 里面，**它不是第二条独立证据**。
    所以并完之后**再去一次包含**。全库量过：有包含关系的只有 8 对
    （`商业找人`/`找人`、`一方面`/`另一方面`、`950 超节点` 那一串…），
    其中**只有这 1 对**会因此从「放行」变成「砍掉」，别的 7 对本来就还有别的合格证据。
    **判据宁可窄：这一刀只切它该切的那一条。**
    """
    squeezed = squeeze(query)
    spans: list[list[int]] = []
    loose: list[str] = []
    for h in _clusters(hits):
        found = False
        start = 0
        while True:
            i = squeezed.find(h, start)
            if i < 0:
                break
            spans.append([i, i + len(h)])
            found = True
            start = i + 1
        # 在查询里定位不到的（`_hits` 的「去空格再比一次」那条路、或者调用方自己塞进来的词）
        # **各自算一串**，不要静默丢掉——丢掉等于把这条召回判死，那是最贵的那种错。
        if not found:
            loose.append(h)
    spans.sort()
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a < merged[-1][1]:          # 严格重叠才合
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out: list[str] = []
    for r in [squeezed[a:b] for a, b in merged] + loose:
        if r not in out:
            out.append(r)
    # 并完再去一次包含（见上面「第四个变种」）。按原顺序留下长的那条。
    return [r for r in out if not any(r != o and r in o for o in out)]


def _why(run: str, attested, weigh=None) -> str:
    """这条证据串**凭什么**算证据：`vocab` / `span` / `pair`（`pair` = 单独不够硬）。

    `weigh(串) -> int | None`：这一串在查询的**分词**里整词覆盖了几个字的实词（P34 #1）。
    `None` = 这一层没启用、或者这一串在查询里定位不到——两种都退回 P32 的原始字数，
    **不启用就是原样**。
    """
    if attested is not None and attested(run):
        return "vocab"
    if run.isascii():
        # 纯数字 / 日期串（`90%` `200` `5月1` 去掉汉字之后）单独永远不够——见上面 P7 #5 那条
        return "span" if run[:1].isalpha() and len(run) >= EVIDENCE_EN_MIN else "pair"
    n = weigh(run) if weigh is not None else None
    if n is None:
        n = len(run)
    return "span" if n >= EVIDENCE_CJK_MIN else "pair"


def _weigher(query: str, segment, common=None):
    """把 `segment`（一个 `str -> list[str]` 的切词函数）变成 `_why` 要的那个 `weigh`。

    **只管纯汉字的串**（`_ALL_CJK`）。带数字的串（`3月15` / `10台到`）退回 P32 的原始字数——
    那一档 P32 专门量过、专门留下的：「再严一档（只要含数字就不单独算）全库只多砍 5 对，
    逐条读下来 2 条是真的（「3 月 15 日媒体及投资人版本」↔「2.0 版本…2026年3月15日」）。不换。」
    **别人量完留下的东西，不顺手带走。**

    `common` 在这里是第二次出场，而且这一次才是它该待的地方：P29 的 df 判据本来落在
    **整串**上（`如果用户` 作为一个 4 字串 df 很低，过得去），分词之后它能落在**词**上——
    `如果` 和 `用户` 都在 P29 那 20 个「满库都是」的串里。**P32 说「df 单独救不了」是对的，
    因为那时候 df 落在滑窗上；分词把词边界给出来之后，df 才有地方落。**
    """
    if segment is None:
        return None
    from . import tokenize as _tok
    squeezed = squeeze(query)

    def useless(t: str) -> bool:
        return _is_cn_filler(t) or (common is not None and common(t))

    # **这一段查询只切一次**（P65 ①）。`content_chars` 每次都 `cut(text)`，而这把尺
    # 原来一次查询只问几下（`_strong_enough` 按 cluster 问），P65 把它挪到取词那一层之后
    # 一条查询要问上千下——真切上千遍就是 0.3 s。切出来的东西是确定的，
    # **口径一个字没动，只是不重复切**；传进来的不是这一段就照样现切（判据宁可窄）。
    toks: list[str] | None = None

    def cut(s: str) -> list[str]:
        nonlocal toks
        if s != squeezed:
            return segment(s)
        if toks is None:
            toks = list(segment(s))
        return toks

    def weigh(run: str):
        if not _ALL_CJK(run):
            return None
        return _tok.content_chars(run, squeezed, cut, useless)

    return weigh


def _ALL_CJK(s: str) -> bool:
    return bool(s) and all("一" <= c <= "鿿" for c in s)


def squeeze(query: str) -> str:
    """查询挤掉空白、转小写——`evidence` / `_aligned` / `is_whole_token` / `display_terms`
    **都按这一份定位**。一处定义：两处各挤各的，偏移就会差一位，而差一位的偏移
    在「两端在不在词边界上」这种判据里是静默错。"""
    return _WS.sub("", (query or "").lower())


def _token_spans(text: str, segment) -> set[tuple[int, int]]:
    """`text` 切完词之后每个词各自占的那一段 `[起, 止)`。"""
    out: set[tuple[int, int]] = set()
    pos = 0
    for t in segment(text):
        out.add((pos, pos + len(t)))
        pos += len(t)
    return out


def is_whole_token(run: str, squeezed: str, segment) -> bool:
    """这一串在查询的切词里**正好是一个整 token**——也就是说**它自己就是一个词**。

    **跟 `_aligned` 不是一回事，P46 量出来的**：`_aligned` 问的是「它是不是若干整词
    接起来的」，所以 `的高频`（的 | 高频）、`月前后`（月 | 前后）、`导出的` 两端**都**在
    词边界上，它们对齐、但前后挂着虚词，剥恰恰是对的。这一条问的是「它是不是**一个**词」：
    `华为` / `阿里` / `不变` / `上线` 是，`的高频` 不是。

    **判据宁可窄**：只认查询自己的切词，不拿 `run` 单独再切一次——单独切
    （`segment("的高频")`）跟它在句子里怎么被切根本是两件事。
    """
    if segment is None or not run or run.isascii():
        return False
    spans = _token_spans(squeezed, segment)
    start = 0
    while True:
        i = squeezed.find(run, start)
        if i < 0:
            return False
        if (i, i + len(run)) in spans:
            return True
        start = i + 1


def is_merged_word(run: str, squeezed: str, segment) -> bool:
    """分词把这一串和它的邻词**并成了一个 token**，而这一串自己是**通用汉语词**。

    `链接` 那条误杀就是这个形状（P44 A0b 逐条读那 64 串次时读出来的，`p44-frag64` 里
    标着「误杀」的唯一一条）：这个人库里 `链接面板` 是一个实体词，被 `segment()` 的
    `extra=` 补了进去，于是「这篇用来看**链接面板**」整个并成一个 token，
    `链接` 落在 token 中间、两端都够不着词边界，`_aligned` 判 `False`，当碎片砍掉。

    **它跟 `is_whole_token` 方向相反**（P46 ② 那句「方向相反，先量代价」）：
    那一条问「它在查询的切词里是不是**正好一个 token**」，这一条问的是
    「它**被一个更长的 token 吞进去了**，但它自己确实是个词」。

    **判据窄在两处，两处都是量出来的**（全库 9 串次 / 5 种，逐条读过）：

    1. **必须整个落在某一个 token 里面**（而且不等于那个 token）。跨在两个 token
       之间的（`可以实` = 可以 | 实现、`数据隐` = 数据 | 隐私）**根本不是这个形状**，
       这一条碰都不碰它们——P44 读出来那 64 串次里 23 种是那个形状，全归 `_aligned` 管。

       「不等于那个 token」那半句是**让这个谓词自己说的话是真的**：自己就是一个 token
       的那一档归 `is_whole_token`（P46），不归这一条。**从 `evidence()` 那边看它不改行为**
       （突变验量出来的，照记）：一串要是正好等于某个 token，它两端就都在词边界上，
       `_aligned` 先回 `True`，根本走不到这儿。所以它守的是**这个函数单独被调用时**的诚实，
       不是调用链上的一个分支。
    2. **必须是底表（`tokenize.base_words()`，330,349 条通用汉语词）里的词。**
       这一条是分开这 5 种的那把刀，全库逐条核过：

       | 串 | 被哪个 token 吞了 | 在底表里 | 判定 |
       |---|---|---|---|
       | `链接` | `链接面板` | **是**（词频 40） | **误杀，救回来** |
       | `电池容` | `电池容量` | 否 | 半个词，照砍 |
       | `基础设` | `基础设施` | 否 | 半个词，照砍 |
       | `成功经` | `成功经验` | 否 | 半个词，照砍 |
       | `操作步` | `操作步骤` | 否 | 半个词，照砍 |

       **为什么是底表而不是这个人的词表**（`attested`）：那 5 种里 `attested` 全是
       `False`，**包括 `链接` 自己**——`链接面板` 才是词表里的那个实体，`链接` 不是。
       拿 `attested` 当判据一条都救不回来，量过（P48 第 2 条）。
       **也不是「这一串单独拿去切是不是一个词」**：`电池容` 单独切出来正好是
       `['电池容']` 一个 token（底表里没有，切不动就整段退回来），拿它当判据会
       1 对 3 错。**底表问的是「它是不是汉语里的一个词」，那才是要问的那个量。**

    英文 / 带数字的串一律 `False`：底表是纯汉字 2–4 字的表，拿它去问 `kol` 没有意义。
    """
    if segment is None or not _ALL_CJK(run):
        return False
    from . import tokenize as _tok
    if run not in _tok.base_words():
        return False
    spans = _token_spans(squeezed, segment)
    start = 0
    while True:
        i = squeezed.find(run, start)
        if i < 0:
            return False
        j = i + len(run)
        for (a, b) in spans:
            if a <= i and j <= b and (a, b) != (i, j):
                return True
        start = i + 1


def evidence_label(run: str, squeezed: str | None = None, segment=None) -> str:
    """这一串**摆到用户眼前**时长什么样：剥掉两端的虚词 / 方位 / 日期后缀。

    跟 `display_terms` 用的是同一把剪刀（`_EDGE_STOP`），也跟它同一条规矩：
    **剥完合不出 ≥2 个字的就不显示**——调用方自己按 `len(...) < 2` 判。
    这里**故意不回退到原串**：`kite_memory.recall_evidence` 原来那行
    `label = term.strip(_EDGE_STOP) or term` 的 `or term` 就是 P40 问题 #4 的第二个坑——
    「号上」（号 / 上 都在 `_EDGE_STOP` 里）剥空之后被原样退回，直接摆到了用户眼前。

    英文 / 带数字的串**原样**：`_EDGE_STOP` 是一张汉字表，拿它去剥 `kol` / `3月15` 没有意义。

    **P46 多的那一条：它自己就是一个词的，不剥**（P44 A0b 顺带读出来的那条——
    `华为` 是这个人库里的词条、两端都在词边界上，却被剥掉 `为` 成了单字「华」而砍掉）。
    判据是 `is_whole_token`，**不是 `_aligned`**：拿 `_aligned` 当判据全库量过，
    会把 `的高频` / `月前后` / `导出的` / `希望通过` 这一堆也留下来（62 条查询的行变了，
    多摆 70 串次），**那把尺子量的是「碎」不是「它是不是一个词」**。
    换成 `is_whole_token` 之后全库只有 9 条行变了：多摆 `华为` `阿里` `不变` `上线`
    `视为` `跟着` 6 种，少摆 1 串次（`ppu`，是前 6 那一刀挪了位，不是被判掉的）。

    `squeezed` / `segment` 任一为 `None` = 这一档不启用，**不启用就是原样剥**
    （老调用方、假的 memory、建不出索引）。
    """
    if run.isascii():
        return run
    if squeezed is not None and segment is not None and is_whole_token(run, squeezed, segment):
        return run
    return run.strip(_EDGE_STOP)


def _word_bounds(text: str, segment) -> set[int]:
    """`text` 切完词之后每个词边界的偏移（含 0 和 len）。"""
    out = {0}
    pos = 0
    for t in segment(text):
        pos += len(t)
        out.add(pos)
    return out


def _aligned(label: str, squeezed: str, segment) -> bool | None:
    """这一串**两端在不在查询的词边界上**（P41 尺子 C）。`None` = 这一层判不了。

    落不上 = 它不是若干**整词**接起来的，是切在词中间的碎片：
    「号上」（号 | 上线）✗、「可以实」（可以 | 实现）✗、「数据隐」（数据 | 隐私）✗；
    「众筹页面」（众筹 | 页面）✓、「用户」✓、「比如」✓ —— **常用词不算碎片**。

    **这把尺子量的是「碎」，不是「泛」，两件事别混**（P41 #2 量出来的）：
    「一个实词都没盖住」（`content_chars == 0`）那把尺子会把 `用户` / `功能` / `算力`
    这种**真词**也数进去——它们是被 `common` 判成「满库都是」才拿 0 分的。用这一把。

    `None` 的三档，都按「不知道」处理（**不许当成碎片**，那是把话说死）：
    · 没有分词器（`segment is None`：假的 memory / 建不出索引）——不启用就是原样；
    · 不是纯汉字串——带数字的那一档 `_weigher` 自己就退回字数了（P32 专门量过、专门留下的），
      拿分词去判它是量程用错；英文串本来就是整词切的，这一层不该再插一手；
    · 在查询里定位不到（`evidence_runs` 的 `loose` 那一档）。

    **同一串在查询里出现多次，只要有一次两端都在词边界上就算对齐**——判据宁可窄。
    """
    if segment is None or not _ALL_CJK(label):
        return None
    bounds = _word_bounds(squeezed, segment)
    start = 0
    seen = False
    while True:
        i = squeezed.find(label, start)
        if i < 0:
            break
        seen = True
        if i in bounds and (i + len(label)) in bounds:
            return True
        start = i + 1
    return False if seen else None


def evidence(hits: list[str], query: str, *, common=None, attested=None,
             segment=None) -> list[dict]:
    """每条**合格**证据串 + 它凭什么算证据。

    `common(串) -> bool`：这个词在这个人的库里到处都是（`UserMemory.common_term`，P29）。
    `attested(串) -> bool`：这个词是这个人词表里的表层词（`UserMemory.vocab_term`）。
    两个都可以是 `None` = 那一档不启用（假的 memory / 建不出索引），**不启用就是原样**。

    `why` 是给用户看的那句「为什么这个词算证据」的原料：
    `vocab` = 它是你知识库里的一个词条；`span` = 这么长的一段原话逐字对上；`pair` = 跟别的词一起命中。

    `aligned` 是 P44 **多带的那一格**（跟 P37 #2 的 `VerifyOut`、P41 #1 的 `recalled` 同一条路子）：
    这一串**剥掉两端虚词之后**（`evidence_label`）在不在查询的词边界上。
    `False` = 它是跨词边界的碎片，**显示层别摆**；`None` = 这一层判不了。
    **判的是摆出来的那一串，不是原始的 run**——拿 run 去判会把 `众筹后` → 「众筹」
    这种剥完是真词的也判成碎片（P44 先量那一趟当场读出来的，64 条里有 6 条是这个形状）。

    **`None` 的第四档是 P48 ② 加的**（`is_merged_word`）：分词把这一串和邻词并成了
    一个 token，而它自己是通用词表里的词（`链接` ⊂ `链接面板`）——`_aligned` 判它
    `False` 是因为**那条词边界被分词吃掉了**，不是因为它碎。全库 9 串次 / 5 种逐条读过，
    底表这把刀 1 对 0 错；账在 `docs/TRACELOG-product.md` P48 ②。

    **这一格只给显示层看。`qualifies` 一个字不动**：证据够不够硬是另一个问题，
    「这个词摆出来难看」不是「这条召回不该进来」——把它接进 `qualifies` 就是拿显示规则
    去判死召回，那是最贵的那种错（P32 `evidence_runs` 的 `loose` 同理）。
    """
    runs = evidence_runs(hits, query)
    weigh = _weigher(query, segment, common)
    squeezed = squeeze(query)
    out: list[dict] = []
    for r in runs:
        if common is not None and common(r):
            continue
        # **判的是摆出来的那一串**，而「摆出来长什么样」这件事只有一个定义
        # （`evidence_label`，P46 起它自己会认「它就是一个词」那一档）。
        # 这里再抄一遍剥法 = 两把尺子，`recall_evidence` 摆的和这里判的会对不上。
        label = evidence_label(r, squeezed, segment)
        al = _aligned(label, squeezed, segment)
        # **第四个 `None` 档**（P48 ②）：分词把它和邻词并成了一个 token，而它自己
        # 是通用词表里的词（`链接` ⊂ `链接面板`）。那不是「它是碎片」，是
        # **这把尺子对它判不了**——它两端够不着词边界，恰恰因为那条边界被分词吃掉了。
        # 归 `None` 不归 `True`：`None` 是 P44 立的「不知道」，说它「对齐」是把话说死。
        if al is False and is_merged_word(label, squeezed, segment):
            al = None
        out.append({"term": r, "why": _why(r, attested, weigh), "aligned": al})
    return out


def qualifies(hits: list[str], query: str, *, common=None, attested=None,
              segment=None) -> bool:
    """这条召回拿不拿得出证据。

    用户**主动搜一个词**时不走这条（`len(query) <= _SHORT_QUERY`，跟 `_terms` 兜底同一个边界）：
    那时候那个词就是查询本身，要求它「再拿出第二条证据」等于搜不出东西。
    """
    if len((query or "").strip()) <= _SHORT_QUERY:
        return bool(hits)
    ev = evidence(hits, query, common=common, attested=attested, segment=segment)
    if not ev:
        return False
    if len(ev) >= 2:
        return True
    return ev[0]["why"] != "pair"


def display_terms(terms: list[str], query: str) -> list[str]:
    """给右栏看的查询词：英文词 / 数字原样；中文 n-gram 片段（「小时预」「号上众」「并以」）合成它们在
    查询里连成的整段、再剥掉两端的虚词——用户看到的是「众筹」「学位」这种词，不是切碎的三个字（P4 #6）。
    没有分词器，这是最接近「整词」的做法；合不出 ≥2 字的就不显示。"""
    squeezed = squeeze(query)
    plain: list[str] = []
    spans: list[tuple[int, int]] = []
    for t in terms:
        if not t or (t.isascii() and t[0].isalpha()) or t[0].isdigit():
            if t and t not in plain:
                plain.append(t)
            continue
        start = 0
        while True:
            i = squeezed.find(t, start)
            if i < 0:
                break
            spans.append((i, i + len(t)))
            start = i + 1
    spans.sort()
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out = list(plain)
    for a, b in merged:
        # 片段常常在词中间断掉（「号上众」← 号上众筹）：往后接到这一串汉字的尽头（最多 3 个字、遇虚词停）
        while b < len(squeezed) and b - a < 8 and _IS_CJK(squeezed[b]) and squeezed[b] not in _EDGE_STOP:
            b += 1
        w = squeezed[a:b].strip(_EDGE_STOP)
        # 「众筹」已经在了就不再列「众筹里面会」；反过来「众筹里面会」在了也不列「众筹」
        if len(w) >= 2 and not any((w in o or o in w) for o in out if not o.isascii()):
            out.append(w)
    return out[:8]


def _IS_CJK(ch: str) -> bool:
    return "一" <= ch <= "鿿"


# 显示时从整段词两端剥掉的字：虚词、方位、「号 / 日」这种日期后缀（「3月10号上众筹」切出的「号上众」剥完就是「众筹」）
_EDGE_STOP = "的了在是和与及或把被对到从这那我们你他她它就也都还又很不没有个一着过为以上里并且而但号日上下前后中"


def matched_terms(rows: list[dict], query: str, memory, store) -> list[str]:
    """The query terms that actually appear in the results.

    The old return value was "terms the vocabulary resolved", which after
    this change is often empty for a Chinese query that nonetheless retrieved
    perfectly. The memory panel shows this to the user as "what it searched
    for", so it has to be the terms that did the work, not the ones a lookup
    table happened to recognise.
    """
    terms = _terms(memory, query)
    texts = [(store.facts.get(r.get("id")).text if store.facts.get(r.get("id")) else "") or "" for r in rows]
    hit: set[str] = set()
    for x in texts:
        hit.update(_hits(terms, x))
    return [t for t in terms if t in hit][:8]


def rank(rows: list[dict], query: str, memory, store, *, limit: int,
         evidence: bool = False, common=None, attested=None, segment=None) -> list[dict]:
    """Order the pool by how much of the query each fact contains.

    Score is the total length of the query terms found in the fact's text.
    Length-weighted because a three-character n-gram matching is much
    stronger evidence than a two-character one; **not** normalised by fact
    length -- normalising was measured and made same-topic recall slightly
    worse, since a long fact covering more of the subject is usually the one
    wanted.
    """
    # **这个实参不能省**（P65 ①，跟 P61 #1 那三个实参同一个形状的接线洞）：省了
    # `weigh` 就是 `None`，`_cjk_terms` 那 16 个名额整条退回「每个句段头三个字」的轮转，
    # `记忆` / `华为` / `超节点` 这些真词又排在碎片后头进不来。`test_p65` 单独钉了一条。
    terms = _terms(memory, query, _weigher(query, segment, common))
    if not terms:
        # **一个内容词都没有 = 这段话跟知识库没关系，就该什么都不返回。**
        # 原来这里是 `return rows[:limit]`——把整池原样交回去。
        # 在「查询词不可能为空」的年代那是无害的兜底；第 747 轮给查询加了中文
        # 口水词过滤之后，「帮我总结一下」这种**整句都是指令**的查询会被剔成空，
        # 而这一行照旧把 8 条不相干的事实端上来（用户原话：「我让你写一个需求文档，
        # 你给我搞了一堆没用的记忆」）。
        # 两个调用点都是召回（正文召回 + 行级回退），返回空正是它们要的语义。
        return []
    # 查询里认出的实体（含同一组的其它写法）：事实挂着它就加分——不然「MemoCat」只召回文本里写成
    # MemoCat 的，写成 memo cat 的那一半排不上来（第 293 轮真库实测 7:1）
    group_codes: set[str] = set()
    if hasattr(memory, "_match_vocab") and hasattr(memory, "_index"):
        try:
            from . import entities as entities_mod
            _t, ents, _s = memory._match_vocab(query, getattr(memory, "_index")()[1])
            g = entities_mod.for_store(store, getattr(memory, "_index")()[1])
            group_codes = {m for e in ents for m in g.members(e)}
        except Exception:      # noqa: BLE001 — 假的 memory 没这些，按纯词面
            group_codes = set()
    ENTITY_BONUS = 4
    long_query = len((query or "").strip()) >= LONG_QUERY

    def score(row: dict) -> tuple[int, str]:
        fact = store.facts.get(row.get("id"))
        text = (fact.text if fact else "") or ""
        # 数字命中比同长度的字词更硬（「4月16」几乎就是在指那一天），多给 2 分
        hits = _hits(terms, text)
        # 长查询（自动召回）：只靠一个泛词命中的候选不要——那不是相关，是凑数（P4 #6）
        # **这三个实参不能省**（P61 #1）：省了 `_weigher` 就是 `None`，整条退回「≥3 字」
        # 那把给滑窗定的尺——`华为` / `周敏` / `手环` 这些真词又全被挡回去。接线洞。
        if long_query and not _strong_enough(hits, query, segment, common):
            return (0, row.get("date") or "")
        # 拿不出**合格证据**的不要（P32 #1）。跟上面那条不是一回事：那条只在 ≥100 字时看
        # 「有没有两个不同的 cluster」，这条在任何长度上问「这两条到底凭什么算相关」——
        # 实体加分也不能让一条**一个查询词都没命中**的事实凭空进来（那样面板连「命中：」都写不出）。
        if evidence and not qualifies(hits, query, common=common, attested=attested,
                                      segment=segment):
            return (0, row.get("date") or "")
        s = sum(len(t) + (2 if t[0].isdigit() else 0) for t in hits)
        # 同一个词出现不止一次再加一点（每多一次 +1，最多 +2）：查询只剩一个内容词时（「…no ideas now but
        # will have ideas later」剔掉虚词只剩 ideas），几十条都提到 ideas 的事实靠日期断结，
        # 说了两遍的那条反而排不进前五（第 531 轮 seed 7 那条 miss）
        low = text.lower()
        s += sum(min(2, max(0, low.count(t) - 1)) for t in hits)
        if group_codes and fact is not None and group_codes & set(getattr(fact, "entities", ()) or ()):
            s += ENTITY_BONUS
        return (s, row.get("date") or "")

    # 一个查询词都没命中的候选不要：它们只是 grep 通道子串撞进来的（`md` 撞 SMD），
    # 排在后面照样会被当成「相关记忆」显示出来（第 224 轮实拍）
    # 每行只打一次分（P11 #3：原来 `if score(r)[0] > 0` 又算一遍，4.4 万行 × 2）
    scored = [(sc, r) for r in rows if (sc := score(r))[0] > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    # 伪相关反馈（第 533 轮实验）：词面排前两名的事实挂着什么主题，其余候选挂同一主题的 +1 再排一次——
    # 「给一个片段找同主题的别的事实」这条口径靠它；查询片段本身很少能直接认出主题（TOPIC_BONUS 试过零效果）
    if len(scored) > 2:
        lead: set[str] = set()
        for (_s, r) in scored[:2]:
            f = store.facts.get(r.get("id"))
            lead |= set(getattr(f, "topics", ()) or ()) if f is not None else set()
        if lead:
            def bump(item):
                (sc, d), r = item
                f = store.facts.get(r.get("id"))
                return ((sc + (1 if f is not None and lead & set(getattr(f, "topics", ()) or ()) else 0), d), r)
            scored = sorted((bump(x) for x in scored), key=lambda x: x[0], reverse=True)
    return [r for _s, r in scored][:limit]
