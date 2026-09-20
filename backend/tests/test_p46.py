"""P46：P43 / P44 留下的记忆与前端遗留里落在后端的三条。

  2. **「它自己就是一个词的就别剥」**（P44 A0b 顺带读出来的那条 / P44 留给下一批 ④）：
     `华为` 是这个人库里的词条、两端都在词边界上，却被 `_EDGE_STOP` 剥成单字「华」
     而砍掉。判据是 `search.is_whole_token`，**不是 `_aligned`**——先量过，账在下面。
  3. **淘汰闸把处置完的层也算进 `CHANGE_LAYER_KEEP = 20`**（P43 留给下一批 ①）：
     做满 20 次并逐处处置完，第 21 次会为几层早就处置完的层报警，**这句话对用户没意义**。
  1. **证据被砍光时前端不许退回更碎的串**（P44 问题 #3）的后端那半边：
     `[]`（判过了、一条都摆不出来）和 `None`（没判成）得分得开。

闸的规矩跟 P38 / P42 / P44 一条不变：**阈值闸管方向、具体断言管接线，两种都得有**。
"""

from __future__ import annotations

import types

from app.database import store as S
from app.database.kb import search
from scripts import memory_sample_replay as R

# 「引入华为的方案」那一句的分词（`华为` 在这个人的词表里，是一个整 token）
_QH = "引入华为的方案"
_SEGH = lambda _t: ["引入", "华为", "的", "方案"]      # noqa: E731


# ---------------------------------------------------------------- 2. is_whole_token

def test_它自己就是一个词的不剥():
    """P44 A0b 点名那一条：`华为` 两端都在词边界上、是词表里的词条，
    可 `为` 在 `_EDGE_STOP` 里，剥完只剩「华」，被「合不出两个字」那一条砍掉。"""
    assert search.is_whole_token("华为", _QH, _SEGH) is True
    assert search.evidence_label("华为", _QH, _SEGH) == "华为"
    # **不给那两个实参就是原样剥**（老调用方 / 假的 memory / 建不出索引）
    assert search.evidence_label("华为") == "华"
    assert search.evidence_label("华为", _QH, None) == "华"
    assert search.evidence_label("华为", None, _SEGH) == "华"


def test_判据是它是不是一个词_不是aligned():
    """**这一刀最容易砍歪的地方，全库量过**：第一版判据是「`_aligned(run) is True` 就不剥」，
    结果 `的高频`（的 | 高频）、`月前后`（月 | 前后）、`导出的`（导出 | 的）**两端也都在
    词边界上**——62 条查询的行变了、多摆 70 串次，`希望通过` 这种全回来了。

    `_aligned` 问的是「它是不是若干**整词**接起来的」，`is_whole_token` 问的是
    「它是不是**一个**词」。**反例就落在这条分支上**：下面三串 `_aligned` 全是 `True`，
    `is_whole_token` 全是 `False`，所以照旧剥。
    """
    q = "看的高频场景，月前后导出的那一版"
    cut = ["看", "的", "高频", "场景", "，", "月", "前后", "导出", "的", "那", "一", "版"]
    seg = lambda _t: list(cut)      # noqa: E731
    for run, stripped in (("的高频", "高频"), ("月前后", "月"), ("导出的", "导出")):
        assert search._aligned(run, q, seg) is True, run          # 对齐：整词接起来的
        assert search.is_whole_token(run, q, seg) is False, run   # 但它自己不是一个词
        assert search.evidence_label(run, q, seg) == stripped, run


def test_一个词都没对上就不算整token():
    """**判据宁可窄**：查询里定位不到、没有分词器、英文——三档一律不认，照旧剥。"""
    assert search.is_whole_token("华为", _QH, None) is False       # 没有分词器
    assert search.is_whole_token("验收", _QH, _SEGH) is False       # 查询里定位不到
    assert search.is_whole_token("kol", "引入 kol 的方案", lambda _t: ["引入", "kol", "的", "方案"]) is False
    assert search.is_whole_token("", _QH, _SEGH) is False


