"""材料进 prompt 前的零模型相关性筛（P8 问题 5）。

P5 人读五篇真实笔记（`docs/TRACELOG-product.md` P5 节问题 5）：`hooks/note.prepare`
按主题树 `filter_facts(topic=…)` 拉材料，**没有「跟本篇相关」这一道**，于是
`3a3a96354546`（一篇网页文案笔记）拿到 EVT 4/16、4 台主机 15 套 PCBA、T0 5/15 这批
硬件节点；`e78306202d78`（教育合作笔记）拉回「Speaker C says the device can help moms
and dads…」和 KO/EVT/T0；`a941efecd390`（面试准备）拿到另一场访谈。P5 里
`material_used` 判 0「一条都没用上」还**逼着**下一轮把它们写进正文（3a3a 第 1→2 轮）；
P6 没逼，模型照样把 EVT 写进了网页文案笔记——材料在 prompt 里，它就会用。

## 量出来的两件事（P8，`docs/TRACELOG-product.md` P8 节问题 5 那张表）

**第一件：跟正文的词元重合本身分不开「相关」和「无关」。** P6 五篇递给模型的
80 条材料逐条对「标题 + 骨架 + 正文」数共用词元：da080 六条人读全对的节点材料
重合 0–2，603dca 那条撑起整段的房价材料（310 / 265 / 235 元）重合 **0**——它们是
来填空节的，跟已有正文不重合是**必然**；而 a941 / 3a3a 的 EVT 硬件节点重合也是
0–2。任何一个整体阈值都会剔掉相关的、留下无关的。

**第二件：无关材料有一个共同的来处——从超大主题里按条数抽样。** 十跑里
`filter_facts` 的返回头「共 N 条，返回 15 条」：无关的那些全部来自
`work_product`（1005 条）/ `project`（1642）/ `work_product_design`（3167）/
`work`（4901），一个上千条的桶只返回最近 15 条，**那是抽样，不是检索**；而
`personal_real_estate_sale`（103）/ `work_go_to_market`（79）/
`learning_school_interview_prep`（440）这些具体主题的返回，人读全部相关。
分界在 1000 上下一个数量级，取 `BROAD_TOPIC_FACTS = 1000`。

所以筛法是**两个条件同时成立才剔**：这条材料出自一个 > 1000 条的主题的抽样，
**而且**跟「标题 + 骨架 + 正文 + 这次跑模型自己发过的查询」一个词元都不共用
（`MIN_SHARED_TERMS = 1`）。具体主题的返回、`gather_subject` / `search_memory`
按查询取回的、多跳取回的，一条不动。**判据宁可窄一点**：误剔一条相关材料的代价
是这一轮少一条依据，误留一条无关材料的代价是它被写进用户的笔记——但两边都要付，
所以只剔那些「来处已经说明它是抽样、内容又跟这篇零重合」的。

特征词 = 英文词（≥3 字母，去停用词）+ 数字（≥2 位）+ 中文 2-gram（去掉本身是虚词的
2-gram，以及首尾是「的了在是…」这类单字虚词的）。「[X 的原话]」展开行和
「（日期 · 说话人 · 类型）」元信息行跟着它的母事实走。
"""

from __future__ import annotations

import re

MIN_SHARED_TERMS = 1
BROAD_TOPIC_FACTS = 1000

_EN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_NUM = re.compile(r"\d{2,}(?:[.,]\d+)?%?")
_CJK = re.compile(r"[一-鿿]+")
# 材料行的两种前缀：``[terrence-2046-2F3] 正文`` / ``[terrence-2046-2F3 的原话] - 2026-03-10｜user：正文``
_HEAD = re.compile(r"^\[([A-Za-z0-9_\-]+)(?P<src> 的原话)?\]\s*(?:-\s*[\d-]+｜[^：:]{0,12}[：:]\s*)?")
_SUFFIX = re.compile(r"（[^）]{0,60}）\s*$")
# `as_facts` 按行拆工具结果，「（2026-05-15 · speaker c · plan）」这种元信息行会单独成一条
_META_LINE = re.compile(r"^（[^）]{0,80}）$")
_BATCH_HEAD = re.compile(r"^共 (\d+) 条，返回 (\d+) 条")
_FACT_ID_IN_RESULT = re.compile(r"^\[([A-Za-z0-9_\-]+)\]", re.M)
_QUERY_KEYS = ("query", "question", "keyword", "keywords", "text")

# 单字虚词：2-gram 首尾任一是它就不算。**只放真正的助词 / 代词 / 连词**——
# 第一版把「这样」「问题」「内容」「时候」整词摊成字放进去，「样机」「容量」
# 「时间线」跟着全没了（P8 校准时抓到的）。
_STOP_CHARS = set("的了在是和与及或把被对到从这那就也都还又很不没有个一着过为以并将其它他她我你们")
# 本身就是虚词的 2-gram
_STOP_BIGRAMS = set("我们 你们 他们 这个 那个 可以 需要 什么 怎么 以及 一个 进行 问题 时间 方式 方法 内容 情况 "
                    "地方 东西 部分 开始 结束 现在 已经 还有 就是 不是 然后 因为 所以 但是 如果 那么 这样 这些 "
                    "那些 或者 比如 可能 应该 觉得 知道 其实 一下 一些 这里 那里 之后 之前 时候 对吧 反正 "
                    "大概 比方 肯定 只是 直接 自己 出来 基本 这么 那么 一直 其他 所有 整个 相对 比较".split())
