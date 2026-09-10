"""识别「用户给的是大纲」，并保护他已经写好的结构。

真实场景，也是这套东西栽得最狠的一次：用户输入

    创业一年回顾
    ## 时间线与里程碑
    ### APP
    ### 硬件
    ### 营销与PR
    ## 团队建设
    ### 研发 / ### 设计 / ### 市场
    ## 反思与展望

—— 一份干净的大纲，每个标题下面是空的，意思很清楚：**骨架我搭好了，你填肉**。

harness 干了什么：骨架环节无视这些标题、自己另生成一套 spine/beats，后面
每轮都在服务它自己那套；修订环节又按"空壳标题是缺陷、要删掉"这条规则去
清理——**用户的目录成了被清理的对象**。最终输出里「硬件」被挪到了最后、
「研发/设计/市场」三个子标题消失、「反思与展望」没了。

用户搭了骨架让它填肉，它把骨架拆了重搭。

所以这里做两件事：确定性地判断"这是不是一份大纲"，以及把用户写的标题原样
取出来当作不可改动的结构。判断刻意用规则不用模型——这是能算准的东西。
"""

from __future__ import annotations

import difflib
import re

_HEADING = re.compile(r"^(#{1,6})\s+(\S.*?)\s*$", re.M)
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})", re.M)


def _mask_fences(content: str) -> str:
    """把围栏代码块里的字符抹成同样长度的占位符。

    **围栏里的东西不是标题。** Python 和 Shell 的注释正好是 ``# `` 开头，
    跟 markdown 的一级标题一个样子，而这个文件里的每个函数都在拿 `_HEADING`
    扫全文。实测一篇「两节正文 + 一个带注释的代码块」的普通笔记：

      · ``is_outline()`` 判成 True —— 假标题凭空造出两个「空小节」，空标题
        占比越过 0.6。这正是这个文件开头写着要避免的事：把正常文章误判成
        大纲，结构就被冻死、修订改不动任何标题。
      · ``next_gap()`` 认为「脚本」那节是空的 —— 它的正文被代码块第一行
        注释截断了，于是这一轮的内容插到了代码块**前面**。
      · ``strip_headings()`` 直接把 ``# 读取退货工单`` 这类注释行从用户的
        代码里删掉。

    **长度和换行必须逐字符保持**：``next_gap()`` 返回的偏移量要拿回原文去
    切，`_bodies()` 也按长度判断「这一节填了没有」。所以是抹成同长占位符，
    不是删掉。

    围栏没闭合时后面一律当代码，跟 markdown 渲染器的处理一致——宁可少认
    几个标题，也不要把代码当结构。
    """
    if "```" not in content and "~~~" not in content:
        return content
    out = list(content)
    fenced = False
    for m in re.finditer(r"^.*$", content, re.M):
        is_fence = bool(_FENCE.match(m.group(0)))
        if is_fence or fenced:
            for i in range(m.start(), m.end()):
                out[i] = "x"
        if is_fence:
            fenced = not fenced
    return "".join(out)


def _marks(content: str) -> list[re.Match]:
    """正文里的标题，围栏代码块里的不算。偏移量对得上原文。"""
    return list(_HEADING.finditer(_mask_fences(content or "")))

# 一个标题下面少于这么多字，就算"还没填"
EMPTY_BODY_CHARS = 40
# 空标题占比超过这个比例，判定为大纲
OUTLINE_RATIO = 0.6
# 至少要有这么多标题才谈得上"大纲"
MIN_HEADINGS = 3


def headings(content: str) -> list[tuple[int, str]]:
    """正文里的标题，返回 (层级, 标题文字)。围栏代码块里的不算（见 _mask_fences）。"""
    return [(len(m.group(1)), m.group(2)) for m in _marks(content)]


def _bodies(content: str) -> list[tuple[str, str]]:
    """每个标题和它下面到下一个标题之间的正文。"""
    out: list[tuple[str, str]] = []
    marks = _marks(content)
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(content or "")
        out.append((m.group(2), (content or "")[m.end():end].strip()))
    return out


def is_outline(content: str) -> bool:
    """这是不是一份"标题搭好了、内容还没填"的大纲。

    判据刻意简单且确定性：标题足够多，且其中大部分下面几乎没有内容。
    宁可漏判也不要误判——把一篇正常文章误判成大纲，会让结构被冻死、
    修订改不动任何标题。
    """
    body = _bodies(content)
    if len(body) < MIN_HEADINGS:
        return False
    titles = [t for t, _b in body]
    if len(set(titles)) != len(titles):
        # 同名标题出现两次。搭骨架的人不会给两节起一样的名字——重名恰恰是
        # 要被修掉的缺陷，判成大纲反而会把它冻住、永远删不掉。
        return False
    empty = sum(1 for _t, b in body if len(b) < EMPTY_BODY_CHARS)
    return empty / len(body) >= OUTLINE_RATIO


