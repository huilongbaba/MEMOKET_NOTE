"""UserMemory.ask()：KITE 的 Answer 把依据叫 evidence（早期叫 facts）。
实拍：「来龙去脉」直接 500——AttributeError: 'Answer' object has no attribute 'facts'。"""
from __future__ import annotations

from types import SimpleNamespace

from app.database.kite import kite_memory as km


class _FakeMemory:
    def __init__(self, answer):
        self._answer = answer

    @classmethod
    def load(cls, path, model=None):
        return cls(cls._next)

    def answer_with_evidence(self, question, limit=10):
        return self._answer


def _stub(monkeypatch, answer):
    _FakeMemory._next = answer
    monkeypatch.setattr(km, "Memory", _FakeMemory)
    monkeypatch.setattr(km, "_export_provider_env", lambda: None)
    monkeypatch.setattr(km.store, "get_active_llm_config", lambda: {"model": "m"})
    monkeypatch.setattr(km.UserMemory, "ensure", lambda self: None)


def _fact(i, sources):
    return SimpleNamespace(id=f"u-{i}-A", content=f"事实{i}", when="2026-01-0" + str(i), kind="event", sources=sources)


def test_认_evidence_字段(monkeypatch):
    answer = SimpleNamespace(text="答", evidence=(_fact(1, [{"content": "原话"}]), _fact(2, ["裸字符串"])), citations=())
    _stub(monkeypatch, answer)
    text, facts = km.UserMemory("t-ask").ask("问")
    assert text == "答"
    assert [f["id"] for f in facts] == ["u-1-A", "u-2-A"]
    assert facts[0]["sources"] == ["原话"] and facts[1]["sources"] == ["裸字符串"]


def test_老版本的_facts_字段也认(monkeypatch):
    answer = SimpleNamespace(text="答", facts=[_fact(3, None)])
    _stub(monkeypatch, answer)
    _text, facts = km.UserMemory("t-ask").ask("问")
    assert facts[0]["id"] == "u-3-A" and facts[0]["sources"] == []