# 英文停用词：材料里几乎每条都有 Speaker / says / user，它们跟任何一篇都「重合」
_STOP_EN = {
    "speaker", "says", "said", "say", "the", "and", "that", "with", "this", "they", "will",
    "are", "was", "were", "have", "has", "had", "from", "for", "not", "but", "about", "into",
    "than", "then", "also", "what", "when", "where", "which", "would", "could", "should",
    "there", "their", "them", "been", "being", "more", "some", "very", "just", "like", "can",
    "you", "your", "our", "its", "user", "people", "thing", "things", "going", "want", "wants",
    "need", "needs", "think", "make", "made", "get", "got", "one", "two", "all", "any",
    "because", "between", "does", "did", "how", "who", "why", "yes", "now", "here", "out",
    "over", "only", "much", "many", "most", "other", "same", "such", "take", "see", "use",
    "used", "using", "way", "well", "still", "even", "back", "good", "new", "first", "last",
    "next", "time", "really", "something", "someone", "let", "lets", "okay", "right",
    "mentions", "mentioned", "asks", "asked", "tells", "told", "thinks", "doing", "before",
    "after", "quickly", "going", "able", "last", "more",
}


def terms(text: str) -> set[str]:
    """一段文字的特征词。"""
    out = {w.lower() for w in _EN.findall(text or "")} - _STOP_EN
    out |= set(_NUM.findall(text or ""))
    for run in _CJK.findall(text or ""):
        for i in range(len(run) - 1):
            g = run[i:i + 2]
            if g[0] in _STOP_CHARS or g[1] in _STOP_CHARS or g in _STOP_BIGRAMS:
                continue
            out.add(g)
    return out


def fact_body(fact: str) -> str:
    """去掉材料行的编号前缀和「（日期 · 说话人 · 类型）」后缀。"""
    return _SUFFIX.sub("", _HEAD.sub("", (fact or "").strip())).strip()


def fact_key(fact: str) -> tuple[str, bool]:
    """``(事实 id, 是不是「的原话」展开行)``；没有 id 返回 ``("", False)``。"""
    m = _HEAD.match((fact or "").strip())
    if not m:
        return "", False
    return m.group(1), bool(m.group("src"))


def shared_terms(fact: str, context_terms: set[str]) -> int:
    return len(terms(fact_body(fact)) & context_terms)


def sampled_ids(calls) -> set[str]:
    """这次工具循环里，哪些事实是从超大主题里**抽样**回来的（`filter_facts` 返回头
    「共 N 条」N > `BROAD_TOPIC_FACTS`）。`calls` 是 `ToolTrace.calls`：(工具名, 参数, 结果)。"""
    out: set[str] = set()
    for name, _args, result in calls or ():
        if name != "filter_facts":
            continue
        m = _BATCH_HEAD.match((result or "").lstrip())
        if m and int(m.group(1)) > BROAD_TOPIC_FACTS:
            out |= set(_FACT_ID_IN_RESULT.findall(result or ""))
    return out


def queries_of(calls) -> str:
    """模型这次跑自己发过的查询词——它对「要找什么」的陈述，算进相关性的量程。"""
    parts: list[str] = []
    for _name, args, _result in calls or ():
        for k in _QUERY_KEYS:
            v = (args or {}).get(k)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
    return "\n".join(parts)


def gate(facts: list[str], calls, context: str, *,
         min_shared: int = MIN_SHARED_TERMS) -> tuple[list[str], list[tuple[str, int]]]:
    """材料分成 ``(留下的, [(剔掉的, 重合数)])``，顺序保持。

    只剔「从超大主题抽样回来 **且** 跟 `context`（标题 + 骨架 + 正文 + 查询）零重合」的；
    元信息行 / 「的原话」行跟着母事实（前一条有 id 的）走。`context` 为空一条都不剔。
    """
    ctx = terms(context or "")
    sampled = sampled_ids(calls)
    if not ctx or not sampled:
        return list(facts), []
    decided: dict[str, bool] = {}
    for f in facts:
        fid, is_src = fact_key(f)
        if fid and not is_src and fid in sampled:
            decided[fid] = shared_terms(f, ctx) >= min_shared
    kept: list[str] = []
    dropped: list[tuple[str, int]] = []
    last_fid = ""
    for f in facts:
        fid, is_src = fact_key(f)
        if fid:
            last_fid = fid
            ok = decided.get(fid, True)
        elif _META_LINE.match((f or "").strip()):
            ok = decided.get(last_fid, True)          # 元信息行跟母事实
        else:
            ok = True                                 # 多跳 / 兜底检索回来的不带 id：不动
        if ok:
            kept.append(f)
        else:
            dropped.append((f, shared_terms(f, ctx)))
    return kept, dropped
