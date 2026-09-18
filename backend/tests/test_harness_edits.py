"""批 23 / 计划 9.1：采集用户的编辑。

[MECH] §5：**整个回路没有 ground truth**。没有任何证据表明「五维全 2 分」
等于「用户愿意留下这篇笔记」，而 Goodhart 已经发生过一次（`best_of.py` 开头
记着第 3 轮为了讨好打分器加的那张单值柱状图）。唯一真实的信号是用户拿到
结果之后对它做了什么（[IND] §8⑥：PRELUDE / coactive learning）。

这个文件盯三件事：
* **采得对**：跑完开一行、用户改完关一行、数对得上；
* **不越界**：`rails_off=("save",)` 的跑一行都不许落（`note_revisions` 是
  `db_guard` 指纹盯着的两张表之一，批 14 / 批 16 出过两次事故）；
* **不调参**：这张表现在没有任何一处写回路。
"""

from __future__ import annotations

import asyncio
import dataclasses
import pathlib
import re

import pytest

from app.database import store
from app.harness import modes
from app.harness.middleware.edits import Edits
from app.harness.state import State
from app.harness.tools import ToolContext

USER = "u"


def _note(content: str = "开跑前就有的正文。") -> str:
    return store.create_note(USER, "标题", content)["id"]


def _st(note_id: str, *, content: str, base: str = "", rails_off=(), round_=2,
        stopped="complete", run_id="run-1"):
    mode = dataclasses.replace(modes.NOTE, rails_off=tuple(rails_off))
    st = State(mode=mode,
               ctx=ToolContext(user=USER, note_id=note_id, note_title="标题"))
    st.round, st.stopped, st.content = round_, stopped, content
    st.bag["run_id"] = run_id
    st.bag["content_at_start"] = base
    return st


def _run(st) -> None:
    asyncio.run(Edits().after_run(st))


# ------------------------------------------------------------ 采得对

def test_跑完落一版正文并开一行():
    nid = _note()
    store.update_note(USER, nid, "标题", "开跑前就有的正文。AI 写的那一段。",
                      source="harness")
    _run(_st(nid, content="开跑前就有的正文。AI 写的那一段。", base="开跑前就有的正文。"))

    revs = [r for r in store.list_revisions(USER, nid)
            if r["reason"] == store.REVISION_REASON_HARNESS]
    assert len(revs) == 1, "跑完那一版正文没落下来"
    rows = store.harness_edits(USER)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "open"
    assert row["run_id"] == "run-1"
    assert row["key"] == f"note:{nid}"
    assert row["revision_id"] == revs[0]["id"], "指针要指得到 AI 那一版"
    with store.connect() as c:
        rev_run = c.execute("SELECT run_id FROM note_revisions WHERE id=?",
                            (revs[0]["id"],)).fetchone()["run_id"]
    assert rev_run == "run-1", \
        "`note_revisions` 那一列就是为了『这一版是哪一次跑交的』才加的"
    assert row["base_chars"] == len("开跑前就有的正文。")
    assert row["ai_chars"] == len("开跑前就有的正文。AI 写的那一段。")


def test_用户改完保存就把那一行关掉并记下留了多少():
    nid = _note()
    ai = "开跑前就有的正文。AI 写的那一段，一共写了不少字。"
    store.update_note(USER, nid, "标题", ai, source="harness")
    _run(_st(nid, content=ai, base="开跑前就有的正文。"))

    mine = "开跑前就有的正文。AI 写的那一段。"      # 用户删掉了后半截
    store.update_note(USER, nid, "标题", mine)      # source 默认就是 user

    row = store.harness_edits(USER)[0]
    assert row["status"] == "edited"
    assert row["user_chars"] == len(mine)
    assert row["kept_chars"] == store.kept_chars(ai, mine)
    assert 0 < row["kept_chars"] < row["ai_chars"], "删了一截，留下的该比 AI 交的少"
    assert row["edited_at"]


def test_harness自己每轮落盘不算用户编辑():
    """**这条是这份信号成不成立的关键。** `middleware/save` 每轮都在写库，
    把它算成一次用户编辑，采到的就全是「用户一个字没改」。"""
    nid = _note()
    store.update_note(USER, nid, "标题", "第一轮。", source="harness")
    _run(_st(nid, content="第一轮。", base=""))
    store.update_note(USER, nid, "标题", "第一轮。第二轮。", source="harness")
    assert store.harness_edits(USER)[0]["status"] == "open"


