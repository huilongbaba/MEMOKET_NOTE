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


# --------------------------------------------------------------- 载荷键 ---
#
# **事件名对得上，不等于载荷键对得上**（批 21 / 计划 11.3）。
# 实拍：`revise.py` 七个 `dropped` 发射点里有一个写的是 `{"reason": …}`，
# 而前端读的是 `v.detail`——于是「修订调用超时，跳过这一轮修订」这条
# 在面板里 push 进去的是 `undefined`，用户看到一条空白项。
# 上面那条 `test_后端每个custom事件前端都接得住` 只查名字，**一声不吭地绿着**。
#
# 「必须有」的定义就写在前端那一行里：
#   · `handlers.onDropped?.(v.detail)` —— 裸读，必须有；
#   · `v.notes ?? []` / `typeof v.round === 'number'` —— 前端自己兜了底，可选。
# 这样这条闸不会去逼后端补一个前端本来就不指望的键。

def _required_payload_keys() -> dict[str, set[str]]:
    src = API_TS.read_text(encoding="utf-8")
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"name === '([a-z_]+)'\)\s*\{?\s*(.*)", src):
        name, line = m.group(1), m.group(2)
        keys = set(re.findall(r"\bv\.([A-Za-z_]\w*)", line))
        # 前端自己给了默认值 / 自己做了类型判断的，不算「必须有」
        keys -= set(re.findall(r"\bv\.([A-Za-z_]\w*)\s*\?\?", line))
        keys -= set(re.findall(r"typeof\s+v\.([A-Za-z_]\w*)", line))
        if keys:
            out[name] = keys
    return out


def _custom_emit_sites():
    """后端每一处 `Event.custom(CUSTOM_X, {...})`：(事件名, 文件:行, 键集合)。

    载荷不是字典字面量的那几处单独返回 `None`——**它们是这条闸的盲区，
    必须显式承认**，不能假装查过了。
    """
    import ast
    consts = {m.group(1): m.group(2) for m in re.finditer(
        r'^(CUSTOM_\w+) = "([a-z_]+)"',
        (ROOT / "backend" / "app" / "harness" / "events.py").read_text(encoding="utf-8"),
        re.M)}
    for f in sorted((ROOT / "backend" / "app").rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "custom" and node.args):
                continue
            name = consts.get(getattr(node.args[0], "id", ""))
            if name is None:
                continue
            payload = node.args[1] if len(node.args) > 1 else None
            keys = ({k.value for k in payload.keys if isinstance(k, ast.Constant)}
                    if isinstance(payload, ast.Dict) else None)
            yield name, f"{f.relative_to(ROOT)}:{node.lineno}", keys


def test_前端裸读的载荷键每个发射点都得有():
    need = _required_payload_keys()
    assert "detail" in need.get("dropped", set()), \
        "前端不再裸读 dropped 的 detail 了——这条闸在查一个不存在的说法"
    bad = []
    for name, where, keys in _custom_emit_sites():
        want = need.get(name)
        if not want or keys is None:
            continue
        if not want <= keys:
            bad.append(f"{where} 发 `{name}` 少了 {sorted(want - keys)}（有 {sorted(keys)}）")
    assert not bad, "这几处的载荷键前端读不到：\n  " + "\n  ".join(bad)


def test_不是字典字面量的发射点要逐处登记():
    """这条闸只看得懂字典字面量。看不懂的那几处**写死在这里**，
    免得下一个人把载荷换成一个变量、闸就安静地不查了。"""
    blind = {where for name, where, keys in _custom_emit_sites()
             if keys is None and name in _required_payload_keys()}
    assert blind == set(), f"新出现了闸看不懂的发射点，去确认它的载荷键：{sorted(blind)}"
