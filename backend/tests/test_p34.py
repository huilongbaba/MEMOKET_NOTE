"""P34 #1 / #2：中文分词（`kb/tokenize`）接进召回的证据资格，以及「同一个词出现两次
被数成两条证据」那个 bug。

P32 给单串那一档定的门槛是「**≥4 个汉字**」，理由是「`_cjk_terms` 最长的窗口是 3，
合并出 ≥4 个字意味着两个窗口都对上了」。**那个理由只说对了一半**：两个窗口都对上，
不代表对上的是两个词。真库上量出来（台账 P34 #1）：靠这条放行的 64 条里 33 条是
「一个虚词 + 一个词」——`这个功能` ×6、`需要明确` ×6、`可以基于` ×4、`而不只是`、`其次呢就`。
**阈值一个没动（还是 4），量程换成了「分词之后的实词字数」。**
"""

from __future__ import annotations

import types

from app.database.kb import search
from app.database.kb import tokenize as T


def _seg():
    return T.default().cut


# ---------------------------------------------------------------- 分词器本身

def test_底表读得出来_而且带词频():
    w = T.base_words()
    assert len(w) > 300000
    assert w["功能"] > 0 and w["第二款"] > 0
    # 只收纯汉字 2–4 字（英文 / 单字 / 5 字以上都不进底表，见 MAXLEN 那段注释）
    assert all(2 <= len(k) <= 4 for k in list(w)[:2000])


def test_词典要被打进包里():
    """**漏了不会炸，只会变差**：`base_words()` 读不出词典就回空表、`segment()` 跟着回 None
    = 静默退回 P32 的字数规则。界面照常、测试照常绿，只有召回悄悄变松——最难发现的那种。
    所以在这里钉一句：`backend.spec` 的 `datas` 必须点名它。"""
    from pathlib import Path

    spec = Path(__file__).resolve().parent.parent / "backend.spec"
    assert T._DICT.exists() and T._DICT.stat().st_size > 1_000_000
    assert "app/database/kb/cn_words.txt.gz" in spec.read_text(encoding="utf-8")


def test_虚词不会粘在词上():
    cut = _seg()
    assert cut("这个功能") == ["这个", "功能"]
    assert cut("需要明确") == ["需要", "明确"]
    assert cut("而不只是") == ["而", "不", "只是"]


def test_非汉字原样成段_不插手英文和数字():
    """英文本来就是整词切的（`_candidate_terms`），这一层不该再插一手。"""
    assert T.default().cut("ai 场景 38 个") == ["ai ", "场景", " 38 ", "个"]


def test_这个人库里的专名压得过底表的切法():
    """底表是通用汉语词，`算力` 它没有——不补的话「算力底座」切成 `算/力/底座`，
    实词字数从 4 掉到 2，**把 P29 点名的一条真沾边砍掉**。"""
    assert T.Tokenizer().cut("算力底座") == ["算", "力", "底座"]
    assert T.Tokenizer(["算力"]).cut("算力底座") == ["算力", "底座"]


def test_库里长出来的词只在另一条路是单字时才赢():
    """`attest` 那一档给的分很低（`ATTEST_FREQ`）：它是给未登录词兜底的，不是来推翻底表的。

    · `众筹` 底表没有、另一条路是 `众/筹` 两个单字 → 它赢，对；
    · `品方` / `的一` 就算在库里攒够了次数，也不许把 `产品/方向`、`的/一个` 挤掉。
      （`的一` 这一条是突变验逼出来的：`ATTEST_FREQ` 调到跟实体词一样高，它当场翻盘。）
    """
    assert T.Tokenizer.ATTEST_FREQ < T.Tokenizer.EXTRA_FREQ
    tok = T.Tokenizer(attest=lambda w: w in ("众筹", "品方", "的一"))
    assert tok.cut("作为众筹后交付") == ["作为", "众筹", "后", "交付"]
    assert tok.cut("产品方向") == ["产品", "方向"]
    assert tok.cut("的一个方案") == ["的", "一个", "方案"]


def test_attest只问2到3个字的串():
    asked = []
    T.Tokenizer(attest=lambda w: asked.append(w) or False).cut("智能化改造方案")
    assert asked and all(2 <= len(w) <= 3 for w in asked)


