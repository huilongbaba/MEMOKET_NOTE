"""P42 A：记忆那条线的三条遗留。

**A1**（位置判据）量完**没做**——结论和那 82 条标注进了 `memory_sample.jsonl`
的 `p42-allpair82` 组，这个文件里只有「那张表没被动过 / 位置是纯函数算得出来的」这几条闸。
**A2**（`common_term` 接到 `plan` 的中文 grep 通道）量完**做了**，闸在下面。
**A3**（标注当批进仓库）是夹具那一组 + 两条闸。

闸的规矩跟 P38 一条不变：**阈值闸管方向、具体断言管接线，两种都得有**。
"""

from __future__ import annotations

import types

from app.database.kb import search
from scripts import memory_sample_replay as R

# ---------------------------------------------------------------- A2 common 接到 grep 通道


class _Mem:
    def __init__(self, cjk):
        self._candidate_terms = lambda text: []
        self._cjk_terms = lambda text, weigh=None: list(cjk)
        self._match_vocab = lambda q, v: ([], [], [])


_VOCAB = types.SimpleNamespace(topics={}, entities={})
_Q = "给投资人讲故事的时候要说清楚三件事"
_CUT = lambda t: ["投资人", "讲故事", "的", "时候", "要说", "清楚", "三件", "事"]   # noqa: E731
# 滑窗那一档**长得跟分词那一档不一样**（真实的滑窗就是这种切碎的三字串）。
# 一样的话「退回滑窗」和「退回只剔口水词」两条分支的产物会撞在一起，
# 反例就落不到被测的那条分支上——突变验当场抓到过（P38 #2 / P32 / P34 之后的第四次）。
_GRAMS = ["投资人", "资人讲", "人讲故", "讲故事"]


def test_满库都是的词不当grep词():
    """`_is_cn_filler` 挡的是口水词那张固定表，`common` 挡的是这个人库里 df ≥ 6% 的那一档。
    实拍：`时候` 在 terrence 的 2362 个 unit 上过了门槛，原来它占着第三个 grep 槽。"""
    qs = search.plan(_Mem(_GRAMS), _Q, _VOCAB, segment=_CUT,
                     common=lambda t: t == "时候")
    got = [q["where"]["grep"] for q in qs]
    assert "时候" not in got
    assert got == ["投资人", "讲故事", "清楚", "三件"]


def test_不给common就一个字不变():
    """**不启用就是原样**——P38 #5 那一版的取词在这里得逐字复现。"""
    a = [q["where"]["grep"] for q in search.plan(_Mem(_GRAMS), _Q, _VOCAB, segment=_CUT)]
    b = [q["where"]["grep"] for q in search.plan(_Mem(_GRAMS), _Q, _VOCAB, segment=_CUT,
                                                 common=None)]
    assert a == b == ["投资人", "讲故事", "时候", "清楚"]


def test_泛词剔光了退回只剔口水词那一版_不留空手():
    """一段里切出来的实词**全被 `common` 判成「满库都是」**时，中文通道不能空手——
    空手 = 把这条召回判死，跟「切不出实词退回滑窗」是同一条理由（P38 #5）。
    退的是**上一档**（只剔口水词），不是一路退到滑窗。"""
    qs = search.plan(_Mem(_GRAMS), _Q, _VOCAB, segment=_CUT, common=lambda t: True)
    got = [q["where"]["grep"] for q in qs]
    assert got == ["投资人", "讲故事", "时候", "清楚"]
    assert got != _GRAMS, "退的是**上一档**（只剔口水词），不是一路退回滑窗"
    assert not any(g in ("的", "事") for g in got), "口水词 / 单字那一关还得在"


def test_一个实词都切不出来时才退回滑窗():
    grams = ["的一个", "这个"]
    qs = search.plan(_Mem(grams), "的一个这个", _VOCAB,
                     segment=lambda t: ["的", "一个", "这个"], common=lambda t: True)
    assert [q["where"]["grep"] for q in qs] == grams


def test_recall只在开着证据闸的那条路上给common(monkeypatch):
    """**接线洞，单独一条。** `common` 跟 `segment` 必须是**同一个闸**：
    候选池那条路（`/memory/relations`、`relations/batch`）收窄取词会把下游
    `detect` 能判出来的关系提前掐掉——N4 那个绿点 P32 / P38 各掉过一次。
    规则层的单测抓不住「`recall` 到底有没有传」，所以这里盯的是调用。"""
    from app.database.kite import kite_memory as KM

    seen: list[tuple[bool, bool]] = []
    real_plan = KM.search.plan

    def spy(memory, query, vocab, *, pool=search.POOL, segment=None, common=None):
        seen.append((segment is not None, common is not None))
        return real_plan(memory, query, vocab, pool=pool, segment=segment, common=common)

    class _St:
        facts: dict = {}

    mem = KM.UserMemory.__new__(KM.UserMemory)
    mem._index = lambda: (_St(), _VOCAB)
    mem._match_vocab = lambda q, v: ([], [], [])
    mem._prescreen = lambda store, queries: queries
    mem.common_term = lambda: (lambda t: False)
    mem.vocab_term = lambda: (lambda t: False)
    mem.segment = lambda: (lambda t: ["投资人"])
    mem._recall_via_lines = lambda *a, **k: []
    mem._cjk_terms = staticmethod(KM.UserMemory._cjk_terms).__func__
    mem._candidate_terms = staticmethod(KM.UserMemory._candidate_terms).__func__
    monkeypatch.setattr(KM.search, "plan", spy)

    mem.recall(_Q, limit=3, evidence=True)
    assert seen == [(True, True)], "拿给用户看的那条路没把 common 接到 grep 上"
    seen.clear()
    mem.recall(_Q, limit=3)
    assert seen == [(False, False)], "候选池那条路不该收窄取词（N4 那个绿点就是这么掉的）"


