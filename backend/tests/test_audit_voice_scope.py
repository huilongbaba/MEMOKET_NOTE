"""审计腔 / 机制泄漏这条判据的**量程**：只判这次跑写出来的字（批 21）。

## 为什么会有这个文件

批 20 量 magic tap 的时候顺手在 18 篇 `origin=user` 真实笔记上跑了一遍
`audit_voice_lines`：**开火 5 篇（27.8%）、9 句**。逐句读出来是两类——

  ① 用户自己写的业务对象：「该智能体还将整合全区**政务知识库**…」（两篇）；
  ② 上一次跑写进他笔记里的真缺陷：「尚不能证明 APP、硬件…已形成稳定闭环」（三篇）。

而这条判据挂在 `note` / `section` 上、**会短路打分并要求模型改写**；同一张
词表还挂在落盘那一路（`scrub_meta_sentences_v`），那一路是**直接删句子**
——实测同样 5 篇会被删掉那 9 句，其中就有用户写的「政务知识库」。

**词表改不动这件事**：把「知识库」摘掉，②那三篇当场全漏，而那正是这条判据
当初被写出来的原因。①②只能靠「这句话是谁写的」分开。所以改的是量程：
**开跑时正文里已经有的句子，这一轮不报、也不删**
（`loop.py` 存 `content_at_start` 那一行的注释早就把这条道理写清楚了）。

数字重跑：`scripts/audit_voice_misfire.py`。
"""

from __future__ import annotations

from pathlib import Path

from app.harness.checks.grounding import no_audit_voice
from app.harness.checks.grounding_rules import (audit_voice_lines,
                                                scrub_meta_sentences_v)
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Dimension, Mode

# 18 篇真实笔记里被误伤的那两句**原话**，一个字都没改。
# 拿真句子当钉子，是因为自己编的「像业务词的句子」证明不了误伤真的没了
# （批 20 ⑯ 的教训：编出来的那一对相似度根本没到门槛）。
USER_OWN = (
    "该智能体还将整合全区政务知识库，通过对摄像头的智能调度分析，"
    "自动完成各类事件的识别与分拨处理。"
)
USER_OWN_2 = (
    "知识库同时记录 EVT 为 4 月 10 号启动、4 月 16 号为大节点，"
    "10 台到货为 6 月 15 日，以 4 月 16 日作为对外对齐点。"
)

# 四句**真实的**缺陷原文。出处：①`dimension_sensitivity_bench.AUDIT_SENTENCE`
# （原样来自 `ecfac1f3c0aa` 那篇真产出）；②③`grounding_rules` 注释里记着的
# 文件夹级 bench 两次实拍；④同一段注释里的机制泄漏原话。
# **放宽量程必须先证明没把该抓的放掉**（[EVAL] §3④）。
TRUE_POSITIVES = (
    "现有材料不足以说明这一判断，仍需与对应的会议记录核对后再写入。",
    "即使面向发货的相关功能已经可用，也不能据此判断用户已经完成硬件交付。",
    "Lassie 的能力扩展仍缺少对应的版本与测试记录，因此不能据此断言它已经可用。",
    "目前 KB 中可核对的记录集中在四月那几周。",
)


def _mode(**kw) -> Mode:
    return Mode(key="note", label="单篇", skill_scope="writing",
                dims=(Dimension("style_fit", "..."),
                      Dimension("factual_grounding", "...")), **kw)


def _st(content: str, started_with: str) -> State:
    st = State(mode=_mode(), ctx=ToolContext(user="u", note_id="n"))
    st.content = content
    st.bag["content_at_start"] = started_with
    return st


# --------------------------------------------------------- 纯函数那一侧 ---

def test_开跑时就在正文里的句子_这一轮一句都不报():
    note = f"## 三季度的智能体规划\n\n{USER_OWN}\n\n{USER_OWN_2}\n"
    assert audit_voice_lines(note), "没给 before 时该照旧开火，否则这条测试在验空气"
    assert audit_voice_lines(note, before=note) == []


def test_这一轮写出来的四句真缺陷_一句都不许漏():
    head = "## 四月的交付节奏\n\n四月上旬定下对外对齐点，硬件那一批的到货排在六月。\n"
    for sentence in TRUE_POSITIVES:
        got = audit_voice_lines(head + "\n" + sentence, before=head)
        assert got, f"真阳性漏了：{sentence}"
        assert sentence[:12] in got[0]


def test_同样四句挪到开跑前就不报了():
    """真阳性和误伤的分界线**只有一条：这句话是不是这次跑写的**。

    同一句话换一个位置就换一个结论，这正是这一批想要的性质；
    如果哪天它两边都报，说明 `before` 那条线断了。
    """
    for sentence in TRUE_POSITIVES:
        note = "开头一句正常的话。\n" + sentence
        assert audit_voice_lines(note, before=note) == [], sentence


def test_句子外面的空行怎么动都不影响():
    """`tidy_blank_lines` / `join_round_text` 会动**句子之外**的空行和换行。
    切句本来就在 `\n` 上切、每句还 `.strip()` 过，所以原样比就够——
    这条钉的是「够」，不是某种归一化。

    （第一版这条测试写的是「重新排版也认得出」，而它排的版全在句子外面，
    **把归一化整个删掉它照样绿**——批 20 ⑯ 那个形状：用例没在验它声称的东西。
    量完之后归一化删了，测试改成钉它真的在钉的那条性质。）"""
    before = f"## 规划\n\n{USER_OWN}\n"
    after = f"## 规划\n{USER_OWN}\n\n\n这一轮新写的一段正常的话。\n"
    assert audit_voice_lines(after, before=before) == []


