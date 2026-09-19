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
    import app.harness.tools as T

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
    """Revise / Sections / Save only make sense for long-form, but they are
    also *required* there: the four historical omissions were all a long-form
    harness missing something the other one had.

    批 15：`compact` 换成 `sections`（计划 3.1 / [CE] §7）——要求的能力没变，
    变的是拿什么去换（摘要是有损的替换，小节索引是无损的指针）。
    """
    required = {"revise", "sections", "save"}
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

    from app.harness.agent_loop import ToolTrace
    from app.harness.middleware.facts import Facts
    from app.harness.state import State
    from app.harness.tools import ToolContext

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
    from app.harness import prompts

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
    import collections

    from app.harness.agent_loop import ToolTrace
    from app.harness.checks.pick import MECHANICS
    from app.harness.state import State
    from app.harness.tools import ToolContext

    # 一段同时踩中全部九条判据的输入。before 是一份大纲、after 有收尾小节、
    # bag 里挂着一条对不上的引用、正文里带一个编造的 [事实 id]——这几样是后加的：**第一版只喂了正文**，
    # 于是 citations_hold / no_audit_voice / outline_intact / tail_clashes
    # 四条一次都没触发，下面那条「维度对不对」的断言对它们完全是空转的。
    # 一条永远返回 None 的坏判据能安然通过。所以现在既查维度，也查触发。
    BEFORE = "## 一、背景\n\n## 二、现状\n\n## 三、问题\n\n## 四、方案\n\n"
    AFTER = "## Next steps\n\n收尾在这儿。\n"
    # 这一轮写出来的：够长、一条引用都没有（citations_present 判 fresh），
    # 末尾同一组清单换个说法列了两遍（no_repeated_lists 判 content、要求 fresh 里碰过）
    # **两份素材，不是一份。** `citations_present` 要的是「这一轮写了一大段、
    # 一个编号都没有」，`no_same_sources_twice` 要的是「两段引了同一组编号」
    # ——同一段 fresh 不可能既没有编号又有两组重复的编号。硬塞在一起的结果是
    # 按下葫芦浮起瓢：加了引用，零引用那条就不响了。
    FRESH_NO_CITE = ("这一轮写满了一整段内容，但一条编号也没给。" * 20
                     + "至少要补齐测试场景、测试时间、使用的硬件版本、异常表现、负责人和最终结论。"
                     + "中间隔着别的话。"
                     + "这里需要补上测试场景、时间、硬件版本、异常表现、负责人、最终结论和接收记录。"
                     # 批 18 / 阶段 7.1 加的两个原子：一个完整日期 + 一个署名里的名字，
                     # 两样在源头（before/after/content_at_start/facts）里都没有。
                     # **加进来是被这条断言逼的**，跟批 16 那三样同一个理由。
                     + "2027 年 4 月 9 日，Speaker K 提到首年采购额已经谈定。")
    FRESH_SAME_CITES = ("付款安排本身也要保留触发条件：供应商先完成货物，再由我们验货，"
                        "验货通过后开票，付清尾款，之后才发货 [u-111-1F1] [u-111-1F2]。"
                        "\n\n商业动作还要按付款、验货、发货、使用拆开，不能把收款直接记成履约完成；"
                        "供应商完成生产后需先验货，确认无误再开票付尾款 [u-111-1F1] [u-111-1F2]。")
    # 批 16 又往里加了三样，每样对应一条新判据（阶段 5）：
    #   · 一张列数对不上的表（`table_columns_match`）
    #   · 正文里一个工具没算过的统计量（`numbers_from_tools`）
    #   · 那张 mermaid 里的数值同样无据（`chart_numbers_grounded`）
    # **加进来是被这条断言逼的**：它要求每条 check 在这段素材上至少响一次，
    # 否则一条永远返回 None 的坏判据能安然通过。
    # P24 #4 又加了一句：**一句话里同一串字抄了两遍**（`no_echoed_text`，e783 实拍的形状）。
    # **加进来是被下面那条「一次都没触发的判据不许存在」的断言逼的**，跟批 16 / 批 18 同一个理由。
    CONTENT = ("## 标题\n[柱状图：各渠道点击量]\n（此处待补充）\n"
               "现有材料不足以说明这一点 [u-999-FF]。\n"
               "三个渠道的转化率合计 47.3%，平均每天 8271 次曝光。\n"
               "项目本身包含硬件、嵌入式和 APP，并按节点推进；其中最靠后的那个还没定，"
               "项目本身包含硬件、嵌入式和 APP，并按节点推进；这一划分来自原有排期。\n"
               "```mermaid\nxychart-beta\n bar [1,2]\n```\n"
               "## Summary\n收个尾。\n")
    # **表格那一条得有两份，跟 FRESH 那一对同一个道理**：`table_present` 要的是
    # 「一张表都没有」，`table_columns_match` 要的是「有一张列数对不上的表」
    # ——同一段正文不可能两样都满足，硬塞在一起就是按下葫芦浮起瓢。
    BROKEN_TABLE = "\n| 渠道 | 点击 | 下单 |\n|---|---|---|\n| 甲 | 12700 |\n"
    FACTS = ["[2026-01] 一条没被用上的事实，里面有独特词 郑州航空港"]
    # 只开了个头的一节（阶段 7.3）：一轮的量，一条材料都没落进去。
    OPENING_ONLY = ("## 从募集支持转入兑现承诺\n\n众筹结束后，项目的主要任务"
                    "就从说服用户支持一个方向，转成按承诺把产品交到用户手里。\n")
    # 「问了，库里一条都没有」：账本里一条发过的查询 + 一个分母为 0 的轴。
    # 形状照 `middleware/ledger.fold` 真的会写出来的那一份。
    # P8 的第六份素材（理由见下面 for 循环里那条注释）。
    P8_BEFORE = ("## 验收链路\n\n验收链路可以压缩成四个连续动作，每一步都要在现场留下结果，"
                 "否则自动这两个字只在顺利录制时成立。\n\n"
                 "1. 录制结束后，原始素材自动进入处理流程，不要求教师手动上传。\n"
                 "2. 转码和摘要完成后，内容带着课程标签进入指定 Discord 共创群。\n"
                 "3. 教师能够直接在群内补充、修正和讨论。\n"
                 "4. 修订后的内容回到案例库，下一次跨校研讨可以直接调用。\n")
    P8_FRESH = ("```mermaid\ngraph LR\nA[录制结束原始素材进入处理流程] --> B[转码摘要课程标签 Discord 共创群]\n"
                "B --> C[教师群内补充修正讨论]\nC --> D[修订内容回到案例库跨校研讨调用]\n```\n\n"
                "The pilot should verify one real path end to end: the teacher starts recording, "
                "the material enters processing automatically, the summary is tagged and pushed to "
                "the Discord group, and the revised version returns to the case library for the next "
                "session to reuse without digging through chat history. મંત્રી\n\n"
                # P19 #5：中文垃圾尾巴（da080 实拍原文）。跟上面那句古吉拉特文残留是一对：
                # 一条判据认外文、一条认中文，素材里两样都得有，不然新那条永远不开火。
                "这一步的验收标准是下一位教师能直接从这份素材继续备课。 日本一本道")
    ASKED_AND_EMPTY = {
        "queries": [{"key": "filter_facts\t{\"topic\": \"work_pricing\"}",
                     "tool": "filter_facts", "hit": 0, "empty": True}],
        "axes": {"topic:work_pricing": {"total": 0, "taken": 0}},
        "facts": {},
    }

    bad = []
    bucketed: set[tuple[str, str]] = set()
    fired: collections.Counter = collections.Counter()
    seen: collections.Counter = collections.Counter()
    for mode in modes.ALL:
        for polish in (False, True) if mode.key == "note" else (False,):
            for has_profile in (False, True):
                shaped = modes.for_run(mode, has_profile=has_profile, polish=polish)
                names = {d.name for d in shaped.dims}
                st = State(mode=shaped, ctx=ToolContext(user="u", note_id="n"))
                # 批 18 / 阶段 7.2 加了第四份素材：**手上一条材料都没有，而查过了**。
                # 它必须跟前三份分开，理由跟 FRESH 那一对、表格那一对完全一样——
                # `material_thin` 要的是「facts 为空」，`citations_hold` /
                # `material_used` / `unsupported_specifics` 要的是「facts 非空」，
                # 同一份 State 不可能两样都满足。
                # 批 20 / 阶段 7.3 加了第五份：**正文还只有一轮的量，而手上
                # 一大把材料没用上**。它也必须单开一份——`section_budget` 要的是
                # 「正文短」，而前四份的正文是长的（那是 `citations_present` /
                # `no_repeated_lists` 要的），同一份 State 不可能两样都满足。
                for fresh, table, facts, ledger, short in (
                        (FRESH_NO_CITE, "", FACTS, {}, False),
                        (FRESH_SAME_CITES, "", FACTS, {}, False),
                        (FRESH_NO_CITE, BROKEN_TABLE, FACTS, {}, False),
                        (FRESH_NO_CITE, "", [], ASKED_AND_EMPTY, False),
                        (OPENING_ONLY, "", FACTS * 6, {}, True),
                        # P8 的第六份：**开跑前是一篇中文正文**（`content_at_start`），这次跑
                        # 写出来的是一段英文（`language_consistent`）+ 一个古吉拉特文乱码
                        # （`no_foreign_script`，e783 实拍「મંત્રી」）+ 一张把上面那条四步清单
                        # 逐节点重画的流程图（`chart_restates_list`，e783 P6 实拍的形状）。
                        # 三条都要「开跑前有什么」这个量程，前五份没有它，所以单开一份。
                        (P8_FRESH, "", FACTS, {}, "p8")):
                    st.fresh = fresh
                    if short == "p8":
                        st.bag["content_at_start"] = P8_BEFORE
                        st.content = P8_BEFORE + "\n\n" + fresh
                    else:
                        st.bag.pop("content_at_start", None)
                        st.content = fresh if short else CONTENT + table + "\n\n" + fresh
                    st.before, st.after = BEFORE, AFTER
                    st.facts = list(facts)
                    st.charts = []
                    st.trace = ToolTrace()
                    st.bag["ledger"] = ledger
                    st.bag["claimed_sources"] = ["[fact-nope] 不存在的来源"]
                    for check in shaped.checks:
                        seen[check.__name__] += 1
                        verdict = check(st)
                        if not verdict:
                            continue
                        fired[check.__name__] += 1
                        if verdict.dimension == MECHANICS:
                            bucketed.add((shaped.key, check.__name__))
                        elif verdict.dimension not in names:
                            bad.append(f"{shaped.key}(profile={has_profile},polish={polish})"
                                       f" 的 {check.__name__} 打了 {verdict.dimension}，"
                                       f"而它的 dims 是 {sorted(names)}")

    silent = sorted(n for n in seen if not fired[n])
    assert not silent, ("这些判据在一段踩满了所有毛病的正文上一次都没触发——"
                        "要么它坏了，要么这段素材该补：" + "、".join(silent))
    assert not bad, "check 打翻了这个 Mode 没有的维度：\n  " + "\n  ".join(bad)

    # **落进兜底桶的那几对要钉死**（计划 4.4）。桶本身是对的——这四条判据在
    # 长文模式下确实没有对应的评分轴（长文没有 `has_charts` / `chart_validity`
    # / `fits_context`，没有个人偏好时也没有 `style_fit`）——但**桶容易变成
    # 新的垃圾桶**：下一个人加一条判据、候选随手写错一个名字，它会安静地
    # 掉进来，谁也不会发现。所以这个集合逐对写死，多一对少一对都要解释。
    assert bucketed == {
        ("note", "no_audit_voice"),        # 审计腔：note 无 profile 时没有 style_fit
        # P8 起 `note` 不挂 `no_fake_charts`（不带 chart 组，见 modes.NOTE 上面那段）
        ("note", "charts_from_tools"),     # 手写 mermaid：长文没有 has_charts
        ("note", "outline_intact"),        # 大纲被压平：长文没有 fits_context
        ("note", "language_consistent"),   # 换语言（P8）：无 profile 时没有 style_fit
        ("note", "no_foreign_script"),     # 乱码字符（P8）：打 fits_context，长文没有
        ("note", "no_junk_tail"),          # 中文垃圾尾巴（P19 #5）：跟乱码字符同一维、同样落桶
        ("section", "no_audit_voice"),
        ("section", "language_consistent"),
        ("section", "no_foreign_script"),
        ("section", "no_junk_tail"),
        ("section", "no_fake_charts"),
        ("section", "charts_from_tools"),
    }, f"落进 mechanics 兜底桶的判据变了：{sorted(bucketed)}"


