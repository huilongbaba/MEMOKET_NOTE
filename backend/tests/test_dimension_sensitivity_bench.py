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

import pathlib
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

bench = pytest.importorskip("dimension_sensitivity_bench")


# ----------------------------------------------------------- 语料筛选 ---
#
# 判据本体在 `corpus_lineage.py`，它自己的闸在 `test_corpus_lineage.py`
# （批 4 的四个夹具用户、批 6 的三篇 soak 产出都钉在那边）。
# 这里只钉 bench 这一侧：**它真的用了那份共用判据**，以及它自己那条「太短」。

def _row(nid, user, title="标题", content="正", spine="", beats=""):
    return {"id": nid, "user_id": user, "title": title,
            "content": content * 400, "spine": spine, "beats": beats}


def test_bench用的是共用的血缘判据而不是自己一份名单():
    """批 6 的结构性修法原话：**不要每个脚本各写一份 `FIXTURE_USERS`**。
    bench 里再出现一份名单，下次 soak 换个 goal 又会有一半语料悄悄混进来。"""
    src = (pathlib.Path(bench.__file__).read_text(encoding="utf-8"))
    assert "FIXTURE_USERS = " not in src, "bench 里又长出了一份自己的夹具名单"
    assert "corpus_lineage" in src


def test_脚本跑出来的笔记要按血缘排掉():
    """`soak.py` 是**拿真实 user_id 跑的**——这一条就是批 6 的原样复现。"""
    import corpus_lineage
    rows = [_row("u1", "terrence", content="用户真写的"),
            _row("s1", "terrence-rewrite", content="soak 跑出来的")]
    lineage = {"s1": corpus_lineage.Lineage("p", "整理一份众筹前后的完整时间线",
                                            "soak-整理一份众筹前后")}
    kept, dropped = bench.select_corpus(rows, lineage)
    assert [k["id"] for k in kept] == ["u1"]
    assert dropped[0]["id"] == "s1" and "soak" in dropped[0]["reason"]


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
    assert {d["id"]: d["origin"] for d in dropped}["b"] == "fixture"


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
    """判据本体在生产侧（批 16 阶段 5.1 搬过去的），bench 这边只 import。"""
    from app.harness.checks.blockcheck import table_column_mismatch

    assert not table_column_mismatch(TABLE)
    dirty = bench.inj_drop_table_column(TABLE, "")
    assert table_column_mismatch(dirty)
    assert bench.GATES["broken_table"](dirty), "bench 的 gate 要走的就是这一条"


def test_列数判据不把正常表报成错():
    """判据宁可窄一点：只在同一张表内部列数不一致时才算。"""
    from app.harness.checks.blockcheck import table_column_mismatch

    assert not table_column_mismatch("正文里有个竖线 a|b 而已")
    assert not table_column_mismatch(TABLE + "\n\n| 甲 |\n|---|\n| 1 |\n")


def test_bench不再自己留一份列数判据():
    """**一份实现两个用途**（批 16）：bench 用它自验植入器、生产用它判产出。
    两边各写一份的话，「植入器植没植进去」和「生产判不判得出来」会各判各的
    ——而那正是这个 gate 存在的全部意义。"""
    src = pathlib.Path(bench.__file__).read_text(encoding="utf-8")
    assert "def table_column_mismatch" not in src
    assert "blockcheck.table_column_mismatch" in src


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


def _many(dim, clean_lvl, dirty_lvl, notes=("n1", "n2", "n3"), reps=3):
    """多篇 × 多次的一整块记录。**「抓住」这一档现在还要过 p 值**，
    而 n=1 篇 × 3 次时排列总数只有 C(6,3)=20、两侧 p 最小 0.10——
    拿一篇一次的数据去断言"抓住"，断言的是一件数学上不成立的事。"""
    out = []
    for n in notes:
        for rep in range(reps):
            out.append(_rec(P.id, n, "clean", dim, clean_lvl, rep=rep))
            out.append(_rec(P.id, n, "dirty", dim, dirty_lvl, rep=rep))
    return out


def test_掉一整档算抓住():
    rows = bench.summarize(_many("non_repetition", 2, 1), (P,))
    assert rows[0]["verdict"] == "抓住" and rows[0]["drop"] == 1.0
    assert rows[0]["p"] < bench.ALPHA and rows[0]["n_notes"] == 3
    assert rows[0]["n_calls"] == 18


def test_掉得够多但样本量不够时只能报掉了但不显著():
    """批 6 ⑥：38 条 probe 里 p ≥ 0.05 的有 20 行，**包括全部三条 n=1 行**。
    一篇一次的"掉了两档"跟噪声分不开，不许跟真抓住的行并排放在一张表里。"""
    rows = bench.summarize(_many("non_repetition", 2, 0, notes=("n1",), reps=3), (P,))
    assert rows[0]["drop"] == 2.0 and rows[0]["p"] >= bench.ALPHA
    assert rows[0]["verdict"] == "掉了但不显著"


def test_不显著不许报成没抓住():
    """"跟噪声分不开"和"一分不掉"是两件事，处理方式相反（前者补样本，后者改判词）。"""
    assert bench.apply_significance("抓住", 0.4) == "掉了但不显著"
    assert bench.apply_significance("没抓住", 0.4) == "没抓住"
    assert bench.apply_significance("抓住", 0.001) == "抓住"
    assert bench.apply_significance("抓住", None) == "抓住"


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


def test_拿去跟阈值比的必须是没四舍五入的掉分():
    """**台账批 11 M1：这条闸是反推补上的，补之前把 `_verdict` 改成拿
    `round(drop, 2)` 去比阈值，1380 条用例全绿。**

    而批 10 自己在台账里写过这条教训——批 9 报「掉 0.89 正好压在 `CAUGHT` 线上，
    抓住」，原始值其实是 0.888…，差 0.002。**那一批只修了读数、没留闸**，
    于是同一个坑换成代码的形态又活了一遍。

    下面这组数就是当时那一格：三篇里两篇掉满一档、一篇掉 2/3，
    平均 0.888…，显示成 0.89 跟 `CAUGHT` 一模一样。
    """
    recs = []
    for note, dirty in (("n1", [1, 1, 1]), ("n2", [1, 1, 1]), ("n3", [1, 1, 2])):
        for rep, lvl in enumerate(dirty):
            recs.append(_rec(P.id, note, "clean", "non_repetition", 2, rep=rep))
            recs.append(_rec(P.id, note, "dirty", "non_repetition", lvl, rep=rep))
    rows = bench.summarize(recs, (P,))
    assert rows[0]["drop"] == 0.89 == bench.CAUGHT, "这组数没落在阈值上，用例就白写了"
    assert rows[0]["p"] < bench.ALPHA, "p 不显著的话「抓住」会被改写成别的档，测不到这件事"
    assert rows[0]["verdict"] == "只动了一点", \
        "0.888… < 0.89，比阈值用的必须是原始值；报告里那个 0.89 是显示值"
    assert bench._verdict(2.0, 0.888) == "只动了一点"
    assert bench._verdict(2.0, 0.89) == "抓住"


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
    rows = bench.summarize(_many("non_repetition", 0, 2), (P,))
    assert rows[0]["verdict"] == "反着来了" and rows[0]["drop"] == -2.0


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
    assert bench.VERDICT_RANK.index("反着来了") > bench.VERDICT_RANK.index("没抓住")


