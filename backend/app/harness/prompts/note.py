"""单篇笔记 harness 自己的提示词：检索规划、改骨架、接着往下写。

对应 hooks/note.py 和 middleware/replan.py。
"""

from __future__ import annotations

from .fragments import (content_block, facts_block, heading_format_reminder,
                        profile_block, spine_beats_block)


# ---------------------------------------------------------------- 单篇笔记 harness
#
# 跟无限续写（writing_plan.py）是同一个"自动修订+自动续写交替、直到内容
# 判定完整才停"的 harness 精神，范围收在一篇笔记内部——不创建新笔记，
# 完成条件是结构节拍（spine/beats）被正文实质覆盖，不是分段列表跑完。
#
# "写完了没有"不再靠续写模型自己在正文末尾主观判断、吐一个标记——见
# harness.checks.rubric.evaluate()：改成每轮续写完之后单独跑一次打分，续写这一步
# 只管往下写，不用兼顾"自我判断完不完整"这件事。

RETRIEVAL_PLAN_SYSTEM = """你是写作助手的检索规划环节。给你一篇正在写的
笔记和它接下来要写的方向，你只做一件事：**判断为了写好接下来这部分，
需不需要查用户的个人知识库；需要的话，把该查的一次查完。**

你现在**不需要写正文**，一个字都不用写。这一步的产出就是工具调用本身。

判断依据：
- 接下来要写的内容，是否依赖用户自己的记录——具体的人名、日期、数字、
  某次会议的结论、某个决定的来龙去脉。**这类东西凭空写就是编造**，必须查。
- 正文里已经出现了某个人名、产品名、项目名，接下来要展开它——先查清楚
  用户自己是怎么描述的，别用你以为的定义。
- 如果接下来这部分纯粹是推理、结构、取舍逻辑，不依赖任何具体事实，那就
  不用查，直接回复"不需要检索"。

怎么查——**先看问题是哪一类，再挑工具，不要一律用 search_memory**：

- **「在讨论 X 的那次会里，除了 X 还有什么」「聊 Y 的时候还定了什么」**
  ——需要先定位到某个场合、再看那个场合里还有什么：用 **search_session_context**。
  这类问题 search_memory 做不到，它只会按关键词捞一堆散落各处的事实，
  给不出"同一次会议里的其他内容"。判断标志是问题里有「那次」「上次」
  「当时」「除了…还」这类把范围锚定在某个场合上的说法。
- **知道确切主题 code**（上面主题清单里有的）：用 **filter_facts**，
  按主题精确取，比关键词匹配准得多，不会串味。
- **有明确关键词、就是想捞相关事实**：用 search_memory。它是字面匹配，
  中英混合的长查询容易召回完全不相关的内容，所以关键词要短、要具体。
- **要写某段时间发生了什么**：用 facts_in_range。
- **拿不准某条事实的确切含义**：用 fact_sources 回溯原话。

list_topics / list_entities 只是帮你决定往哪查的**元信息**，它们本身不返回
事实——只调它们就收手，等于什么都没查到。
- 一次把要查的都查了，同一件事不要换几种说法反复查。
- 拿到事实后如果拿不准某条的确切含义，可以用 fact_sources 回溯原话。

宁可多查一点，也不要在该查的时候不查——查不到最多是白花点时间，不查就
会编造，而编造出来的具体日期和人名会被用户当成自己的记录。

**这一步也是加载技能的地方。** 下面如果列了可用技能，判断这次写的东西
跟哪一条对得上，就调 load_skill 把它的完整说明拿进来；技能说明里提到某个
参考文件时再调 read_skill_ref。**只有这一步能调工具**——写正文那一步没有
工具可用，那时候再想起来就晚了。"""


