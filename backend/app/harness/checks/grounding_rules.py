"""确定性地检查「正文有没有真的用上检索回来的材料」。

这是整晚测出来的最深一个缺口。评分的六个维度里没有任何一条在衡量这件事：
``factual_grounding`` 只查「有没有跟事实矛盾、有没有编造」，**不查「有没有
用」**。通用常识既不矛盾也不编造，所以稳拿 2 分——于是一篇零知识库内容的
通用文章，六维全 2、判定 complete，系统告诉你「写完了」。

实测证据：同一篇「定价要覆盖哪些成本」，本地模型查了 6 次知识库（其中
``filter_facts topic=work_product_cost_control``，341 条可用），最终正文里
一条用户自己的材料都没有，写的是教科书式成本分类——``factual_grounding``
仍然给 2。换更强的模型跑，一次都没查、同样全 2、一轮就 complete。

所以这个闭环的最优解是「干净的通用文章」，而这个产品的全部价值恰恰在于
「写你自己的东西」。这个模块把那条缺失的线补上。

**刻意不用 LLM 判断**：这是可以确定性计算的东西——检索回来的事实里的特征词，
在正文里出现了几条。整晚反复验证过模型的自我判断不可靠，这种能用规则算准的
就不该再交给它。
"""

from __future__ import annotations

import re

# **词表只定义这一处。** 之前 bench（scripts/suite.py）自己写了一份要检查的词，
# 跟这里的正则漂移开了：bench 报「无法判断」和「仍需与」，而 scrub 的正则要求
# 它们后面跟特定的字（"无法判断…是否"、"仍需与…核对"），于是检测得出来、删不掉。
# 现在 bench 从这里 import，两边不可能再对不上。
LEAK_PHRASES = ("知识库", "KB", "检索到的记录", "可核对的记录", "可核对的事实")
AUDIT_PHRASES = ("不能证明", "无法证明", "不能据此", "不足以说明", "仍需与",
                 "逐项核对", "待核对", "待补证据", "无法判断", "尚无法判断",
                 "不能据以", "无从判断", "难以证实")

# 三个正则都由上面的词表拼出来，别再各写各的。
_MECHANISM = re.compile("|".join(
    "(?<![A-Za-z])KB(?![A-Za-z])" if w == "KB" else re.escape(w) for w in LEAK_PHRASES))
_AUDIT_VOICE = re.compile("|".join(re.escape(w) for w in AUDIT_PHRASES)
                          + "|缺少.{0,12}记录，因此")
# 机制泄漏 + 审计腔，两类元话语一起删
_META_SENT = re.compile(_MECHANISM.pattern + "|" + _AUDIT_VOICE.pattern)


# 事实文本前面的元信息前缀，比对时要剥掉：``[2026-04-10] 正文……``、
# ``[terrence-2046-2F3] 正文……``、以及工具输出里的 ``（日期 · 说话人 · 类型）``
_META_PREFIX = re.compile(r"^(?:\[[^\]]{1,40}\]\s*)+")
_META_SUFFIX = re.compile(r"（[^）]{0,60}）\s*$")

# 太常见、出现在哪都不说明问题的词，不能拿它们判"用上了"
_STOP = set("的了和与及或对于关于这个那个可以需要我们他们什么怎么以及一个进行"
            "问题时间方式方法内容情况地方东西部分开始结束现在已经还有就是不是")


def _terms(text: str) -> set[str]:
    """特征词：英文词 + 中文 2-gram。中文按 2-gram 是因为事实文本和正文
    几乎不会字面相同——事实是抽取模型的转述，正文是写作模型的再表达，
    只有共同的实体名、数字、专有说法会重合，而那正是我们要找的信号。"""
    out = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)}
    out |= set(re.findall(r"\d[\d.,%]*", text))          # 数字是最强的信号
    for seg in re.findall(r"[一-鿿]{2,}", text):
        out |= {seg[i:i + 2] for i in range(len(seg) - 1)}
    return out - _STOP


def _fact_body(fact: str) -> str:
    return _META_SUFFIX.sub("", _META_PREFIX.sub("", fact)).strip()