def test_未跑排在没抓住反着来了后面():
    """批 7 ⑤：原来 `未跑` 排在它们前面，于是一个维度只要有一条 probe 没跑，
    它真正测出来的**失败就被静默吞掉**——表上写"未跑"，看着像"还没测"。"""
    assert bench.VERDICT_RANK[-1] == "未跑"
    rows = [{"dim": "d", "probe": "跑了", "verdict": "没抓住", "drop": 0.0,
             "clean": 2.0, "dirty": 2.0, "n_notes": 3},
            {"dim": "d", "probe": "没跑", "verdict": "未跑", "drop": None,
             "clean": None, "dirty": None, "n_notes": 0}]
    assert bench.roll_up(rows)[0]["probe"] == "跑了"


def test_被roll_up洗掉的失败行要单独报出来():
    """批 5 的台账只贴了 roll_up 之后那张表，**4 条「没抓住」被洗进了别的档**，
    其中样本量最大的一行（n=6 篇、掉 0.00）在进 git 的台账里一个字都看不到。"""
    rows = [{"dim": "d", "probe": "好", "verdict": "抓住", "drop": 1.0,
             "clean": 2.0, "dirty": 1.0, "n_notes": 3, "p": 0.001},
            {"dim": "d", "probe": "坏", "verdict": "没抓住", "drop": 0.0,
             "clean": 2.0, "dirty": 2.0, "n_notes": 6, "p": 1.0},
            {"dim": "e", "probe": "独", "verdict": "没抓住", "drop": 0.0,
             "clean": 2.0, "dirty": 2.0, "n_notes": 3, "p": 1.0}]
    washed = bench.washed_out(rows)
    # `d` 的失败被洗掉了要报；`e` 自己就是最终结论，不算被洗掉
    assert [r["probe"] for r in washed] == ["坏"]


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


# ------------------------------------------- as-deployed 到底像不像生产 ---
#
# 批 8 之前这一档是脚本里硬编的「长文两条给 spine/beats、六个 block 模式
# 什么都不给」。硬编的那份靠人记得跟生产同步——而生产那边**三样证据一样
# 都没传**（事实块 / block 前后文 / 用户那条指令），脚本抄的恰好是那个空账，
# 于是整张表里「as-deployed」这个词名不副实。
# 现在它由生产代码自己拼，下面四条钉住这件事。

def _note_with(content: str) -> dict:
    return {"id": "n1", "user_id": "terrence", "title": "众筹前后",
            "content": content, "spine": "", "beats": ""}


def test_as_deployed的上下文是生产那个函数拼的():
    """**接线闸**：生产把 `score_context.for_block` 撤掉、或者 bench 自己
    另写一份，这条就红。"""
    src = pathlib.Path(bench.__file__).read_text(encoding="utf-8")
    assert "score_context.for_block" in src and "score_context.material" in src
    assert "这一块前面的正文" not in src, \
        "bench 又把打分上下文的形状抄了一份——它只能由 score_context 说了算"


def test_bench的材料也排在正文之后():
    """批 16：材料块挪到 `[Content]` 之后。**bench 也必须挪**，否则
    `as-deployed` 这一列量的就不再是生产那份 prompt 了——而这次改的正是
    "同一份内容排在哪"，排布不一致等于整张灵敏度表换了一个自变量。

    判据盯的是 `run_one` 那一行真的调了拆分函数，**并且没有自己 pop 一份**
    （批 15 计划外发现 5：判据去读源码的时候，注释也是源码，所以匹配的是
    真实调用形态，不是一个能写进注释的子串）。
    """
    src = pathlib.Path(bench.__file__).read_text(encoding="utf-8")
    assert re.search(r"^\s*head, tail = score_context\.split_for_prompt\(",
                     src, re.M), "bench 的 run_one 没走生产那道拆分"
    assert re.search(r"^\s*ev = await evaluate\(.*tail_context=tail", src,
                     re.M | re.S), "拆出来了却没用 tail_context 传给 evaluate"
    assert not re.search(r"^\s*\w+\.pop\(score_context\.MATERIAL_KEY", src, re.M), \
        "bench 又自己拆了一份——排布只能由 score_context 说了算"


def test_block模式的as_deployed带上了前后文():
    """`fits_context` 判的是「跟周围合不合」，六个 block 模式在批 8 之前
    一个字的周围都没拿到（计划 4.1 / [EVAL] 问题一）。"""
    note = _note_with(NOTE + "\n\n" + CHART + "\n\n收尾这一段是后文。")
    probe = bench.Probe("eda", "chart-block", "chart_to_prose", ("has_charts",))
    subject = bench.SELECTORS[probe.selector](note)
    ctx = bench.production_context(probe, subject, note)
    joined = "\n".join(ctx.values())
    assert "第一节 众筹前的验证" in joined, "前文没进去"
    assert "收尾这一段是后文" in joined, "后文没进去"


def test_指令只给真的一定有指令的那三个模式():
    """`prompt` / `custom` 是用户亲手打的，`analysis` 的 task 本身就是一个
    问题；其余三个用户常常什么都不打，合成一句等于凭空多一个变量。"""
    note = _note_with(NOTE)
    def ctx_of(mode, selector):
        probe = bench.Probe(mode, selector, "answer_swap", ("follows_prompt",))
        subject = bench.SELECTORS[selector](note)
        return bench.production_context(probe, subject, note)
    assert "用户的指令" in ctx_of("prompt", "numeric-block")
    assert "用户的指令" in ctx_of("analysis", "numeric-block")
    assert "用户的指令" not in ctx_of("chart", "numeric-block")


def test_所有模式的as_deployed都带材料():
    """`loop._evaluate` 拼材料时**不分模式**。少拼一个模式，那个模式的
    `factual_grounding` / `data_grounding` 量出来的就还是旧世界的数。"""
    note = _note_with(NOTE)
    for mode, selector in (("note", "whole"), ("section", "whole-section"),
                           ("eda", "numeric-block"), ("prompt", "numeric-block")):
        probe = bench.Probe(mode, selector, "shift_dates", ("factual_grounding",))
        subject = bench.SELECTORS[selector](note)
        ctx = bench.production_context(probe, subject, note)
        assert "2026 年 3 月 15 日" in ctx.get("知识库事实", ""), f"{mode} 没拿到材料"


def test_真正发出去的那一格带的就是生产那份上下文():
    """**上面几条都是直接调 `production_context`，谁也没管 `build_tasks` 用不用
    它**——突变验第一轮就是这么漏的：把 `build_tasks` 里那一行改回
    `dict(subject.context)`（等于整个批 8 的测量口径退回批 7），155 条全绿。
    闸跑绿不等于闸有用：要盯的是**真的发给 `evaluate()` 的那个 context**。"""
    note = _note_with(NOTE + "\n\n" + CHART + "\n\n收尾这一段是后文。")
    probe = bench.Probe("eda", "chart-block", "chart_to_prose", ("has_charts",))
    tasks, _ = bench.build_tasks([note], (probe,), 1, set())
    assert tasks, "这篇上应该能建出格子"
    ctx = tasks[0].context
    assert "第一节 众筹前的验证" in "\n".join(ctx.values()), "发出去的那一格没带前后文"
    assert ctx.get("知识库事实"), "发出去的那一格没带材料"


def test_已经接进生产的证据不再留一份with_evidence():
    """留着就是同一份上下文跑两遍——而且两行数字一模一样，读表的人会以为
    「补了证据也没变化」。批 8 删掉的是事实块 / 前后文 / 指令那三样。"""
    left = {p.id for p in bench.PROBES if p.condition == "with-evidence"}
    assert left == {"note/whole/audit_voice/with-evidence"}, \
        f"with-evidence 这一档只该剩生产仍然不给的那一样（个人偏好）：{sorted(left)}"


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


# ============================== 植入器自验：28 个一个都不许没有闸 ==========
#
# **批 6 ⑤ 逼出来的**：审查把 `inj_drop_chart_series` 换成**恒等函数**
# （什么都不植入），44 条单测**全绿存活**——因为压根没有一条用例碰过那个植入器。
# 植入器是整张灵敏度表的承重墙，它没植入声称的缺陷，表上每一行都是空的，
# 而且**看不出任何症状**。所以下面按名单逐个过，正反两个方向都要断言。

