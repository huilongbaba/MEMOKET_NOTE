"""用户选中一段文字之后能做的事：改写、润色、展开、核查、回顾。

跟别的提示词的区别是**输入里有一个"选区"**，模型的活儿被限定在这段上，
不碰其余正文。只有 routers/compose.py 这一个调用方——它们不是 harness
的一部分，是编辑器里的一次性动作。
"""

from __future__ import annotations

from .fragments import facts_block, spine_beats_block


# 结构直接照抄语料本身的人工摘要习惯（见 terrence_records 里已有的
# *_transcript+new.md 文件：核心结论/关键决定/主要问题/推荐行动/风险），
# 说明这套结构本来就是这类会议记录的自然归纳方式，不是凭空发明的模板。
DIGEST_SYSTEM = """你是回顾助手。给你一段时间内、按时间顺序排列的知识库事实，
写一份简短的阶段回顾，帮用户快速找回这段时间发生了什么。

用以下结构（都是 markdown 二级标题）：
## 核心结论
## 关键决定
## 待跟进
## 值得注意的变化

要求：
- 每节 2-4 条要点，一句话一条，用 "- " 列表
- 只依据给出的事实，不要编造没提到的内容
- 某一节没有对应内容就省略整节，不要硬凑
- 直接输出 markdown 正文，不要任何额外解释或前后缀
"""


# ---------------------------------------------------------------- 选中文本操作

REWRITE_SYSTEM = """你是写作编辑。用户选中了正文里的一段内容，要求你根据
这篇笔记的上下文重写它——不是随便换个说法，是让这段话更贴合上下文的核心
张力、结构节拍，以及笔记其余部分已经确立的语气和事实。

只输出 JSON，形如 {"text":"重写后的内容","reason":"为什么这样改"}
- text 只包含重写后的这一段，不要包含选中范围之外的内容
- 保持大致相当的信息密度，除非上下文明显要求精简或展开
- 语言与原文一致
"""


POLISH_SYSTEM = """你是写作编辑。用户选中了正文里的一段内容，要求你润色它：
改善表达、消除歧义或啰嗦，但不改变原意，也不添加原文没有的信息——重写是
"改成更贴合上下文"，润色是"同样的意思说得更好"，两者不同。

只输出 JSON，形如 {"text":"润色后的内容","reason":"改了什么、为什么"}
- text 只包含润色后的这一段
- 语言与原文一致
"""


EXPAND_SYSTEM = """你是写作编辑。用户选中了正文里的一个点（一句话或一个
片段），想在它前面和/或后面补充缺失的上下文——往前补"是什么背景/前提让
这句话成立"，往后补"这句话之后自然的展开或后果"。

只输出 JSON，形如 {"before":"...","after":"...","sources":["依据的知识库事实原文"]}
- before/after 各自独立判断要不要写，都不需要就都留空字符串，不要硬凑
- sources：如果 before/after 用到了知识库里的具体事实，把依据的那条事实
  原文摘进这个数组（不超过 3 条）；纯粹基于选中片段本身合理推断、没有用
  具体事实的话，sources 留空数组——这是给用户看的溯源标注，不能瞎填，没
  用到就是没用到
- 不要重复选中片段本身已经说过的内容
- **重点检查【选中片段前面已有的内容】【选中片段后面已有的内容】**：这个
  选中片段大概率不是孤立的，前后已经写了什么，实测踩过的真实问题——
  完整正文里选中片段前后本来就有真实内容时，模型会把这些已经存在的邻近
  句子几乎原样当成"新补充的上下文"复述一遍，结果是插入的内容跟旁边已经
  写的东西重复，等于没补充。判断 before/after 前，先确认这句话是不是
  【选中片段前面已有的内容】结尾、或【选中片段后面已有的内容】开头已经
  在说的——是的话这个方向就不用补了，留空字符串，不要为了填满而重复
- 语言与原文一致，衔接要自然，不要用"首先/其次"这类生硬的过渡词
- 如果给了知识库中的相关事实，补充的背景/展开优先从这些事实里来，不要在
  知识库明明有真实细节的情况下，自己编一个听起来合理但查无实据的背景
  （比如泛泛写"团队评审了 XX""经过讨论决定 YY"这类没有具体依据的套话）。
  没有相关事实、或者事实里确实没有能支撑背景/展开的内容，才可以基于选中
  片段本身合理推断，但推断的内容要保守，不要编造具体的人名/数字/结论
"""


VERIFY_SYSTEM = """你是事实核查助手。给你一段被选中的正文（下称"待核查内容"），
连同这篇笔记的完整正文、以及从用户知识库里检索到的相关事实（带编号）。

判断待核查内容是否可信、有没有跟其他信息冲突：
- 跟知识库里某条事实矛盾：verdict 填"矛盾"，reason 说清楚具体冲突点，
  fact_index 填那条事实的编号
- 跟笔记里其他地方写的内容自相矛盾：verdict 填"矛盾"，reason 里说明是
  笔记的哪一处，fact_index 填 -1
- 有证据支持待核查内容：verdict 填"支持"，reason 简述依据，fact_index
  填对应事实编号。**待核查内容本身出现在正文里不算依据**——它就是从正文里选出来的，
  "正文写明了这一点"是循环论证；只有正文里**另一处**独立记载的内容才算笔记自身支持
  （那时填 -1），优先用知识库里的事实
- 找不到任何相关信息可以判断：verdict 填"无法判断"，reason 说明原因，
  fact_index 填 -1——找不到证据不等于有问题，不要为了给结论而牵强附会

只输出 JSON 数组，每条形如：
{"verdict":"矛盾"|"支持"|"无法判断","reason":"...","fact_index":整数}
最多 4 条，只挑真正有判断依据的，不要为了凑数硬找；如果完全没有值得
指出的地方，输出 []。
"""


