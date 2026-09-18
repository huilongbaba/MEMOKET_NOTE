"""六个 block 模式的 `stop_when`（计划 4.6 / [EVAL] 问题三）。

在这之前它们**一条都没有**：note 有 4 条、section 有 2 条、block 0 条，唯一的
提前收场方式是 `complete` / `blocked`，否则跑满 3 轮。

[EVAL] 当时写的是「加之前先看每轮数据」。数据在
`scripts/block_rounds_probe.py` 跑出来的 18 次真跑 / 38 轮里，而这一份测试
**逐字回放那批真跑的形状**——不是构造一个好看的用例，是把实拍的那三条轨迹
（`prompt` 三轮分数一字不差、`analysis` 第 3 轮工具全重复、`table` 第 2 轮
工具全重复但第 3 轮才 complete）钉成断言。

*最后那一条是反面用例，也是这一批最要紧的一条*：按 [EVAL] 的字面加「工具
调用全是重复的就停」，`table` 那次跑会被停在一份没达标的产出上。
"""

from __future__ import annotations

from app.harness import modes
from app.harness.middleware.ledger import Ledger
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import DimensionScore, Evaluation


def _st(mode_key: str = "prompt", round_: int = 2) -> State:
    st = State(mode=modes.BLOCK[mode_key],
               ctx=ToolContext(user="u", note_id="n"))
    st.round = round_
    return st


def _score(**levels) -> Evaluation:
    return Evaluation(scores={k: DimensionScore(v, "") for k, v in levels.items()},
                      status="continue", weakest=min(levels, key=levels.get))


# ------------------------------------------------- nothing_changed ---
#
# 实拍：`prompt` 那一次跑三轮的分数向量逐字相同
# （checklist_1/2/3 全 2、fits_context 卡在 1、follows_prompt / no_fabrication 2）。

REAL_PROMPT_VECTOR = dict(checklist_1=2, checklist_2=2, checklist_3=2,
                          fits_context=1, follows_prompt=2, no_fabrication=2)


def test_六个block模式都挂上了这两条():
    """**建了判据不等于用了判据。** 漏挂一个模式不会报错，只会让它继续
    跑满三轮，而那正是这一条要治的事。"""
    for key, mode in modes.BLOCK.items():
        names = {f.__name__ for f in mode.stop_when}
        assert names == {"nothing_changed", "tools_ran_dry"}, key


def test_分数向量跟上一轮一字不差就停():
    st = _st()
    st.bag["score_vectors"] = [dict(REAL_PROMPT_VECTOR), dict(REAL_PROMPT_VECTOR)]
    assert modes.nothing_changed(st) == "nothing_changed"


def test_有一维动了就不停():
    """哪怕只从 1 动到 2——分数一动就说明这一轮的改动落在了某条判据的视野里。"""
    st = _st()
    moved = dict(REAL_PROMPT_VECTOR, fits_context=2)
    st.bag["score_vectors"] = [dict(REAL_PROMPT_VECTOR), moved]
    assert modes.nothing_changed(st) is None


def test_第一轮不停():
    st = _st(round_=1)
    st.bag["score_vectors"] = [dict(REAL_PROMPT_VECTOR)]
    assert modes.nothing_changed(st) is None


def test_判据短路的轮次不进比对():
    """判据伪造的 `Evaluation` 只有一个维度、分数 0，跟真分数向量不可比。
    混进来的话，连着两轮被同一条判据打回会被读成「什么都没变」，而
    `Checks.STUCK_ROUNDS` 对那一档另有安排（拦两轮是给修订的机会）。"""
    import asyncio

    st = _st()
    st.ev = _score(table_validity=0)
    st.skip_judge = True
    asyncio.run(Ledger().after_judge(st))
    assert st.bag.get("score_vectors") in (None, [])

    st.ev, st.skip_judge = _score(**REAL_PROMPT_VECTOR), False
    asyncio.run(Ledger().after_judge(st))
    assert st.bag["score_vectors"] == [REAL_PROMPT_VECTOR]


# -------------------------------------------------- tools_ran_dry ---


def test_工具调用全是重复的而且这一轮不是最好的就停():
    """实拍：`analysis` 那两次跑的第 3 轮——4 次工具调用 4 次重复，
    分数被 `numbers_from_tools` 打回 0，交的是第 2 轮。"""
    st = _st("analysis", round_=3)
    st.content = "第三轮写的"
    st.best = ((3, 1.4), "第二轮写的")
    st.bag["ledger_round"] = {"tool_calls": 4, "repeat_calls": 4}
    assert modes.tools_ran_dry(st) == "tools_ran_dry"