# 标题和正文**不隔空行**、图表和表格夹在中间——真实笔记就是这个形状。
# 上一版 `inj_strip_specifics` 正是栽在这里：它按 `\n\n` 切段，然后把
# 「以 # 或 | 开头、或含 ``` 的段」整段留下，于是整节带日期的正文被当成
# 「标题段」原样保留，一张带 5 个日期的时间线原封不动。**旧夹具的标题和正文
# 之间有空行，所以这个失效模式在它身上根本不可能出现。**
TIGHT_NOTE = (
    "## 交付节点\n"
    "项目原定于 2026 年 6 月底出货，目前版本已改为 8 月 5 日。MP 最终时间为 7 月 29 日。\n"
    "首单 1 万台预计在 7 月底完成生产，按当时口径保守情景 1.5 万台。\n\n"
    "```mermaid\ntimeline\n"
    "    2026-03-15 : 版本冻结\n    2026-04-16 : EVT 手板\n"
    "    2026-06-15 : 10 台到货\n    2026-07-29 : MP\n    2026-08-05 : 出货\n```\n\n"
    "| 情景 | 销量 |\n|---|---|\n| 保守 | 1.5 万台 |\n| 中性 | 3 万台 |\n\n"
    "## 结论\n"
    "这说明交付安排已经排好，团队对此已经有共识，接下来照此推进即可。\n"
)

# 图 + 一段**真的点了图里某个节点的名**的正文。`covers_the_data` 的判词要的
# 就是这个形状：「句子里提到的分组要画全，the subject of the sentence is missing」。
NARRATED_CHART = (
    "从版本冻结到出货一共四个节点，其中 6 月 15 日 10 台到货之后才具备"
    "小范围对外可用与硬件联动的真实验证条件。\n\n"
    "```mermaid\ngraph LR\n"
    "A[3月31日 可对外讲清] --> B[4月16日 EVT 手板]\n"
    "B --> C[6月15日 10台到货]\nC --> D[8月5日 出货]\n```\n"
)

# 正文一个节点都没点名的图——上一版植入器在这种材料上照样"植入成功"，
# 而打分器判 2.0 是对的：**没东西可抓**。
ANONYMOUS_CHART = (
    "下面这张图把几件事串起来看，重点是节奏而不是某一个节点。\n\n"
    "```mermaid\ngraph LR\n甲[第一步] --> 乙[第二步]\n乙 --> 丙[第三步]\n丙 --> 丁[第四步]\n```\n"
)

HEDGED = (
    "## 现状\n"
    "目前大致可以确认三件事，其中两件仍需与会议记录核对。\n"
    "如果供应链不出意外，预计七月底可以完成生产，大约 1 万台。\n\n"
    "## 判断\n"
    "若按现在的排期推进，可能在八月初出货，尚不足以断定最终交付日期。\n"
    "这一判断依赖的材料并不完整，需补充一次访谈之后再确认。\n"
)

ACTIONABLE = (
    "## 现状\n"
    "三家中介的报价差得很远，最高和最低之间差了一百二十万。\n"
    "接下来要做的第一件事是把各自的判断依据摊开对齐。\n\n"
    "## 安排\n"
    "建议先约其中两家复看一次，需要同时把带看记录整理出来。\n"
    "下一步应当在两周内出一版可以对外的口径。\n"
)

DONOR = (
    "另一个主题的第一段：团队远程协作的沟通渠道要分层，紧急的事走电话，其余一律走异步，"
    "避免把所有人都拖进同一个会议里，这一条在扩张期尤其重要。渠道分层之后还要配一条"
    "响应时效的约定，否则异步会变成「永远没人回」，那比开会更耗人。时效约定也不必很严，"
    "把「当天内」和「两小时内」分开写清楚就够了，剩下的靠人自己判断，规则一多就没人记得住。\n\n"
    "另一个主题的第二段：文档沉淀的标准是「三个月后的新人能自己看懂」，所以每份文档都要"
    "写清楚背景和当时的取舍，而不是只留一个结论在那里。结论会过期，取舍不会——"
    "下一个人真正需要知道的是当时为什么没选另一条路。写得太全反而没人维护，"
    "所以宁可短一点，但背景那一段一定要留着，它是这份文档里最不会过期的部分，也是唯一一段值得后来人花时间读完的内容。\n"
)

# 每个植入器一份**它真的能施展的**材料。名单跟 `INJECTORS` 必须一一对上
# （下面有闸），新加一个植入器而不给夹具，测试直接红。
INJECTOR_FIXTURES: dict[str, tuple[str, str]] = {
    "duplicate_paragraph": (NOTE, ""),
    "off_spine_graft": (NOTE, DONOR),
    "drop_last_section": (NOTE, ""),
    "truncate_bodies": (NOTE, ""),
    "shift_dates": (NOTE, ""),
    "scramble_numbers": (NOTE, ""),
    "swap_section_bodies": (NOTE, ""),
    "heading_levels": (NOTE, ""),
    "double_ending": (NOTE, ""),
    "strip_specifics": (TIGHT_NOTE, ""),
    "audit_voice": (NOTE, ""),
    "placeholder": (NOTE, ""),
    "handwrite_mermaid": (CHART, ""),
    "break_mermaid_fence": (CHART, ""),
    "chart_to_prose": (CHART, ""),
    "duplicate_chart": (CHART, ""),
    "drop_mentioned_node": (NARRATED_CHART, ""),
    "chart_to_image": (CHART, ""),
    "drop_table_column": (TABLE, ""),
    "invent_table_cells": (TABLE, ""),
    "invent_statistic": (NOTE, ""),
    "strip_caveats": (HEDGED, ""),
    "strip_next_steps": (ACTIONABLE, ""),
    "heading_flood": (NOTE, ""),
    "lead_in": (NOTE, DONOR),
    "fabricate_specifics": (NOTE, ""),
    "answer_swap": (NOTE, DONOR),
    # 批 12：`NOTE` 里带「N 月 D 日」，把它改回被取代的那一版
    "use_superseded_date": (NOTE, ""),
}


def test_每个植入器都有一份夹具():
    """名单对不上就红。**新加一个植入器而没人验它，等于给整张表开了个洞。**"""
    assert set(INJECTOR_FIXTURES) == set(bench.INJECTORS)


def test_没有自验闸的植入器根本注册不进来():
    """闸放在构造函数里而不是测试里：测试只钉现在这 27 个，构造闸连以后新加的也拦得住。"""
    with pytest.raises(ValueError, match="没有任何自验闸"):
        bench.Injector("裸奔", lambda t, d: t + "x")


@pytest.mark.parametrize("name", sorted(INJECTOR_FIXTURES))
def test_植入器真的植入了它声称的那个缺陷(name):
    text, donor = INJECTOR_FIXTURES[name]
    inj = bench.INJECTORS[name]
    dirty, why = inj.mutate(text, donor)
    assert dirty and not why, f"{name} 在自己的夹具上就植不进去：{why}"


@pytest.mark.parametrize("name", sorted(INJECTOR_FIXTURES))
def test_把植入器换成什么都不做它的闸必须变红(name):
    """**这就是批 6 ⑤ 那次突变**：审查把一个植入器换成恒等函数，44 条单测全绿。
    这里反方向逐个验一遍——什么都不植入的"植入器"必须被自己的闸挡下来。"""
    text, donor = INJECTOR_FIXTURES[name]
    real = bench.INJECTORS[name]
    idle = bench.Injector(name, lambda t, d: t + "\n", gate=real.gate, verify=real.verify)
    dirty, why = idle.mutate(text, donor)
    assert not dirty and why, f"{name} 的闸挡不住一个什么都不做的植入器"