# 「完整正文」块最多给这么多字；再长就只给选区周围的一段。实拍 47k 字的长文上
# 校验一句话，整篇 3 万 token 跟着进提示词——慢、贵，而且离选区两万字远的内容对
# 「这句对不对 / 怎么改」没有帮助。
_CONTEXT_MAX_CHARS = 8000
_CONTEXT_RADIUS = 3000


def selection_context(content: str, selection: str,
                      max_chars: int = _CONTEXT_MAX_CHARS, radius: int = _CONTEXT_RADIUS) -> str:
    """正文不长就原样给；长了就切选区前后各 radius 字的一段，切口对齐到段落，
    两头标出省掉了多少字。找不到选区（理论上不会）就给开头 max_chars 字。"""
    if len(content) <= max_chars:
        return content
    idx = content.find(selection) if selection else -1
    if idx < 0:
        return content[:max_chars] + f"\n\n…（后面还有 {len(content) - max_chars} 字，略）"
    start = max(0, idx - radius)
    end = min(len(content), idx + len(selection) + radius)
    # 切口对齐到段落边界（往外找最近的空行），别在句子中间断
    if start > 0:
        cut = content.rfind("\n\n", max(0, start - 400), start)
        if cut >= 0:
            start = cut + 2
    if end < len(content):
        cut = content.find("\n\n", end, min(len(content), end + 400))
        if cut >= 0:
            end = cut
    head = f"…（前面还有 {start} 字，略）\n\n" if start > 0 else ""
    tail = f"\n\n…（后面还有 {len(content) - end} 字，略）" if end < len(content) else ""
    return head + content[start:end] + tail


def rewrite_user(content: str, selection: str, spine: str, beats: list[str]) -> str:
    parts = []
    spine_block = spine_beats_block(spine, beats)
    if spine_block:
        parts.append(spine_block)
    parts.append("【完整正文】\n" + selection_context(content, selection))
    parts.append("【被选中要处理的片段】\n" + selection)
    return "\n\n".join(parts)


# before/after 各给这么多字符的"已有邻近内容"——不用整段，够模型判断
# "这个方向是不是已经写过了"就行，太长反而稀释选中片段本身的注意力。
_EXPAND_NEIGHBOR_CHARS = 150


def expand_user(content: str, selection: str, facts: list[str] | None = None) -> str:
    parts = [f"【完整正文】\n{selection_context(content, selection)}", f"【被选中的片段（要在它前后补上下文）】\n{selection}"]
    idx = content.find(selection)
    if idx >= 0:
        before_ctx = content[max(0, idx - _EXPAND_NEIGHBOR_CHARS):idx].strip()
        after_ctx = content[idx + len(selection):idx + len(selection) + _EXPAND_NEIGHBOR_CHARS].strip()
        parts.append("【选中片段前面已有的内容（判断 before 前先看这里是不是已经写过了）】\n"
                     + (before_ctx or "（前面没有内容了，这已经是开头）"))
        parts.append("【选中片段后面已有的内容（判断 after 前先看这里是不是已经写过了）】\n"
                     + (after_ctx or "（后面没有内容了，这已经是结尾）"))
    if facts:
        parts.append(facts_block(facts))
    return "\n\n".join(parts)


def verify_user(content: str, selection: str, facts: list[str]) -> str:
    parts = ["【笔记完整正文】\n" + selection_context(content, selection), "【待核查内容】\n" + selection]
    if facts:
        numbered = "\n".join(f"[{i}] {f}" for i, f in enumerate(facts))
        parts.append("【知识库检索到的相关事实】\n" + numbered)
    else:
        parts.append("【知识库检索到的相关事实】\n（没有找到相关记录）")
    return "\n\n".join(parts)


RELATIONS_SYSTEM = """你是写作者的记忆助手。给你一段正文和几条知识库里的旧记录，以及代码按数字 / 日期
初判出来的关系。请逐条确认：这条关系成立吗（是同一件事的同一个量吗）？成立的话用一句
中文把关系说清楚（先说旧记录的日期和值，再说正文写的是什么）；不成立就丢掉。
只输出 JSON 数组，每项 {"index": 候选序号, "keep": true|false, "say": "一句话"}。"""


def relations_user(passage: str, candidates: list[dict], facts_by_id: dict[str, dict]) -> str:
    lines = [f"【正文】\n{passage.strip()[:600]}", "【候选关系】"]
    for i, c in enumerate(candidates):
        refs = "；".join(f"[{fid}] {facts_by_id[fid].get('date', '')} {facts_by_id[fid].get('text', '')}"
                        for fid in c.get("fact_ids", []) if fid in facts_by_id)
        lines.append(f"{i}. {c.get('relation', '')}：{c.get('say', '')}\n   依据：{refs}")
    return "\n".join(lines)


def digest_user(facts: list[str]) -> str:
    return "【事实（按时间顺序）】\n" + "\n".join(facts)
