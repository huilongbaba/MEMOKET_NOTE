"""命题比对：这一轮写出来的具体说法，逐条去对那份封闭的本地材料。

**这是 `checks/numbers.py` 的同一条线往「带具体名字的陈述」上扩**（计划 7.1，
依据 [IND] §8①）。批 16 已经把「数字」这一类做成了 decompose-then-verify：
正文里的每个数 → 跟工具返回逐个 diff。这里做的是同一件事，只是原子换了一类。
**没有另起一套**：源头那一侧（`numbers.sources`）、容差之外的「没有 oracle
就不判」（`numbers.has_tool_output`）、以及「先窄再说」的纪律全部复用。

## 为什么值得做（这是第一大阻塞项）

`factual_grounding` 实测 **41% 不达标、11 次 0 分**，而它整条交给了一个跟
写作那一步同一个模型的打分器。行业那条线（FActScore / SAFE / VeriScore /
Claimify）统称 **decompose-then-verify**：把长文拆成原子命题，逐条对来源。
**我们的条件比论文里还好**——它们要去 Google 搜证据，我们的来源是一个
封闭的本地知识库，而且这一次跑累积的那份材料就在手上（`st.facts` /
`bag["facts_all"]`，批 8 接进打分器、批 15 改成只追加）。

## SAFE 的三步，逐条落在哪

| SAFE | 我们 |
|---|---|
| ① 抽命题 | `decompose()`：**句级**。粒度是量出来的，见下一节 |
| ② 改写以消解指代不清 | **结构上不需要**：我们的原子是**表面字面量**（一个完整日期、一个署名里的名字），指代不清这件事对字面量不成立。论文要改写是因为它的原子是自然语言命题，脱离上下文就没法查；我们的原子脱离上下文照样查得动。**这是「封闭语料 + 字面原子」白捡的那一半** |
| ③ 相关性检查：这条值不值得查 | `relevant()` + **整条流水线只有一个方向**：正文 → 源头。源头里有、正文里没有的东西**结构上产生不了任何裁决**。这正是 `_FACTUAL_GROUNDING` 里那条吃过亏才写进 guidance 的规矩（「检索到的事实没有被全部用上，明确不算不足」——为它扣过一次分，下一轮正文里就「引入了大量未在知识库中出现的具体日期与人物」）。**以前它是一段指望模型自觉的文字，现在它是这个模块里一条走不通的路**，另有一条单测钉着 |

## 拆解粒度是量出来的，不是拍的

`Decomposition Dilemmas` 那篇专门在问拆解到底是帮忙还是添乱——**拆得太碎会
丢语境、制造无法验证的碎片**。所以粒度当成一个要量的参数，在 24 篇
`origin=user` 真实笔记（非空 18 篇，走 `corpus_lineage`）上量了三档：

| 粒度 | 单元数 | 平均字数 | **碎片率**（带指代、单元内找不到先行词） |
|---|---:|---:|---:|
| 段级 | 683 | 113.2 | 6.1% |
| **句级** | **1446** | **53.4** | **8.1%** |
| 子句级 | 5903 | 13.1 | 4.2% |

子句级的碎片率看着最低是个**假象**：切到平均 13 个字，大部分单元里连一个
指代词都没有（分母被"什么都不含的碎渣"灌满了），而 5903 个单元里真正带
可查原子的不到 2%。段级的问题在另一头：平均 113 字，报出来模型不知道该改
哪一句——`no_placeholder` 第 601 轮那次死锁就是「拿整段说事、模型改不动」。
**句级是两头都不塌的那一档**，所以取句级。

## 原子只取两类，另外四类**量完之后明确不取**

留下的两类，在同一批语料上**两个档都 0 开火**：

| 原子 | 自源头档候选 / 开火 | 严苛档候选 / 开火 |
|---|---:|---:|
| 完整日期（年月日三字段齐全） | 8 / **0** | 0 / **0** |
| 署名里的那个拉丁名字（`X 说 / 提到 / 确认…`） | 17 / **0** | 6 / 5 ⚠ |

*自源头档* = 批 16 那套（整篇同时当产出和源头，按定义一次都不该开火）。
*严苛档* = 每篇后 30% 当「这一轮写的」、前 70% 当**唯一**源头——生产里源头
还包含全部事实和工具返回，所以这一档是**上界**，不是生产值。署名那一栏的
5 次开火全是 `Speaker A/C/D`、`Aaron` 这类**真人**，他们在生产里由事实块带进来
（`_fmt_facts` 的 `（日期 · Speaker A · 类型）`）；真跑那一侧另外量过（台账批 18）。

**不取的四类，每一类都对着一个实测数字**：

1. **两个字段的日期**（「3 月 31 日」「2026 年 6 月」）：严苛档 23 个候选
   **开火 5 次（21.7%）**，五次全是用户自己笔记里真有的日期。
   一个会把真日期报成编造的判据，正是铁律里最贵的那一档。
2. **中文人名**：18 篇真实笔记 + 16 篇脚本产出里**总共 4 个候选，3 个是错的**
   ——`江汽`（江淮汽车的简称）两次、`方案已`（从「方案已确认」里切出来的碎渣）
   一次。这是 `Decomposition Dilemmas` 说的「制造无法验证的碎片」的字面版本。
   姓氏表 + 言说动词这条启发式在中文上不成立，**整类不要**。
3. **所有拉丁专名**（不要求带言说动词）：严苛档 97 个候选**开火 44 次（45.4%）**，
   开火的东西是 `Zoom` / `Discord` / `Apple` / `Harvard`（世界知识，不是对
   用户项目的断言）、`GWh` / `MWh` / `Wh`（单位）、`This` / `You` / `After`
   （句首的普通英文词）、`Ims` / `Scm` / `DeepSeck`（语音转写的错字）。
   **「专名」这个类本身就把世界知识和用户专属断言混在一起了**，没法靠停用词救。
4. **正文里的统计量**（`numbers.prose_statistics`，批 16 已经在 eda/analysis
   上用着的那一条）：严苛档 167 个候选**开火 79 次（47.3%）**。长文跟 eda
   不一样——eda 的 task 明写「所有数字都来自工具返回，不要自己算」，长文
   没有这条规矩，模型把三条材料的数合计一下、把「4500 万」换算成「0.45 亿」
   都是**对的写法**，而 0.5% 的相对容差救不了合计和换算。**这一类留在
   eda / analysis 那条道上，不进长文。**

## 判据窄在哪（除了上面的选类，还有四道）

1. **只判这一轮写的**（`st.fresh`），不判整篇。用户自己原来那几段里的名字和
   日期不是这次跑写的——`citations_present` 早就是这个规矩（「用户自己原来
   那些段落没有引用是正常的」）。
2. **源头宁可多给**：整篇笔记 + 这次跑之前已经写出来的部分 + 用户那条指令 +
   这次跑累积的全部事实 + 工具返回 + 画过的图。**多给一处源头只会漏，少给
   一处就会误伤。**
3. **没有源头就不判**：手上一条材料、一次工具调用都没有的时候，「查无出处」
   和「无从判断」分不开——跟批 16 那条「没有工具输出就不判」是同一条纪律。
4. **围栏 / 表格 / 引用块里的不取**：mermaid 节点名里的日期是图的内容
   （`grounding_rules.placeholder_lines` 那条「图里的节点名是内容，不是占位」
   同一个道理）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..state import State
from ..types import Verdict
from . import numbers
from .pick import pick_dimension

# ------------------------------------------------------------ ① 拆解 ---

# 句级。**不切子句**：切到「，」以下平均 13 个字，原子还在、语境没了。
_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")
_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.M)
_QUOTE_ROW = re.compile(r"^\s*>.*$", re.M)
_LINK = re.compile(r"!?\[[^\]]*\]\([^)]*\)")

# 单元里出现它 = 带指代。粒度那张表的「碎片率」用的就是这一条。
_ANAPHOR = re.compile(r"这(?:个|些|项|次|一|类|种|条|批)?|该(?:项|批|条|方案|产品|功能)?"
                      r"|其(?:中|余|他|它)?|此(?:外|前|后|处)?|上述|前者|后者")


def _strip_uncheckable(text: str) -> str:
    """围栏 / 行内代码 / 表格 / 引用块 / 链接地址一律挖掉，见窄化第 4 条。"""
    t = _FENCE.sub(" ", text or "")
    t = _INLINE_CODE.sub(" ", t)
    t = _LINK.sub(" ", t)
    t = _TABLE_ROW.sub(" ", t)
    t = _QUOTE_ROW.sub(" ", t)
    return t


def decompose(text: str) -> list[str]:
    """正文 → 句级单元。粒度为什么是句级见模块文档那张表。"""
    return [s.strip() for s in _SENT_SPLIT.split(_strip_uncheckable(text)) if s.strip()]


def has_anaphor(unit: str) -> bool:
    """这个单元带不带指代。**只给量粒度用**，不参与裁决。

    SAFE 的第二步（改写以消解指代）我们不做，因为我们的原子是字面量；
    但「拆碎了会丢语境」这件事本身要量得出来，否则粒度那个参数就是拍的。
    """
    return bool(_ANAPHOR.search(unit or ""))


# ------------------------------------------------------------ ② 原子 ---

@dataclass(frozen=True)
class Atom:
    kind: str           # "date" / "attributed"
    surface: str        # 正文里的原样写法，报给模型看的就是它
    key: object         # 比对用的规范形式
    unit: str           # 它所在的那一句（报出来让模型知道改哪一句）


# 完整日期：`2026 年 8 月 5 日` / `2026-08-05` / `2026/8/5`。
# **三个字段必须齐全**——两个字段那一档实测 21.7% 误伤，见模块文档「不取的四类」①。
_DATE_FULL = re.compile(
    r"(?<![\d])(\d{4})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})\s*[日号]?(?![\d])")
# 源头那一侧另外认「年月」和「月日」两种残缺写法，**只用来放宽匹配、不用来抽原子**：
# 事实块里写 `2026-08`、正文里写 `2026 年 8 月 5 日` 时，日那一位确实是新的，
# 但把它报成「编造」太狠——所以源头有 (年,月) 就算这条日期有出处。
_DATE_YM = re.compile(r"(?<![\d])(\d{4})\s*[-/年.]\s*(\d{1,2})(?![\d:])")
_DATE_MD = re.compile(r"(?<![\d])(\d{1,2})\s*月\s*(\d{1,2})\s*[日号](?![\d])")

# 署名：一个名字**紧跟**着一个言说 / 决定动词。
# 「紧跟」是这一类全部的窄化所在：不要求动词，这一类就退化成「所有拉丁专名」
# ——那一档实测 45.4% 误伤（Zoom / GWh / This），见模块文档「不取的四类」③。
_SPEECH = (r"(?:说|讲过|讲|提到|提过|表示|认为|指出|强调|确认|答复|回复|建议|"
           r"要求|拍板|决定|负责|承诺|反馈|问过)")
_ATTRIBUTED = re.compile(
    rf"(?<![A-Za-z])([A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)?)\s*(?={_SPEECH})")

# 长得像名字、其实是普通词。**这份名单是实拍出来的**：24 篇真实笔记里
# 「Owner 负责准确性与时效性」当场把 `Owner` 抽成了人名。
# 顺带把句首常见的英文词收进来——中文笔记里它们只会以「句首大写」的身份出现。
_NOT_A_NAME = {
    "owner", "app", "beta", "preview", "agent", "top", "team", "product",
    "design", "customer", "manufacturer", "insights", "note", "notes",
    "this", "that", "these", "those", "you", "we", "they", "it", "he", "she",
    "after", "before", "when", "while", "the", "and", "but", "for", "with",
    "ok", "yes", "no", "all", "one", "two", "some", "any", "new", "old",
}


def _date_key(y: int, mo: int, d: int) -> tuple[int, int, int]:
    return (y, mo, d)


def date_atoms(unit: str) -> list[Atom]:
    """这一句里的完整日期。"""
    out: list[Atom] = []
    for m in _DATE_FULL.finditer(unit):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= 2200):
            continue
        out.append(Atom("date", m.group(0).strip(), _date_key(y, mo, d), unit))
    return out


def _norm_name(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip())


def attributed_atoms(unit: str) -> list[Atom]:
    """这一句里「谁说了 / 谁决定了」中的那个名字。"""
    out: list[Atom] = []
    for m in _ATTRIBUTED.finditer(unit):
        name = _norm_name(m.group(1))
        if name.lower() in _NOT_A_NAME:
            continue
        if len(name.replace(" ", "")) < 2:
            continue
        out.append(Atom("attributed", name, name.lower(), unit))
    return out


def atoms(text: str) -> list[Atom]:
    """正文 → 逐句拆开之后能机械核对的那些原子。"""
    out: list[Atom] = []
    for unit in decompose(text):
        out += date_atoms(unit)
        out += attributed_atoms(unit)
    return out


# ------------------------------------------------- ③ 相关性：值不值得查 ---

def relevant(atoms_: list[Atom]) -> list[Atom]:
    """SAFE 第三步：这一条值不值得去核对。

    **这个函数存在的意义有一半是它没有的那一半**——它只会从「正文里出现的
    原子」里往下筛，永远不会因为「源头里有、正文里没写」而产生一条原子。
    `_FACTUAL_GROUNDING` 的 guidance 里那条规矩（「检索到的事实没有被全部
    用上，明确不算不足」）在这里是**结构上的**，不是一句劝告：
    反方向那条路在这个模块里根本不存在。有单测钉着这个性质。

    真正筛掉的只有一种：同一个原子在这一轮里反复出现，只查一次。
    """
    seen: set[tuple[str, object]] = set()
    out: list[Atom] = []
    for a in atoms_:
        sig = (a.kind, a.key)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(a)
    return out


# ------------------------------------------------------------ ④ 比对 ---

def source_keys(text: str) -> dict[str, set]:
    """源头那一侧：能核对的东西按类摊平。"""
    dates: set[tuple[int, int, int]] = set()
    body = text or ""
    for m in _DATE_FULL.finditer(body):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        dates |= {(y, mo, d), (y, mo, 0), (0, mo, d)}
    for m in _DATE_YM.finditer(body):
        dates.add((int(m.group(1)), int(m.group(2)), 0))
    for m in _DATE_MD.finditer(body):
        dates.add((0, int(m.group(1)), int(m.group(2))))
    return {"date": dates, "text": {re.sub(r"\s+", " ", body).lower()}}


def supported(atom: Atom, keys: dict[str, set]) -> bool:
    """这一条原子在源头里对得上吗。

    日期：三字段全等，或者源头只给到「年月」而正文多写了一个日——**那也算
    对上**。多出来的那个日确实没出处，但把它判成「编造」会逼模型去删一句
    本来有依据的话，而铁律是**误伤比漏报贵**。
    署名：忽略空白、忽略大小写的逐字包含。
    """
    if atom.kind == "date":
        y, mo, d = atom.key                     # type: ignore[misc]
        pool = keys.get("date") or set()
        return (y, mo, d) in pool or (y, mo, 0) in pool
    blob = next(iter(keys.get("text") or {""}))
    return str(atom.key) in blob


# ------------------------------------------------------------ 判据本体 ---

# 这一轮写得太少就不判：一两句话里蹦出一个日期，多半是承接上文，
# 而这时候"上文"还没进源头（跨轮那部分靠 `st.content` 补，见 `sources`）。
MIN_FRESH_CHARS = 120
# 一次最多报几条。报一串模型会挑着改，跟 `Checks` 只报第一条判据是同一个道理。
MAX_REPORT = 3


def fresh_text(st: State) -> str:
    """这一轮真的写出来的那部分。"""
    return (st.fresh or "").strip()


def sources(st: State) -> str:
    """能当出处的全部文字。**宁可多给**，见模块文档窄化第 2 条。

    在 `numbers.sources`（整篇笔记 + 指令 + 选区 + 全部事实 + 工具返回 + 图）
    之上再补一样：**这次跑在这一轮之前已经写出来的部分**。长文是一轮一轮
    往后接的，第 3 轮写的名字可能是第 1 轮引进来的——那不是这一轮编的。
    """
    prior = st.content or ""
    fresh = st.fresh or ""
    if fresh and prior.endswith(fresh):
        prior = prior[: len(prior) - len(fresh)]
    elif fresh and fresh in prior:
        # 产出之后被清洗过（`scrub_meta_sentences`）时 `endswith` 会落空。
        prior = prior.replace(fresh, " ")
    return numbers.sources(st) + "\n" + prior


# ------------------------------------ ④ 这一轮到底判没判（批 27 / §5 第 8 行）---
#
# `abstained` 的取值表。**加一列之前先把它的取值列全，再逐个问"真写得进去吗"**
# ——批 22 的 `stopped` 那一列从加进来那天起就记不到 `max_rounds`，规矩就是
# 那么来的。这五个取值各自由谁写进去：
#
# | 取值 | 谁写得进去 |
# |---|---|
# | `not_in_mode` | 六个 block 模式任何一轮（它们的 `checks` 里没有这一条） |
# | `too_short` | 这一轮新写的不足 `MIN_FRESH_CHARS`（打磨轮 / 清理轮常态） |
# | `no_oracle` | 工具一次都没返回东西的轮（`numbers.has_tool_output` 为假） |
# | `no_atoms` | 写了一大段、但里头一个完整日期 / 一个署名都没有 |
# | `judged` | 真的逐条比对过了（比完过没过是另一件事，看 `fired_checks`） |
#
# 库里还会有第六种：**空串**。那是批 27 之前落的行的 `DEFAULT ''`，
# **活着的跑一次都写不出它**——这件事写在这儿，免得下一个人把它当成一档。
NOT_IN_MODE = "not_in_mode"
TOO_SHORT = "too_short"
NO_ORACLE = "no_oracle"
NO_ATOMS = "no_atoms"
JUDGED = "judged"


def probe(st: State) -> tuple[list[Atom], str]:
    """`(候选原子, 判没判 / 为什么没判)`。**纯函数、零调用。**

    它和 `unsupported_specifics` **共用同一段前置判断**，而且是后者调它——
    另写一份"跟判据一样的前置条件"，判据一改这一列量的就不是同一件事了
    （跟 bench 那条「判据必须是生产那个函数」同一条纪律）。

    **候选原子数照算，不因为弃权就记 0**：「这一轮没有候选原子」和「这一轮
    压根没去看」是两件事，而 §5 第 8 行问的正是前者（候选原子率）。
    """
    text = fresh_text(st)
    cands = relevant(atoms(text))
    if len(text) < MIN_FRESH_CHARS:
        return cands, TOO_SHORT
    if not numbers.has_tool_output(st):
        return cands, NO_ORACLE
    if not cands:
        return cands, NO_ATOMS
    return cands, JUDGED


def unsupported_specifics(st: State) -> Verdict | None:
    """这一轮写的具体日期 / 署名，有没有在封闭材料里查无此事（计划 7.1）。

    三档不判的理由：正文太短没什么可判；**手上没有任何材料时「查无出处」和
    「无从判断」分不开**（这一档由 7.2 的 `material_thin` 去说「你还没查 /
    库里没有」，那才是能照办的诊断）；没有候选原子就没有可判的东西。
    三档由 `probe` 统一给出——这一列量的必须是判据自己那套条件。
    """
    cands, why = probe(st)
    if why != JUDGED:
        return None
    keys = source_keys(sources(st))
    bad = [a for a in cands if not supported(a, keys)]
    if not bad:
        return None
    lines = []
    for a in bad[:MAX_REPORT]:
        unit = a.unit if len(a.unit) <= 60 else a.unit[:60] + "…"
        lines.append(f"「{a.surface}」（出现在：{unit}）")
    more = f"，另有 {len(bad) - MAX_REPORT} 处同样查不到" if len(bad) > MAX_REPORT else ""
    return Verdict(
        pick_dimension(st, "factual_grounding", "no_fabrication", "material_use"),
        "这一轮写的这几个具体说法，在这篇笔记和这次查到的全部材料里都找不到出处："
        + "；".join(lines) + more + "。"
        "**只改这几处**：换成材料里真有的那个日期 / 名字，或者把这句话改成不带"
        "具体日期和署名的说法。**别去动别的句子**——这条判的只是上面列出来的"
        "那几个字面。（材料里没用上的那些事实不用管，这条跟用了多少材料无关。）",
    )