# ------------------------------------ ②：把带数字的句子全剔光，这次是真的 ---

def test_夹具本身就是真实形状_标题和正文不隔空行():
    """闸的前提：**夹具必须真的长成会触发那个失效模式的样子**，
    否则这条测试测的是另一份材料。"""
    assert "## 交付节点\n项目原定于" in TIGHT_NOTE          # 标题正文不隔空行
    old_style_skipped = [p for p in bench.paragraphs(TIGHT_NOTE)
                         if p.lstrip().startswith(("#", "|")) or "```" in p]
    assert len(old_style_skipped) >= 3, "夹具里要同时有标题段、表格段和围栏段"
    # 上一版会原样留下的那些具体材料，这份夹具里都在
    assert sum(len(re.findall(r"\d", p)) for p in old_style_skipped) >= 10


def test_去掉具体材料之后正文里一个数字都不剩():
    dirty = bench.inj_strip_specifics(TIGHT_NOTE, "")
    assert dirty is not None
    assert not bench.has_specific_material(dirty)
    # 上一版残留的正是这三样：标题段里的正文、整张时间线、整张表
    for leftover in ("2026-06-15", "7 月 29 日", "1.5 万台"):
        assert leftover not in dirty, f"{leftover} 还留在正文里"
    assert "## 交付节点" in dirty and "## 结论" in dirty    # 标题是结构，不动


def test_去掉具体材料删不动多少就不算植入():
    """砍不动的时候必须返回 None：拿一个没成形的"缺陷"去给维度定罪是最坏的一种错。"""
    assert bench.inj_strip_specifics("没有任何具体信息的一段话。" * 10, "") is None


def test_保留措辞和下一步也按行走():
    """跟 `strip_specifics` 同一条教训——上一版这两个也让 `#` / `|` 开头的段直通。"""
    d1 = bench.inj_strip_caveats(HEDGED, "")
    assert d1 and not bench.has_hedge(d1) and bench.ASSERTION_SENTENCE in d1
    d2 = bench.inj_strip_next_steps(ACTIONABLE, "")
    assert d2 and not bench.has_next_step(d2)


# ------------------------------- ③：真能造出 covers_the_data 缺陷的植入器 ---

def test_删掉的是正文点过名的那个节点():
    """判词原话：「句子里提到的分组要画全，**the subject of the sentence is
    missing**」。正文一个字不动，掉分只可能来自"图里少了它"。"""
    assert bench.mentioned_nodes(NARRATED_CHART) == [("C", "6月15日 10台到货")]
    dirty = bench.inj_drop_mentioned_node(NARRATED_CHART, "")
    assert dirty is not None
    chart = re.search(r"```mermaid\n.*?```", dirty, re.S).group(0)
    assert "10台到货" not in chart                       # 图里没了
    assert "6 月 15 日 10 台到货" in dirty                # 正文还在讲它
    assert bench.subject_missing_from_chart(NARRATED_CHART, dirty)


def test_正文没点名任何节点时不许硬来():
    """**批 6 ③ 就是这条**：上一版删掉图里第一条边，而三篇正文没有一篇提过那个节点——
    打分器判 2.0 是对的，根本没东西可抓。造不出缺陷就跳过，不许拿它去给维度定罪。"""
    assert bench.mentioned_nodes(ANONYMOUS_CHART) == []
    assert bench.inj_drop_mentioned_node(ANONYMOUS_CHART, "") is None


def test_成对自验在没植入时不给过():
    assert not bench.subject_missing_from_chart(NARRATED_CHART, NARRATED_CHART)
    # 删的是正文没提过的那个节点 → 不算造出了这个缺陷
    other = NARRATED_CHART.replace("A[3月31日 可对外讲清] --> B[4月16日 EVT 手板]\n", "")
    assert not bench.subject_missing_from_chart(NARRATED_CHART, other)


def test_covers_the_data只用带叙述的图块():
    """取材器选错，这一维就是在"没有句子提到它"的条件下被打分的——
    量出来的是语料不是判据（批 5 ⑦ 同一条教训）。"""
    for p in bench.PROBES:
        if "covers_the_data" in p.targets:
            assert p.selector == "chart-block-narrated", p.id
    note = {"id": "n", "user_id": "terrence", "title": "t",
            "content": NARRATED_CHART, "spine": "", "beats": ""}
    assert bench.pick_chart_narrated(note) is not None
    assert bench.pick_chart_narrated({**note, "content": ANONYMOUS_CHART}) is None


# ------------------------------------------- 图块：引子不许是围栏残片 ---
#
# 真实语料上唯一带 mermaid 的那篇（`06647b9c2031`）本身是坏的：全篇只有
# **3 个** ``` ，图前面那一段是 `]` 加一个游离的围栏收尾符（上一次生成漏掉的
# 残片）。下面这段夹具是那篇的形状。

BROKEN_FENCE_NOTE = (
    "## 节奏\n\n"
    "10 台到货后才具备 10 人小范围对外可用与硬件联动验证条件，合规评审要留出回滚时间。\n\n"
    "]\n```\n\n"
    "```mermaid\ngraph LR\nA[6月15日 10台到货] --> B[10人小范围对外可用]\n```\n\n"
    "### 后面还有正文\n\n招聘启动顺序跟着定义走。\n"
)


def _broken_note(content: str = BROKEN_FENCE_NOTE) -> dict:
    return {"id": "n", "user_id": "terrence", "title": "t", "content": content,
            "spine": "", "beats": ""}


def test_图块的引子不许是围栏残片():
    """**台账批 11 M4**：跟批 10 修的 `numeric-block` 同型——「命中块前面那一段」
    不一定是正文。取成围栏残片之后，交给打分器的 subject 开头是一个孤零零的
    ``` ，`chart_validity` 的干净版恒 0 分，报「无从判断」。
    **那是取材缺陷，不是"这篇没图"**，两者的处理方式完全相反。"""
    sub = bench.pick_chart_block(_broken_note())
    assert sub is not None
    assert not sub.text.startswith("]"), "引子取成了游离的围栏收尾符"
    assert sub.text.count("```") == 2, "只该有图自己那一对围栏"
    assert sub.text.startswith("10 台到货后"), "引子该是块前面那一段真正的正文"


def test_图块交出去的正文里围栏必须成对():
    """奇数个围栏 = 打分器看到的是半个代码块。这条比上面那条宽一档，
    是**症状**那一侧的闸：换一种取错法也照样红。"""
    for pick in (bench.pick_chart_block, bench.pick_chart_narrated):
        sub = pick(_broken_note())
        assert sub is not None, pick.__name__
        assert sub.text.count("```") % 2 == 0, f"{pick.__name__} 交出了奇数个围栏"


def test_带叙述的图块同样只认干净的正文段():
    """`covers_the_data` 判的是"句子里提到的分组画全了没有"——叙述里带着
    半个围栏，判的就不是那件事了。"""
    sub = bench.pick_chart_narrated(_broken_note())
    assert sub is not None and "```mermaid" in sub.text
    assert bench.mentioned_nodes(sub.text), "引子里得真的点过图里的名字"
    assert not sub.text.startswith("]") and sub.text.count("```") == 2


def test_挑不到干净引子时引子留空而不是拿残片凑():
    """拿不到跟拿错是两件事：拿错没有任何症状。"""
    only_junk = "]\n```\n\n```mermaid\ngraph LR\nA[甲] --> B[乙]\n```\n\n后面还有正文。\n"
    assert bench.clean_leads("]\n```") == []
    sub = bench.pick_chart_block(_broken_note(only_junk))
    assert sub is not None
    assert sub.text.startswith("```mermaid"), "没有干净引子就只交那一块"
    assert only_junk[sub.at:sub.at + 12] == sub.text[:12], "起点要指到块本身"


