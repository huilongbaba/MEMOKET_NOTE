"""/api/health：两个外部探测必须并行。

实测桌面版每次启动等 6.5s 才知道 LLM 红不红——LLM /models 1.6s、语音服务（局域网
上没开的机器）等满 5s 超时，两个串着跑。这里把两个探测都换成各睡 0.3s 的假函数，
串行会 ≥0.6s，并行 <0.5s。
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store  # noqa: E402
from app.database.ingest import asr  # noqa: E402


def test_health_probes_run_concurrently(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")

    async def slow_asr() -> bool:
        await asyncio.sleep(0.3)
        return False

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k):
            await asyncio.sleep(0.3)
            return _Resp()

    import app.main as main
    monkeypatch.setattr(asr, "healthy", slow_asr)
    monkeypatch.setattr(main.httpx, "AsyncClient", _Client)

    with TestClient(main.app) as c:
        t0 = time.perf_counter()
        r = c.get("/api/health")
        dt = time.perf_counter() - t0
    assert r.status_code == 200
    body = r.json()
    assert body["llm"]["ok"] is True and body["asr"]["ok"] is False
    assert dt < 0.55, f"两个探测串行了：{dt:.2f}s"
