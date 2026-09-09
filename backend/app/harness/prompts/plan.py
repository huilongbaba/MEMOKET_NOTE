"""无限续写计划 harness 自己的提示词：拆分段、写一段、要不要再加几段。

对应 hooks/section.py 和 routers/writing_plan.py。
"""

from __future__ import annotations

from .fragments import FOCUS_LABELS, heading_format_reminder, profile_block


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
    block = profile_block(profile)
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
        # heading_format_reminder() 里。
        parts.append(heading_format_reminder() + "笔记标题已经是这个分段的主题了，不用再写一遍一级标题。")
    if focus:
        label = FOCUS_LABELS.get(focus, focus)
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
- **提出每一个新分段之前，先逐条对照已完成分段的标题和"覆盖："里列出的
  小标题**，确认这个主题不是换个说法重说同一件事。真实踩过的坑：已经写完
  《决策、冲突与升级机制》，又提出了《决策与冲突处理规范》；已经写完
  《工时、在线状态与可预期性》，又提出了《可预期工作时段与在线状态管理》
  ——两对都是同一主题换了个标题，用户拿到的是两篇内容雷同的笔记。判断
  依据是**主题是否重叠**，不是标题字面是否相同；只是换语序、换近义词、
  把大主题拆成它自己的某个小标题，都算重复，不要提
- **已完成分段里的毛病不是可以再开一节去讲的内容**。如果某个分段小结读
  起来编号错乱、结论重复、前后矛盾，那是那一篇要被修掉的缺陷，不要提出
  《统一编号与体例》《澄清前后立场》这种"专门收拾上一篇烂摊子"的新分段
  ——那样错误留在原地，用户还多拿到一篇笔记
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