def test_引子是原文里逐字的那一段():
    """引子是重拼出来的，但**每一段都得在原文里逐字找得到**——
    取材器不许合成一句引子出来（跟 `pick_chart_narrated` 那条同一个纪律）。"""
    note = _broken_note()
    for pick in (bench.pick_chart_block, bench.pick_chart_narrated,
                 bench.pick_table_block):
        sub = pick(note)
        if sub is None:
            continue
        for para in sub.text.split("\n\n"):
            assert para.strip() in note["content"], f"{pick.__name__}: {para[:30]}"


# --------------------------------------- 表格块：最后一行不许落在匹配之外 ---

def test_表格块要包含最后一行():
    """批 7 撞出来的：`_TABLE_BLOCK` 原来写死行尾 `\\n`，正文结尾的那张表
    **最后一行整行落在匹配之外**——`drop_table_column` / `invent_table_cells`
    都只改到半张表，`table_column_mismatch` 也只数了半张。"""
    tail_table = "引子。\n\n| 甲 | 乙 |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"   # 结尾没换行
    m = bench._TABLE_BLOCK.search(tail_table)
    assert m and "| 3 | 4 |" in m.group(0)


# --------------------------------------------- ⑤：噪声标定与逐行 p 值 ---

def _noise_records(probe_id, dim, notes=("n1", "n2"), reps=6, seed=3):
    """clean 和 dirty 抽自**同一个分布**——真值掉分为 0 的一批格子。"""
    import random as _r
    rng = _r.Random(seed)
    out = []
    for n in notes:
        for rep in range(reps):
            for arm in ("clean", "dirty"):
                out.append(_rec(probe_id, n, arm, dim, rng.choice([0, 1, 2]), rep=rep))
    return out


def test_纯噪声下那条线明显大于零():
    """批 6 ⑥：审查量出**纯噪声下 |掉分| ≥ 0.5 的概率就有 10.1%**，
    「掉 ≥ 半档算抓住」那条线是拍的。这里钉住"标定出来的线必须比 0 大得多"，
    以及标定函数确实在报那个 10% 量级的数。"""
    calib = bench.calibrate_threshold(_noise_records(P.id, "non_repetition"), (P,),
                                      resamples=200)
    assert calib["n_rows"] == 1 and calib["n_samples"] == 200
    assert calib["threshold"] > 0.2
    assert 0.0 < calib["p_over_half"] < 0.5


def test_那条线是可以被调用方换掉的():
    """线本身是数据，不是常量信仰。语料换了要能重新标定，也要能验"换了会怎样"。"""
    recs = _many("non_repetition", 2, 1)
    assert bench.summarize(recs, (P,), caught=0.5)[0]["verdict"] == "抓住"
    assert bench.summarize(recs, (P,), caught=1.5)[0]["verdict"] == "只动了一点"


def test_p值算出来是确定的():
    """这张表要进台账，同一份日志每次必须算出同一个 p。"""
    recs = _many("non_repetition", 2, 1)
    assert bench.summarize(recs, (P,))[0]["p"] == bench.summarize(recs, (P,))[0]["p"]


def test_p值永远大于零():
    """`(命中 + 1) / (重排次数 + 1)`——**"p = 0" 是不存在的**，
    报 0 会让读者以为这行铁得不能再铁。"""
    assert bench.permutation_p([([2, 2, 2], [0, 0, 0])] * 4, resamples=200) > 0


def test_同一篇之内打乱而不是跨篇():
    """跨篇打乱会把"篇与篇之间本来就差一截"当成噪声算进去，p 会假性变小。
    这里给两篇：一篇整体高、一篇整体低，但**篇内 clean/dirty 一分不差**——
    真值掉分为 0，p 必须很大。"""
    recs = ([_rec(P.id, "高", arm, "non_repetition", 2, rep=r)
             for arm in ("clean", "dirty") for r in range(3)]
            + [_rec(P.id, "低", arm, "non_repetition", 0, rep=r)
               for arm in ("clean", "dirty") for r in range(3)])
    assert bench.summarize(recs, (P,))[0]["p"] > 0.5


# --------------------------------- 改了植入器之后，旧分数不许混进新表 ---

def test_格子的身份里带正文指纹():
    """批 7 实施中撞出来的坑（计划里没写）：老的 key 是
    `笔记|probe|arm|重复次数`，改完植入器之后同一个 key 指向的已经是**另一段正文**，
    而断点续跑只看 key——"修好的植入器"和"没修的旧分数"会被拼进同一张表，
    **毫无症状**。"""
    a = bench.cell_key("n1", "p", "dirty", 0, "植入前的正文", {})
    b = bench.cell_key("n1", "p", "dirty", 0, "植入后的正文", {})
    assert a != b and a.rsplit("|", 1)[0] == b.rsplit("|", 1)[0]


def test_上下文变了也算另一个格子():
    """`with-evidence` 那一档改的是 context 而不是正文——它一样得算新格子。"""
    a = bench.cell_key("n1", "p", "clean", 0, "同一段正文", {})
    b = bench.cell_key("n1", "p", "clean", 0, "同一段正文", {"知识库事实": "[F1] …"})
    assert a != b


def test_复制的那一段要插在最后一段之前而不是它第一次出现的地方():
    """批 7 撞出来的：`replace(tail, ..., 1)` 换的是**第一次**出现。
    `06647b9c2031` 那篇里最后一段的文字在正文中段也出现过，于是复制品被塞进了
    别人的段落中间，拼成一段四不像——「逐字复制了一整段」这句话就不成立了。"""
    repeated_tail = "收尾这句话。"
    text = ("第一段正文足够长，长到能被选成被复制的那一段。" * 6 + "\n\n"
            + "这一段的开头先说点别的。" + repeated_tail + "这一段中间也有同一句话。\n\n"
            + "第三段也要有点内容，凑够四段。" * 4 + "\n\n"
            + repeated_tail)
    dirty = bench.inj_duplicate_paragraph(text, "")
    assert dirty is not None
    src = max(bench.paragraphs(text)[:-1], key=len)
    # 复制品必须**自成一段**，而不是被拼进别人段落的中间
    assert bench.paragraphs(dirty).count(src) == 2
    assert bench._v_duplicate_paragraph(text, dirty, "")


def test_排列检验必须在同一篇之内打乱():
    """跨篇打乱会把「篇与篇之间本来就差一截」当成噪声算进去，p 值就跟"篇的基线"
    绑在一起了。这里钉的是不变性：把某一篇的**两臂同时**加一个常数
    （它的掉分一点没变），p 必须一点不变。跨篇打乱做不到这件事。"""
    base = [([2, 2, 2], [1, 1, 1]), ([2, 2, 2], [1, 1, 1])]
    shifted = [([2, 2, 2], [1, 1, 1]), ([5, 5, 5], [4, 4, 4])]
    assert bench.permutation_p(base, resamples=800) == \
        bench.permutation_p(shifted, resamples=800)


# ================================================== 批 10：测量完整性 ===
#
# 两条都是「量错了东西」而不是「量出了坏结果」——这一类错误的共同特征是
# **表照出、数照有、结论照下**，只有内容是错的。

