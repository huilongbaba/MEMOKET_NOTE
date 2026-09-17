"""被取代的事实接进取材（`harness/middleware/supersede.py`，计划 2.2）。

为什么这几条要紧：知识库**已经知道**「8 月 5 日那条取代了 6 月 3 日那条」
（`kb_conflicts` 表 + 事实上的 `superseded_by` 属性），而写作 harness 全仓
没有一处读它。两条都被取出来、都被写进正文时，`factual_grounding` 判词要的
「没有跟事实矛盾的说法」**它自己判不出哪条是旧的**——两条都真实存在。

最容易写错、也最贵的一条在最后：**未裁决的冲突不许当成取代**。
`harness/conflict_confirm.py` 开头记着实拍：新用户导入两篇真会议记录，
收件箱里两条**全是误报**。拿误报去把一条正确的事实标成过时，是误伤。
"""

from __future__ import annotations

from app.harness.middleware.ledger import blank, fold
from app.harness.middleware.supersede import _pairs, apply


def _facts(*pairs) -> str:
    return "\n".join(f"[{i}] {t}\n    （2026-06-03 · Speaker A · 决定）" for i, t in pairs)


def _led(*pairs) -> dict:
    led = blank()
    fold(led, [("search_memory", {"query": "dvt"}, _facts(*pairs))])
    return led


def _kb(**rows):
    return lambda fid: rows.get(fid)


def test_被取代的事实在账本里标出来():
    led = _led(("old", "DVT 定在 6 月 3 日"))
    _added, hits = apply(led, [], superseded={"old": "new"}, conflicts={},
                         lookup=_kb(new={"id": "new", "text": "DVT 推到 8 月 5 日",
                                         "when": "2026-08-05"}))
    assert hits == 1
    assert led["facts"]["old"]["superseded_by"] == "new"


def test_取代它的那条要一起带回来():
    """**光标出「这条过时了」不够**：模型手上只剩一条旧的，它要么照写，
    要么什么都不写。带回新的那条才有得写。"""
    led = _led(("old", "DVT 定在 6 月 3 日"))
    added, _ = apply(led, [], superseded={"old": "new"}, conflicts={},
                     lookup=_kb(new={"id": "new", "text": "DVT 推到 8 月 5 日",
                                     "when": "2026-08-05"}))
    assert len(added) == 1
    assert "DVT 推到 8 月 5 日" in added[0]
    assert "[new]" in added[0] and "[old]" in added[0], "得写清楚是谁取代了谁"
    assert "2026-08-05" in added[0]


def test_带回来的那条也进账本():
    """它就是「我们手上有的材料」，账本是那份索引，不认得就对不上账。"""
    led = _led(("old", "旧的"))
    apply(led, [], superseded={"old": "new"}, conflicts={},
          lookup=_kb(new={"id": "new", "text": "新的", "when": "2026-08-05"}))
    assert led["facts"]["new"]["state"] == "taken"
    assert led["facts"]["new"]["when"] == "2026-08-05"


def test_取代它的那条取不回来时_至少说一声():
    """id 漂了 / 那条被删了。静默放过等于让模型拿一条已知过时的事实当定论。"""
    led = _led(("old", "旧的"))
    added, hits = apply(led, [], superseded={"old": "gone"}, conflicts={},
                        lookup=_kb())
    assert hits == 1
    assert "取不回来" in added[0] and "[old]" in added[0]


def test_没裁决的冲突只提醒_不声称谁取代谁():
    """`conflict_confirm.py` 实拍：收件箱里两条全是误报（竞品 159 美元 vs
    我们 199 美元，根本不是同一个量）。**判据宁可窄一点，误伤比漏报贵。**"""
    led = _led(("a", "定价 159 美元"))
    added, hits = apply(led, [], superseded={},
                        conflicts={"a": ("b", "跟知识库 2026-03-04 的记录不一致：那里是 199美元。")},
                        lookup=_kb())
    assert hits == 0, "未裁决的不许算成「被取代」"
    assert "superseded_by" not in led["facts"]["a"]
    assert led["facts"]["a"]["conflict_with"] == "b"
    assert "还没裁决" in added[0] and "199美元" in added[0]


def test_已经在材料里的更正不重复补():
    """每一轮都会跑一遍，逐轮往材料里堆同一句话就把这一节挤没了。"""
    led = _led(("old", "旧的"))
    lookup = _kb(new={"id": "new", "text": "新的", "when": ""})
    added, _ = apply(led, [], superseded={"old": "new"}, conflicts={}, lookup=lookup)
    again, _ = apply(led, list(added), superseded={"old": "new"}, conflicts={},
                     lookup=lookup)
    assert again == []


def test_一轮最多补几条():
    led = _led(*[(f"f{i}", f"第 {i} 条") for i in range(20)])
    added, _ = apply(led, [], superseded={f"f{i}": "new" for i in range(20)},
                     conflicts={}, lookup=_kb(new={"id": "new", "text": "新的"}))
    assert len(added) <= 6


def test_冲突两边都认得():
    """取回来的可能是任一边——只认旧那一边，取回新的那条时就一声不吭。"""
    pairs = _pairs([{"new_fact_id": "n1", "old_fact_id": "o1", "say": "对不上"}])
    assert pairs["o1"] == ("n1", "对不上")
    assert pairs["n1"] == ("o1", "对不上")


def test_跟这次跑无关的事实不管():
    """账本里没有的事实 = 这次没取到，跟这次写作无关。"""
    led = _led(("a", "甲"))
    added, hits = apply(led, [], superseded={"别人家的": "x"}, conflicts={},
                        lookup=_kb())
    assert (added, hits) == ([], 0)
