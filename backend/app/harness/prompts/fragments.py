"""提示词里反复出现的几块积木。

这四个的共同点是**不属于任何一条 harness**：谁要在提示词里放用户画像、
放骨架、提醒标题格式，就来拿一块。之前它们躺在 1119 行大文件的中段、
顶着下划线被三个别的段落调用——下划线在那里是假的，它们从来就是这个
文件对内的正式接口。
"""

from __future__ import annotations

import re


def profile_block(profile: list[str]) -> str:
    return "【个人偏好】\n" + "\n".join(f"- {p}" for p in profile) if profile else ""


def spine_beats_block(spine: str, beats: list[str]) -> str:
    parts = []
    if spine:
        parts.append("【核心张力】\n" + spine)
    if beats:
        parts.append("【结构节拍】\n" + "\n".join(f"- {b}" for b in beats))
    return "\n\n".join(parts)


FOCUS_LABELS = {
    "spine_fidelity": "正文是否紧扣核心张力（spine），而不是散成流水账",
    "beat_coverage": "有没有结构节拍完全没有对应内容",
    "topic_fidelity": "正文是否紧扣这个分段自己的主题，没有写到其他分段该写的内容",
    "non_repetition": "有没有跨段落/跨轮次的重复论点或结论",
    "coherence": "整篇是否自洽：有没有出现第二个结尾、标题层级混乱、"
                 "编号错序、前后体例不统一、或者自我拆台的表述",
    "factual_grounding": "正文依赖知识库事实的地方是否准确、有没有矛盾",
    "style_fit": "语气/结构/用词是否贴合个人偏好",
}


# 三处续写型 user prompt（magic_tap_user/section_write_user/
# note_harness_continue_user）共用同一条提醒：MAGIC_TAP_SYSTEM 的格式指令
# 是"延续已有格式风格"，但正文里还没出现过任何 "## " 标题时没有风格可
# 延续——实测这会让模型要么整段不分点写成散文，要么用 **加粗** 短语冒充
# 小节标题，跟后面真正用上标题的轮次体例不一致（同一篇笔记一节是"**标题**"
# 另一节是"## 标题"，读起来不像统一体例写出来的）。只在 content 里还没
# 出现过 "##" 时插入，已经有标题的话交给"延续已有风格"那条指令自然管，
# 不用再提醒一遍。
def heading_format_reminder() -> str:
    return (
        "正文里目前还没有出现过 \"## \" 这种标题——不代表不用格式。内容"
        "如果有并列/递进的小节或要点，照样要用 \"## \" 二级标题分节、"
        "\"- \" 列表分点，不要因为还没有\"已有风格\"可以延续就整段写成"
        "不分点的散文；也不要用 **加粗** 短语冒充小节标题——**加粗**只用来"
        "强调段落里的关键结论，跟标题是两回事，不能一节用标题、另一节用"
        "加粗假装标题。"
    )


# 材料开头的事实 id：``[terrence-2046-2F3] …``。跟 store._CITE / 前端 factCite 同一形状。
_FACT_ID = re.compile(r"^\[[A-Za-z][A-Za-z0-9_-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+\]")


def facts_block(facts: list[str]) -> str:
    """检索到的事实那一块。没有事实就返回空串，由调用方决定丢不丢。

    抽出来是因为它原本在五个提示词里**逐字重复**了五遍（单篇续写、分段
    写作、要不要再加几段、选区展开、magic tap）。模型在不同入口看到的
    材料格式必须是同一个；五份拷贝只要漂一份，就有一个入口的材料长得
    跟别处不一样，而且没有任何东西会报错。
    """
    if not facts:
        return ""
    block = "【知识库中的相关事实】\n" + "\n".join(f"- {f}" for f in facts)
    if any(_FACT_ID.match(f) for f in facts):
        # 引用规则只在材料真的带 id 时才说——没有 id 的材料（工具的多跳结果、
        # 原话回溯）说了也照不了办，反而诱导它编一个。
        block += ("\n\n引用规则：每条开头的 [编号] 是这条事实的 id。正文里用到某条事实时，"
                  "在那句话末尾**原样照抄**它的 [编号]（例：「…定在 6 月 30 日 [terrence-1872-5F8]」）。"
                  "只引用上面列出的编号，不要自己编；一句话用到几条就带几个。")
    return block


_DATA_URI = re.compile(r"\]\(data:[a-zA-Z0-9.+/-]+;base64,[^)\s]{16,}\)")


def strip_data_uris(content: str) -> str:
    """把内嵌的 base64 图片 / 音频换成一个占位：一张截图就是几十 KB 的 base64，
    原样进提示词等于把 token 全烧在一串没有任何语义的字母上，还可能把正文挤出
    上下文。占位保留了「这里有张图」这个事实。"""
    return _DATA_URI.sub("](内嵌图片)", content or "")


def content_block(content: str, empty: str = "") -> str:
    """已写正文那一块。``empty`` 是正文为空时替代它的那句话——

    三个调用方的说法不一样（「（还没开始写）」「（这个分段还没开始写）」、
    以及干脆原样给空），这个差别是有意的：模型据此知道自己在什么处境。
    所以留成参数，不统一。
    """
    return "【已写正文】\n" + (strip_data_uris(content) or empty)
