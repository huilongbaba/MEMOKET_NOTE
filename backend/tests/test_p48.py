"""P48：P46「留给下一批」那几条里落在后端的一条，外加三条**量完不改**的账。

改的只有 **②**：

  2. **`链接` 那条误杀**（P44 留给下一批 ⑤ / P46 留给下一批 ②）：这个人库里
     `链接面板` 是一个实体词，分词把它并成一个 token，于是 `链接` 落在 token 中间、
     两端够不着词边界，`_aligned` 判 `False` 当碎片砍掉。**那不是「它碎」，是
     「这把尺子判不了」**——那条边界正是被分词吃掉的。判据 `search.is_merged_word`：
     整个落在一个 token 里面 **且** 它自己是**通用词表**里的词。
     全库 28 串次 / 18 种逐条读过（夹具 `p48-merged26`），底表这把刀 **2 对 0 错**。

**另外三条量完没改，数都在台账 P48 里**，这里不设断言（**没改的东西不许拿测试假装守住了**）：

  1. `视为` / `跟着` 那一档（真词但弱）——要治得动 `common` 那一层的门槛，
     最便宜的一档是 **47 : 1**（砍对 3 串次、砍错 141 串次，连带砍掉 `memocat`
     `kickstarter` `kol` `上线` `手表` `样机` 这些）。按这条线的账法（P27 2:3、
     P38 否掉 2.2:1、P42 否掉 1.20:1）**远远不够**。
  3. `display_terms` 那条「接到汉字串尽头」——全库 3462 个合并段里 **2193 个**被它
     往后接过、接完摆出来的串**条条都变了**（`华为` 一个词被接成 `华为方案` /
     `华为做` / `华为深入恒瑞医药` 等 11 种）。但 P46 #1 之后它只服务
     「判据自己抛了」那一档，全库 `recall_evidence` 抛了 **0 / 765** 条——
     **今天一个用户都看不见它**。要治得把分词器接进 `display_terms`，
     代价 2193 串次换 0，不换。
  4. `CHANGE_LAYER_MAX_AGE_DAYS = 30` 对处置完的层要不要也放宽——**量不出来**：
     真库 `note_change_layers` **0 行**，10 份历史备份里这张表**根本不存在**。
     没有一条真实的层可以拿来问「它活多久」。**没量出来就不改。**

闸的规矩跟 P38 / P42 / P44 / P46 一条不变：**阈值闸管方向、具体断言管接线，两种都得有**。
"""

from __future__ import annotations

import re
import types

import pytest

from app.database.kb import search
from app.database.kb import tokenize as tok
from scripts import memory_sample_replay as R

# 「这篇用来看链接面板。」——`链接面板` 是这个人词表里的实体，分词把它并成一个 token。
_QL = "这篇用来看链接面板。"
_CUTL = ["这篇", "用来", "看", "链接面板", "。"]
_SEGL = lambda _t: list(_CUTL)      # noqa: E731


# ---------------------------------------------------------------- is_merged_word

def test_分词把两个词并成一个token_里面那个真词不算碎片():
    """P44 A0b 读出来的那条唯一误杀（`p44-frag64` 里标着「误杀」的那一条）。"""
    assert search.is_merged_word("链接", _QL, _SEGL) is True
    # 它确实两端够不着词边界——**`_aligned` 没判错，是这把尺子对它判不了**
    assert search._aligned("链接", _QL, _SEGL) is False


def test_归None不归True_那是把话说死():
    """`None` 是 P44 立的「这一层判不了」，`True` 是「它两端在词边界上」。

    这一串**确实不在**词边界上，说它对齐就是替尺子撒谎。**下游只认 `is False` 那一刀**，
    所以归 `None` 就够了——恒 `True` 那一刀在这儿红。
    """
    ev = search.evidence(["链接"], _QL, segment=_SEGL)
    assert [(e["term"], e["aligned"]) for e in ev] == [("链接", None)], ev


def test_判据是通用词表_不是这个人的词表():
    """**`attested` 一条都救不回来**，全库 18 种逐条核过：词表里的实体是 `链接面板`，
    **不是 `链接`**。拿「这个人的词表」当判据，这条误杀原地不动。

    底表（`tokenize.base_words()`）问的才是要问的那个量：**它是不是汉语里的一个词**。
    """
    base = tok.base_words()
    assert "链接" in base and "版本" in base
    # 这个人的词表里是那个长的，不是短的
    attested = lambda t: t == "链接面板"      # noqa: E731
    ev = search.evidence(["链接"], _QL, segment=_SEGL, attested=attested)
    assert ev[0]["aligned"] is None           # 靠底表救回来的，不是靠 attested
    assert attested("链接") is False


