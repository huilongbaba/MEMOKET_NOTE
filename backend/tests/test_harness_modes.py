"""Rules about the Mode table itself, checked mechanically.

Every assertion here corresponds to an omission that actually shipped. The
point is that "did anyone remember to wire that in" stops being a question a
human has to ask.
"""

from __future__ import annotations

from app.harness import modes
from app.harness.middleware import BASE, describe, verify


def test_every_mode_declares_a_skill_scope():
    """An empty scope means every user skill silently stops applying to that
    feature -- no error, nothing in the logs, it just quietly does less.
    That is exactly the state all six block modes are in today."""
    missing = [m.key for m in modes.ALL if not m.skill_scope]
    assert not missing, f"no skill_scope on: {missing}"


def test_no_mode_switches_off_a_standard_capability():
    """Switching one off is allowed and sometimes right. It is not allowed to
    happen by accident, which is how all four previous omissions happened."""
    off = {m.key: m.rails_off for m in modes.ALL if m.rails_off}
    assert not off, f"{off} -- argue for it in the pull request, don't just set it"


def test_every_mode_has_at_least_one_dimension_or_check():
    """A mode with no judgement at all always 'completes' on round one, which
    looks like it's working."""
    empty = [m.key for m in modes.ALL if not m.dims and not m.checks]
    # note / section fill dims from harness_adapter at wiring time; they carry
    # checks in the meantime, so this catches a mode with genuinely nothing.
    assert not empty, f"no judgement configured for: {empty}"


def test_dimension_names_are_unique_within_a_mode():
    """Two dimensions sharing a name means one silently overwrites the other
    in the scores dict."""
    for m in modes.ALL:
        names = [d.name for d in m.dims]
        assert len(names) == len(set(names)), f"{m.key} has duplicate dimensions"


def test_middleware_order_holds_for_every_mode():
    for m in modes.ALL:
        verify(tuple(BASE) + tuple(m.extra_mw))


def test_tool_groups_exist():
    import app.tools as T

    known = {t.group for t in T.registry._REGISTRY.values()}
    for m in modes.ALL:
        unknown = set(m.groups) - known
        assert not unknown, f"{m.key} authorises non-existent group(s): {unknown}"


def test_excluded_tools_are_not_a_workaround_for_bad_grouping():
    """If the same tool keeps being excluded, it is in the wrong group.
    Fix the group; ``exclude`` is for genuine one-offs."""
    from collections import Counter

    counts = Counter(tool for m in modes.ALL for tool in m.exclude)
    repeated = [t for t, n in counts.items() if n >= 2]
    assert not repeated, (f"{repeated} excluded by several modes -- move it to "
                          f"its own group instead")


def test_long_form_modes_carry_the_long_form_capabilities():
    """Revise / Compact / Save only make sense for long-form, but they are
    also *required* there: the four historical omissions were all a long-form
    harness missing something the other one had."""
    required = {"revise", "compact", "save"}
    for key in ("note", "section"):
        mode = next(m for m in modes.ALL if m.key == key)
        attached = {name for name, _hooks in describe(mode.extra_mw)}
        assert required <= attached, f"{key} is missing {required - attached}"


def test_block_modes_do_not_persist_each_round():
    """A block is handed to the editor, not written to the note. Attaching
    Save there would write partial blocks into the user's document."""
    for m in modes.BLOCK.values():
        attached = {name for name, _hooks in describe(m.extra_mw)}
        assert "save" not in attached, f"{m.key} must not persist rounds"


# --------------------------------------------------------------- for_run ---


def test_a_run_without_a_style_profile_is_not_scored_on_style():
    """style_fit compares against a profile. With no profile there is nothing
    to be faithful to, and a dimension that can never be satisfied keeps the
    loop running until it hits max_rounds."""
    names = [d.name for d in modes.for_run(modes.NOTE).dims]
    assert "style_fit" not in names
    assert "style_fit" in [d.name for d in modes.for_run(
        modes.NOTE, has_profile=True).dims]


def test_polish_is_not_scored_on_how_much_got_written():
    """Polish may only edit. Scoring it on beat coverage or material use asks
    it to improve by writing, which is exactly what it is forbidden to do."""
    names = [d.name for d in modes.for_run(modes.NOTE, polish=True).dims]
    assert "beat_coverage" not in names
    assert "material_use" not in names
    assert "spine_fidelity" in names       # what polish *can* move still counts


def test_modes_with_fixed_dimensions_pass_through_unchanged():
    for mode in modes.ALL:
        if mode.key not in ("note", "section"):
            assert modes.for_run(mode, has_profile=True) is mode


def test_every_mode_ends_up_with_at_least_one_dimension():
    """An empty dimension list scores as 'nothing failed', so a mode that
    forgets its dims silently completes on round one."""
    for mode in modes.ALL:
        shaped = modes.for_run(mode, has_profile=True)
        assert shaped.dims, f"{mode.key} has no dimensions to be judged on"


