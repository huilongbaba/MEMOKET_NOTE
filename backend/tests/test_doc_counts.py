"""文档里那几个数字，得跟代码对得上。

**写在文档里的数字必然会过期**，而且过期了不会有任何症状。第 23 节曾经
写着 harness 是「31 个文件、3193 行」——那是改造刚落地时的快照，后来
prompts 拆了包、check 拆出 pick.py，早就不是那个数了。

只盯**结构性**的那几个：几个 Mode、几个工具、几条 check、几条 middleware。
「多少个文件、多少行」这种改一行就变的量不该写进文档，也就不在这里查。
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.harness import modes
from app.harness.middleware import BASE
from app.harness.tools import registry

DOC = pathlib.Path(__file__).resolve().parents[2] / "docs" / "harness-framework.md"


def _counts() -> dict[str, int]:
    checks = {c.__name__ for m in modes.ALL
              for c in modes.for_run(m, has_profile=True).checks}
    middleware = {type(m).__name__ for m in
                  list(BASE) + [x for mo in modes.ALL for x in mo.extra_mw]}
    return {"Mode": len(modes.ALL), "工具": len(registry._snapshot()),
            "check": len(checks), "middleware": len(middleware)}


@pytest.mark.parametrize("what", ["Mode", "工具", "check", "middleware"])
def test_文档里写的数量跟代码一致(what):
    real = _counts()[what]
    doc = DOC.read_text(encoding="utf-8")
    # 「8 个 Mode」「21 个工具」「9 条 check」「13 个 middleware」
    written = {int(n) for n in re.findall(rf"(\d+) ?[个条] ?{re.escape(what)}\b", doc)}
    assert written, f"文档里一次都没写「N 个{what}」——这条测试在查一个不存在的说法"
    wrong = sorted(written - {real})
    assert not wrong, f"文档里写着 {wrong} 个{what}，实际是 {real}"