def test_半个词照砍():
    """**这一刀最容易砍歪的地方**：同一个形状里另外那些是真的半个词。
    全库 18 种里 16 种是这一档，底表把它们一条不漏地挡在外面。"""
    cases = [
        ("电池容", "电池容量", ["本周", "把", "电池容量", "定在", "420mah"]),
        ("基础设", "基础设施", ["讲", "的", "是", "基础设施", "三阶段"]),
        ("成功经", "成功经验", ["再", "把", "成功经验", "复制", "给", "客户"]),
        ("操作步", "操作步骤", ["文案", "缺", "操作步骤", "说明"]),
        ("应优", "应优先", ["也", "应优先", "补", "这", "一", "条"]),
    ]
    base = tok.base_words()
    for run, token, cut in cases:
        q = "".join(cut)
        seg = lambda _t, c=cut: list(c)      # noqa: E731
        assert run in token                                   # 确实落在那个 token 里
        assert run not in base, run                           # 但它不是词
        assert search.is_merged_word(run, q, seg) is False, run
        assert search._aligned(run, q, seg) is False, run     # 照旧判成碎片
        assert search.evidence(["x" + run], q, segment=seg) is not None


def test_单独拿去切是不是一个token_那把尺子救对2救错13():
    """**先量过、否掉的那一把**，全库 26 行上的成绩单：救对 2、**救错 13**。

    **「切出来是一个 token」跟「它是一个词」不是一回事**——跟 P46 那次
    「`_aligned` 不是『它是不是一个词』」是同一个坑的第二次：
    · **单字恒等于一个 token**（`计` / `半` / `次` / `兴` / `众` …，26 行里占 15 行）；
    · `电池容` 在 shot-demo 的库里攒够了次数，走 `Tokenizer` 的 `attest` 档，
      **拿这个人的分词器单独切正好是 `['电池容']`**（底表分词器切的是 `['电池','容']`）。

    底表不上这个当：这三串一个都不在那 330,349 条里。
    """
    base = tok.base_words()
    for s in ("电池容", "计", "应优"):
        assert s not in base, s
    # 单字：随便哪个分词器都只切得出一个 token，可它摆出来没有任何意义
    assert tok.default().cut("计") == ["计"]
    # 真正的判据不上这个当
    q = "本周把电池容量定在420mah"
    seg = lambda _t: ["本周", "把", "电池容量", "定在", "420mah"]      # noqa: E731
    assert search.is_merged_word("电池容", q, seg) is False


def test_跨在两个token之间的不归这一条管():
    """**判据宁可窄**：这一条只认「整个落在**一个** token 里面」。
    `可以实`（可以 | 实现）跨在两个 token 之间，是 P41 #2 点名的那个形状，
    归 `_aligned` 管，这一条碰都不碰它——就算它在底表里也一样。"""
    q = "看看可以实现哪些"
    seg = lambda _t: ["看看", "可以", "实现", "哪些"]      # noqa: E731
    assert search.is_merged_word("可以实", q, seg) is False
    assert search._aligned("可以实", q, seg) is False
    ev = search.evidence(["可以实"], q, segment=seg)
    assert ev[0]["aligned"] is False, ev          # 照旧是碎片，照旧不摆


def test_同一串出现多次_有一处被并进token就算():
    """跟 `_aligned` / `is_whole_token` 同一条规矩：**同一串在查询里出现多次，
    只要有一处落在这个形状里就算**——判据宁可窄，别因为第一处不是就把话说死。

    反例真的落在那条 `start = i + 1` 上：第一处 `链接` 自己就是一个 token，
    第二处才被并进 `链接面板`。**只看第一处的那一刀在这儿红。**
    """
    q = "链接在这里，这篇用来看链接面板。"
    cut = ["链接", "在", "这里", "，", "这篇", "用来", "看", "链接面板", "。"]
    seg = lambda _t: list(cut)      # noqa: E731
    assert "".join(cut) == q
    assert search.is_merged_word("链接", q, seg) is True


def test_等于那个token本身的不算被并进去():
    """自己**就是**那个 token 的不算「被并进去」——那一档归 `is_whole_token`（P46），
    不归这一条。两条判据不许互相顶。

    **反例必须真的落在那条 `(a, b) != (i, j)` 上**（这是栽过五次的那个坑，
    第一版拿 `链接面板` 当反例是错的：它**不在底表里**，在上一行就回 `False` 了，
    砍掉这条守门的那一刀照样绿）。所以这里用 `版本`——**底表里有**（词频 49），
    而且在这条查询里它自己就是一个整 token。
    """
    q = "这一版版本没变"
    cut = ["这", "一版", "版本", "没", "变"]
    seg = lambda _t: list(cut)      # noqa: E731
    assert "".join(cut) == q
    assert "版本" in tok.base_words()                        # 底表那一关过得去
    assert search.is_merged_word("版本", q, seg) is False     # 挡它的是「不等于那个 token」
    assert search.is_whole_token("版本", q, seg) is True
    # 老反例也照旧：`链接面板` 不在底表里，走的是另一条守门
    assert search.is_merged_word("链接面板", _QL, _SEGL) is False
    assert "链接面板" not in tok.base_words()


