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
- 已经有的内容不要用换一种说法重复提一遍——检查一下 text 里要写的结论是不是
  正文别处已经说过了，是的话跳过这条
- **专门找一遍正文里有没有已经存在的重复**：这篇正文可能是分好几轮续写
  出来的，不同轮次容易在换一种措辞的情况下把同一个结论/同一组边界条件/
  同一个论点说了不止一次（比如前面一节讲过"这个方案的适用边界是……"，
  后面一节用不同的句子又把同一组边界条件讲了一遍）。发现这种情况，对
  较晚出现、信息量较小或者不如另一处完整的那次重复，提一条 delete
  把它删掉——这条检查不依赖 spine/beats，是专门为多轮续写场景加的，
  上面几条是"这处该不该改"，这条是"这两处是不是在说同一件事"
- **删除内容后留意有没有留下空壳标题**：如果你提的某条 delete/replace 会
  让一个 `## 标题` 底下基本没剩什么内容（标题后面直接空行接下一个标题，
  或者只剩一两句无关紧要的过渡话），额外再提一条 delete 把这个空壳标题
  本身也删掉——不要留下正文里读起来"这一节几乎是空的"这种痕迹

正文是 Markdown，text 字段里可以用格式语法（**加粗**关键结论、"- " 列出
并列项）让插入/替换的内容更易读；但不要为了格式而格式，纯粹是一两句话的
修订不需要刻意加格式。知识库事实的语言不一定跟正文一致（可能是英文），
写进 text 前先转换成正文的语言意译，不要把原文语言的句子原样嵌进来。