# ---------------------------------------------- 长循环那两组维度 ---
#
# 这几条原来在 test_harness_adapter 里，因为维度定义曾经在 adapter.py。
# 维度是 Mode 的配置，测试跟着搬过来。

def test_note_dimensions_includes_style_fit_only_with_profile():
    with_profile = modes._note_dims(has_profile=True)
    without_profile = modes._note_dims(has_profile=False)
    assert "style_fit" in {d.name for d in with_profile}
    assert "style_fit" not in {d.name for d in without_profile}


def test_beat_coverage_guidance_does_not_demand_more_elaboration():
    # TRACELOG [10]：实测 beats 早就被正文实质覆盖了，续写模型还是主观
    # 续续续，没有内在动力主动收敛——这条打分指令必须明确"覆盖了就是
    # 覆盖了"，不能被"还能写得更详细"这种理由带着继续判定"没覆盖"。
    # 之前是 BEATS_COVERAGE_SYSTEM 自己的规则，现在是 beat_coverage 这个
    # 维度的 guidance 文案。
    dims = {d.name: d for d in modes._note_dims(has_profile=False)}
    assert "写到极致" in dims["beat_coverage"].guidance


def test_section_dimensions_has_topic_fidelity_instead_of_spine_beats():
    dims = {d.name for d in modes._section_dims(has_profile=False)}
    assert "topic_fidelity" in dims
    assert "spine_fidelity" not in dims
    assert "beat_coverage" not in dims