# ---------------------------------------------------------------- content_chars

def test_实词字数只数实词():
    cut = _seg()
    q = "如果用户感受不到，这个功能就没有成立。"
    assert T.content_chars("这个功能", q, cut, search._is_cn_filler) == 2     # 这个是口水词
    q2 = "2月1日上规模广告投放以及新的官网收定金。"
    assert T.content_chars("广告投放", q2, cut, search._is_cn_filler) == 4


def test_压在边界上的词要压够两个字():
    """证据串是滑窗合并出来的，不会正好停在词边界上。

    · `启动第二` 压住 `第二款` 两个字 → 算（P27 拼命捞回来的那条真沾边）；
    · `未来会` 在「用『未来会好』回避」里只压住 `会好` 一个字 → 不算
      （算了的话 P32 点名砍掉的那条当场回来）。
    """
    cut = _seg()
    q1 = "q3启动第二款产品研发，目标指向2027ces发布"
    assert T.content_chars("启动第二", q1, cut, search._is_cn_filler) >= 4
    q2 = "其余时间我都在用未来会好回避当下的体感缺口"
    assert T.content_chars("未来会", q2, cut, search._is_cn_filler) == 2
    # 「引入华为翻译部」切成 `引入` / `华为`，串 `入华为` 只压住 `引入` 一个字。
    # 碰到就算的话 2 + 2 = 4，「引入华为」当场沾上「进入华为工作十年」——实拍过。
    q3 = "华为的改进路径引入华为翻译部的专业能力"
    assert T.content_chars("入华为", q3, cut, search._is_cn_filler) == 2


def test_定位不到就回None_不许当成0():
    """当成 0 就是把这条召回判死，那是最贵的那种错（同 `evidence_runs` 的 `loose`）。"""
    assert T.content_chars("电池容量", "完全无关的另一段", _seg()) is None


# ---------------------------------------------------------------- 接进 search

LONG = "比如我想卖房时，需要和不同中介聊天、打电话。如果用户感受不到它确实替自己省下时间，这个功能就没有成立。"


def test_一个虚词加一个词撑不起一条召回_但不启用就是原样():
    assert search.qualifies(["这个功", "个功能"], LONG) is True               # 今天（P32）：4 个汉字
    assert search.qualifies(["这个功", "个功能"], LONG, segment=_seg()) is False


def test_两个实词照样站得住():
    q = "2月1日上规模广告投放以及新的官网收定金。"
    assert search.qualifies(["广告投", "告投放"], q, segment=_seg()) is True


def test_词本身满库都是就不算实词字数():
    """**P32 说「df 单独救不了」是对的，因为那时候 df 落在滑窗上**——`如果用户` 作为一个
    4 字串 df 很低，过得去。分词把词边界给出来之后，df 才有地方落：`如果` 和 `用户`
    都在 P29 那 20 个「满库都是」的串里。"""
    common = {"如果", "用户"}.__contains__
    assert search.qualifies(["如果用", "果用户"], LONG, segment=_seg()) is True
    assert search.qualifies(["如果用", "果用户"], LONG, segment=_seg(), common=common) is False


def test_带数字的串退回P32的原始字数():
    """P32 专门量过、专门留下的那一档：「再严一档（只要含数字就不单独算）全库只多砍 5 对，
    逐条读下来 2 条是真的」。**别人量完留下的东西，不顺手带走。**"""
    q = "3 月 10 日众筹版本与 3 月 15 日媒体及投资人版本，不能只按发布日期区分。"
    assert search.qualifies(["3月15"], q, segment=_seg()) is True


def test_在查询里定位不到的串退回字数_不许判死():
    """`evidence_runs` 的 `loose` 那一档（`_hits` 的「去空格再比一次」）在查询里找不到位置，
    分词也就无从下口。**这时候要退回 P32 的字数规则，不能当成 0 个实词字**——
    当成 0 就是把这条召回判死，那是最贵的那种错。"""
    q = "这一段正文跟那条事实的字面完全对不上，但召回通道把它捞了回来，长度也够长了。"
    assert search.qualifies(["电池容量"], q, segment=_seg()) is True


