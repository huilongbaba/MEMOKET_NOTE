"""跑批脚本碰真库的那两道闸（`scripts/db_guard.py`）。

被什么逼出来的：2026-09-17 批 13，实施 agent 报告「一篇笔记都没写」，
而实际上两篇 terrence 的真实笔记被改了——`e78306202d78` 从 1976 字掉到 650 字
（丢了 1326 字用户自己写的内容）。原文靠备份救回来了。

这是这个仓**第二次**踩同一个坑（第一次记在 `harness_quality_sample.py` 开头：
三篇真实笔记的原文永久丢失）。第一次之后写的是一段警告注释，第二次照样发生——
**所以这次写成能跑的闸。**
"""

from __future__ import annotations

import importlib.util
import re
import sqlite3
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location("db_guard", _SCRIPTS / "db_guard.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["db_guard"] = mod          # dataclass 解注解要从 sys.modules 取（批 5 记过）
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop("db_guard", None)
    return mod


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "notes.sqlite3"
    c = sqlite3.connect(p)
    c.executescript("""
        CREATE TABLE notes (id TEXT PRIMARY KEY, content TEXT, updated_at TEXT);
        CREATE TABLE note_revisions (id TEXT PRIMARY KEY, created_at TEXT);
        INSERT INTO notes VALUES ('a', '甲甲甲', '2026-09-01T00:00:00');
        INSERT INTO notes VALUES ('b', '乙乙',   '2026-09-02T00:00:00');
    """)
    c.commit(); c.close()
    return p


def test_只读连接写不了(db):
    """靠 `mode=ro` 而不是靠「记得别写 SQL」——**这次出事正是因为有人以为自己没写**。"""
    g = _load()
    conn = g.readonly(db)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("UPDATE notes SET content='改了' WHERE id='a'")


def test_要写就必须说理由(db):
    """必填参数会让「顺手写一下」变成「先想清楚」。"""
    g = _load()
    with pytest.raises(ValueError, match="为什么"):
        g.writable("", db=db)
    with pytest.raises(ValueError):
        g.writable("   ", db=db)
    conn = g.writable("单测：验证可写路径确实可写", db=db)
    conn.execute("UPDATE notes SET content='改了' WHERE id='a'")     # 不该抛


def test_跑批没动笔记就放行(db):
    g = _load()
    with g.Watch(db):
        pass                                    # 什么都没干


def test_改了内容就抓住_哪怕行数和时间戳都没变(db):
    """**三样一起看，因为任何一样单独都骗得过。**
    这一条专治「改内容不涨行、时间戳写回去」。"""
    g = _load()
    with pytest.raises(g.NotesTouched, match="总字数"):
        with g.Watch(db):
            c = sqlite3.connect(db)
            c.execute("UPDATE notes SET content='甲甲甲甲甲甲' WHERE id='a'")  # 时间戳不动
            c.commit(); c.close()


def test_加了一篇也抓住(db):
    g = _load()
    with pytest.raises(g.NotesTouched, match="行数"):
        with g.Watch(db):
            c = sqlite3.connect(db)
            c.execute("INSERT INTO notes VALUES ('c','丙','2026-09-03T00:00:00')")
            c.commit(); c.close()


def test_删一段加一段正好抵消也抓得住(db):
    """总字数不变，但 `updated_at` 变了——这就是第三个信号存在的理由。"""
    g = _load()
    with pytest.raises(g.NotesTouched, match="最后修改"):
        with g.Watch(db):
            c = sqlite3.connect(db)
            c.execute("UPDATE notes SET content='丙丙丙', updated_at='2026-09-09T00:00:00'"
                      " WHERE id='a'")
            c.commit(); c.close()


def test_真要写的跑批显式声明就放行(db):
    """压测那类确实要写笔记的跑批走这条，但**必须自己写出来**。"""
    g = _load()
    with g.Watch(db, allow=True):
        c = sqlite3.connect(db)
        c.execute("UPDATE notes SET content='压测写的' WHERE id='a'")
        c.commit(); c.close()


def test_跑批自己炸了不要被闸盖住(db):
    """本来就抛了异常时，闸不该把真异常换成自己的——那会让排查从
    「这里报错了」变成「笔记被动了」，指向完全错误的方向。"""
    g = _load()
    with pytest.raises(ZeroDivisionError):
        with g.Watch(db):
            sqlite3.connect(db).execute(
                "UPDATE notes SET content='顺手改了' WHERE id='a'")
            1 / 0


def test_只盯笔记和它的历史_不盯跑批本来就该写的表(db):
    """`harness_runs` / `llm_usage` 这些跑批本来就要写——算进指纹会让闸天天误报，
    而**一个天天误报的闸等于没有闸**。"""
    g = _load()
    assert set(g.WATCHED) == {"notes", "note_revisions"}


# ===================================================== 批 15：第四样 + 两条接线 ===


def test_一篇变短另一篇变长正好抵消也抓得住(db):
    """**第四样存在的全部理由。**

    前三样（行数 / max(updated_at) / 正文总字数）里只有总字数在看正文，
    而它是**总和**。批 14 那场事故正是一篇 1976→650、另一篇 2762→5279
    ——一短一长，只是没恰好抵消才被总字数抓到。这里把时间戳写回去、
    并让两篇的增减正好相等：前三样**一个都不响**。
    """
    g = _load()
    with pytest.raises(g.NotesTouched, match="正文变了"):
        with g.Watch(db):
            c = sqlite3.connect(db)
            # a: 3 字 → 2 字；b: 2 字 → 3 字。总字数 5 不变，时间戳原样写回。
            c.execute("UPDATE notes SET content='甲甲', updated_at='2026-09-01T00:00:00'"
                      " WHERE id='a'")
            c.execute("UPDATE notes SET content='乙乙乙', updated_at='2026-09-02T00:00:00'"
                      " WHERE id='b'")
            c.commit(); c.close()


def test_备份还原型跑批_正文原样还原就放行(db):
    """`harness_stress_test.py` 那一档：过程中真的写，出来时正文逐字还原。

    还原本身是一次写，所以 `updated_at` 必然前进——**卡它等于天天误报**，
    而一个天天误报的闸等于没有闸。
    """
    g = _load()
    with g.Watch(db, restores=True):
        c = sqlite3.connect(db)
        c.execute("UPDATE notes SET content='跑批写的', updated_at='2026-09-30T00:00:00'"
                  " WHERE id='a'")
        c.commit()
        c.execute("UPDATE notes SET content='甲甲甲', updated_at='2026-09-30T00:00:01'"
                  " WHERE id='a'")            # 还原：正文逐字放回，时间戳往前走
        c.commit(); c.close()


def test_备份还原型跑批_没还原干净就吵(db):
    """**这一档不能用 `allow=True`。** `allow=True` 等于「随便写，不核对」，
    而这个脚本历史上翻车的形状恰恰是「以为还原了，其实没有」——进程被外层
    超时杀掉、finally 没跑，一篇真实笔记的原文永久丢失。"""
    g = _load()
    with pytest.raises(g.NotesTouched, match="还原没把正文放回原样"):
        with g.Watch(db, restores=True):
            c = sqlite3.connect(db)
            c.execute("UPDATE notes SET content='跑批写的没还原' WHERE id='a'")
            c.commit(); c.close()


def _script_texts() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(_SCRIPTS.glob("*.py"))}