def fact_usage(content: str, facts: list[str], *, min_overlap: int = 3) -> tuple[int, list[str]]:
    """有多少条检索回来的事实，在正文里留下了痕迹。

    返回 ``(用上的条数, 用上的那几条)``。判定标准是一条事实的特征词跟正文
    重合到 ``min_overlap`` 个以上——单个词重合（比如都出现"成本"）说明不了
    什么，三个以上才像是真的把这条写进去了。
    """
    if not facts or not content.strip():
        return 0, []
    body = _terms(content)
    used = []
    for f in facts:
        ft = _terms(_fact_body(f))
        if not ft:
            continue
        if len(ft & body) >= min_overlap:
            used.append(f)
    return len(used), used


def grounding_gap(content: str, facts: list[str]) -> str:
    """检索到了材料却一条都没用上时，给出一句喂回下一轮的诊断；否则返回空串。

    只在**确实检索到了东西**的时候才判——知识库里本来就没有相关内容时写得
    抽象一点是正常的，不该因此扣分（这是 factual_grounding 早期版本犯过的
    错：给"没用完检索结果"扣分，反而诱发编造）。
    """
    if not facts:
        return ""
    n, _used = fact_usage(content, facts)
    if n:
        return ""
    preview = "；".join(_fact_body(f)[:40] for f in facts[:3])
    return (f"这一轮从知识库检索到了 {len(facts)} 条材料，但正文里一条都没用上——"
            f"写出来的是任何人都能写的通用内容。检索到的是：{preview}。"
            "下一轮必须把这些具体材料写进正文：用户自己的项目、数字、决定，"
            "才是这篇笔记的价值所在；通用常识写得再干净也等于没写。")


def material_exhausted(content: str, facts: list[str], *, min_facts: int = 2) -> bool:
    """这一轮检索到的材料是不是**已经全部写进正文了**。

    真实观测到的失败：种子只有一句话，知识库里相关材料只够写一节，但
    完成条件是 ``beat_coverage``——骨架给了四到六条节拍，它必须写满。于是
    它把同一批材料换个角度再写一遍，每节还各自收一次尾：

        第1轮  coherence=2  non_repetition=2      干净
        第2轮  coherence=1  「第一节已经用"所以"收束，后面又继续展开」
               non_repetition=1  「首节与第二节多次重复 ask memory 优先…」
        第3轮  又新开一节讲同一件事

    **不是模型写得差，是它被逼着写。** 终止条件里缺了"材料用完了"这一条，
    只有"节拍写满"和"轮数用尽"，而前者在材料不足时根本达不到。

    判据是确定性的：检索回来的每一条都能在正文里找到痕迹，就说明没有新东西
    可写了。``min_facts`` 是个下限——只检索到一条就说"材料用完"太草率。
    """
    if len(facts) < min_facts:
        return False
    used, _ = fact_usage(content, facts)
    return used == len(facts)


# 写了个坑没填：正文里留下的占位。续写 prompt 的规则三已经明令禁止
# （"不写空模板占位符、不写编号占位的待办"），20 轮 soak 里照样出了 21 处
# ——单个种子最多 10 处。跟今晚其他几类一样，规则说了不算，得给具体位置。
_PLACEHOLDER = re.compile(r"待指定|待倒排|待定|待补|待确认|待明确|待填|TBD|"
                          r"（待[^）]{0,8}）|_{3,}|\bXX\b|X{3,}")


def placeholder_lines(content: str, *, limit: int = 6) -> list[str]:
    """正文里带占位符的那几行，原样返回给修订这一步去填实或删掉。

    只报**行**不报整段：表格里一格「待指定」时，要改的就是那一行。
    """
    out = []
    for line in content.splitlines():
        s = line.strip()
        if s and _PLACEHOLDER.search(s):
            out.append(s[:160])
            if len(out) >= limit:
                break
    return out


# 审计腔：关于"证据够不够"的元评论。这是用户自己的笔记，不是给第三方看的
# 审计报告——他要的是"这一年发生了什么"，不是"哪些事我无法证明"。
#
# 续写 prompt 的规则〇早就明令禁止（"绝对不要写关于证据充分性的元评论"），
# 文件夹级第一次做 bench 就两次跑两次命中：
#   「即使面向发货的相关功能已经可用，也不能据此判断用户已经完成硬件交付」
#   「Lassie 的能力扩展仍缺少对应的版本与测试记录，因此不能据此断言…」
# 泛泛的规则拦不住，得把具体句子指给修订——跟占位符是同一套路。
#
# 机制泄漏（把"知识库""KB"这类工作机制写进正文）归到同一类，判据一样确定。


