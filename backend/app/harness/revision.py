"""Locating and applying revisions -- pure functions, no I/O.

Moved out of the 1078-line note_harness router, where writing_plan had to
reach across and import them. Two routers importing each other is how a
dependency graph stops being drawable, and these were the last case of it.

**Carried over verbatim.** Every guard here was paid for by a real failure,
and the point of this move is to change where they live, not what they do:

* **Ambiguous anchors mangle text.** A short anchor occurring three times,
  applied to the first, cuts somewhere arbitrary. But the first version of
  that guard was too strict and rejected "delete the duplicated section" --
  an operation whose anchor *must* repeat. Twenty runs later non_repetition
  scored 0 every single time and coherence had fallen to 0.5, because
  deduplication had been switched off entirely. The surviving rule is narrow:
  reject only a bare ``replace`` whose anchor is ambiguous *and* unbounded.
* **The model argues with itself.** Left alone it rewrites the same passage
  three rounds running with nothing but wording changes. Similarity above
  0.62 counts as "the same thing said differently" and is dropped -- measured
  on real output, where the rewrites of one passage sat at 0.78-0.91 while
  every revision that actually changed something came in under 0.5.
* **Broken words.** A span that starts or ends mid-word leaves visibly
  mangled output, and only *newly* broken words count -- text that was
  already broken isn't this revision's fault.

The comments below are the original ones; they carry the specific evidence.
"""

from __future__ import annotations

import difflib
import re


# 同义重写的判定阈值。0.62 是在真实产出上量出来的：实测被反复重写的那段
# 「因此，ask memory 进入本版。它被视为 2026 年 3 月 15 日版本的显著差异点…」
# 三个版本之间两两相似度 0.78~0.91，而真正改出了东西的修订都在 0.5 以下。
_REWRITE_SAME = 0.62


# 修订切错位置留下的残骸。用户要求"锚点用少的字符数去 match，别把整段原文
# 抄一遍"之后，锚变短了，``content.find(anchor)`` 找的是第一次出现——正文里
# 同样的开头出现两次时就会切在错误的地方。真实产出里抓到的破字：
#     「不要把未计算的节点写成已确定日期：、设计稿确认、页面开发、测试……」
# 「日期：」后面直接跟顿号，是前半句被换掉、后半截留在原地的残骸。
# 标点连缀是确定性可查的，比让模型自己检查靠谱。
_BROKEN = re.compile(r"[：:，,。.；;！!？?]\s*[、，,；;。.]"      # 标点连缀
                     r"|(?:^|\n)\s*[、，,；;]"                  # 句子以顿号/逗号起头
                     r"|[，、]\s*(?:\n\n|$)")                   # 段落以顿号/逗号收尾


def _tidy_blank_lines(content: str) -> str:
    """把连续空行压回一个。

    delete 一条修订会留下 ``前段\n\n`` + ``\n\n后段``——两组段落分隔符
    并在一起变成三个空行；insert 也会在少数拼接位置多带一个。单看每条
    修订都没错，攒起来读者就看见正文里一块块的空白。这个只在自动批量
    应用完一轮之后做一次，纯格式归一化，不动任何文字。

    代码块里的空行是内容不是格式，用 ``` 围栏计数跳过。
    """
    out: list[str] = []
    in_fence = False
    blanks = 0
    for line in content.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and not line.strip():
            blanks += 1
            if blanks > 1:
                continue
        else:
            blanks = 0
        out.append(line.rstrip() if not in_fence else line)
    return "\n".join(out)


def _breakage(before: str, after: str) -> str:
    """这条修订有没有把正文切出破字。只报**新增**的破损，原文本来就有的不算。"""
    was = len(_BROKEN.findall(before))
    now = _BROKEN.findall(after)
    if len(now) <= was:
        return ""
    return "".join(now[-1].split())


def _locate(content: str, anchor: str, anchor_end: str) -> tuple[int, int]:
    """这条修订要动的区间 ``[起, 止)``。找不到返回 ``(-1, -1)``。

    anchor 在正文里出现多处时，取**跨度最小**的那一组 (anchor, 其后最近的
    anchor_end)。这是去重场景的正确语义：

        ## 众筹节奏      ← anchor 第一处
        三月上旬启动。
        ## 众筹节奏      ← anchor 第二处
        三月上旬启动众筹。 ← anchor_end

    「删掉重复的那一节」给出的就是这一对。从第一处 anchor 往后找 anchor_end，
    会把两节整个删掉；取最小跨度才落在第二节上。

    第一版这里是"anchor 有多处就一律丢弃"，结果把去重功能干掉了：20 轮实测
    重复标题那篇 ``non_repetition`` 全 20 次 0 分、``coherence`` 掉到 0.5。
    """
    i = content.find(anchor)
    if i < 0:
        return -1, -1
    if not anchor_end:
        return i, i + len(anchor)
    first, best = i, (-1, -1)
    while i >= 0:
        j = content.find(anchor_end, i + len(anchor))
        if j >= 0:
            end = j + len(anchor_end)
            if best[0] < 0 or end - i < best[1] - best[0]:
                best = (i, end)
        i = content.find(anchor, i + 1)
    # 结尾标记一次都没匹配上时退回只用 anchor：宁可少改一点，也不要按错误的
    # 范围改，更不要因为一个写错的结尾标记就整条丢弃。
    return best if best[0] >= 0 else (first, first + len(anchor))


def _replaced_span(content: str, anchor: str, anchor_end: str) -> str:
    """这条修订将要替换掉的那段原文。"""
    i, j = _locate(content, anchor, anchor_end)
    return content[i:j] if i >= 0 else ""


