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

## P11：按查询取回的那一路也走同一道筛（`search_memory` / `gather_subject`）

P8 记着一条没筛住的：da080 / e783 的 prompt 里各进了 9 / 6 条 `apple-74b508a0612feb7e-*`
「公司计算产业的芯片包括…鲲鹏 CPU」——`search_memory("cross-comparison intelligence 消费者 反馈")`
取回来的，跟查询、跟这两篇都零关系；**同一件事挡住一半等于没挡**（§21）。它的「来处」也说得清：
词法检索返回的事实必然跟查询共用词元，一条**跟取回它的那句查询零重合**的事实，是从查询解析到的
主题 / 实体桶里按时间取回来的——跟 `filter_facts` 的抽样是同一个形状。所以候选多一档：
`queried_ids`（search_memory / gather_subject 返回的、跟自己那句查询零重合的），再过同一道
「跟标题 + 骨架 + 正文 + 查询零重合」——两个条件同时成立才剔，默认照旧只记不剔。

## P8 退回：默认只记不剔（`params.RELEVANCE_FILTER`）

真跑五篇：剔的没剔错，但 da080 第 1 轮三批全是抽样、筛完剩 2 条 → 8 轮（P6 1 轮）、留下 95% → 50%；
3a3a 12 条全剔 → `material_thin` 弃答（70% → 40%）；token 翻倍。计划铁律第 7 条：让产出变差的退回去。
所以 `gate(apply=False)` 是默认——「本该剔的」照样算出来进 `round_summary.facts_irrelevant`，
材料一条不动；开关打开时也剔不到 `MIN_KEPT` 条以下。

## P28：开开关之前的三条前置（**开关照旧默认关**）

P26 在 P24 那 5 跑上量出「开着会怎样」，并留下三条「开之前必须先做对」的。P28 做的就是这三条，
`RELEVANCE_FILTER` 一个字没动 —— 开不开还是要等编辑信号那张表（`middleware/edits.py` 采的）
攒出「用户留没留」（P8b 的教训）。**这一段只提采集口、不写那张表的名字**：
「只采集不调参」那条闸是按表名 grep 整个 `app/` 的（docstring 也算），写上就把它变红了。

1. **回填顺序确定下来。** 夹逼回填的候选 `scored` 全是 0（它们正是因为零重合才被剔的），
   只按 `-scored[i]` 排就是按 `set` 的迭代序，**跟 `PYTHONHASHSEED` 走**。
   P28 在 P26 那 5 跑 r1 上实测复现（`<scratch>/p28/m2_gate.py`，`facts_irrelevant` 跟记录 5/5 全同）：
   `3a3a96354546` seed 0 塞回 `{12F2, 12F8}`、seed 1 `{8F6, 12F8}`、seed 2 `{8F6, 12F9}`；
   `da080ca847cf` seed 0 `{12F2}`、seed 1/2 `{8F6}`。**开关一开，prompt 就是跨进程不可复现的**，
   任何 A/B 都做不了。第二个排序键是材料在 `facts` 里的位置（检索给的次序）。