def test_同一串出现多次_有一处是整token就算():
    """跟 `_aligned` 同一条规矩：一处压在词中间、另一处是整词，按整词算。
    **第一处得真的不是整 token**，不然这一刀砍空（反例落不到那条分支里）。"""
    q = "华为芯组里华为自己也做"
    cut = ["华", "为", "芯", "组", "里", "华为", "自己", "也", "做"]
    seg = lambda _t: list(cut)      # noqa: E731
    assert search.is_whole_token("华为", q, seg) is True


def test_evidence那一格跟着摆出来的那一串走():
    """`aligned` 判的是 `evidence_label` 回出来的那一串——**只有一个 `evidence_label`**。
    `evidence()` 里再抄一遍剥法就是两把尺子，`recall_evidence` 摆的和这里判的会对不上。"""
    ev = search.evidence(["华为"], _QH, segment=_SEGH)
    assert [(e["term"], e["aligned"]) for e in ev] == [("华为", True)]
    # 老的三格一个字没多也没少（P44 那条闸的形状照旧）
    assert all(set(e) == {"term", "why", "aligned"} for e in ev)


def test_这一格照旧不许接进qualifies():
    """P44 立的那条，P46 一个字没动：显示规则不许判死召回。
    **反例真的落在被测分支里**——碎片 + 一条 `pair`，滤掉碎片就只剩一条 `pair`，闸当场翻。"""
    q = "本周把电池容量定在420mAh，kol 样机也要发"
    cut = ["本周", "把", "电池", "容量", "定在", "420mah", "，kol", "样机", "也", "要", "发"]
    seg = lambda _t: list(cut)      # noqa: E731
    assert search.is_whole_token("电池容", q, seg) is False
    assert search.qualifies(["电池容", "420mah"], q, segment=seg) is True


# ---------------------------------------------------------------- 2. recall_evidence 接线

class _Store:
    def __init__(self, texts):
        self.facts = {f"f{i}": types.SimpleNamespace(text=t, topics=(), entities=())
                      for i, t in enumerate(texts)}


def _mem(texts, cjk, *, seg, df=None, en=()):
    from app.database.kite import kite_memory as KM

    vocab = types.SimpleNamespace(topics={}, entities={})
    idx = types.SimpleNamespace(unit_count=2362,
                                unit_df=lambda w, floor=0: (df or {}).get(w, 0))
    mem = KM.UserMemory.__new__(KM.UserMemory)
    mem._index = lambda: (_Store(texts), vocab)
    mem._grep_index = lambda store: idx
    mem._candidate_terms = lambda text: list(en)
    mem._cjk_terms = lambda text, weigh=None: list(cjk)
    mem._match_vocab = lambda q, v: ([], [], [])
    mem.common_term = lambda: None
    mem.vocab_term = lambda: None
    mem.segment = lambda: seg
    return mem


def test_面板上摆的是华为不是华():
    """P44 A0b 那条在**用户看得见的那一行**上的样子。"""
    mem = _mem(["引入华为的方案之后成本降了"], ["华为"], seg=_SEGH, df={"华为": 12})
    got = mem.recall_evidence(_QH, [{"id": "f0"}])
    assert [(e["term"], e["units"]) for e in got] == [("华为", 12)], got


def test_接线洞_recall_evidence必须把查询和分词器交给evidence_label():
    """**省掉那两个实参就静静退回「一律剥」**，而上面那格 `aligned` 是**带着**它们算的——
    两把尺子，`华为` 判成对齐、摆出来却是单字「华」，然后被「合不出两个字」砍掉。
    这一条是**接线断言**，砍掉那两个实参的那一刀在这儿红（阈值闸看不见它）。"""
    src = (__import__("pathlib").Path(__file__).resolve().parents[1]
           / "app/database/kite/kite_memory.py").read_text(encoding="utf-8")
    assert "label = search.evidence_label(term, squeezed, segment)" in src
    assert "squeezed = search.squeeze(q)" in src


def test_英文和数字不归这一条管():
    """`is_whole_token` 对英文直接回 `False`——英文串本来就是整词切的，
    `_EDGE_STOP` 是一张汉字表，剥它是恒等变换，这一层不该再插一手。"""
    q = "定在 420mAh，kol 样机"
    cut = ["定在", "420mah", "，kol", "样机"]
    seg = lambda _t: list(cut)      # noqa: E731
    assert search.evidence_label("kol", q, seg) == "kol"
    assert search.evidence_label("420mah", q, seg) == "420mah"


