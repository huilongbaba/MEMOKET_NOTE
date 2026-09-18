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

对外的是这六个：``apply_revision`` · ``reject_revision`` · ``breakage`` ·
``expand_sources`` · ``tidy_blank_lines`` · ``user_text_touched``，
``middleware/revise.py`` 全用。
其余（``_locate`` · ``_replaced_span`` · ``_is_same_meaning_rewrite``）才是
真私有。**下划线只用来标真私有**——之前那四个明明被别的模块 import，却顶着
下划线，读的人无从知道这个模块的契约到底是哪几个。
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


def tidy_blank_lines(content: str) -> str:
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


_LINK = re.compile(r"\[[^\]\n]+\]\([^)\s]+\)")
_LINK_URL = re.compile(r"\]\([^)\s]+\)|note://[0-9a-f]{12}|https?://")


def _dangling_links(text: str) -> int:
    """链接残骸：有 URL 却没有配对的 ``[文字](url)``。实拍：修订从「另见 [链接测试]」
    中间切开，正文里留了个孤零零的 ``(note://bb215ab441a2)。``。"""
    return len(_LINK_URL.findall(text)) - len(_LINK.findall(text))


def breakage(before: str, after: str) -> str:
    """这条修订有没有把正文切出破字。只报**新增**的破损，原文本来就有的不算。"""
    was = len(_BROKEN.findall(before))
    now = _BROKEN.findall(after)
    if len(now) > was:
        return "".join(now[-1].split())
    if _dangling_links(after) > _dangling_links(before):
        return "半截链接"
    return ""


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
    #
    # **这个退路只对 insert 安全**，对 replace / delete 是有害的——见
    # `_span_missing`，那条会在应用之前就把它们拦掉，所以走到这里的不会是
    # 那两种。插入只拿这个区间定位，窄一点不影响插在哪。
    return best if best[0] >= 0 else (first, first + len(anchor))


def _span_missing(content: str, anchor: str, anchor_end: str) -> bool:
    """给了结尾标记，却在正文里配不成一对。

    第 602 轮真跑实拍的正文损坏：模型要 replace 一整段，`anchor_end` 写成
    「这里**只**需要补上测试场景…」，正文里是「这里需要补上…」——差一个字，
    配不上。`_locate` 于是退回只替换 anchor 那二十来个字，而 `text` 是整段的
    重写，**结果段尾原封不动留在原地，被新文本复述了一遍**：同样三个分句在
    一段里连着说了两遍，交付给用户的正文就是这样的。

    replace / delete 是**按范围**动刀的，范围找不到就没有"少改一点"这回事，
    只有"改错地方"。丢掉它，下一轮模型会重新给一条锚点写对的。
    """
    if not anchor_end:
        return False
    i = content.find(anchor)
    while i >= 0:
        if content.find(anchor_end, i + len(anchor)) >= 0:
            return False
        i = content.find(anchor, i + 1)
    return True


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


# ============================================ 用户原文不许 replace / delete（P6）===
#
# P5 人读五篇真实笔记（`docs/TRACELOG-product.md` P5 节）：**85 条落地的修订里
# 40 条的锚点落在开跑前就有的正文上**（20/36、7/15、5/11、4/14、4/9），5/5 篇都被
# 改了用户自己写的段落。链条是：打分器把用户原文判成「知识库查无此事」→ steer
# 「查不到就把那句改写掉」→ `EDIT_SYSTEM`「与事实矛盾以事实为准」→ replace /
# delete 落在用户段落上。实拍原话：
#
#   `e78306202d78` 开头两段「与陈校的沟通从招生策略切入…双方在方向上达成一致」
#   → 「项目目前仍处于…不能在正文中写成已经由特定学校、校长或教授确认的共识」
#   理由：「知识库没有陈校、教授…的事实记录」——陈校是用户在笔记里写的人。
#   `a941efecd390` 四段访谈原话 + 8 条正确引用 → 一段「目前给定的知识库没有提供…」
#
# 这一档跟 `no_audit_voice` 的量程（批 21）是同一个形状：**判据看的是整篇，而
# 整篇里一大半是用户自己写的字**。那次收的是「报不报」，这次收的是「动不动」：
# **replace / delete 的锚段必须整段落在这次跑写出来的差集里**（`content_at_start`
# 之外）。用户原文只允许两种动法：insert 接在它后面；或「机械性修正」——编号 /
# 标题层级 / 粗体 / 标点这类不换字的改动（`_core` 相等）。
#
# **为什么是段落 / 句子级而不是整段字面比**：一条 delete 的范围可以从用户段落的
# 中间起、到这次新写的段落结束——整段字面不在 `before` 里，但它吃掉了用户的半段。
# 所以把范围切成段落、再切成句子，任何一片在开跑前的正文里逐字出现过，就算动了
# 用户的字。**去重是唯一的例外**：这次跑把用户的一节又写了一遍，删掉多出来的那份
# 是对的——判法是「这一片在现在的正文里出现的次数 > 开跑时的次数」，多出来的那份
# 才是这次跑写的。
#
# **打磨模式不走这条**：那个模式的全部目的就是改已有内容，用户点的就是「改我写的」。
# 调用方（`middleware/revise.py`）按 `st.bag["polish"]` 决定给不给 `before`。