def test_句子被改过一个字就不再算_开跑时就有的():
    """原样比的另一半：**跟开跑时不一样 = 这次跑动过它**，该判。
    修订就地改写旧段落正是这条路（见下面那条 `st.fresh` 的反例）。"""
    before = "## 规划\n\n开跑时这里是一句正常的话。\n"
    after = before + "\n" + TRUE_POSITIVES[0]
    assert audit_voice_lines(after, before=before)


def test_没给_before_时行为一个字不变():
    """老调用点（bench / suite / 探针）不传这个参数，它们要的就是整篇口径。"""
    note = f"正常的一句话。{TRUE_POSITIVES[0]}"
    assert len(audit_voice_lines(note)) == 1
    assert len(audit_voice_lines(note, before="")) == 1


# ------------------------------------------------------- 落盘 scrub 那一侧 ---

def test_落盘时不许删用户开跑前写的句子():
    """这一路比判据更狠：它**直接删**，用户连事件都看不到自己少了一句。"""
    note = f"## 三季度的智能体规划\n\n{USER_OWN}\n"
    out, gone = scrub_meta_sentences_v(note, note)
    assert gone == []
    assert USER_OWN in out

    _out_old, gone_old = scrub_meta_sentences_v(note)
    assert gone_old, "不给 before 时该照旧删——否则这条测试在验空气"


def test_落盘时照样删这一轮写出来的元话语():
    before = "## 四月的交付节奏\n\n四月上旬定下对外对齐点。\n"
    note = before + "\n" + TRUE_POSITIVES[3] + "排期要往前倒推。"
    out, gone = scrub_meta_sentences_v(note, before)
    assert len(gone) == 1 and "KB" in gone[0]
    assert "KB" not in out and "排期要往前倒推。" in out


def test_一篇里同时有两种_只删这一轮那句():
    """误伤和真阳性挨在一起时才看得出量程是按句走的，不是按篇走的。"""
    before = f"## 规划\n\n{USER_OWN}\n"
    note = before + "\n" + TRUE_POSITIVES[1]
    out, gone = scrub_meta_sentences_v(note, before)
    assert len(gone) == 1 and "不能据此判断" in gone[0]
    assert USER_OWN in out


# ----------------------------------------------------------- 判据那一侧 ---

def test_no_audit_voice_读的是开跑时那份正文():
    note = f"## 三季度的智能体规划\n\n{USER_OWN}\n"
    assert no_audit_voice(_st(note, note)) is None
    # 开跑时那份为空（比如一篇空笔记从头写）→ 整篇都是这次跑写的，照旧开火
    assert no_audit_voice(_st(note, "")) is not None


def test_修订就地塞回来的审计腔_不在_st_fresh_里也要抓到():
    """**这条就是「为什么量程不是 `st.fresh`」的那份证据。**

    `revise.py` 的注释记着实拍：「a single replace can put audit voice straight
    back into the text -- measured on the folder path after the
    continuation-side scrub was already in place.」修订是**就地改写旧段落**，
    改出来的句子不进 `st.fresh`，却确实是这次跑写的。
    只看 `st.fresh` 的量程会把它整类放掉。
    """
    started = "## 四月的交付节奏\n\n四月上旬定下对外对齐点。\n"
    # 修订把开跑时那一段替换成了带审计腔的版本；这一轮的续写（st.fresh）另在别处
    st = _st(f"## 四月的交付节奏\n\n{TRUE_POSITIVES[0]}\n\n新写的一段。\n", started)
    st.fresh = "新写的一段。\n"
    verdict = no_audit_voice(st)
    assert verdict is not None, "修订塞回去的审计腔被放过了"
    assert "不足以说明" in verdict.message


# ----------------------------------------------------------- 接线形状 ---
#
# 批 20 ⑨ 的教训：**纯函数那一侧的用例看不见端点怎么调它**。把调用改成
# `check_tap(body.content + written)` 时函数行为一个字没变，全套照绿。
# 所以四个调用点的形状单独钉一次。

_HARNESS = Path(__file__).resolve().parent.parent / "app" / "harness"


def test_四个调用点都把开跑时那份正文传下去():
    checks = (_HARNESS / "checks" / "grounding.py").read_text(encoding="utf-8")
    assert 'audit_voice_lines(\n        st.content, before=str(st.bag.get("content_at_start")' in checks, \
        "no_audit_voice 又在判整篇了"

    revise = (_HARNESS / "middleware" / "revise.py").read_text(encoding="utf-8")
    assert 'st.bag.get("content_at_start")' in revise
    assert "audit_voice_lines(\n                              st.content, before=_started_with(st))" in revise, \
        "递给修订的审计腔又变回整篇了"
    assert "scrub_meta_sentences_v(\n            st.content, _started_with(st))" in revise, \
        "修订后的 scrub 又变回整篇了"

    mirror = (_HARNESS / "hooks" / "mirror.py").read_text(encoding="utf-8")
    assert 'scrub_meta_sentences_v(\n        content, str(st.bag.get("content_at_start")' in mirror, \
        "续写落盘的 scrub 又变回整篇了——这一路是直接删句子的"


def test_开跑时那份正文只有_loop_存一次():
    """`content_at_start` 是这条量程的唯一来源。它要是没人写，四个调用点
    会安静地退回整篇口径——**凡是只能靠自报来保证的性质，迟早会被报错一次**。
    """
    loop = (_HARNESS / "loop.py").read_text(encoding="utf-8")
    assert loop.count('st.bag["content_at_start"] = st.content') == 1
