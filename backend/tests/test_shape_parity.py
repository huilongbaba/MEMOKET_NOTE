"""「这一段整个是不是一串 JSON」前后端对拍（P40 · A，P37「留给下一批」②）。

判据只留一份：``shared/shape-cases.json``，这里跑后端 ``harness/checks/shape.looks_like_json``，
前端那份由 ``frontend/scripts/check-shape-parity.mts`` 跑同一张表（接在 ``npm test`` 里）。谁漂了谁红。

**为什么非要一张表。** 两边的注释都写着「逐字同一条」（``blockShape.ts`` 头上那段、
本文件对面那个 ``shape.py`` 的「判据宁可窄」），而 P40 拿这张表一对，**六个样本上两边答得不一样**，
两个根因：

1. ``_unfence`` 的围栏那一行：前端是「第一个换行之前都算」，后端是 ``^```[A-Za-z0-9_-]*\\s*\\n``
   ——``` ```json extra ```、``` ``` json ```（带空格）、``` ```json title=x ``` 后端剥不掉，
   于是整段被当成「以 ``` 开头」直接放行。
2. ``json.loads`` **默认收 ``NaN`` / ``Infinity``**，``JSON.parse`` 不收——``{"a": NaN}``
   后端拦、前端放行。

用户那一侧的后果：同一串产出，``/`` 插一块时被拦下，智能续写那条路上却原样落进正文。
**注释不是闸。**
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.harness.checks import shape

TABLE = json.loads(
    (Path(__file__).resolve().parents[2] / "shared" / "shape-cases.json").read_text(encoding="utf-8")
)
CASES = TABLE["cases"]


def test_用例表还在():
    """判据就是这张表——删空了它，两边的闸就都是绿的假象。"""
    assert len(CASES) >= TABLE["min_cases"], f"用例只剩 {len(CASES)} 条"
    negatives = [c for c in CASES if not c["json"]]
    assert len(negatives) >= TABLE["min_counterexamples"], (
        f"反例只剩 {len(negatives)} 条——「正常产出不许被拦」那一侧塌了，这张表就只剩半边"
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_后端跟共享用例表一致(case):
    got = shape.looks_like_json(case["text"])
    assert got is case["json"], (
        f"{case['name']}：后端 {got}，表里是 {case['json']}\n  样本: {case['text']!r}"
    )


def test_落正文那一刀跟判据用的是同一条():
    """``json_paragraphs`` 摘段落时用的必须是同一个 ``looks_like_json``——
    两条路各判各的话，判据说「这一轮答的是 JSON」而 ``fix`` 一段都摘不掉，
    ``fix_done`` 永远为真、正文留着那串 JSON（P23 #1 那条的形状）。

    量程：表里每一条正面样本，单独成段时都得被 ``json_paragraphs`` 摘出来。"""
    for case in CASES:
        text = case["text"].strip()
        if not text:
            continue
        got = shape.json_paragraphs(text)
        assert bool(got) is case["json"], f"{case['name']}：json_paragraphs 跟 looks_like_json 漂了"
