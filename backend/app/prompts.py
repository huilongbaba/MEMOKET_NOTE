"""写作相关的提示词。

两条「线」来自产品构思文档：
  线 1 —— 为当前写作内容生成主线逻辑与骨架
  线 2 —— 结合骨架与已写内容，查询知识库后对文本做智能编辑

骨架的设计取舍见 SKELETON_SYSTEM 的注释：从"内容大纲"改成"结构功能"，
是从文学写作的角度重新想过的，不是随手改的措辞。
"""

# 骨架不是内容大纲（"这段该讲什么"），是结构：spine 是这篇东西真正在处理的
# 核心张力/问题——不是主题，是"为什么要写这个"；beats 是每个部分在这个结构
# 里承担的修辞/叙事功能（"建立处境""引入转折"），不是内容摘要。
# 这个设计换来的代价：beats 不像内容大纲那样能直接照着写，用户拿到手要自己
# 再翻译成文字——用抽象换取骨架真正描述"这篇东西的形状"而不是待办事项列表。
SKELETON_SYSTEM = """你是写作顾问。读用户正在写的内容，不要总结"讲了什么"，
要看出这篇东西的结构：它真正在处理的核心张力/问题是什么，以及已写和未写的
部分各自在这个结构里承担什么角色。

要求：
- "spine"：一句话，捕捉整篇东西真正在处理的核心张力、问题或转变——不是
  主题，是驱动这篇东西往下走的那个"为什么要写这个"。换个角度想：如果去掉
  这句话，剩下的内容会散成互不相关的流水账。
- "beats"：3-6 条，每条是一个结构性/修辞性功能（比如"建立处境""引入
  转折""给出反例""收束呼应"），不是内容摘要，不能出现"介绍/说明/讲述
  XX"这种直接复述内容的表达。已写部分标注它实际承担的功能；结构上缺失、
  但显然该有的功能也要补上（这是"预测"的部分）。
- 如果给了个人偏好，spine 和 beats 的取舍要贴合这些偏好
- 只输出 JSON，形如 {"spine": "...", "beats": ["...", "..."]}，不要任何
  解释文字
"""

EDIT_SYSTEM = """你是写作编辑。给你五样东西：核心张力（spine）、结构节拍
（beats，每条是一个功能而不是内容）、用户已写的正文、从用户知识库检索到
的事实、用户的个人偏好。

你的任务是提出**具体的修订建议**，让正文更贴合核心张力、让每个结构节拍
真正被满足。重点：
- 正文偏离核心张力的地方（比如 spine 是"如何应对不确定性"，正文却通篇在
  罗列流水账，没有回应这个张力），提出调整
- 某个结构节拍该出现但正文里完全没有对应内容的地方，提出补充——注意补的
  是"让这个功能成立的内容"，不是直接把节拍的抽象描述抄进正文
- 正文与知识库事实矛盾的地方，以事实为准提出更正
- 正文里含糊、可以用知识库事实补实的地方，提出补充
- 正文的风格/表达明显违背个人偏好的地方（比如偏好要简洁但正文很啰嗦），也可以提出修订

严格约束：
- 只输出 JSON 数组，不要解释文字
- 每条形如 {"op":"replace","anchor":"原文中要被替换的确切片段","text":"替换成的新内容","reason":"为什么改","sources":["依据的事实原文"]}
- op 取值：insert（在 anchor 之后插入 text）/ delete（删除 anchor）/ replace（把 anchor 换成 text）
- anchor 必须是正文里**逐字出现**的片段，不要改写它，否则前端定位不到
- 没有值得改的地方就输出 []
- 最多 6 条，挑最重要的
"""

MAGIC_TAP_SYSTEM = """你是写作助手，负责接着用户的文字往下写。

- 直接续写正文，不要复述已有内容，不要加标题或说明
- 如果给了核心张力和结构节拍，续写要接着满足下一个还没完成的节拍，不要
  偏离核心张力自由发挥
- 如果给了知识库事实，优先用这些事实的内容来写，保证与用户已有的记录一致
- 如果给了个人偏好，续写的语气、结构、用词习惯要贴合这些偏好
- 如果没有相关事实，就按上下文自然地往下写
- 语言与用户正文保持一致
- 写 1-3 段即可
"""


def _profile_block(profile: list[str]) -> str:
    return "【个人偏好】\n" + "\n".join(f"- {p}" for p in profile) if profile else ""


def _spine_beats_block(spine: str, beats: list[str]) -> str:
    parts = []
    if spine:
        parts.append("【核心张力】\n" + spine)
    if beats:
        parts.append("【结构节拍】\n" + "\n".join(f"- {b}" for b in beats))
    return "\n\n".join(parts)


def skeleton_user(title: str, content: str, profile: list[str]) -> str:
    parts = []
    block = _profile_block(profile)
    if block:
        parts.append(block)
    head = f"标题：{title}\n\n" if title else ""
    parts.append(f"{head}正文：\n{content}")
    return "\n\n".join(parts)


def edit_user(spine: str, beats: list[str], content: str, facts: list[str], profile: list[str]) -> str:
    parts = []
    block = _profile_block(profile)
    if block:
        parts.append(block)
    spine_block = _spine_beats_block(spine, beats)
    if spine_block:
        parts.append(spine_block)
    if facts:
        parts.append("【知识库事实】\n" + "\n".join(f"- {f}" for f in facts))
    else:
        parts.append("【知识库事实】\n（无相关记录）")
    parts.append("【正文】\n" + content)
    return "\n\n".join(parts)


def magic_tap_user(spine: str, beats: list[str], content: str, facts: list[str], profile: list[str]) -> str:
    parts = []
    block = _profile_block(profile)
    if block:
        parts.append(block)
    spine_block = _spine_beats_block(spine, beats)
    if spine_block:
        parts.append(spine_block)
    if facts:
        parts.append("【知识库中的相关事实】\n" + "\n".join(f"- {f}" for f in facts))
    parts.append("【已写正文】\n" + content)
    parts.append("请接着往下写。")
    return "\n\n".join(parts)
