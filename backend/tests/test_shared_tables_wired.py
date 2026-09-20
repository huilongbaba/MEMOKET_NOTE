"""**接线洞**：`shared/` 里每一张表都得有两条闸，而且两条都真的被跑到（P40 · A）。

判据表这种东西最容易出的不是「写错了」，是「**写好了没人跑**」——
P32 / P34 / P36 三次都栽在同一个形状上：函数对了、单测也对了，就是没接上去，
规则层的单测一条都抓不住。这里单独一条断言把接线钉死：

  · 每张 `shared/*.json` 都有一个前端 runner 和一个后端 runner，两个文件都在；
  · 前端那个 runner **真的写在 `frontend/package.json` 的 `test` 里**
    （不写进去的话它就是一份放在仓库里没人跑的代码）；
  · `shared/` 下不许有第四种表没登记——新加一张表忘了配闸，这条当场红。

后端那一列不用另外核：它们就是 `tests/` 下的文件，`pytest` 收得到。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 表 → （前端 runner，后端 runner）。**加表就得加这一行**，不然下面第一条红。
GATES = {
    "revision-cases.json": ("scripts/check-revision-parity.mts", "tests/test_revision_parity.py"),
    "done-cases.json": ("scripts/check-done-parity.mts", "tests/test_p13.py"),
    "shape-cases.json": ("scripts/check-shape-parity.mts", "tests/test_shape_parity.py"),
    "precondition-cases.json": ("scripts/check-precondition-parity.mts", "tests/test_precondition_parity.py"),
    "twin-cases.json": ("scripts/check-twin-parity.mts", "tests/test_twin_parity.py"),
}


def test_shared_下的表跟登记的一一对上():
    on_disk = {p.name for p in (ROOT / "shared").glob("*.json")}
    assert on_disk == set(GATES), (
        f"shared/ 下有没登记的表（或登记了不存在的）：多 {on_disk - set(GATES)}、少 {set(GATES) - on_disk}"
    )


def test_每张表的两条闸文件都在():
    for table, (fe, be) in GATES.items():
        assert (ROOT / "frontend" / fe).exists(), f"{table} 的前端闸不在：{fe}"
        assert (ROOT / "backend" / be).exists(), f"{table} 的后端闸不在：{be}"


def test_前端那几条闸真的接在npm_test里():
    """**这条才是接线洞那一条。** 闸写好了不接进 `npm test`，它就是一份没人跑的代码。"""
    pkg = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    script = pkg["scripts"]["test"]
    for table, (fe, _) in GATES.items():
        assert fe in script, f"{table} 的前端闸没接进 npm test：{fe}"


def test_每张表都写清了自己是干什么的():
    """表头那段话是给下一个人看的：这是两边共同的什么契约、谁跑、漂了会怎样。"""
    for table in GATES:
        data = json.loads((ROOT / "shared" / table).read_text(encoding="utf-8"))
        why = data.get("why") or data.get("_why")
        assert why, f"{table} 没写 why"
