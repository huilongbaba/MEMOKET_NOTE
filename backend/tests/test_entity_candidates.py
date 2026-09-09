"""给模型的「已知实体」提示词候选怎么挑。

这个模块的来历写在它自己的 docstring 里：KITE 原本把这份提示拼成
``sorted(vocabulary.entities)[:80]``，而 terrence 的真实词表 1958 个实体里
有 105 个是数字开头的噪声（「100美元」「10号」「2月10号」…），数字排在
字母前面——那 105 个把 80 个位置全占满了，**一个真实的具名实体都到不了
模型面前**。后果是语料里被提到最多的实体「memoket」自己裂成了 61 个码
（memocat、memocad、memokit、memokai、memo_kid…）。

跑覆盖率之前这个文件 86 行里 73 行没执行过——包括那个挑候选的算法本身，
和 install() 里那道「上游版本变了就别偷偷打补丁」的安全阀。两样都是
「坏了不报错、只是悄悄退回原来的毛病」。
"""

from __future__ import annotations

import warnings

from app.database.kite.kite_entity_candidates import (
    _bigrams, _coarse_entity_candidates, install)


class _Entity:
    def __init__(self, name, aliases=()):
        self.name = name
        self.aliases = list(aliases)


class _Vocab:
    def __init__(self, **entities):
        self.entities = {k: v for k, v in entities.items()}


def test_原样出现在正文里的实体排最前():
    vocab = _Vocab(memoket=_Entity("memoket"),
                   plaud=_Entity("plaud"),
                   随便一个=_Entity("完全无关的东西"))
    got = _coarse_entity_candidates(vocab, "今天聊了 memoket 的硬件进度")
    assert got[0] == "memoket"
    assert "随便一个" not in got


def test_没原样出现的按字符二元组重合度排():
    vocab = _Vocab(memokit=_Entity("memokit"), 完全不沾边=_Entity("量子物理"))
    got = _coarse_entity_candidates(vocab, "memoket 的进度")
    assert got and got[0] == "memokit", "拼写相近的该排前面"


def test_一两个字的垃圾码不参与匹配():
    """早期抽取漏进词表的「a」「m」这种码，作为子串几乎能命中任何正文，
    会把真正的候选全淹掉。两条分支用同一个长度下限。"""
    vocab = _Vocab(a=_Entity("a"), m=_Entity("m"), memoket=_Entity("memoket"))
    got = _coarse_entity_candidates(vocab, "memoket 的一段对话")
    assert got == ["memoket"]


def test_别名也算实体的表面形式():
    vocab = _Vocab(mk=_Entity("Memoket", aliases=["小忆", "记忆猫"]))
    assert _coarse_entity_candidates(vocab, "今天跟记忆猫聊了聊") == ["mk"]


def test_数量上限管用():
    vocab = _Vocab(**{f"实体{i}": _Entity(f"实体{i}") for i in range(200)})
    assert len(_coarse_entity_candidates(vocab, "实体1 实体2 实体3", cap=80)) <= 80


def test_空词表不炸():
    assert _coarse_entity_candidates(_Vocab(), "随便什么") == []


def test_二元组():
    assert _bigrams("abc") == {"ab", "bc"}
    assert _bigrams("a") == set()


def test_上游版本对不上就不打补丁只报警(monkeypatch):
    """这个补丁整个拷贝了 memoket_kite 内部一个函数、只改了一行。上游改了
    形状还照打，坏法会很难查——所以对不上就退回 KITE 自己的行为并报警，
    而不是静默继续。"""
    from app.database.kite import kite_entity_candidates as mod

    monkeypatch.setattr(mod.memoket_kite, "__version__", "999.0.0-不存在的版本")
    before = mod._extract._extract_facts_with_cache
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        install()
    assert mod._extract._extract_facts_with_cache is before, "版本对不上却还是打了补丁"
    assert any("has not been re-diffed" in str(w.message) for w in caught)


def test_版本对得上就真的换掉那个函数(monkeypatch):
    from app.database.kite import kite_entity_candidates as mod

    monkeypatch.setattr(mod._extract, "_extract_facts_with_cache", lambda *a: None)
    install()
    assert mod._extract._extract_facts_with_cache is mod._extract_facts_with_cache