_CORE_STRIP = re.compile(r"[\s#*_`>|\-\d\.,;:!?，。；：！？、（）()\[\]【】「」『』“”‘’\"']+")


def _core(s: str) -> str:
    """机械性修正前后不该变的那部分：去掉空白、markdown 记号、标点、数字。"""
    return _CORE_STRIP.sub("", s or "").lower()


def _pieces(span: str) -> list[tuple[str, bool]]:
    """一段范围 → 段落 + 句子两级的片 `(片, 是不是整段)`。短于 4 字的片不算
    （「- 」「1.」这类只是排版）。"""
    out: list[tuple[str, bool]] = []
    for para in re.split(r"\n\s*\n", span or ""):
        p = para.strip()
        if len(p) >= 4:
            out.append((p, True))
        for sent in re.split(r"(?<=[。！？!?\n])", p):
            t = sent.strip()
            if len(t) >= 4 and t != p:
                out.append((t, False))
    return out


def _is_mechanical(old: str, new: str) -> bool:
    """只动了编号 / 层级 / 粗体 / 标点，一个字没换。"""
    return _core(old) == _core(new) and _core(old) != ""


def user_text_touched(content: str, op: str, anchor: str, text: str,
                      anchor_end: str = "", before: str = "") -> str:
    """这条 replace / delete 是不是在动用户开跑前就写好的字。要丢就返回理由，否则空串。

    `before` = 开跑时的正文（`st.bag["content_at_start"]`）。**不给 `before` 就什么
    都不拦**（老行为）——这一句是量程，撤掉它这条守卫就是空的，
    `tests/test_p6_user_text.py` 的突变验钉着。
    """
    if op not in ("replace", "delete") or not (before or "").strip():
        return ""
    span = _replaced_span(content, anchor, anchor_end)
    if not span.strip():
        return ""
    # 去重例外只给**整段**：这次跑把用户的一段又写了一遍，多出来的那份是这次跑的。
    # 句子级的片不给——P6 重放 a941 实拍：一条 replace 锚在用户句子的尾巴
    # 「to the next step.」上，恰好这次跑在别处也写过这几个字，按次数比就放行了，
    # 落点却是 `find` 找到的第一处、用户那句，把它从中间劈成两段。
    whole = "\n" in span.strip() or any(p == span.strip() for p, _ in _pieces(span))
    touched = [p for p, is_para in [(span.strip(), whole), *_pieces(span)]
               if p in before and (not is_para or content.count(p) <= before.count(p))]
    if not touched:
        return ""
    if op == "replace" and _is_mechanical(span, text):
        return ""
    key = " ".join(touched[0].split())[:24]
    return (f"这条要{'删掉' if op == 'delete' else '改写'}你开跑前就写好的内容，已拦下"
            f"（续写只在你的正文之外补写；改编号 / 标题层级 / 标点这类不换字的修正除外）：{key}…")