严格约束：
- 只输出 JSON 数组，不要解释文字
- 每条形如 {"op":"replace","anchor":"原文中要被替换的确切片段","text":"替换成的新内容","reason":"为什么改","sources":["依据的事实原文"]}
- op 取值：insert（在 anchor 之后插入 text）/ delete（删除 anchor）/ replace（把 anchor 换成 text）
- anchor 必须是正文里**逐字出现**的片段，不要改写它，否则前端定位不到
- 没有值得改的地方就输出 []
- 最多 6 条，挑最重要的
"""

# mermaid 之前完全没在任何写作 prompt 里出现过——编辑器能渲染，但没有任何
# 提示词告诉模型"你可以画图"，所以模型自然从来不产出 ```mermaid，看起来就
# 像是"没实现"。这里给了触发条件（流程/时间线/层级/多方关系）和一个可抄的
# 最小语法样例，而不是空泛地说"可以用 mermaid"——本地模型不给具体语法示例
# 很容易画出解析不了的图。
_MERMAID_HINT = """如果接下来要写的内容本质上是流程、时间线、层级结构或多
方关系（比如"谁向谁汇报""这几步先后怎么推进""哪些角色互相牵扯"），优先
用 ```mermaid 代码块画出来，比堆文字更清楚。纯叙述、说理、描述性的内容不
需要画图，不要为了用而用。最小语法示例（可参照改写，不要照抄内容）：
```mermaid
graph TD
A[需求确认] --> B[样机测试]
B --> C[外观定型]
```
节点的 [方括号标签] 里绝对不能出现任何引号字符——直引号 " 和中文弯引号
"  都不行，哪怕原文里那句话本身带着引号也要去掉再写进标签，否则图会直接
解析失败（渲染成一个大大的错误图标，等于白画）。比如原文是"录制信任：从
"随时录"到"一定录到且不尴尬""，标签只能写成 A[录制信任：从随时录到一定
录到且不尴尬]，把引号去掉，不要用转义、不要用别的引号替代，直接去掉。
"""

MAGIC_TAP_SYSTEM = f"""你是写作助手，负责接着用户的文字往下写。

- 续写之前，先通读一遍已写正文，在心里记住已经提出过的结论/论点/数字，
  确保接下来不会用不同的措辞重新说一遍同一件事。这条是实测踩过的真实
  问题：模型经常在文章末尾把前面某个结论重新总结一遍（"XX 即为 YY 的
  关键点"这类句子在正文靠前的地方已经出现过，结尾又用近似的话再说一次）
  ——发现自己要写的内容在传达同一个结论，就跳过，往下一个还没写过的点走，
  不要因为想"呼应"或"总结"就重复
- 直接续写正文，不要复述已有内容
- 正文是 Markdown：延续已有的格式风格——原文在用列表就继续用列表，在用
  标题就延续标题层级；关键结论用 **加粗**；并列的多项内容用 "- " 列表；
  有先后顺序的步骤用 "1. " 有序列表。信息密度高、有多个并列小节的内容
  （比如分主题的进展汇报），每个小节都应该有自己的二级标题，不是只有
  其中一节加了格式、其余堆成大段文字——要么都用结构化格式，不要选择性地
  只格式化一部分
- 如果续写内容开始满足一个新的结构节拍（真正的结构性转折，不是随手换个
  话题），可以用一个简短的二级标题（## ...）标出这个转折，让结构在文档里
  看得见，而不是所有内容挤成一段连续的流水账；但不要每段都加标题，只在
  真正的转折处加
- 标题必须独占一行，前面空一行再写：不要写成"接下来我们看 ## 如何应对"这样
  把 "##" 接在其他文字后面同一行——不空行、不换行的 "##"/"###" 不会被解析
  成标题，只会变成正文里几个多余的井号；另外标题内容不要跟它前面那句话
  说的是同一件事（比如前面刚说完"我们该如何克服挑战"，标题又写一遍"如何
  克服挑战"），标题是给下面内容分节用的，不是复述上一句
- {_MERMAID_HINT}
- 如果给了核心张力和结构节拍，续写要接着满足下一个还没完成的节拍，不要
  偏离核心张力自由发挥
- 如果给了知识库事实，优先用这些事实的内容来写，保证与用户已有的记录一致；
  知识库里的事实语言不一定跟正文一致（可能是英文），融入正文前要先转换成
  正文的语言意译，不要把原文语言的句子原样嵌进来
- 检索到的事实不是每条都真的贴合你正在写的这一点——判断一下：这条事实
  能不能自然地支撑或印证你要写的内容，不是"检索到了就必须想办法用上"。
  正文的主题如果跟知识库里这些事实所属的领域根本不是一回事（比如正文在
  谈个人习惯，检索到的事实全是另一个产品项目的进度细节），不要为了显得
  "有依据"硬把不相关的事实编成一个牵强的类比或案例——读起来会很突兀，
  用户会觉得莫名其妙插进来一段不相关的东西。这种时候，跳过这些事实、
  按上下文本身的逻辑自然写下去，比强行牵扯一个不搭的类比要好
- 如果给了个人偏好，续写的语气、结构、用词习惯要贴合这些偏好
- 如果没有相关事实，就按上下文自然地往下写
- 语言与用户正文保持一致
- 写 1-3 段即可，除非用了标题或图表让篇幅自然变长
"""


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

只输出 JSON，形如 {"before":"要插在选中片段之前的内容","after":"要插在选中片段之后的内容"}
- before/after 各自独立判断要不要写，都不需要就都留空字符串，不要硬凑
- 不要重复选中片段本身已经说过的内容
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
  填对应事实编号（笔记自身支持的话填 -1）
- 找不到任何相关信息可以判断：verdict 填"无法判断"，reason 说明原因，
  fact_index 填 -1——找不到证据不等于有问题，不要为了给结论而牵强附会

只输出 JSON 数组，每条形如：
{"verdict":"矛盾"|"支持"|"无法判断","reason":"...","fact_index":整数}
最多 4 条，只挑真正有判断依据的，不要为了凑数硬找；如果完全没有值得
指出的地方，输出 []。
"""


def rewrite_user(content: str, selection: str, spine: str, beats: list[str]) -> str:
    parts = []
    spine_block = _spine_beats_block(spine, beats)
    if spine_block:
        parts.append(spine_block)
    parts.append("【完整正文】\n" + content)
    parts.append("【被选中要处理的片段】\n" + selection)
    return "\n\n".join(parts)


def expand_user(content: str, selection: str, facts: list[str] | None = None) -> str:
    parts = [f"【完整正文】\n{content}", f"【被选中的片段（要在它前后补上下文）】\n{selection}"]
    if facts:
        parts.append("【知识库中的相关事实】\n" + "\n".join(f"- {f}" for f in facts))
    return "\n\n".join(parts)


def verify_user(content: str, selection: str, facts: list[str]) -> str:
    parts = ["【笔记完整正文】\n" + content, "【待核查内容】\n" + selection]
    if facts:
        numbered = "\n".join(f"[{i}] {f}" for i, f in enumerate(facts))
        parts.append("【知识库检索到的相关事实】\n" + numbered)
    else:
        parts.append("【知识库检索到的相关事实】\n（没有找到相关记录）")
    return "\n\n".join(parts)


def digest_user(facts: list[str]) -> str:
    return "【事实（按时间顺序）】\n" + "\n".join(facts)


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


_FOCUS_LABELS = {
    "spine_fidelity": "正文是否紧扣核心张力（spine），而不是散成流水账",
    "beat_coverage": "有没有结构节拍完全没有对应内容",
    "topic_fidelity": "正文是否紧扣这个分段自己的主题，没有写到其他分段该写的内容",
    "non_repetition": "有没有跨段落/跨轮次的重复论点或结论",
    "factual_grounding": "正文依赖知识库事实的地方是否准确、有没有矛盾",
    "style_fit": "语气/结构/用词是否贴合个人偏好",
}


def edit_user(spine: str, beats: list[str], content: str, facts: list[str],
              profile: list[str], focus: str = "") -> str:
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
    if focus:
        label = _FOCUS_LABELS.get(focus, focus)
        parts.append(f"【这一轮优先检查】\n上一轮评分里这一项最弱：{label}。"
                     "优先看这个问题有没有解决，其余几条原则仍然适用，但不用逐条重新过一遍。")
    parts.append("【正文】\n" + content)
    return "\n\n".join(parts)


# 三处续写型 user prompt（magic_tap_user/section_write_user/
# note_harness_continue_user）共用同一条提醒：MAGIC_TAP_SYSTEM 的格式指令
# 是"延续已有格式风格"，但正文里还没出现过任何 "## " 标题时没有风格可
# 延续——实测这会让模型要么整段不分点写成散文，要么用 **加粗** 短语冒充
# 小节标题，跟后面真正用上标题的轮次体例不一致（同一篇笔记一节是"**标题**"
# 另一节是"## 标题"，读起来不像统一体例写出来的）。只在 content 里还没
# 出现过 "##" 时插入，已经有标题的话交给"延续已有风格"那条指令自然管，
# 不用再提醒一遍。
def _heading_format_reminder() -> str:
    return (
        "正文里目前还没有出现过 \"## \" 这种标题——不代表不用格式。内容"
        "如果有并列/递进的小节或要点，照样要用 \"## \" 二级标题分节、"
        "\"- \" 列表分点，不要因为还没有\"已有风格\"可以延续就整段写成"
        "不分点的散文；也不要用 **加粗** 短语冒充小节标题——**加粗**只用来"
        "强调段落里的关键结论，跟标题是两回事，不能一节用标题、另一节用"
        "加粗假装标题。"
    )


def magic_tap_user(spine: str, beats: list[str], content: str, facts: list[str],
                   profile: list[str], folder_context: str = "") -> str:
    parts = []
    block = _profile_block(profile)
    if block:
        parts.append(block)
    spine_block = _spine_beats_block(spine, beats)
    if spine_block:
        parts.append(spine_block)
    if folder_context:
        parts.append(folder_context)
    if facts:
        parts.append("【知识库中的相关事实】\n" + "\n".join(f"- {f}" for f in facts))
    parts.append("【已写正文】\n" + content)
    if "##" not in content:
        parts.append(_heading_format_reminder())
    parts.append("请接着往下写。")
    return "\n\n".join(parts)


# ---------------------------------------------------------------- 单篇笔记 harness
#
# 跟无限续写（writing_plan.py）是同一个"自动修订+自动续写交替、直到内容
# 判定完整才停"的 harness 精神，范围收在一篇笔记内部——不创建新笔记，
# 完成条件是结构节拍（spine/beats）被正文实质覆盖，不是分段列表跑完。
#
# "写完了没有"不再靠续写模型自己在正文末尾主观判断、吐一个标记——见
# writer_harness.evaluate()：改成每轮续写完之后单独跑一次打分，续写这一步
# 只管往下写，不用兼顾"自我判断完不完整"这件事。

def note_harness_continue_user(spine: str, beats: list[str], content: str,
                               facts: list[str], profile: list[str]) -> str:
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
    if "##" not in content:
        parts.append(_heading_format_reminder())
    parts.append(
        "请接着往下写，优先覆盖结构节拍里还没被正文实质覆盖的部分。没有给"
        "结构节拍的话，凭正文内容本身判断接下来该写什么。"
    )
    return "\n\n".join(parts)


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


# ---------------------------------------------------------------- 无限续写计划
#
# 跟 SKELETON_SYSTEM 的 spine/beats（一篇文章内部的修辞结构）是两回事——
# 这里的"分段"是内容主题的拆分，每个分段最终落成文件夹里独立的一篇笔记，
# 拆的是"要写哪些东西"，不是"一篇东西怎么组织"。

PLAN_SYSTEM = """你是写作规划助手。用户给了一个写作目标，你要把它拆解成
一份有序的分段列表——每个分段最终会独立成一篇笔记，所以分段之间应该是
并列或递进的关系（不是同一件事换个说法说两遍），合起来覆盖这个目标。

要求：
- 分段数量不用刻意控制，够覆盖目标即可，通常 3-8 个；如果目标本身很大，
  给更多也可以——后面写的过程中还能再追加，不用现在就想全
- 每条分段是一个简短的主题短语（比如"硬件续航方案"），不是完整句子，
  不要写"介绍/说明 XX"这种空洞前缀
- 分段之间不要互相包含或大面积重叠
- 如果给了已有笔记或知识库事实，分段要贴合这些已有材料的实际情况，不要
  凭空想象一个跟已有材料无关的大纲
- 只输出 JSON 数组，形如 ["分段1", "分段2", ...]，不要任何解释文字
"""


def plan_user(goal: str, facts: list[str], folder_context: str) -> str:
    parts = [f"【写作目标】\n{goal}"]
    if folder_context:
        parts.append(folder_context)
    if facts:
        parts.append("【知识库中的相关事实】\n" + "\n".join(f"- {f}" for f in facts))
    parts.append("请给出分段列表。")
    return "\n\n".join(parts)


def section_write_user(section_title: str, goal: str, prior_summaries: list[str],
                       content: str, facts: list[str], folder_context: str,
                       profile: list[str], focus: str = "") -> str:
    parts = []
    block = _profile_block(profile)
    if block:
        parts.append(block)
    parts.append(f"【这篇笔记要写的分段主题】\n{section_title}")
    if goal:
        parts.append(f"【整个写作计划的总体目标】\n{goal}")
    if prior_summaries:
        parts.append("【计划里已完成的其他分段小结（避免重复，需要呼应时可以引用，"
                     "但不要把它们的内容重写一遍）】\n"
                     + "\n".join(f"- {s}" for s in prior_summaries))
    if folder_context:
        parts.append(folder_context)
    if facts:
        parts.append("【知识库中的相关事实】\n" + "\n".join(f"- {f}" for f in facts))
    parts.append("【已写正文】\n" + (content or "（这个分段还没开始写）"))
    if "##" not in content:
        # 笔记标题已经是这个分段的主题了，不用在正文里再重复一次一级标题
        # ——这条是 section_write 特有的（每个 section 独立成一篇笔记，标题
        # 就是分段主题），magic_tap_user/note_harness_continue_user 的笔记
        # 标题是用户自己起的，不适用这条，所以没放进共享的
        # _heading_format_reminder() 里。
        parts.append(_heading_format_reminder() + "笔记标题已经是这个分段的主题了，不用再写一遍一级标题。")
    if focus:
        label = _FOCUS_LABELS.get(focus, focus)
        parts.append(f"【上一轮评分里这一项最弱】\n{label}，这一轮优先解决这个问题。")
    parts.append("请接着写，只围绕上面这个分段主题展开，不要跑去写其他分段该写的内容。")
    return "\n\n".join(parts)


MORE_SECTIONS_SYSTEM = """你是写作规划助手。一份写作计划的所有已规划分段都
写完了，现在要判断：基于写作目标、已经写完的这些分段、以及知识库里的相关
事实，还有没有明显遗漏、值得单独再开一个分段来写的内容。

要求：
- 不要为了凑数硬找新分段——如果目标已经被现有分段覆盖得比较完整了，就
  如实说没有了，这是正常的终止条件，不是失败
- 只有当知识库事实或已有笔记里明显有一块内容跟目标相关、但完全没被任何
  已完成分段覆盖到时，才提出新分段
- 只输出 JSON 数组，形如 ["新分段1", "新分段2"]；如果没有更多，输出 []
"""


def more_sections_user(goal: str, section_summaries: list[str], facts: list[str],
                       folder_context: str) -> str:
    parts = [f"【写作目标】\n{goal}"]
    if section_summaries:
        parts.append("【已完成的分段小结】\n" + "\n".join(f"- {s}" for s in section_summaries))
    if folder_context:
        parts.append(folder_context)
    if facts:
        parts.append("【知识库中的相关事实（这轮重新检索的，可能有新内容）】\n"
                     + "\n".join(f"- {f}" for f in facts))
    parts.append("还有没有更多值得写的分段？")
    return "\n\n".join(parts)


# TRACELOG [10] 的发现（现在由 writer_harness.evaluate() 的 beat_coverage
# 维度承接，见 app/harness_adapter.py 里这个维度的 guidance 文案）：
# note_harness 每轮"要不要停"完全靠模型自己在续写输出末尾主观判断——实测
# 一个 4 条 beats 的笔记，第 1 轮就已经把 4 条 beats 都实质覆盖了，模型却
# 继续跑到第 5 轮才主观判定"完整"，中间 3 轮全是把同样几个结论换着法子
# 再展开一遍（定价讲了 4 次、资源冲突讲了 3 次）。根因是完成判定跟 beats
# 完全脱钩，续写模型本身没有动力主动收敛——独立打一次分，把"是否完整"从
# 模型的主观续写判断里剥离出来，才是这个问题的真正解法。


def join_round_text(content: str, round_text: str) -> str:
    """跨轮次续写累积正文时用这个，不要直接用 `content + round_text`——
    实测真实撞过：上一轮恰好停在一个 mermaid 代码块的收尾 \"```\" 上（流式
    结束时没有保证有尾随换行），下一轮的内容紧接着拼上去，变成同一行的
    \"```### 新标题\"，markdown 解析器不认这是"代码块结束+新标题"，代码块
    可能都不会正常闭合，后面一大段内容跟着解析错位（TRACELOG [8]）。
    两边各自 strip 掉首尾换行再用固定的空行拼接，不管两边原来各自有没有
    换行都能保证拼接处至少空一行——note_harness.py 单篇内 harness、
    writing_plan.py 分段 harness 的跨轮次累积都要走这个，不要各自维护一份
    容易漏改的拼接逻辑。"""
    if not round_text:
        return content
    if not content:
        return round_text
    return content.rstrip("\n") + "\n\n" + round_text.lstrip("\n")


def render_tracking_doc(goal: str, status: str, sections: list[dict]) -> str:
    """把 plan+sections 的结构化状态渲染成一篇人可读的笔记正文——这是用户
    实际会打开看的"追踪文档"，但它是单向从数据库状态生成的镜像，harness
    自己的状态判断永远只读数据库，不会回头解析这篇笔记的 markdown。"""
    lines = ["# 写作追踪", "", "## 目标", goal or "（未设定）", "", "## 进度"]
    status_label = {"pending": "⬜ 待写", "in_progress": "🔄 写作中", "done": "✅ 已完成"}
    for s in sections:
        mark = status_label.get(s["status"], s["status"])
        lines.append(f"- {mark} **{s['title']}**")
        if s.get("summary"):
            lines.append(f"  {s['summary']}")
    lines.append("")
    plan_status_label = {"active": "进行中", "done": "已完成", "abandoned": "已停止"}
    lines.append(f"## 计划状态：{plan_status_label.get(status, status)}")
    return "\n".join(lines)


# ---------------------------------------------------------------- Skill 系统
#
# 把"写作规则"从写死在各个 XXX_SYSTEM 常量里的固定文本，变成可存储、可
# 开关、可编排顺序的独立单元——每条 skill 挂在一个或多个 scope（对应下面
# 某个生成调用点）上，生成时在那个调用点的基础 system prompt 之后按顺序
# 叠加。基础 prompt（MAGIC_TAP_SYSTEM 这些）仍然是地基，不会被 skill 替换
# 掉，skill 只是追加的行为约束，这样已经踩过坑调好的核心规则不会被一条
# 写得不好的 skill 意外覆盖。

# 每个 scope 对应代码里实际的一个生成调用点，不是随便起的分类——新增调用
# 点时要同步在这里加一条，否则那个调用点的 skill 面板选项会找不到对应位置。
SKILL_SCOPES = {
    "magic_tap": "续写（magic tap）",
    "section_write": "无限续写 · 分段写作",
    "plan_generate": "无限续写 · 生成分段计划",
    "more_sections": "无限续写 · 判断还有更多",
    "verify": "选中校验",
    "rewrite": "选中重写",
    "polish": "选中润色",
    "expand": "选中扩展上下文",
    "edit": "整篇修订建议",
    "skeleton": "生成骨架",
    "digest": "阶段回顾",
}


def compose_system(base: str, skills: list[dict]) -> str:
    """在基础 system prompt 后面按顺序叠加启用的 skill 内容。skills 已经是
    过滤+排序好的（见 store.enabled_skills_for_scope），这里只管拼。"""
    if not skills:
        return base
    parts = [base, "以下是额外启用的写作技能，在不违反上面规则的前提下按顺序叠加生效："]
    for sk in skills:
        parts.append(f"【{sk['name']}】\n{sk['content']}")
    return "\n\n".join(parts)


def skill_generate_system() -> str:
    """懒生成而不是模块顶层常量——要引用 DEFAULT_SKILLS 里的例子当风格
    参考，放函数里避免在模块加载顺序上对 DEFAULT_SKILLS（定义在下面）产生
    依赖。"""
    scope_lines = "\n".join(f"- {k}：{v}" for k, v in SKILL_SCOPES.items())
    examples = "\n\n".join(
        f"例：{sk['name']}\n{sk['content']}" for sk in DEFAULT_SKILLS[:3]
    )
    return f"""你是写作技能生成助手。用户会用一两句话描述想要的写作行为，
