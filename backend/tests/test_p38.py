"""P38：把抽样标注变成仓库里的资产（#1），加上记忆那条线上量出来才定的两条改动
（#2 证据串合并之后再去一次包含、#5 中文 grep 通道接分词，只接在拿给用户看的那条路上）。

**#1 为什么要有。** P27 / P29 / P32 / P34 各自抽了 45–47 条逐条读过，**四份标注全丢了**
（scratch 目录被清）。于是 P34 只能重抽一份，还得专门解释「这张抽样表说明不了什么」。
标注是这条线上最贵的东西——代码可以重跑，人读不能。所以它进仓库，并且配一条闸。

**闸的线怎么定的**（`test_误判率不许超过这条线` / `test_硬的不许掉太多`）：
定在**今天的数上加一点余量**，不是「不许变差」。「不许变差」那种闸会天天误报——
判据每动一格、抽样上都可能晃一条，而这份样本自己的口径就写着「改动幅度小的时候
分辨率不够」。所以闸管的是**方向**：误判率别爬回 P32 之前那一档，「硬」别成片地掉。
"""

from __future__ import annotations

import json
import types

from app.database.kb import search
from scripts import memory_sample_replay as R

# ---------------------------------------------------------------- #1 样本本身

def _load():
    meta, rows = R.load_sample()
    corpus = json.loads(R.CORPUS.read_text(encoding="utf-8"))
    return meta, rows, corpus


def test_样本读得出来_47条_口径写在里面():
    meta, rows, _ = _load()
    assert len(rows) == 47
    assert {r["label"] for r in rows} <= {"hard", "meh", "bad"}
    # **标注本身是资产，它不该因为代码变了而变**——只有人重读一遍才会变。
    # 钉死这三个数，不然「把 bad 全改成 hard」这种事闸一声不吭（突变验抓到过）。
    got = {k: sum(1 for r in rows if r["label"] == k) for k in ("hard", "meh", "bad")}
    assert got == {"hard": 36, "meh": 4, "bad": 7}, (
        f"P34 读出来的是 36 硬 / 4 勉强 / 7 不硬，现在是 {got}——"
        "改标注只能靠人重读一遍，并且在台账里说清楚是谁读的")
    # 口径里必须写清楚它**答不了**什么——P34 踩过一次（拿一份分辨率不够的抽样报误判率）
    assert "答不了什么" in meta and "全库误判率" in meta["答不了什么"]
    assert "不是随机" in meta["怎么抽的"]
    # (用户, 查询, 事实) 不许重复：重复会让「留下几条」这个分母悄悄变
    keys = {(r["user"], r["query"], r["fact_id"]) for r in rows}
    assert len(keys) == 47
    for r in rows:
        assert r["query"] and r["fact"] and isinstance(r["hit"], list)
        assert r["labeled_by"] and r["lineage"] in {"user", "script", "fixture"}


def test_误判率不许超过这条线():
    """线定在 **18%**：今天是 13%（6/46），留两条的余量。
    爬到 18% 以上意味着判据松回了 P32 之前那一档（那时候是 57%）。"""
    _, rows, corpus = _load()
    now = R.tally(R.replay(rows, corpus))
    assert now["留下"] > 0
    assert now["误判率"] <= 0.18, f"抽样上的误判率爬上来了：{now}"


def test_硬的不许掉太多():
    """今天 36 条「硬」。掉到 34 以下就是成片地砍——那是 P27 起每一批都在盯的
    「留下率不许跌」，只是这里落在标注上。"""
    _, rows, corpus = _load()
    now = R.tally(R.replay(rows, corpus))
    assert now["hard"] >= 34, f"「硬」掉了：{now}"


def test_冻下来的库真的在起作用():
    """**接线洞，单独一条。** `qualifies` 的三个注入口全来自这个人的 11 MB codebook，
    夹具把它们冻成了一张表。那张表要是退化成「查什么都是 0」，重放照样跑得出一个
    看着挺像的数——闸绿了，闸没用。所以这里钉：**撤掉它，结果必须不一样**。"""
    _, rows, corpus = _load()
    with_corpus = R.tally(R.replay(rows, corpus))

    class _Dead(R.FrozenCorpus):
        def common_term(self):
            return None

        def vocab_term(self):
            return None

        def segment(self):
            return None

    real, R.FrozenCorpus = R.FrozenCorpus, _Dead
    try:
        without = R.tally(R.replay(rows, corpus))
    finally:
        R.FrozenCorpus = real
    assert with_corpus != without, "三个注入口全撤掉结果没变——那张冻结的表没接上"