# ---------------------------------------------------------------- A3 那 82 条标注


def _p42():
    return R.load_sample(set_name="p42-allpair82")


def test_两组都在_默认那组一条没动():
    """加第二组的代价必须是零：`load_sample` 不带参数回的还是 P34 那 47 条，
    P38 的三条闸都吊在它上面。"""
    _, rows47 = R.load_sample()
    assert len(rows47) == 47
    meta82, rows82 = _p42()
    assert len(rows82) == 82
    assert meta82["set"] == "p42-allpair82"
    keys = {(r["user"], r["query"], r["fact_id"]) for r in rows82}
    assert len(keys) == 82, "(用户, 查询, 事实) 重复会让分母悄悄变"


def test_这82条的标注不许因为代码变了而变():
    """跟 P38 那条同一个理由，也是突变验抓出来的同一个洞：
    **一份被抹平的标注跟一次真改进在阈值闸上长得一模一样**。所以钉逐格。"""
    _, rows = _p42()
    got = {k: sum(1 for r in rows if r["label"] == k) for k in ("hard", "meh", "bad")}
    assert got == {"hard": 48, "meh": 4, "bad": 30}, (
        f"P42 逐条读出来的是 48 硬 / 4 勉强 / 30 不硬，现在是 {got}——"
        "改标注只能靠人重读一遍，并且在台账里说清楚是谁读的")
    assert all(r["labeled_by"] == "P42" for r in rows)


def test_口径里写清楚它是全量不是抽样_而且不能跟P34那组比():
    """P34 那组踩过一次「拿一份分辨率不够的抽样报误判率」。这一组是**全量枚举**，
    它答得了「这个形状里误判占多少」、答不了「全库误判率」——两句都得写在里面。
    再加一句更要紧的：**两组的数不能直接比**（集合不同、「勉强」的边界也不同）。"""
    meta, _ = _p42()
    assert "不是抽样" in meta["怎么抽的"]
    assert "答不了" in meta["怎么抽的"]
    assert "不能直接比" in meta["跟 P34 那 47 条的关系"]


def test_位置指标是纯函数算出来的_离线逐条重算得上():
    """**接线洞。** 这 82 条冻的是位置，不是 `qualifies` 的重放——位置不问库，
    所以它必须能离线重算。算不上就说明这张表跟 `position_stats` 之间断了。"""
    _, rows = _p42()
    for r in rows:
        assert R.position_stats(r["terms"], r["query"], r["fact"]) == r["pos"], r["i"]


def test_位置指标真的在起作用_不是一堆常数():
    """第二条接线断言，钉的是**另一件事**：这些数不是全 0 / 全 None。
    上一条钉「算得上」，这一条钉「没退化」。"""
    _, rows = _p42()
    dmax = [r["pos"]["dmax"] for r in rows]
    assert all(d is not None for d in dmax)
    assert min(dmax) == 0 and max(dmax) == 392
    assert sum(1 for d in dmax if d == 0) == 12


def test_冻下来的证据串还是当前代码认的那几条():
    """**第三条接线断言。** `terms` 是 P38-收尾那一版 `evidence_runs` 的产物；
    `hit` 也冻着，所以拿当前代码重算一遍，`terms` 必须还是它的子集
    （`evidence` 会再按 `common` 滤掉一些，所以是子集不是相等）。
    对不上 = 取词那一层动了，这张表和它的结论都得重读，**不许静悄悄**。"""
    _, rows = _p42()
    for r in rows:
        runs = set(search.evidence_runs(r["hit"], r["query"]))
        assert set(r["terms"]) <= runs, (r["i"], r["terms"], sorted(runs))


def test_位置判据在这82条上分不开_这一格钉死免得下一批再试一遍():
    """A1 量完的那一档：`dmax ≤ 5` 才放行——**留下的那 24 条一条误判都没有**，
    可代价是砍 25 硬换 30 不硬 = **1.20 : 1**。按这条线一直用的账法
    （P27「2 换 3，不换」、P38 #2 否掉 2.2 : 1）**不够**。

    这条闸不管产品行为，它管的是**别再试一遍**：谁要改这个判据，先看这一格。
    """
    _, rows = _p42()
    keep = [r for r in rows if r["pos"]["dmax"] is not None and r["pos"]["dmax"] <= 5]
    by = {k: sum(1 for r in keep if r["label"] == k) for k in ("hard", "meh", "bad")}
    assert by == {"hard": 23, "meh": 1, "bad": 0}
    cut_hard = 48 - by["hard"]
    cut_bad = 30 - by["bad"]
    assert cut_hard == 25 and cut_bad == 30
    assert cut_bad / cut_hard < 2.0, "换的比没到这条线上认的那一档"