2. **context 那一侧也剥编号**（`strip_ids`，量在它的 docstring 里）。
3. **剔到下限先再检索一次**（`gate(refill=…)`），而不是把刚判过的抽样行塞回去。
"""

from __future__ import annotations

import re

MIN_SHARED_TERMS = 1
BROAD_TOPIC_FACTS = 1000

_EN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_NUM = re.compile(r"\d{2,}(?:[.,]\d+)?%?")
# 月份自己就是一个词元（P57 #3）。`4 月 10 号` / `8月5号` / `2026年12月18号` 都认，
# **前面紧挨着数字的不认**（`2026年` 里的 `26` 不是月份）。中文数字那一侧靠
# 调用方注入的 `relations.cn_month_to_digits` 先换成阿拉伯数字。
_MONTH = re.compile(r"(?<!\d)(\d{1,2})\s*月")
_CJK = re.compile(r"[一-鿿]+")
# 材料行的两种前缀：``[terrence-2046-2F3] 正文`` / ``[terrence-2046-2F3 的原话] - 2026-03-10｜user：正文``
_HEAD = re.compile(r"^\[([A-Za-z0-9_\-]+)(?P<src> 的原话)?\]\s*(?:-\s*[\d-]+｜[^：:]{0,12}[：:]\s*)?")
_SUFFIX = re.compile(r"（[^）]{0,60}）\s*$")
# `as_facts` 按行拆工具结果，「（2026-05-15 · speaker c · plan）」这种元信息行会单独成一条
_META_LINE = re.compile(r"^（[^）]{0,80}）$")
_BATCH_HEAD = re.compile(r"^共 (\d+) 条，返回 (\d+) 条")
# 正文里**行内**的事实编号：`[terrence-1844-16F2]`。跟 `_HEAD` 不是一回事——那个只认行首、
# 剥的是材料行自己的前缀；这个要在一整篇正文里找（P28 #2②）。
# **窄在「至少三段、段间连字符」这个形状上**：`[备注]` / `[Note](note://x)` 的方括号里
# 没有两个连字符，不会被误剥。
_CITE_IN_TEXT = re.compile(r"\[[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+){2,}\]")
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


def terms(text: str, *, normalize=None) -> set[str]:
    """一段文字的特征词。

    `normalize`（P57 #3）：**调用方注入**的一个 `str -> str`，在抽词元之前先过一遍。
    生产那一侧传的是 `kb/relations.cn_month_to_digits`（`就八月` → `就8月`）。
    为什么是注入而不是 import：这个模块在 `tests/test_layering.py` 的 `PURE` 名单里，
    只许依赖标准库——而 P56 又明说「别在这儿再写一份数字归一」。同 P29 给
    `relations.detect` 注 `common`、P32 给 `recall` 注 `qualifies` 的做法。

    `N月` 单独算一个词元（`_MONTH`）：归一只走一半。`八月` 归一成 `8月` 之后，
    `_CJK` 那个 run 只剩一个 `月` 字**连 2-gram 都出不来**，`_NUM` 又是 `\\d{2,}`
    一位数的 `8` 也不算——不补这一条，归一救不回任何一条。
    实测账在 `relations.cn_month_to_digits` 的 docstring 里（误剔 3 → 1，剔对的 29 条没动）。
    """
    if normalize is not None:
        text = normalize(text or "")
    out = {w.lower() for w in _EN.findall(text or "")} - _STOP_EN
    out |= set(_NUM.findall(text or ""))
    for m in _MONTH.finditer(text or ""):
        n = int(m.group(1))
        if 1 <= n <= 12:
            out.add(f"{n}月")
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


def strip_ids(text: str) -> str:
    """把正文里行内的 `[terrence-1844-16F2]` 这种编号拿掉再抽词元（P28 #2②）。

    **材料那一侧 `fact_body()` 早就剥了，context 这一侧一直没剥**——于是
    `_NUM`（`\\d{2,}`）从编号里抽出 `1844` / `16` 当成正文的特征词，材料里那句
    「4 月 16 号的 EVT 是纯主机的」跟它「重合」，判成相关留下来。
    实测（P24 那 5 跑 r1，`<scratch>/p28/m2_terms.py`）：`a941efecd390` 的
    context 里 9 个编号贡献了 **11 个纯数字词元**（`16` / `1844` / `50` / `380`…）
    和 9 个 id 词元，**这 11 个数字没有一个在剥完编号的正文里还出现过**——
    也就是说剥掉不会丢任何真词元。剥完 would-drop 6 → 10 行，
    两条「4 月 16 号…」的硬件材料不再靠编号活着。
    """
    return _CITE_IN_TEXT.sub(" ", text or "")


def fact_key(fact: str) -> tuple[str, bool]:
    """``(事实 id, 是不是「的原话」展开行)``；没有 id 返回 ``("", False)``。"""
    m = _HEAD.match((fact or "").strip())
    if not m:
        return "", False
    return m.group(1), bool(m.group("src"))


def shared_terms(fact: str, context_terms: set[str], *, normalize=None) -> int:
    return len(terms(fact_body(fact), normalize=normalize) & context_terms)


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


# 按查询取材料的两个工具（`tools/memory_tools.py`）。`search_session_context` 是多跳、
# `fact_sources` 是回溯原话，都不是「按查询撒网」，不算。
_QUERY_TOOLS = ("search_memory", "gather_subject")


def _query_text(args) -> str:
    return " ".join(str((args or {}).get(k) or "") for k in _QUERY_KEYS
                    if isinstance((args or {}).get(k), str)).strip()


def queried_ids(calls, *, normalize=None) -> set[str]:
    """按查询取回、却跟取回它的那句查询**零重合**的事实 id（P11）——来处说明它不是词法命中，
    是查询解析到的主题 / 实体桶按时间取的，跟 `filter_facts` 的抽样同一个形状。
    同一条事实被别的查询真命中过就不算。"""
    hit: set[str] = set()
    miss: set[str] = set()
    for name, args, result in calls or ():
        if name not in _QUERY_TOOLS:
            continue
        qterms = terms(_query_text(args), normalize=normalize)
        for line in (result or "").splitlines():
            fid, is_src = fact_key(line.strip())
            if not fid or is_src:
                continue
            if qterms and shared_terms(line, qterms, normalize=normalize) >= MIN_SHARED_TERMS:
                hit.add(fid)
            else:
                miss.add(fid)
    return miss - hit


def queries_of(calls) -> str:
    """模型这次跑自己发过的查询词——它对「要找什么」的陈述，算进相关性的量程。"""
    parts: list[str] = []
    for _name, args, _result in calls or ():
        for k in _QUERY_KEYS:
            v = (args or {}).get(k)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
    return "\n".join(parts)


# 开着筛也不许剔到这么多条以下（P8 退回）：3a3a 第 1 轮 12 条全剔 → `material_thin` → 弃答。
# 数的是**材料条**（带 id 的行 + 不带 id 的兜底行），「（日期 · 说话人 · 类型）」元信息行不算一条。
#
# **P26 量完的判断：这个下限太松，而且它买的安全根本没买到。**（P26 #5）
# ① 它在 4/9 个会剔的轮开火，每一次塞回来的**正是 P22 抱怨的那批材料**
#    （`3a3a96354546` 塞回「4 月 16 号的 EVT 是纯主机的」+「EVT 准备 4 台主机，15 套 PCBA」）；
# ② 它保的是**条数不是可用材料**——`e78306` r2 第三个名额给了「Speaker D: 对，好理解，」；
# ③ 提到 4/5 只让更多被判过的材料回来，降到 0/1 又当场复现 P8b 的弃答。
# **所以要调的不是它的高度**，是**补的时候补什么**：P28 #2③ 把第一顺位换成
# `gate(refill=…)` —— 剔到下限先**再检索一次**（`hooks/note` 传的是零模型的关键词检索，
# 来处不是 >1000 的抽样桶），补够了就一条旧的都不塞回去；`refill` 没给或它也空手，
# 才退回这套按重合度塞回来的兜底（那是 P8b 用弃答换来的那条命，不能撤）。
MIN_KEPT = 3


def gate(facts: list[str], calls, context: str, *,
         min_shared: int = MIN_SHARED_TERMS, min_kept: int | None = None,
         apply: bool = True,
         refill=None, normalize=None) -> tuple[list[str], list[tuple[str, int]]]:
    """材料分成 ``(留下的, [(剔掉的, 重合数)])``，顺序保持。

    只剔「从超大主题抽样回来（或按查询取回却跟查询零重合，P11）**且** 跟 `context`（标题 + 骨架 + 正文 + 查询）零重合」的；
    元信息行 / 「的原话」行跟着母事实（前一条有 id 的）走。`context` 为空一条都不剔。
    `context` 里行内的事实编号先被 `strip_ids()` 剥掉（P28 #2②）。

    `apply=False`（`params.RELEVANCE_FILTER` 关着，P8 退回后的默认）：**只记不剔**——第二项照样
    列出「本该剔的」，第一项就是原样的 `facts`。

    `apply=True` 时剔到 `min_kept` 条以下的处理（P28 #2③，依据在 `MIN_KEPT` 上面）：
    **先要 `refill()` 再检索一次**，它返回的新材料补进来；补够了就一条都不塞回去。
    只有 `refill` 没给、或者它也空手时，才退回 P8 那套「把刚剔掉的按重合度塞回来」——
    那是最后一道防线（P8b 实测第 1 轮空手 → `material_thin` 弃答，代价比材料脏大）。
    """
    ctx = terms(strip_ids(context or ""), normalize=normalize)
    # 两档来处（`sampled_ids` 抽样 + `queried_ids` 按查询取回却跟查询零重合），同一道筛
    sampled = sampled_ids(calls) | queried_ids(calls, normalize=normalize)
    if not ctx or not sampled:
        return list(facts), []
    facts = list(facts)
    scored: dict[str, int] = {}
    for f in facts:
        fid, is_src = fact_key(f)
        if fid and not is_src and fid in sampled:
            scored[fid] = shared_terms(f, ctx, normalize=normalize)
    drop_ids = {fid for fid, n in scored.items() if n < min_shared}
    # 下限在调用时读模块常量（不是默认参数绑死的那份）——测试和突变验改的就是它
    if min_kept is None:
        min_kept = MIN_KEPT

    def _is_item(f: str) -> bool:
        return not _META_LINE.match((f or "").strip())

    if apply and drop_ids:
        # 下限：留下的材料条（不数元信息行）不能少于 min_kept
        total = sum(1 for f in facts if _is_item(f))
        # 剔掉的条数 = 那些 id 的母事实行 + 跟着走的「的原话」行
        gone_items = sum(1 for f in facts if _is_item(f) and fact_key(f)[0] in drop_ids)
        if total - gone_items < min_kept and refill is not None:
            # **剔到下限 = 重新检索的信号**，不是「把刚判过的抽样行补回三条」。
            # 新来的这批不过这道筛：它的来处不是 >1000 的抽样桶（`sampled_ids` 只认
            # `filter_facts` 返回头那个分母），本来就一条都轮不到被剔。
            have = set(facts)
            fresh = [f for f in (refill() or []) if f and f not in have]
            facts += fresh
            total += sum(1 for f in fresh if _is_item(f))
        # 兜底：`refill` 没给 / 也空手 —— 才把刚剔掉的按重合度塞回来（P8b 那条命）。
        # **顺序必须确定**（P28 #2①）：候选的 `scored` 全是 0（它们正是因为
        # `n < min_shared` 才进这个集合的），只按 `-scored[i]` 排等于按 `set` 的迭代序，
        # 而那个序**跟 `PYTHONHASHSEED` 走**——实测同一篇 `3a3a96354546` r1：
        # seed 0 塞回 {12F2, 12F8}、seed 1 {8F6, 12F8}、seed 2 {8F6, 12F9}，
        # 三个 seed 三套不同的 prompt。第二个键是**材料自己在 `facts` 里的位置**
        # （检索给的次序），不是 id 字典序：并列时先来的先回来，读得出理由。
        order = {}
        for i, f in enumerate(facts):
            fid = fact_key(f)[0]
            if fid and fid not in order:
                order[fid] = i
        for fid in sorted(drop_ids, key=lambda i: (-scored[i], order.get(i, 1 << 30), i)):
            if total - gone_items >= min_kept:
                break
            drop_ids.discard(fid)
            gone_items -= sum(1 for f in facts if _is_item(f) and fact_key(f)[0] == fid)
    kept: list[str] = []
    dropped: list[tuple[str, int]] = []
    last_fid = ""
    for f in facts:
        fid, is_src = fact_key(f)
        if fid:
            last_fid = fid
            ok = fid not in drop_ids
        elif _META_LINE.match((f or "").strip()):
            ok = last_fid not in drop_ids                 # 元信息行跟母事实
        else:
            ok = True                                     # 多跳 / 兜底检索回来的不带 id：不动
        if not ok:
            dropped.append((f, shared_terms(f, ctx, normalize=normalize)))
        if ok or not apply:
            kept.append(f)
    return kept, dropped