def test_词表里的词照旧直接放行_分词管不着它():
    q = "参会：李工、周敏、市场同学，讨论这个功能的定价。"
    assert search.qualifies(["这个功", "个功能"], q, segment=_seg(),
                            attested={"这个功能"}.__contains__) is True


# ---------------------------------------------------------------- #2 同一个词数两次

def test_同一个词在查询里出现两次只算一条():
    """读产出当场抓到的：`evidence_runs` 原来按**位置**收，于是

        「先回答读者会追问的『为什么现在写』和『**前提是**什么』。**前提是**我承认…」

    一个语篇词回两串，`qualifies` 的 `len(ev) >= 2` 当场放行。
    **这是 P27「那个 2 数的是同一个词被切成的两半」的第三个变种。**
    """
    q = "读者会追问的‘为什么现在写’和‘前提是什么’。前提是我承认在产品叙事上过度理想化。"
    assert search.evidence_runs(["前提是"], q) == ["前提是"]
    assert search.qualifies(["前提是"], q) is False


def test_去重之后真有两个不同的词还是两条():
    q = "本周把电池容量定在 420mAh，电池容量这件事下周还要再谈，KOL 样机也要发。"
    assert search.evidence_runs(["电池容", "池容量", "kol"], q) == ["电池容量", "kol"]


# ---------------------------------------------------------------- 接线

class _Store:
    def __init__(self, texts):
        self.facts = {f"f{i}": types.SimpleNamespace(text=t, topics=(), entities=())
                      for i, t in enumerate(texts)}


class _Mem:
    def __init__(self, en, cjk):
        self._candidate_terms = lambda text: list(en)
        self._cjk_terms = lambda text: list(cjk)


def test_rank_把segment传给qualifies_而且只在开闸时():
    st = _Store(["auto 也有这个功能，plotica 也有这个功能，但我们不一定要做这个功能"])
    rows = [{"id": "f0"}]
    mem = _Mem([], ["这个功", "个功能"])
    # 闸不开：`segment` 传了也不该动任何东西
    assert [r["id"] for r in search.rank(rows, LONG, mem, st, limit=5, segment=_seg())] == ["f0"]
    # 闸开、没给 segment：退回 P32 的字数规则，这条留下
    assert [r["id"] for r in search.rank(rows, LONG, mem, st, limit=5, evidence=True)] == ["f0"]
    # 闸开、给了 segment：砍掉
    assert search.rank(rows, LONG, mem, st, limit=5, evidence=True, segment=_seg()) == []


def test_segment建不出来就是不启用_不是报错():
    """词典读不出来 / 索引建不出来一律回 `None` = 原样，**不能让召回整条挂掉**。"""
    from app.database.kite import kite_memory as KM

    mem = KM.UserMemory.__new__(KM.UserMemory)
    mem._index = lambda: (_ for _ in ()).throw(RuntimeError("no index"))
    assert mem.segment() is None


def _fake_mem(df):
    """一个只够 `segment()` 跑起来的 `UserMemory`：假词表 + 假 df 索引。"""
    from app.database.kite import kite_memory as KM

    vocab = types.SimpleNamespace(topics={}, entities={})
    idx = types.SimpleNamespace(unit_count=2362,
                                unit_df=lambda w, floor=0: df.get(w, 0))
    mem = KM.UserMemory.__new__(KM.UserMemory)
    mem._index = lambda: (_Store([]), vocab)
    mem._grep_index = lambda store: idx
    return mem


def test_库里长出来的词那两道闸():
    """`_corpus_word` 的两条，**直接测判据本身**：

    · 串里有口水字就一律不认——`的一` 在真库里 df=359，次数远远够，可它是跨词切出来的；
      按次数收词一定会收到这种。（这一条在切词结果上看不出来，因为 `ATTEST_FREQ` 很低，
      它本来也赢不了；**判据成不成立不该靠另一个参数碰巧压住它**，所以在这一层单独钉。）
    · 次数不够的不认——`品方` 1 条、`户提` 2 条是撞出来的。
    """
    import types as _t

    from app.database.kite import kite_memory as KM

    assert KM.WORD_DF_MIN == 5
    df = {"的一": 359, "了这": 120, "众筹": 107, "户提": 2, "品方": 1, "算力": 5}
    idx = _t.SimpleNamespace(unit_count=2362, unit_df=lambda w, floor=0: df.get(w, 0))
    w = KM._corpus_word(idx)
    assert w("众筹") is True and w("算力") is True
    assert w("的一") is False and w("了这") is False      # 口水字
    assert w("户提") is False and w("品方") is False      # 次数不够