def test_取材器挑的块定位得回原文():
    """批 10 的根：取材器把一节重新拼成 `标题 + "\\n" + 正文`，比原文少一个
    换行，于是 `surrounding()` 里那句 `find()` 一律落空，落进「就当它在正文
    中间」的兜底——`after` 恒为空、`before` 是错的那半篇。真实语料上
    `numeric-block` 三篇全中、`chart-block` 中一篇。"""
    note = _note_with(NOTE + "\n\n" + CHART + "\n\n收尾这一段是后文。")
    for name in ("numeric-block", "chart-block", "chart-block-narrated",
                 "table-block", "paragraph"):
        subject = bench.SELECTORS[name](_note_with(NOTE + "\n\n" + CHART
                                                   + "\n\n" + TABLE + "\n\n收尾。")) \
            if name in ("table-block",) else bench.SELECTORS[name](note)
        if subject is None:
            continue
        assert subject.at >= 0, f"{name} 没报自己在原笔记里的位置"


def test_数字最密那一块优先挑后面还有正文的():
    """台账批 9 ③：这一档挑的块后面恒为空，于是 `fits_context` /
    `actionable` / `numbers_from_tools` / `honest_caveats` /
    `answers_the_question` / `states_limits` **六个维度是在只给一半上下文的
    条件下被测的**。"""
    note = _note_with(NOTE)
    subject = bench.SELECTORS["numeric-block"](note)
    assert subject is not None
    _before, after = bench.surrounding(subject, note)
    assert after.strip(), "挑中的块后面又是空的"


def test_整篇只有末节有数时照实取不硬凑():
    """那一篇上「后面没有正文」是关于**这篇笔记**的事实，不是取材偏差。
    硬凑一个不在文末的块，量出来的就不是生产那一刻的样子了。"""
    note = _note_with("## 开头\n\n这一节没有任何数目字。\n\n"
                      "## 末节\n\n1 2 3 4 5 6 7 8 个数字都在这里。\n")
    subject = bench.SELECTORS["numeric-block"](note)
    assert subject is not None and "末节" in subject.text


def test_前后文用的是块的真实位置():
    note = _note_with(NOTE)
    subject = bench.SELECTORS["numeric-block"](note)
    before, after = bench.surrounding(subject, note)
    assert subject.text not in before and subject.text not in after, \
        "块自己被算进了它的前后文"
    assert before + subject.text + after == note["content"] or \
        (before + note["content"][len(before):]) == note["content"]


def test_定位不到时宁可把前后文记成空():
    """编一个位置出来，`fits_context` 就会去罚一段它根本没见过的上下文。"""
    note = _note_with(NOTE)
    before, after = bench.surrounding(bench.Subject("这段话根本不在这篇笔记里面出现过"), note)
    assert (before, after) == ("", "")


# ---------------------------------------------- 前置条件（批 9 ② 的修法）---

def _pre_probe(**kw):
    return bench.Probe("note", "whole", "strip_specifics", ("material_use",),
                       precondition=lambda s, n, c: kw["ok"],
                       precondition_label="材料块非空")


def _rows(pre_true: list[tuple[int, int]], pre_false: list[tuple[int, int]],
          probe) -> list[dict]:
    """`[(干净分, 植入分)]` → 日志行。每一对算一篇。"""
    out = []
    for i, (group, pre) in enumerate(((pre_true, True), (pre_false, False))):
        for j, (c, d) in enumerate(group):
            note = f"n{i}{j}"
            out.append({"key": f"k{i}{j}c", "note": note, "probe": probe.id,
                        "arm": "clean", "rep": 0, "pre": pre,
                        "scores": {"material_use": c}})
            out.append({"key": f"k{i}{j}d", "note": note, "probe": probe.id,
                        "arm": "dirty", "rep": 0, "pre": pre,
                        "scores": {"material_use": d}})
    return out


def test_条件没成立的格子不进掉分均值():
    """台账批 9 ②：`material_use` 整行掉 0.67（"只动了一点"），按材料块空不空
    拆开是「非空 3 篇掉 0.89」＋「为空 1 篇掉 0.00」。**不分组就是把"条件没
    出现"和"判据不灵"算进同一个均值**，而这两件事的处理方式完全相反。"""
    probe = _pre_probe(ok=True)
    records = _rows([(2, 1), (2, 1), (2, 1)], [(2, 2)], probe)
    rows = bench.summarize(records, (probe,), resamples=200)
    main = [r for r in rows if r["verdict"] != bench.UNMET]
    unmet = [r for r in rows if r["verdict"] == bench.UNMET]
    assert len(main) == 1 and main[0]["drop"] == 1.0 and main[0]["n_notes"] == 3
    assert len(unmet) == 1 and unmet[0]["n_notes"] == 1 and unmet[0]["drop"] is None


def test_条件没成立的行不参与一维的最终结论():
    """它既不能证明判据好，也不能证明判据坏。让它进来会在两个方向上都撒谎。"""
    probe = _pre_probe(ok=True)
    rows = bench.summarize(_rows([(2, 0), (2, 0)], [(2, 2), (2, 2)], probe),
                           (probe,), resamples=200)
    rolled = bench.roll_up(rows)
    assert len(rolled) == 1 and rolled[0]["verdict"] != bench.UNMET
    # 条件成立的那两篇掉满一整档；混进条件没成立的两篇就只剩一半
    assert rolled[0]["n_notes"] == 2 and rolled[0]["drop"] == 2.0


def test_没声明前置条件的probe恒成立():
    """默认 False 会让整张表静默空掉一半，而空表看起来跟"还没跑"一样。"""
    probe = bench.Probe("note", "whole", "strip_specifics", ("material_use",))
    note = _note_with(NOTE)
    assert probe.holds(bench.SELECTORS["whole"](note), note, {}) is True


def test_材料块为空的那一格判成条件没成立():
    """`_MATERIAL_USE` 判词第一句：「只在【知识库事实】块里**确实给了材料**时
    才判这一项，没给材料就算达标」——空材料时判 2.0 是**判词规定的正确行为**。"""
    note = _note_with(NOTE)
    subject = bench.SELECTORS["whole"](note)
    assert bench._pre_has_material(subject, note, {}) is False
    assert bench._pre_has_material(subject, note, {"知识库事实": "- [F1] 甲"}) is True


def test_前置条件能在报告时重算():
    """**不重算就得先再花一次全量评测的钱**：批 9 那 396 格的日志里没有这一列。"""
    note = _note_with(NOTE)
    probe = [p for p in bench.PROBES if p.precondition is not None][0]
    pre_map = bench.precondition_map([note], (probe,))
    assert (note["id"], probe.id) in pre_map
    records = [{"key": "k", "note": note["id"], "probe": probe.id,
                "arm": "clean", "rep": 0, "scores": {"material_use": 2}}]
    bench.annotate_preconditions(records, pre_map)
    assert "pre" in records[0]


def test_跑那一格时记下的前置条件不被重算覆盖():
    """当场记下的是事实，重算的是推断——两者冲突时以当场那份为准。"""
    records = [{"key": "k", "note": "n1", "probe": "p", "pre": False, "scores": {}}]
    bench.annotate_preconditions(records, {("n1", "p"): True})
    assert records[0]["pre"] is False


def test_前置条件不进格子的身份():
    """它不改变递给打分器的任何东西。进了 key 只会让跑过的格子全部作废重跑。"""
    note = _note_with(NOTE)
    probe = bench.Probe("note", "whole", "duplicate_paragraph", ("non_repetition",),
                        precondition=lambda s, n, c: True, precondition_label="恒真")
    tasks, skips = bench.build_tasks([note], (probe,), 1, set())
    assert tasks, skips
    same = bench.cell_key(note["id"], probe.id, tasks[0].arm, 0,
                          tasks[0].text, tasks[0].context)
    assert tasks[0].key == same


