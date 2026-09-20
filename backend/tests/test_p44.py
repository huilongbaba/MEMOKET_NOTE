"""P44 A：召回命中词里的碎片（P40 问题 #4 / P41 #2 / P42 问题 #5）。

账 P41 已经量完了（尺子 C：43 串次 / 24 种 / 6.2%，前 3 里 31 串次 / 19 种），
这个文件钉的是**照那三条修法落下来的代码**：
  1. `kb/search.evidence()` 多带一格 `aligned`；
  2. `kite_memory.recall_evidence` 那行 `label = … or term` 的 `or term` 去掉；
  3. **过滤必须留底**——一条证据都摆不出来 ≠ 这条召回不成立。

闸的规矩跟 P38 / P42 一条不变：**阈值闸管方向、具体断言管接线，两种都得有**。
"""

from __future__ import annotations

import types

from app.database.kb import search
from scripts import memory_sample_replay as R

# 「3月12号上线」那一句真实的分词结果（P41 #2 定点复现里逐字打出来的那一行）
_Q = "这周把众筹页面的文案定稿了，3月12号上线。"
_SQ = "这周把众筹页面的文案定稿了，3月12号上线。"
_CUT = ["这周", "把", "众筹", "页面", "的", "文案", "定稿", "了", "，3", "月", "12",
        "号", "上线", "。"]
_SEG = lambda _t: list(_CUT)     # noqa: E731


def test_跨词边界的碎片判得出来():
    """「号上众」剥完剩下的「众」压在「众筹」中间；「筹页」横跨 `众筹` 和 `页面`。

    **「号上」这一串自己走的是另一条路**：它每一个字都在 `_EDGE_STOP` 里，剥完是空串，
    `_ALL_CJK("")` 为假 → `aligned` 回 `None`，由「合不出 ≥2 个字」那一条砍
    （见 `test_剥空了不退回原串` / `test_面板上不再摆号上`）。
    """
    assert search._aligned("众", _SQ, _SEG) is False      # 起点在边界、终点不在
    assert search._aligned("筹", _SQ, _SEG) is False       # 终点在边界、起点不在
    assert search._aligned("筹页", _SQ, _SEG) is False     # 两端都不在
    assert search._aligned("案定", _SQ, _SEG) is False


def test_整词和整词接起来的不算碎片():
    """**「泛」和「碎」是两件事**（P41 #2）：`用户` / `功能` / `页面` 这种常用词是真词，
    它们拿 0 分是因为 `common` 判「满库都是」，不是因为它们碎。这把尺子不许碰它们。"""
    assert search._aligned("众筹页面", _SQ, _SEG) is True      # 众筹 | 页面
    assert search._aligned("众筹", _SQ, _SEG) is True
    assert search._aligned("页面", _SQ, _SEG) is True
    # **0 和 len 也是词边界**：落在最前 / 最后的整词不能算碎片
    assert search._aligned("这周", _SQ, _SEG) is True
    assert search._aligned("页面", "众筹页面", lambda _t: ["众筹", "页面"]) is True


def test_判不了的三档一律None_不许当成碎片():
    """`None` = 不知道。**把「不知道」当成「是碎片」就是把话说死**——
    跟 `content_chars` 的 `None`、`evidence_runs` 的 `loose` 同一条理由。"""
    assert search._aligned("众筹页面", _SQ, None) is None       # 没有分词器
    assert search._aligned("3月12", _SQ, _SEG) is None          # 不是纯汉字（P32 留下的那一档）
    assert search._aligned("kol", _SQ, _SEG) is None
    assert search._aligned("验收标准", _SQ, _SEG) is None       # 查询里定位不到


def test_同一串出现多次_有一次对齐就算对齐():
    """**判据宁可窄**：一处是碎片、另一处是整词，按整词算。

    **第一处得真的没对齐**，不然「碰到没对齐的就判死」那一刀砍空（反例落不到那条分支里）：
    「马**上线**下沟通」里的 `上线` 横跨 马上 | 线下，第二处「然后**上线**清单」才是整词。
    """
    q = "马上线下沟通，然后上线清单过一遍"
    cut = ["马上", "线下", "沟通", "，", "然后", "上线", "清单", "过", "一遍"]
    assert search._aligned("上线", q, lambda _t: list(cut)) is True


def test_evidence多带的那一格():
    ev = search.evidence(["众筹页", "筹页面", "案定稿"], _Q, segment=_SEG)
    got = {e["term"]: e["aligned"] for e in ev}
    # `众筹页` + `筹页面` 重叠，合成「众筹页面」= 众筹 | 页面，两端都在边界上
    assert got == {"众筹页面": True, "案定稿": False}, got
    # 老的两格一个字没动
    assert all(set(e) == {"term", "why", "aligned"} for e in ev)