def test_自动保存但一个字没改的那一下不算编辑():
    """编辑器每几秒存一次。正文跟 AI 那一版逐字相同时这一行要继续开着，
    否则采到的全是「刚跑完那一秒用户还没动」。"""
    nid = _note()
    ai = "AI 写的正文。"
    store.update_note(USER, nid, "标题", ai, source="harness")
    _run(_st(nid, content=ai, base=""))
    store.update_note(USER, nid, "别的标题", ai)       # 只改标题
    store.update_note(USER, nid, "别的标题", ai)       # 正文原样再存一次
    assert store.harness_edits(USER)[0]["status"] == "open"


def test_同一篇又跑一次旧行记superseded():
    """同一篇只留一行开着：两行同时开着的话，用户下一次保存会被两次跑同时
    认领，而其中至少一个是错的。"""
    nid = _note()
    store.update_note(USER, nid, "标题", "第一次跑。", source="harness")
    _run(_st(nid, content="第一次跑。", run_id="run-1"))
    store.update_note(USER, nid, "标题", "第二次跑。", source="harness")
    _run(_st(nid, content="第二次跑。", run_id="run-2"))

    rows = {r["run_id"]: r["status"] for r in store.harness_edits(USER)}
    assert rows == {"run-1": "superseded", "run-2": "open"}


def test_AI那一版被历史修剪掉之后这一行作废():
    """没有「AI 提出了什么」，剩下的数只是一次保存，不是一份编辑样本。"""
    nid = _note()
    store.update_note(USER, nid, "标题", "AI 写的。", source="harness")
    _run(_st(nid, content="AI 写的。"))
    rev_id = store.harness_edits(USER)[0]["revision_id"]
    with store.connect() as c:
        c.execute("DELETE FROM note_revisions WHERE id=?", (rev_id,))
        c.commit()
    store.update_note(USER, nid, "标题", "我改过了。")
    assert store.harness_edits(USER)[0]["status"] == "lost"


def test_恢复到旧版本也是一次编辑而恢复到AI那版不是():
    nid = _note("原来的正文，用户自己写的。")
    old = store.list_revisions(USER, nid)
    assert not old, "新建的笔记还没有历史版本"
    store.snapshot_note(USER, nid, "manual")
    old_rev = store.list_revisions(USER, nid)[0]["id"]

    ai = "原来的正文，用户自己写的。AI 接着写的一段。"
    store.update_note(USER, nid, "标题", ai, source="harness")
    _run(_st(nid, content=ai, base="原来的正文，用户自己写的。"))
    ai_rev = store.harness_edits(USER)[0]["revision_id"]

    store.restore_revision(USER, nid, ai_rev)
    assert store.harness_edits(USER)[0]["status"] == "open", \
        "恢复到 AI 那一版 = 接受，不是编辑"
    store.restore_revision(USER, nid, old_rev)
    row = store.harness_edits(USER)[0]
    assert row["status"] == "edited", "把 AI 写的整个扔掉，是最重的一种编辑"
    assert row["kept_chars"] < row["ai_chars"]


# ------------------------------------------------------------ 不越界

def test_rails_off挡住save时一行都不许落():
    """**这次跑不许碰这篇笔记**，历史也不行。跑批脚本一律用
    `rails_off=("save",)`，而 `note_revisions` 正是 `db_guard` 指纹盯着的
    两张表之一——往里写行会让每一批跑批的收尾核对当场变红。"""
    nid = _note()
    before = store.list_revisions(USER, nid)
    _run(_st(nid, content="跑批写出来的东西", rails_off=("save",)))
    assert store.list_revisions(USER, nid) == before
    assert store.harness_edits(USER) == []


@pytest.mark.parametrize("round_,stopped", [(0, "blocked"), (2, "awaiting_review")])
def test_不进历史的跑也不采(round_, stopped):
    """条件跟 `History` 是**同一个函数**（`records_this_run`）。各写一句 `if`
    就是 §21 那条「同一件事挡住一半等于没挡」。"""
    nid = _note()
    _run(_st(nid, content="写了点东西", round_=round_, stopped=stopped))
    assert store.harness_edits(USER) == []


def test_块模式不采():
    """六个 block 模式的 `st.content` 是**一个块**，不是这篇笔记——
    `hooks/block.commit` 是空的，笔记一个字都没被动过。在那儿开一行，
    `ai_chars` 数的是块、`revision_id` 指的是没被动过的整篇，
    **两边说的不是同一份东西**，而一份指错对象的 ground truth 比没有更糟。
    """
    nid = _note()
    st = _st(nid, content="模型生成的一个块")
    st.mode = dataclasses.replace(modes.BLOCK["prompt"], rails_off=())
    assert "save" not in [getattr(m, "name", "") for m in st.mode.extra_mw]
    _run(st)
    assert store.harness_edits(USER) == []
    assert store.list_revisions(USER, nid) == []


