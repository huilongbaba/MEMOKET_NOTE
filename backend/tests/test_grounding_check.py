"""「有没有真的用上检索回来的材料」这条确定性检查的测试。

这是整晚测出来最深的一个缺口：评分六个维度里没有一条在衡量这件事，
factual_grounding 只查"有没有矛盾/编造"，通用常识既不矛盾也不编造，
所以一篇零知识库内容的文章可以六维全 2、判定 complete。
"""

from __future__ import annotations

from app.grounding_check import fact_usage, grounding_gap

FACTS = [
    "[2026-03-12] 手板厂之前打的那架外观结构样 2300 块钱一套。",
    "[2026-05-01] 五月份 PVE 的 DV 批只备一两百 KIT，做个五十、一百套。",
    "[2026-03-11] Speaker B 说明设立美国子公司的原因是业务涉及 AI 硬件及美国市场上的数据。",
]

# 真实观测到的失败形态：查了 6 次知识库，写出来的是教科书式成本分类
GENERIC = """## 定价要覆盖哪些成本

物料成本之外，隐性成本才是把盈利变成亏损的机制：配件损耗与备件、渠道报备与
合规费用、汇率波动与结算滞后、售后与退换、以及项目管理与沟通的工时摊销。
"""

GROUNDED = """## 定价要覆盖哪些成本

手板厂之前打的那架外观结构样 2300 块钱一套，摊到首批五十套就是 46 元一套。
五月份 PVE 的 DV 批只备一两百 KIT，这个量级最容易把成本边界算窄。
"""


def test_generic_writing_is_caught_even_though_it_is_not_wrong():
    """通用常识既不矛盾也不编造——其他维度全都抓不到它，只有这条能。"""
    n, _ = fact_usage(GENERIC, FACTS)
    assert n == 0
    gap = grounding_gap(GENERIC, FACTS)
    assert gap and "一条都没用上" in gap
    assert "2300" in gap or "手板" in gap        # 诊断里带上查到的是什么


def test_material_actually_written_in_counts_as_used():
    n, used = fact_usage(GROUNDED, FACTS)
    assert n >= 2
    assert any("2300" in u for u in used)
    assert grounding_gap(GROUNDED, FACTS) == ""


def test_no_facts_retrieved_is_not_a_failure():
    """知识库里本来就没有相关内容时写得抽象是正常的，不该扣分——
    factual_grounding 早期版本就犯过这个错（给"没用完检索结果"扣分），
    反而诱发了编造。"""
    assert grounding_gap(GENERIC, []) == ""
    assert fact_usage(GENERIC, []) == (0, [])


def test_a_single_shared_word_is_not_enough():
    """都出现"成本"两个字说明不了什么，得有几个特征词同时重合。"""
    facts = ["[2026-03-12] 渠道报备的成本构成是时间加文件加合规改动。"]
    assert fact_usage("这一节讲成本。", facts)[0] == 0


def test_numbers_are_the_strongest_signal():
    facts = ["[2026-04-10] 硬件 4 月 10 号出来，首批 50 套。"]
    assert fact_usage("硬件 4 月 10 号出来，首批 50 套要盯紧。", facts)[0] == 1


def test_metadata_prefix_and_suffix_do_not_count_as_usage():
    """事实前后的元信息（日期前缀、说话人后缀）是我们自己加的，
    不能因为正文里恰好出现日期就算"用上了"。"""
    facts = ["[2026-03-12] 完全无关的内容。\n    （2026-03-12 · speaker b · plan）"]
    assert fact_usage("2026-03-12 这天没什么特别的。", facts)[0] == 0


def test_material_use_override_does_not_mutate_a_frozen_evaluation():
    """Evaluation 是 frozen dataclass，压低 material_use 必须用 replace 造新的。

    踩过：直接 `evaluation.status = "continue"` 抛 FrozenInstanceError，而且是
    在 SSE 生成器里抛的——整个 run 当场断掉、连接被硬中断，用户看到的是
    "跑了一下什么都没改"。pytest 抓不到，因为没有测试会走到那条兜底分支。
    """
    import dataclasses

    import pytest

    from app.scoring.types import DimensionScore, Evaluation

    ev = Evaluation(scores={"material_use": DimensionScore(level=2, note="ok")},
                    status="complete")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.status = "continue"          # 固定住"不能直接改"这个事实

    scores = dict(ev.scores)
    scores["material_use"] = dataclasses.replace(scores["material_use"], level=0, note="没用上")
    ev2 = dataclasses.replace(ev, scores=scores, status="continue", weakest="material_use")
    assert ev2.status == "continue" and ev2.weakest == "material_use"
    assert ev2.scores["material_use"].level == 0
    assert ev.status == "complete"      # 原对象不受影响


