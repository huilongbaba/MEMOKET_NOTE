"""智能排版：模型只输出「第几行改成什么结构」，原文由代码搬运。

这是这个功能的核心设计，也是它跟"让模型重写一遍"的根本区别：

    模型看到带行号的正文，输出一组操作（第 3 行提升为二级标题、
    第 5-7 行改成列表、第 9 行改成引用……）。**它一个字的原文都不用输出。**
    代码按操作去改每一行的结构标记，正文内容原样搬过去。

于是「排版顺手把内容改了」在结构上就不可能发生，而不是事后去检测——检测总有
漏网的，何况一旦漏网，用户点的是"排版"却丢了内容。

唯一允许新增文字的地方是 ``insert_heading``：把一段话组织出小标题时，那几个字
是新写的。它有长度上限，且只能新增标题行，不能碰正文。
"""

from __future__ import annotations

import re

# 行首已有的结构标记。换结构之前先剥掉，操作才是幂等的、也才能互相转换。
_MARKER = re.compile(r"^[ \t]*(?:#{1,6}[ \t]+|>[ \t]?|[-*+][ \t]+|\d+[.)][ \t]+)")
_FENCE = re.compile(r"^[ \t]*(?:`{3,}|~{3,})")

OPS = ("heading", "list", "ordered", "quote", "paragraph", "insert_heading", "split")

# 行内的显式序号：（1）/(1)/1、/1. /①。**拆点由代码按这个找，模型只说拆哪一行**
# ——让模型自己报拆点等于让它重新输出正文，那正是要避免的事。
#
# 真实文档里最该拆的一处长这样（四条并列步骤挤在一行）：
#   「…（1）智能体可以自动生成巡查任务…（2）在这个过程中…（3）事件一旦发生…
#     （4）下发指令的一段时间后…」
# 括号序号和圈号在哪都算（真实文档里就写成「比如（1）智能体…」，序号前面
# 紧跟着字，不是标点）；裸数字序号「1、」歧义大（可能是年份、条款号），
# 要求它前面是行首或标点才算。
_ENUM = re.compile(r"[（(]\s*(\d{1,2})\s*[）)]|([①-⑳])|"
                   r"(?:^|(?<=[。；;：:\s]))\s*(\d{1,2})\s*[、.]\s*(?=[^\d])")
MIN_SPLIT_ITEMS = 3
MAX_HEADING_CHARS = 40
# 一行超过这个长度就不许变成标题。**标题是短的**——真实文档上实测，模型会把
# 「大民生：什么叫大民生？过去理解民生，就是看病、上学、养老这些具体需求。
# 而大民生，是把整座城市的运行都看成民生…」这样一整段提升成三级标题，
# 目录里出现一段一百多字的"标题"，比不排版还糟。
#
# 拿真实文档量的：那篇 26714 字的汇报里，被正确识别的标题最长 22 字
# （"接下来是能源行业"那类），而被误判的两处都在 40 字以上。60 留了足够余量。
MAX_HEADING_LINE = 60

# 标题不会长成一个句子。真实文档上，长度守卫拦住了 94 字那条，却放过了
#   「## 接下来是能源行业，能源是经济社会运行的"血液"，华为解决方案目前主要
#     应用在油气、电力和矿山。」
# ——49 字，在阈值以内，但它有主谓宾、有句号，是一句话不是一个标题。
#
# 判据（任一命中即拒）：
#   · 结尾是句号/问号/感叹号 —— 标题不这么收尾（「政府：」这种冒号结尾是标题）
#   · 里面有两个以上的句读停顿，且长度过半 —— 那是在叙述，不是在命名
_SENTENCE_END = re.compile(r"[。！？.!?]\s*$")
_PAUSES = re.compile(r"[，,；;]")
# 括号里的补充说明。判断前先摘掉——真实文档里有
#   「5.展厅布局图。（从算力底座到各行业实践成果）」
# 这样的标题：编号 + 短名 + 括号补充，句号在中间。不摘掉括号的话，它既不以
# 句号结尾（结尾是「）」）又不够短，规则怎么写都容易判错。
_PAREN = re.compile(r"[（(][^）)]*[）)]")


def looks_like_sentence(text: str) -> bool:
    """这行看起来是一句话还是一个标题。

    标题是**命名**，句子是**叙述**。判据（任一命中即算句子）：
      · 摘掉括号补充之后仍以句号/问号/感叹号结尾
      · 有两个以上的句读停顿，且长度过半——那是在叙述
    """
    core = _PAREN.sub("", text).strip()
    # 编号前缀（「5.」「3、」）不算句读，它是标题的一部分
    core = re.sub(r"^\d+\s*[.、)）]\s*", "", core)
    # 句号只在**够长**的时候才算句子的信号。「展厅布局图。」这种短标题带个
    # 句号是笔误，不是在叙述——真实文档里「5.展厅布局图。（…）」就是这样。
    if len(core) > 12 and _SENTENCE_END.search(core):
        return True
    return len(_PAUSES.findall(core)) >= 2 and len(core) > MAX_HEADING_LINE // 2


def numbered(md: str) -> str:
    """给模型看的带行号正文。代码块整块标出来，让它知道那里不能动。"""
    out = []
    in_code = False
    for i, line in enumerate(md.splitlines(), 1):
        if _FENCE.match(line):
            in_code = not in_code
            out.append(f"{i:>4}│ {line}    ← 代码块边界，不要动")
            continue
        out.append(f"{i:>4}│ {line}" + ("    ← 代码块内，不要动" if in_code else ""))
    return "\n".join(out)


def body(line: str) -> str:
    """剥掉结构标记之后的内容部分。"""
    return _MARKER.sub("", line).strip()


