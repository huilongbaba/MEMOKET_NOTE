"""零 LLM 检索的排序。

原来的实现命中主题之后跑的是「按时间倒序取前 8」——**没有任何相关性
排序**。给它一条事实自己的原文去查，只有 22% 能召回它自己、38% 能召回
同主题的东西。而且模块里早就算好的中文 n-gram 只用在行级兜底上，从来
没拿去 grep 过 fact，所以一个不含英文词的中文查询只有一条可用通道。

修完是 90% / 97%，仍然几毫秒。这个文件钉住两件事：**中文查询能命中**，
以及**返回顺序跟查询有关**。
"""

from __future__ import annotations

import types

from app.database.kb import search


class _FakeMemory:
    """只提供 search.plan/rank 用到的那几个方法。"""

    @staticmethod
    def _candidate_terms(text):
        import re
        return [w for w in re.findall(r"[A-Za-z]{2,}", text.lower())][:12]

    @staticmethod
    def _cjk_terms(text):
        import re
        out = []
        for run in re.findall(r"[一-鿿]{2,}", text):
            for size in (3, 2):
                for i in range(len(run) - size + 1):
                    g = run[i:i + size]
                    if g not in out:
                        out.append(g)
        return out[:16]

    @staticmethod
    def _match_vocab(text, vocab):
        return (vocab or {}).get("topics", []), (vocab or {}).get("entities", []), []


def _store(texts: dict[str, str]):
    facts = {fid: types.SimpleNamespace(id=fid, text=t) for fid, t in texts.items()}
    return types.SimpleNamespace(facts=facts)


def test_中文查询会被拿去搜事实而不是只当兜底():
    plan = search.plan(_FakeMemory(), "录音设备的电量和佩戴体验", None)
    greps = [q["where"]["grep"] for q in plan if "grep" in q.get("where", {})]
    assert greps, "中文查询一条 grep 通道都没有——这正是原来的 bug"
    assert any("录音" in g or "设备" in g for g in greps)


def test_没命中词表时也有候选通道():
    """词表命中与否决定不了有没有结果——原来它决定了。"""
    plan = search.plan(_FakeMemory(), "完全陌生的一句中文", None)
    assert plan, "词表落空时应该还有词法通道"


def test_排序按查询词的覆盖量而不是日期():
    store = _store({
        "a": "跟查询完全无关的一条内容。",
        "b": "录音设备的电量和佩戴体验都需要验证。",
        "c": "录音设备。",
    })
    rows = [{"id": "a", "date": "2026-09-01"},
            {"id": "b", "date": "2026-01-01"},
            {"id": "c", "date": "2026-08-01"}]
    out = search.rank(rows, "录音设备的电量和佩戴体验", _FakeMemory(), store, limit=3)
    # 一个词都没命中的 a 不再返回（第 224 轮）：它只是候选池里撞进来的
    assert [r["id"] for r in out] == ["b", "c"], \
        "最贴题的那条要排最前，哪怕它最旧"


def test_日期只在得分相同时用来断结():
    store = _store({"a": "录音设备", "b": "录音设备"})
    rows = [{"id": "a", "date": "2026-01-01"}, {"id": "b", "date": "2026-09-01"}]
    out = search.rank(rows, "录音设备", _FakeMemory(), store, limit=2)
    assert [r["id"] for r in out] == ["b", "a"]


def test_查询里一个词都提取不出来时原样返回():
    store = _store({"a": "内容"})
    rows = [{"id": "a", "date": ""}]
    assert search.rank(rows, "!!!", _FakeMemory(), store, limit=1) == rows


def test_报出来的命中词是真的出现在结果里的():
    store = _store({"a": "录音设备的电量"})
    got = search.matched_terms([{"id": "a"}], "录音设备的电量和佩戴体验",
                               _FakeMemory(), store)
    assert got, "命中词不该是空的"
    assert all(t in "录音设备的电量" for t in got)