def test_P40那一行照旧不摆号上():
    """P44 修的那条**一个字都没退**：`号上` 每个字都在 `_EDGE_STOP` 里，
    而且它在这条查询里**不是一个整 token**，所以 `is_whole_token` 救不了它。"""
    q = "这周把众筹页面的文案定稿了，3月12号上线。"
    cut = ["这周", "把", "众筹", "页面", "的", "文案", "定稿", "了", "，3", "月", "12",
           "号", "上线", "。"]
    seg = lambda _t: list(cut)      # noqa: E731
    assert search.is_whole_token("号上", q, seg) is False
    assert search.evidence_label("号上", q, seg) == ""
    mem = _mem(["众筹页面的文案定稿，3月12号上线成功"], ["众筹页", "筹页面", "号上"], seg=seg)
    got = [e["term"] for e in mem.recall_evidence(q, [{"id": "f0"}])]
    assert got == ["众筹页面", "3月12"], got


# ---------------------------------------------------------------- 2. 夹具

def test_夹具里四组都在_前三组一个字没动():
    assert len(R.load_sample()[1]) == 47
    assert len(R.load_sample(set_name="p42-allpair82")[1]) == 82
    assert len(R.load_sample(set_name="p44-frag64")[1]) == 64
    assert len(R.load_sample(set_name="p46-unstrip9")[1]) == 10


def test_这10条的标注分布逐格相同():
    """**「把标注抹平」那种突变也要挡**：三档各自钉死，再钉一条「不许只剩一档」。"""
    from collections import Counter

    _meta, rows = R.load_sample(set_name="p46-unstrip9")
    dist = Counter(r["label"] for r in rows)
    assert dist == {"word": 6, "weak": 3, "cut-shift": 1}, dist
    assert Counter(r["side"] for r in rows) == {"多摆": 9, "少摆": 1}
    assert sorted({r["p46"] for r in rows if r["side"] == "多摆"}) == \
        ["上线", "不变", "华为", "视为", "跟着", "阿里"]


def test_这10条离线逐条重算得上():
    """冻的是 `cut`，所以两把尺子都能离线重跑——**夹具那句「不用再读一遍」得兑现**。"""
    _meta, rows = R.load_sample(set_name="p46-unstrip9")
    for r in rows:
        assert R.display_stats(r["run"], r["query"], r["cut"], ruler="p44")["label"] == r["p44"], r["i"]
        assert R.display_stats(r["run"], r["query"], r["cut"], ruler="p46")["label"] == r["p46"], r["i"]
    # 少摆那一条**不是被判掉的**：两把尺子给它的 label 逐字相同，它只是被前 6 那一刀挤出去了
    shift = [r for r in rows if r["label"] == "cut-shift"]
    assert shift and shift[0]["p44"] == shift[0]["p46"] == "ppu"


def test_冻下来的分词真的是这条查询的():
    """量具自己得先对（P42 量具教训 #2）：`cut` 拼起来必须逐字等于挤掉空白的查询。"""
    import re

    _meta, rows = R.load_sample(set_name="p46-unstrip9")
    for r in rows:
        assert "".join(r["cut"]) == re.sub(r"\s+", "", r["query"].lower()), r["i"]


def test_P44那64条在新尺子下重跑():
    """**兑现 `p44-frag64` 那句「下一批换尺子拿它重跑，不用再读一遍」。**

    64 条里 **7 条**不再被砍（`跟着` `上线` `视为`×2 `华为`×2 `不变`），
    剩下 57 条照砍。那 64 条的标注**没有作废**：它标的是「P44 摆出来的那一串
    （`跟`/`线`/`视`/`华`/`变`）是碎的」——那句话今天照样成立，变的是**不摆那一串了**。
    """
    from collections import Counter

    _meta, rows = R.load_sample(set_name="p44-frag64")
    old = [R.display_stats(r["run"], r["query"], r["cut"], ruler="p44") for r in rows]
    new = [R.display_stats(r["run"], r["query"], r["cut"], ruler="p46") for r in rows]
    assert all(not o["shown"] for o in old)                      # P44 那一把：64 条全砍
    assert Counter(n["shown"] for n in new) == {False: 57, True: 7}
    assert sorted(n["label"] for n in new if n["shown"]) == \
        ["上线", "不变", "华为", "华为", "视为", "视为", "跟着"]
    # 冻下来的那一格照旧逐条对得上**它自己那一把尺子**
    for r, o in zip(rows, old):
        assert o["rule"] == r["rule"] and o["label"] == r["stripped"], r["i"]