# ============================================ 元话语整条丢弃（P6）===
#
# P5 实拍：修订的 `text` 本身带着「这里应改为：」「不能在正文中写成…」「更准确的
# 写法是」「应明确标注为待补充访谈证据」，落进正文之后 `scrub_meta_sentences_v`
# 按「。！？」切句，冒号收尾的半句留下——`e78306202d78` 最终正文的第一行就是
# 「这里应改为：」。在这里整条丢掉比落盘后再切句稳：一条修订的 text 里有元话语，
# 说明它整条都是在跟读者解释「材料不够」，不是在写正文。词表在
# `checks/grounding_rules.REWRITE_PHRASES`（只收 P5 真出现过的形状）。

def meta_in_text(text: str, before: str = "") -> str:
    """修订 text 里第一句元话语（开跑前正文里就有的那句不算）。没有返回空串。"""
    from .checks.grounding_rules import meta_sentences
    hits = meta_sentences(text or "", before)
    return hits[0] if hits else ""


def reject_revision(content: str, op: str, anchor: str, text: str,
                    anchor_end: str = "", edited: set[str] | None = None,
                    before: str = "") -> str:
    """这条修订该不该丢。要丢就返回一句给用户看的理由，否则返回空串。

    三类都是在真实产出上抓到的，且都是**确定性可判**的——整晚反复验证过，
    这类"别重复改""别切坏"的元指令写进提示词不管用，只有在应用阶段硬拦有效。

    ``note_harness`` 和 ``writing_plan`` 共用 ``apply_revision``，所以这三道
    防线也必须共用：只修一边，等于另一条路径上的 bug 还活着。

    P6 加的第四类：``text`` 里带元话语的整条丢（``meta_in_text``），排在最前面
    ——别的守卫说的是「改哪儿」，这条说的是「写的根本不是正文」。
    """
    key = " ".join(anchor.split())[:40]
    meta = meta_in_text(text, before) if op != "delete" else ""
    if meta:
        return (f"这条修订写的是元话语（「{meta[:30]}…」），不是正文，整条已丢弃：{key[:24]}…")
    if op in ("replace", "delete") and _span_missing(content, anchor, anchor_end):
        return f"这条的结尾标记在正文里找不到，范围划不出来，已丢弃：{key[:24]}…"
    if op == "replace" and edited is not None and key in edited:
        return f"这处上一轮已改过，跳过：{key[:24]}…"
    if op == "replace" and _is_same_meaning_rewrite(
            _replaced_span(content, anchor, anchor_end), text):
        return f"这条只是换了措辞，没改出东西，已丢弃：{key[:24]}…"
    if op in ("insert", "insert_before") and _splits_a_sentence(content, op, anchor, anchor_end, text):
        # 用户实拍（第 570 轮）：「这批设备适合用来验证漏斗后半段：如果要把验证结果与产品推进
        # 节点对齐，还应明确……时间节点；KOL 是否愿意持续展示……」——冒号后面被塞进一整句，
        # 原来那句的后半截（KOL 是否愿意…）被顶到插入内容之后，读起来是两句缝在一起。
        # 补一个引用标记 / 几个字的短语不算，只拦「整句级」插到句子中间。
        return f"这条会把一句话从中间劈开，已丢弃：{key[:24]}…"
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


# 到这儿为止是一句话，可以在后面另起一句
_SENTENCE_END = set("。！？!?…；;」』）】》”’\n")


def _splits_a_sentence(content: str, op: str, anchor: str, anchor_end: str, text: str) -> bool:
    """这条 insert 会不会插在一句话中间。"""
    # 自己另起一行/一段的不算劈开（模型给的 text 以换行开头时，插在标题或半句后也是新的一段）
    if (text or "").startswith(("\n", "\r")):
        return False
    body = (text or "").strip()
    # 只拦整句级的插入：补引用标记（`[terrence-1-A]`）或几个字的短语不该被拦
    if len(body) < 20 or not any(ch in "。！？!?" for ch in body):
        return False
    i, end = _locate(content, anchor, anchor_end)
    if i < 0:
        return False
    head = content[: (i if op == "insert_before" else end)]
    if not head.strip():
        return False
    return head.rstrip(" \t")[-1:] not in _SENTENCE_END


def apply_revision(content: str, op: str, anchor: str, text: str,
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


def expand_sources(raw: list, facts: list[str]) -> list[str]:
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
