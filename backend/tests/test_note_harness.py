"""单篇笔记 harness：note_harness._apply_revision() 的锚点应用语义（跟
前端 RevisionPanel.tsx 的 applyRevision() 是同一套语义，Python 版本），
以及 prompts.note_harness_continue_user()/edit_user() 的拼装。

"完不完整"的判断已经迁到 writer_harness.evaluate()（见
writer_harness/tests/test_rubric.py），这里不再重复测；_beats_status()
和 NOTE_HARNESS_DONE_MARKER 已经随之删除。

    cd backend && python -m pytest tests/test_note_harness.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import prompts  # noqa: E402
from app.routers.note_harness import _apply_revision  # noqa: E402


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
    from app.routers.note_harness import _tidy_blank_lines

    # 「## A\n\n正文\n\n## B」删掉中间正文后的形态
    assert _tidy_blank_lines("## A\n\n\n\n## B") == "## A\n\n## B"
    assert _tidy_blank_lines("a\n\nb") == "a\n\nb"          # 正常段落间距不动
    assert _tidy_blank_lines("a\nb") == "a\nb"                # 单换行不动


def test_tidy_blank_lines_keeps_code_block_content_intact():
    """代码块里的空行是内容不是格式，不能压。"""
    from app.routers.note_harness import _tidy_blank_lines

    src = "```\nx\n\n\n\ny\n```"
    assert _tidy_blank_lines(src) == src


def test_harness_entry_points_accept_the_args_the_loop_passes():
    """调用点跟函数签名必须对得上。

    真实踩过：给 _run_edit_pass 加 round_idx 时签名替换没匹配上，调用点却
    加了这个 kwarg，跑起来第一时间 TypeError、整个 run 当场死掉——而
    **pytest 全绿**，因为没有任何测试会调用这个函数。SSE 生成器里的
    TypeError 只会在真机跑的时候暴露，所以这里用签名检查兜住。
    """
    import inspect

    from app.routers import note_harness as nh, writing_plan as wp

    edit = inspect.signature(nh._run_edit_pass).parameters
    for name in ("max_revisions", "round_idx"):
        assert name in edit, f"_run_edit_pass 缺少 {name}"

    ev = inspect.signature(nh._evaluate_round).parameters
    assert "facts_used" in ev

    sec = inspect.signature(wp._evaluate_section).parameters
    assert "facts_used" in sec


def test_anchor_end_locates_a_span_without_echoing_it():
    """anchor + anchor_end 用两个短标记定位一整段，模型不用把原文抄一遍。

    原来的契约要求 anchor 是"要被替换的完整原文"——一段两百字的段落就得
    原样回显两百字，replace 时改后的 text 再输出一遍，同一段内容进出各一次。
    输出 token 直接换算成时间，是纯浪费。
    """
    from app.routers.note_harness import _apply_revision

    c = "## 标题\n\n开头这几个字，中间很长的一大段内容省略掉，结尾这几个字。\n\n下一段。"
    assert _apply_revision(c, "replace", "开头这几个字", "换成这个",
                           anchor_end="结尾这几个字。") == "## 标题\n\n换成这个\n\n下一段。"
    assert _apply_revision(c, "delete", "开头这几个字", "",
                           anchor_end="结尾这几个字。") == "## 标题\n\n\n\n下一段。"


def test_missing_anchor_end_falls_back_to_anchor_only():
    """结尾标记定位不到时宁可少改一点，也不要按错误的范围改。"""
    from app.routers.note_harness import _apply_revision

    c = "第一段。第二段。"
    assert _apply_revision(c, "delete", "第一段。", "", anchor_end="不存在") == "第二段。"
    # 不给 anchor_end 时行为跟以前完全一致
    assert _apply_revision(c, "delete", "第一段。", "") == "第二段。"


def test_sources_markers_expand_to_full_facts():
    """模型只回显方括号标记，后端还原成完整事实——显示不减，输出 token 大减。"""
    from app.routers.note_harness import _expand_sources

    facts = ["[2026-04-10] 硬件4月10号出来。", "[terrence-2046-2F3] Speaker E 问3月31号。"]
    assert _expand_sources(["2026-04-10"], facts) == ["[2026-04-10] 硬件4月10号出来。"]
    assert _expand_sources(["[terrence-2046-2F3]"], facts)[0].startswith("[terrence-2046-2F3]")
    assert _expand_sources(["认不出来的"], facts) == ["认不出来的"]   # 不丢来源


def test_judging_uses_run_level_facts_not_this_round():
    """一切"拿整篇正文去比对材料"的判断，材料一侧必须是整次 run 累积的。

    真实 bug：``round_facts`` 每轮重置，正文却是累积的。第 3 轮的打分拿第 3 轮
    检索到的材料审判包含第 1 轮内容的整篇，于是把第 1 轮明明有依据的日期判成
    "知识库中查无此事"——``factual_grounding`` 从 2 掉到 0。篇幅越长误判越多，
    所以它是随写作质量变好才暴露的。

    这条只能靠读源码测：三个判断点都在 SSE 生成器内部，没有可以单独调用的
    入口，而 290 条单测全绿的时候这个 bug 就在线上跑着。
    """
    src = (Path(__file__).resolve().parent.parent
           / "app" / "routers" / "note_harness.py").read_text(encoding="utf-8")
    for call in ("facts_used=",                      # 打分
                 "grounding_check.grounding_gap(",   # material_use 兜底
                 "grounding_check.material_exhausted("):  # 材料耗尽终止
        idx = src.index(call)
        arg = src[idx:idx + 90]
        assert "round_facts" not in arg, f"{call} 用了本轮事实，应该用 run_facts：{arg!r}"
        assert "run_facts" in arg, f"{call} 没用累积事实：{arg!r}"


def test_same_meaning_rewrite_is_rejected():
    """只换措辞的 replace 必须被拦下。样本取自真实产出：同一段被 replace 三次。"""
    from app.routers.note_harness import _is_same_meaning_rewrite as same

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
    """同一处只允许改一次——第二次一律拦掉，否则轮次全耗在原地打磨措辞。"""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "routers" / "note_harness.py").read_text(encoding="utf-8")
    assert "edited_spans: set[str] = set()" in src, "run 循环里要建跨轮集合"
    assert "edited=edited_spans" in src, "集合要传进编辑 pass"
    assert 'if op == "replace" and edited is not None and key in edited:' in src, \
        "应用阶段要硬拦，不能只在提示词里说"


def test_breakage_catches_half_replaced_sentence():
    """修订切错位置留下的残骸要能查出来。样本是真实产出里抓到的破字。"""
    from app.routers.note_harness import _breakage as brk

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
           / "app" / "routers" / "note_harness.py").read_text(encoding="utf-8")
    assert 'op == "replace" and not anchor_end and content.count(anchor) > 1' in src
    assert "broke = _breakage(content, new_content)" in src


def test_both_harnesses_share_the_same_revision_guards():
    """两条 harness 共用 _apply_revision，防线也必须共用——只修一边等于
    另一条路径上的 bug 还活着（insert 顺序那个保护就吃过这个亏）。"""
    root = Path(__file__).resolve().parent.parent / "app" / "routers"
    plan = (root / "writing_plan.py").read_text(encoding="utf-8")
    assert "reject_revision(" in plan, "writing_plan 没接上同义重写/歧义锚点防线"
    assert "_breakage(content, new_content)" in plan, "writing_plan 没接上破字防线"


def test_reject_revision_reasons():
    from app.routers.note_harness import reject_revision as rej

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
    from app.routers.note_harness import reject_revision as rej

    doc = "## 众筹节奏\n\n三月上旬启动。\n\n## 众筹节奏\n\n三月上旬启动众筹。\n"
    assert rej(doc, "delete", "## 众筹节奏", "") == ""          # 去重，放行
    assert rej(doc, "replace", "## 众筹节奏", "## 别的标题")      # 改哪个说不准，拦
    # 「删掉重复的那一节」= 重复的锚 + 结尾标记，是去重的**标准形态**，必须放行。
    # 第一版把它拦了，20 轮实测 non_repetition 全 20 次 0 分、coherence 掉到 0.5。
    assert rej(doc, "delete", "## 众筹节奏", "", anchor_end="启动众筹。") == ""


def test_every_edit_pass_call_site_carries_the_guards():
    """每一个 _run_edit_pass 调用点都必须带上结构硬防线和跨轮去重集合。

    真实缺陷：「只清理不续写」那条分支两个都没传，于是三层大纲的标题层级
    在 20 轮 soak 里 **20/20 全被压平**（两层 95%、深层 90% 正常）——清理这一步
    正是「空壳标题要删掉」规则火力最猛的地方，而它在裸奔。

    这类"两条路径共用一个函数，只修了一边"的缺陷今晚出现过三次
    （insert_offset、writing_plan 的丢弃防线、这一条），所以用测试钉住。
    """
    src = (Path(__file__).resolve().parent.parent
           / "app" / "routers" / "note_harness.py").read_text(encoding="utf-8")
    calls = [i for i in range(len(src)) if src.startswith("_run_edit_pass(user,", i)]
    assert len(calls) >= 2, "调用点少于两个，这条测试的前提变了"
    for i in calls:
        block = src[i:i + 900]
        end = block.index("):")
        assert "outline_note=" in block[:end], f"第 {src[:i].count(chr(10))+1} 行的调用没传 outline_note"
        assert "edited=" in block[:end], f"第 {src[:i].count(chr(10))+1} 行的调用没传 edited"


def test_outline_target_is_decided_before_retrieval():
    """大纲模式下必须先定"这轮写哪一节"再去检索，否则每轮拿回同一批事实。

    20 轮 soak 的数据：non_repetition 是全局最弱的一维（0.9~1.7），大纲组
    50 次撞 max_rounds 而 beat_coverage 已经 1.9~2.0——卡住的正是重复。
    根因是顺序反了，模型手握众筹的材料被要求写「团队」那一节。
    """
    src = (Path(__file__).resolve().parent.parent
           / "app" / "routers" / "note_harness.py").read_text(encoding="utf-8")
    decide = src.index("outline_target = outline.next_gap(content) if is_outline else None")
    assert src.count("outline_target = outline.next_gap(") == 1, "只该算一次"
    assert decide < src.index("agent_loop.gather_context("), "定小节必须在检索之前"
    assert decide < src.index("if AGENT_TOOLS:"), "要在两条分支之上，否则关工具那条会用陈旧值"
    assert "section=outline_target[0] if outline_target else \"\"" in src, "小节名要传进检索规划"


def test_locate_picks_the_smallest_span_when_anchor_repeats():
    """锚点重复时取跨度最小的那一组——这是"删掉重复的那一节"的正确语义。"""
    from app.routers.note_harness import _apply_revision, _locate

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
    src = (Path(__file__).resolve().parent.parent
           / "app" / "routers" / "note_harness.py").read_text(encoding="utf-8")
    assert 'context["标题结构"]' in src
    assert "不要评价标题的层级" in src
    assert "is_outline=is_outline" in src, "打分调用要知道这是大纲模式"


def test_polish_mode_never_freezes_structure():
    """打磨模式不能启用大纲保护——两者语义直接冲突。"""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "routers" / "note_harness.py").read_text(encoding="utf-8")
    assert 'is_outline = body.mode != "polish" and outline.is_outline(content)' in src, \
        "打磨的全部意义是修结构缺陷，大纲保护的全部意义是冻结结构"


def test_dry_rounds_stop_the_loop():
    """连着两轮检索没带回新事实就停——继续写只能语义重复。

    实测证据：段落两两相似度最高只有 0.29（字面完全不重复），而打分判词
    连着三轮都是「ask memory 优先、integration 顺延的结论在多个段落中反复
    出现」。机械查重和 drop_already_written 都抓不到这种语义重复，根因也
    不在写作在材料——material_use 一直是 2.0，它确实在用材料，用了三遍。
    """
    src = (Path(__file__).resolve().parent.parent
           / "app" / "routers" / "note_harness.py").read_text(encoding="utf-8")
    assert "dry_rounds = 0 if fresh else dry_rounds + 1" in src
    assert 'body.mode != "polish" and round_idx >= 2 and dry_rounds >= 2' in src, \
        "打磨模式本来就不检索，不能拿这条停它"
    # 必须在打分之后判：停下来时要带上这一轮的分数
    assert src.index("dry_rounds >= 2") > src.index("evaluation = await _evaluate_round(")


def test_dropped_revisions_are_not_reported_as_errors():
    """防线丢掉一条修订是正常工作，不能用 error 事件报。

    四道防线（同义重写／锚点有歧义／会切出破字／会动到用户的标题）一轮能丢
    好几条，全用 error 报的话前端会渲染成一片红色报错。
    """
    root = Path(__file__).resolve().parent.parent / "app" / "routers"
    for name in ("note_harness.py", "writing_plan.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert '_sse("dropped"' in src, f"{name} 没用 dropped 事件"
        for phrase in ("已丢弃", "已跳过", "改哪个说不准"):
            for i in range(len(src)):
                if not src.startswith(phrase, i):
                    continue
                # 往前找最近的 _sse( 调用，确认不是 error
                head = src.rfind("_sse(", max(0, i - 400), i)
                if head < 0:
                    continue                       # 注释或 reject_revision 的返回值
                kind = src[head + 5:head + 15]
                assert '"error"' not in kind, f"{name} 用 error 报了丢弃：{src[i:i+30]!r}"


def test_scorer_diagnosis_reaches_the_edit_pass():
    """打分器写的那句诊断原文必须传到修订，光传维度名不够。

    重复往往是**语义**的（实测段落两两相似度最高只有 0.29），difflib 的机械
    查重看不见，`dup_hints` 是空的——那句诊断是修订唯一的具体线索。丢掉它的
    代价：12 次跑里 7 次第一轮就判 non_repetition=1，然后 1 → 1 → 1，跑完
    三轮一次都没回到 2，而清理分支存在的全部意义就是修这个。

    这条测试是防"改了一半"：上一次改这里，note_harness 改完了、prompts 没改，
    单测全绿而线上一跑就是 TypeError（今晚第三次栽在同一个坑）。
    """
    import inspect
    from app import prompts
    from app.routers import note_harness as nh

    assert "focus_note" in inspect.signature(prompts.edit_user).parameters
    assert "focus_note" in inspect.signature(nh._run_edit_pass).parameters
    src = Path(nh.__file__).read_text(encoding="utf-8")
    assert src.count("focus_note=focus_note") >= 3, "两个调用点 + prompts 那次都要传"
    out = prompts.edit_user("张力", ["节拍"], "正文", [], [], focus="non_repetition",
                            focus_note="结论在多个段落中反复出现")
    assert "结论在多个段落中反复出现" in out
    # 没有诊断时不要凭空多出一句
    assert "打分时具体指出的问题是" not in prompts.edit_user(
        "张力", ["节拍"], "正文", [], [], focus="non_repetition")


def test_both_harnesses_get_the_same_deterministic_defect_feed():
    """占位符、审计腔、插入前去重——三条都必须两条 harness 都接上。

    「两条路径共用一套机制、只修了一边」今晚出现了五次：insert_offset、
    writing_plan 的丢弃防线、清理分支的结构保护、drop_already_written、
    以及审计腔定位。每次都是给新路径做 bench 才发现的，所以在这里钉死。
    """
    root = Path(__file__).resolve().parent.parent / "app" / "routers"
    for name in ("note_harness.py", "writing_plan.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "grounding_check.placeholder_lines(content)" in src, f"{name} 缺占位符检测"
        assert "grounding_check.audit_voice_lines(content)" in src, f"{name} 缺审计腔检测"
        assert "outline.drop_already_written(" in src, f"{name} 缺插入前去重"


def test_mechanism_leak_is_scrubbed_before_saving():
    """两条 harness 落盘前都要删掉提到工作机制的句子。

    最后一轮写出来的内容不会再经过修订（循环是「修订→续写→打分」），所以
    只靠 audit_voice_lines() 喂给修订这条线够不到它——文件夹级实测两个目标
    两次都把「知识库」写进了用户的笔记。
    """
    root = Path(__file__).resolve().parent.parent / "app" / "routers"
    for name in ("note_harness.py", "writing_plan.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "grounding_check.scrub_meta_sentences(" in src, f"{name} 落盘前没做清理"


def test_meta_scrub_runs_after_revisions_too():
    """修订应用完也要清理元话语——一条 replace 就能把审计腔写回正文。

    实测：给续写侧加了清理之后，文件夹级仍然出现「不能证明」。第六次撞上
    「一条路径修了、另一条没修」。
    """
    root = Path(__file__).resolve().parent.parent / "app" / "routers"
    for name in ("note_harness.py", "writing_plan.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "scrub_meta_sentences_v(content)" in src, f"{name} 修订后没清理"
        assert "if applied or meta_gone:" in src, f"{name} 只有修订成功才落盘，纯清理的结果会丢"


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