def test_没有run_id就不采():
    """指针没有对象。没挂 `Ledger` 的模式走的正是这条。"""
    nid = _note()
    _run(_st(nid, content="写了点东西", run_id=""))
    assert store.harness_edits(USER) == []


def test_删掉笔记时采集的样本一起走():
    nid = _note()
    store.update_note(USER, nid, "标题", "AI 写的。", source="harness")
    _run(_st(nid, content="AI 写的。"))
    assert store.harness_edits(USER)
    store.delete_note(USER, nid)
    assert store.harness_edits(USER) == []


# ------------------------------------------------------------ 数怎么算的

def test_留下多少字是逐字对齐算的():
    assert store.kept_chars("一样的正文", "一样的正文") == len("一样的正文")
    assert store.kept_chars("甲乙丙丁", "") == 0


def test_长中文正文改一个字不许算成没留下():
    """`difflib` 默认的 autojunk 把出现得太频繁的字符当噪声整个跳过，而中文
    正文里高频字满篇都是。实拍：680 字的正文改掉 1 个字，**开着 autojunk
    只认出 100 字「留下了」**（85% 的正文凭空消失），关掉之后是 595。
    """
    import difflib

    base = "这一节讲的是众筹的节奏和依赖关系。" * 40
    changed = base[:100] + "X" + base[101:]
    kept = store.kept_chars(base, changed)
    with_junk = sum(b.size for b in
                    difflib.SequenceMatcher(None, base, changed).get_matching_blocks())
    assert with_junk < len(base) * 0.2, "这条测试在查一个不存在的坑：autojunk 没有伤害"
    assert kept > len(base) * 0.85
    # `SequenceMatcher` 是贪心的，在这种高度重复的文本上给不出最优对齐
    # （595 而不是 679）。**这个数是下界**——写在这儿免得下一个人把它当
    # 精确的编辑距离用。
    assert kept <= len(base)


# ------------------------------------------------------------ 不调参

def test_采来的数据没有任何一处写回路():
    """**只采集，不调参**（计划 9.1 的边界）。样本不够时按它调参比不调更糟。

    判据盯的是「除了采集这一处和它的读取口，`app/` 里没有别人碰这张表」
    这个**性质**——哪天有人把它接进 prompt / policy / 打分，这条当场变红，
    那时该做的是先看样本量，不是把闸删掉。
    """
    app = pathlib.Path(__file__).resolve().parent.parent / "app"
    allowed = {"database/store.py", "harness/middleware/edits.py"}
    users = []
    for path in sorted(app.rglob("*.py")):
        rel = str(path.relative_to(app))
        if rel in allowed:
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"harness_edits|open_harness_edit", line) and not line.lstrip().startswith("#"):
                users.append(f"{rel}:{i}")
    assert not users, ("采来的编辑信号被这些地方读走了：" + "、".join(users)
                       + "\n计划 9.1 的边界是「只采集，不调参」")


def test_每一处写用户笔记的调用都登记过自己是谁():
    """`source` 默认是 `user`，代价是**新加一处机器写入而忘了声明，会被当成
    一次用户编辑**——而这份信号的全部价值就在于分得清人和机器。

    所以这里把 `app/` 下每一处 `store.update_note(` / `update_note(` 逐处
    写死。新增一处就得来这儿写一行，顺便回答「你是谁」。
    （同批 21 那条「载荷不是字典字面量的发射点逐处登记」。）
    """
    app = pathlib.Path(__file__).resolve().parent.parent / "app"
    found: dict[str, list[str]] = {}
    for path in sorted(app.rglob("*.py")):
        rel = str(path.relative_to(app))
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if not re.search(r"(?<![\w.])(store\.)?update_note\(", line):
                continue
            if line.lstrip().startswith("#") or "def update_note" in line:
                continue
            block = "\n".join(lines[i:i + 3])
            m = re.search(r"source=([\"\'])(\w+)\1", block)
            found.setdefault(rel, []).append(m.group(2) if m else "user(默认)")
    # **按文件登记，不按行号**：钉行号的话，上面加一行注释这条就红，而它
    # 什么都没查出来——「一个跟着被测代码一起动的断言，没有在断言任何东西」。
    assert found == {
        "database/store.py": ["harness"],        # upsert_child：程序反复重写同一篇
        "harness/middleware/save.py": ["harness"],   # 每轮落盘
        "routers/harness.py": ["user"],          # 处置完「不再往下写」，送回来的就是用户要的那版
        "routers/notes.py": ["user(默认)"],       # PUT /api/notes/{id}：编辑器保存
        "routers/writing_plan.py": ["harness"],  # 跟踪文档，程序重写
    }, f"写用户笔记的调用点变了，来这儿登记一下：{found}"
