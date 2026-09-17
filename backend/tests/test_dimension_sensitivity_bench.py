"""灵敏度评测台自己的回归测试（`scripts/dimension_sensitivity_bench.py`）。

跟 `test_quality_bench_checks.py` 同一个理由，而且更硬一层：这个 bench 的结论是
**「哪几个评分维度不合格」**，直接决定要不要动 `modes.py` 里的判词。测量工具坏了，
结论会**看起来完全正常**地把好维度判成废的（植入器其实没植进去）或者把废维度判成
好的（植入器顺手把别的东西也改了，掉分来自别处）。

所以这里钉三样，一样都不能少：

1. **语料筛选**——批 4 的教训：夹具用户不排掉，任何在"真实数据"上量出来的数
   都被一篇 47k 字的合成探针支配。
2. **每个植入器真的植入了那个缺陷**，而且**只植入那个**（能用代码判准的一律
   用代码判：占位符、审计腔、假图、手写 mermaid、表格列数）。
3. **统计**——"抓住 / 没抓住 / 无从判断 / 未跑"四种结论不许互相串台；
   尤其是「干净版就已经 0 分」必须报成"无从判断"而不是"没抓住"。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

bench = pytest.importorskip("dimension_sensitivity_bench")


# ----------------------------------------------------------- 语料筛选 ---

def _row(nid, user, title="标题", content="正", spine="", beats=""):
    return {"id": nid, "user_id": user, "title": title,
            "content": content * 400, "spine": spine, "beats": beats}


def test_批4点名的四个夹具用户一个都不许漏():
    """批 4 的驳回理由原文里点名了这四个。名单退化会让整张灵敏度表失真，
    而且**不会有任何症状**——所以单独钉一条。"""
    for user in ("shot-perf", "shot-demo", "harness-test-2", "cancel-test3"):
        assert bench.fixture_reason(user, "随便什么标题"), user


def test_真实用户的真实笔记要留下():
    """判据窄一点：只认夹具用户名单和标题里的自我标注，
    不做任何"看起来像测试"的推断——误伤一篇真实产出比多跑一篇夹具贵。"""
    assert bench.fixture_reason("terrence", "众筹前的产品验证与用户反馈") == ""
    assert bench.fixture_reason("terrence-rewrite", "未命名") == ""


def test_真实用户名下自标注的自测笔记也要排掉():
    assert "自测" in bench.fixture_reason("terrence", "harness 测试（可删）")
    assert "自测" in bench.fixture_reason("terrence", "链接测试（可删）")


def test_筛选把排掉的原因一并报出来():
    """排掉了什么必须能报出来——批 4 的问题正是"语料脏"这件事没有任何地方看得见。"""
    kept, dropped = bench.select_corpus([
        _row("a", "terrence", content="真实内容"),
        _row("b", "shot-perf"),
        _row("c", "terrence", title="harness 测试（可删）"),
        {"id": "d", "user_id": "terrence", "title": "短", "content": "太短了",
         "spine": "", "beats": ""},
    ])
    assert [k["id"] for k in kept] == ["a"]
    reasons = {d["id"]: d["reason"] for d in dropped}
    assert "shot-perf" in reasons["b"]
    assert "自测" in reasons["c"]
    assert "太短" in reasons["d"]


def test_留下的按长度从长到短():
    kept, _ = bench.select_corpus([_row("short", "terrence", content="甲乙"),
                                   _row("long", "terrence", content="甲乙丙")])
    assert [k["id"] for k in kept] == ["long", "short"]


def test_取材器没人满足时要把语料补上():
    """纯按长度取前 N 会让整类 probe 永远"未跑"，而那跟"没测出来"是两回事。"""
    long_no_table = _row("long", "terrence", content="没有表格的长正文。")
    short_with_table = {"id": "tbl", "user_id": "terrence", "title": "有表",
                        "content": "引子。\n\n| 甲 | 乙 |\n|---|---|\n| 1 | 2 |\n",
                        "spine": "", "beats": ""}
    sel = {"table-block": bench.pick_table_block}
    picked = bench.choose_notes([long_no_table, short_with_table], 1, sel)
    assert [p["id"] for p in picked] == ["long", "tbl"]
    # 已经有人满足时不多取
    assert len(bench.choose_notes([short_with_table, long_no_table], 1, sel)) == 1


# ------------------------------------------------------------- 植入器 ---

NOTE = (
    "## 第一节 众筹前的验证\n\n"
    "2026 年 3 月 15 日的版本优先验证 ask memory，首单 1.5 万台预计七月底完成生产并出货。"
    "这一节讲的是众筹之前团队怎么验证真实需求，依据是当时留下的会议记录与客户访谈；"
    "验证的重点不是功能数量，而是用户能不能在持续使用中感受到软件带来的帮助。"
    "按当时的口径，保守情景 1.5 万台、中性情景 3 万台、谨慎乐观情景 10 万台。\n\n"
    "团队当时判断硬件只是一次性的入口，软件体验才是长期产生价值、持续扩展的部分，"
    "所以决定先把手上已有的两个模块做完，再往下推进，避免在没有真实体验的情况下堆功能。\n\n"
    "## 第二节 众筹后的承接\n\n"
    "众筹结束之后要把支持者转成真实用户，8 月 5 日出货，中性情景是 3 万台。"
    "这一节讲的是发货之后怎么承接这批人，跟上一节讲的验证不是一件事；"
    "承接的关键在于首次使用是否发生，以及使用之后有没有留下可用于迭代的反馈。\n\n"
    "## 第三节 下一步\n\n"
    "接下来要观察首次使用率，再决定第二款产品是否立项；在这些结果出来之前，"
    "任何关于第二款产品的方向都只能算规划，不应当写成已经确定的产品路线。\n"
)

CHART = ("下面这张图是节点关系：\n\n```mermaid\ngraph LR\n"
         "A[3月15日版本] --> B[7月29日MP]\nB --> C[7月底首单]\nC --> D[8月5日出货]\n```\n")

TABLE = ("各中介的方案放在同一张表里比较：\n\n"
         "| 中介 | 报价 | 判断依据 |\n|---|---|---|\n"
         "| A | 填写具体金额 | 填写可比成交 |\n| B | 填写具体金额 | 填写带看反馈 |\n")


def test_复制一段是逐字复制的():
    out = bench.inj_duplicate_paragraph(NOTE, "")
    src = max(bench.paragraphs(NOTE)[:-1], key=len)
    assert out.count(src) == 2


def test_复制一段在段数不够时不硬来():
    assert bench.inj_duplicate_paragraph("一段而已。", "") is None


def test_删整节删的是标题带正文():
    out = bench.inj_drop_last_section(NOTE, "")
    assert "## 第三节 下一步" not in out
    assert "## 第一节 众筹前的验证" in out and "## 第二节 众筹后的承接" in out
    assert "接下来要观察首次使用率" not in out


def test_改日期只动日期():
    out = bench.inj_shift_dates(NOTE, "")
    assert "2031 年" in out and "2026 年" not in out
    assert "8 月 5 日" not in out
    # 正文的其他字一个都没动
    assert "这一节讲的是众筹之前团队怎么验证真实需求" in out


def test_改数字只动带量词的数():
    out = bench.inj_scramble_numbers(NOTE, "")
    assert "11.5 万台" in out and "16 万台" in out and "37 万台" in out   # ×3 再 +7
    assert "保守情景 1.5 万台" not in out
    assert "ask memory" in out and "这一节讲的是发货之后怎么承接这批人" in out


def test_两节正文对调_跳过正文是空的那一节():
    """真实产出里第一个标题下面常常是空的（正文挂在子标题上），
    拿空的去换等于什么都没换——这条钉住的就是那次实测。"""
    empty_first = "## 空壳\n\n### 子节\n\n" + "正文很长。" * 30 + "\n\n## 第二节\n\n" + "另一件事。" * 30
    out = bench.inj_swap_section_bodies(empty_first, "")
    assert out is not None and out != empty_first


def test_标题层级打乱只降一个():
    """只把第二个二级标题降成四级，别的标题原样——**改多了就不是"层级混用"
    这一种缺陷了**，掉分会混进别的原因。"""
    out = bench.inj_heading_levels(NOTE, "")
    assert "#### 第二节 众筹后的承接" in out
    assert out.count("\n## ") == NOTE.count("\n## ") - 1
    assert "## 第一节 众筹前的验证" in out and "## 第三节 下一步" in out
    assert len(out) == len(NOTE) + 2                # 只多了两个 #


# 具体材料占主体的一段真实形状文本（`strip_specifics` 要砍掉的正是这一类句子）
MATERIAL_HEAVY = (
    "## 交付节点\n\n"
    "项目原定于 2026 年 6 月底出货，目前版本已改为 8 月 5 日。"
    "MP 最终时间为 7 月 29 日，首单 1 万台预计在 7 月底完成生产。"
    "2026 年的销售预测按半年周期划分为三种情景，分别约为 1.5 万台、3 万台和 10 万台。"
    "团队计划于 2026 年 8 月向用户发货。\n\n"
    "这说明交付安排已经排好。\n")


def test_去掉具体材料之后正文里一个数字都不剩():
    out = bench.inj_strip_specifics(MATERIAL_HEAVY, "")
    assert out is not None
    body = "\n".join(l for l in out.splitlines() if not l.startswith("#"))
    assert not any(ch.isdigit() for ch in body)
    assert len(out) < len(MATERIAL_HEAVY) * 0.6
    assert "## 交付节点" in out          # 标题不动，掉的只是具体材料


def test_去掉具体材料删不动多少就不算植入():
    """砍不动的时候必须返回 None：拿一个没成形的"缺陷"去给维度定罪是最坏的一种错。"""
    assert bench.inj_strip_specifics("没有任何具体信息的一段话。" * 10, "") is None


def test_审计腔和占位符要被确定性判据认出来():
    from app.harness.checks import grounding_rules
    assert not grounding_rules.audit_voice_lines(NOTE)
    assert grounding_rules.audit_voice_lines(bench.inj_audit_voice(NOTE, ""))
    assert not grounding_rules.placeholder_lines(NOTE)
    assert grounding_rules.placeholder_lines(bench.inj_placeholder(NOTE, ""))


def test_手写mermaid要被charts判据认出来():
    from app.harness.checks import blockcheck
    assert not blockcheck.unauthorized_charts(CHART, [])       # 简单流程图本来就放行
    assert blockcheck.unauthorized_charts(bench.inj_handwrite_mermaid(CHART, ""), [])


def test_把图换成文字要被假图判据认出来():
    from app.harness.checks import blockcheck
    dirty = bench.inj_chart_to_prose(CHART, "")
    assert "```mermaid" not in dirty
    assert blockcheck.fake_charts(dirty) or blockcheck.text_flow(dirty)


def test_截断代码块之后收尾围栏没了():
    dirty = bench.inj_break_mermaid_fence(CHART, "")
    assert dirty.count("```") == 1


def test_表头少一列能被列数判据抓到():
    assert not bench.table_column_mismatch(TABLE)
    dirty = bench.inj_drop_table_column(TABLE, "")
    assert bench.table_column_mismatch(dirty)


def test_列数判据不把正常表报成错():
    """判据宁可窄一点：只在同一张表内部列数不一致时才算。"""
    assert not bench.table_column_mismatch("正文里有个竖线 a|b 而已")
    assert not bench.table_column_mismatch(TABLE + "\n\n| 甲 |\n|---|\n| 1 |\n")


def test_往表里填的是笔记里查无此事的数():
    dirty = bench.inj_invent_table_cells(TABLE, "")
    assert "填写" not in dirty and "842 万元" in dirty


def test_mutate在干净版本身就有缺陷时跳过而不是照跑():
    """这是整个 bench 最容易出错的地方：干净版已经有审计腔时，
    "植入版也有审计腔"什么都证明不了。"""
    inj = bench.INJECTORS["audit_voice"]
    dirty, why = inj.mutate(NOTE, "")
    assert dirty and not why
    already = NOTE + "\n" + bench.AUDIT_SENTENCE
    dirty2, why2 = inj.mutate(already, "")
    assert not dirty2 and "干净版本身" in why2


def test_mutate在植入没成形时跳过():
    """植入器返回了文本、但确定性判据没抓到 → 不能当成"维度不灵敏"。"""
    bad = bench.Injector("坏的", lambda t, d: t + "什么都没加。", gate="placeholder")
    dirty, why = bad.mutate(NOTE, "")
    assert not dirty and "没成形" in why


def test_mutate在植入器不适用时跳过():
    inj = bench.INJECTORS["drop_table_column"]
    dirty, why = inj.mutate(NOTE, "")
    assert not dirty and "不适用" in why


# --------------------------------------------------------------- 统计 ---

def _rec(probe, note, arm, dim, level, rep=0):
    return {"key": f"{note}|{probe}|{arm}|{rep}", "probe": probe, "note": note,
            "arm": arm, "rep": rep, "scores": {dim: level}}


P = bench.Probe("note", "whole", "duplicate_paragraph", ("non_repetition",))


def test_掉一整档算抓住():
    rows = bench.summarize([_rec(P.id, "n1", "clean", "non_repetition", 2),
                            _rec(P.id, "n1", "dirty", "non_repetition", 1)], (P,))
    assert rows[0]["verdict"] == "抓住" and rows[0]["drop"] == 1.0


def test_一分不掉算没抓住():
    rows = bench.summarize([_rec(P.id, "n1", "clean", "non_repetition", 2),
                            _rec(P.id, "n1", "dirty", "non_repetition", 2)], (P,))
    assert rows[0]["verdict"] == "没抓住"


def test_掉不到半档只算只动了一点():
    """判据宁可窄一点：三档制下 0.5 = 一半的配对掉了一整档，低于这个不算抓住。"""
    rows = bench.summarize([_rec(P.id, "n1", "clean", "non_repetition", 2),
                            _rec(P.id, "n1", "dirty", "non_repetition", 2, rep=0),
                            _rec(P.id, "n1", "dirty", "non_repetition", 2, rep=1),
                            _rec(P.id, "n1", "dirty", "non_repetition", 1, rep=2)], (P,))
    assert rows[0]["verdict"] == "只动了一点"


def test_干净版就已经垫底时报无从判断():
    """0 分再植入缺陷也掉不下去。把这种报成"没抓住"是**假阳性**——
    会让一个其实分不出好坏的格子去给维度定罪。"""
    rows = bench.summarize([_rec(P.id, "n1", "clean", "non_repetition", 0),
                            _rec(P.id, "n1", "dirty", "non_repetition", 0)], (P,))
    assert rows[0]["verdict"] == "无从判断"


def test_植入之后反而涨分要单独报出来():
    """比"没抓住"严重一档：不是看不见，是**看反了**。实测撞到过——
    把一张工具画的 mermaid 换成一个根本不存在的图片引用，
    `chart_validity` / `data_grounding` / `right_kind` 从 0 分齐涨到 2 分。"""
    rows = bench.summarize([_rec(P.id, "n1", "clean", "non_repetition", 0),
                            _rec(P.id, "n1", "dirty", "non_repetition", 2)], (P,))
    assert rows[0]["verdict"] == "反着来了"


def test_干净版基线偏低时不许下没抓住的结论():
    """1.6 要分开的正是这两件事：**判据废了**（干净版分数正常、植入后不掉）
    和**条件没出现**（这一维在这份语料上本来就分不出好坏）。
    基线 0.5 分时"没掉"说明不了前者。"""
    rows = bench.summarize([_rec(P.id, "n1", "clean", "non_repetition", 1, rep=0),
                            _rec(P.id, "n1", "clean", "non_repetition", 0, rep=1),
                            _rec(P.id, "n1", "dirty", "non_repetition", 1, rep=0),
                            _rec(P.id, "n1", "dirty", "non_repetition", 0, rep=1)], (P,))
    assert rows[0]["clean"] == 0.5 and rows[0]["verdict"] == "基线偏低"


def test_基线正常又一分不掉才算没抓住():
    rows = bench.summarize([_rec(P.id, "n1", "clean", "non_repetition", 2),
                            _rec(P.id, "n1", "dirty", "non_repetition", 2)], (P,))
    assert rows[0]["verdict"] == "没抓住"


def test_没跑过的格子报未跑而不是没抓住():
    """"没测"和"测了没反应"是两件事，混在一起这张表就没法用。"""
    rows = bench.summarize([], (P,))
    assert rows[0]["verdict"] == "未跑" and rows[0]["n_notes"] == 0


def test_只有一边的配对不算数():
    rows = bench.summarize([_rec(P.id, "n1", "clean", "non_repetition", 2)], (P,))
    assert rows[0]["verdict"] == "未跑"


def test_打分失败那一格不进统计():
    """`ScoreParseError` = 这一轮没打上分，跟"打了 0 分"是两回事（批 3 的 1.7）。

    **带 `error` 的行一律不是一次测量，哪怕它身上还挂着 scores。** 第一版用例
    只给了个没有 scores 的错误行——那条什么都没钉住：把 `r.get("error")` 这道
    守卫整个删掉，用例照样全绿（统计本来就会因为没有 scores 而跳过它）。
    这正是批 3 记下的那种"用例不够"的突变漏网。
    """
    err = {"key": "k", "probe": P.id, "note": "n1", "arm": "dirty", "rep": 0,
           "error": "ScoreParseError: x", "scores": {"non_repetition": 0}}
    rows = bench.summarize([_rec(P.id, "n1", "clean", "non_repetition", 2), err], (P,))
    assert rows[0]["verdict"] == "未跑"


def test_一维取它最好的那条probe():
    """一维只要有一条 probe 抓住了，它就不算不合格——剩下那几条说的是
    那**种缺陷**抓不抓得到，不是那**一维**废不废。实测：`topic_fidelity`
    对"两节正文对调"毫无反应，对"把别的主题接进来"掉 0.6。"""
    rows = [{"dim": "topic_fidelity", "probe": "a", "verdict": "没抓住", "drop": 0.0,
             "clean": 1.0, "dirty": 1.0, "n_notes": 4},
            {"dim": "topic_fidelity", "probe": "b", "verdict": "抓住", "drop": 0.6,
             "clean": 1.07, "dirty": 0.47, "n_notes": 5}]
    assert [r["probe"] for r in bench.roll_up(rows)] == ["b"]


def test_同档之间取掉分更大的那条():
    rows = [{"dim": "d", "probe": "小", "verdict": "只动了一点", "drop": 0.08,
             "clean": 2.0, "dirty": 1.92, "n_notes": 4},
            {"dim": "d", "probe": "大", "verdict": "只动了一点", "drop": 0.33,
             "clean": 1.47, "dirty": 1.13, "n_notes": 5}]
    assert bench.roll_up(rows)[0]["probe"] == "大"


def test_反着来了排在最后一档():
    """植入缺陷之后反而涨分，比"没抓住"更糟，不许被当成"还行"的结论。"""
    rows = [{"dim": "d", "probe": "反", "verdict": "反着来了", "drop": -1.89,
             "clean": 0.11, "dirty": 2.0, "n_notes": 3},
            {"dim": "d", "probe": "没", "verdict": "没抓住", "drop": 0.0,
             "clean": 2.0, "dirty": 2.0, "n_notes": 3}]
    assert bench.roll_up(rows)[0]["probe"] == "没"
    assert bench.VERDICT_RANK[-1] == "反着来了"


def test_顺带掉分只报不是目标的那几维():
    recs = [_rec(P.id, "n1", "clean", "non_repetition", 2),
            _rec(P.id, "n1", "dirty", "non_repetition", 0),
            {"key": "x", "probe": P.id, "note": "n1", "arm": "clean", "rep": 0,
             "scores": {"coherence": 2}},
            {"key": "y", "probe": P.id, "note": "n1", "arm": "dirty", "rep": 0,
             "scores": {"coherence": 1}}]
    side = bench.collateral(recs, (P,))
    assert [s["dim"] for s in side] == ["coherence"]


# --------------------------------------------------------- 任务与覆盖 ---

def test_断点续跑跳过已经跑完的格子():
    note = {"id": "n1", "user_id": "terrence", "title": "标题",
            "content": NOTE, "spine": "", "beats": ""}
    tasks, _ = bench.build_tasks([note], (P,), 1, set())
    assert {t.arm for t in tasks} == {"clean", "dirty"}
    done = {tasks[0].key}
    again, _ = bench.build_tasks([note], (P,), 1, done)
    assert len(again) == len(tasks) - 1


def test_植不进去的probe记成跳过而不是静默消失():
    note = {"id": "n1", "user_id": "terrence", "title": "标题",
            "content": "只有一段话，什么都植不进去。", "spine": "", "beats": ""}
    tasks, skips = bench.build_tasks([note], (P,), 1, set())
    assert not tasks and len(skips) == 1 and skips[0]["probe"] == P.id


def test_每个评分维度都有probe盯着():
    """25 个维度一条不落。**加了新维度而没给它配 probe，这条会红**——
    否则新维度的灵敏度就是一个谁都不知道的空白。"""
    from app.harness import modes
    live = {d.name for m in modes.ALL
            for d in modes.for_run(m, has_profile=True, polish=False).dims}
    covered = set(bench.covered_dimensions())
    assert not (live - covered), f"这些维度没有 probe：{sorted(live - covered)}"
    assert not (covered - live), f"probe 盯着不存在的维度：{sorted(covered - live)}"


def test_按核心张力打分的probe只用真有核心张力的语料():
    """实测踩过：最长的两篇 `spine` / `beats` 都是空的，于是
    `spine_fidelity` / `beat_coverage` 是在"没有张力 / 没有节拍"的条件下被打分的。
    那量出来的是"条件没出现"，跟"判据不灵"是两回事。"""
    no_spine = {"id": "a", "user_id": "terrence", "title": "t",
                "content": NOTE, "spine": "", "beats": ""}
    with_spine = {**no_spine, "id": "b", "spine": "这篇要解决的是…"}
    with_beats = {**no_spine, "id": "c", "beats": '["先讲验证", "再讲承接"]'}
    assert bench.pick_whole_with_spine(no_spine) is None
    assert bench.pick_whole_with_spine(with_spine) is not None
    assert bench.pick_whole_with_beats(no_spine) is None
    assert bench.pick_whole_with_beats({**no_spine, "beats": "[]"}) is None
    assert bench.pick_whole_with_beats(with_beats) is not None
    for p in bench.PROBES:
        if "spine_fidelity" in p.targets:
            assert p.selector == "whole-with-spine", p.id
        if "beat_coverage" in p.targets:
            assert p.selector == "whole-with-beats", p.id


def test_每条probe的目标维度真的属于那个模式():
    """probe 写错模式时，目标维度根本不在打分结果里，
    统计会一路安静地报"未跑"——那是最难发现的一种测量错。"""
    from app.harness import modes
    by_key = {m.key: m for m in modes.ALL}
    for p in bench.PROBES:
        dims = {d.name for d in
                modes.for_run(by_key[p.mode], has_profile=True, polish=False).dims}
        assert set(p.targets) <= dims, f"{p.id} 的目标维度不在 {p.mode} 里"
