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


# ============================== 植入器自验：27 个一个都不许没有闸 ==========
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