def protected_lines(md: str) -> set[int]:
    """不能改结构的行号（1 起）：代码块内、代码块边界、表格。

    表格是一整块结构，逐行套列表/引用标记会把它拆坏。
    """
    out: set[int] = set()
    in_code = False
    for i, line in enumerate(md.splitlines(), 1):
        if _FENCE.match(line):
            in_code = not in_code
            out.add(i)
            continue
        if in_code or line.lstrip().startswith("|"):
            out.add(i)
    return out


def apply_ops(md: str, ops: list[dict]) -> tuple[str, list[str]]:
    """按操作改结构，返回 (新正文, 被跳过的操作说明)。

    **原文只在这里被搬运，不经过模型。** 任何一条操作只改行首的结构标记，
    或者插入一行新标题；正文一个字都不会变。
    """
    lines = md.splitlines()
    protect = protected_lines(md)
    skipped: list[str] = []
    # line 号 → 要套的新标记；insert 单独存，最后从后往前插（不然行号会错位）
    marks: dict[int, str] = {}
    splits: dict[int, str] = {}
    inserts: list[tuple[int, str]] = []

    for op in ops:
        if not isinstance(op, dict):
            continue
        kind = str(op.get("op", "")).strip()
        if kind not in OPS:
            skipped.append(f"不认识的操作 {kind!r}")
            continue
        if kind == "insert_heading":
            at = int(op.get("before", 0) or 0)
            text = str(op.get("text", "")).strip()
            level = max(1, min(6, int(op.get("level", 2) or 2)))
            if not text:
                skipped.append("insert_heading 没给标题文字")
                continue
            if len(text) > MAX_HEADING_CHARS:
                # 标题是唯一允许新增文字的地方，必须短——长了就是在写内容
                skipped.append(f"新标题太长（{len(text)} 字），只允许 {MAX_HEADING_CHARS} 字以内")
                continue
            if at < 1 or at > len(lines) + 1:
                skipped.append(f"insert_heading 的位置 {at} 超出范围")
                continue
            inserts.append((at, "#" * level + " " + text))
            continue

        ln = int(op.get("line", 0) or 0)
        if ln < 1 or ln > len(lines):
            skipped.append(f"行号 {ln} 超出范围")
            continue
        if ln in protect:
            skipped.append(f"第 {ln} 行在代码块或表格里，不动")
            continue
        if not body(lines[ln - 1]):
            skipped.append(f"第 {ln} 行是空行，不动")
            continue
        if kind == "heading":
            text = body(lines[ln - 1])
            if len(text) > MAX_HEADING_LINE:
                skipped.append(f"第 {ln} 行有 {len(text)} 字，太长了不像标题，保持原样")
                continue
            if looks_like_sentence(text):
                skipped.append(f"第 {ln} 行是一句话不是标题，保持原样：{text[:24]}…")
                continue
            level = max(1, min(6, int(op.get("level", 2) or 2)))
            marks[ln] = "#" * level + " "
        elif kind == "list":
            level = max(0, min(4, int(op.get("indent", 0) or 0)))
            marks[ln] = "  " * level + "- "
        elif kind == "ordered":
            marks[ln] = "1. "          # 具体编号交给格式化器统一重排
        elif kind == "quote":
            marks[ln] = "> "
        elif kind == "split":
            splits[ln] = "1. " if str(op.get("marker", "")) == "ordered" else "- "
        else:                           # paragraph：降级成普通段落
            marks[ln] = ""

    out: list[str] = []
    for i, line in enumerate(lines):
        n = i + 1
        if n in splits:
            lead, items = split_enumerated(body(line))
            if items:
                # 引子是这组列表的引言，**不套列表标记**
                if lead:
                    out.append(lead)
                out.extend((splits[n] + it) for it in items)
                continue
            skipped.append(f"第 {n} 行找不到 {MIN_SPLIT_ITEMS} 个以上的显式序号，没拆")
        out.append((marks[n] + body(line)) if n in marks else line)
    for at, text in sorted(inserts, key=lambda x: -x[0]):
        out.insert(at - 1, text)
    return "\n".join(out), skipped


def split_enumerated(text: str) -> tuple[str, list[str]]:
    """按行内显式序号把一行拆成 (引子, 条目列表)；拆不出来返回 ("", [])。

    **序号本身去掉**——它是标点在承担结构，改成列表之后由列表符号承担，
    跟「甲、乙、丙」拆成三项时顿号消失是同一回事。序号前面的引子
    （「比如针对一些特定的事件，」）保留成第一段。
    """
    marks = list(_ENUM.finditer(text))
    if len(marks) < MIN_SPLIT_ITEMS:
        return "", []
    # 序号必须是从小到大连着的，否则那多半是正文里偶然出现的数字
    nums = []
    for m in marks:
        g = m.group(1) or m.group(3)
        nums.append(int(g) if g else (ord(m.group(2)) - 0x2460 + 1))
    if nums != list(range(nums[0], nums[0] + len(nums))):
        return "", []
    out: list[str] = []
    lead = text[:marks[0].start()].strip()
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        piece = text[m.end():end].strip()
        if piece:
            out.append(piece)
    if len(out) < MIN_SPLIT_ITEMS:
        return "", []
    # 引子单独占一行，不做成列表项——它是这组列表的引言。
    #
    # 太短的（「比如」这种连接词）**并进第一项，不能丢**：漂移校验当场抓到了
    # 我第一版把它删掉——那确实是在删内容。好看不是删字的理由。
    if len(lead) < 6:
        # 太短的（「比如」这种连接词）并进第一项，**不能丢**——漂移校验当场抓到
        # 我第一版把它删掉了，那确实是在删内容。好看不是删字的理由。
        return "", ([lead + out[0]] + out[1:]) if lead else out
    return lead, out