def outline_block(content: str) -> str:
    """给 prompt 用的一段说明：用户的结构长什么样、必须怎么对待它。"""
    hs = headings(content)
    if not hs:
        return ""
    tree = "\n".join(f"{'  ' * (lv - 1)}- {txt}" for lv, txt in hs)
    return (
        "【用户已经搭好的结构 —— 这是他明确的写作意图，不是待整理的草稿】\n"
        + tree
        + "\n\n**这些标题一个字都不许改、不许删、不许重新排序、不许合并。**\n"
        "标题下面是空的，说明那一节还没写，不是「空壳标题」这种缺陷——\n"
        "用户搭好骨架就是要你按这个骨架往里填内容。\n"
        "**这一轮只写指定的那一节，不要新建任何标题**——需要填的小节用户\n"
        "都已经写好了，你只写正文。在文末另起一个同名标题会让目录里出现\n"
        "两个「市场」这种重复（实测发生过）。\n"
        "**知识库里查不到某一节需要的材料时**，就在那一节写一句\n"
        "「这里需要补上 XX 的实际记录」然后跳过，去填别的能写实的小节——\n"
        "**绝对不要写这类话**：「现有材料不能证明…」「仍需与原始记录逐项\n"
        "核对」「不能据此判断…」「应保留为待补证据」。这是用户自己的笔记，\n"
        "不是给第三方看的审计报告——他要的是「这一年发生了什么」，不是\n"
        "「哪些事我无法证明」。查到什么就写什么，查不到就用上面那句话标出来，\n"
        "两句话之间不要夹一整段关于证据充分性的说明。"
    )


def structure_intact(before: str, after: str) -> bool:
    """改动之后，用户原有的标题是不是**原样、按原顺序**还在。

    这是代码层面的硬防线，不依赖模型听话。实测：``outline_block()`` 已经
    明确写了「一个字都不许改、不许删、不许重新排序」，模型照样把
    「## APP」改成「## APP：把长内容压缩成可消化的摘要」、把「团队建设」
    「研发」「设计」「市场」四个标题直接删掉。

    原因是 EDIT_SYSTEM 里有两条规则在跟它对着干——「空壳标题要删掉」和
    「脚手架标题要换成有信息的标题」——而**那两条在 system prompt 里、
    保护说明在 user prompt 里，system 权重更高**。这一晚上反复验证过：
    提示词层面的约束在"该用哪个工具""能不能动结构"这类事情上一律不可靠，
    有效的只有结构性/确定性的手段。

    所以这里不劝，直接判：一条修订只要动了用户的标题，就丢弃它。
    """
    # 比对 (层级, 文字) 而不是只比文字——实测模型把 ``### APP`` 改成了
    # ``## APP``，只比文字会放行，用户的层级结构就被压平了。
    old = headings(before)
    if not old:
        return True
    old_set = set(old)
    kept = [h for h in headings(after) if h in old_set]
    return kept == old


def next_gap(content: str) -> tuple[str, int] | None:
    """下一个还没填内容的小节：返回 (标题文字, 该插入的位置)。

    大纲填充本质上是**定向插入**，不是"接着往下写"。harness 的续写一律
    追加到文末（``join_round_text``），而用户大纲里待填的小节在中间——
    实测结果就是模型在文末又新建了一个「市场」，跟用户原有的「市场」
    并存，目录里同一个标题出现两次。

    这里确定性地找出第一个空小节和它的插入点，让续写定向填进去。
    """
    marks = _marks(content)
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(content or "")
        body = (content or "")[m.end():end].strip()
        if len(body) < EMPTY_BODY_CHARS:
            return m.group(2), m.end()
    return None


def insert_into(content: str, pos: int, text: str) -> str:
    """把这一轮写的内容插到指定小节标题之后，而不是追加到文末。"""
    body = text.strip()
    if not body:
        return content
    head = content[:pos].rstrip("\n")
    tail = content[pos:].lstrip("\n")
    # 插入点后面若以标点开头（实测出现过「…已完成成果。**，而要按**…」这种
    # 残留），把那个孤立的标点去掉——它本来是接在被插内容之前那句话上的。
    tail = re.sub(r"^[，、。；：,;:]+\s*", "", tail)
    return f"{head}\n\n{body}\n\n{tail}"


