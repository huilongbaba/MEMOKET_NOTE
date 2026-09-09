"""写作场景专用的 KITE compile profile。

``compile_plan()`` 的 prompt 全部来自 ``profile.COMPILE_PROMPT``——profile 就是
这个库官方留的定制点。默认那份（``memoket_kite/prompts/recall.py``，13 行）是
通用兜底，直接拿来用有三个实测问题：

1. **schema 里根本没有 ``stages``**，模型不知道多跳存在，所以永远编不出多跳
   计划。「在讨论 X 的那次会里还提到了什么」这类问题只能退化成单跳关键词。
   而多跳恰恰是 compile 相对词法检索唯一不可替代的能力。
2. **只说了一句 "distinctive word stems"，模型照样写整句短语**，而 ``grep`` 是
   对 fact 文本的字面正则硬过滤——"APP 安装不上" 在 20361 条事实里命中 0 条，
   整条 query 直接报废。没有任何后校验。
3. **``{units}`` 把 2427 个 session 的 id=date 全量塞进 prompt**，实测占 73,062
   字符里的 68,518（93.8%），是 compile 要 20-38 秒的主因。而它存在的理由——
   让模型能挑出具体 session id——正是 ``stages`` 让它变得不必要的事：第一跳去
   找 session，第二跳用 ``$anchor.units`` 绑定，模型根本不需要预先看到 id 清单。

``str.format`` 会忽略模板里没用到的键，所以模板不引用 ``{units}``，那 68K 就
不会进 prompt——不需要改库里的任何代码。
"""

from __future__ import annotations

import re

COMPILE_PROMPT = """Translate the question into a KITE retrieval plan. Return JSON only.

TOPICS: {tree}
ENTITIES: {entities}
KINDS: {kinds}
TODAY: {today}
COVERAGE: __COVERAGE__
QUESTION: {question}

RULES
- `grep` is matched as a literal regex against fact text. Use ONE short
  distinctive stem: 2-4 characters for Chinese, a single word for English.
  A phrase such as "APP 安装不上" matches nothing. Prefer `topics` and
  `entities` filters; add `grep` only to narrow further.
- Never invent unit ids. To scope a query to the session where something was
  discussed, use shape 2 below and let the first stage find the units.
- Speaker labels (speaker_a, speaker_b, ...) are per-session diarization
  labels, not stable identities: the same label refers to different people in
  different sessions. Do not filter by them unless the question is explicitly
  about a labelled speaker.
- Only use a `time` filter when the question is actually about a period.

SHAPE 1 — single hop. Independent lookups, pooled and ranked together:
{{"queries":[{{"select":"facts","where":{{"grep":str,"who":[str],
"topics":[{{"code":str,"closure":true}}],"entities":[str],"kind":[str],
"time":[str,str]}},"pipe":[{{"op":"head","n":10}}]}}],"intent":"factual"}}

SHAPE 2 — multi hop. Use this whenever the question is scoped to the context
of something else: "in the meeting where X came up, what else was decided",
"after we agreed on X, what changed", "the person who raised X, what else did
they say". The first stage locates an anchor; later stages reference it with
"$name.units" / "$name.unit" / "$name.date". Reference resolution is
deterministic — you only write the template:
{{"stages":[
 {{"name":"anchor","select":"facts","where":{{"grep":str,
   "topics":[{{"code":str,"closure":true}}]}},"pipe":[{{"op":"head","n":3}}]}},
 {{"name":"rest","select":"facts","where":{{"units":"$anchor.units"}},
   "pipe":[{{"op":"head","n":12}}]}}],"intent":"factual"}}

Pick shape 2 if the question depends on first finding something; otherwise
shape 1 with one to three queries."""


# 纯数字、极短码这类没有检索价值的实体（实测 120 个里有 40 个是这种：
# 110 / 210 / 3085 / 8g / 99 / 18号拍摄 / 2012实验室）
_JUNK_ENTITY = re.compile(r"^(\d[\w\-]*|[a-z0-9_]{1,3})$")
# 说话人标签是会话内的 diarization 编号，不是稳定身份：同一个 speaker_c
# 在 124 个不同会话里是不同的人。它们占了全部实体引用的 54%，喂给模型
# 只会让它按说话人过滤，然后跨会话串味。
_SPEAKER_LABEL = re.compile(r"^speaker[_ ]?[a-z0-9]$", re.I)