def test_出现得不够多的串不当成词():
    assert _fake_mem({"众筹": 4}).segment()("作为众筹后交付") == ["作为", "众", "筹", "后", "交付"]
    assert _fake_mem({"众筹": 5}).segment()("作为众筹后交付") == ["作为", "众筹", "后", "交付"]


def test_闸不开时不建切词器():
    """`segment()` 要读 1.5 MB 词典 + 建索引，闸不开就没人问它——白建一份。"""
    from app.database.kite import kite_memory as KM

    calls = []
    mem = KM.UserMemory.__new__(KM.UserMemory)
    mem._index = lambda: (_Store([]), types.SimpleNamespace(topics={}, entities={}))
    mem._match_vocab = lambda q, v: ([], [], [])
    mem._prescreen = lambda store, queries: queries
    mem.common_term = lambda: None
    mem.vocab_term = lambda: None
    mem.segment = lambda: calls.append(1) or None
    mem._recall_via_lines = lambda *a, **k: []
    mem._cjk_terms = staticmethod(KM.UserMemory._cjk_terms).__func__
    mem._candidate_terms = staticmethod(KM.UserMemory._candidate_terms).__func__
    mem.recall("电池容量定在 420mAh 这一版", limit=3)
    assert calls == []
    mem.recall("电池容量定在 420mAh 这一版", limit=3, evidence=True)
    assert calls == [1]


def test_recall里每一次rank都要带上segment():
    """**这一条是突变验逼出来的**：`recall` 里有**两次** `rank`（先按符号通道排，
    排空了再走行级回退）。把第一次的 `segment=segment` 撤掉，
    P32 那条路由断言**照样绿**——因为那条路上事实池是空的，走的是第二次。
    漏传的后果是静默退回 P32 的字数规则，界面上看不出来。
    """
    from app.database.kite import kite_memory as KM

    calls = []
    real_rank = KM.search.rank

    def spy(rows, query, memory, store, *, limit, evidence=False, common=None,
            attested=None, segment=None):
        calls.append(segment is not None)
        return real_rank(rows, query, memory, store, limit=limit, evidence=evidence,
                         common=common, attested=attested, segment=segment)

    mem = _fake_mem({})
    mem._match_vocab = lambda q, v: ([], [], [])
    mem._prescreen = lambda store, queries: queries
    mem.common_term = lambda: None
    mem.vocab_term = lambda: None
    mem._recall_via_lines = lambda *a, **k: []
    mem._candidate_terms = staticmethod(KM.UserMemory._candidate_terms).__func__
    mem._cjk_terms = staticmethod(KM.UserMemory._cjk_terms).__func__
    old = KM.search.rank
    KM.search.rank = spy
    try:
        mem.recall("电池容量定在 420mAh 这一版", limit=3, evidence=True)
    finally:
        KM.search.rank = old
    assert len(calls) == 2 and all(calls), f"有一次 rank 没带 segment：{calls}"


def test_recall_evidence也要把segment传下去():
    """右栏那句「为什么给我看这条」跟闸必须用同一把尺——不然面板说「整段原话对上」，
    而闸已经按「一个虚词加一个词」把它砍了。"""
    from app.database.kite import kite_memory as KM

    seen = {}
    real = KM.search.evidence

    def spy(hits, query, *, common=None, attested=None, segment=None):
        seen["segment"] = segment is not None
        return real(hits, query, common=common, attested=attested, segment=segment)

    mem = _fake_mem({})
    mem.common_term = lambda: None
    mem.vocab_term = lambda: None
    mem._candidate_terms = staticmethod(KM.UserMemory._candidate_terms).__func__
    mem._cjk_terms = staticmethod(KM.UserMemory._cjk_terms).__func__
    old = KM.search.evidence
    KM.search.evidence = spy
    try:
        mem.recall_evidence("电池容量定在 420mAh", [{"id": "f0"}])
    finally:
        KM.search.evidence = old
    assert seen == {"segment": True}
