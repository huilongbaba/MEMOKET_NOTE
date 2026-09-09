"""单篇笔记 harness：note_harness._apply_revision() 的锚点应用语义（跟
前端 RevisionPanel.tsx 的 applyRevision() 是同一套语义，Python 版本），
以及 prompts.note_harness_continue_user()/edit_user() 的拼装。

"完不完整"的判断已经迁到 scoring.evaluate()（见
tests/test_scoring_test_rubric.py），这里不再重复测；_beats_status()
和 NOTE_HARNESS_DONE_MARKER 已经随之删除。

    cd backend && python -m pytest tests/test_note_harness.py -v
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import prompts  # noqa: E402
# 修订的定位与应用搬到了 app/harness/revision.py —— 两条 harness 共用，
# 而 router 之间不该互相 import。
from app.harness.revision import _apply_revision  # noqa: E402


def test_apply_revision_replace():
    result = _apply_revision("正文里有一段旧内容在这里。", "replace", "旧内容", "新内容")
    assert result == "正文里有一段新内容在这里。"


def test_apply_revision_insert_after_anchor():
    result = _apply_revision("开头。结尾。", "insert", "开头。", "中间。")
    assert result == "开头。中间。结尾。"


def test_apply_revision_insert_before_anchor():
    result = _apply_revision("开头。结尾。", "insert_before", "结尾。", "中间。")
    assert result == "开头。中间。结尾。"


def test_apply_revision_delete():
    result = _apply_revision("保留这段，删掉这段，保留这段。", "delete", "，删掉这段", "")
    assert result == "保留这段，保留这段。"


def test_apply_revision_missing_anchor_returns_unchanged():
    result = _apply_revision("正文内容", "replace", "找不到的锚点", "新内容")
    assert result == "正文内容"


def test_consecutive_inserts_on_same_anchor_keep_model_order():
    # 真实质量采样抓到的 bug：模型按正确顺序给了两条 insert（先「### 3.」
    # 后「### 4.」）、锚点完全相同，但 insert 语义是「紧贴锚点末尾插入」，
    # 第二条又插回锚点正后方，把第一条顶到后面，正文里编号 4 就排到了 3
    # 前面。批量自动应用时必须用 insert_offset 累计已插入长度。
    content = "锚点句。"
    first = "\n\n### 3. 第三节"
    second = "\n\n### 4. 第四节"

    # 旧行为（不传 insert_offset）会颠倒顺序——这里明确固定住"为什么需要
    # 这个参数"，不是抽象地测新参数能用
    naive = _apply_revision(content, "insert", "锚点句。", first)
    naive = _apply_revision(naive, "insert", "锚点句。", second)
    assert naive.index("第四节") < naive.index("第三节")

    stepped = _apply_revision(content, "insert", "锚点句。", first, insert_offset=0)
    stepped = _apply_revision(stepped, "insert", "锚点句。", second, insert_offset=len(first))
    assert stepped.index("第三节") < stepped.index("第四节")


def test_apply_revision_insert_offset_defaults_to_old_behavior():
    # 前端逐条接受走的是单条应用，不传 offset，行为必须跟以前一模一样
    assert _apply_revision("开头。结尾。", "insert", "开头。", "中间。") == "开头。中间。结尾。"


def test_apply_revision_only_touches_first_occurrence():
    # find() 找第一处，跟前端 indexOf() 语义一致——重复出现的锚点里，
    # 修订只作用在第一个匹配上，不是全局替换
    result = _apply_revision("重复 重复 重复", "replace", "重复", "改了")
    assert result == "改了 重复 重复"


def test_note_harness_continue_user_includes_beats_and_facts():
    text = prompts.note_harness_continue_user(
        spine="核心张力", beats=["节拍一"], content="正文", facts=["事实一"], profile=[],
    )
    assert "核心张力" in text
    assert "节拍一" in text
    assert "事实一" in text


def test_edit_user_includes_focus_when_given():
    text = prompts.edit_user(
        spine="", beats=[], content="正文", facts=[], profile=[], focus="non_repetition",
    )
    assert "这一轮优先检查" in text


def test_edit_user_omits_focus_block_when_not_given():
    text = prompts.edit_user(
        spine="", beats=[], content="正文", facts=[], profile=[],
    )
    assert "这一轮优先检查" not in text


def test_tidy_blank_lines_collapses_runs_left_by_delete():
    """delete 一条修订会把前后两组段落分隔符并在一起，留下多余空行。"""
    from app.harness.revision import _tidy_blank_lines

    # 「## A\n\n正文\n\n## B」删掉中间正文后的形态
    assert _tidy_blank_lines("## A\n\n\n\n## B") == "## A\n\n## B"
    assert _tidy_blank_lines("a\n\nb") == "a\n\nb"          # 正常段落间距不动
    assert _tidy_blank_lines("a\nb") == "a\nb"                # 单换行不动


def test_tidy_blank_lines_keeps_code_block_content_intact():
    """代码块里的空行是内容不是格式，不能压。"""
    from app.harness.revision import _tidy_blank_lines

    src = "```\nx\n\n\n\ny\n```"
    assert _tidy_blank_lines(src) == src


def test_every_harness_supplies_the_three_callbacks_the_loop_calls():
    """The loop calls prepare / produce / commit by name on whatever it is
    given. Nothing type-checks that at import time, and a missing one only
    surfaces inside an SSE generator -- where it reads to the user as the
    connection dying.
    """
    import inspect

    from app.harness.hooks.block import BlockHooks
    from app.harness.hooks.note import NoteHooks
    from app.harness.hooks.section import SectionHooks

    for cls in (BlockHooks, NoteHooks, SectionHooks):
        for name in ("prepare", "produce", "commit"):
            fn = getattr(cls, name, None)
            assert fn is not None, f"{cls.__name__} 缺 {name}"
            assert list(inspect.signature(fn).parameters) == ["self", "st"], \
                f"{cls.__name__}.{name} 的签名跟 loop 的调用对不上"
        assert inspect.isasyncgenfunction(cls.produce), \
            f"{cls.__name__}.produce 必须是 async generator，loop 是 async for 消费的"


def test_anchor_end_locates_a_span_without_echoing_it():
    """anchor + anchor_end 用两个短标记定位一整段，模型不用把原文抄一遍。

    原来的契约要求 anchor 是"要被替换的完整原文"——一段两百字的段落就得
    原样回显两百字，replace 时改后的 text 再输出一遍，同一段内容进出各一次。
    输出 token 直接换算成时间，是纯浪费。
    """
    from app.harness.revision import _apply_revision

    c = "## 标题\n\n开头这几个字，中间很长的一大段内容省略掉，结尾这几个字。\n\n下一段。"
    assert _apply_revision(c, "replace", "开头这几个字", "换成这个",
                           anchor_end="结尾这几个字。") == "## 标题\n\n换成这个\n\n下一段。"
    assert _apply_revision(c, "delete", "开头这几个字", "",
                           anchor_end="结尾这几个字。") == "## 标题\n\n\n\n下一段。"


def test_missing_anchor_end_falls_back_to_anchor_only():
    """结尾标记定位不到时宁可少改一点，也不要按错误的范围改。"""
    from app.harness.revision import _apply_revision

    c = "第一段。第二段。"
    assert _apply_revision(c, "delete", "第一段。", "", anchor_end="不存在") == "第二段。"
    # 不给 anchor_end 时行为跟以前完全一致
    assert _apply_revision(c, "delete", "第一段。", "") == "第二段。"


def test_sources_markers_expand_to_full_facts():
    """模型只回显方括号标记，后端还原成完整事实——显示不减，输出 token 大减。"""
    from app.harness.revision import _expand_sources

    facts = ["[2026-04-10] 硬件4月10号出来。", "[terrence-2046-2F3] Speaker E 问3月31号。"]
    assert _expand_sources(["2026-04-10"], facts) == ["[2026-04-10] 硬件4月10号出来。"]
    assert _expand_sources(["[terrence-2046-2F3]"], facts)[0].startswith("[terrence-2046-2F3]")
    assert _expand_sources(["认不出来的"], facts) == ["认不出来的"]   # 不丢来源


def test_judging_uses_run_level_facts_not_this_round():
    """"拿整篇正文去比对材料"的判断，材料一侧必须是整次 run 累积的。

    真实 bug：本轮材料每轮重置，正文却是累积的。第 3 轮的打分拿第 3 轮检索
    到的材料审判包含第 1 轮内容的整篇，于是把第 1 轮明明有依据的日期判成
    「知识库中查无此事」。这个 bug 在三条 harness 里各写了一遍、修了两遍。

    现在只有一处能犯这个错：``Facts`` 是唯一往 ``st.facts`` 写的东西，而
    打分、material_use 兜底、材料耗尽三处判断都读它。
    """
    from app.harness.middleware.facts import Facts
    from app.harness.state import State
    from app.harness.modes import NOTE
    from app.agent_loop import ToolTrace
    from app.tools import ToolContext

    st = State(mode=NOTE, ctx=ToolContext(user="u", note_id="n"))
    st.trace = ToolTrace()
    for round_facts in (["第一轮的事实"], ["第二轮的事实"]):
        st.facts_new = round_facts
        asyncio.run(Facts().after_prepare(st))
    assert st.facts == ["第一轮的事实", "第二轮的事实"], "材料必须跨轮累积"

    src = (Path(__file__).resolve().parent.parent / "app" / "harness").rglob("*.py")
    writers = sorted(f.name for f in src
                     if "st.facts = " in f.read_text(encoding="utf-8"))
    # snapshot.py 也写，但那是「把上次累积的结果放回去」，不是累积规则
    assert writers == ["facts.py", "snapshot.py"], f"st.facts 的写入方变了：{writers}"


def test_same_meaning_rewrite_is_rejected():
    """只换措辞的 replace 必须被拦下。样本取自真实产出：同一段被 replace 三次。"""
    from app.harness.revision import _is_same_meaning_rewrite as same

    v1 = ("因此，`ask memory` 进入本版。它被视为 2026 年 3 月 15 日版本的显著差异点和核心价值，"
          "即使 integration 还不能完全实现，也不能因此把 ask memory 一起往后推。")
    v2 = ("因此，`ask memory` 进入本版。它被视为 2026 年 3 月 15 日版本的显著差异点和核心价值，"
          "主要围绕用户自己的录音和记忆内容回答问题，即使 integration 还不能完全实现。")
    assert same(v1, v2)

    # 真改出了东西的不能误伤
    assert not same(v1, "整版推迟到 4 月，先把硬件良率的问题解决掉，功能范围下个月再定。")
    # 短锚点（标题、编号）本来就该允许小改
    assert not same("### 3. 甲", "### 2. 甲")
    assert not same("", "任意内容")


def test_edited_spans_block_second_rewrite_of_same_place():
    """同一处只允许改一次——第二次一律拦掉，否则轮次全耗在原地打磨措辞。

    集合必须是**整次 run 级**的，不是一遍修订内的：两轮各改一次同一段，
    每轮各自看都合法，合起来就是编辑 pass 在跟自己打架。
    """
    revise = (Path(__file__).resolve().parent.parent
              / "app" / "harness" / "middleware" / "revise.py").read_text(encoding="utf-8")
    assert 'st.bag.setdefault("edited_spans", set())' in revise, \
        "跨轮集合要放在 bag 里，放局部变量就只在一轮内有效"
    assert "edited)" in revise, "集合要传进 reject_revision"

    rev = (Path(__file__).resolve().parent.parent
           / "app" / "harness" / "revision.py").read_text(encoding="utf-8")
    assert 'if op == "replace" and edited is not None and key in edited:' in rev, \
        "应用阶段要硬拦，不能只在提示词里说"


def test_breakage_catches_half_replaced_sentence():
    """修订切错位置留下的残骸要能查出来。样本是真实产出里抓到的破字。"""
    from app.harness.revision import _breakage as brk

    ok = "不要把未计算的节点写成已确定日期。应把需求收口、设计稿确认逐项列入倒排表。"
    bad = "不要把未计算的节点写成已确定日期：、设计稿确认、页面开发逐项列入倒排表。"
    assert brk(ok, bad)                       # 「日期：」后直接跟顿号
    assert brk("好好的一段。", "、设计稿确认、页面开发。")   # 整段以顿号起头
    assert not brk(ok, ok)                    # 没变化
    assert not brk(ok, "换了一句完全正常的话。")
    # 只报**新增**的破损：原文本来就有的不能让一条无关修订背锅
    assert not brk(bad, bad + "\n\n新加一段正常的话。")


def test_ambiguous_anchor_is_skipped():
    """锚点在正文里有多处时不能瞎改——短锚点契约下这会切坏正文。"""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "harness" / "revision.py").read_text(encoding="utf-8")
    assert 'op == "replace" and not anchor_end and content.count(anchor) > 1' in src
    revise = (Path(__file__).resolve().parent.parent
              / "app" / "harness" / "middleware" / "revise.py").read_text(encoding="utf-8")
    assert "broke = _breakage(st.content, updated)" in revise


def test_both_harnesses_share_the_same_revision_guards():
    """两条长循环 harness 必须跑同一份修订实现。

    这条测试以前比对两个 router 的源码字符串，因为那时确实是两份拷贝，而
    「只修了一边」发生过六次。现在只有一份——所以要钉的变成了「两条都挂上
    了它」。
    """
    from app.harness import modes

    for mode in (modes.NOTE, modes.SECTION):
        names = [type(m).__name__ for m in mode.extra_mw]
        assert "Revise" in names, f"{mode.key} 没挂修订"
        assert "Save" in names, f"{mode.key} 没挂逐轮落盘"


def test_reject_revision_reasons():
    from app.harness.revision import reject_revision as rej

    body = ("因此，`ask memory` 进入本版。它被视为 2026 年 3 月 15 日版本的显著差异点和核心价值，"
            "即使 integration 还不能完全实现，也不能因此把它一起往后推。")
    doc = "开头。\n\n" + body + "\n\n结尾。"
    same = body.replace("即使 integration 还不能完全实现，也不能因此把它一起往后推。",
                        "主要围绕用户自己的录音回答问题，即使 integration 还不能完全实现。")
    assert "换了措辞" in rej(doc, "replace", body, same)
    assert rej(doc, "replace", body, same, edited={" ".join(body.split())[:40]})
    assert "多处" in rej("甲说了话。\n\n甲说了话。", "replace", "甲说了话。", "乙说了别的话。")
    assert rej(doc, "replace", body, "整版推迟到四月，先解决硬件良率，功能范围下月再定。") == ""
    assert rej(doc, "insert", body, "补一段新内容。") == ""


def test_dedup_delete_survives_the_ambiguity_guard():
    """删重复标题必须放行——去重恰恰要求锚点出现多次。

    真实回归（我自己引入的）：歧义锚点防线一律拦掉多处锚点，结果
    ``## 众筹节奏`` 出现两次的那篇跑满三轮也没删掉重复的那个，
    non_repetition 掉到 0。
    """
    from app.harness.revision import reject_revision as rej

    doc = "## 众筹节奏\n\n三月上旬启动。\n\n## 众筹节奏\n\n三月上旬启动众筹。\n"
    assert rej(doc, "delete", "## 众筹节奏", "") == ""          # 去重，放行
    assert rej(doc, "replace", "## 众筹节奏", "## 别的标题")      # 改哪个说不准，拦
    # 「删掉重复的那一节」= 重复的锚 + 结尾标记，是去重的**标准形态**，必须放行。
    # 第一版把它拦了，20 轮实测 non_repetition 全 20 次 0 分、coherence 掉到 0.5。
    assert rej(doc, "delete", "## 众筹节奏", "", anchor_end="启动众筹。") == ""


def test_the_edit_pass_carries_the_guards_on_every_path():
    """修订的结构硬防线和跨轮去重不能只在某一条分支上生效。

    真实缺陷：「只清理不续写」那条分支两个都没传，三层大纲的标题层级在
    20 轮 soak 里 **20/20 全被压平**——清理这一步正是「空壳标题要删掉」
    规则火力最猛的地方，而它在裸奔。现在没有第二条分支可漏：修订是一个
    middleware，续写与否是它之后的事。
    """
    revise = (Path(__file__).resolve().parent.parent
              / "app" / "harness" / "middleware" / "revise.py").read_text(encoding="utf-8")
    assert 'outline_mode = bool(st.bag.get("outline_mode"))' in revise
    assert "outline.structure_intact(st.content, updated)" in revise, "缺结构硬防线"
    assert 'st.bag.setdefault("edited_spans", set())' in revise, "缺跨轮去重"

    from app.harness.middleware.revise import Revise
    assert Revise.hooks == ("before_produce",), \
        "修订必须在续写之前跑：先修已经写坏的，再往上加"


def test_outline_target_is_decided_before_retrieval():
    """大纲模式下必须先定"这轮写哪一节"再去检索，否则每轮拿回同一批事实。

    20 轮 soak 的数据：non_repetition 是全局最弱的一维（0.9~1.7），大纲组
    50 次撞 max_rounds 而 beat_coverage 已经 1.9~2.0——卡住的正是重复。
    根因是顺序反了，模型手握众筹的材料被要求写「团队」那一节。
    """
    src = (Path(__file__).resolve().parent.parent
           / "app" / "harness" / "hooks" / "note.py").read_text(encoding="utf-8")
    decide = src.index("target = outline.next_gap(st.content)")
    assert src.count("outline.next_gap(") == 1, "只该算一次"
    assert decide < src.index("agent_loop.gather_context("), "定小节必须在检索之前"
    assert decide < src.index("if not AGENT_TOOLS:"), \
        "要在两条分支之上，否则关工具那条会用陈旧值"
    assert 'section=target[0] if target else ""' in src, "小节名要传进检索规划"


def test_locate_picks_the_smallest_span_when_anchor_repeats():
    """锚点重复时取跨度最小的那一组——这是"删掉重复的那一节"的正确语义。"""
    from app.harness.revision import _apply_revision, _locate

    doc = ("## 众筹节奏\n\n三月上旬启动。\n\n"
           "## 众筹节奏\n\n三月上旬启动众筹。\n\n综上所述，要盯紧。\n")
    i, j = _locate(doc, "## 众筹节奏", "三月上旬启动众筹。")
    assert doc[i:j] == "## 众筹节奏\n\n三月上旬启动众筹。", "从第一处往后找会把两节整个删掉"

    out = _apply_revision(doc, "delete", "## 众筹节奏", "", anchor_end="三月上旬启动众筹。")
    assert out.count("## 众筹节奏") == 1, "重复的那一节应该被删掉"
    assert "三月上旬启动。" in out, "留下的应该是第一节"

    # 没有 anchor_end 时行为不变：定位到第一处的锚点本身
    assert _locate(doc, "## 众筹节奏", "") == (0, len("## 众筹节奏"))
    # 结尾标记找不到时退回只用 anchor，不能按错误范围乱切
    assert _apply_revision(doc, "delete", "综上所述，", "", anchor_end="根本不存在的标记") \
        == doc.replace("综上所述，", "", 1)


def test_outline_headings_are_excluded_from_scoring():
    """大纲模式下不能拿用户自己写的标题层级去扣 coherence。

    实测连续三轮的判词都是「产品和众筹使用三级标题而时间线、团队、反思使用
    二级标题，造成标题层级不统一」——那正是用户给的结构，而且系统还有一道
    硬防线专门保证它不被改动。**既扣分又不许改，闭环只能空转。**
    """
    from app.harness.state import State
    from app.harness.modes import NOTE
    from app.routers.note_harness import _score_context
    from app.tools import ToolContext

    st = State(mode=NOTE, ctx=ToolContext(user="u", note_id="n"))
    assert "标题结构" not in _score_context(st)
    st.bag["outline_mode"] = True
    assert "不要评价标题的层级" in _score_context(st)["标题结构"]


def test_polish_mode_never_freezes_structure():
    """打磨模式不能启用大纲保护——两者语义直接冲突。"""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "harness" / "hooks" / "note.py").read_text(encoding="utf-8")
    assert "is_outline = (not self.polish) and outline.is_outline(content)" in src, \
        "打磨的全部意义是修结构缺陷，大纲保护的全部意义是冻结结构"


def test_dry_rounds_stop_the_loop():
    """连着两轮检索没带回新事实就停——继续写只能语义重复。

    实测证据：段落两两相似度最高只有 0.29（字面完全不重复），而打分判词
    连着三轮都是「ask memory 优先、integration 顺延的结论在多个段落中反复
    出现」。机械查重和 drop_already_written 都抓不到这种语义重复，根因也
    不在写作在材料——material_use 一直是 2.0，它确实在用材料，用了三遍。
    """
    from app.harness.modes import NOTE, material_used_up
    from app.harness.state import State
    from app.tools import ToolContext

    st = State(mode=NOTE, ctx=ToolContext(user="u", note_id="n"), round=3)
    st.bag["dry_rounds"] = 2
    assert material_used_up(st) == "material_used_up"

    st.bag["polish"] = True
    assert material_used_up(st) is None, "打磨模式本来就不检索，不能拿这条停它"

    assert material_used_up(State(mode=NOTE, ctx=st.ctx, round=1,
                                  bag={"dry_rounds": 5})) is None, "第一轮不算"
    assert material_used_up in NOTE.stop_when


def test_dropped_revisions_are_not_reported_as_errors():
    """防线丢掉一条修订是正常工作，不能用 error 事件报。

    四道防线（同义重写／锚点有歧义／会切出破字／会动到用户的标题）一轮能丢
    好几条，全用 error 报的话前端会渲染成一片红色报错。
    """
    src = (Path(__file__).resolve().parent.parent
           / "app" / "harness" / "middleware" / "revise.py").read_text(encoding="utf-8")
    assert "CUSTOM_DROPPED" in src
    assert "Event.run_error" not in src, "丢弃不是错误"
    for phrase in ("已丢弃", "删掉一句元话语"):
        i = src.index(phrase)
        head = src.rfind("Event.custom(", max(0, i - 400), i)
        assert head >= 0 and "CUSTOM_DROPPED" in src[head:head + 40], \
            f"{phrase!r} 不是用 dropped 事件报的"


def test_scorer_diagnosis_reaches_the_edit_pass():
    """打分器写的那句诊断原文必须传到修订，光传维度名不够。

    重复往往是**语义**的（实测段落两两相似度最高只有 0.29），difflib 的机械
    查重看不见，`dup_hints` 是空的——那句诊断是修订唯一的具体线索。丢掉它的
    代价：12 次跑里 7 次第一轮就判 non_repetition=1，然后 1 → 1 → 1，跑完
    三轮一次都没回到 2，而清理分支存在的全部意义就是修这个。
    """
    import inspect
    from app.scoring import DimensionScore, Evaluation

    from app import prompts
    from app.harness.loop import _weak_note
    from app.harness.modes import NOTE
    from app.harness.state import State
    from app.tools import ToolContext

    assert "focus_note" in inspect.signature(prompts.edit_user).parameters

    st = State(mode=NOTE, ctx=ToolContext(user="u", note_id="n"))
    st.ev = Evaluation(
        scores={"non_repetition": DimensionScore(level=1, note="结论在多个段落中反复出现")},
        status="continue", weakest="non_repetition")
    assert _weak_note(st) == "结论在多个段落中反复出现"

    revise = (Path(__file__).resolve().parent.parent
              / "app" / "harness" / "middleware" / "revise.py").read_text(encoding="utf-8")
    assert 'focus_note=st.bag.get("focus_note", "")' in revise, "诊断没传进修订"

    out = prompts.edit_user("张力", ["节拍"], "正文", [], [], focus="non_repetition",
                            focus_note="结论在多个段落中反复出现")
    assert "结论在多个段落中反复出现" in out
    # 没有诊断时不要凭空多出一句
    assert "打分时具体指出的问题是" not in prompts.edit_user(
        "张力", ["节拍"], "正文", [], [], focus="non_repetition")


def test_both_harnesses_get_the_same_deterministic_defect_feed():
    """占位符、审计腔、插入前去重——三条都必须两条 harness 都接上。

    「两条路径共用一套机制、只修了一边」出现过六次：insert_offset、
    writing_plan 的丢弃防线、清理分支的结构保护、drop_already_written、
    审计腔定位、修订后清理。前五次都是给新路径做 bench 才发现的。
    """
    harness = Path(__file__).resolve().parent.parent / "app" / "harness"
    revise = (harness / "middleware" / "revise.py").read_text(encoding="utf-8")
    assert "grounding_check.placeholder_lines(st.content)" in revise, "缺占位符检测"
    assert "grounding_check.audit_voice_lines(st.content)" in revise, "缺审计腔检测"

    for name in ("note.py", "section.py"):
        src = (harness / "hooks" / name).read_text(encoding="utf-8")
        assert "outline.drop_already_written(" in src, f"{name} 缺插入前去重"


def test_mechanism_leak_is_scrubbed_before_saving():
    """两条 harness 落盘前都要删掉提到工作机制的句子。

    最后一轮写出来的内容不会再经过修订（循环是「修订→续写→打分」），所以
    只靠 audit_voice_lines() 喂给修订这条线够不到它——文件夹级实测两个目标
    两次都把「知识库」写进了用户的笔记。
    """
    hooks = Path(__file__).resolve().parent.parent / "app" / "harness" / "hooks"
    for name in ("note.py", "section.py"):
        src = (hooks / name).read_text(encoding="utf-8")
        assert "grounding_check.scrub_meta_sentences(" in src, f"{name} 落盘前没做清理"


def test_meta_scrub_runs_after_revisions_too():
    """修订应用完也要清理元话语——一条 replace 就能把审计腔写回正文。

    实测：给续写侧加了清理之后，文件夹级仍然出现「不能证明」。第六次撞上
    「一条路径修了、另一条没修」——现在只有一条路径了。
    """
    src = (Path(__file__).resolve().parent.parent
           / "app" / "harness" / "middleware" / "revise.py").read_text(encoding="utf-8")
    assert "scrub_meta_sentences_v(st.content)" in src, "修订后没清理"
    assert "if applied or meta_gone:" in src, "只有修订成功才落盘，纯清理的结果会丢"


def test_skeleton_is_persisted_with_the_note():
    """写作骨架必须跟着笔记存，不能只活在前端内存里。

    真实症状：「写作骨架一会儿就没了」。前端 open() 一进笔记就
    setSpine('')/setBeats([])，于是换一篇、刷新页面、甚至无限续写开着「跟随」
    自动切到下一段，骨架都没了——而 harness 每轮都拿它当主线依据，没了就得
    重新花一次模型调用生成一份。
    """
    from app import store

    src = (Path(__file__).resolve().parent.parent / "app" / "store.py").read_text(encoding="utf-8")
    assert "ALTER TABLE notes ADD COLUMN spine" in src
    assert "ALTER TABLE notes ADD COLUMN beats" in src

    user = "test-skeleton"
    n = store.create_note(user, "标题", "正文")
    assert n["spine"] == "" and n["beats"] == []
    store.set_skeleton(user, n["id"], "核心张力", ["起", "承", "转"])
    assert store.get_skeleton(user, n["id"]) == ("核心张力", ["起", "承", "转"])
    # 出参必须是数组：库里存的是 JSON 字符串，不转的话 Note 响应模型会校验失败、
    # 整个笔记接口 500
    got = store.get_note(user, n["id"])
    assert isinstance(got["beats"], list) and got["spine"] == "核心张力"
    assert isinstance(store.list_notes(user)[0]["beats"], list)
    # 改正文不能顺手把骨架抹掉
    store.update_note(user, n["id"], "标题", "改过的正文")
    assert store.get_skeleton(user, n["id"])[0] == "核心张力"
    store.delete_note(user, n["id"])