def retrieval_plan_user(title: str, spine: str, beats: list[str], content: str,
                        steer: str = "", require_verification: bool = False,
                        topics_overview: str = "", section: str = "") -> str:
    """``steer`` 是策略控制器根据上一轮反馈给出的方向（见 runtime_policy.py）。

    它承载的是此前被整个丢掉的信号——打分模型写的自然语言诊断。上一轮说
    "使用了知识库中未出现的具体日期和人物"，这句话原封不动喂回检索规划，
    比只把最弱维度的名字塞进去能指导的多得多。
    """
    parts = []
    if section:
        # 大纲模式下这一轮只写某一节。**检索必须知道是哪一节**，否则每轮都
        # 拿同一批事实，模型只能把同一批材料换个标题再说一遍——20 轮 soak 里
        # non_repetition 是全局最弱的一维（0.9~1.7），大纲组 50 次撞 max_rounds
        # 而 beat_coverage 已经 1.9~2.0，卡住的正是重复。
        parts.append(f"【这一轮只写「{section}」这一节】\n"
                     f"查的材料要针对这一节，不要再取上几轮已经写过的那些。")
    if topics_overview:
        # 主题树直接摆出来，不让它先花一次工具往返去问「知识库里有什么」。
        #
        # 实测的问题：prompt 里明明写了「不确定就先 list_topics」，但六次
        # 检索全是 search_memory，一次都没用过主题树——引导写在文字里，
        # 模型还是走最短路径。而 search_memory 是关键词匹配，中英混合长
        # 查询会串味：查「Speaker C APP 安装 测试」召回的是知识库里《秘密
        # 花园》的英文段落。主题树本身零 LLM、亚毫秒，没有任何理由不直接
        # 给——摆在面前它才会用 filter_facts 按主题精确取。
        parts.append("【这个用户的知识库覆盖哪些主题（括号内是事实条数）】\n"
                     + topics_overview
                     + "\n\n上面这些 code 可以直接作为 filter_facts 的 topic 参数。"
                       "**主题对得上就优先用 filter_facts 按主题取，比 search_memory "
                       "的关键词匹配准得多**——关键词检索在中英混合的长查询上会召回"
                       "完全不相关的内容。")
    if title:
        parts.append(f"【笔记标题】\n{title}")
    block = spine_beats_block(spine, beats)
    if block:
        parts.append(block)
    parts.append(content_block(content, "（还没开始写）"))
    if steer:
        parts.append("【上一轮的反馈，这一轮优先处理】\n" + steer)
    if require_verification:
        parts.append("上一轮正文里的具体事实被判为站不住。这一轮凡是要写进正文的"
                     "具体人名、日期、数字，都要先查到出处；拿不准某条事实的确切"
                     "含义就用 fact_sources 回溯原话核对。")
    parts.append("接下来要续写这篇笔记，优先补上结构节拍里还没被正文覆盖的部分。"
                 "现在判断：需要查知识库吗？需要就调用工具，不需要就回复「不需要检索」。")
    return "\n\n".join(parts)


REPLAN_SYSTEM = """你是写作顾问，现在做一件很具体的事：**修正一份已经在用的
结构节拍**。

这份骨架是在正文还很短、还没查知识库的时候定的，掌握的信息比现在少。
现在正文写了一些、可能也检索到了具体材料，回头看会发现有的节拍定错了。
你要做的不是重写骨架，是**改掉错的那几条**。

只能做三种操作：
- ``rewrite``：把某一条节拍改写成更准确的说法（给 index 和新的 text）
- ``drop``：删掉某一条已经被证明不该服务的节拍（给 index）
- ``add``：补一条现有节拍完全没预见到的（给 text）

**绝对不许改核心张力（spine）**。核心张力换了就是另一篇文章，那不叫修正
叫跑题。你手上只有节拍这一层。

什么样的节拍该改：
- **放在任何一篇文章上都成立的修辞功能位**——「建立警示性处境」「预判读者
  追问」「收束呼应并强化行动指令」。它们描述的是通用议论文该长什么样，
  不是这一篇该写什么，正文没法"覆盖"它们，只能不断往上堆套话。改成落在
  具体内容上的说法：「用某某项目的实际成本构成说明物料价之外的开销占多少」。
- **把正文里的毛病当成了写作意图**——编号错序、前后矛盾、层级混乱这些是
  要被修掉的缺陷，不是这篇笔记的目标。发现节拍在要求"以编号错位呈现"
  这类东西，直接 drop。
- **跟检索到的材料对不上**——如果知识库里明明有一块很相关的具体内容，而
  现有节拍一条都没覆盖到它，补一条。

不要为了改而改：只有真的定错了才动，没问题的节拍原样留着不用出现在输出里。
节拍数量不会因为你的新增而变多（新增最多补回你删掉的条数），所以要新增
就先想清楚删哪条。

只输出 JSON 数组，形如：
[{"op": "rewrite", "index": 0, "text": "..."}, {"op": "drop", "index": 3},
 {"op": "add", "text": "..."}]
没有要改的就输出 []。不要任何解释文字。"""