def test_尺子名写错要吵():
    """**不许悄悄按默认那一把算过去**——那正是「拿今天的尺子核昨天冻的数」那种静默错。"""
    import pytest

    with pytest.raises(ValueError):
        R.display_stats("华为", _QH, ["引入", "华为", "的", "方案"], ruler="p45")


# ---------------------------------------------------------------- 3. 淘汰闸

_USER = "p46"


def _note() -> str:
    return S.create_note(_USER, "P46", "甲乙丙丁戊己庚辛")["id"]


def _layer(lid: str, states: list[str], seq: int = 0) -> dict:
    """`at` 取现在——过期那条闸（30 天）不该在这几条里插嘴。"""
    from datetime import datetime, timezone
    return {"id": lid, "label": "格式化", "source": "format", "seq": seq,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hunks": [{"k": k, "from": k, "to": k + 1, "del": "a", "ins": "b", "state": s}
                      for k, s in enumerate(states)]}


def test_一处活的都不剩的层不算活口():
    assert S._layer_is_live({"hunks": [{"state": "pending"}]}) is True
    assert S._layer_is_live({"hunks": [{"state": "off"}]}) is True          # 整层关着≠处置完
    assert S._layer_is_live({"hunks": [{"state": "accepted"}, {"state": "reverted"}]}) is False
    assert S._layer_is_live({"hunks": [{"state": "accepted"}, {"state": "pending"}]}) is True
    assert S._layer_is_live({"hunks": []}) is False
    assert S._layer_is_live({}) is False


def test_处置完的层不再占KEEP那20个名额():
    """**P43 #1 那条「下一步」**：一篇上做满 20 次 AI 动作并逐处处置完，
    第 21 次原来会弹「N 层改动没能留到下次打开」——而那几层早就处置完了。

    **反例真的落在被测分支里**：20 层全处置完 + 1 层活的 = 21 层，
    混着数的那一版在这儿会淘汰掉最早那一层并报一句；分开数就**一个字不说**。
    """
    nid = _note()
    layers = [_layer(f"done{i}", ["accepted"], seq=i) for i in range(20)]
    layers.append(_layer("live", ["pending"], seq=20))
    r = S.save_change_layers(_USER, nid, layers)
    assert r["evicted"] == [], r["evicted"]
    assert r["saved"] == 21
    assert [l["id"] for l in S.list_change_layers(_USER, nid)] == \
        [f"done{i}" for i in range(20)] + ["live"]


def test_活口真的超了还是要淘汰还是要吵():
    """闸**没有被拆掉**，只是数对了东西：21 层活的照样扔最早那一层、照样说出来。"""
    nid = _note()
    r = S.save_change_layers(_USER, nid, [_layer(f"live{i}", ["pending"], seq=i) for i in range(21)])
    assert len(r["evicted"]) == 1
    assert r["evicted"][0]["label"] == "格式化"
    assert f"超过 {S.CHANGE_LAYER_KEEP} 层" in r["evicted"][0]["why"]
    assert [l["id"] for l in S.list_change_layers(_USER, nid)] == [f"live{i}" for i in range(1, 21)]


def test_处置完的层自己那一档也有上限():
    """**更宽，但不是没有**：一行 JSON 无限长下去读写都慢（同 `CHANGE_LAYER_HUNKS`）。
    那一句话跟活口那一句**不是同一句**——用户看到的得是「已经处置完的」。"""
    nid = _note()
    n = S.CHANGE_LAYER_SETTLED_KEEP + 2
    r = S.save_change_layers(_USER, nid, [_layer(f"d{i}", ["accepted"], seq=i) for i in range(n)])
    assert len(r["evicted"]) == 2
    assert all("已经处置完的改动层" in e["why"] for e in r["evicted"]), r["evicted"]
    assert all(f"超过 {S.CHANGE_LAYER_KEEP} 层" not in e["why"] for e in r["evicted"])
    assert S.CHANGE_LAYER_SETTLED_KEEP > S.CHANGE_LAYER_KEEP


