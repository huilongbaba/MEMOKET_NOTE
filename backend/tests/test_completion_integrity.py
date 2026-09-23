from app.harness import loop, modes
from app.harness.completion import unfinished_reasons
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import DimensionScore, Evaluation


def _state(content: str, *, mode=modes.NOTE) -> State:
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n"), content=content)
    st.ev = Evaluation(scores={"coherence": DimensionScore(2, "")}, status="complete")
    return st


def test_明说待补的草稿不能再报完成():
    st = _state("# 项目复盘\n\n已经写好的内容。\n\n这里需要补上关键指标的实际记录。")
    assert unfinished_reasons(st.content) == ["正文明确标了待补材料"]
    assert loop._complete(st) == "needs_input"


def test_空章节不能再报完成():
    st = _state("# 项目复盘\n\n## 已发生的事\n\n有内容。\n\n## 下一步\n")
    assert unfinished_reasons(st.content) == ["有 1 个空章节（下一步）"]
    assert loop._complete(st) == "needs_input"


def test_完整长文仍然按评分结果完成():
    st = _state("# 项目复盘\n\n## 已发生的事\n\n有内容。\n\n## 下一步\n\n下一步先验证关键假设。")
    assert unfinished_reasons(st.content) == []
    assert loop._complete(st) == "complete"


def test_说不需要补材料不是待补标记():
    st = _state("# 结论\n\n现有记录已经足够，不需要补上新的案例。")
    assert unfinished_reasons(st.content) == []
    assert loop._complete(st) == "complete"


def test_英文待办标记同样不能报完成():
    st = _state("# Project review\n\nCompleted context.\n\nTODO: add verified outcome metrics.")
    assert unfinished_reasons(st.content) == ["正文明确标了待补材料"]
    assert loop._complete(st) == "needs_input"


def test_英文计划待办同样不能报完成():
    st = _state("# Project review\n\nComplete draft.")
    assert unfinished_reasons(st.content, ["TBD: confirm the launch date"]) == [
        "写作计划还有 1 项未覆盖"]


def test_block生成模板不受长文交付闸影响():
    st = _state("## 待补：请输入数据", mode=modes.BLOCK["custom"])
    assert loop._complete(st) == "complete"
