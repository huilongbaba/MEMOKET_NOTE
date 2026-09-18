"""Skill tools: how the model reaches level 2 and 3 of progressive disclosure.

The system prompt carries every skill's name and description (~100 tokens
each). When the model judges one relevant it calls ``load_skill``; if that
body points at a bundled file it calls ``read_skill_ref``. Nothing else is in
context until it asks.

Putting these behind tools rather than a bespoke code path is deliberate:
they then inherit authorisation (``group="skill"``), provenance (results land
in ToolTrace, so TapProvenance can show what was consulted), per-round call
caps, and error isolation -- all of it for free.
"""

from __future__ import annotations

from .. import skills
from .registry import ToolContext, register


@register(
    name="load_skill",
    group="skill",
    description="Load a skill's full instructions. The system prompt lists "
                "which skills exist and when each applies; call this when one "
                "of them fits what you're doing now.",
    params={"name": {"type": "string", "description": "the skill's name, as listed"}},
    required=["name"],
    max_calls_per_round=3,
)
def load_skill(ctx: ToolContext, name: str) -> str:
    """Pull one skill's body into context, and keep it for later rounds.

    Kept across rounds because a run can go eight rounds; re-loading the same
    skill each time would be eight wasted calls for one piece of unchanging
    text.
    """
    # The harness puts its own ``skill_bodies`` list in here, so appending
    # writes through to the run's state; a caller that doesn't provide one
    # simply gets no accumulation, and the tool still works.
    loaded = ctx.scratch.get("skill_bodies")
    # **额度数的是「模型自己加载了几条」，不是「上下文里一共有几条」**（批 22）。
    # 原来数的是 `len(skill_bodies)`，而那个 list 在 `middleware/skills` 的
    # 第一轮就已经被 **scope 注入**的正文填过了——实测 13 条内置技能里
    # `verify` / `edit` / `plan_generate` 三个 scope 各注入 2 条，于是模型
    # 一条都没加载就只剩 1 次额度；哪天某个 scope 配到 3 条，`load_skill`
    # 会**永久返回拒绝**。而拒绝的原话是「Already loaded 3 skills」——
    # **告诉模型它做过一件它没做过的事**，那是最坏的一种反馈。
    # （`tests/test_skill_loop.py` 原来那条上限用例的 fixture 一条 scope 都
    # 没配，正好绕开了这个交互，所以一直是绿的。）
    # 这一份不进快照（`ctx.scratch` 本来就不进），于是恢复之后额度重新给满
    # ——那是「宽一点」的那一侧，比今天「一次都没用就用光」安全。
    by_model = ctx.scratch.setdefault("loaded_by_model", [])

    if len(by_model) >= skills.MAX_LOADED_SKILLS:
        # A ceiling, because the model will otherwise load five and fill the
        # window. Same principle as the chart tools refusing uninformative
        # charts: a tool that says no beats an instruction to show restraint.
        return (f"(Already loaded {skills.MAX_LOADED_SKILLS} skills, which is "
                f"enough for one piece of work. If a different one is needed, "
                f"say which and why.)")

    body = skills.read_body(ctx.user, name.strip())
    if body is None:
        available = ", ".join(s.name for s in skills.load_all(ctx.user) if s.enabled)
        return f"(No skill named {name!r}. Available: {available or 'none'})"

    if name.strip() not in by_model:
        by_model.append(name.strip())
    if loaded is not None and body not in loaded:
        loaded.append(body)
    return body


@register(
    name="read_skill_ref",
    group="skill",
    description="Read a reference file bundled with a skill (a template, a "
                "worked example, a checklist). Only call this when a skill's "
                "instructions point at a specific file.",
    params={
        "skill": {"type": "string", "description": "which skill the file belongs to"},
        "path": {"type": "string", "description": "the file name as written in the "
                                                  "skill's instructions"},
    },
    required=["skill", "path"],
    max_calls_per_round=3,
)
def read_skill_ref(ctx: ToolContext, skill: str, path: str) -> str:
    """Read one bundled file. Level 3 -- costs nothing until asked for.

    ``skills.read_reference`` rejects traversal and non-text files. That
    matters here because the argument comes from the model, which took it
    from a skill body -- untrusted text that may well have been written by
    someone else.
    """
    text = skills.read_reference(ctx.user, skill.strip(), path.strip())
    if text is None:
        return (f"(Can't read {path!r} from skill {skill!r}. It must be a text "
                f"file inside that skill's own directory.)")
    return text
