"""剩下那三处「两边各写一遍、谁都没盯着」的对拍（P40 · A）。

判据只留一份：``shared/twin-cases.json``，前端那份由 ``frontend/scripts/check-twin-parity.mts`` 跑。

  ① 记忆范围的标签（``kb/scope.SCOPE_LABEL`` ↔ ``frontend/src/api.SCOPE_LABEL``）——
     「全部」不含屏幕活动这件事是**写在标签里**的承诺，两边漂了就有一边在说假话。
  ② 占位标题那一组（``harness/tray.PLACEHOLDER_TITLES`` ↔ ``util/displayTitle.PLACEHOLDER``）。
  ③ 空行分段（``checks/skeleton._paragraphs`` ↔ ``editor/marginMemory.paragraphsWithLines``）——
     **段落文本拿去查关系、行号回来画页边圆点**，两边切得不一样，点就画在别的段上。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.database.kb import scope as kb_scope
from app.harness import tray
from app.harness.checks import skeleton

TABLE = json.loads(
    (Path(__file__).resolve().parents[2] / "shared" / "twin-cases.json").read_text(encoding="utf-8")
)


def test_用例表还在():
    assert len(TABLE["paragraphs"]) >= TABLE["paragraphs_min_cases"]


def test_记忆范围的五个标签逐字跟表一致():
    assert kb_scope.SCOPE_LABEL == TABLE["scope_label"]
    assert set(kb_scope.SCOPES) == set(TABLE["scope_label"]), "标签少一档或多一档，下拉框就跟实现对不上"


def test_占位标题那一组跟表一致():
    assert tray.PLACEHOLDER_TITLES == frozenset(TABLE["placeholder_titles"])


@pytest.mark.parametrize("case", TABLE["paragraphs"], ids=lambda c: c["name"])
def test_空行分段跟共享用例表一致(case):
    got = [{"line": ln, "text": txt} for ln, txt in skeleton._paragraphs(case["content"])]
    assert got == case["expect"], f"{case['name']}：后端 {got!r}"