def test_material_exhausted_stops_the_pointless_extra_rounds():
    """材料用完了还被 beat_coverage 逼着写，就会把同一批材料换角度重写。

    实测：种子一句话、相关材料只够写一节，骨架却给了四到六条节拍。
    第 2、3 轮把「ask memory 优先、integration 延后」翻来覆去写了三遍，
    每节各收一次尾，coherence 和 non_repetition 一路从 2 掉到 1。
    """
    from app.grounding_check import material_exhausted

    facts = ["[2026-01-23] ask memory 功能优先做，integration 延后。",
             "[2026-01-23] 首发版本先覆盖核心录音与摘要体验。"]
    written = ("ask memory 功能优先做，integration 延后；"
               "首发版本先覆盖核心录音与摘要体验。")
    assert material_exhausted(written, facts)

    # 还有没写进去的材料 → 不算用完
    assert not material_exhausted("只写了 ask memory 优先做，integration 延后。", facts)
    # 材料太少时不下这个判断
    assert not material_exhausted(written, facts[:1])
    assert not material_exhausted(written, [])


def test_placeholder_lines():
    from app.grounding_check import placeholder_lines

    doc = ("## 倒排表\n\n"
           "| 众筹素材锁定 | 待指定 | 页面与首发版本一致 | 待倒排 |\n"
           "正常的一句话，什么坑都没留。\n"
           "责任人：___ 交付时间：___\n")
    got = placeholder_lines(doc)
    assert len(got) == 2
    assert any("待指定" in g for g in got)
    assert any("___" in g for g in got)
    assert placeholder_lines("干干净净的一段话。") == []
    assert len(placeholder_lines("待定\n" * 20)) == 6      # 限量


def test_audit_voice_lines():
    """审计腔和机制泄漏要能定位到具体句子。样本取自文件夹级 bench 的真实产出。"""
    from app.grounding_check import audit_voice_lines

    doc = ("众筹三月上旬启动。"
           "即使面向发货的相关功能已经可用，也不能据此判断用户已经完成硬件交付。"
           "目前 KB 中可核对的记录集中在二月。")
    got = audit_voice_lines(doc)
    assert len(got) == 2
    assert any("不能据此" in g for g in got)
    assert any("KB" in g for g in got)
    assert audit_voice_lines("三月上旬启动众筹，四月底结束。") == []
    assert audit_voice_lines("KBase 是个产品名，不该误伤。") == []
    assert len(audit_voice_lines("不能证明。" * 20)) == 5      # 限量


def test_scrub_meta_sentences():
    """元话语（机制泄漏 + 审计腔）整句删掉——最后一轮写的内容不会再经过修订。"""
    from app.grounding_check import scrub_meta_sentences

    t = "三月上旬启动众筹。目前 KB 中可核对的记录集中在二月。排期要往前倒推。"
    got = scrub_meta_sentences(t)
    assert "KB" not in got and "可核对的记录" not in got
    assert "三月上旬启动众筹。" in got and "排期要往前倒推。" in got
    assert scrub_meta_sentences("干净的一段话。") == "干净的一段话。"
    # 表格和代码块整块留着，不按句切
    tbl = "| 环节 | 负责人 |\n|---|---|\n| 众筹 | 甲 |"
    assert scrub_meta_sentences(tbl) == tbl
    # 审计腔也整句删：实测那两句整句都是对冲，没有实质信息，而规则里写得很
    # 清楚这类话在用户笔记里根本不该存在（正确形态是「这里需要补上 XX 的实际
    # 记录」）。最后一轮写的内容不会再经过修订，留给修订等于留在正文里。
    assert "不能据此" not in scrub_meta_sentences(
        "三月启动众筹。功能已可用，但不能据此判断已交付。排期要倒推。")
    assert "三月启动众筹。" in scrub_meta_sentences(
        "三月启动众筹。功能已可用，但不能据此判断已交付。排期要倒推。")


def test_bench_wordlist_and_scrubber_cannot_drift():
    """bench 检查的每个词，scrub 都必须删得掉。

    真实漂移：bench 自己写了一份词表，报出「无法判断」「仍需与」，而 scrub 的
    正则要求它们后面跟特定的字（"无法判断…是否"、"仍需与…核对"）——检测得出来、
    删不掉，文件夹级连着两批带着「无法判断」交付。现在词表只定义在
    grounding_check，bench 从那里 import。
    """
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "scripts"))
    from suite import AUDIT, LEAK  # noqa: PLC0415

    from app.grounding_check import _META_SENT, scrub_meta_sentences

    for w in tuple(AUDIT) + tuple(LEAK):
        assert _META_SENT.search(f"这里{w}的一句话。"), f"bench 报 {w!r} 而 scrub 删不掉"
        assert w not in scrub_meta_sentences(f"三月启动。这里{w}的一句话。排期倒推。")