def test_两档各淘汰各的_留下来的是哪几层():
    """两档一起数，**各扔各的**：活口 22 > 20 扔最早两层，处置完 22 ≤ 60 一层不扔。

    **这一条钉的不是「我那行列表顺序没打乱」**（突变验当场量出来那是个 no-op：
    `list_change_layers` 是 `ORDER BY seq, created_at, rowid`，层序由 `seq` 那一格扛着，
    把留下来的层按档重排读回来一模一样）。钉的是**扔掉的是哪几层、留下的是哪几层**。
    """
    nid = _note()
    layers = []
    for i in range(22):                       # 交替：活 / 处置完
        layers.append(_layer(f"live{i}", ["pending"], seq=2 * i))
        layers.append(_layer(f"done{i}", ["accepted"], seq=2 * i + 1))
    r = S.save_change_layers(_USER, nid, layers)
    ids = [l["id"] for l in S.list_change_layers(_USER, nid)]
    # 活口 22 > 20，扔最早两层；处置完 22 ≤ 60，一层不扔
    assert len(r["evicted"]) == 2
    assert [i for i in ids if i.startswith("live")] == [f"live{i}" for i in range(2, 22)]
    assert [i for i in ids if i.startswith("done")] == [f"done{i}" for i in range(22)]
    # 层序按 `seq` 读回来：done0 / done1 排在最前（live0 / live1 被扔了），后面照旧一活一处置完
    assert ids[:2] == ["done0", "done1"]
    assert ids.index("live2") < ids.index("done2") < ids.index("live3")
    # 扔的是**活口那一档最早的两层**，一层处置完的都没动
    assert {e["label"] for e in r["evicted"]} == {"格式化"}
    assert all(f"超过 {S.CHANGE_LAYER_KEEP} 层" in e["why"] for e in r["evicted"])


def test_淘汰照旧吵闹_一层不许悄悄少存():
    """`evicted` 里每一条都得带着 label 和 at——前端据此逐层说出来。"""
    nid = _note()
    r = S.save_change_layers(_USER, nid, [_layer(f"live{i}", ["pending"], seq=i) for i in range(23)])
    assert len(r["evicted"]) == 3
    assert all(set(e) == {"label", "at", "why"} and e["at"] for e in r["evicted"])


# ---------------------------------------------------------------- 1. `[]` ≠ `None`

def test_判过了是空列表_没判成才是null(monkeypatch):
    """P46 #1 的后端那半边：前端据此决定「如实说一句」还是「退回 `display_terms`」。
    **压成一档**（两边都回 `[]`）就等于让「判过了」那一档去退回一串没判过的碎词。

    **反例真的落在被测分支里**：两种局面各发一次真请求，读回包里那一格。
    """
    import pytest
    from fastapi.testclient import TestClient

    from app.database.kite import kite_memory as KM
    from app.main import app

    with TestClient(app, headers={"X-User-Id": "p46ev"}) as c:
        S.create_note("p46ev", "P46", "甲乙丙丁")
        # ① 判过了、一条都摆不出来 → `[]`
        monkeypatch.setattr(KM.UserMemory, "recall",
                            lambda self, q, **kw: ([{"id": "x", "type": "fact"}], ["甲乙"], 1.0))
        monkeypatch.setattr(KM.UserMemory, "recall_evidence", lambda self, q, rows: [])
        r = c.post("/api/memory/recall", json={"query": "甲乙丙丁戊己庚辛", "limit": 6})
        assert r.status_code == 200
        assert r.json()["evidence"] == []
        # ② 判据自己抛了 → `null`
        def boom(self, q, rows):
            raise RuntimeError("判据炸了")
        monkeypatch.setattr(KM.UserMemory, "recall_evidence", boom)
        r = c.post("/api/memory/recall", json={"query": "甲乙丙丁戊己庚辛", "limit": 6})
        assert r.status_code == 200
        assert r.json()["evidence"] is None
        assert pytest is not None
