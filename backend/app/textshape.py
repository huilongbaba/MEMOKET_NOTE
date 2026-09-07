"""判断「重排结构」有没有偷偷改内容。

智能排版让模型决定哪行是标题、哪几句是列表——这是语义判断，规则算不出来。
但模型很容易**顺手把内容也改了**：润色几个词、合并两句、删掉一句它觉得多余的。
排版和改写是两件事，用户点「排版」不该丢内容。

这里做确定性校验：把 markdown 标记全剥掉，只留文字，比对前后。文字对不上就
说清楚差在哪，让 harness 带着这条诊断重来一轮——跟 grounding_gap 强制压
material_use 是同一个套路（见 harness-architecture 第 9 节）。
"""

from __future__ import annotations

import re

# 结构标记：行首的 #、>、列表符号、表格竖线、代码围栏
_LEADING = re.compile(r"^[ \t]*(?:#{1,6}[ \t]+|>[ \t]?|[-*+][ \t]+|\d+[.)][ \t]+)")
_FENCE = re.compile(r"^[ \t]*(?:`{3,}|~{3,})")
# 行内标记：粗体/斜体/行内代码/链接的括号部分
_INLINE = re.compile(r"\*\*|__|[*_`~]|\[|\]\([^)]*\)")
# 表格分隔行整行丢掉
_TABLE_SEP = re.compile(r"^[ \t]*\|[\s:|-]+\|[ \t]*$")


def plain_text(md: str) -> str:
    """剥掉所有 markdown 标记，只留可比较的文字。

    **空白和标点分隔一律归一**：排版本来就会动这些（补空格、换行、加空行），
    拿它们比会满屏假阳性。要抓的是「词句被改了」。
    """
    out: list[str] = []
    in_code = False
    for line in (md or "").splitlines():
        if _FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            out.append(line)                      # 代码块内容一个字都不该动
            continue
        if _TABLE_SEP.match(line):
            continue
        s = _LEADING.sub("", line)
        s = s.replace("|", " ")                   # 表格竖线是结构不是内容
        s = _INLINE.sub("", s)
        out.append(s)
    text = "\n".join(out)
    # 只比**文字**，不比空白和标点。两者都是排版的合法产物，留着比全是假阳性：
    #   · 空白：中文不靠空格分词，而排版会在中西文之间补空格
    #   · 顿号/逗号：「甲、乙、丙」拆成三个列表项时，分隔的顿号本来就该消失
    #     ——那是标点在承担结构，改成列表之后由列表符号承担
    #   · 句号/冒号：一句话变成列表项时，末尾的句号通常也跟着去掉
    #
    # 这样漏掉的只有"只改了标点"这一种情况，而内容保全现在是**结构性**保证
    # （模型不输出原文，见 app/restructure.py），这里只是兜底断言。
    # 行内序号（（1）①1、）也是结构不是内容：一行拆成列表之后，序号由列表
    # 符号承担，原来的（1）本来就该消失——跟顿号变列表项是同一回事。
    text = re.sub(r"[（(]\s*\d{1,2}\s*[）)]|[①-⑳]", "", text)
    return re.sub(r"[\s、；;，,。．.：:！!？?]+", "", text)


def _headings(md: str) -> str:
    """所有标题行的文字，按同一套规则归一。"""
    out = []
    in_code = False
    for line in (md or "").splitlines():
        if _FENCE.match(line):
            in_code = not in_code
            continue
        if not in_code and re.match(r"^[ \t]*#{1,6}[ \t]+", line):
            out.append(_LEADING.sub("", line))
    return re.sub(r"[\s、；;，,。．.：:！!？?]+", "", "".join(out))


def content_drift(before: str, after: str, *, sample: int = 3) -> str:
    """内容有没有被改。没改返回空串；改了返回一句给模型看的诊断。

    ``tolerate_added``：**新增的标题文字是合法的排版产物**——把一段话组织成
    「## 众筹节奏」+ 正文，那个标题是新写的几个字，但它是结构不是内容。所以
    少量净新增放行，而**任何删改一律拦**：排版不该让任何一句原文消失。
    """
    a, b = plain_text(before), plain_text(after)
    if a == b:
        return ""
    # 找出第一处分歧的位置，把上下文摘出来——只说"内容变了"模型无从改起
    import difflib

    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    lost: list[str] = []
    added: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("delete", "replace") and i2 > i1:
            lost.append(a[i1:i2][:60])
        if tag in ("insert", "replace") and j2 > j1:
            added.append(b[j1:j2][:60])
    # **新增的文字必须全部出现在新标题里**，才算合法的排版产物。
    #
    # 第一版是按长度容忍（"新增不超过 24 字就放行"），那是在猜——实测一段
    # 22 个字的编造分析就这么溜过去了。改成按来源判断：把一段话组织出小标题，
    # 那几个字确实是新写的；除此之外任何新增都是在写内容。
    if not lost and added:
        heads = _headings(after)
        if all(chunk in heads for chunk in added):
            return ""
    parts = []
    if lost:
        parts.append("被删掉或改写了：" + "；".join(lost[:sample]))
    if added:
        parts.append("凭空多出来了：" + "；".join(added[:sample]))
    return ("这一轮把**内容**也改了，而排版只该动结构标记（标题层级、列表、"
            "引用、段落划分），一个字都不该增删。" + " ".join(parts)
            + " 请保持每一句话的原文不变，只调整它们的结构。")
