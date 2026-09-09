"""修订这条 middleware：四道防线、插入顺序、大纲保护、失败降级。

跑覆盖率之前这个文件 82 行里有 65 行没被执行过——纯函数那一层
（`harness/revision.py`）测得很细，可**把它们串起来的这一层**几乎是空白：
防线在什么时候被调、丢弃的事件长什么样、同一个锚点上两条插入谁在前、
大纲模式下动了用户标题会怎样、模型调用挂了整轮会不会跟着死。

除了那一次模型调用，这里的一切都是确定性的——把 `llm.stream_events`
打桩就全测得了。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.harness.middleware.revise import Revise
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Dimension, Mode


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """不让它写真库。存不存是另一条断言，用 saved 记下来。"""
    from app.harness.middleware import revise as mod

    saved: list[str] = []
    monkeypatch.setattr(mod.store, "update_note",
                        lambda user, nid, title, content: saved.append(content))
    return saved


def _stub_llm(monkeypatch, payload):
    """让修订这一步「返回」指定的 JSON；payload 是 None 表示调用直接抛异常。"""
    from app.harness.middleware import revise as mod

    async def fake(messages, **kw):
        if payload is None:
            raise RuntimeError("模型超时了")
        yield "thinking", "想一想"
        yield "output", json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(mod.llm, "stream_events", fake)


def _st(content: str, *, round_: int = 2, **bag) -> State:
    mode = Mode(key="t", label="t", skill_scope="test_scope",
                dims=(Dimension("coherence", "..."),))
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="标题"))
    st.content, st.round = content, round_
    st.bag.update(bag)
    return st


def _drive(st) -> list:
    async def go():
        return [e async for e in Revise().before_produce(st)]
    return asyncio.run(go())


def _named(events, name):
    return [e.data["value"] for e in events if e.data.get("name") == name]


# ------------------------------------------------------------ 什么都不做 ---

def test_第一轮不修订(monkeypatch):
    """第一轮还没有正文可修，而且计数必须被重置——循环的「没进展」判断
    读的就是它，上一轮留下的旧值会让一个已经死掉的 run 继续跑。"""
    _stub_llm(monkeypatch, [{"op": "replace", "anchor": "甲", "text": "乙"}])
    st = _st("有正文", round_=1)
    st.bag["revisions_applied"] = 99
    assert _drive(st) == []
    assert st.bag["revisions_applied"] == 0


def test_正文是空的就不修订(monkeypatch):
    _stub_llm(monkeypatch, [{"op": "replace", "anchor": "甲", "text": "乙"}])
    assert _drive(_st("   \n  ")) == []


# ---------------------------------------------------------------- 正常路径 ---

def test_一条替换被应用并存了盘(monkeypatch, _no_db):
    _stub_llm(monkeypatch, [{"op": "replace", "anchor": "旧的说法",
                             "text": "新的说法", "reason": "更准确"}])
    st = _st("前面一段。旧的说法。后面一段。")
    events = _drive(st)
    assert "新的说法" in st.content and "旧的说法" not in st.content
    assert st.bag["revisions_applied"] == 1
    assert _no_db == [st.content], "改了正文就该落盘"
    (rev,) = _named(events, "revision")
    assert rev["op"] == "replace" and rev["reason"] == "更准确"


def test_同一个锚点上的两条插入保持原顺序(monkeypatch):
    """两条 insert 都是「紧贴锚点之后」，不记偏移的话后插的会顶到前面去——
    模型按 3、4 的顺序给，正文里变成 4 在 3 前面。"""
    _stub_llm(monkeypatch, [
        {"op": "insert", "anchor": "锚点", "text": "\n第三条"},
        {"op": "insert", "anchor": "锚点", "text": "\n第四条"},
    ])
    st = _st("锚点")
    _drive(st)
    assert st.content.index("第三条") < st.content.index("第四条")


# ------------------------------------------------------------ 挑出去的那些 ---

def test_锚点不在正文里就跳过(monkeypatch):
    _stub_llm(monkeypatch, [{"op": "replace", "anchor": "根本没有这句", "text": "x"}])
    st = _st("一段正文")
    _drive(st)
    assert st.content == "一段正文" and st.bag["revisions_applied"] == 0


def test_不认识的操作就跳过(monkeypatch):
    _stub_llm(monkeypatch, [{"op": "重写一遍", "anchor": "正文", "text": "x"},
                            "这甚至不是个对象"])
    st = _st("一段正文")
    _drive(st)
    assert st.content == "一段正文"


def test_超出上限的修订不再应用(monkeypatch):
    _stub_llm(monkeypatch, [{"op": "insert", "anchor": f"第{i}句", "text": "补"}
                            for i in range(1, 9)])
    st = _st("".join(f"第{i}句。" for i in range(1, 9)))
    _drive(st)
    assert st.bag["revisions_applied"] == 6, "DEFAULT_MAX_REVISIONS 是 6"


def test_大纲模式下动到用户标题的修订被丢弃(monkeypatch):
    """用户自己搭的骨架是硬约束。提示词里已经写了别动，模型照动不误——
    这是那句话背后的硬防线。"""
    大纲 = "## 一、背景\n\n## 二、现状\n\n## 三、方案\n\n"
    _stub_llm(monkeypatch, [{"op": "replace", "anchor": "## 二、现状",
                             "text": "## 二、我改的标题", "reason": "更顺"}])
    st = _st(大纲, outline_mode=True)
    events = _drive(st)
    assert "## 二、现状" in st.content, "用户的标题被动了"
    assert any("动到你写的标题" in d["detail"] for d in _named(events, "dropped"))


def test_元话语在修订之后也要清掉(monkeypatch):
    """一条 replace 能把审计腔重新塞回正文里。清理只挂在续写那一侧的时候，
    文件夹那条路径上实测漏过。"""
    # 注意替换文本不带句号：带的话会跟锚点后面那个句号连成「。。」，被
    # breakage 那道防线先一步拦下来——素材本身要先过得了前面几道防线，
    # 才测得到最后这一道清理。
    _stub_llm(monkeypatch, [{"op": "replace", "anchor": "占位",
                             "text": "现有材料不足以说明这一点"}])
    st = _st("正文开头。占位。正文结尾。")
    events = _drive(st)
    assert "不足以说明" not in st.content
    assert any("元话语" in d["detail"] for d in _named(events, "dropped"))


# -------------------------------------------------------------------- 降级 ---

def test_修订调用挂了只赔上这一轮的修订(monkeypatch, _no_db):
    """实测：持续压力下一次调用超过 300s 超时，没有这道保护时异常会从 SSE
    生成器里逃出去——客户端看到的是连接被切断，不是一个错误事件。"""
    _stub_llm(monkeypatch, None)
    st = _st("一段正文")
    events = _drive(st)
    assert st.content == "一段正文"
    assert _no_db == [], "什么都没改就不该落盘"
    assert any("修订调用失败" in d["reason"] for d in _named(events, "dropped"))


def test_模型返回的不是数组就整轮跳过(monkeypatch, _no_db):
    _stub_llm(monkeypatch, {"op": "replace", "anchor": "正文", "text": "x"})
    st = _st("一段正文")
    assert _named(_drive(st), "revision") == []
    assert st.content == "一段正文" and _no_db == []


def test_歧义锚点被防线拦下(monkeypatch):
    """短锚点在正文里出现好几次，`find()` 取第一次出现——改的多半不是模型
    想改的那处。防线只拦「无界的 replace」这一种窄情况：删重复段落的锚点
    本来就必须重复，一并拦掉会把去重整个关掉（实测二十轮里 non_repetition
    全是 0 分）。"""
    _stub_llm(monkeypatch, [{"op": "replace", "anchor": "同样的话",
                             "text": "改一下", "reason": "重复"}])
    st = _st("同样的话在这里。中间隔一段。同样的话又出现。同样的话第三次。")
    events = _drive(st)
    assert st.content.count("同样的话") == 3, "正文被改了"
    assert _named(events, "dropped"), "防线该报一条丢弃"


def test_会切出破字的修订被丢弃(monkeypatch):
    """替换文本末尾带句号，接上锚点后面原有的句号就成了「。。」——只有
    **新**出现的破字才算，本来就破的不算这条修订的账。"""
    _stub_llm(monkeypatch, [{"op": "replace", "anchor": "占位",
                             "text": "换成这句话。"}])
    st = _st("正文开头。占位。正文结尾。")
    events = _drive(st)
    assert st.content == "正文开头。占位。正文结尾。"
    assert any("破字" in d["detail"] for d in _named(events, "dropped"))
