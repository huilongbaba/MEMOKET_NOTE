"""P32 #1：召回的**证据资格**（`kb/search.evidence_runs` / `evidence` / `qualifies`）。

用户怎么发现（P31 #6 实拍）：正文「先把叙事和体感分开看，**再决定**这个动效要不要保留」，
右栏给出「Speaker B 问是否可以搜一下…然后根据情况**再决定**」，面板写着「命中：再决定」——
**它说对了自己在干什么，干的这件事本身是错的**。判据和量出来的数写在 `kb/search` 里那段注释上。
"""

from __future__ import annotations

import types

from app.database.kb import search


# ---------------------------------------------------------------- evidence_runs

def test_重叠的两个片段是同一个词_合成一条证据():
    """`池容量` + `电池容` 是「电池容量」被 3 字滑窗切出来的两半。

    `_clusters` 的「互不包含」去重挡不住它们（谁也不包含谁），于是 `_strong_enough`
    数出两条证据——**那个 2 数的是同一个词**。这跟 P27 在圆点那侧修的是同一个毛病。
    """
    q = "本周把电池容量定在 420mAh。"
    assert search.evidence_runs(["池容量", "电池容"], q) == ["电池容量"]


def test_相邻的两个词不合并():
    """「成本高」紧跟着「效率低」是两个词。合成一串就把两条证据压成一条（P27 的理由原样成立）。"""
    q = "成本高效率低，两头都要改。"
    assert search.evidence_runs(["成本高", "效率低"], q) == ["成本高", "效率低"]


def test_在查询里定位不到的命中各自算一串_不静默丢掉():
    """`_hits` 有一条「去掉空格再比一次」的路，命中的词未必能在查询里原样找到。
    找不到就当没有证据 = 把这条召回判死，那是最贵的那种错。"""
    assert search.evidence_runs(["memocat"], "另一段完全无关的正文") == ["memocat"]


# ---------------------------------------------------------------- evidence / qualifies

def _q(hits, query, **kw):
    return search.qualifies(hits, query, **kw)


def test_P31那条_一个三字滑窗撑不起一条召回():
    """`再决定` 跨在「再」和「决定」之间，是 3 字滑窗（`_cjk_terms` 最长就是 3）——
    **它在真库里 df=1，是个「稀有词」，所以 P29 的 df 判据救不了这条**。"""
    q = "这一版把动效做满了，但读起来反而更慢。先把叙事和体感分开看，再决定这个动效要不要保留。"
    assert _q(["再决定"], q) is False
    # 同一条正文里凑够两条独立证据就留下
    assert _q(["再决定", "动效"], q) is True


def test_合并出四个汉字就站得住_因为一个窗口装不下():
    q = "本周把电池容量定在 420mAh。"
    assert _q(["池容量", "电池容"], q) is True          # 合并成「电池容量」= 4 字
    assert _q(["电池容"], q) is False                    # 单个 3 字窗口不行


def test_两个字母的英文词单独不算证据_三个字母算():
    """`ai` / `ib` / `pr` / `mp` / `md` / `kv` 这一档是撞词的重灾区；
    `kol` / `evt` / `dvt` / `cpu` / `ict` 这一档是这个库里实打实的专业词。"""
    assert _q(["ib"], "IB 可以用光纤，但不等于全光通信。") is False
    assert _q(["kol"], "KOL 推广的复盘要把样机发出和真实使用拆开。") is True


def test_纯数字串单独不算证据():
    """P7 #5 早定过「一个词 + 同一天」分不开「2月1号上线」和「2月1号发工资」；
    实测三条误判全靠一个 `90%` 沾上「AI 写的代码现在 90% 以上」。"""
    assert _q(["90%"], "常用病理知识诊断回答准确率达到 90%，已覆盖 19 个常见癌种。") is False
    assert _q(["90%", "病理"], "常用病理知识诊断回答准确率达到 90%，已覆盖 19 个常见癌种。") is True


def test_泛词按df否掉资格_跟P29同一条判据():
    common = {"ai"}.__contains__
    q = "井工矿远控方案：借助 5G 和 AI 改造部署了全景视频远程掘进方案。"
    assert _q(["ai"], q) is False                       # `common` 没接上时也不行（2 字母）
    assert _q(["ai", "全景视"], q, common=common) is False     # `ai` 被 df 否掉，只剩一条 3 字滑窗
    assert _q(["ai", "全景视"], q) is True                     # 不启用 df 就是原样
    # 被否掉之后剩下的那条**自己站得住**就照样留：泛词那关只是不算它一票
    assert _q(["ai", "远程掘进"], q, common=common) is True


def test_词表里的词单独就站得住_但只当放行条件():
    """P29 #1 量过：拿「是不是实体」当唯一的闸会连 `cpu+npu` / `第二款产品` 一起砍。
    所以它只在「只剩一条证据串」那一档放行，**从不用来否掉任何东西**。"""
    q = "参会：李工、周敏、市场同学，讨论定价。"
    assert _q(["李工"], q) is False
    assert _q(["李工"], q, attested={"李工"}.__contains__) is True
    # 泛词那一关先过：词表里有也救不回来
    assert _q(["李工"], q, attested={"李工"}.__contains__, common={"李工"}.__contains__) is False


