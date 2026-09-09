"""前端监听的事件名，后端必须发得出来。

这次重构把三条 harness 的循环合成了一份，事件也从 23 个手写名字换成了
AG-UI 那 9 个标准事件 + CUSTOM。前端一行没改——中间隔着
``events.legacy_frames()`` 这个翻译层。

翻译层最容易出的错是**沉默地少翻一个**：前端的事件分发是 else-if 链，
不认识的名字直接忽略，所以少发一种帧的症状不是报错，是「轮数不动了」
「来源面板一直空的」这种没人第一时间归因到后端的现象。实测就漏过
``round-start`` 和 ``replan`` 两个。

所以这里从前端源码里把它监听的名字抠出来，跟翻译层能产出的名字对一遍。
"""

from __future__ import annotations

import pathlib
import re

from app.harness.events import Event, EventType, legacy_frames

ROOT = pathlib.Path(__file__).resolve().parents[2]
API_TS = ROOT / "frontend" / "src" / "api.ts"

# 前端里跟 harness 无关的那几条流（磁贴续写、批量导入任务）。它们没走这个
# 循环，事件名也不该由翻译层负责。
NOT_OURS = {"meta", "grounding", "progress", "end",
            # plan 级事件由 writing_plan 的 router 直接发，不经过翻译层
            "plan-loaded", "plan-extended", "plan-done",
            "section-start", "section-done"}


def _frontend_event_names() -> set[str]:
    src = API_TS.read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"event === '([a-z-]+)'", src)} - NOT_OURS


def _translatable() -> set[str]:
    """翻译层实际能产出的帧名。"""
    samples = [
        Event.run_started("note", "写"),
        Event.run_finished("正文", "complete"),
        Event.run_error("boom"),
        Event.step_started(1, "写"),
        Event.step_finished(1),
        Event.text_start("r1"),
        Event.text_content("r1", "字"),
        Event.text_end("r1"),
        Event.tool_result("recall", {}, "结果"),
        Event.activity("在查…"),
    ]
    samples += [Event.custom(name, {}) for name in (
        "evaluate", "policy", "revision", "dropped", "skeleton",
        "phase_delta", "round_summary", "replan")]

    names = set()
    for event in samples:
        for frame in legacy_frames(event):
            names.add(frame.split("\n", 1)[0].removeprefix("event: "))
    return names


def test_前端听的每一个事件后端都发得出来():
    missing = _frontend_event_names() - _translatable()
    assert not missing, (
        f"翻译层发不出这些帧，前端会静默地什么都不显示：{sorted(missing)}")


def test_每一种事件都翻得出东西或明确不翻():
    """AG-UI 那边新增一种事件时，这条会逼着做个决定，而不是默认漏掉。"""
    # TEXT_MESSAGE_START/END 在旧契约里没有对应物——旧前端从来没见过它们。
    silent = {EventType.TEXT_MESSAGE_START, EventType.TEXT_MESSAGE_END,
              EventType.RUN_STARTED}
    for kind in EventType:
        if kind is EventType.CUSTOM or kind in silent:
            continue
        event = Event(kind, {"step": 1, "delta": "x", "content": "x",
                             "message": "x", "reason": "complete",
                             "toolName": "t", "args": {}})
        assert legacy_frames(event), f"{kind.value} 翻不出任何帧，也没写在 silent 里"


def test_未知的custom事件不会炸():
    assert legacy_frames(Event.custom("something_new", {"a": 1})) == []