def test_aligned不许接进qualifies():
    """**这一格只给显示层看。**「这个词摆出来难看」不是「这条召回不该进来」——
    接进 `qualifies` 就是拿显示规则去判死召回，那是最贵的那种错。

    **反例得真的落在被测的那条分支里**（已栽过四次）：光有一条碎片证据时 `qualifies`
    本来就回 `False`（单条 `pair` 不够硬），拿那种例子测等于没测。所以这里凑第二条证据
    （`kol`），让它走 `len(ev) >= 2` 那一支——**放行的理由里真的有那条碎片**。"""
    q = "本周把电池容量定在420mAh，kol 样机也要发"
    cut = ["本周", "把", "电池", "容量", "定在", "420mah", "，kol", "样机", "也", "要", "发"]
    seg = lambda _t: list(cut)      # noqa: E731
    # `电池容` 是碎片（压在 电池 | 容量 上，一个整词都没凑齐）
    ev = search.evidence(["电池容"], q, segment=seg)
    assert [(e["term"], e["aligned"]) for e in ev] == [("电池容", False)], ev
    # **它照样够格进来**：`电池容` + `kol` 两条证据，`qualifies` 的 `len(ev) >= 2` 放行。
    # 这就是反例真的落在被测那条分支里的样子——把 `aligned` 接进 `qualifies` 的那一刀在这儿红。
    # 第二条故意挑 `420mah`（数字打头 → `why=pair`，单独不够硬）：
    # 把碎片滤掉之后就只剩一条 `pair`，闸当场翻成 `False`——**那一刀这才砍在被测的分支里**。
    # 挑 `kol`（`why=span`）的话滤不滤都放行，等于没测。
    assert search.qualifies(["电池容", "420mah"], q, segment=seg) is True
    assert [(e["term"], e["why"], e["aligned"]) for e in
            search.evidence(["电池容", "420mah"], q, segment=seg)] == [
        ("电池容", "pair", False), ("420mah", "pair", None)]


def test_aligned判的是摆出来的那一串_不是原始的run():
    """拿 run 去判会把 `众筹后` → 「众筹」这种剥完是真词的也判成碎片（P44 先量那一趟读出来的）。
    反过来 `华为` 这一条正好相反，**反例真的落在被测那条分支里**：

    「引入**华为**的方案」里 run `华为` 两端都在词边界上，可 `为` 在 `_EDGE_STOP` 里，
    剥完只剩「华」，压在「华为」中间——**摆出来的那一串是碎的**，所以这一条判 `False`。
    （顺带：这也说明「对齐了的串不该再剥」，留给下一批。）
    """
    q = "引入华为的方案"
    seg = lambda _t: ["引入", "华为", "的", "方案"]      # noqa: E731
    assert search._aligned("华为", q, seg) is True          # run 自己是对齐的
    assert search._aligned("华", q, seg) is False           # 摆出来的那一串不是
    assert [(e["term"], e["aligned"]) for e in
            search.evidence(["华为"], q, segment=seg)] == [("华为", False)]
    # 反过来那一侧：`众筹后` 剥完是「众筹」，是真词，不许判成碎片
    q2 = "作为众筹后交付"
    seg2 = lambda _t: ["作为", "众筹", "后", "交付"]      # noqa: E731
    assert [(e["term"], e["aligned"]) for e in
            search.evidence(["众筹后"], q2, segment=seg2)] == [("众筹后", True)]


# ---------------------------------------------------------------- evidence_label

def test_剥空了不退回原串():
    """P40 问题 #4 的第二个坑：`label = term.strip(_EDGE_STOP) or term` 的 `or term`
    把「号上」（号 / 上 都在 `_EDGE_STOP` 里）原样退了回来，直接摆到了用户眼前。"""
    assert search.evidence_label("号上") == ""
    assert search.evidence_label("号上众") == "众"
    assert search.evidence_label("众筹后") == "众筹"
    assert search.evidence_label("众筹页面") == "众筹页面"


def test_英文和带数字的原样不剥():
    """`_EDGE_STOP` 是一张汉字表，拿它去剥 `kol` / `3月15` 没有意义。"""
    assert search.evidence_label("kol") == "kol"
    assert search.evidence_label("3月15") == "3月15"


# ---------------------------------------------------------------- recall_evidence

class _Store:
    def __init__(self, texts):
        self.facts = {f"f{i}": types.SimpleNamespace(text=t, topics=(), entities=())
                      for i, t in enumerate(texts)}