def test_英文词不分大小写也不重复计分():
    """第 191 轮真库实测：英文候选词是小写的，事实原文里 EVT / PCBA 大写，之前永远不得分。"""
    store = _store({
        "up": "EVT 的大节点是 4 月 16 号，PCBA 15 套。",
        "low": "然后再到evtdvt对对他这个不可能兼职的",
        "none": "跟查询无关。",
    })
    rows = [{"id": "none", "date": "2026-09-01"}, {"id": "low", "date": "2026-08-01"}, {"id": "up", "date": "2026-01-01"}]
    mem = _FakeMemory()
    mem._candidate_terms = lambda text: ["evt", "pcba", "evt"]
    mem._cjk_terms = lambda text: []
    out = search.rank(rows, "EVT 准备 PCBA evt", mem, store, limit=3)
    assert [r["id"] for r in out][0] == "up"
    assert search.matched_terms(out, "EVT PCBA", mem, store) == ["evt", "pcba"]


def test_数字也是查询词_但光秃秃的一两位数不算():
    assert search._number_terms("4月16日的 EVT 准备 4 台主机和 15 套 PCBA，电池 380mAh，成本 2026") == ["4月16", "4台", "15套", "380", "2026"]
    store = _store({"date": "EVT 的大节点是 4 月 16 号", "pcba": "板子就 PCBA 肯定还是要，KIO 有 15 台"})
    rows = [{"id": "pcba", "date": "2026-09-01"}, {"id": "date", "date": "2026-01-01"}]
    mem = _FakeMemory()
    mem._candidate_terms = lambda text: ["evt", "pcba"]
    mem._cjk_terms = lambda text: []
    out = search.rank(rows, "4月16日的EVT准备4台主机和15套PCBA", mem, store, limit=2)
    assert [r["id"] for r in out] == ["date", "pcba"]


def test_英文短词整词匹配_不靠子串得分():
    """第 224 轮：拖一篇 .md 进来，`md` 子串命中 SMDowner / B2ECMD，右栏全是不相干的事实。"""
    store = _store({
        "smd": "当他是SMDowner，给他B2ECMD的指令",
        "real": "把笔记导出成 md 文件",
        "said": "he said the ai model is fine",
        "none": "无关",
    })
    rows = [{"id": k, "date": "2026-01-01"} for k in ("smd", "real", "said", "none")]
    mem = _FakeMemory()
    mem._candidate_terms = lambda text: ["md"]
    mem._cjk_terms = lambda text: []
    out = search.rank(rows, "拖进树的 .md", mem, store, limit=1)
    assert out[0]["id"] == "real"
    assert search.matched_terms([rows[0]], "md", mem, store) == []
    mem._candidate_terms = lambda text: ["ai"]
    assert search._hits(["ai"], "he said the ai model") == ["ai"] and search._hits(["ai"], "he said") == []


def test_英文虚词和说话人标签不当查询词():
    """「Speaker B says they have no ideas now」：speaker b / says / they / have 一人一分把内容词稀释掉（第 527 轮）。"""
    mem = _FakeMemory()
    mem._candidate_terms = lambda text: ["speaker b", "speaker", "says", "they", "have", "ideas", "later"]
    mem._cjk_terms = lambda text: []
    terms = search._terms(mem, "Speaker B says they have no ideas now but will have ideas later")
    assert terms == ["ideas"]
    # 全是虚词时退回原样，别搜不出东西
    mem._candidate_terms = lambda text: ["speaker a", "says", "it"]
    assert search._terms(mem, "speaker a says it") == ["speaker a", "says", "it"]


def test_同一个词出现两次的排在只出现一次的前面():
    """查询只剩一个内容词时，几十条候选靠日期断结；说了两遍的那条才是「它自己」（第 531 轮）。"""
    store = _store({
        "twice": "they have no ideas now but will have ideas later",
        "once": "some ideas about pricing",
        "none": "unrelated",
    })
    rows = [{"id": "none", "date": "2026-09-03"}, {"id": "once", "date": "2026-09-02"}, {"id": "twice", "date": "2026-09-01"}]
    mem = _FakeMemory()
    mem._candidate_terms = lambda text: ["ideas"]
    mem._cjk_terms = lambda text: []
    out = search.rank(rows, "ideas", mem, store, limit=3)
    assert [r["id"] for r in out] == ["twice", "once"]