ENTITY_LIMIT = 80


def curated_entities(store, vocab, limit: int = ENTITY_LIMIT) -> str:
    """按被引用次数排序的实体清单，剔掉说话人标签和垃圾码。

    库自带的做法是 ``sorted(vocab.entities)[:120]``——**按字母序截断**。
    实测在 terrence 的 1203 个实体上，这份清单切在 "canberra"，引用次数
    最高的 20 个里有 16 个根本没进 prompt（包括用户自己的产品名 memo_cat、
    他本人 terrence、kickstarter、google），而进去的 120 个里有 40 个是
    纯数字垃圾码，还有《秘密花园》的人物。模型只能在这份任意前缀里挑，
    所以编出来的 plan 老是 entities:["app"]——app 恰好字母序靠前。
    """
    counts: dict[str, int] = {}
    for f in store.facts.values():
        for code in f.entities:
            counts[code] = counts.get(code, 0) + 1
    picked = []
    for code, _n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if _SPEAKER_LABEL.match(code) or _JUNK_ENTITY.match(code):
            continue
        ent = vocab.entities.get(code)
        aliases = sorted(getattr(ent, "aliases", None) or []) if ent else []
        picked.append(code + (f" (aka {', '.join(aliases[:2])})" if aliases else ""))
        if len(picked) >= limit:
            break
    return ", ".join(picked) or "(none)"


def time_context(store) -> str:
    """压缩的时间上下文，替代库里那份全量 session 清单。

    默认 prompt 用 ``UNITS: id=date; id=date; ...`` 把每个 session 都列出来，
    实测占 73,080 字符里的 68,510（93.8%），是 compile 要 20-38 秒的主因。
    但它真正承载的信息量小得多：terrence 的 2427 个 session 只覆盖三个月，
    整份清单压成月度直方图只要 36 个字符。

    ``COVERAGE`` 让模型知道哪些区间有数据（不至于把 time 过滤框到空区间），
    具体 session id 一个都不给——那是 ``stages`` 的活：第一跳按内容找到
    session，第二跳用 ``$anchor.units`` 绑定，不需要模型预先看到 id。
    """
    dates = sorted(u.date for u in store.units.values() if (u.date or "").strip())
    if not dates:
        return "(no dated sessions)"
    months: dict[str, int] = {}
    for d in dates:
        months[d[:7]] = months.get(d[:7], 0) + 1
    hist = " ".join(f"{k}:{v}" for k, v in sorted(months.items()))
    return (f"{dates[0]}..{dates[-1]} ({len(dates)} sessions) — by month: {hist}. "
            "Never invent session ids; use SHAPE 2 to find them.")


class WritingProfile:
    """包一层基础 profile，只换掉 COMPILE_PROMPT。

    其余属性（KINDS、抽取用的 prompt 等）一律转发给基础 profile——这里只
    改检索编译这一件事，不碰入库那条链路。

    传了 ``store``/``vocab`` 就用整理过的实体清单替换库里那份字母序前缀；
    没传就退回原样（``{entities}`` 仍由 ``_compile_prompt`` 填充），这样
    这个类在没有 store 的场景下也能用。
    """

    def __init__(self, base, store=None, vocab=None):
        self._base = base
        self._store = store
        self._vocab = vocab

    @property
    def COMPILE_PROMPT(self) -> str:  # noqa: N802 - 库里就是这个名字
        if self._store is None or self._vocab is None:
            # 没有 store 就填不出覆盖范围，整行去掉——留着占位符会让模型
            # 看到一个字面量 __COVERAGE__
            return COMPILE_PROMPT.replace("COVERAGE: __COVERAGE__\n", "")
        # 把整理好的实体直接嵌进模板，并去掉 {entities} 占位符——
        # _compile_prompt() 仍会计算它，但模板不引用就不会进 prompt。
        return COMPILE_PROMPT.replace(
            "ENTITIES: {entities}",
            "ENTITIES: " + curated_entities(self._store, self._vocab)
        ).replace("__COVERAGE__", time_context(self._store))

    @property
    def EXTRACT_PROMPT(self) -> str:  # noqa: N802 - 库里就是这个名字
        return _writing_extract_prompt(self._base.EXTRACT_PROMPT)

    @property
    def EXTRACT_PROMPT_NO_FACETS(self) -> str:  # noqa: N802
        return _writing_extract_prompt(self._base.EXTRACT_PROMPT_NO_FACETS)

    def __getattr__(self, name):
        return getattr(self._base, name)