def test_判的是摆出来的那一串_不是原始的run():
    """P44 立的那条规矩在这一刀上的样子：**判的是 `evidence_label` 剥完的那一串**。

    全库那 26 行里有 1 行只有按 label 才露得出来：`3月15日版本中` 切出来的 run 是
    `日版本`，剥掉「日」之后才是 `版本`——而 `日版本` **不在底表里**，
    拿原始的 run 去判，这一条就救不回来。**反例落在那个实参上。**
    """
    q = "3月15日版本中的改动"
    cut = ["3", "月", "15", "日", "版本中", "的", "改动"]
    seg = lambda _t: list(cut)      # noqa: E731
    assert "".join(cut) == q
    assert search.evidence_label("日版本", q, seg) == "版本"
    assert "日版本" not in tok.base_words() and "版本" in tok.base_words()
    assert search.is_merged_word("日版本", q, seg) is False    # 拿 run 去判：救不回来
    assert search.is_merged_word("版本", q, seg) is True       # 拿 label 去判：救得回来
    ev = search.evidence(["日版本"], q, segment=seg)
    assert [(e["term"], e["aligned"]) for e in ev] == [("日版本", None)], ev


def test_英文和没有分词器一律不认():
    """三档一律 `False`，**不启用就是原样**：底表是一张纯汉字 2–4 字的表。"""
    assert search.is_merged_word("链接", _QL, None) is False       # 没有分词器
    assert search.is_merged_word("kol", "kol样机", lambda _t: ["kol样机"]) is False
    assert search.is_merged_word("", _QL, _SEGL) is False
    assert search.is_merged_word("链接", "完全不相干的一句话", _SEGL) is False  # 定位不到


def test_面板上摆的是链接():
    """这条误杀在**用户看得见的那一行**上的样子。"""
    mem = _mem(["这一版的链接面板改了布局"], ["链接"], seg=_SEGL, df={"链接": 3})
    got = mem.recall_evidence(_QL, [{"id": "f0"}])
    assert [e["term"] for e in got] == ["链接"], got


def test_接线洞_evidence必须把这一条接上():
    """**省掉这一条就静静退回 P46 的行为**，而阈值闸看不见这种洞
    （全库只有 2 / 765 条查询会变）。这一条是**接线断言**。"""
    src = (__import__("pathlib").Path(__file__).resolve().parents[1]
           / "app/database/kb/search.py").read_text(encoding="utf-8")
    assert "if al is False and is_merged_word(label, squeezed, segment):" in src
    assert "al = None" in src


def test_这一格照旧不许接进qualifies():
    """P44 立的那条一个字没退：**显示规则不许判死召回**。

    反例真的落在被测分支里：一条被并进 token 的真词 + 一条 `420mah`，
    `qualifies` 照旧只数「有没有两条证据」，不看 `aligned`。
    """
    q = "这篇用来看链接面板420mah"
    seg = lambda _t: ["这篇", "用来", "看", "链接面板", "420mah"]      # noqa: E731
    assert search.qualifies(["链接", "420mah"], q, segment=seg) is True
    # 全砍成碎片的那一档也照旧进得来
    q2 = "看看可以实现哪些420mah"
    seg2 = lambda _t: ["看看", "可以", "实现", "哪些", "420mah"]      # noqa: E731
    assert search.qualifies(["可以实", "420mah"], q2, segment=seg2) is True


# ---------------------------------------------------------------- 夹具第五组

def test_夹具里五组都在_前四组一个字没动():
    assert len(R.load_sample()[1]) == 47
    assert len(R.load_sample(set_name="p42-allpair82")[1]) == 82
    assert len(R.load_sample(set_name="p44-frag64")[1]) == 64
    assert len(R.load_sample(set_name="p46-unstrip9")[1]) == 10
    assert len(R.load_sample(set_name="p48-merged26")[1]) == 26