def replan_user(title: str, spine: str, beats: list[str], content: str,
                facts: list[str], why: str) -> str:
    parts = [f"【为什么找你重排】\n{why}"]
    if title:
        parts.append(f"【笔记标题】\n{title}")
    parts.append(f"【核心张力（不许改，只作为判断依据）】\n{spine or '（空）'}")
    parts.append("【现有结构节拍（index 从 0 开始）】\n"
                 + "\n".join(f"{i}. {b}" for i, b in enumerate(beats)))
    if facts:
        parts.append("【这一轮从知识库检索到的材料】\n"
                     + "\n".join(f"- {f}" for f in facts[:12]))
    parts.append("【目前写成的正文】\n" + content)
    return "\n\n".join(parts)


def note_harness_continue_user(spine: str, beats: list[str], content: str,
                               facts: list[str], profile: list[str],
                               outline_note: str = "",
                               sections: list[str] | None = None) -> str:
    parts = []
    block = profile_block(profile)
    if block:
        parts.append(block)
    if outline_note:
        parts.append(outline_note)
    spine_block = spine_beats_block(spine, beats)
    if spine_block:
        parts.append(spine_block)
    if facts:
        parts.append(facts_block(facts))
    parts.append(content_block(content))
    if "##" not in content:
        parts.append(heading_format_reminder())
    parts.append(
        "请接着往下写，优先覆盖结构节拍里还没被正文实质覆盖的部分。没有给"
        "结构节拍的话，凭正文内容本身判断接下来该写什么。"
    )
    if sections:
        parts.append(place_directive_block(sections))
    return "\n\n".join(parts)


def place_directive_block(sections: list[str]) -> str:
    """定向续写：让模型先说这段该放进哪一节。

    正文已经有目录、各节也都有内容之后，「接着往下写」只会把所有新内容堆在
    最后一节底下（实拍：讲硬件延期的段落离「硬件」隔了两千字）。第一行的
    指令是确定性可解析的，位置由代码算——不让模型自己重排正文。
    """
    listed = "\n".join(f"- {t}" for t in sections[:24])
    return (
        "**第一行只写一句放置指令**，格式是「【放到：标题原文】」，标题从下面这些"
        "现有小节里选（原样照抄，不要改一个字）；实在不属于任何一节才写"
        "「【放到：文末】」。然后空一行开始正文。正文里不要再写那个小节的标题，"
        "也不要新开跟现有小节同名的标题。\n" + listed
    )


# 文件夹摘录长度上限——同文件夹笔记只是参考上下文，不是要复述的正文，塞太长
# 反而挤占知识库事实和已写正文的注意力
_FOLDER_NOTE_EXCERPT_CHARS = 600


def folder_context_block(notes: list[dict]) -> str:
    """无限续写用：把同文件夹里其他笔记的标题+摘录格式化成一段参考上下文。
    notes 是 store.notes_in_folder() 的返回值（已按更新时间排好序、去重了
    当前笔记）。没有笔记就返回空字符串，调用方按空串跳过这一段。"""
    if not notes:
        return ""
    sections = []
    for n in notes:
        title = (n.get("title") or "未命名").strip()
        excerpt = (n.get("content") or "").strip()[:_FOLDER_NOTE_EXCERPT_CHARS]
        if not excerpt:
            continue
        sections.append(f"### {title}\n{excerpt}")
    if not sections:
        return ""
    return ("【同文件夹其他笔记摘录（仅供参考上下文，不要直接复制原句，"
            "更不要跟这几篇笔记的内容重复）】\n" + "\n\n".join(sections))
