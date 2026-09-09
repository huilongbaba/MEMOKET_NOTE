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
    assert [r["id"] for r in out] == ["b", "c", "a"], \
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
