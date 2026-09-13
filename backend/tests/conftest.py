"""每个测试默认用自己的临时 sqlite：之前只有一半的测试文件记得 monkeypatch `store._db_path`，
另一半（比如带 BASE 中间件跑循环的 test_harness_loop）把运行记录写进了开发库——dev 库里攒了
`t:n` / `chart:n` 各 50 行（第 174 轮巡检发现）。要用真库的测试自己再 monkeypatch 回去。"""

from __future__ import annotations

import pytest

from app.database import store


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    yield