# 「会跑 harness」的确定性判据：要么打了那两个跑批路由，要么直接 import 生产的
# harness 包。**不是一份名单**——名单会腐烂，而新加的脚本必须自动落进网里。
_RUNS_HARNESS = re.compile(r"note-harness/run|writing-plan/run|app\.harness")
# 唯一豁免：`dump_prompts.py` import 了 `app.harness`，但它只把提示词渲染出来
# 打印，**一次模型调用都不发、一行都不写**。下面那条断言钉着这个理由，
# 它哪天开始发调用了，豁免当场失效。
_PROMPT_DUMP_ONLY = "dump_prompts.py"
# 真正的接线长这样：一行 `with db_guard.Watch(...)`（行首只能有空白）。
_WIRED = re.compile(r"^\s*with db_guard\.Watch\(", re.M)


def test_会跑harness的脚本必须夹在Watch里():
    """**建了闸不等于用了闸。**

    批 14 的整改是写出 `Watch`，批 15 才是把它接上。没有这条断言的话，
    下一个新脚本照样会在没有任何核对的情况下跑，而事故形状一模一样：
    报告说「一篇笔记都没写」，没有任何东西在核对这句话。
    """
    missing = []
    for name, text in _script_texts().items():
        if name in ("db_guard.py", _PROMPT_DUMP_ONLY):
            continue
        # **必须匹配真正的那一行 `with db_guard.Watch(...)`，不能拿子串
        # `"db_guard.Watch(" in text` 了事。** 突变验当场打脸：把 `soak.py` 的
        # `with db_guard.Watch(): main()` 撤成裸 `main()`，这条闸**照样是绿的**
        # ——因为上面那段接线注释里写着「跑批一律夹在 `db_guard.Watch()` 里」，
        # 子串还在。**闸被自己的注释骗过去了。**
        if _RUNS_HARNESS.search(text) and not _WIRED.search(text):
            missing.append(name)
    assert not missing, (
        f"这些脚本会跑 harness 却没接指纹闸：{missing}。"
        "在 `if __name__ == \"__main__\":` 里用 `with db_guard.Watch():` 包住 main()")