# ---------------------------------------------------------------- 抽取

# 面向**写作**的事实抽取。库自带那份第一句就是
# "Extract durable, atomic structured facts"，目标是"以后能被问答召回"——
# 原子化、可精确定位、保留说话人。写作要的恰恰相反。
#
# 实测（terrence 的 20361 条）：16% 对写作直接无用——碎片 8.3%、纯提问 2.9%、
# 只有说话人+短语 2.9%、口语填充/ASR 噪声 1.4%；剩下 84% 也是问答形态，
# 比如「沪江维多利亚有机会。」（六个字，脱离语境没法用）、
# 「Speaker B 说硬件这个设计是没问题的。」（写作里 Speaker B 是谁不重要，
# 而且它跨会话不是同一个人）。
EXTRACT_RULES = """Extract facts that can be **written into the user's own notes later**.
SESSION DATE: {date}
SPEAKERS: {speakers}
KNOWN TOPICS: {tree}
KNOWN ENTITIES: {entities}
CONVERSATION (id|speaker|time|text):
{dialog}

This memory feeds a writing assistant, not a question-answering system. A fact
is useful only if it can be paraphrased into prose months later by someone who
was not in the room.

Rules:
- **Self-contained and load-bearing.** Each fact must carry its own context:
  what was decided or observed, the constraint or consequence attached to it,
  and the concrete numbers, dates, amounts, model names or part names involved.
  Write "the enclosure sample from the model shop cost 2300 RMB per set, which
  has to be amortised over the first 50-100 units", not "the sample cost 2300".
- **No relative time, no bare pronouns.** Write the date the session
  establishes, not the words the speaker used: "in June 2026", not "next
  month" / "later" / "currently" / "this year". Name the thing, not a pointer
  to it: "the wristband prototype", not "this plan" / "that project". This is
  the single most common defect measured in real output -- five sampled
  meetings, five identical complaints -- and it is fatal for writing, because
  a fact that says "starting this year" is unusable once it is read outside
  the conversation it came from.
- **Merge, do not atomise.** If one thing is discussed several times in this
  conversation — a number that changes, a decision that gets revised — emit ONE
  fact that carries the progression, not one fact per mention.
- **Keep real names; drop only the diarization labels.** Speaker A/B/C are
  per-session tags — the same label is a different person in another session —
  so never write "Speaker B said X" into the content. But when the transcript
  names an actual person, product, supplier or project, **keep that name in the
  fact**: "Angela is preparing for the CDNIS interview", not "a student is
  preparing for an interview". Generalising a named person into "someone" or
  "a student" destroys exactly what makes the fact worth writing about later.
  Attribution of who *said* it goes in the `who` field, not in the content.
- **Skip the noise.** Do not emit: filler and disfluency ("就是就是", "他他他"),
  ASR garbage, greetings and scheduling chatter, bare questions with no answer,
  acknowledgements, or anything under about 15 characters. An empty facts list
  is a correct answer for a conversation that carried no durable content.
- Prefer fewer, richer facts over many thin ones. Ten usable facts beat fifty
  fragments.
- "kind": one of {kinds}. "who": the person or role the fact is about.
- "t": event time as YYYY-MM-DD or YYYY-MM when stated or safely resolvable;
  otherwise null. "conf": high, med, or low.
- "topics": reuse the most specific known codes. If none fits, propose one
  specific child under a known root. "entities": named people, places,
  organizations, products, works, or other concrete named things — **never
  Speaker A/B/C style labels**.
- "src": one or more message IDs that directly support the fact.
"""


def _writing_extract_prompt(base_prompt: str) -> str:
    """把库里那份 prompt 的规则段换掉，**保留它原有的 JSON schema 段**。

    schema 段（facts/proposals/entity_types 的字段定义）必须原样保留——
    解析那一侧是库里的代码，改了 schema 就解析不出来。这里只换规则。
    """
    marker = "Return JSON only"
    i = base_prompt.find(marker)
    schema = base_prompt[i:] if i >= 0 else ""
    facets = base_prompt[base_prompt.find("Add retrieval facets"):i] if "Add retrieval facets" in base_prompt else ""
    return EXTRACT_RULES + "\n" + facets + schema
