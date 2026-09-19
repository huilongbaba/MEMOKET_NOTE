"""每个测试默认用自己的临时 sqlite：之前只有一半的测试文件记得 monkeypatch `store._db_path`，
另一半（比如带 BASE 中间件跑循环的 test_harness_loop）把运行记录写进了开发库——dev 库里攒了
`t:n` / `chart:n` 各 50 行（第 174 轮巡检发现）。要用真库的测试自己再 monkeypatch 回去。"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile

# 在任何 app 模块 import 之前把数据目录指到临时目录：skills / assets / backups / jobs 这些模块是
# `from ..util.config import get_settings` 按名字绑的，事后 monkeypatch 模块属性够不着它们
# （实拍 test_endpoints 在 backend/data/ 下长出 u1/skills）。环境变量优先级高于 .env。
_TMP_DATA = tempfile.mkdtemp(prefix="memoket-tests-")
os.environ.setdefault("KITE_DATA_DIR", _TMP_DATA)
atexit.register(lambda: shutil.rmtree(_TMP_DATA, ignore_errors=True))

import pytest  # noqa: E402

from app.database import store
from app.database.kite import kite_memory
from app.util.config import get_settings


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    # codebook 也进临时目录：不然 UserMemory("u1") 会在 backend/data/ 下长出 u1 / cancel-test 这种目录
    real = get_settings()
    monkeypatch.setattr(kite_memory, "get_settings", lambda: real.model_copy(update={"kite_data_dir": tmp_path / "kite"}))
    yield


@pytest.fixture(autouse=True)
def _no_journey_sweep(monkeypatch):
    """屏幕活动的保留期清理**默认在测试里关掉**（第 779 轮 / P21）。

    它挂在 `GET /journey/days` 上，按**真实的今天**算日期。而这个仓的 journey
    测试全都拿写死的日期当夹具（`2026-09-14` 这种）——真实时钟一往前走，
    那些夹具就会在测试跑到一半时被真的删掉，于是一批本来无关的测试在某个
    日子之后集体变红。**这是个定时炸弹，不是偶发**。

    要测清理本身的：把这个 fixture 当参数拿进去，`yield` 出来的就是**真的那个**
    （`test_journey_retention.py` 就是这么用的）。
    """
    from app.routers import journey as J

    real = J._sweep_if_due
    monkeypatch.setattr(J, "_sweep_if_due", lambda user: None)
    yield real