def _is_same_meaning_rewrite(old: str, new: str) -> bool:
    """改了等于没改：只换了几个词的同义重写。

    真实观测（种子「这一轮产品取舍」，3 轮）：同一个锚
    ``因此，`ask memory` 进入本版。`` 被 replace 了三次，每次只加几个定语：

        1  …即使 integration 还不能完全实现，也不能因此把 ask memory 一起往后推。
        2  …主要围绕用户自己的录音和记忆内容回答问题，即使 integration 还不能…
        3  …主要基于用户自己的录音和记忆内容回答问题，并计划支持多轮对话。即使…

    第 2 轮甚至先 delete 掉第 1 轮刚 insert 的 300 字，再 replace 同一处——
    **编辑 pass 在跟自己打架**。这直接造成三个现象：delta 为 0 的轮次字数照涨、
    ``non_repetition`` 永远停在 1、以及用户那句"感觉啥也没改"。

    根因是编辑 pass 每轮独立跑，没有任何东西告诉它上轮改过哪儿。提示词层面
    说"不要重复修订"这类元指令整晚验证过是不管用的，所以在应用阶段硬拦。
    """
    old, new = old.strip(), new.strip()
    if not old or not new or len(old) < 24:
        return False       # 短锚点（标题、编号）本来就该允许小改
    return difflib.SequenceMatcher(None, old, new).ratio() > _REWRITE_SAME


def reject_revision(content: str, op: str, anchor: str, text: str,
                    anchor_end: str = "", edited: set[str] | None = None) -> str:
    """这条修订该不该丢。要丢就返回一句给用户看的理由，否则返回空串。

    三类都是在真实产出上抓到的，且都是**确定性可判**的——整晚反复验证过，
    这类"别重复改""别切坏"的元指令写进提示词不管用，只有在应用阶段硬拦有效。

    ``note_harness`` 和 ``writing_plan`` 共用 ``_apply_revision``，所以这三道
    防线也必须共用：只修一边，等于另一条路径上的 bug 还活着。
    """
    key = " ".join(anchor.split())[:40]
    if op == "replace" and edited is not None and key in edited:
        return f"这处上一轮已改过，跳过：{key[:24]}…"
    if op == "replace" and _is_same_meaning_rewrite(
            _replaced_span(content, anchor, anchor_end), text):
        return f"这条只是换了措辞，没改出东西，已丢弃：{key[:24]}…"
    if op == "replace" and not anchor_end and content.count(anchor) > 1:
        # 只有"光秃秃的 replace + 锚点多处"才真的无法消歧：没有 anchor_end
        # 划出范围，改哪一处都说得通，切错的代价是正文被破坏。
        #
        # 其余两种都能确定地解决，不该拦：
        #   - 光秃秃的 delete：「删掉重复的那个标题」本来就要求锚点出现多次，
        #     两处内容一样，删哪个都对。
        #   - 带 anchor_end 的：交给 _locate() 取最小跨度那一组。删「重复的
        #     那一节」给出的正是这个形态，第一版把它拦了，直接干掉去重功能
        #     （20 轮实测 non_repetition 全 20 次 0 分、coherence 掉到 0.5）。
        return f"这个位置在正文里有多处、又没给结尾标记，改哪个说不准：{key[:24]}…"
    return ""


def _apply_revision(content: str, op: str, anchor: str, text: str,
                    insert_offset: int = 0, anchor_end: str = "") -> str:
    """前端 RevisionPanel.tsx 的 applyRevision() 用的是同一套锚点语义，这里
    是要在没有人工审核的情况下自动应用，所以后端自己实现一份——不能指望
    前端那份，那是给用户点"接受"用的，只在浏览器里跑。

    ``insert_offset``：本轮已经为同一个锚点插入过多少字符。批量自动应用
    多条修订时，第二条 insert 必须插在第一条插入的内容**之后**，否则会
    紧贴锚点、把先插的内容顶到后面去，顺序就颠倒了（见调用方注释里记的
    真实 bug）。单条应用（前端逐条接受）时保持 0，行为跟以前完全一致。"""
    # 给了结尾标记时，要动的是"起始标记开头 → 结尾标记结尾"这一整段：模型
    # 只要回显两个短标记，不用把整段原文抄一遍。anchor 有多处时按最小跨度
    # 消歧（见 _locate）。找不到结尾标记就退回只用 anchor，宁可少改一点也
    # 不要按错误的范围改。
    i, end = _locate(content, anchor, anchor_end)
    if i < 0:
        return content  # 锚点在当前正文里找不到了（可能已经被上一条修订动过），跳过这条
    if anchor_end and end <= i + len(anchor):
        end = i + len(anchor)
    if op == "insert":
        end += insert_offset
        return content[:end] + text + content[end:]
    if op == "insert_before":
        return content[:i] + text + content[i:]
    if op == "delete":
        return content[:i] + content[end:]
    return content[:i] + text + content[end:]  # replace


def _expand_sources(raw: list, facts: list[str]) -> list[str]:
    """把模型给的简短来源标记还原成完整事实。

    知识库事实进 prompt 时都带方括号前缀（``[2026-04-10]`` 或
    ``[terrence-2046-2F3]``），所以模型只要回显标记就够定位。之前的契约是
    让它把整条事实抄回来——一条修订依据六条事实就是几百字的重复输出，
    而输出 token 直接换算成时间。

    展开在这里做而不是丢给前端：facts 只有后端有。标记匹配不上就原样保留
    模型给的字符串，宁可显示得糙一点也不要把这条来源弄丢。
    """
    out: list[str] = []
    for item in raw[:6]:
        key = str(item).strip().strip("[]")
        if not key:
            continue
        hit = next((f for f in facts if key in f[:60]), None)
        out.append(hit or str(item))
    return out