def test_这一轮成了最好的那一轮就不停():
    """**这条是数据当场否掉字面规则的那一条。**

    实拍：`table` 那一次跑第 2 轮工具全重复（1 次调用 1 次重复）、正文也只跟
    上一轮差 0.14，而**第 3 轮才达到 `complete`**。按字面「工具全重复就停」，
    那次跑会被停在 `fits_context=1` 的产出上。
    """
    st = _st("table", round_=2)
    st.content = "第二轮写的"
    st.best = ((2, 1.67), "第二轮写的")          # 这一轮就是最好的
    st.bag["ledger_round"] = {"tool_calls": 1, "repeat_calls": 1}
    assert modes.tools_ran_dry(st) is None


def test_还有新查询就不停():
    st = _st("eda", round_=2)
    st.content = "这一轮"
    st.best = ((1, 0.5), "上一轮")
    st.bag["ledger_round"] = {"tool_calls": 4, "repeat_calls": 3}   # 实拍的 eda 第 2 轮
    assert modes.tools_ran_dry(st) is None


def test_一次工具都没调不算查到头():
    """`prompt` / `custom` 经常一次工具都不调（实拍 38 轮里有 9 轮 tool_calls=0）。
    「没查」跟「查到头了」是两件事——判据宁可窄一点。"""
    st = _st("custom", round_=2)
    st.content = "这一轮"
    st.best = ((1, 0.5), "上一轮")
    st.bag["ledger_round"] = {"tool_calls": 0, "repeat_calls": 0}
    assert modes.tools_ran_dry(st) is None


def test_第一轮不算查到头():
    st = _st("eda", round_=1)
    st.bag["ledger_round"] = {"tool_calls": 2, "repeat_calls": 2}
    assert modes.tools_ran_dry(st) is None


# ----------------------------------------------------- 顺序 / 边界 ---


def test_达标那一轮永远先停在complete上():
    """实拍里 `chart` 和 `table` 各有一次第 2 轮**又 complete 又工具全重复**。
    `loop.BUILTIN_STOPS`（complete / blocked / no_progress / regressed）排在
    `mode.stop_when` **前面**，所以这两条新判据够不到它——收场理由必须还是
    `complete`，不然 SSE 那一行会告诉用户「查到头了」而其实是写完了。"""
    from app.harness import loop

    assert loop.BUILTIN_STOPS[0].__name__ == "_complete"
    st = _st("chart", round_=2)
    st.content = "这一轮"
    st.best = ((4, 2.0), "上一轮")
    st.bag["ledger_round"] = {"tool_calls": 1, "repeat_calls": 1}
    st.ev = Evaluation(scores={"chart_validity": DimensionScore(2, "")},
                       status="complete")
    assert loop._stop(st) == "complete"


def test_长文那两条没被这两条顶掉():
    """block 的停机条件不许挂到长文上：`material_used_up` / `stalled` /
    `nothing_left_to_fix` / `pause_for_review` 是两批人花了好几轮定下来的。"""
    # `check_stuck`（P6 问题 4）是长文自己的：同一条判据连响三轮就停，block 模式
    # 三轮封顶本来就到不了那一档。
    assert {f.__name__ for f in modes.NOTE.stop_when} == {
        "check_stuck", "material_used_up", "stalled", "nothing_left_to_fix", "pause_for_review"}
    assert {f.__name__ for f in modes.SECTION.stop_when} == {
        "check_stuck", "material_used_up", "pause_for_review"}


def test_停机条件是只读的():
    """`loop.py` 那段注释写死了：会改状态的停机条件会让「为什么停的」
    变成一个答不出来的问题。所以「上一轮判了多少」由 `Ledger` 记。"""
    st = _st()
    st.bag["score_vectors"] = [dict(REAL_PROMPT_VECTOR), dict(REAL_PROMPT_VECTOR)]
    st.bag["ledger_round"] = {"tool_calls": 4, "repeat_calls": 4}
    before = repr(sorted(st.bag.items(), key=lambda kv: kv[0]))
    modes.nothing_changed(st)
    modes.tools_ran_dry(st)
    assert repr(sorted(st.bag.items(), key=lambda kv: kv[0])) == before
