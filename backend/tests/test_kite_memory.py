"""实体去重（TRACELOG [14] 续）：_vote_entity_merges() 的 2/3 投票一致性
门槛，以及 UserMemory.preview_entity_consolidation() 只读、不动真实 vocab。

    cd backend && python -m pytest tests/test_kite_memory.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.kite import kite_memory# noqa: E402
from app.kite.kite_memory import UserMemory, _is_cjk_pair, _vote_entity_merges  # noqa: E402


@pytest.fixture()
def isolated_kite(tmp_path, monkeypatch):
    fake_settings = SimpleNamespace(
        kite_data_dir=tmp_path, kite_extract_model="fake-model",
        llm_api_key="fake-key", llm_base_url="http://fake",
    )
    monkeypatch.setattr(kite_memory, "get_settings", lambda: fake_settings)
    return tmp_path


class _FakeEntity:
    def __init__(self, code):
        self.aliases = set()
        self.rels = set()
        self.code = code


class _FakeVocab:
    """merge_entities() 真实语义的最小复刻——只测投票门槛这一层的逻辑，
    不需要真的解析 XML。"""

    def __init__(self, codes):
        self.entities = {c: _FakeEntity(c) for c in codes}
        self.merged: list[tuple[str, str]] = []

    def merge_entities(self, losers, winner):
        rewrite = {}
        for loser in losers:
            if loser == winner or loser not in self.entities:
                continue
            del self.entities[loser]
            rewrite[loser] = winner
            self.merged.append((loser, winner))
        return rewrite

    def entity_merge_candidates(self, min_len=2):
        return []  # preview 测试里候选是绕过这个方法直接指定的，这里不用


def test_vote_entity_merges_requires_two_of_three_consensus(monkeypatch):
    # 只 1 轮投了 merge、另外 2 轮没投（模型判断不合并/调用失败）——不够
    # 2/3 一致，不能真的合并，哪怕唯一一次投票是"合并"——llm_json() 返回的
    # 是已经解析好的 dict（不是 JSON 字符串），mock 也要照这个形状给
    responses = iter([
        {"decisions": [{"i": 0, "merge": True, "winner": "ai_insights"}]},
        {"decisions": [{"i": 0, "merge": False, "winner": "ai_insights"}]},
        {"decisions": [{"i": 0, "merge": False, "winner": "ai_insights"}]},
    ])
    monkeypatch.setattr(kite_memory, "llm_json", lambda *a, **k: next(responses))

    vocab = _FakeVocab(["ai_insight", "ai_insights"])
    rewrites = _vote_entity_merges(vocab, [("ai_insight", "ai_insights")], "fake-model")
    assert rewrites == {}
    assert vocab.merged == []


def test_vote_entity_merges_applies_when_two_of_three_agree(monkeypatch):
    responses = iter([
        {"decisions": [{"i": 0, "merge": True, "winner": "ai_insights"}]},
        {"decisions": [{"i": 0, "merge": True, "winner": "ai_insights"}]},
        {"decisions": [{"i": 0, "merge": False, "winner": "ai_insights"}]},
    ])
    monkeypatch.setattr(kite_memory, "llm_json", lambda *a, **k: next(responses))

    vocab = _FakeVocab(["ai_insight", "ai_insights"])
    rewrites = _vote_entity_merges(vocab, [("ai_insight", "ai_insights")], "fake-model")
    assert rewrites == {"ai_insight": "ai_insights"}
    assert vocab.merged == [("ai_insight", "ai_insights")]


def test_vote_entity_merges_skips_a_code_already_merged_this_run(monkeypatch):
    # apple 在两条候选里都出现（apple|apple_watch、apple|apple_pay）——
    # 第一条如果真的合并了，第二条不能又把 apple 或它的赢家再卷进另一次
    # 合并，防止一轮内把同一个 code 链式合并两次
    vote = {"decisions": [{"i": 0, "merge": True, "winner": "apple"},
                          {"i": 1, "merge": True, "winner": "apple"}]}
    monkeypatch.setattr(kite_memory, "llm_json", lambda *a, **k: vote)

    vocab = _FakeVocab(["apple", "apple_watch", "apple_pay"])
    rewrites = _vote_entity_merges(
        vocab, [("apple", "apple_watch"), ("apple", "apple_pay")], "fake-model")
    assert rewrites == {"apple_watch": "apple"}


def test_preview_entity_consolidation_does_not_mutate_real_vocab(isolated_kite, monkeypatch):
    mem = UserMemory("u")
    fake_vocab = _FakeVocab(["ai_insight", "ai_insights"])
    monkeypatch.setattr(mem, "_index", lambda: (None, fake_vocab))

    def fake_vote(vocabulary, candidates, model, batch_size=60):
        assert vocabulary is not fake_vocab  # 传进去的必须是深拷贝，不是真身
        vocabulary.merge_entities(["ai_insight"], "ai_insights")
        return {"ai_insight": "ai_insights"}
    monkeypatch.setattr(kite_memory, "_vote_entity_merges", fake_vote)

    rewrites = mem.preview_entity_consolidation()
    assert rewrites == {"ai_insight": "ai_insights"}
    assert "ai_insight" in fake_vocab.entities  # 真身没被动过


# TRACELOG [15] 续：中文重复的产生机制（ASR 同音字混淆）跟英文重复的
# 产生机制（打字/拼写变体）不是一回事，两个问法混用实测准确率差很多
# （英文该判重复的例子，用"读音像不像"问法 0/5 判对，换成"拼写变体"
# 问法 4/5 判对）——所以候选要按脚本类型分流，问不同的问题。
def test_is_cjk_pair_detects_either_side():
    assert _is_cjk_pair("安克", "安客") is True
    assert _is_cjk_pair("granona", "granola") is False
    assert _is_cjk_pair("granona", "granola中文") is True  # 任一边含 CJK 就算


def test_vote_entity_merges_routes_cjk_and_latin_to_different_prompts(monkeypatch):
    seen_prompts = []

    def fake_llm_json(prompt, model=None):
        seen_prompts.append(prompt)
        if "安克" in prompt:
            return {"decisions": [{"i": 0, "merge": True, "winner": "安克"}]}
        return {"decisions": [{"i": 0, "merge": True, "winner": "granola"}]}
    monkeypatch.setattr(kite_memory, "llm_json", fake_llm_json)

    vocab = _FakeVocab(["安克", "安客", "granona", "granola"])
    rewrites = _vote_entity_merges(
        vocab, [("安克", "安客"), ("granona", "granola")], "fake-model")

    assert rewrites == {"安客": "安克", "granona": "granola"}
    # 一条 prompt 里问 "SOUND"（读音，中文那批），一条问 "typo"（拼写变体，
    # 英文那批）——两条候选没有被同一个 prompt 问到
    cjk_prompts = [p for p in seen_prompts if "安克" in p]
    latin_prompts = [p for p in seen_prompts if "granona" in p]
    assert all("SOUND" in p for p in cjk_prompts)
    assert all("typo" in p for p in latin_prompts)
    assert not any("安克" in p and "granona" in p for p in seen_prompts)