def test_末节数字更密时也不挑末节():
    """**这一条是上面那条的突变闸**：把「优先挑后面还有正文的」撤掉，
    取材器就会去挑数字最密的末节，而末节后面什么都没有——六个维度又回到
    「只给一半上下文」的条件下（台账批 9 ③）。"""
    note = _note_with("## 前面这一节\n\n2026 年 3 月 15 日首单 1.5 万台，"
                      "中性 3 万台，乐观 10 万台。\n\n"
                      "## 中间这一节\n\n这一节是给末节垫后文用的，"
                      "写得长一点好让它够得上门槛：这里讲的是承接那批支持者的做法，"
                      "以及发货之后怎么收集反馈。\n\n"
                      "## 末节\n\n1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 个数字全在这。\n")
    subject = bench.SELECTORS["numeric-block"](note)
    assert subject is not None and "前面这一节" in subject.text, \
        "又去挑末节了——那一档的后文恒为空"


# ------------------------- 被取代的事实：这套里唯一会改材料的东西（批 12）---
#
# `middleware/supersede.py` 是批 10 唯一会改材料内容的改动，交出去的时候
# **零灵敏度覆盖**（台账批 11 H2）。下面钉的是这条 probe 立得住：
# 它量的是「正文用了一条**有出处但已经作废**的事实」，而不是别的什么。

SUPERSEDE_PROBE = next(p for p in bench.PROBES if p.injector == "use_superseded_date")


def _dated_note() -> dict:
    return {"id": "n", "user_id": "terrence", "title": "节奏",
            "content": NOTE, "spine": "", "beats": ""}


def test_更正那条probe的材料里真有一行生产写的更正():
    note = _dated_note()
    sub = bench.SELECTORS[SUPERSEDE_PROBE.selector](note)
    ctx = bench.production_context(SUPERSEDE_PROBE, sub, note)
    block = ctx[bench.score_context.MATERIAL_KEY]
    assert bench.score_context.NOTICE_MARK in block
    assert "这条取代了" in block and bench.SUPERSEDED_OLD_ID in block
    assert SUPERSEDE_PROBE.holds(sub, note, ctx)


def test_更正行的格式必须由生产那个函数写():
    """脚本另抄一份格式，生产一改这条 probe 量的就不是那行字了——
    跟 `as-deployed` 的上下文必须由 `score_context` 拼是同一条纪律。"""
    import pathlib as _p

    src = _p.Path(bench.__file__).read_text(encoding="utf-8")
    assert "prod_supersede.replacement_line(" in src
    from app.harness.middleware import supersede as prod

    note = _dated_note()
    sub = bench.SELECTORS[SUPERSEDE_PROBE.selector](note)
    facts = bench.superseded_material(sub, note, [])
    sent = facts[0].split("] ", 1)[1].replace(*bench.superseded_pair(sub.text)[::-1])
    assert facts[1] == prod.replacement_line(bench.SUPERSEDED_NEW_ID, sent, "",
                                             bench.SUPERSEDED_OLD_ID)


def test_植入臂写的那个日期在材料里逐字找得到():
    """**这条是这个 probe 跟 `shift_dates` 的全部区别。** 改出来的日期要是
    材料里根本没有，判据判它编造就行了，量的就不是「作废的那一条」这件事。"""
    note = _dated_note()
    sub = bench.SELECTORS[SUPERSEDE_PROBE.selector](note)
    dirty, why = bench.INJECTORS[SUPERSEDE_PROBE.injector].mutate(sub.text, "")
    assert not why, why
    now, older = bench.superseded_pair(sub.text)
    block = bench.production_context(SUPERSEDE_PROBE, sub, note)[
        bench.score_context.MATERIAL_KEY]
    assert older in dirty and now not in dirty
    assert older in block, "被取代的那一版必须在材料里，否则这条 probe 退化成 shift_dates"
    assert now in block, "现行那一版也得在——生产里两条都会被取出来，这正是它要治的"


def test_两臂的材料一模一样_只有正文不同():
    """材料按**干净版**摘（`build_tasks` 里两臂共用一份 ctx）。两臂的材料不一样的话，
    掉分里混进了「材料变了」这个变量，那张表就不是在量判据。"""
    note = _dated_note()
    sub = bench.SELECTORS[SUPERSEDE_PROBE.selector](note)
    tasks, _ = bench.build_tasks([note], (SUPERSEDE_PROBE,), 1, set())
    ctxs = {t.arm: t.context for t in tasks}
    assert ctxs["clean"] == ctxs["dirty"]
    texts = {t.arm: t.text for t in tasks}
    assert texts["clean"] != texts["dirty"]


def test_更正行被切掉时这一格报条件没出现而不是判据不灵():
    """H2 的另一半：更正行要是被 `score_context.material` 的截断切掉，
    这一格量的是「材料里压根没有更正」，那跟「判据不看更正」是两件事。"""
    note = _dated_note()
    sub = bench.SELECTORS[SUPERSEDE_PROBE.selector](note)
    assert not SUPERSEDE_PROBE.holds(sub, note, {bench.score_context.MATERIAL_KEY:
                                                 "- 一条没有更正的普通材料"})


def test_别的probe的材料一个字都没动():
    """`material` 钩子只有这一条 probe 用。它要是漏进了别的 probe，
    整张表的材料就都变了，而格子指纹会让旧数据**静默**作废重跑。"""
    users = [p.id for p in bench.PROBES if p.material is not None]
    assert users == [SUPERSEDE_PROBE.id]


# ------------- 报告参数 + 日志分类：两张表能不能比，先看它们是不是同一个 n ---

def _one_note() -> dict:
    return {"id": "n1", "user_id": "terrence", "title": "节奏",
            "content": NOTE, "spine": "", "beats": ""}


def test_重复次数排在外面的行不许跟指纹对不上的混成一个数():
    """**台账批 11 H3 点名的那处误报。** 拿默认 `--repeats 3` 去读一份按
    `--repeats 5` 跑出来的日志，rep=3 / rep=4 那些行身份完全没问题，
    只是这次没要它们——上一版跟「取材器改过、指纹对不上」的行一起报成
    「对不上现在的语料/植入器」。实测这一处是 **328 行有效数据**。

    两类的处理方式相反：前者调回 `--repeats` 就在，后者必须重跑。
    """
    note = _one_note()
    probes = (SUPERSEDE_PROBE,)
    cells5, _ = bench.build_tasks([note], probes, 5, set())
    cells3, _ = bench.build_tasks([note], probes, 3, set())
    log = [{"key": t.key, "probe": t.probe_id, "note": t.note_id,
            "arm": t.arm, "rep": t.rep, "scores": {"factual_grounding": 2}}
           for t in cells5]
    split = bench.classify_stale(log, cells3)
    assert len(split["used"]) == len(cells3)
    assert len(split["out_of_repeats"]) == len(cells5) - len(cells3) > 0
    assert split["mismatched"] == []


def test_指纹对不上的行仍然报作废():
    """取材器 / 植入器一改，同一个 key 指向的已经是另一段正文了——
    这种行混进统计是**毫无症状**的（批 7 撞出来的那个坑）。"""
    note = _one_note()
    cells, _ = bench.build_tasks([note], (SUPERSEDE_PROBE,), 1, set())
    log = [{"key": bench.cell_key("n1", SUPERSEDE_PROBE.id, "clean", 0,
                                  "另一段正文", {}), "probe": SUPERSEDE_PROBE.id}]
    split = bench.classify_stale(log, cells)
    assert len(split["mismatched"]) == 1 and split["out_of_repeats"] == []