def test_冻下来的库没有退化成空表():
    """第二条接线断言，钉的是**另一件事**：表里真有东西、`unit_df` 的三种回答都还在
    （查得到的数 / 查不到 = 0 / 预筛不了 = None）。上一条钉「接上了」，这一条钉「没被清空」。"""
    _, _, corpus = _load()
    c = R.FrozenCorpus(corpus, "terrence")
    assert c.unit_count == 2362
    assert c.unit_df("众筹") >= 100                  # 真库里 df=107
    assert c.unit_df("这个串库里没有有有") == 0        # 查不到 = 0
    assert c.common_term() is not None and c.vocab_term() is not None
    assert c.segment() is not None
    # 词表那一档要真答得出来：`pr` / `pro` 是这个人的实体（`kb-entities-plan` §5 点名），
    # 冻结的词表退化成「什么都不是」的话，[42] 会悄悄换一条理由留下来，数还看着对
    assert c.vocab_term()("pr") is True
    # floor 的语义要跟真索引一字不差：子串数没到 floor 就回那个上界，不再按词边界核
    assert c.unit_df("pr", floor=10_000) == c._df["pr"][0]
    # 三种回答都要在：查得到 / 查不到=0 / **预筛不了=None**（不许当成 0——
    # 当成 0 就是把一条召回判死，`content_chars` 那条 `None` 同理）
    blob = json.loads(R.CORPUS.read_text(encoding="utf-8"))
    blob["users"]["terrence"]["df"]["(带正则元字符的串)"] = [None, None]
    assert R.FrozenCorpus(blob, "terrence").unit_df("(带正则元字符的串)") is None


def test_P34花钱砍掉的那一条不许回来():
    """[46]（`前提是` 在查询里出现两次、被数成两条证据）是 P34 逐条读产出才抓到的，
    砍它花了一整轮。这里单独钉一格，别让后面哪一批顺手把它放回来。"""
    _, rows, corpus = _load()
    judged = {r["i"]: r for r in R.replay(rows, corpus)}
    assert judged[46]["kept"] is False
    # 反过来：P34 认下来的「硬」那几条得还在
    assert judged[4]["kept"] and judged[0]["kept"]


# ---------------------------------------------------------------- #2 并完再去包含

def test_并完之后一串是另一串的子串_不算第二条证据():
    """P27 是一个词被切成两半，P32 是两个滑窗重叠，P34 是同一个词出现两次，
    **这是第四个变种**：合并把包含关系重新造出来。

    **反例是从真库里原样抄下来的，不是编的**——这一点在这条判据上是决定性的：
    命中词是 `['前提是', '提是我']`，**谁也不包含谁**，所以 `_clusters` 那道
    「互不包含」去重两条都留着；`前提是` 在查询里出现两处，第二处跟 `提是我`
    重叠、并成 `前提是我`，于是回来的是 `['前提是', '前提是我']`——
    **包含关系是合并之后才有的**。
    编一个 `['前提是', '前提是我']` 当反例是测不到这条分支的（`_clusters` 先把它做掉了），
    突变验当场抓到过一次。P32 `looksLikeJson`、P34 `未来会`，这是第三次。
    """
    q = "为什么现在写：因为我需要先回答读者会追问的‘为什么现在写’和‘前提是什么’。前提是我承认在产品叙事上过度理想化。"
    assert search._clusters(["前提是", "提是我"]) == ["前提是", "提是我"]
    assert search.evidence_runs(["前提是", "提是我"], q) == ["前提是我"]


def test_这一刀不许误伤还有别的证据的():
    """全库量过：合并之后有包含关系的 8 对里，只有上面那 1 对会从「放行」变「砍掉」，
    别的 7 对本来就还有别的合格证据。`找人` / `商业找` 是其中一对（同样是原样抄的）。"""
    q = "产品方向：商业找人产品，用于境外用户特别是欧美用户的商业人脉匹配场景。范围锚点为商业找人"
    runs = search.evidence_runs(["找人", "商业找", "欧美用"], q)
    assert "找人" not in runs and "商业找人" in runs and "欧美用" in runs


def test_不重叠也不包含的两串照旧是两条():
    """别把这一刀切过头：`成本高` 紧跟着 `效率低` 是两个词，谁也不包含谁，
    合成一串就又把两条证据压成一条（P27 那条老理由）。"""
    q = "23万台区超过35万充电桩，成本高效率低"
    assert search.evidence_runs(["成本高", "效率低"], q) == ["成本高", "效率低"]


# ---------------------------------------------------------------- #5 grep 通道接分词

class _Mem:
    def __init__(self, cjk):
        self._candidate_terms = lambda text: []
        self._cjk_terms = lambda text, weigh=None: list(cjk)
        self._match_vocab = lambda q, v: ([], [], [])


_VOCAB = types.SimpleNamespace(topics={}, entities={})
_Q = "自动化测试应长期保留，不能替代人工操作"


def test_不给切词函数就原样走滑窗():
    """**不启用就是原样**——这一条钉的是「没人接的时候这一处一个字都不变」。"""
    grams = ["动化测", "自动化", "化测试", "长期保"]
    qs = search.plan(_Mem(grams), _Q, _VOCAB)
    assert [q["where"]["grep"] for q in qs] == grams


