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
    """不让它写真库。存不存是另一条断言，用 saved 记下来。

    批 16 起 `Revise` 不再自己调 `store.update_note`，而是走
    `middleware/save.persist`（写库全仓只有一个出口，而且那个出口自己认
    `rails_off`）——所以桩打在 `save.store` 上。"""
    from app.harness.middleware import save as save_mod

    saved: list[str] = []
    monkeypatch.setattr(save_mod.store, "update_note",
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
    # 客户端要在本地删同一句：scrub 事件带全量整句（dropped 那条是给面板看的、截过）
    (sc,) = _named(events, "scrub")
    assert sc["why"] == "元话语" and "不足以说明" in sc["sentence"] and sc["sentence"].strip() == sc["sentence"]


# -------------------------------------------------------------------- 降级 ---

def test_修订调用挂了只赔上这一轮的修订(monkeypatch, _no_db):
    """实测：持续压力下一次调用超过 300s 超时，没有这道保护时异常会从 SSE
    生成器里逃出去——客户端看到的是连接被切断，不是一个错误事件。"""
    _stub_llm(monkeypatch, None)
    st = _st("一段正文")
    events = _drive(st)
    assert st.content == "一段正文"
    assert _no_db == [], "什么都没改就不该落盘"
    # 键名是 `detail`（批 21 / 计划 11.3）。原来这里跟着实现一起写的是
    # `reason`，而前端读的是 `v.detail`——**测试跟着被测代码一起错**，
    # 于是一条空白项在面板上待了很久，全套照绿。
    # （同一个形状：批 20 计划外发现 3「跟着被测常量一起变的断言」。）
    assert any("修订调用失败" in d["detail"] for d in _named(events, "dropped"))


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


def test_同一段不能连着两轮被改写(monkeypatch):
    """跨轮去重：改过的锚点记在 ``st.bag["edited_spans"]`` 里，**整个 run**
    有效，不是这一轮有效。

    没有它的时候，修订这一步会跟自己吵架——同一段连着三轮被重写，每轮
    只换措辞。这条以前只有一句「源码里有没有 `st.bag.setdefault(
    "edited_spans", set())`」的断言：改个变量名它就红，而真把去重删了、
    只要那行字符串还在，它照样绿。
    """
    _stub_llm(monkeypatch, [{"op": "replace", "anchor": "这一段要改",
                             "text": "改过一次了"}])
    st = _st("前面。这一段要改。后面。")
    _drive(st)
    assert "改过一次了" in st.content
    assert st.bag["revisions_applied"] == 1

    # 第二轮：模型又想改同一处（换个说法），必须被拦
    _stub_llm(monkeypatch, [{"op": "replace", "anchor": "改过一次了",
                             "text": "再换个说法"}])
    st.bag["edited_spans"].add("改过一次了")     # 上一轮记下的就是这个 key
    st.round = 3
    events = _drive(st)
    assert "再换个说法" not in st.content, "同一段被连着改了两轮"
    assert _named(events, "dropped"), "拦下来了却没说一声"


def test_只做了元话语清理也要落盘(monkeypatch, _no_db):
    """一条修订都没应用、但清掉了一句审计腔——这也是改动，不落盘就丢了。

    以前这条靠「源码里有没有 `if applied or meta_gone:`」来断言：改个变量
    名它就红，真把 or 那半边删了、只要字符串还在它照样绿。
    """
    _stub_llm(monkeypatch, [])          # 模型一条修订都没提
    st = _st("正文开头。现有材料不足以说明这一点。正文结尾。")
    _drive(st)
    assert st.bag["revisions_applied"] == 0
    assert "不足以说明" not in st.content
    assert _no_db == [st.content], "只做了清理就没存，这次清理白做了"


def test_被防线丢弃的修订不能用错误事件报(monkeypatch):
    """四道防线一轮能丢好几条。全用 error 报的话，界面会渲染成一片红色
    报错——而这恰恰是防线在正常工作的样子。"""
    _stub_llm(monkeypatch, [
        {"op": "replace", "anchor": "同样的话", "text": "改"},        # 歧义锚点
        {"op": "replace", "anchor": "占位", "text": "换成这句话。"},   # 破字
    ])
    st = _st("同样的话在这里。同样的话又出现。同样的话第三次。占位。结尾。")
    events = _drive(st)
    assert _named(events, "dropped"), "防线该报丢弃"
    assert not [e for e in events if e.type.value == "RUN_ERROR"], \
        "丢弃被当成错误报了"


def test_修订事件带全量的_anchor_和_text(monkeypatch, _no_db):
    """客户端拿这条事件在本地重放同一条修订：text 截到 300 字它就只插前 300 字、anchor 截到 120 字
    它就定位失败——第 375 轮真跑第 3 轮本地跟服务端差 267 字。面板要短的自己截。"""
    long_anchor = "锚" * 150
    long_text = "新" * 400
    _stub_llm(monkeypatch, [{"op": "replace", "anchor": long_anchor, "text": long_text, "reason": "长"}])
    st = _st("前面。" + long_anchor + "。后面。")
    events = _drive(st)
    (rev,) = _named(events, "revision")
    assert rev["anchor"] == long_anchor and rev["text"] == long_text
    assert long_text in st.content


# ------------------------------------------- 提出 / 落地 两个数（计划 11.3） ---
#
# 「被丢掉的修订用户看不到、我们也没统计」。看不到那一半是 `dropped` 事件的事
# （载荷键的闸在 `test_event_contract`）；**没统计**这一半在这里：
# `revisions_proposed` / `revisions_dropped` 进 `st.bag`，`Ledger` 再落进
# `harness_rounds`。两个数一起，因为只有分子说明不了任何事。

def test_丢掉的修订要算进_bag_里的那两个数(monkeypatch, _no_db):
    """四条提议：一条能落地，三条分别栽在 op / 锚点 / 空改上。
    **后三条一个 `dropped` 事件都不发**——所以分子只能是「提出减落地」，
    不能是「数一数发了几条事件」。"""
    _stub_llm(monkeypatch, [
        {"op": "replace", "anchor": "第二段。", "text": "改好的第二段。", "reason": "r"},
        {"op": "rewrite", "anchor": "第一段。", "text": "x", "reason": "op 不认识"},
        {"op": "replace", "anchor": "正文里没有这句话", "text": "x", "reason": "锚点找不到"},
        {"op": "insert", "anchor": "第三段。", "text": "", "reason": "改完跟原文一样"},
    ])
    st = _st("第一段。\n\n第二段。\n\n第三段。")
    events = _drive(st)
    assert st.bag["revisions_proposed"] == 4
    assert st.bag["revisions_applied"] == 1
    assert st.bag["revisions_dropped"] == 3
    # 这三条确实是**静默**掉的：一个事件都没发。要是哪天给它们补了事件，
    # 这条断言会红——那时候该改的是这条断言，不是那两个数。
    assert _named(events, "dropped") == []


def test_超出额度的那几条不算进分母(monkeypatch, _no_db):
    """`max_revisions` 砍掉的那些**根本没被裁决过**。算进分母会把
    「守卫拦掉的比例」冲淡成「模型话多的比例」。"""
    _stub_llm(monkeypatch, [{"op": "replace", "anchor": "正文里没有这句话",
                             "text": "x", "reason": "锚点找不到"}] * 9)
    st = _st("第一段。\n\n第二段。", policy=None)
    _drive(st)
    from app.harness.middleware.revise import DEFAULT_MAX_REVISIONS
    assert st.bag["revisions_proposed"] == DEFAULT_MAX_REVISIONS
    assert st.bag["revisions_dropped"] == DEFAULT_MAX_REVISIONS


def test_这一轮没跑修订时两个数都清零(monkeypatch, _no_db):
    """第 1 轮不跑修订。留着上一轮的数会让 `harness_rounds` 里那一行
    记成「这一轮丢了三条」，而这一轮一条都没提过。"""
    st = _st("一段正文", round_=1)
    st.bag["revisions_proposed"], st.bag["revisions_dropped"] = 5, 3
    _drive(st)
    assert st.bag["revisions_proposed"] == 0 and st.bag["revisions_dropped"] == 0


def test_两个数真的被记进_harness_rounds():
    """**建了字段不等于用了字段。** bag 里有数、`record_harness_round` 收得下，
    中间那一段（`Ledger.after_judge`）漏掉的话，两列会永远是 0 而不报任何错。"""
    from pathlib import Path
    ledger = (Path(__file__).resolve().parent.parent / "app" / "harness"
              / "middleware" / "ledger.py").read_text(encoding="utf-8")
    assert 'revisions_proposed=int(st.bag.get("revisions_proposed") or 0)' in ledger
    assert 'revisions_dropped=int(st.bag.get("revisions_dropped") or 0)' in ledger
    store = (Path(__file__).resolve().parent.parent / "app" / "database"
             / "store.py").read_text(encoding="utf-8")
    assert '("harness_rounds", "revisions_proposed"' in store
    assert '("harness_rounds", "revisions_dropped"' in store
    assert "revisions_proposed,revisions_dropped" in store, "INSERT 的列名没跟上"