def audit_voice_lines(content: str, *, limit: int = 5) -> list[str]:
    """正文里带审计腔或机制泄漏的句子，原样返回给修订就地改掉。

    按句切而不是按行：这类话通常夹在一个正常段落中间，指出整段没用。
    """
    out = []
    for sent in re.split(r"(?<=[。！？\n])", content):
        s = sent.strip()
        # 用 _META_SENT（审计腔 + 机制泄漏）而不是只用 _AUDIT_VOICE：这两类
        # 一起喂给修订，判据也该是同一个。拆开正则时漏了这里，单测当场抓到。
        if s and _META_SENT.search(s):
            out.append(s[:160])
            if len(out) >= limit:
                break
    return out


# 只有"把工作机制写进正文"这一类才直接删。审计腔（"不能据此判断…"）里往往
# 还带着真实信息（哪一块缺记录），交给修订去改写成「这里需要补上 XX 的实际
# 记录」；而"目前 KB 中可核对的记录集中在…"这种句子对用户零价值，是纯噪声。


# 「**依赖链：**容量确认」——模型爱把冒号 / 逗号写在粗体**里面**。CommonMark 的
# 右侧定界规则：闭合 ** 前面是标点、后面紧跟汉字，就不算闭合，整段粗体渲染成
# 一串裸星号（实拍）。把标点挪到粗体外面，语义不变、渲染就对了。
# 放在这个纯模块里（不是 editor/textshape）：这里不许依赖 app 内其它包，见 test_layering。
_BOLD_PUNCT = re.compile(r"\*\*([^*\n]+?)([：:，,。；;！!？?、）)])\*\*")


def fix_bold_punct(md: str) -> str:
    """`**依赖链：**` → `**依赖链**：`。围栏代码块里不动。"""
    out: list[str] = []
    fenced = False
    for line in md.split("\n"):
        if re.match(r"^\s*(`{3,}|~{3,})", line):
            fenced = not fenced
            out.append(line)
            continue
        out.append(line if fenced else _BOLD_PUNCT.sub(r"**\1**\2", line))
    return "\n".join(out)


def scrub_meta_sentences(content: str) -> str:
    """兼容旧调用：只要清理后的正文。落盘前顺手把「**标题：**」这类渲染不出来的
    粗体修成「**标题**：」——四条落盘路径都经过这里。"""
    return fix_bold_punct(scrub_meta_sentences_v(content)[0])


def scrub_meta_sentences_v(content: str) -> tuple[str, list[str]]:
    """删掉正文里的元话语句子：提到工作机制的，和关于证据够不够的。

    为什么要在落盘处再来一道，而不是只靠修订：**最后一轮写出来的内容不会再
    经过修订**。两条 harness 的循环都是「修订 → 续写 → 打分」，最后一次续写
    之后就收尾了，所以 audit_voice_lines() 那条线永远够不到它。文件夹级实测
    两个目标两次都把「知识库」写进了用户的笔记。

    审计腔一开始是留着交给修订改写的（想着"里面还有真信息"），实测下来那两句是：

        「即使面向发货的相关功能已经可用，也不能据此判断用户已经完成硬件交付。」
        「Lassie 的能力扩展仍缺少对应的版本与测试记录，因此不能据此断言…」

    整句都是对冲，没有实质信息；而规则里写得很清楚，这类话在用户笔记里**根本
    不该存在**，正确形态是「这里需要补上 XX 的实际记录」。所以跟机制泄漏一样
    整句删掉，不需要再打一次模型。

    只按句删，不动段落结构；整段都是元话语时段落会空掉，一并清掉多余空行。
    """
    if not content or not _META_SENT.search(content):
        return content, []
    removed: list[str] = []
    out = []
    for para in re.split(r"(\n\s*\n)", content):
        if para.strip().startswith(("|", "```", "#")) or "\n" in para.strip()[:0]:
            out.append(para)                       # 表格/代码块/标题原样留着
            continue
        if not _META_SENT.search(para):
            out.append(para)
            continue
        kept = []
        for x in re.split(r"(?<=[。！？])", para):
            if not x:
                continue
            (removed if _META_SENT.search(x) else kept).append(x.strip() or x)
        out.append("".join(k if k in para else k for k in kept))
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip(), removed
