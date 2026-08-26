"""写作相关的提示词。

两条「线」来自产品构思文档：
  线 1 —— 为当前写作内容生成主线逻辑与骨架
  线 2 —— 结合骨架与已写内容，查询知识库后对文本做智能编辑
"""

SKELETON_SYSTEM = """你是写作助手。读用户正在写的内容，提炼出这篇文章的主线逻辑骨架。

要求：
- 输出 3-7 个要点，每个是一句话，描述这一段应该讲什么
- 覆盖已写内容的走向，并补上作者显然还没写但应该写的部分
- 只输出 JSON 数组，形如 ["要点1", "要点2"]，不要任何解释文字
"""

EDIT_SYSTEM = """你是写作编辑。给你三样东西：文章骨架、用户已写的正文、从用户知识库检索到的事实。

你的任务是提出**具体的修订建议**，让正文更准确、更贴合骨架。重点：
- 正文与知识库事实矛盾的地方，以事实为准提出更正
- 正文里含糊、可以用知识库事实补实的地方，提出补充
- 明显偏离骨架的地方，提出调整

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
- 如果给了知识库事实，优先用这些事实的内容来写，保证与用户已有的记录一致
- 如果没有相关事实，就按上下文自然地往下写
- 语言与用户正文保持一致
- 写 1-3 段即可
"""


def skeleton_user(title: str, content: str) -> str:
    head = f"标题：{title}\n\n" if title else ""
    return f"{head}正文：\n{content}"


def edit_user(skeleton: list[str], content: str, facts: list[str]) -> str:
    parts = []
    if skeleton:
        parts.append("【骨架】\n" + "\n".join(f"- {s}" for s in skeleton))
    if facts:
        parts.append("【知识库事实】\n" + "\n".join(f"- {f}" for f in facts))
    else:
        parts.append("【知识库事实】\n（无相关记录）")
    parts.append("【正文】\n" + content)
    return "\n\n".join(parts)


def magic_tap_user(skeleton: list[str], content: str, facts: list[str]) -> str:
    parts = []
    if skeleton:
        parts.append("【骨架】\n" + "\n".join(f"- {s}" for s in skeleton))
    if facts:
        parts.append("【知识库中的相关事实】\n" + "\n".join(f"- {f}" for f in facts))
    parts.append("【已写正文】\n" + content)
    parts.append("请接着往下写。")
    return "\n\n".join(parts)
