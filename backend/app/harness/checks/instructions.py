"""用户那条指令里**代码能判准**的那几类约束（计划 6.2 / [IND] §4 的 IFEval 那条线）。

`prompt` / `custom` 两个模式的指令是用户刚打进来的，天然短而具体，里面常带着
「写三段」「不超过 200 字」「必须提到 X」这种**不需要理解、只需要数一下**的要求。
IFEval 把这类整理成 25 类可程序验证的指令，用确定性算法判——铁律第 2 条
（能用代码判准的，不交给模型）落在这里正合适：这几条交给打分模型，等于花一次
调用去数它本来就数不准的东西（`_NON_REPETITION` 九批 2160 次实测稳在 1.3 的那种
「说不清就给中间档」）。

**判据窄在哪**（铁律第 3 条：误伤比漏报贵）：

1. **只认抽取本身就确定的写法。** 「不超过 200 字」抽得准；「写短一点」
   「简明扼要」抽不准——后者一条都不抽，交给现场生成的 checklist 那一路
   （`harness/checklist.py`）让模型判。抽错一条约束的后果不是漏报，是
   **正确的产出被判不合格**，然后下一轮的诊断逼着模型去改一个本来没错的地方。
2. **验证一律取宽的那一档**（IFEval 的 loose 档）：字数带 10% 容差；
   「分三点」认「三个列表项」也认「三段」；```围栏里的代码不算进字数。
3. **判不了就不判**（`verify` 返回 `None`）：正文还是空的、字数数不出来——
   这时候「没达标」和「无从判断」分不开，跟批 16 那条「没有工具输出就不判」
   是同一条纪律。
4. **否定式先摘掉。** 「不要用表格」里也有「用表格」三个字，不先挡住就会把
   「别用表格」抽成「必须用表格」——那是最典型的一种误伤。
5. **同一类抽出两个不同的数就整类作废。** 「先写 3 段，再补 5 段」这种指令
   抽不出唯一答案，抽出来的那个必然有一半的时候是错的。

抽出来的东西只做两件事：① 挂成一条 `Check`（`instruction_constraints`），
② 告诉现场生成 checklist 的那一步「这几条程序已经判了，别再让模型判一遍」。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..state import State
from ..types import Verdict
from . import blockcheck
from .pick import pick_dimension

# 字数的容差。IFEval 分 strict / loose 两档，我们只要 loose 那一档：
# 「不超过 200 字」写了 214 字不该被判不合格——用户要的是别写长，不是卡在第
# 200 个字符上。而我们数字数的方式本身就有误差（markdown 记号、英文按词算），
# 没有容差的话误差会直接变成误伤。
TOLERANCE = 0.1

# 一条指令最多抽这么多条。抽太多等于把一条指令拆成一张长清单，`Checks` 每轮
# 只报第一条，后面那些只会拖轮数。
MAX_CONSTRAINTS = 5

_CN_NUM = {"两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
# **只认单个汉字数字**（一~十），「二十三」这种不认：多字汉字数字要写一个小解析器，
# 而它出错的那几种写法（「十二」「二十」）恰恰是最容易抽歪的。宁可漏。
_NUM = r"(\d{1,4}|[两二三四五六七八九十])"

# 段 / 点 / 条这类计数的合理范围。超出这个范围的多半不是在说产出的结构
# （「分 100 点」没人真要，「第 2024 条」是编号）。
_COUNT_RANGE = (2, 12)
# 字数的合理范围。10 字以下的限制不像是在说产出（「不超过 3 字」），
# 5000 字以上对一块 block 来说等于没限制。
_CHARS_RANGE = (10, 5000)

# 否定式：跟在这些词后面的「用表格」「提到 X」意思正好相反。
_NEG_BEFORE = re.compile(
    r"(?:不要|不用|不必|无需|不许|不能|别|勿|禁止|避免|不得|没必要|无须)\s*$")

# **「每段不超过 100 字」说的不是整块的字数。** 第一版在自己的冒烟用例上当场
# 撞到了这条：「写三段，每段不超过 100 字」抽出来的是「整块不超过 100 字」，
# 三段写下来必然超，于是**完全照做的产出被判不合格**——这正是铁律第 3 条
# （误伤比漏报贵）说的那种。按段算得先切段、再把约束摊到每一段上，而切得准不准
# 本身又是一次判断。**抽不准就不抽。**
_PER_UNIT_BEFORE = re.compile(r"(?:每|各)(?:段|点|条|部分|个|篇|行|项|节|句)\s*$")

_QUOTE_OPEN = "「『“\"'"
_QUOTE_CLOSE = "」』”\"'"

# **否定词一律当场作废，不分类型**：多摘掉一条约束只会漏报，
# 而把「别用表格」读成「必须用表格」是最典型的一种误伤。
_PATTERNS: tuple[tuple[str, str], ...] = (
    # 「最多写 200 字」「至少写 300 字」——限定词和数字之间常夹一个动词。
    ("max_chars", rf"(?:不超过|不多于|最多|别超过|不要超过)\s*(?:写|写到|给|输出)?\s*{_NUM}\s*(?:个)?字"),
    ("max_chars", rf"{_NUM}\s*(?:个)?字(?:以内|之内|以下)"),
    ("min_chars", rf"(?:至少|不少于|不低于|最少)\s*(?:写|写到|给|输出)?\s*{_NUM}\s*(?:个)?字"),
    ("min_chars", rf"{_NUM}\s*(?:个)?字以上"),
    ("min_bullets",
     rf"(?:分|列|写|给|总结|归纳|概括)(?:成|出)?\s*{_NUM}\s*(?:点|条)(?![0-9])"),
    ("min_paragraphs", rf"(?:分|写|拆)(?:成|为)?\s*{_NUM}\s*(?:个)?段(?:落)?"),
    # 表格：**必须带动词**。光有「表格」两个字可能是在说笔记里已经有的那张表
    #（「参考上面那张表格写一段」——那是材料，不是对产出的要求）。
    ("table", r"(?:用|做成|整理成|改成|输出成|以)\s*(?:markdown\s*|一张\s*)?表格"),
    ("table", r"表格(?:形式|呈现)"),
)

# 「必须提到 X」「不要出现 Y」：**只认带引号的**。不带引号时 X 的边界靠猜
#（「提到北京和上海的差异」里 X 到底是「北京」还是「北京和上海的差异」），
# 猜错就是拿一个用户没说过的词去卡产出。
_MENTION = re.compile(
    rf"(?:必须|一定|记得|需要|务必|要|请)?\s*(?:提到|提及|包含|写上|加上|带上|出现)\s*"
    rf"[{_QUOTE_OPEN}]([^{_QUOTE_CLOSE}\n]{{1,30}})[{_QUOTE_CLOSE}]")
_NOT_MENTION = re.compile(
    rf"(?:不要|不许|不能|别|禁止|避免|不得|勿)\s*(?:提到|提及|包含|出现|写|用|使用)\s*"
    rf"[{_QUOTE_OPEN}]([^{_QUOTE_CLOSE}\n]{{1,30}})[{_QUOTE_CLOSE}]")

# 同一类只能有一个值的那几类（`must_mention` / `must_not_mention` 天然可以有多条）。
_UNIQUE_KINDS = ("max_chars", "min_chars", "min_bullets", "min_paragraphs", "table")


@dataclass(frozen=True)
class Constraint:
    """一条抽出来的约束。

    `source` 是**指令里逐字的那一段**，不是重新措辞的描述：判据报错时要把它
    原样念给用户听（「你写的是『不超过 200 字』，而这一版 380 字」），
    重新措辞的话用户对不上自己写过什么。它同时也是快照里唯一能复原这条约束
    出处的东西。

    `value` 统一存成字符串（数字也是），因为 `harness/snapshot.py` 的编解码
    按字段值的类型走，一个字段两种类型是找麻烦。
    """

    kind: str
    value: str
    source: str


def _num(raw: str) -> int | None:
    raw = (raw or "").strip()
    if raw.isdigit():
        return int(raw)
    return _CN_NUM.get(raw)


def _in_range(kind: str, n: int) -> bool:
    lo, hi = _CHARS_RANGE if kind.endswith("chars") else _COUNT_RANGE
    return lo <= n <= hi


def extract(instruction: str) -> tuple[Constraint, ...]:
    """从用户那条指令里抽出**能被代码判准**的约束。抽不准的一条都不抽。"""
    text = (instruction or "").strip()
    if not text:
        return ()

    found: list[Constraint] = []
    for kind, pattern in _PATTERNS:
        for m in re.finditer(pattern, text):
            before = text[max(0, m.start() - 6):m.start()]
            if _NEG_BEFORE.search(before) or _PER_UNIT_BEFORE.search(before):
                continue
            if kind == "table":
                found.append(Constraint(kind, "1", m.group(0)))
                continue
            n = _num(m.group(1))
            if n is None or not _in_range(kind, n):
                continue
            found.append(Constraint(kind, str(n), m.group(0)))

    for m in _NOT_MENTION.finditer(text):
        found.append(Constraint("must_not_mention", m.group(1).strip(), m.group(0)))
    banned = {c.value for c in found if c.kind == "must_not_mention"}
    for m in _MENTION.finditer(text):
        word = m.group(1).strip()
        # 「不要提到『X』」同时也匹配 `_MENTION`（「提到『X』」是它的子串）。
        # 两条都留下的话，同一个词既必须出现又必须不出现，产出怎么写都不合格。
        if word in banned or _NEG_BEFORE.search(text[max(0, m.start() - 6):m.start()]):
            continue
        if word:
            found.append(Constraint("must_mention", word, m.group(0)))

    return _resolve(found)


def _resolve(found: list[Constraint]) -> tuple[Constraint, ...]:
    """去重 + 把抽出矛盾的那几类整类作废。

    **矛盾时作废整类，不是挑一个**：「先写 3 段，再补 5 段」两个数都是指令里
    真写着的，挑哪个都有一半的时候在拿错的数去卡产出。抽不准就交给 checklist
    那一路——那边是模型判，判错只是判错，不会把一条确定性的「不合格」按在
    正确的产出上。
    """
    out: list[Constraint] = []
    seen: set[tuple[str, str]] = set()
    values: dict[str, set[str]] = {}
    for c in found:
        values.setdefault(c.kind, set()).add(c.value)
    bad_kinds = {k for k in _UNIQUE_KINDS if len(values.get(k, ())) > 1}
    # 上下限自相矛盾（「至少 500 字，不超过 100 字」）同样两条都不要。
    lo = next(iter(values.get("min_chars", ())), None)
    hi = next(iter(values.get("max_chars", ())), None)
    if lo and hi and int(lo) > int(hi):
        bad_kinds |= {"min_chars", "max_chars"}
    for c in found:
        if c.kind in bad_kinds or (c.kind, c.value) in seen:
            continue
        seen.add((c.kind, c.value))
        out.append(c)
    return tuple(out[:MAX_CONSTRAINTS])


# ------------------------------------------------------------------ 验证 ---

_FENCE = re.compile(r"```.*?```", re.S)
_BULLET = re.compile(r"^\s*(?:[-*+]|\d{1,2}[.、)]|[一二三四五六七八九十]+[、.])\s+", re.M)
_CJK = re.compile(r"[一-鿿]")
_LATIN_WORD = re.compile(r"[A-Za-z0-9]+")
_SPACE = re.compile(r"\s+")


def _body(text: str) -> str:
    """去掉 ``` 围栏里的东西。

    一块 mermaid 或一段代码在用户嘴里不算「字」，算进去会让「不超过 200 字」
    在一张图上当场开火——而那张图正是工具画的、判据自己要求必须原样搬进来的。
    """
    return _FENCE.sub("\n", text or "")


def count_chars(text: str) -> int | None:
    """产出的「字数」。数不出来返回 None（＝无从判断，不开火）。

    一个汉字算一个字，一个英文单词也算一个字——用户说「不超过 100 字」时，
    100 个英文字母显然不是他要的那个 100。markdown 记号不算。
    """
    body = _body(text)
    n = len(_CJK.findall(body)) + len(_LATIN_WORD.findall(body))
    return n or None


def count_units(text: str) -> int:
    """「分三点」里的那个「点」数得出来几个。

    **取列表项和段落里多的那个**，这是有意放宽的一档（IFEval 的 loose）：
    「分三点」用三个列表项写是对的，用三个自然段写也是对的，卡死一种就是
    拿格式去罚内容。
    """
    body = _body(text)
    bullets = len(_BULLET.findall(body))
    paras = len([p for p in re.split(r"\n\s*\n", body) if p.strip()])
    return max(bullets, paras)


def _norm(text: str) -> str:
    return _SPACE.sub("", (text or "")).lower()


def verify(c: Constraint, text: str) -> bool | None:
    """这一条约束满没满足。`None` = 无从判断（不开火）。"""
    body = _body(text)
    if not (text or "").strip() or not body.strip():
        return None
    if c.kind in ("max_chars", "min_chars"):
        n = count_chars(text)
        if n is None:
            return None
        want = int(c.value)
        if c.kind == "max_chars":
            return n <= want * (1 + TOLERANCE)
        return n >= want * (1 - TOLERANCE)
    if c.kind in ("min_bullets", "min_paragraphs"):
        return count_units(text) >= int(c.value)
    if c.kind == "table":
        return blockcheck.has_table(text)
    if c.kind == "must_mention":
        return _norm(c.value) in _norm(text)
    if c.kind == "must_not_mention":
        return _norm(c.value) not in _norm(text)
    return None                     # 不认识的类型：不判，不是判不合格


def failure(c: Constraint, text: str) -> str:
    """开火时说给模型听的那句话。**先念用户的原话，再说现在是什么样**。"""
    if c.kind == "max_chars":
        return (f"用户的指令里写着「{c.source}」，而这一版有 {count_chars(text)} 字，"
                f"超了。删到 {c.value} 字以内，别靠删掉有信息量的句子来凑。")
    if c.kind == "min_chars":
        return (f"用户的指令里写着「{c.source}」，而这一版只有 {count_chars(text)} 字，"
                f"不够。接着写够 {c.value} 字，不要靠车轱辘话凑数。")
    if c.kind in ("min_bullets", "min_paragraphs"):
        unit = "点" if c.kind == "min_bullets" else "段"
        return (f"用户的指令里写着「{c.source}」，而这一版只数得出 "
                f"{count_units(text)} {unit}。按要求补够 {c.value} {unit}。")
    if c.kind == "table":
        return (f"用户的指令里写着「{c.source}」，而这一版里没有一张 markdown 表格"
                "（要有表头行和 |---|---| 分隔行）。")
    if c.kind == "must_mention":
        return f"用户的指令里写着「{c.source}」，而这一版里没有出现「{c.value}」。"
    if c.kind == "must_not_mention":
        return f"用户的指令里写着「{c.source}」，而这一版里出现了「{c.value}」。"
    return f"用户的指令里写着「{c.source}」，这一版没做到。"


def instruction_constraints(st: State) -> Verdict | None:
    """把指令里那几条可程序验证的约束逐条对一遍（计划 6.2）。

    **这条 check 不是写死在 `Mode.checks` 里的**，是 `middleware/checklist.py`
    在开跑时按这一次的指令挂上去的——`Mode` 必须是纯数据，而这条判据的内容
    （查几个字、查哪个词）来自用户刚打的那句话。

    只报第一条：`Checks` 本来就是「第一条响的赢」，一次给模型五条抱怨会换来
    一轮哪条都没改好（见 `middleware/checks.py`）。
    """
    constraints = tuple(st.bag.get("prompt_constraints") or ())
    if not constraints:
        return None
    for c in constraints:
        if not isinstance(c, Constraint):
            continue            # 快照里复原不出类时会退化成 dict，宁可不判
        if verify(c, st.content) is False:
            return Verdict(dimension=pick_dimension(st, "follows_prompt"),
                           message=failure(c, st.content))
    return None
