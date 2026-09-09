"""每个 scripts/ 下的脚本都还 import 得进来。

脚本不在测试里，所以重构把它们打断了**没有任何东西会说话**——下次有人要跑
一次质量采样，才发现它三个月前就挂了，而那正是最需要它的时候。

这一轮就抓到一个：`soak.py` 从 `routers/note_harness` import `_BROKEN`，
而那个函数已经搬进 `app/harness/revision.py`（两条 harness 共用，router
之间不该互相 import）。

只测「导得进来」，不测跑得通——脚本要花模型调用、要真实知识库，那是另一
回事。但导不进来是**确定**跑不了的，而且零成本就能挡住。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCRIPTS = sorted((ROOT / "scripts").glob("*.py"))


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_脚本导得进来(path, monkeypatch):
    # 脚本顶层常有 argv 解析和 main()，只 import 不执行——把 argv 收拾干净，
    # 让 `if __name__ == "__main__"` 那一段不触发。
    monkeypatch.setattr(sys, "argv", [str(path)])
    spec = importlib.util.spec_from_file_location(f"_probe_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pass                            # argparse 在没参数时退出，是正常的


def test_脚本目录不是空的():
    """上面那条是 parametrize 的——名单空了它会静默全绿。"""
    assert len(SCRIPTS) >= 10