def test_polish_mode_drops_dimensions_it_may_not_act_on():
    """打磨只修不写，就不能拿"写了多少"去打分——否则闭环不可能收敛。"""
    from app.harness.modes import _note_dims as note_dimensions

    write = {d.name for d in note_dimensions(has_profile=False)}
    polish = {d.name for d in note_dimensions(has_profile=False, polish=True)}
    assert {"beat_coverage", "material_use"} <= write
    assert not ({"beat_coverage", "material_use"} & polish), \
        "打磨模式不许写，就不该被节拍覆盖/材料使用打分（实测：判 0 → 永远到不了 complete → 撞 max_rounds）"
    assert {"spine_fidelity", "non_repetition", "factual_grounding", "coherence"} <= polish
    assert "style_fit" in {d.name for d in note_dimensions(has_profile=True, polish=True)}


def test_每条middleware声明的hook和它真的实现的一致():
    """打错一个字母，这条 middleware 就永远不会跑，而且完全无声。

    循环 `_fire` 用的是 ``getattr(m, hook)``——它**不看** ``m.hooks``。
    所以两个方向都会悄悄出错：

      · 方法名写成 ``after_prodcue``：循环永远取不到它，能力静默消失；
      · ``hooks`` 声明写错：方法照跑，但 ``middleware/_order.py`` 的先后
        依赖校验是按声明做的，于是校验在错的钩子上进行。

    没有任何东西会报错，两种情况的症状都是「这个能力好像没生效」。
    ``wrap_prepare``/``wrap_produce`` 同样按 hasattr 找，一并纳入。
    """
    import pathlib
    import re

    from app.harness.middleware import BASE

    loop_src = (pathlib.Path(__file__).resolve().parents[1]
                / "app" / "harness" / "loop.py").read_text(encoding="utf-8")
    fired = set(re.findall(r'_fire\(chain, "([a-z_]+)"', loop_src))
    fired |= set(re.findall(r'hasattr\(x, "(wrap_[a-z_]+)"\)', loop_src))
    assert len(fired) >= 9, f"没从 loop.py 里认出钩子名，只找到 {sorted(fired)}"

    instances = {}
    for m in list(BASE) + [x for mo in modes.ALL for x in mo.extra_mw]:
        instances[type(m).__name__] = m

    bad = []
    for cls, m in sorted(instances.items()):
        declared = set(getattr(m, "hooks", ()))
        implemented = {n for n in dir(m)
                       if n.startswith(("before_", "after_", "wrap_"))
                       and callable(getattr(m, n))}
        if declared - fired:
            bad.append(f"{cls} 声明了循环不会触发的钩子：{sorted(declared - fired)}")
        if declared != implemented:
            bad.append(f"{cls} 声明 {sorted(declared)} ≠ 实现 {sorted(implemented)}")
    assert not bad, "\n  ".join([""] + bad)