你要把它写成一条具体、可执行的写作指令。

可选的生效范围（scope）：
{scope_lines}

要求：
- name：8-16 字左右的技能名称
- description：一句话说明这条技能做什么
- scopes：从上面的可选范围里选 1-3 个最贴合用户描述意图的，不要瞎猜太多、
  跟意图明显无关的范围不要选
- content：具体的指令内容，风格参考下面的例子——描述具体的"不要做什么/
  要做什么"，给出可以直接照做的判断标准，不要写"让内容更好""提升质量"
  这种空话
- 只输出 JSON，形如 {{"name":"...","description":"...","scopes":["..."],"content":"..."}}，
  不要任何解释文字

参考风格例子：
{examples}
"""


def skill_generate_user(goal: str, scope_hint: str = "") -> str:
    parts = [f"【用户想要的写作行为】\n{goal}"]
    if scope_hint:
        parts.append(f"【用户指定的生效范围提示】\n{scope_hint}")
    parts.append("请生成这条技能。")
    return "\n\n".join(parts)


# 从调研到的高质量 Claude Skill 改写来的默认技能——内容是重新写的、贴合
# MEMOKET_NOTE 现有 prompt 风格的中文版本，不是原文翻译。每条有个稳定的
# "key"，store._seed_missing_default_skills() 靠它做增量播种（判断这个
# 用户是不是已经有过这条了），所以这里新增条目会自动补给已有用户，但已经
# 加过的 key 千万不能改字符串本身，否则等于又是一条新的，会重复种一遍。
#
# 覆盖面：11 个生成调用点（SKILL_SCOPES）现在每个至少有一条，不是只集中
# 在校验/无限续写这两个我最先调研的方向——续写、分段写作、判断还有没有
# 更多、扩展上下文、整篇修订、生成骨架、阶段回顾之前是空的，都补上了。
DEFAULT_SKILLS: list[dict] = [
    {
        "key": "doc-coauthoring-sections",
        "name": "结构化分段（受doc-coauthoring 启发）",
        "description": "生成分段列表前先想清楚读者会追问什么，让分段之间体现真正的推进关系，不是把目标里的名词各开一段。",
        "scopes": ["plan_generate"],
        "content": (
            "生成分段列表前，先在心里过一遍：这个目标如果要写成一份完整、"
            "经得起读者检验的文档，读者最可能追问的几个问题是什么——分段要"
            "覆盖到能回答这些追问，不是简单地把目标里出现的名词各开一段。"
            "分段之间要能看出明确的推进关系（比如问题→方案→验证→执行这种"
            "结构性递进），不是并列罗列话题。"
        ),
    },
    {
        "key": "discernment-nudge-verify-triage",
        "name": "校验触发/跳过规则（受discernment-nudge 启发）",
        "description": "只标记看起来像事实陈述、但知识库里没有直接支持的具体论断，别把创意表达或用户已承认的猜测也标成待核实。",
        "scopes": ["verify"],
        "content": (
            "给内容打校验标记前，先判断值不值得校验：如果选中内容是纯粹的"
            "创意表达、语气性的润色用词，或者用户已经在这句话里明确说了"
            "是自己的猜测/不确定，就不用标记为需要核实——只标记那些看起来"
            "像陈述事实、但没有在知识库里找到直接支持的具体论断（数字、"
            "时间点、因果关系、归因）。每条校验意见要说清楚缺的是什么证据，"
            "不要只说“建议核实”这种空话。"
        ),
    },
    {
        "key": "brainstorming-confirm-scope",
        "name": "生成前确认范围（受brainstorming 启发）",
        "description": "目标描述得模糊或范围很大时，先给一份偏保守聚焦的分段列表，而不是自己脑补一个特别大的计划。",
        "scopes": ["plan_generate"],
        "content": (
            "如果写作目标描述得比较模糊、或者范围看起来很大（比如笼统的"
            "“写一份 XX 规划”没给出具体边界），不要因为目标模糊就默认展开"
            "成一个特别大而全的计划，宁可先给一份偏保守、聚焦在目标里明确"
            "提到的内容的分段列表——范围不够可以后面用「还有没有更多」的"
            "机制自然补上，先给太大的范围反而容易写偏。"
        ),
    },
    {
        "key": "structured-reasoning-evidence-tiers",
        "name": "区分证据确定性（受结构化推理 skill 启发）",
        "description": "校验意见要区分「原文直接支持」「能合理推断但没有直接原文」「知识库完全没提到」三种不同确定性，不要把推断包装成原文支持。",
        "scopes": ["verify"],
        "content": (
            "给出校验意见时，明确区分三类确定性：知识库里有原文直接支持的"
            "（标“支持”或“矛盾”，给出原文依据）；知识库里没有直接证据、但"
            "能从已有事实合理推出的（说明这是推断，以及推理链条是什么）；"
            "以及知识库完全没提到、纯粹在正文之外的（如实说无法判断，不要"
            "为了给出意见就强行编一个）。不要把“合理推断”包装成“原文支持”，"
            "这是两种确定性完全不同的结论，混在一起会让人误判证据强度。"
        ),
    },
    {
        "key": "source-check-top-edit-rewrite",
        "name": "保留具体信息 + 去 AI 味（受source-check/top-edit 启发）",
        "description": "重写润色时别把数字、人名、时间点这类具体信息改得笼统模糊，同时主动去掉套话开头、过度排比、各打五十大板式的和稀泥表达。",
        "scopes": ["rewrite", "polish"],
        "content": (
            "重写/润色时如果正文里有具体的数字、人名、时间点、因果归因这类"
            "可核实的陈述，优先原样保留这些具体信息，不要在让语言更顺的过程"
            "中把具体表述改得更笼统模糊——这是最常见的把内容改“顺”但改“空”的"
            "失误。同时检查有没有典型的 AI 写作痕迹要去掉：不必要的“总的来说”"
            "“值得注意的是”这类套话开头、过度使用排比结构、正反双面各打"
            "五十大板式的和稀泥表达——发现就直接去掉，不用保留痕迹。"
        ),
    },
    {
        "key": "llm-writing-avoid-defaults",
        "name": "去 AI 写作痕迹（受llm-writing 启发）",
        "description": "续写时主动避开排比收尾、升调句式、硬凑对比这些无意识的 AI 写作默认习惯，句子长短要自然变化。",
        "scopes": ["magic_tap"],
        "content": (
            "续写时主动避开无意识的 AI 写作默认习惯：不要每段都用排比句式"
            "收尾，不要习惯性地用“这不仅…而且…”这种升调句式制造虚假的重要"
            "感，没有实际内容对比时不要硬凑“不是 A，而是 B”这种句式来制造"
            "深度感。句子长短应该自然变化，不要每句都写成中等长度的复合句"
            "——短句、长句交替，跟真实写作的语感一致。"
        ),
    },
    {
        "key": "story-memory-term-consistency",
        "name": "分段术语一致性（受story-memory 启发）",
        "description": "分段写作时人名/项目名/专有名词的写法要跟其他分段保持一致，不要在这一段又造一个新叫法。",
        "scopes": ["section_write"],
        "content": (
            "这个分段引用的人名、项目名、专有名词、缩写，写法要跟计划里其他"
            "分段/已完成小结保持完全一致，不要在这段又造一个新叫法（比如已经"
            "统一用某个正式项目名，就不要在这段又换成非正式简称，除非原文"
            "本身就是这么叫的）。发现术语不一致，以先写的那个分段为准。"
        ),
    },
    {
        "key": "discernment-nudge-more-sections-restraint",
        "name": "宁缺毋滥（受discernment-nudge 的克制原则启发）",
        "description": "判断还有没有更多分段时默认倾向于「没有了」，只有知识库里明显有一块内容完全没被覆盖到才追加。",
        "scopes": ["more_sections"],
        "content": (
            "判断还有没有更多分段时，默认倾向于“没有了”——只有当知识库事实"
            "或已有笔记里有一块跟目标明显相关、但完全没被任何已完成分段覆盖"
            "到的具体内容时，才提出新分段。不要因为“这个话题理论上还能再"
            "展开”就加分段，展开空间是无限的，但那不代表值得写。"
        ),
    },
    {
        "key": "story-planning-expand-consistency",
        "name": "扩展不能制造矛盾（受story-planning 的一致性检查启发）",
        "description": "往前/往后补充上下文前，先扫一遍正文其他地方有没有相关的既定信息，补充内容不能跟已经写出的部分矛盾。",
        "scopes": ["expand"],
        "content": (
            "往前/往后补充上下文时，补充的内容不能跟正文里已经明确写出的"
            "信息矛盾——如果正文后面已经提到某个结论或数字，往前补的背景就"
            "不能暗示一个不同的结论或数字。补充前先扫一遍正文其他部分有没有"
            "相关的既定信息。"
        ),
    },
    {
        "key": "source-check-edit-evidence",
        "name": "修订意见要给具体依据（受source-check 启发）",
        "description": "每条修订建议要说清楚具体依据是知识库哪条事实或正文哪句话，给不出具体依据就不提这条。",
        "scopes": ["edit"],
        "content": (
            "每条修订建议的理由要说清楚具体依据是什么（引用了知识库哪条"
            "事实、或者正文哪里的哪句话跟这里矛盾），不要写“表述不够准确”"
            "这种没有具体依据的空泛理由——给不出具体依据的地方，宁可不提"
            "这条修订。"
        ),
    },
    {
        "key": "top-edit-structural-patterns",
        "name": "跨全文结构套路检查（受top-edit 启发）",
        "description": "检查有没有每节都用一模一样的三段式展开、每次建议都硬凑够三条这类结构性的 AI 写作套路，不只是逐句看。",
        "scopes": ["edit"],
        "content": (
            "除了逐句检查，也要跨全文看有没有结构性的 AI 写作痕迹：是不是"
            "每个小节都用一模一样的套路展开（比如永远是“背景/现状/建议”三"
            "段式，不管内容是否真的适合这个结构）；是不是每次给建议都必须"
            "凑够三条，明显是为了凑数而不是真的有三个要点。发现这种结构性"
            "套路化，在修订建议里指出来。"
        ),
    },
    {
        "key": "doc-coauthoring-anticipate-questions",
        "name": "先想读者会追问什么（受doc-coauthoring 的语境收集启发）",
        "description": "生成骨架的 beats 之前先想清楚读者会在哪里卡住、追问什么，beats 里至少留一条专门用来接住这些追问。",
        "scopes": ["skeleton"],
        "content": (
            "生成 beats 之前，先想清楚这篇东西如果拿给一个不了解背景的读者"
            "看，读者会在哪里卡住、会追问什么——beats 里至少要有一条是专门"
            "用来接住这些追问的（比如“预判反对意见”“补充背景”），不能只有"
            "正叙推进、没有防守的部分。"
        ),
    },
    {
        "key": "highlight-deltas-digest",
        "name": "标出变化而不只是罗列",
        "description": "阶段回顾的「值得注意的变化」要专门标出跟更早记录相比的改变/反转/矛盾，不要图省事写成「没有变化」。",
        "scopes": ["digest"],
        "content": (
            "阶段回顾不只是把这段时间的事实分类罗列，“值得注意的变化”这一"
            "节要专门标出跟更早的记录相比发生了改变、反转、或者互相矛盾的"
            "地方——这是回顾最有价值的部分，不要因为找起来麻烦就跳过，写成"
            "“没有变化”之前先确认真的对比过前后的事实。"
        ),
    },
]