def _mem(texts, cjk, *, seg=_SEG, df=None, en=()):
    """一个只够 `recall_evidence` 跑起来的 `UserMemory`。"""
    from app.database.kite import kite_memory as KM

    vocab = types.SimpleNamespace(topics={}, entities={})
    idx = types.SimpleNamespace(unit_count=2362,
                                unit_df=lambda w, floor=0: (df or {}).get(w, 0))
    mem = KM.UserMemory.__new__(KM.UserMemory)
    mem._index = lambda: (_Store(texts), vocab)
    mem._grep_index = lambda store: idx
    mem._candidate_terms = lambda text: list(en)
    mem._cjk_terms = lambda text: list(cjk)
    mem._match_vocab = lambda q, v: ([], [], [])
    mem.common_term = lambda: None
    mem.vocab_term = lambda: None
    mem.segment = lambda: seg
    return mem


def test_面板上不再摆号上():
    """P40 实拍那一行：「命中：众筹页面、**号上**、页面」。"""
    mem = _mem(["众筹页面的文案定稿，3月12号上线成功"], ["众筹页", "筹页面", "号上"])
    got = [e["term"] for e in mem.recall_evidence(_Q, [{"id": "f0"}])]
    assert "号上" not in got
    # `3月12` 还在：**带数字的那一档 `_weigher` 自己就退回字数了**（P32 专门量过、专门留下的），
    # 这一批一个字没碰它——「别人量完留下的东西，不顺手带走」。
    assert got == ["众筹页面", "3月12"], got


def test_跨词边界的碎片不摆():
    q = "每台8卡可以实现与传统方案的对比"
    cut = ["每台", "8", "卡", "可以", "实现", "与", "传统", "方案", "的", "对比"]
    mem = _mem(["这个方案可以实同样的效果"], ["可以实"], seg=lambda _t: list(cut))
    assert [e["term"] for e in mem.recall_evidence(q, [{"id": "f0"}])] == []
    # 反过来：`可以实` 和 `以实现` 都命中时合成「可以实现」= 可以 | 实现，**整词接起来的照样摆**
    mem2 = _mem(["这个方案可以实现同样的效果"], ["可以实", "以实现"], seg=lambda _t: list(cut))
    assert [e["term"] for e in mem2.recall_evidence(q, [{"id": "f0"}])] == ["可以实现"]


def test_过滤必须留底_召回那几条一条不少():
    """**一条证据都摆不出来 ≠ 这条召回不成立**（P32 `evidence_runs` 的 `loose` 同理）。
    这里回空列表，前端 `evidenceLine` 自己退回 `display_terms` 那一行。
    全库量过：765 条查询里有 9 条落到这一档。"""
    q = "每台8卡可以实现与传统方案的对比"
    cut = ["每台", "8", "卡", "可以", "实现", "与", "传统", "方案", "的", "对比"]
    rows = [{"id": "f0"}, {"id": "f1"}]
    mem = _mem(["这个方案可以实同样的效果", "另一条也说可以实"], ["可以实"],
               seg=lambda _t: list(cut))
    assert mem.recall_evidence(q, rows) == []
    # 传进来的那几条**一个都没被动过**——这个函数只管「摆什么」，不管「留谁」
    assert rows == [{"id": "f0"}, {"id": "f1"}]


def test_同一个词剥完撞在一起只摆一遍():
    """`众筹后` 和 `把众筹` 剥完都是「众筹」。按原始 run 去重会把同一个词摆两遍。"""
    q = "作为众筹后的安排，把众筹页面定稿"
    cut = ["作为", "众筹", "后", "的", "安排", "，", "把", "众筹", "页面", "定稿"]
    mem = _mem(["众筹后要交付", "把众筹的页面定稿"], ["众筹后", "把众筹"],
               seg=lambda _t: list(cut))
    assert [e["term"] for e in mem.recall_evidence(q, [{"id": "f0"}, {"id": "f1"}])] == ["众筹"]


def test_没有分词器就是原样_只去掉or_term那个退回():
    """**不启用就是原样**：假的 memory / 建不出索引时 `aligned` 全是 `None`，
    R1 一条都不砍；但 `or term` 那个退回**在哪一档都不许有**。"""
    mem = _mem(["众筹页面的文案定稿，3月12号上线成功"], ["众筹页", "号上"], seg=None)
    got = [e["term"] for e in mem.recall_evidence(_Q, [{"id": "f0"}])]
    assert "号上" not in got          # `or term` 那个退回没了
    assert got == ["众筹页", "3月12"], got     # 碎片照旧摆着：这一档 R1 一条都不砍