def test_only筛小范围时别的probe的行不许报成作废():
    """**同一个形状第三次。** 批 12 把「重复次数排在外面」跟「指纹对不上」
    分开报，批 13 跑 `--only chart-block` 又中一次：报告头印着
    「**1548** 行指纹对不上现在的取材/植入器（真作废）」——那是整份日志，
    真作废的只有 973 行。`--only` 把 `all_cells` 一起筛小了，别的 probe 的
    每一行都掉进 `mismatched`。照这个数去重跑等于把整张表白烧一遍。

    没传 `--only` 时这一类必须恒为空——否则就是把好行误判成废行的反向误伤。
    """
    note = _one_note()
    other = [p for p in bench.PROBES if p.id != SUPERSEDE_PROBE.id][0]
    both, _ = bench.build_tasks([note], (SUPERSEDE_PROBE, other), 1, set())
    log = [{"key": t.key, "probe": t.probe_id} for t in both]

    only_one, _ = bench.build_tasks([note], (SUPERSEDE_PROBE,), 1, set())
    split = bench.classify_stale(log, only_one, {SUPERSEDE_PROBE.id})
    assert split["mismatched"] == [], "别的 probe 的行不是作废，是不在本次范围里"
    assert len(split["out_of_scope"]) == len(both) - len(only_one) > 0

    # 不筛的时候这一类必须是空的：行为跟批 12 一字不差。
    split_all = bench.classify_stale(log, both)
    assert split_all["out_of_scope"] == [] and split_all["mismatched"] == []
    assert len(split_all["used"]) == len(both)


def test_一格都取不出来的probe_它的旧行仍然算作废():
    """**范围判据宁可窄一点。** 第一版拿「有没有 cells」当范围，于是一条
    probe 在这批语料上一格都取不出来时（批 12 修完取材器之后的
    `chart-block-narrated` 就是这样），它那些**真作废**的旧行被报成
    「去掉 --only 就在」——反向误伤，比原来那个错更难发现。
    范围必须由调用方显式传 `--only` 选中的那些 id。
    """
    note = _one_note()
    other = [p for p in bench.PROBES if p.id != SUPERSEDE_PROBE.id][0]
    both, _ = bench.build_tasks([note], (SUPERSEDE_PROBE, other), 1, set())
    log = [{"key": t.key, "probe": t.probe_id} for t in both]
    only_one, _ = bench.build_tasks([note], (SUPERSEDE_PROBE,), 1, set())
    # 范围里两条 probe 都在（没传 --only），但 `other` 这次一格都没取出来
    split = bench.classify_stale(log, only_one, {SUPERSEDE_PROBE.id, other.id})
    assert split["out_of_scope"] == []
    assert len(split["mismatched"]) == len(both) - len(only_one) > 0


def test_报告头把三类没进统计的行分开报():
    """三类的处理方式不一样：调 `repeats` / 去掉 `only` / 真重跑。
    混成一个数，人只会当成「日志脏了」，然后去重跑本来好好的行。"""
    out = _report()
    assert "重复次数排在本次 `repeats` 之外" in out
    assert "不在本次 `only` 选中的范围里" in out
    assert "指纹对不上现在的" in out


def _report(**over) -> str:
    params = {"repeats": 5, "notes": 5, "only": "（全部）", "caught": bench.CAUGHT,
              "alpha": bench.ALPHA, "perm_resamples": bench.PERM_RESAMPLES,
              "seed": bench.PERM_SEED}
    params.update(over)
    return bench.render_report([], [], [_one_note()], [], [], kept_total=1,
                               params=params, stale={"used": [], "mismatched": [],
                                                     "out_of_repeats": [1, 2],
                                                     "out_of_scope": [3]})


def test_报告头必须写着这次跑的repeats():
    """不记 `repeats`，两张表并排放进台账就没人看得出「显著了」是修好接线
    买的还是多跑两次买的——批 10 的头条正是这么混掉的。"""
    out = _report(repeats=5)
    assert "| `repeats` | 5 |" in out
    assert "repeats" in out.split("## 语料")[0], "得写在报告头，不是埋在末尾"
    assert "5" in _report(repeats=5) and "| `repeats` | 3 |" in _report(repeats=3)


def test_报告头缺参数就不许出表():
    """缺了当场炸，好过出一张看不出 n 的表——那张表会被当成可比的。"""
    with pytest.raises(AssertionError):
        bench.render_report([], [], [], [], [], params={"notes": 5})


def test_报告头要把两类没进统计的行分开报():
    out = _report()
    assert "重复次数排在本次 `repeats` 之外" in out and "数据仍然有效" in out


def test_报告里要标明材料那几维是上界():
    """**台账批 11 H4。** 材料是从干净正文摘的，打分器拿到的是正文原句的
    逐字副本——那四维测在最有利的条件下。数字照发，但不许当成生产灵敏度。"""
    out = _report()
    head = out.split("## 灵敏度（逐条 probe")[0]
    assert "上界" in head and "derived_facts" in head
    for dim in ("material_use", "factual_grounding", "numbers_from_tools",
                "data_grounding"):
        assert dim in head, dim


# ------------------------------------------- checklist 那一档（批 17 / 6.1）---
#
# 这一档改的**不是给打分器看什么**（那是 `with-evidence`），而是**拿什么去判**：
# 同一份正文、同一份上下文，维度表后面多接几条现场生成的二元条目。
# 所以它和自己的 `as-deployed` 兄弟行必须严格配对，否则前后对照比的是两件事。

def test_checklist那一档跟as_deployed严格配对():
    pairs = {(p.mode, p.selector, p.injector, p.targets)
             for p in bench.PROBES if p.condition == "as-deployed"}
    for p in bench.PROBES:
        if p.condition == bench.CHECKLIST_CONDITION:
            assert (p.mode, p.selector, p.injector, p.targets) in pairs, (
                f"{p.id} 没有对照行——单独一条 checklist 行没有任何可比的对象")


def test_checklist那一档只在指令类两个模式上():
    """别的模式在生产里根本不挂这个 middleware，给它们量等于量一个不存在的配置。"""
    modes_ = {p.mode for p in bench.PROBES if p.condition == bench.CHECKLIST_CONDITION}
    assert modes_ <= {"prompt", "custom"}


def test_bench取指令走的是生产那个键名():
    """**批 16 的形状**：两处各写一份字符串，一处改名另一处静默取到空串——
    而空串跟「用户没打指令」长得一模一样，这一档会安静地退化成 as-deployed。"""
    from app.harness import score_context

    ctx = score_context.for_block(prompt="随便一条指令")
    assert score_context.PROMPT_KEY in ctx


def test_同一条指令只生成一次清单(monkeypatch):
    """生成是要花钱的，而且两臂必须用**同一张清单**——重生成一次，
    clean 和 dirty 就在拿两套判据比分数。"""
    import asyncio

    from app.harness import adapter

    calls = {"n": 0}

    class LLM:
        async def complete(self, messages, **kw):
            calls["n"] += 1
            return '{"items": [{"check": "围绕原主题写", "quote": "按原主题"}]}'

    monkeypatch.setattr(adapter, "AppLLMClient", lambda *a, **kw: LLM())
    monkeypatch.setattr(bench, "_CHECKLIST_CACHE", {})
    monkeypatch.setattr(bench, "_CHECKLIST_LOCK", None)

    async def go():
        a = await bench.checklist_dims("按原主题把这一段写清楚")
        b = await bench.checklist_dims("按原主题把这一段写清楚")
        return a, b

    a, b = asyncio.run(go())
    assert calls["n"] == 1
    assert [d.name for d in a] == ["checklist_1"] == [d.name for d in b]
    assert a[0].binary is True                  # 条目一律二元（[IND] §6②）
    assert "围绕原主题写" in a[0].guidance       # 判词里带着条目原文


def test_没有指令就不生成(monkeypatch):
    import asyncio

    monkeypatch.setattr(bench, "_CHECKLIST_CACHE", {})
    assert asyncio.run(bench.checklist_dims("  ")) == ()