def test_给了切词函数就换成分词出来的实词_长的排前面():
    grams = ["动化测", "自动化", "化测试", "长期保"]
    cut = lambda t: ["自动化测试", "应", "长期", "保留", "，", "不能", "替代", "人工", "操作"]
    qs = search.plan(_Mem(grams), _Q, _VOCAB, segment=cut)
    got = [q["where"]["grep"] for q in qs]
    assert got[0] == "自动化测试"
    assert set(got) <= {"自动化测试", "长期", "保留", "不能", "替代", "人工", "操作"}
    assert not any(g in grams for g in got), "滑窗那几条应该被换掉，不是加在后面"


def test_切不出实词就退回滑窗_不留空手():
    """一段全是口水词 / 单字时，分词那条路一个词都给不出——那时候**退回滑窗**，
    别把中文通道整条关掉（关掉等于把这条召回判死）。"""
    grams = ["的一个", "这个"]
    qs = search.plan(_Mem(grams), "的一个这个", _VOCAB, segment=lambda t: ["的", "一个", "这个"])
    assert [q["where"]["grep"] for q in qs] == grams


def test_口水词不当grep词():
    grams = ["这个功", "个功能"]
    cut = lambda t: ["这个", "功能", "可以", "基于", "电池容量"]
    qs = search.plan(_Mem(grams), "这个功能可以基于电池容量", _VOCAB, segment=cut)
    got = [q["where"]["grep"] for q in qs]
    assert "这个" not in got and "可以" not in got
    assert got[0] == "电池容量"


def test_recall只在开着证据闸的那条路上给segment(monkeypatch):
    """**接线洞，单独一条。** `plan` 的 `segment` 跟 `rank` 的那三个是同一种东西——
    规则层的单测抓不住「`recall` 到底有没有传」。而这一处**必须跟着 `evidence` 开关**：
    喂给 `kb/relations.detect` 的那条候选池路开了它，N4 那个从 P22 就在的绿点当场掉
    （`corroborated → no_record`）。P32 那一刀的同款第二次。"""
    from app.database.kite import kite_memory as KM

    seen: list[bool] = []
    real_plan = KM.search.plan

    def spy(memory, query, vocab, *, pool=search.POOL, segment=None, common=None):
        # `common` 是 P42 A2 加的，跟 `segment` 同一个闸；这条测的还是 `segment`
        seen.append(segment is not None)
        return real_plan(memory, query, vocab, pool=pool, segment=segment, common=common)

    class _St:
        facts: dict = {}

    mem = KM.UserMemory.__new__(KM.UserMemory)
    mem._index = lambda: (_St(), _VOCAB)
    mem._match_vocab = lambda q, v: ([], [], [])
    mem._prescreen = lambda store, queries: queries
    mem.common_term = lambda: (lambda t: False)
    mem.vocab_term = lambda: (lambda t: False)
    mem.segment = lambda: (lambda t: ["自动化测试"])
    mem._recall_via_lines = lambda *a, **k: []
    mem._cjk_terms = staticmethod(KM.UserMemory._cjk_terms).__func__
    mem._candidate_terms = staticmethod(KM.UserMemory._candidate_terms).__func__
    monkeypatch.setattr(KM.search, "plan", spy)

    mem.recall(_Q, limit=3, evidence=True)
    assert seen == [True], "拿给用户看的那条路没把切词接到 grep 上"
    seen.clear()
    mem.recall(_Q, limit=3)
    assert seen == [False], "候选池那条路不该接切词（N4 那个绿点就是这么掉的）"


def test_圆点那两条路仍然不开这一档(monkeypatch, tmp_path):
    """路由级：`/memory/recall` 开、`/memory/relations` 和 `/relations/batch` 不开。
    P32 / P34 各钉过一次 `evidence`，`segment` 现在跟着它走——**同一条线上的第三次**，
    所以这里钉的是「`recall` 的 `evidence` 参数在这三条路上分别是什么」。"""
    from fastapi.testclient import TestClient

    from app.database import store as _store
    from app.database.kite.kite_memory import UserMemory
    monkeypatch.setattr(_store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app

    seen: list[bool] = []
    real = UserMemory.recall

    def spy(self, query, limit=8, scope="all", *, evidence=False):
        seen.append(evidence)
        return real(self, query, limit=limit, scope=scope, evidence=evidence)

    monkeypatch.setattr(UserMemory, "recall", spy)
    monkeypatch.setattr("app.routers.memory._has_facts", lambda mem: True)
    c = TestClient(app)
    assert c.post("/api/memory/recall", json={"query": "电池容量 420mAh", "limit": 5}).status_code == 200
    assert seen == [True]
    seen.clear()
    assert c.post("/api/memory/relations", json={"passage": "电池容量定在 420mAh。"}).status_code == 200
    assert c.post("/api/memory/relations/batch",
                  json={"passages": ["电池容量定在 420mAh。"]}).status_code == 200
    assert seen == [False, False], f"喂判据的那两条路不该开：{seen}"


def test_重放脚本自己能跑():
    """夹具 + 脚本是一对，脚本跑不起来夹具就是一堆死数据。"""
    assert R.SAMPLE.exists() and R.CORPUS.exists()
    _, rows, corpus = _load()
    judged = R.replay(rows, corpus)
    assert len(judged) == 47
    assert all("evidence" in r and "kept" in r for r in judged)