def test_英文和数字不归那两条过滤管():
    """两条过滤都是**汉字这一侧**的规矩：`_EDGE_STOP` 是一张汉字表，
    「合不出 ≥2 个字」说的也是汉字词。拿它们去砍 `5` / `kol` 是量程用错。

    **直接测这一关本身**（同 P34「库里长出来的词那两道闸」那条的做法）：
    今天的 `_terms` 大概率切不出一个字的英文串，所以走公开那条路测不到这一关——
    而**判据成不成立不该靠上游碰巧不给它这种输入**。
    """
    from app.database.kite import kite_memory as KM

    mem = _mem(["随便一条"], [], seg=None)
    old = KM.search.evidence
    KM.search.evidence = lambda hits, query, **kw: [
        {"term": "5", "why": "pair", "aligned": None},
        {"term": "kol", "why": "span", "aligned": None},
    ]
    try:
        got = [e["term"] for e in mem.recall_evidence("定在 420mAh，5 台样机", [{"id": "f0"}])]
    finally:
        KM.search.evidence = old
    assert got == ["5", "kol"], got


def test_units数的还是原始的那一串():
    """`units` 是 P29 的 df，数的是**这一串**在库里出现在几个 unit 里——
    剥完的 label 不是库里那个词，拿它去查 df 会把这个数说小。"""
    mem = _mem(["作为众筹后交付"], ["众筹后"],
               seg=lambda _t: ["作为", "众筹", "后", "交付"], df={"众筹后": 7, "众筹": 107})
    got = mem.recall_evidence("作为众筹后交付", [{"id": "f0"}])
    assert got == [{"term": "众筹", "why": "pair", "units": 7}], got


# ---------------------------------------------------------------- 夹具那一组（P38 ① 的规矩）

def test_夹具里三组都在_默认组一个字没动():
    meta47, rows47 = R.load_sample()
    assert len(rows47) == 47 and meta47
    assert len(R.load_sample(set_name="p42-allpair82")[1]) == 82
    assert len(R.load_sample(set_name="p44-frag64")[1]) == 64


def test_这64条的标注分布逐格相同():
    """**「把标注抹平」那种突变也要挡**：63 / 1 这两个数各自钉死，
    再钉一条「不许全是同一个标注」——抹平成全 `frag` 的那一刀在这儿红。"""
    from collections import Counter

    _meta, rows = R.load_sample(set_name="p44-frag64")
    dist = Counter(r["label"] for r in rows)
    assert dist["frag"] == 63 and dist["word"] == 1, dist
    assert len(dist) == 2, f"标注被抹平了：{dist}"
    assert len({r["shown"] for r in rows}) == 42
    # 砍它的是哪一条规则，也逐格钉
    assert Counter(r["rule"] for r in rows) == {"R1-跨词边界": 57, "R2-合不出两个字": 7}


def test_这64条离线逐条重算得上():
    """冻的是 `cut`（查询的分词结果），所以这一层**不问库、不问 codebook**——
    下一批换尺子拿它重跑，不用再读一遍 64 条（同 P42 那 82 条冻位置指标）。"""
    _meta, rows = R.load_sample(set_name="p44-frag64")
    for r in rows:
        got = R.display_stats(r["run"], r["query"], r["cut"])
        assert got["rule"] == r["rule"], (r["i"], r["shown"], got)
        assert got["aligned"] == r["aligned"], (r["i"], r["shown"], got)
        assert got["label"] == r["stripped"], (r["i"], r["shown"], got)
        assert got["shown"] is False, (r["i"], r["shown"], got)


def test_冻下来的分词真的是这条查询的():
    """量具自己得先对：`cut` 拼起来必须逐字等于挤掉空白的查询，
    否则「离线重算得上」就是拿一份对不上的分词自说自话（P42 量具教训 #2）。"""
    import re

    _meta, rows = R.load_sample(set_name="p44-frag64")
    for r in rows:
        assert "".join(r["cut"]) == re.sub(r"\s+", "", r["query"].lower()), r["i"]


def test_P40那一串在这64条里():
    """这一组冻的第一件事就是「P40 实拍那一行到底被砍掉了什么」。"""
    _meta, rows = R.load_sample(set_name="p44-frag64")
    zhong = [r for r in rows if r["shown"] == "众"]
    assert zhong and zhong[0]["run"] == "号上众", zhong


def test_口径里写清它答不了什么():
    """**结论写在夹具自己身上**（P42 A3 那条）：不是抽样 / 不能跟另两组比 / 那 1 条误杀。"""
    meta, _rows = R.load_sample(set_name="p44-frag64")
    assert "不是抽样" in meta["怎么抽的"]
    assert "全量枚举" in meta["怎么抽的"]
    assert "全库误判率" in meta["答不了什么"]
    assert "p34-sample47" in meta["答不了什么"] and "p42-allpair82" in meta["答不了什么"]
    assert "链接" in meta["结论"]


def test_display_stats是纯函数_分词对不上就吵():
    """`cut` 跟查询对不上时**吵闹地失败**，不许悄悄按「没有分词器」算过去。"""
    import pytest

    with pytest.raises(ValueError):
        R.display_stats("号上", _Q, ["完全", "不相干", "的", "切法"])
