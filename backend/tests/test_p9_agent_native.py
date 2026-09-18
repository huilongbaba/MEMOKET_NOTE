"""P9（产品就绪计划 §2 C2 + B 线遗留，`docs/TRACELOG-product.md` P9 节）：后端管得着的几条。

  文档意图（`editor/intent.py`，agent-native-editor §3.1）：normalize / as_text / block 三个纯函数；
      `PUT /api/notes/{id}/intent` 落库、`GET /api/notes` 带回；骨架 / 重写 / 扩展 / 校验 / 排版的
      system prompt **第一段**是它（空意图一个字不加）
  页边圆点连事实一起回（`relations/batch` 的 `facts`，§3.3 边缘记忆）：卡上要能说「上次记的是 6/3」
  来龙去脉 × 模型报错：KITE 把 provider 异常吞成「No information」——现在第一次失败之后不再重试 /
      退避，`ask()` 抛 `ProviderFailed`，`/api/memory/trace` 回 502 + 一句人话（不再说「没记录」）

    cd backend && python -m pytest tests/test_p9_agent_native.py -v
"""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store  # noqa: E402
from app.database.kite import kite_memory  # noqa: E402
from app.editor import intent  # noqa: E402
from app.routers import compose, compose_block  # noqa: E402

FRONTEND_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "util" / "docIntent.ts"
H = {"X-User-Id": "u1"}


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app
    return TestClient(app)


# ================================================================ 文档意图：纯函数


def test_intent_normalize_收成一行_封顶_来源只认两种():
    d = intent.normalize({"goal": "  写清\n楚 ", "reader": "x" * 500, "done": None, "source": "prefill"})
    assert d["goal"] == "写清 楚"
    assert len(d["reader"]) == intent.FIELD_MAX
    assert d["done"] == ""
    assert d["source"] == "prefill"
    assert intent.normalize({"source": "robot"})["source"] == ""
    assert intent.normalize("not a dict") == {"goal": "", "reader": "", "done": "", "source": "", "checked": []}


def test_intent_as_text_只列填了的_跟前端同一格式():
    assert intent.as_text({"goal": "本周汇报", "reader": "", "done": "每条有日期"}) == "目标：本周汇报；完成标准：每条有日期"
    assert intent.as_text({}) == ""
    # 前端 `intentText` 用的标签和分隔符要跟这里一样（一份两处，逐字核对）
    ts = FRONTEND_TS.read_text(encoding="utf-8")
    for label in intent.FIELD_LABEL.values():
        assert f"'{label}'" in ts, f"前端 docIntent.ts 缺标签 {label}"
    assert ".join('；')" in ts and "`${INTENT_LABEL[k]}：${i[k].trim()}`" in ts


def test_intent_block_空意图一个字不加_有意图是第一段():
    assert intent.block("") == ""
    assert intent.block("   ") == ""
    b = intent.block("目标：本周汇报")
    assert b.startswith(intent.HEAD + "目标：本周汇报")
    assert intent.DONE_HINT in b and b.endswith("\n\n")
    # 前端带过来的那句也封顶，别让一段正文冒充意图撑爆 system
    assert len(intent.block("x" * 5000)) < 1000


# ================================================================ 文档意图：落库 + 接口


