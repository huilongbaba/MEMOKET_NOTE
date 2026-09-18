"""P3（产品就绪计划 §2 B 线，`docs/edge-cases.md`）：临界条件表修的第一批里后端管得着的几条。

每条对应台账 `docs/TRACELOG-product.md` P3 节的一格：

  前后端同一份整篇前置判断（`editor/preconditions`）：空正文 → 骨架 / 续写 / 排版 / 幻灯片
      400 + 那句话，一次模型都不调；前端 TS 文件里逐句原样有一份
  模型侧异常翻成人话（`llm.describe_error`）：连不上 / 拒绝 / 401 / 429 / 5xx 各说各的，
      不再把 `HTTPStatusError: … for url 'http://…' For more information check: https://…`
      写进正文里的运行块
  非流式路由冒出来的 httpx 异常 → 502 + 那句话（原来是光秃秃的 500）
  harness 跑挂 → RUN_ERROR 带的是那句话；骨架生成失败是 warning 不是 RUN_ERROR（跑还在继续）
  语音服务的错说语音服务（`asr.describe_error`），不指去 LLM 供应商
  连接超时单独 10 秒（读超时不动）

    cd backend && python -m pytest tests/test_p3_edge_cases.py -v
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store  # noqa: E402
from app.database.ingest import asr  # noqa: E402
from app.editor import preconditions  # noqa: E402
from app.harness import loop  # noqa: E402
from app.harness.events import EventType  # noqa: E402
from app.util import llm  # noqa: E402

FRONTEND_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "editor" / "preconditions.ts"


# ================================================================ 前后端同一份前置判断


def test_precondition_strings_exist_in_frontend_verbatim():
    """`docs/edge-cases.md` 的纪律：**前后端共用同一份前置判断**。前端不能 import 后端，
    所以两边各写一份、这里逐句核对——改一边忘了另一边，这条当场红。"""
    ts = FRONTEND_TS.read_text(encoding="utf-8")
    for action, text in preconditions.EMPTY_NOTE.items():
        assert f"{action}: '{text}'" in ts, f"前端 preconditions.ts 缺 {action} 那句：{text}"
    # 动作集合也要一样：前端多一个后端没有的（或反过来）就是半截实现
    front_actions = set(re.findall(r"^\s+(\w+): '", ts, re.M))
    assert front_actions == set(preconditions.EMPTY_NOTE)


@pytest.mark.parametrize("action,content,title,blocked", [
    ("skeleton", "", "", True),
    ("skeleton", "", "有标题", False),          # 标题一句也够生成骨架
    ("skeleton", "   \n", "", True),
    ("tap", "", "标题", False),
    ("tap", "正文", "", False),
    ("harness", "", "", True),
    ("restructure", "", "有标题也不行", True),   # 只看正文：标题排不了版
    ("slides", "", "标题", True),
    ("polish", "", "标题", True),
    ("ingest", "", "标题", True),
    ("ingest", "一句正文", "", False),
    ("nosuch", "", "", False),                  # 不认识的动作放行（别把新入口误拦）
])
def test_note_precondition(action, content, title, blocked):
    got = preconditions.note_precondition(action, content, title)
    assert bool(got) is blocked
    if blocked:
        assert got == preconditions.EMPTY_NOTE[action]


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app
    return TestClient(app)


def test_blank_note_routes_400_without_model_call(tmp_path, monkeypatch):
    """空正文：骨架 / 续写 / 排版 / 幻灯片四条路由各 400 + 前置判断那句话，**一次模型都不调**。"""
    calls = []

    async def boom(*a, **k):
        calls.append(1)
        raise AssertionError("空正文不该调模型")

    monkeypatch.setattr(llm, "complete", boom)
    monkeypatch.setattr(llm, "complete_json_raw", boom)
    monkeypatch.setattr(llm, "stream", boom)
    c = _client(tmp_path, monkeypatch)
    h = {"X-User-Id": "p3"}
    r = c.post("/api/skeleton", json={"title": "", "content": "  "}, headers=h)
    assert r.status_code == 400 and r.json()["detail"] == preconditions.EMPTY_NOTE["skeleton"]
    r = c.post("/api/magic-tap", json={"content": "", "spine": "", "beats": [], "title": ""}, headers=h)
    assert r.status_code == 400 and r.json()["detail"] == preconditions.EMPTY_NOTE["tap"]
    r = c.post("/api/compose/restructure", json={"note_id": "x", "title": "标题", "content": "\n", "cursor": 0, "mode": "prompt"}, headers=h)
    assert r.status_code == 400 and r.json()["detail"] == preconditions.EMPTY_NOTE["restructure"]
    assert calls == []


# ================================================================ 模型侧异常 → 人话


def _resp(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://model.local/v1/chat/completions")
    return httpx.HTTPStatusError("boom", request=req, response=httpx.Response(code, request=req))


@pytest.mark.parametrize("exc,must,must_not", [
    (httpx.ConnectTimeout("t"), "10 秒内没连上", "HTTPStatusError"),
    (httpx.ConnectError("refused"), "拒绝了连接", "ConnectError"),
    (httpx.ReadTimeout("r"), "太久没应答", "ReadTimeout"),
    (_resp(500), "返回 500", "For more information"),
    (_resp(401), "API key", "401 Unauthorized"),
    (_resp(429), "限流", "429"),
    (_resp(404), "没有这个接口或模型", "Client error"),
    (RuntimeError("模型没按格式答"), "模型没按格式答", "RuntimeError"),
])
def test_describe_error_is_human(exc, must, must_not):
    got = llm.describe_error(exc)
    assert must in got, got
    assert must_not not in got, got
    assert "developer.mozilla.org" not in got
    assert len(got) <= 260


def test_describe_error_names_the_address(monkeypatch):
    monkeypatch.setattr(store, "get_active_llm_config",
                        lambda: {"base_url": "http://192.168.77.8:8080/v1", "api_key": "", "model": "m"})
    assert "192.168.77.8:8080" in llm.describe_error(httpx.ConnectTimeout("t"))


def test_connect_timeout_is_short_read_timeout_is_not():
    """收的只是「根本连不上」那一种：连接 10 秒，读仍是 300 / 600 秒（本地模型算得久是正常的）。"""
    assert llm.TIMEOUT.connect == 10.0 and llm.TIMEOUT.read == 300.0
    assert llm.STREAM_TIMEOUT.connect == 10.0 and llm.STREAM_TIMEOUT.read == 600.0


def test_httpx_error_becomes_502_with_sentence(tmp_path, monkeypatch):
    """校验 / 重写这类非流式路由：模型连不上原来是光秃秃的 500，前端只能说「后端处理出错」。"""
    async def refused(*a, **k):
        raise httpx.ConnectError("All connection attempts failed")

    monkeypatch.setattr(llm, "complete", refused)
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/rewrite", json={"content": "一段正文在这里", "selection": "一段正文", "intent": "rewrite",
                                     "spine": "", "beats": []}, headers={"X-User-Id": "p3"})
    assert r.status_code == 502
    assert "拒绝了连接" in r.json()["detail"]


def test_asr_error_names_the_voice_service(monkeypatch):
    monkeypatch.setattr(store, "get_asr_base_url", lambda: "http://127.0.0.1:1")
    got = asr.describe_error(httpx.ConnectError("refused"))
    assert "语音服务" in got and "127.0.0.1:1" in got
    assert "LLM" not in got
    got = asr.describe_error(_resp(500))
    assert got.startswith("语音服务返回 500")


# ================================================================ harness：RUN_ERROR 只在跑挂时发


def test_loop_run_error_is_human():
    """`loop.run` 顶层兜住的异常翻成人话再发 RUN_ERROR——原来 `f"{type(exc).__name__}: {exc}"`
    把 httpx 的整段（含模型地址、MDN 链接）写进了轮次卡片 / 运行块。"""
    import asyncio
    from app.harness import State
    from app.harness.tools import ToolContext
    from app.harness.types import Dimension, Mode

    class ExplodingHooks:
        async def prepare(self, st):
            raise httpx.ConnectTimeout("t")

        async def produce(self, st):
            yield ""

        async def commit(self, st):
            pass

    mode = Mode(key="t", label="test", skill_scope="test_scope", dims=(Dimension("d0", "..."),))
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n"), request=None)

    async def _collect():
        return [e async for e in loop.run(st, ExplodingHooks())]

    events = asyncio.run(_collect())
    errs = [e for e in events if e.type == EventType.RUN_ERROR]
    assert errs, [e.type for e in events]
    assert "10 秒内没连上" in errs[0].data["message"]
    assert "ConnectTimeout" not in errs[0].data["message"]


def test_skeleton_failure_is_warning_not_run_error():
    """骨架生成失败跑还在继续——它不能再发 RUN_ERROR（前端现在把 RUN_ERROR 当「出错停下」）。"""
    src = (Path(__file__).resolve().parent.parent / "app" / "harness" / "hooks" / "note.py").read_text(encoding="utf-8")
    assert "run_error(" not in src
    assert "CUSTOM_WARNING" in src
    # 全仓只剩 loop.run 一处发 RUN_ERROR
    root = Path(__file__).resolve().parent.parent / "app"
    emitters = [p for p in root.rglob("*.py") if "run_error(" in p.read_text(encoding="utf-8") and p.name != "events.py"]
    assert [p.name for p in emitters] == ["loop.py"], emitters