def test_这26条的标注分布逐格相同():
    """**「把标注抹平」那种突变也要挡**：三档各自钉死，再钉一条「不许只剩一档」。"""
    from collections import Counter

    _meta, rows = R.load_sample(set_name="p48-merged26")
    dist = Counter(r["判定"] for r in rows)
    assert dist == {"剥成单字": 15, "半个词": 9, "误杀": 2}, dist
    assert Counter(r["p48"] for r in rows) == {"砍": 24, "摆": 2}
    assert sorted(r["label"] for r in rows if r["判定"] == "误杀") == ["版本", "链接"]
    # **误杀那两条靠的是底表，不是这个人的词表**——`attested` 全库一条都救不回来
    assert all(r["attested_run"] is False and r["attested_label"] is False for r in rows)
    assert [r["in_base_dict"] for r in rows if r["判定"] == "误杀"] == [True, True]
    assert not any(r["in_base_dict"] for r in rows if r["判定"] != "误杀")


def test_这26条离线逐条重算得上():
    """冻的是 `cut`，所以三把尺子都能离线重跑——**夹具那句「不用再读一遍」得兑现**。"""
    _meta, rows = R.load_sample(set_name="p48-merged26")
    for r in rows:
        p46 = R.display_stats(r["run"], r["query"], r["cut"], ruler="p46")
        p48 = R.display_stats(r["run"], r["query"], r["cut"], ruler="p48")
        assert p46["shown"] is False, r["i"]                 # P46 那一把：26 条全砍
        assert p48["shown"] is (r["p48"] == "摆"), r["i"]
        assert p48["label"] == r["label"], r["i"]
    assert sum(1 for r in rows if r["p48"] == "摆") == 2


def test_冻下来的分词真的是这条查询的():
    """量具自己得先对（P42 量具教训 #2）：`cut` 拼起来必须逐字等于挤掉空白的查询。"""
    _meta, rows = R.load_sample(set_name="p48-merged26")
    for r in rows:
        assert "".join(r["cut"]) == re.sub(r"\s+", "", r["query"].lower()), r["i"]


def test_这一刀在P44那64条上只动了链接那一条():
    """**兑现 `p44-frag64` 那句「下一批换尺子拿它重跑，不用再读一遍」**，
    而且钉死**只动它该动的那一条**。

    P44 逐条读那 64 串次时读出 **1 条误杀**：`链接`（第 53 行）——
    「这个人库里 `链接面板` 是一个实体词，分词把它并成一个 token，`链接` 就落在
    token 中间」。这一批把它兑现了，**另外 63 条一条不动**。

    **那 64 条的标注没有作废**：它标的是「P44 摆出来的那一串是不是碎的」，
    而 `链接` 那一条 P44 标的就是「真词、砍错了」。
    """
    _meta, rows = R.load_sample(set_name="p44-frag64")
    moved = []
    for r in rows:
        a = R.display_stats(r["run"], r["query"], r["cut"], ruler="p46")
        b = R.display_stats(r["run"], r["query"], r["cut"], ruler="p48")
        assert a["label"] == b["label"], r["i"]        # 摆出来长什么样一个字没变
        if a["shown"] != b["shown"]:
            moved.append((r["i"], r["run"], b["shown"]))
    assert moved == [(53, "链接", True)], moved


def test_P46那10条在新尺子下逐条不动():
    """`p46-unstrip9` 那一组拿 p48 重跑，跟 p46 **逐条相同**——动了就是判据宽了。"""
    _meta, rows = R.load_sample(set_name="p46-unstrip9")
    for r in rows:
        a = R.display_stats(r["run"], r["query"], r["cut"], ruler="p46")
        b = R.display_stats(r["run"], r["query"], r["cut"], ruler="p48")
        assert a["label"] == b["label"] == r["p46"], r["i"]
        assert a["shown"] == b["shown"], r["i"]


def test_p44那一把尺子照旧是一律剥():
    """三把尺子各是各的。**拿今天的尺子去核昨天冻的数，红的不是代码而是尺子换过了**。"""
    _meta, rows = R.load_sample(set_name="p44-frag64")
    old = [R.display_stats(r["run"], r["query"], r["cut"], ruler="p44") for r in rows]
    assert all(not o["shown"] for o in old)
    for r, o in zip(rows, old):
        assert o["rule"] == r["rule"] and o["label"] == r["stripped"], r["i"]


def test_尺子名写错要吵():
    """**不许悄悄按默认那一把算过去**——那正是「拿今天的尺子核昨天冻的数」那种静默错。"""
    assert R.RULERS == ("p44", "p46", "p48")
    with pytest.raises(ValueError):
        R.display_stats("链接", _QL, _CUTL, ruler="p47")


# ---------------------------------------------------------------- 造一个假 memory（同 test_p46）

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
    mem._cjk_terms = lambda text: list(cjk)
    mem._match_vocab = lambda q, v: ([], [], [])
    mem.common_term = lambda: None
    mem.vocab_term = lambda: None
    mem.segment = lambda: seg
    return mem