def test_intent_put_get_roundtrip(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    n = c.post("/api/notes", headers=H, json={"title": "第 37 周周报", "content": "x"}).json()
    # 库里没有 = 四个空串 + 空的勾选列表（P12 加的 checked），不是缺字段
    assert n["intent"] == {"goal": "", "reader": "", "done": "", "source": "", "checked": []}
    r = c.put(f"/api/notes/{n['id']}/intent", headers=H, json={"goal": "本周汇报", "reader": "老板", "done": "每条有日期", "source": "user"})
    assert r.status_code == 200
    assert r.json()["intent"] == {"goal": "本周汇报", "reader": "老板", "done": "每条有日期", "source": "user", "checked": []}
    got = next(x for x in c.get("/api/notes", headers=H).json() if x["id"] == n["id"])
    assert got["intent"]["goal"] == "本周汇报"
    # 全空也照存 = 「这篇不要意图」
    assert c.put(f"/api/notes/{n['id']}/intent", headers=H, json={}).json()["intent"]["goal"] == ""
    assert c.put("/api/notes/nope/intent", headers=H, json={"goal": "x"}).status_code == 404


def test_intent_坏JSON不让接口500(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    n = c.post("/api/notes", headers=H, json={"title": "t", "content": "x"}).json()
    with store.connect() as conn:
        conn.execute("UPDATE notes SET intent='{not json' WHERE id=?", (n["id"],))
    assert c.get("/api/notes", headers=H).status_code == 200


# ================================================================ 文档意图：进 system 第一段


class _Capture:
    def __init__(self):
        self.systems: list[str] = []

    async def complete(self, messages, **kw):
        self.systems.append(messages[0]["content"])
        return json.dumps({"text": "改写", "reason": "r"})

    async def complete_json_raw(self, messages, **kw):
        self.systems.append(messages[0]["content"])
        return {"spine": "s", "beats": ["已写：a"]}, ""

    async def complete_json(self, messages, **kw):
        self.systems.append(messages[0]["content"])
        return []


@pytest.fixture
def cap(monkeypatch):
    c = _Capture()
    for mod in (compose, compose_block):
        monkeypatch.setattr(mod.llm, "complete", c.complete, raising=False)
        monkeypatch.setattr(mod.llm, "complete_json_raw", c.complete_json_raw, raising=False)
        monkeypatch.setattr(mod.llm, "complete_json", c.complete_json, raising=False)
    return c


@pytest.mark.parametrize("path,body", [
    ("/api/skeleton", {"title": "t", "content": "正文" * 20, "intent": "目标：本周汇报"}),
    ("/api/rewrite", {"content": "这一段要改", "selection": "这一段要改", "intent": "polish", "doc_intent": "目标：本周汇报"}),
    ("/api/compose/restructure", {"note_id": "n", "content": "第一行\n第二行", "intent": "目标：本周汇报"}),
])
def test_intent_是_system_的第一段(tmp_path, monkeypatch, cap, path, body):
    c = _client(tmp_path, monkeypatch)
    r = c.post(path, headers=H, json=body)
    assert r.status_code == 200, r.text
    assert cap.systems and cap.systems[-1].startswith(intent.HEAD + "目标：本周汇报"), cap.systems[-1][:120]


def test_intent_空着时_system_原样(tmp_path, monkeypatch, cap):
    c = _client(tmp_path, monkeypatch)
    assert c.post("/api/skeleton", headers=H, json={"title": "t", "content": "正文" * 20}).status_code == 200
    assert not cap.systems[-1].startswith(intent.HEAD)


# ================================================================ 页边圆点连事实一起回


def test_relations_batch_每个点带事实(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    from app.routers import memory as memory_router
    rows = [{"id": "f1", "text": "DVT我们给的时间线是6月3号", "date": "2026-06-03", "kind": "plan"}]

    class _Mem:
        def __init__(self, user):
            pass

        def stats(self):
            return {"facts": 1}

        def recall(self, p, limit=8, scope="all"):
            return rows, [], 0.0

        def fact_attrs(self, key):
            return {}

        def source_lines(self, r):
            return []

    monkeypatch.setattr(memory_router, "UserMemory", _Mem)
    r = c.post("/api/memory/relations/batch", headers=H, json={"passages": ["DVT 定在 6月3号，之后再排 PVT。", "没有数字的一段话。"]}).json()
    top, none = r["marks"]
    assert none is None
    assert top["relation"] == "corroborated" and top["fact_ids"] == ["f1"]
    assert [f["id"] for f in top["facts"]] == ["f1"]
    assert top["facts"][0]["when"] == "2026-06-03" and "6月3号" in top["facts"][0]["text"]


# ================================================================ 来龙去脉 × 模型报错


def test_watch_provider_第一次失败之后不再打模型也不睡():
    from memoket_kite.providers import llm as kite_llm
    import time as _t
    calls: list[int] = []

    def boom(*a, **kw):
        calls.append(1)
        raise urllib.error.HTTPError("http://x/v1/chat/completions", 500, "Internal", {}, None)

    real_http, real_time = kite_llm._http_llm, kite_llm.time
    kite_llm._http_llm = boom
    t0 = _t.perf_counter()
    try:
        with kite_memory._watch_provider() as failures:
            for _ in range(3):                       # KITE 一次 ask 大约 3 次 llm()，每次 retries=2（退避 2s + 4s）
                with pytest.raises(Exception):
                    kite_llm.llm("p", model="m")
        assert failures and failures[0] == "模型服务返回 500"
        assert len(calls) == 1, "第一次失败之后不该再真的打模型"
        assert _t.perf_counter() - t0 < 1.0, "失败之后不该再睡退避（原来 3 × (2s + 4s) = 18 秒）"
    finally:
        kite_llm._http_llm, kite_llm.time = real_http, real_time
    # 用完原样装回去
    assert kite_llm._http_llm is real_http and kite_llm.time is real_time


def test_describe_翻译urllib的错():
    assert kite_memory._describe(urllib.error.HTTPError("u", 502, "Bad", {}, None)) == "模型服务返回 502"
    assert kite_memory._describe(urllib.error.URLError("Connection refused")).startswith("模型连不上")
    assert "TimeoutError" in kite_memory._describe(TimeoutError("timed out"))


def test_trace_模型报错回502不说没记录(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    from app.routers import memory as memory_router

    class _Mem:
        def __init__(self, user):
            pass

        def stats(self):
            return {"facts": 3}

        def ask(self, q, limit=10):
            raise kite_memory.ProviderFailed("模型服务返回 500")

    monkeypatch.setattr(memory_router, "UserMemory", _Mem)
    monkeypatch.setattr(store, "get_active_llm_config", lambda: {"base_url": "http://127.0.0.1:1/v1", "api_key": "", "model": "m"})
    r = c.post("/api/memory/trace", headers=H, json={"passage": "众筹 199 美元怎么定的"})
    assert r.status_code == 502
    assert "模型服务返回 500" in r.json()["detail"] and "没有" not in r.json()["detail"]
    assert "127.0.0.1:1" in r.json()["detail"] and "设置" in r.json()["detail"]


def test_ask_有依据就不算失败(monkeypatch):
    """回退拿到了真依据（词法路径）就照常返回——观察器只拦「失败且空手」的。"""
    class _Answer:
        text = "答"
        evidence = [type("F", (), {"id": "f1", "content": "c", "when": "2026-01-01", "kind": "k", "sources": []})()]

    class _Memory:
        @staticmethod
        def load(path, model=""):
            return _Memory()

        def answer_with_evidence(self, q, limit=10):
            from memoket_kite.providers import llm as kite_llm
            with pytest.raises(Exception):
                kite_llm._http_llm("p", 1, 0.0, "m")     # 观察器已装上：这一下记成失败
            return _Answer()

    monkeypatch.setattr(kite_memory, "Memory", _Memory)
    monkeypatch.setattr(kite_memory, "_export_provider_env", lambda: None)
    monkeypatch.setattr(store, "get_active_llm_config", lambda: {"base_url": "http://127.0.0.1:1/v1", "api_key": "", "model": "m"})
    from memoket_kite.providers import llm as kite_llm
    real_http = kite_llm._http_llm
    kite_llm._http_llm = lambda *a, **kw: (_ for _ in ()).throw(urllib.error.HTTPError("u", 500, "x", {}, None))
    try:
        mem = kite_memory.UserMemory("u1")
        monkeypatch.setattr(mem, "ensure", lambda: None)
        text, facts = mem.ask("q")
        assert text == "答" and facts[0]["id"] == "f1"
    finally:
        kite_llm._http_llm = real_http
