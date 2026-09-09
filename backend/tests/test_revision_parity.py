"""后端和前端对同一条修订必须算出同一个结果。

锚点语义有两份实现：后端 `harness/revision.py` 的 ``apply_revision()``（自动
应用，没人审核），前端 `components/RevisionPanel.tsx` 的 ``applyRevision()``
（用户点「接受」）。两份是有意的——后端不能指望一份只跑在浏览器里的代码。

代价是它们会漂，而且实测漂过：同一条去重修订，后端删掉重复的那一节，前端
把**整篇笔记删光**（只剩一个换行）。用户点一下「接受」就丢了整篇内容，界面
上不会有任何报错。

`shared/revision-cases.json` 是两边共同的判据。这里读它跑后端那一份；前端
那一份由 `frontend/scripts/check-revision-parity.mts` 读同一张表跑一遍，
接在 `npm test` 里。谁漂了谁红。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.harness.revision import apply_revision

CASES = json.loads(
    (pathlib.Path(__file__).resolve().parents[2] / "shared" / "revision-cases.json")
    .read_text(encoding="utf-8"))["cases"]


def test_用例表本身没有退化():
    assert len(CASES) >= 8, "用例被删了？两边的判据就是这张表"
    assert any(c.get("anchor_end") for c in CASES), "没有带结尾标记的用例"
    assert {c["op"] for c in CASES} >= {"insert", "insert_before", "delete", "replace"}


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_后端按共享用例表的语义来(case):
    got = apply_revision(case["content"], case["op"], case["anchor"],
                         case.get("text", ""),
                         anchor_end=case.get("anchor_end", ""))
    assert got == case["expected"]