def test_用户主动搜一个词时不走这条():
    """`_SHORT_QUERY`（4 字）以内就是用户自己敲的那个词，要求它「再拿出第二条证据」
    等于搜不出东西（第 527 轮定的那条边界，这里沿用，不新造一个数）。"""
    assert _q(["再决定"], "再决定") is True
    assert _q([], "再决定") is False                      # 一个词都没命中还是不行


def test_evidence_把为什么算证据也说出来():
    """右栏那句「为什么给我看这条」的原料（计划 §2 A5）。"""
    q = "本周把电池容量定在 420mAh，KOL 样机下周发。"
    ev = search.evidence(["池容量", "电池容", "kol"], q, attested={"kol"}.__contains__)
    assert [e["term"] for e in ev] == ["电池容量", "kol"]
    assert [e["why"] for e in ev] == ["span", "vocab"]


# ---------------------------------------------------------------- 接线（P25 / P29 的教训：测的是零件不是那条路）

class _Store:
    def __init__(self, texts):
        self.facts = {f"f{i}": types.SimpleNamespace(text=t, topics=(), entities=())
                      for i, t in enumerate(texts)}


class _Mem:
    def __init__(self, en, cjk):
        self._candidate_terms = lambda text: list(en)
        self._cjk_terms = lambda text: list(cjk)


LONGISH = "这一版把动效做满了，但读起来反而更慢。先把叙事和体感分开看，再决定这个动效要不要保留。"


def test_rank_默认不开证据闸_开了才筛():
    """闸默认关着**是量出来的**：喂给 `kb/relations.detect` 的那条路开了闸会掉一个
    从 P22 就在的绿点（`detect` 靠「同值同单位」判的，词面证据不够不等于关系判不出来）。"""
    st = _Store(["Speaker B 问是否可以搜一下，然后根据情况再决定。"])
    rows = [{"id": "f0"}]
    assert [r["id"] for r in search.rank(rows, LONGISH, _Mem([], ["再决定"]), st, limit=5)] == ["f0"]
    assert search.rank(rows, LONGISH, _Mem([], ["再决定"]), st, limit=5, evidence=True) == []


def test_只有拿给用户看的那条路开闸_喂判据的那两条不开(tmp_path, monkeypatch):
    """**这一条是突变验逼出来的**：把 `/memory/recall` 里的 `evidence=True` 撤掉，
    规则层和接线层的单测**一条都不红**——只有这条路知道「这次是拿给用户看的」。
    同一个文件里另外两条（`/relations`、`/relations/batch`）**必须不开**，
    开了会掉一个从 P22 就在的绿点（理由写在 `UserMemory.recall` 的文档串里）。
    """
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
    assert seen == [True], "拿给用户看的那条路没开证据闸"
    seen.clear()
    assert c.post("/api/memory/relations", json={"passage": "电池容量定在 420mAh。"}).status_code == 200
    assert c.post("/api/memory/relations/batch",
                  json={"passages": ["电池容量定在 420mAh。"]}).status_code == 200
    assert seen == [False, False], f"喂判据的那两条路不该开闸：{seen}"


def test_路由把common和attested真的传下去了():
    """`/memory/recall` 那条路到底有没有把这个人的 df 索引和词表接上——
    规则层的单测抓不住这个（撤掉 `evidence=True` 规则层照样绿）。

    **P34 #1 多钉了一格 `segment`**（中文切词）：它跟 `common` / `attested` 是同一种东西
    ——`kb/search` 拿不到这个人的库，只能由 `UserMemory` 注入；漏传就是静默退回 P32
    的原始字数规则，**规则层的单测一条都不会红**。
    """
    from app.database.kite import kite_memory as KM

    seen = {}
    real_rank = KM.search.rank

    def spy(rows, query, memory, store, *, limit, evidence=False, common=None,
            attested=None, segment=None):
        seen.update(evidence=evidence, common=common is not None,
                    attested=attested is not None, segment=segment is not None)
        return real_rank(rows, query, memory, store, limit=limit, evidence=evidence,
                         common=common, attested=attested, segment=segment)

    mem = KM.UserMemory.__new__(KM.UserMemory)
    mem._index = lambda: (_Store([]), types.SimpleNamespace(topics={}, entities={}))
    mem._match_vocab = lambda q, v: ([], [], [])
    mem._prescreen = lambda store, queries: queries
    mem.common_term = lambda: (lambda t: False)
    mem.vocab_term = lambda: (lambda t: False)
    mem._recall_via_lines = lambda *a, **k: []
    mem._cjk_terms = staticmethod(KM.UserMemory._cjk_terms).__func__
    mem._candidate_terms = staticmethod(KM.UserMemory._candidate_terms).__func__
    old = KM.search.rank
    KM.search.rank = spy
    try:
        mem.recall("电池容量定在 420mAh 这一版", limit=3, evidence=True)
    finally:
        KM.search.rank = old
    assert seen == {"evidence": True, "common": True, "attested": True, "segment": True}
