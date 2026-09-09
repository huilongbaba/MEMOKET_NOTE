"""抽取的模型判判据：规则判不了的那两条。

`extract_check` 管代码能判的（数字有没有出处）。判不了的是「这条事实脱离
上下文还读得懂吗」和「挂的主题对不对」——而这两条恰恰决定了写作那边用不
用得上它。

用的是写作 harness 那套 `evaluate()`，只换一组维度——`app/scoring` 当初
做成独立包就是为了这个。

**成本实测**：判一场 6-9 秒，抽一场 32-48 秒，判据是抽取的约 20%，不是
设计里担心的「翻倍」（那个估算假设的是逐 chunk 判）。
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.scoring import DimensionScore, Evaluation  # noqa: E402

from app.kb import extract_judge  # noqa: E402


def _memory(units: dict[str, list[str]], facts: list[tuple[str, str, list[str]]]):
    lines, unit_objs, fact_objs = {}, {}, {}
    n = 0
    for uid, texts in units.items():
        unit_objs[uid] = types.SimpleNamespace(id=uid)
        for text in texts:
            n += 1
            lines[f"L{n}"] = types.SimpleNamespace(id=f"L{n}", unit=uid, text=text)
    for i, (uid, text, topics) in enumerate(facts):
        fact_objs[f"F{i}"] = types.SimpleNamespace(
            id=f"F{i}", unit=uid, text=text, topics=topics)
    store = types.SimpleNamespace(units=unit_objs, lines=lines, facts=fact_objs)
    return types.SimpleNamespace(_index=lambda: (store, None))


def _patch(monkeypatch, memory, evaluation=None, seen=None):
    monkeypatch.setattr(extract_judge, "UserMemory", lambda u: memory)

    async def fake_evaluate(_llm, *, content, dimensions, context=None, **kw):
        if seen is not None:
            seen.append({"content": content, "dimensions": dimensions,
                         "context": context or {}})
        if evaluation is None:
            raise RuntimeError("judge failed")
        return evaluation
    monkeypatch.setattr(extract_judge, "evaluate", fake_evaluate)


def _ev(**levels):
    return Evaluation(
        scores={k: DimensionScore(level=v, note=f"{k} 的判词") for k, v in levels.items()},
        status="continue", weakest=min(levels, key=levels.get))


def test_判的是这一场的事实和它自己的原文(monkeypatch):
    mem = _memory({"m1": ["原文一", "原文二"], "m2": ["别场的原文"]},
                  [("m1", "事实甲", ["t1"]), ("m2", "别场的事实", ["t2"])])
    seen = []
    _patch(monkeypatch, mem, _ev(self_contained=2, topic_fit=2), seen)
    got = asyncio.run(extract_judge.judge_meeting("u", "m1"))
    assert got.facts == 1
    assert "事实甲" in seen[0]["content"] and "别场的事实" not in seen[0]["content"]
    assert "原文一原文二" in seen[0]["context"]["原始对话"]
    assert "别场的原文" not in seen[0]["context"]["原始对话"]


def test_主题挂在事实上一起给判据看(monkeypatch):
    """「主题对不对」这一维，不把主题给它就没法判。"""
    mem = _memory({"m1": ["原文"]}, [("m1", "读 MBA", ["education_abroad"])])
    seen = []
    _patch(monkeypatch, mem, _ev(self_contained=2, topic_fit=0), seen)
    asyncio.run(extract_judge.judge_meeting("u", "m1"))
    assert "education_abroad" in seen[0]["content"]


def test_判据调用失败不能弄丢事实(monkeypatch):
    """这一步跑在抽取成功之后。判不了就是判不了，不能反过来影响抽取的结果。"""
    mem = _memory({"m1": ["原文"]}, [("m1", "事实", ["t"])])
    _patch(monkeypatch, mem, None)
    got = asyncio.run(extract_judge.judge_meeting("u", "m1"))
    assert got.evaluation is None and got.facts == 1


def test_没有事实的会议不去打模型(monkeypatch):
    mem = _memory({"m1": ["原文"]}, [])
    seen = []
    _patch(monkeypatch, mem, _ev(self_contained=2), seen)
    got = asyncio.run(extract_judge.judge_meeting("u", "m1"))
    assert got.evaluation is None and seen == []


def test_抽样先判事实最多的那几场(monkeypatch):
    """只抽出三条事实的会议说明不了抽取规则的好坏。"""
    facts = [("small", "一条", ["t"])] + [("big", f"第{i}条", ["t"]) for i in range(5)]
    mem = _memory({"small": ["a"], "big": ["b"]}, facts)
    seen = []
    _patch(monkeypatch, mem, _ev(self_contained=1, topic_fit=2), seen)
    got = asyncio.run(extract_judge.judge_sample("u", limit=1))
    assert got["judged"] == 1
    assert "第0条" in seen[0]["content"]


def test_聚合是给规则看的不是给单场看的(monkeypatch):
    """规则有毛病的表现是每一场都挨同一句批评——所以聚合比单场重要。
    实测就是这样：五场会议、五个 self_contained=1、五句一模一样的判词
    （相对时间和代词），改 prompt 之后同样三场从均值 0.33 升到 1.00。"""
    mem = _memory({"m1": ["a"], "m2": ["b"]},
                  [("m1", "甲", ["t"]), ("m2", "乙", ["t"])])
    _patch(monkeypatch, mem, _ev(self_contained=1, topic_fit=2))
    got = asyncio.run(extract_judge.judge_sample("u", limit=5))
    assert got["dimensions"]["self_contained"] == {"mean": 1.0, "below_bar": 2}
    assert got["dimensions"]["topic_fit"] == {"mean": 2.0, "below_bar": 0}


def test_判据说的话跟抽取规则对得上():
    """判据挑毛病、规则不说怎么做，闭环就是空的。这两条是同一件事的两面。"""
    from app import kite_profile

    rules = kite_profile.EXTRACT_RULES
    assert "No relative time, no bare pronouns" in rules
    guidance = " ".join(d.guidance for d in extract_judge.DIMENSIONS)
    assert "相对时间" in guidance and "主题" in guidance