def test_豁免的那个脚本确实一次调用都不发():
    """防豁免腐烂：`dump_prompts.py` 只渲染提示词。它哪天开始发模型调用 /
    起 HTTP，这条就红，豁免必须重新论证。"""
    text = _script_texts()[_PROMPT_DUMP_ONLY]
    for banned in ("llm.", "httpx", "asyncio"):
        assert banned not in text, (
            f"{_PROMPT_DUMP_ONLY} 里出现了 {banned}——它不再是「只渲染提示词」，"
            "要么接上 db_guard.Watch()，要么把豁免理由重写")


def test_跑批脚本不许自己拼只读连接():
    """只读连接只有一处实现（`db_guard.readonly`）。

    拼一次 `mode=ro` 就多一个地方可能漏掉它，而批 14 的根因正是
    「以为自己没写」。**`db_guard.py` 自己是那一处实现，不在此列。**
    """
    offenders = [name for name, text in _script_texts().items()
                 if name != "db_guard.py" and "sqlite3.connect(" in text]
    assert not offenders, (
        f"这些脚本自己拼了 sqlite3 连接：{offenders}。只读走 db_guard.readonly()，"
        "真要写走 db_guard.writable(why=...)")


# ---------------------------------------------------- 批 16：写库只有一个出口

def test_harness里只有一处在写用户的笔记():
    """**这条是拿两篇真实笔记换来的**（2026-09-18，批 16，第三次写坏真库）。

    跑批脚本一直靠 `rails_off=("save",)` 保证「这次跑不碰用户的笔记」，
    而 `loop.run` 只是按 `name` 把 middleware 过滤掉——**`middleware/revise.py`
    自己也在调 `store.update_note`**，那条根本没被摘掉。批 14 的复盘写着
    「`rails_off=("save",)` 本身是好的」，然后去猜是不是有人直接打了 HTTP
    路由；**不是，答案一直在第二个 middleware 里**。

    所以判据盯的是「出口只有一个」这个**性质**，不是「revise 里有没有那一行」
    这个写法：再加一个会写库的 middleware，这条当场变红。
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "app" / "harness"
    writers = []
    for path in sorted(root.rglob("*.py")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "store.update_note(" in line and not line.lstrip().startswith("#"):
                writers.append(f"{path.relative_to(root)}:{i}")
    assert writers == ["middleware/save.py:64"] or len(writers) == 1, (
        "harness 里写用户笔记的地方不止一处了：" + "、".join(writers)
        + "\n写库只许走 middleware/save.persist——理由见它的 docstring")


def test_rails_off挡住save时一个字都不许落库():
    """**词法闸挡不住这一条**：出口收成一个函数之后，只要 `persist` 自己不认
    `rails_off`，调用方照样会把用户的笔记写坏（批 16 就是这么发生的）。
    所以这里直接跑一遍：`rails_off=("save",)` 的 Mode，`persist` 必须不写。
    """
    import dataclasses

    from app.harness.middleware import save as save_mod
    from app.harness.state import State
    from app.harness.tools import ToolContext
    from app.harness.types import Dimension, Mode

    wrote: list[str] = []
    real = save_mod.store.update_note
    save_mod.store.update_note = lambda u, n, t, c: wrote.append(c)
    try:
        base = Mode(key="t", label="t", skill_scope="s", task="做点什么",
                    dims=(Dimension("d0", "..."),))
        st = State(mode=dataclasses.replace(base, rails_off=("save",)),
                   ctx=ToolContext(user="u", note_id="真实笔记"))
        st.content = "这一轮写出来的正文"
        assert save_mod.persist(st) is False
        assert wrote == [], "rails_off 挡住了 save，却还是写了库"

        st.mode = base                       # 没挡的时候必须照写
        assert save_mod.persist(st) is True
        assert wrote == ["这一轮写出来的正文"]
    finally:
        save_mod.store.update_note = real
