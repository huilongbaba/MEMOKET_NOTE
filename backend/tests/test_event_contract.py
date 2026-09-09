"""前端听的事件名，后端必须发得出来。

**这一版是过渡层拆掉之后的形态。** 后端一度用 23 个自定义事件名，改成
AG-UI 标准之后加了一层 `legacy_frames()` 把标准名翻回旧名，好让三条
router 逐条迁移期间前端不用动。三条都切完了，前端换成标准名，翻译层删掉。

现在两边说的是同一套名字，这个文件盯的就变成了：**前端的分支不能比后端
发得出的事件少**。前端的事件分发是 else-if 链，不认识的名字直接忽略——
少一个分支的症状不是报错，是「轮数不动了」「来源面板一直空的」这种没人
第一时间归因到后端的现象。翻译层时代就漏过 `round-start` 和 `replan`。
"""

from __future__ import annotations

import pathlib
import re

from app.harness.events import Event, EventType, to_sse

ROOT = pathlib.Path(__file__).resolve().parents[2]
API_TS = ROOT / "frontend" / "src" / "api.ts"


def _frontend_events() -> set[str]:
    """前端认的 AG-UI 事件名。"""
    src = API_TS.read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"event === '([A-Z_]+)'", src)}


def _frontend_custom_names() -> set[str]:
    """CUSTOM 里前端认的 name。"""
    src = API_TS.read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"name === '([a-z_]+)'", src)}


def _backend_custom_names() -> set[str]:
    """后端定义的 CUSTOM name 常量。"""
    src = (ROOT / "backend" / "app" / "harness" / "events.py").read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r'^CUSTOM_\w+ = "([a-z_]+)"', src, re.M)}


def test_前端认的每个标准事件后端都发得出来():
    backend = {e.value for e in EventType}
    unknown = _frontend_events() - backend
    assert not unknown, f"前端在等一些后端不会发的事件：{sorted(unknown)}"


def test_后端每个custom事件前端都接得住():
    """一个后端在发、前端没有分支的 CUSTOM，就是一个静默丢失的信号。"""
    missing = _backend_custom_names() - _frontend_custom_names()
    # warning 是给开发看的诊断（某个 middleware 挂了但 run 继续），前端不展示
    missing -= {"warning", "check_hit"}
    assert not missing, f"这些 CUSTOM 事件前端没有分支：{sorted(missing)}"


def test_每种事件都序列化得出一帧():
    for kind in EventType:
        frame = to_sse(Event(kind, {"x": 1}))
        assert frame.startswith(f"event: {kind.value}\n")
        assert frame.endswith("\n\n")


def test_翻译层真的删干净了():
    """过渡层从写下第一天就标好了死期：三条 router 都切完就删。留着的话，
    下一个人会以为前端还在听旧名字。"""
    backend = ROOT / "backend" / "app"
    left = [str(f.relative_to(backend)) for f in backend.rglob("*.py")
            if "legacy_frames" in f.read_text(encoding="utf-8")]
    assert not left, f"还有地方引用翻译层：{left}"
    assert "legacy" not in API_TS.read_text(encoding="utf-8").lower()


def test_没有人手写sse帧也没有人自己开流():
    """SSE 的帧格式和响应头，各只有一处。

    改之前：帧格式 ``event: X\\ndata: {json}\\n\\n`` 在 compose / ingest /
    writing_plan 里各手写了一遍（八处），``StreamingResponse(...)`` 带着
    那两个响应头在六个 router 里各抄了一遍。

    抄出来的东西迟早漂，而且漂了不报错：``ensure_ascii`` 漏一个，那条流
    吐的就是 ``\\u4e2d\\u6587`` 转义；``X-Accel-Buffering: no`` 漏一个，
    那条流在 nginx 后面会攒够几 KB 才吐一次——本地一切正常，线上「一动
    不动然后突然全出来」。
    """
    import pathlib

    routers = pathlib.Path(__file__).resolve().parents[1] / "app" / "routers"
    files = sorted(routers.glob("*.py"))
    assert files, "一个 router 都没找到"

    handwritten, own_stream = [], []
    for f in files:
        src = f.read_text(encoding="utf-8")
        if '"event: ' in src or "'event: " in src:
            handwritten.append(f.name)
        if "StreamingResponse(" in src and f.name != "deps.py":
            own_stream.append(f.name)
    assert not handwritten, f"这些 router 在手写 SSE 帧，用 events.sse()：{handwritten}"
    assert not own_stream, f"这些 router 自己开流，用 deps.sse_response()：{own_stream}"
