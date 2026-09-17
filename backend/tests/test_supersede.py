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


def test_更正行必须活过打分那一侧的截断():
    """**批 11 H2 的原样复现。** `supersede` 的注释写着「不按 `fact_budget`
    再裁一刀，否则被更正的那条反而留在材料里，比不补更糟」——但它 append 在
    `st.facts` 末尾，而 `score_context.material()` 是从头累加、到 6000 字
    `break`（实测 60 条 806 字只留 11 条）。**它防的那个失败模式在打分器那一侧
    原样发生**：旧的那条在前面留着，说它过时的那一行被切掉。

    所以这条闸钉的是「材料塞满时更正行还在不在」，不是「supersede 加没加」。
    """
    from app.harness import score_context

    led = _led(("old", "DVT 定在 6 月 3 日"))
    added, _ = apply(led, [], superseded={"old": "new"}, conflicts={},
                     lookup=_kb(new={"id": "new", "text": "DVT 推到 8 月 5 日",
                                     "when": "2026-08-05"}))
    # 先把预算塞满，再按生产的顺序把更正接在末尾（`Supersede.after_prepare`）
    filler = [f"[f{i}] " + "把材料塞满的一条事实。" * 20 for i in range(60)]
    block = score_context.material(filler + added)
    assert sum(len(f) for f in filler) > score_context.MATERIAL_CHARS, \
        "填充材料没超预算，这条用例就没在测截断"
    assert "DVT 推到 8 月 5 日" in block, "更正行被截断切掉了"
    assert "[old]" in block and "以这条为准" in block
    assert "把材料塞满的一条事实" in block, "别把正经材料整块挤没了"


def test_未裁决的提醒也带记号():
    """两条分支写出来的行都要能活过截断——被切掉的那一条是「别当定论」，
    切掉之后留在材料里的正是那条**可能是误报**的事实，一个字的提示都没有。"""
    from app.harness.score_context import NOTICE_MARK

    led = _led(("a", "定价 159 美元"))
    added, _ = apply(led, [], superseded={},
                     conflicts={"a": ("b", "跟知识库 2026-03-04 的记录不一致。")},
                     lookup=_kb())
    assert NOTICE_MARK in added[0]


def test_带回来的那条仍然算给过的材料():
    """记号只能放行尾：`citations.supplied_ids` 认的是**行首**那个 `[事实 id]`，
    记号插到行首，模型引用带回来的那条新事实时会被当成悬空引用去查库。"""
    from app.harness.checks.citations import supplied_ids

    led = _led(("old", "旧的"))
    added, _ = apply(led, [], superseded={"old": "terrence-2046-2F3"}, conflicts={},
                     lookup=_kb(**{"terrence-2046-2F3": {"id": "terrence-2046-2F3",
                                                         "text": "新的", "when": ""}}))
    assert "terrence-2046-2F3" in supplied_ids(added)
