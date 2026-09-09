"""Skill 系统的提示词：把启用的 skill 拼进 system prompt，以及让模型
自己写一个 skill 出来。

``compose_system`` 是全仓用得最多的一个——每条 harness 的每次生成都要
它把「基础人格 + 用户启用的 skill」拼起来。
"""

from __future__ import annotations


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
    # `/` 唤起的块生成。这两个是新加的——六个块模式此前一个 scope 都没有，
    # 于是用户在那条路径上配的技能一条都不生效，而且不报错。
    "block_write": "`/` 生成图表 · 表格 · 数据分析",
    "block_prompt": "`/` 按提示词写 · 右键自定义提示",
}


def compose_system(base: str, scope: str, user: str = "",
                   menu: list[tuple[str, str]] | None = None,
                   bodies: list[str] | None = None) -> str:
    """Base prompt + the skills in play + the menu of the rest.

    Two channels, and the difference is who decided:

    * **scope match** -- the user configured "this skill applies when doing
      X". The body goes straight in; there is nothing for the model to judge.
    * **the menu** -- name and description only, about 100 tokens each. The
      model calls ``load_skill`` if one fits. This is what progressive
      disclosure means: read the table of contents, pick the chapter.

    ``bodies`` and ``menu`` come from the run's state when there is one. That
    matters for ``bodies`` specifically: it holds the scope matches **plus
    whatever the model loaded itself**, and recomputing from ``for_scope``
    here would drop the loaded ones on the floor -- the model would call
    ``load_skill``, watch the body never arrive, and call it again.
    """
    from .. import skills as skills_store

    if bodies is None or menu is None:
        injected, listed = skills_store.for_scope(user, scope)
        bodies = [s.body for s in injected] if bodies is None else bodies
        menu = [(s.name, s.description) for s in listed] if menu is None else menu

    parts = [base]
    if bodies:
        parts.append("以下是额外启用的写作技能，在不违反上面规则的前提下按顺序叠加生效：")
        parts.extend(bodies)
    block = skills_store.menu_block(menu)
    if block:
        parts.append(block)
    return "\n\n".join(parts)


def skill_generate_system() -> str:
    """Read the style examples off disk rather than from a constant.

    The built-in skills used to be a list of dicts here, and were seeded into
    a database table. They are ordinary ``SKILL.md`` directories now -- the
    same shape a user writes and a third party ships -- so there is one
    definition of what a skill is, and this function reads three of them as
    examples instead of holding its own copy.
    """
    from .. import skills as skills_store

    scope_lines = "\n".join(f"- {k}：{v}" for k, v in SKILL_SCOPES.items())
    examples = []
    root = skills_store.BUILTIN_ROOT
    for directory in sorted(root.iterdir())[:3] if root.is_dir() else []:
        md = directory / "SKILL.md"
        if not md.is_file():
            continue
        try:
            _name, _desc, body = skills_store.parse_skill_md(
                md.read_text(encoding="utf-8"))
        except skills_store.SkillFormatError:
            continue
        examples.append(f"例：{body}")
    return f"""你是写作技能生成助手。用户会用一两句话描述想要的写作行为，
你要把它写成一条具体、可执行的写作指令。

可选的生效范围（scope）：
{scope_lines}

要求：
- name：8-16 字左右的技能名称（可以是中文，会作为技能说明的一级标题）
- description：一句话说明这条技能**做什么**、以及**什么时候用**——
  这是模型判断要不要触发它的唯一依据
- scopes：从上面的可选范围里选 1-3 个最贴合用户描述意图的，不要瞎猜太多、
  跟意图明显无关的范围不要选
- content：具体的指令内容，风格参考下面的例子——描述具体的"不要做什么/
  要做什么"，给出可以直接照做的判断标准，不要写"让内容更好""提升质量"
  这种空话
- 只输出 JSON，形如 {{"name":"...","description":"...","scopes":["..."],"content":"..."}}，
  不要任何解释文字

参考风格例子：
{chr(10).join(examples)}
"""


def skill_generate_user(goal: str, scope_hint: str = "") -> str:
    parts = [f"【用户想要的写作行为】\n{goal}"]
    if scope_hint:
        parts.append(f"【用户指定的生效范围提示】\n{scope_hint}")
    parts.append("请生成这条技能。")
    return "\n\n".join(parts)