def strip_headings(text: str) -> str:
    """剥掉续写里自己写的标题行。

    大纲模式下续写的任务是"往用户已有的标题下面填正文"，prompt 里明确写了
    「不要写标题」——它照样写。实测两版 prompt（25 条规则的完整版和 6 条的
    精简版）都把用户的 ``### APP`` 压平成了 ``## APP``，因为模型自己又写了
    一遍标题、层级还写错了。

    ``structure_intact()`` 只守修订那一侧，续写这一侧之前完全没有防线。
    跟今晚其他几处一样：指令层面的约束在这类事情上不可靠，只有确定性手段
    有效。这里直接剥掉，用户的结构是唯一权威。
    """
    # 按掩码后的文本判断哪几行是标题，但保留原文那一行——围栏里的 ``# 注释``
    # 不是标题，剥掉它等于在删用户的代码。
    masked = _mask_fences(text or "").splitlines()
    kept = [ln for ln, mk in zip((text or "").splitlines(), masked)
            if not _HEADING.match(mk)]
    out = "\n".join(kept)
    # 剥完可能留下连续空行
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def _is_block(para: str) -> bool:
    """代码块（含 mermaid）、表格、引用块——这些不参与判重。

    它们的相似度由格式骨架决定，跟内容说的是不是同一件事无关。
    """
    p = para.lstrip()
    return p.startswith(("```", "|", ">", "    ")) or "```" in p


def drop_already_written(content: str, text: str, *, threshold: float = 0.62) -> str:
    """把这一轮写出来的、正文里已经有的段落剔掉。

    真实产出（三层大纲，第 3 轮 ``non_repetition`` 判 0）：

        众筹阶段除了导入流量，还需要把价值感和转化规则讲清楚。团队曾建议
        展示划线的179美元 MSRP…众筹结束后，官网仍可承接浏览、定金预订…
        众筹阶段除了导入流量，还需要把价值感和转化规则讲清楚。Pitch 的反馈
        是缩短开场介绍…团队曾建议展示划线的179美元 MSRP…众筹结束后，官网…

    第二遍是第一遍的超集，中间插了一句新的。机制是：大纲模式每轮把新写的
    内容插到目标小节标题之后，而模型这一轮把**整节重写了一遍**，于是新旧
    并存。团队那节的末句也连着出现了两次，同一个原因。

    这不是"主题撞车"，是逐字重复。修订那一步的机械查重本该抓到它，但要改
    就得发 replace，而两段开头一模一样、锚点有歧义——绕了一圈还是修不掉。
    所以在**插入之前**就剔掉，跟今晚其他几处一样：确定性手段，不指望模型
    自己不重复。

    阈值取 0.62。这个数字改过两次，过程值得记下来：

    - 最初 0.72，按单个样本定的（重复段 0.83，同一节里真正不同的段落 <0.4）。
    - 用 180 篇产出量分布（中位 0.25 / 90% 0.39 / 最高 0.65）后降到 0.55，
      想吃掉 0.50~0.65 那一段。**这一步是错的**：把原文抓出来一看，那几对
      "高相似度"全是两张 mermaid 图共享语法骨架造成的假阳性，内容完全不同。
      0.55 会误删用户正文里第二张合理的图表。
    - 现在代码块/表格直接排除在判重之外（见 _is_block），散文的真实分布回到
      0.4 以下，阈值取 0.62：比观测到的散文上限留出余量，又能抓住 0.83 那种
      整段重写。

    **教训：按聚合指标改机制之前，先把命中的原文抓出来看一眼。**
    """
    body = (text or "").strip()
    if not body:
        return body
    # 已有正文为空或很短时**不能提前返回**——轮内去重照样要做，而且第一轮
    # 正文最短、恰恰是重复最多的那一轮（实测重复就是第一轮在一次续写的输出
    # 内部写出来的）。原来这里两个早退把轮内比对整个跳过了。
    old = [p for p in re.split(r"\n\s*\n", content or "")
           if len(p.strip()) >= 40 and not _is_block(p.strip())]
    kept = []
    for para in re.split(r"\n\s*\n", body):
        p = para.strip()
        if len(p) < 40 or _is_block(p):
            # 短行（列表项、标题残留）和代码块/表格不参与判重。
            #
            # **代码块这一条是踩过坑才加的**：两张 mermaid 图共享语法骨架
            # （```mermaid / flowchart LR / A[…] --> B[…]），difflib 给到
            # 0.55，而内容完全不同（一张讲众筹前准备、一张讲交付节奏）。
            # 我按这个假阳性把阈值从 0.72 降到 0.55，那会误删用户正文里第二张
            # 合理的图表——按测量伪影改真实机制，比不改更糟。
            kept.append(para)
            continue
        # 除了跟已有正文比，**还要跟这一轮自己已经留下的段落比**：实测重复
        # 大量出现在同一次续写的输出内部（180 篇里 3 篇段落相似度 >0.5，全部
        # 被打分器独立判了 non_repetition=1），而只跟旧正文比根本看不到它们。
        # 把阈值从 0.72 降到 0.55 也没消掉这 3 篇，就是因为比错了对象。
        seen = old + [x.strip() for x in kept if len(x.strip()) >= 40]
        if any(difflib.SequenceMatcher(None, p, o.strip()).ratio() > threshold for o in seen):
            continue
        kept.append(para)
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(kept)).strip()
