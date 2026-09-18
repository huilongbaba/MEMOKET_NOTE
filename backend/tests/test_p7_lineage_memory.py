"""P7（第 772 轮）：修 P4 读出来的十条——脉络梳理 + 记忆浮现。每条一组用例 + 反向（植入）用例。

判据来源全是 P4 台账上的真实片段（`docs/TRACELOG-product.md` P4 节），不是编的。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store                                     # noqa: E402
from app.database.kb import relations, search                      # noqa: E402
from app.harness.checks import skeleton as sk                      # noqa: E402


# ---------------------------------------------------------------- #1 骨架不再被截成半句

def test_1_trim_to_boundary_按句读收不按字硬切():
    long = "已写：用Speaker B关于录后打开手机、上传、等待和二次操作的反馈，具体暴露硬件交互与真实使用目标之间的断点，并将问题从能不能录推进到录完系统替用户完成多少工作。" * 2
    out = store.trim_to_boundary(long, 200)
    assert len(out) <= 200
    assert out.endswith("。") and not out.endswith("并将问")     # 真库那 4 篇的病：「…之间的断点，并将问」
    assert store.trim_to_boundary("短的", 200) == "短的"


def test_1_没有句读时才按字数切并补省略号():
    out = store.trim_to_boundary("一个很长的节拍" * 30, 200)
    assert len(out) == 200 and out.endswith("…")


def test_1_BEAT_MAX高于实测分布():
    # P4 实跑 57–185、历史 28–185：上限必须在这之上，不然「所见」和「所存」照样不一样
    assert store.BEAT_MAX >= 185


def test_1_clamp_不再把P4那份骨架截成60():
    beats = ["a" * 57, "b" * 87 + "。", "c" * 72 + "。", "d" * 92 + "。", "e" * 96 + "。"]
    _s, out = store.clamp_skeleton("spine", beats)
    assert [len(b) for b in out] == [57, 88, 73, 93, 97]        # P4 `d1_roundtrip.py`：原来存成 [57,60,60,60,60]


def test_1_set_skeleton_超长报错不静默截断(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path, raising=False)
    with pytest.raises(ValueError, match="节拍太长"):
        store.set_skeleton("u", "n", "spine", ["x" * (store.BEAT_MAX + 1)])
    with pytest.raises(ValueError, match="核心张力太长"):
        store.set_skeleton("u", "n", "s" * (store.SPINE_MAX + 1), ["ok"])


# ---------------------------------------------------------------- #2 「待补」的正文里已经有

N4 = """# 国际高中

陈校从招生策略延伸到课程本土化、师资协作的沟通，以及午餐邀请。

Speaker B 说录完还要打开手机、上传、等待，再做二次操作。

数据流转译如何落地：录后自动分发、摘要，按课程标签自动推送到共创群，同时写入案例库。

Speaker A 说在 Discord 上建一个 MemoCad 的账号，作为讨论板块。