def test_a_repair_round_does_not_count_as_running_dry():
    """清理轮不检索，所以它"没查到新材料"说明不了材料的任何事。

    实测：一篇笔记第 1 轮查回 22 条事实，第 2、3 轮因为 coherence 弱转成
    清理轮，于是连续两轮 facts=0，材料耗尽的判据当场触发，跑到第 3 轮就
    以 material_used_up 停了——而知识库里的材料一点都没少。
    """
    import asyncio

    from app.agent_loop import ToolTrace
    from app.harness.middleware.facts import Facts
    from app.harness.state import State
    from app.tools import ToolContext

    st = State(mode=modes.NOTE, ctx=ToolContext(user="u", note_id="n"))
    st.trace, st.facts_new = ToolTrace(), ["查到的一条"]
    asyncio.run(Facts().after_prepare(st))
    assert st.bag["dry_rounds"] == 0

    st.bag["cleanup_only"] = True
    st.facts_new = []
    for _ in range(3):
        asyncio.run(Facts().after_prepare(st))
    assert st.bag["dry_rounds"] == 0, "清理轮不该被算成材料枯竭"
    assert st.facts == ["查到的一条"], "清理轮也不该把已有材料弄丢"

    # 真的查空了才算
    st.bag["cleanup_only"] = False
    for _ in range(2):
        asyncio.run(Facts().after_prepare(st))
    assert st.bag["dry_rounds"] == 2


def test_每个mode都填了skill_scope():
    """漏填 = 那个功能上用户配的技能全部静默失效。

    `compose_block` 的六个模式此前就是这么漏的：一个 scope 都没有，用户
    在数据可视化那条路径上配的技能一条都不生效，也不报错。
    """
    from app import prompts

    for mode in modes.ALL:
        assert mode.skill_scope, f"{mode.label} 没填 skill_scope"
        assert mode.skill_scope in prompts.SKILL_SCOPES, (
            f"{mode.key} 的 skill_scope={mode.skill_scope!r} 不在 SKILL_SCOPES 里，"
            "用户在面板上根本选不到这个范围")


def test_每个mode都能拿到skill工具():
    """能看见有哪些技能却调不了 load_skill，这个机制就只剩半截。"""
    for mode in modes.ALL:
        assert "skill" in mode.groups, f"{mode.key} 没开 skill 工具组"


def test_每条check打翻的维度这个mode真的有():
    """**这是被问出来的一个真 bug。**

    一条 check 被多个 Mode 共用，而它以前把维度名写死：``no_fake_charts``
    写死打 ``has_charts``，在数据可视化模式下对，在智能插图模式下打的是一个
    **那个模式根本没有的维度**（它那一维叫 ``chart_validity``）。24 个
    「check × mode」组合里 8 个是这样。

    后果不大但很别扭：Evaluation 里冒出一个模型从来不会打的维度名，喂回
    下一轮的诊断也顶着一个模型没见过的标签。

    修法不是统一命名——``has_charts``（图有没有信息量）和 ``chart_validity``
    （图是不是工具产出的）是**不同的轴**。修法是让 check 在候选里挑这个
    Mode 认识的那个（``checks.pick_dimension``）。这条断言保证挑得到。
    """
    import asyncio
    import types as _t

    from app.agent_loop import ToolTrace
    from app.harness.state import State
    from app.tools import ToolContext

    bad = []
    for mode in modes.ALL:
        for polish in (False, True) if mode.key == "note" else (False,):
            for has_profile in (False, True):
                shaped = modes.for_run(mode, has_profile=has_profile, polish=polish)
                names = {d.name for d in shaped.dims}
                st = State(mode=shaped, ctx=ToolContext(user="u", note_id="n"))
                # 让每条 check 都命中：喂一段同时踩中所有判据的正文
                st.content = ("## 标题\n[柱状图：各渠道点击量]\n（此处待补充）\n"
                              "现有材料不足以证明这一点。\n[fact-nope] 引用了不存在的事实\n"
                              "```mermaid\nxychart-beta\n bar [1,2]\n```\n")
                st.before = "### 上文的标题\n"
                st.facts = ["[2026-01] 一条没被用上的事实，里面有独特词 郑州航空港"]
                st.charts = []
                st.trace = ToolTrace()
                for check in shaped.checks:
                    verdict = check(st)
                    if verdict and verdict.dimension not in names:
                        bad.append(f"{shaped.key}(profile={has_profile},polish={polish})"
                                   f" 的 {check.__name__} 打了 {verdict.dimension}，"
                                   f"而它的 dims 是 {sorted(names)}")
    assert not bad, "check 打翻了这个 Mode 没有的维度：\n  " + "\n  ".join(bad)
    _ = asyncio, _t