用"不用再去记录"衡量合作价值是否兑现，在销售上市前验证师资协作价值。
"""


def test_2_待补的正文里有就翻成已写并带行号():
    beats = ["尚缺：补齐数据流各环节的责任人、课程标签与Discord/案例库的接入方式，以及用“打开即有答案、不用再记录”在销售上市前验证师资协作价值是否真正兑现。"]
    out = sk.verify_beats(beats, N4)
    assert out[0].startswith("已写（正文第 ") and "行起）：" in out[0]
    assert "尚缺" not in out[0]


def test_2_再核一遍是幂等的():
    beats = ["尚缺：补齐数据流各环节的责任人、课程标签与Discord/案例库的接入方式，以及用“打开即有答案、不用再记录”在销售上市前验证师资协作价值是否真正兑现。"]
    once = sk.verify_beats(beats, N4)
    assert sk.split_beat_label(once[0]) == ("written", once[0].split("：", 1)[1])
    assert sk.verify_beats(once, N4) == once


def test_2_真的缺的保留待补():
    beats = ["待补：把跨行业案例收束为一套可复用的合作方法：先识别最昂贵或最危险的环节，再以算力和数据底座承载模型，保留人的关键决策与行业责任。"]
    out = sk.verify_beats(beats, N4)
    assert out[0].startswith("待补：")


def test_2_五种标签写法统一成一种():
    beats = ["【已写】甲", "已写：乙", "已写并需继续收紧：丙", "尚缺：丁的责任人和试点决策以及一堆正文里没有的东西", "待补 戊的什么什么正文里没有"]
    out = sk.verify_beats(beats, N4)
    assert out[0] == "已写：甲" and out[1] == "已写：乙" and out[2] == "已写：丙"
    assert out[3].startswith("待补：") and out[4].startswith("待补：")


def test_2_没标的盖住了才标已写_盖不住不乱标():
    out = sk.verify_beats(["Speaker B 说录完还要打开手机上传等待做二次操作", "把跨行业案例收束为可复用的合作方法并明确客户下一步"], N4)
    assert out[0].startswith("已写：")
    assert not out[1].startswith("已写") and not out[1].startswith("待补")


def test_2_门槛在P4量出来的两簇之间():
    # 编的 ≤ 0.19、写了的 ≥ 0.35（P4 五篇 31 条）
    assert 0.19 < sk.COVER_MIN < 0.35


# ---------------------------------------------------------------- #3 条数按长度

def test_3_beats_budget():
    assert sk.beats_budget(800) == 6 and sk.beats_budget(4900) == 6
    assert sk.beats_budget(12_000) == 6 and sk.beats_budget(14_001) == 8
    assert sk.beats_budget(26_714) == 12 and sk.beats_budget(100_000) == 12
    rule = sk.skeleton_length_rule(26_714)
    assert "3–12 条" in rule and f"{sk.BEAT_TARGET_CHARS} 字" in rule and "待补" in rule


# ---------------------------------------------------------------- #4 单位表 + 弱重合

@pytest.mark.parametrize("text,unit", [
    ("100辆矿卡", "辆"), ("42.35平方公里", "平方公里"), ("-50度", "度"), ("3500万吨", "万吨"),
    ("8 个 NPU 刀片", "个"), ("1.2PB", "PB"), ("132kW", "kW"), ("秒级完成，用时 3 秒", "秒"), ("50000+tps", "tps"),
    ("投入3年", "年"), ("72卡", "卡"),
])
def test_4_单位表补齐(text, unit):
    assert unit in {u for _v, u in relations.extract_values(text)["nums"]}, text


def test_4_年份是日期不是量():
    v = relations.extract_values("营收几乎与2020年的巅峰持平")
    assert "2020" in v["dates"] and not v["nums"]


def test_4_一个弱重合压不掉缺依据():
    # P4 复盘 L7：正文「…华为现在21万员工…WiFi…」top 事实是「他的通信就是要通过WiFi。」（只因为 wifi）
    facts = [{"id": "f-1", "text": "他的通信就是要通过WiFi。", "date": "2026-03-01"}]
    rels = relations.detect("从90年代开始每年至少投入营收的10%到研发上，华为现在21万员工，WiFi 的标准专利数量全球第一。", facts)
    assert [r["relation"] for r in rels] == ["unsupported"]


def test_4_沾边但没带同样的量也算缺依据():
    facts = [{"id": "f-1", "text": "华为的研发投入和研发工程师占比很高，专利数量全球领先。", "date": "2026-03-01"}]
    rels = relations.detect("华为每年投入营收的10%到研发上，研发工程师占一半，专利数量全球第一。", facts)
    kinds = [r["relation"] for r in rels]
    assert "unsupported" in kinds
    assert "沾边" in next(r for r in rels if r["relation"] == "unsupported")["say"]


def test_4_同量的记录在就不是缺依据():
    facts = [{"id": "f-1", "text": "华为每年投入营收的10%以上到研发上。", "date": "2026-03-01"}]
    rels = relations.detect("华为每年投入营收的10%到研发上，最近几年超 20%。", facts)
    kinds = [r["relation"] for r in rels]
    assert "corroborated" in kinds and "unsupported" not in kinds


# ---------------------------------------------------------------- #5 月级日期 / 中文数字 / 乱码

def test_5_月级和中文数字日期():
    assert relations.extract_values("并以6月末/7月销售上市窗口为验收边界")["dates"] == ["6", "7"]
    assert relations.extract_values("六月末或七月会在网站上开始销售")["dates"] == ["6", "7"]
    assert relations.extract_values("随后五月到六月渠道收回到官网做预购")["dates"] == ["5", "6"]
    assert relations.extract_values("2026年8月发布")["dates"] == ["2026-8"]
    assert relations.extract_values("在7月份的世界人工智能大会上")["dates"] == ["7"]
    # 天级的还是天级，不会被月级抢走
    assert relations.extract_values("3月10号上众筹")["dates"] == ["3-10"]


def test_5_中文数字带硬单位():
    v = relations.extract_values("先做三百台样机，二十万美元预算")
    # 「二十万美元」跟「21万员工」一个待遇：量是 20 万（「万」在单位表里），不拆成 200000 美元
    assert (300.0, "台") in v["nums"] and (20.0, "万") in v["nums"]
    assert relations.extract_values("统一台账、唯一条件")["nums"] == []
    assert relations.cn_to_int("三百二十") == 320 and relations.cn_to_int("十五") == 15 and relations.cn_to_int("两") == 2


def test_5_单个中文数字不带硬单位不转():
    # 「一个工具」满篇都是，转了每段都成了量
    assert relations.extract_values("需要一个工具，分成三类")["nums"] == []


def test_5_N4_L27_跟库里一模一样的话印证():
    # P4 表 A #7：正文「以6月末/7月销售上市窗口为验收边界」 ↔ 库里 `1439-0F4`「应该在 6 月末或 7 月会在网站上开始销售产品」
    facts = [{"id": "1439-0F4", "text": "Speaker B 说 应该在 6 月末或 7 月会在网站上开始销售产品", "date": "2026-03-12"}]
    rels = relations.detect("决策节奏需要收束。午餐会要把方向共识转化为可落地的闭环方案，并以6月末/7月销售上市窗口为验收边界，销售产品前验证。", facts)
    c = next(r for r in rels if r["relation"] == "corroborated")
    assert c["fact_ids"] == ["1439-0F4"] and c["values"] == ["6月", "7月"]


def test_5_同一天的两件不相干的事不算日期印证():
    # 突变验抓出来的：`MIN_SHARED_TERMS` 撤成 1 时，只共用「月号」一个词的两句会因为同一天判成「日期一致」
    facts = [{"id": "f", "text": "2月1号发工资。", "date": "2026-01-20"}]
    rels = relations.detect("产品 2月1号上线，上线前把页面刷一遍。", facts)
    assert not any(r["relation"] == "corroborated" for r in rels)
    assert any(r["relation"] == "unsupported" for r in rels)


def test_5_月级不判日期冲突():
    facts = [{"id": "f", "text": "众筹页面 7 月 21 日上线，众筹里面有很多页面", "date": "2026-03-12"}]
    rels = relations.detect("7月上线众筹页面，众筹里面页面很多", facts)
    assert not any(r["relation"] == "conflict" for r in rels)


def test_5_乱码token不当查询词():
    assert "start" not in relations._terms("第一<|start|>关联感知：第一段录音后锚点卡打开率≥70%")
    assert "<|start|>" not in search.clean_query("第一<|start|>关联感知") and "start" not in search.clean_query("第一<|start|>关联感知")


def test_5_N2_L74_八个指标的段判缺依据():
    # P4 表 A #3：一段 8 个指标，被 `start` 撞上 start-up 的英文事实压掉 → 什么都没有
    facts = [{"id": "f-%d" % i, "text": t, "date": "2026-03-01"} for i, t in enumerate([
        "why we start this company", "business development can start after Kickstarter", "start exploring AI"])]
    rels = relations.detect("录制信任闭环：演示现场就绪信号可视率≥90%，3 秒录性评分触发率≥80%，现场因设备犹豫放弃率<5%。第一<|start|>关联感知：第一段录音后锚点卡打开率≥70%。", facts)
    assert [r["relation"] for r in rels] == ["unsupported"]


# ---------------------------------------------------------------- #6 召回不硬凑

class _Fact:
    def __init__(self, text):
        self.text, self.topics, self.entities = text, (), ()


class _Store:
    def __init__(self, texts):
        self.facts = {f"f{i}": _Fact(t) for i, t in enumerate(texts)}


class _Mem:
    def __init__(self, en, cjk):
        self._candidate_terms = lambda text: list(en)
        self._cjk_terms = lambda text: list(cjk)


LONG = ("这样整理后，下一步才会明确：要求报价偏高或偏低的中介补充可比案例，向对买家判断最具体的人核实近期带看和反馈，"
        "要求给出成交周期依据；在关键依据尚未补齐前，暂缓接受任何一个单独的报价或周期判断。"
        "最终产出的不是一份更短的聊天记录，而是一套能追溯依据、看清分歧并支持下一步行动的决策材料。")


def test_6_长查询只剩一个泛词就返回空():
    assert len(LONG) >= search.LONG_QUERY
    st = _Store(["有的人开始说视频去记录自己的生活", "这个记录仅记录在那个聊天窗口里", "崩溃率日志记录的"])
    rows = [{"id": k} for k in st.facts]
    assert search.rank(rows, LONG, _Mem([], ["记录"]), st, limit=5) == []


def test_6_长查询命中两个不同的整词才算():
    st = _Store(["Slowo 负责 UI 和 UIUX，九月学位不确定", "只提到 ui 的一条", "uiux 缺页 ui 晚一天"])
    rows = [{"id": k} for k in st.facts]
    got = search.rank(rows, LONG, _Mem(["slowo", "ui"], ["学位"]), st, limit=5)
    assert [r["id"] for r in got] == ["f0"]           # ui / uiux 是同一个词，f2 只算一个


def test_6_短查询不受这条限制():
    st = _Store(["有的人开始说视频去记录自己的生活"])
    rows = [{"id": k} for k in st.facts]
    assert search.rank(rows, "记录", _Mem([], ["记录"]), st, limit=5) == rows


def test_6_显示用整词不是碎片():
    q = "因为3月10号上众筹，众筹里面会有很多的页面是要放我们自己的ui的页面"
    shown = search.display_terms(["ui", "的页面", "众筹里", "号上众", "3月10"], q)
    assert "ui" in shown and "3月10" in shown
    assert "号上众" not in shown and "众筹里" not in shown and "的页面" not in shown
    assert any("众筹" in w for w in shown)


def test_6_clusters():
    assert sorted(search._clusters(["华为", "华为的", "90%", "ai"])) == sorted(["华为的", "90%", "ai"])
    assert search._clusters(["ai", "90%", "华为的", "华为"]) == search._clusters(["华为", "华为的", "90%", "ai"])   # 跟输入顺序无关
    assert search._strong_enough(["记录"]) is False and search._strong_enough(["ui", "uiux"]) is False
    assert search._strong_enough(["slowo", "学位"]) is True


# ---------------------------------------------------------------- #9 叠加 / 合并要跟正文相干

def test_9_叠加要共用单位或三个词元():
    # P4：L97「用户规模超400万」叠加 `1604-9F2`「我10秒打一个，过10分钟又打了一下」
    facts = [{"id": "1604-9F2", "text": "我10秒打一个，过10分钟又打了一下，用户打电话来", "date": "2026-03-01"}]
    rels = relations.detect("文旅：用户规模超400万，电话咨询也在涨。", facts)
    assert relations.shared_terms("文旅：用户规模超400万，电话咨询也在涨。", facts[0]["text"]) == 2   # 沾边（用户、电话），但不到 3
    assert not any(r["relation"] == "accumulation" for r in rels)
    facts2 = [{"id": "f", "text": "文旅项目用户规模超 400万，日活 30万人，2026-03-10 上线", "date": "2026-03-01"}]
    rels2 = relations.detect("文旅项目用户规模超400万，用户规模还在涨。", facts2)
    assert any(r["relation"] == "accumulation" for r in rels2)


def test_9_合并候选两条都要跟正文沾边():
    # P4：L283 反欺诈「50000+tps」合并 `1818-7F1/7F2`「这个也是新加坡的」×2
    facts = [{"id": "a", "text": "这个也是新加坡的 tps 系统 50000", "date": "2026-03-01"},
             {"id": "b", "text": "OK，好，这个也是新加坡的 tps 系统 50000", "date": "2026-03-01"}]
    rels = relations.detect("反欺诈：50000+tps，毫秒级响应，风控模型覆盖全部交易。", facts)
    assert not any(r["relation"] == "merge" for r in rels)
