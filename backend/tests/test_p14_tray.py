"""P14：材料托盘（产品就绪计划 §2 C2，`docs/agent-native-editor.md` §3.4，`docs/TRACELOG-product.md` P14 节）。

  1. 表 `note_tray`：四种 kind（note / fact / import / selection）各一条**真写真读**（框架 §21「每个取值都写得进去吗」）；
     不合法的丢、同一条不重复、顺序 = 数组顺序、封顶；`GET / PUT / DELETE /api/notes/{id}/tray`；删笔记连托盘一起收。
  2. `harness/tray.lines_of`：四种 kind 各变成什么样的一行（fact 跟 `retrieval.format_fact` 同形，引用规则才对它成立）。
  3. harness 侧只有三条：**优先**（`hooks/note.prepare` / `hooks/block.prepare` 回的列表托盘在最前，prompt 里单独一块摆在检索材料前）、
     **不筛**（拼在 `relevance.gate` 之后：gate 把别的全剔了托盘还在、也不进 `facts_irrelevant`）、
     **不滚出窗口**（`middleware/facts.py`：`fact_budget=2` 连跑三轮托盘还钉在 `st.facts` 头上、不进一行索引、不算 fresh）。
  4. `ToolContext.tray` 跟 intent 同一条路：`/api/note-harness/run` 从库里装、`/api/compose/block` 从库里装 + `from_tray` 托盘空着 400、
     `/api/magic-tap` 带 note_id 时 meta.sources 托盘在前、快照带着走。

每条断言的量程写在 docstring 里（撤掉哪一行它红）。
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.database import store                                          # noqa: E402
from app.harness import prompts, snapshot, tray                         # noqa: E402
from app.harness import skills as skills_store                          # noqa: E402
from app.harness.agent_loop import ToolTrace                            # noqa: E402
from app.harness.checks import relevance                                # noqa: E402
from app.harness.hooks import note as note_hooks_mod                    # noqa: E402
from app.harness.hooks.block import BlockHooks                          # noqa: E402
from app.harness.hooks.note import NoteHooks                            # noqa: E402
from app.harness.middleware.facts import Facts                          # noqa: E402
from app.harness.state import State                                     # noqa: E402
from app.harness.tools import ToolContext                               # noqa: E402
from app.harness.types import Dimension, Mode                           # noqa: E402
from app.routers import compose, compose_block, note_harness            # noqa: E402

H = {"X-User-Id": "p14"}

FOUR = [
    {"kind": "note", "ref_id": "0eecee3d7b94", "title": "创业反思", "excerpt": "我写这篇反思不是为了复盘流水账"},
    {"kind": "fact", "ref_id": "terrence-2046-12F1", "title": "2026-04-16", "excerpt": "EVT 的大节点是 4 月 16 号"},
    {"kind": "import", "ref_id": "", "title": "周会.md", "excerpt": "硬件 4 月 10 号出来"},
    {"kind": "selection", "ref_id": "", "title": "", "excerpt": "从飞书文档里摘的一段"},
]
TRAY_LINES = tray.lines_of(FOUR)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app
    return TestClient(app)


@pytest.fixture
def no_skills(monkeypatch):
    monkeypatch.setattr(skills_store, "for_scope", lambda user, scope: ([], []))


def _mode(fact_budget: int = 40) -> Mode:
    return Mode(key="t", label="t", skill_scope="test_scope", dims=(Dimension("coherence", "..."),),
                groups=("memory",), fact_budget=fact_budget)


def _st(items=FOUR, **bag) -> State:
    st = State(mode=_mode(), ctx=ToolContext(user="p14", note_id="n", note_title="创业一年的回顾", tray=list(items)))
    st.content = "创业一年的回顾\n\n## 历程\n\n"
    st.bag.update(bag)
    return st


# ============================================================ 1. 表：四种 kind 真写真读 ===

def test_1_四种_kind_各一条_真写真读_顺序是数组顺序(client):
    """量程：`store.replace_tray` 的 INSERT + `list_tray` 的 ORDER BY position。任一 kind 写不进去这条红。"""
    n = client.post("/api/notes", headers=H, json={"title": "创业一年的回顾", "content": "## 历程\n"}).json()
    r = client.get(f"/api/notes/{n['id']}/tray", headers=H)
    assert r.status_code == 200 and r.json()["items"] == []            # 空托盘是空数组，不是 404
    r = client.put(f"/api/notes/{n['id']}/tray", headers=H, json={"items": FOUR})
    assert r.status_code == 200, r.text
    got = r.json()["items"]
    assert [g["kind"] for g in got] == ["note", "fact", "import", "selection"]
    assert [g["position"] for g in got] == [0, 1, 2, 3]
    for want, g in zip(FOUR, got):
        assert (g["ref_id"], g["title"], g["excerpt"]) == (want["ref_id"], want["title"], want["excerpt"])
        assert g["id"] and g["added_at"]
    # 库里真有四行（不是响应模型编的）
    with store.connect() as c:
        rows = c.execute("SELECT kind FROM note_tray WHERE note_id=? ORDER BY position", (n["id"],)).fetchall()
    assert [r[0] for r in rows] == ["note", "fact", "import", "selection"]
    # GET 回的跟 PUT 回的一样
    assert client.get(f"/api/notes/{n['id']}/tray", headers=H).json()["items"] == got


def test_1_拖序_删一条_不合法的丢_同一条不重复_封顶(client):
    """量程：`replace_tray` 的去重 key / `TRAY_MAX_ITEMS` / `normalize_tray_item` 的四条判法；`DELETE` 路由。"""
    n = client.post("/api/notes", headers=H, json={"title": "t", "content": "x"}).json()
    first = client.put(f"/api/notes/{n['id']}/tray", headers=H, json={"items": FOUR}).json()["items"]
    # 拖序：倒过来 PUT，position 跟着数组走，id / added_at 保留
    rev = list(reversed(first))
    got = client.put(f"/api/notes/{n['id']}/tray", headers=H, json={"items": rev}).json()["items"]
    assert [g["kind"] for g in got] == ["selection", "import", "fact", "note"]
    assert [g["id"] for g in got] == [g["id"] for g in rev]
    assert [g["added_at"] for g in got] == [g["added_at"] for g in rev]
    # 删一条
    r = client.delete(f"/api/notes/{n['id']}/tray/{got[0]['id']}", headers=H)
    assert r.status_code == 200 and [g["kind"] for g in r.json()["items"]] == ["import", "fact", "note"]
    assert client.delete(f"/api/notes/{n['id']}/tray/nope", headers=H).status_code == 404
    # 不合法的丢：note 没 ref_id、selection 没 excerpt、kind 不认识（pydantic 直接 422）
    bad = [{"kind": "note", "ref_id": "", "excerpt": "x"}, {"kind": "selection", "excerpt": "  "},
           {"kind": "fact", "ref_id": "terrence-1-1F1", "excerpt": "ok"}]
    got = client.put(f"/api/notes/{n['id']}/tray", headers=H, json={"items": bad}).json()["items"]
    assert [g["kind"] for g in got] == ["fact"]
    assert client.put(f"/api/notes/{n['id']}/tray", headers=H, json={"items": [{"kind": "url", "ref_id": "x"}]}).status_code == 422
    # 同一篇放两次只留一次；封顶 TRAY_MAX_ITEMS
    twice = [FOUR[0], dict(FOUR[0], excerpt="另一段摘要")] + [
        {"kind": "fact", "ref_id": f"terrence-{i}-1F1", "excerpt": f"f{i}"} for i in range(store.TRAY_MAX_ITEMS + 5)]
    got = client.put(f"/api/notes/{n['id']}/tray", headers=H, json={"items": twice}).json()["items"]
    assert sum(1 for g in got if g["kind"] == "note") == 1
    assert len(got) == store.TRAY_MAX_ITEMS
    # 笔记不存在：三条路由都 404
    assert client.get("/api/notes/nope/tray", headers=H).status_code == 404
    assert client.put("/api/notes/nope/tray", headers=H, json={"items": []}).status_code == 404
    # 别人的笔记看不到
    assert client.get(f"/api/notes/{n['id']}/tray", headers={"X-User-Id": "other"}).status_code == 404


def test_1_删笔记_托盘一起收(client):
    """量程：`store.delete_note` 里那句 `DELETE FROM note_tray`。"""
    n = client.post("/api/notes", headers=H, json={"title": "t", "content": "x"}).json()
    client.put(f"/api/notes/{n['id']}/tray", headers=H, json={"items": FOUR})
    assert client.delete(f"/api/notes/{n['id']}", headers=H).status_code == 200
    with store.connect() as c:
        assert c.execute("SELECT count(*) FROM note_tray WHERE note_id=?", (n["id"],)).fetchone()[0] == 0


def test_1_excerpt_和_title_封顶(client):
    n = client.post("/api/notes", headers=H, json={"title": "t", "content": "x"}).json()
    long = [{"kind": "selection", "title": "t" * 500, "excerpt": "长" * 2000}]
    g = client.put(f"/api/notes/{n['id']}/tray", headers=H, json={"items": long}).json()["items"][0]
    assert len(g["excerpt"]) == store.TRAY_EXCERPT_MAX and len(g["title"]) == store.TRAY_TITLE_MAX


# ============================================================ 2. 一条托盘项长成什么样 ===

def test_2_lines_of_四种形状():
    """量程：`tray.lines_of` 的四个分支。fact 那一行必须跟 `retrieval.format_fact` 同形（`[id] [日期] 正文`）——
    引用规则「句末照抄 [编号]」和 `check_citations` 认的就是这个形状。"""
    from app.database.retrieval import format_fact
    assert TRAY_LINES[0] == "[笔记「创业反思」](note://0eecee3d7b94) 我写这篇反思不是为了复盘流水账"
    assert TRAY_LINES[1] == format_fact({"id": "terrence-2046-12F1", "date": "2026-04-16", "text": "EVT 的大节点是 4 月 16 号"})
    assert TRAY_LINES[2] == "[导入「周会.md」] 硬件 4 月 10 号出来"
    assert TRAY_LINES[3] == "[摘录] 从飞书文档里摘的一段"
    assert prompts.fragments._FACT_ID.match(TRAY_LINES[1])                # 事实那一行触发引用规则
    assert not prompts.fragments._FACT_ID.match(TRAY_LINES[0])            # 笔记那一行不冒充事实 id
    # 形状不对的跳过；重复的只留一条；空托盘一行都没有
    assert tray.lines_of([{"kind": "note", "ref_id": ""}, {"kind": "x", "excerpt": "y"}, FOUR[3], FOUR[3]]) == [TRAY_LINES[3]]
    assert tray.lines_of(None) == [] and tray.lines_of([]) == []


# ============================================================ 3. harness 三条：优先 / 不筛 / 不滚出窗口 ===

def _fake_gather(calls):
    async def gather(msgs, ctx, **kw):
        tr = ToolTrace()
        tr.calls.extend(calls)
        return [], tr
    return gather


SEARCH = ("[terrence-9-1F1] 公司计算产业的芯片包括鲲鹏 CPU\n    （2026-09-07 · 公司 · identity）\n"
          "[terrence-9-1F2] 昇腾 NPU 面向 AI 计算\n    （2026-09-07 · 公司 · identity）\n")


def test_3_prepare_托盘排最前_且不过相关性筛(monkeypatch, no_skills):
    """量程：`hooks/note.prepare` 末尾 `return tray + [...]` 那一行——拼在 `relevance.gate` **之后**。
    突变 A：把托盘并进 facts 再过 gate（或不拼）→ 这里的 gate 把一切都剔掉，托盘也没了 → 红。
    突变 B：把托盘拼在最后 → `facts[:4]` 不是托盘 → 红。"""
    monkeypatch.setattr(note_hooks_mod, "AGENT_TOOLS", True)
    monkeypatch.setattr(note_hooks_mod.query_cache, "dispatch", lambda name, args, ctx: "")
    monkeypatch.setattr(note_hooks_mod.agent_loop, "gather_context",
                        _fake_gather([("search_memory", {"query": "芯片"}, SEARCH)]))
    # 一个把**所有**材料都剔掉的 gate（比真 gate 严得多）：托盘不经它，别的一条不剩
    monkeypatch.setattr(note_hooks_mod.relevance, "gate",
                        lambda facts, calls, context, apply=True, **kw: ([], [(f, 0) for f in facts]))
    st = _st(spine="s", beats=["b"])
    facts, trace = asyncio.run(NoteHooks().prepare(st))
    assert facts[:4] == TRAY_LINES and len(facts) == 4
    assert st.bag["tray_lines"] == TRAY_LINES
    # 不算「无关」：facts_irrelevant 里只有检索回来的那两条 + 元信息行
    assert all(not tray.is_tray_line(f, TRAY_LINES) for f, _n in st.bag["facts_irrelevant"])
    assert len(st.bag["facts_irrelevant"]) == 4


def test_3_prepare_真_gate_开着也不剔托盘_检索材料排在后面(monkeypatch, no_skills):
    """跟上一条互补：用**真** gate（`RELEVANCE_FILTER` 开、`min_kept=0` 等价的严格档），托盘四行跟正文零重合照样在最前。"""
    monkeypatch.setattr(note_hooks_mod, "AGENT_TOOLS", True)
    monkeypatch.setattr(note_hooks_mod.params, "RELEVANCE_FILTER", True)
    monkeypatch.setattr(note_hooks_mod.query_cache, "dispatch", lambda name, args, ctx: "")
    monkeypatch.setattr(note_hooks_mod.agent_loop, "gather_context",
                        _fake_gather([("search_memory", {"query": "回顾 历程"}, "[terrence-3-1F1] 4 月 16 号 EVT 的历程回顾\n")]))
    st = _st(spine="s", beats=["b"])
    facts, _ = asyncio.run(NoteHooks().prepare(st))
    assert facts[:4] == TRAY_LINES
    assert any("terrence-3-1F1" in f for f in facts[4:])


def test_3_零工具那条路_托盘也在最前(monkeypatch):
    """量程：`prepare` 里 `if not AGENT_TOOLS:` 那个 return。"""
    monkeypatch.setattr(note_hooks_mod, "AGENT_TOOLS", False)
    monkeypatch.setattr(note_hooks_mod, "_retrieve", lambda *a, **k: (["[terrence-1-1F1] 检索来的"], ["terrence-1-1F1"], 1.0))
    st = _st()
    facts, _ = asyncio.run(NoteHooks().prepare(st))
    assert facts == TRAY_LINES + ["[terrence-1-1F1] 检索来的"]


def test_3_facts_中间件_托盘钉在头上_不滚出窗口_不进索引_不算fresh():
    """量程：`middleware/facts.py` 的 `pinned` 三行。突变：`st.facts = all_facts[-budget:]`（不加 pinned）→ 第 1 轮就红；
    `fresh` 不排除 pinned → dry_rounds 那条红；索引把 pinned 也压进去 → 最后一条红。"""
    st = State(mode=_mode(fact_budget=2), ctx=ToolContext(user="u", note_id="n", tray=FOUR))
    st.trace = ToolTrace()
    st.bag["tray_lines"] = TRAY_LINES
    for k, batch in enumerate((["[terrence-1-1F1] 一", "[terrence-1-1F2] 二"], ["[terrence-1-1F3] 三"],
                               ["[terrence-1-1F4] 四", "[terrence-1-1F5] 五"])):
        st.facts_new = TRAY_LINES + batch                    # prepare 回的就是「托盘 + 检索」
        asyncio.run(Facts().after_prepare(st))
        assert st.facts[:4] == TRAY_LINES, f"第 {k + 1} 轮托盘滚出窗口了：{st.facts}"
        assert len(st.facts) == 4 + min(2, 2 * (k + 1) - k)  # 窗口只对检索材料算：2 条
        assert st.bag["dry_rounds"] == 0
    assert st.facts == TRAY_LINES + ["[terrence-1-1F4] 四", "[terrence-1-1F5] 五"]
    assert st.bag["facts_index"] and all(not tray.is_tray_line(l, TRAY_LINES) for l in st.bag["facts_index"])
    assert all(not tray.is_tray_line(l, TRAY_LINES) for l in st.bag["facts_all"])
    # 一轮只带托盘、没有新检索 = 干轮（托盘不算 fresh）
    st.facts_new = list(TRAY_LINES)
    asyncio.run(Facts().after_prepare(st))
    assert st.bag["dry_rounds"] == 1 and st.facts[:4] == TRAY_LINES


def test_3_写正文那一发_托盘单独一块_摆在检索材料前(monkeypatch, no_skills):
    """量程：`prompts/note.note_harness_continue_user(tray=)` 的 `tray_block` + 去重；`hooks/note.produce` 传 `tray=`。"""
    seen: list[str] = []

    async def fake_stream(messages, **kw):
        seen.append(messages[-1]["content"])
        yield "写的一句。"
    monkeypatch.setattr("app.harness.hooks.note.llm.stream", fake_stream)
    st = _st(spine="s", beats=["b"], tray_lines=TRAY_LINES)
    st.facts = TRAY_LINES + ["[terrence-1-1F1] [2026-04-16] 检索来的一条"]

    async def _p():
        return [p async for p in NoteHooks().produce(st)]
    asyncio.run(_p())
    user = seen[0]
    i_tray, i_facts = user.find("【用户摊在桌上的材料（托盘）"), user.find("【知识库中的相关事实】")
    assert 0 <= i_tray < i_facts, user[:400]
    assert user.count(TRAY_LINES[1]) == 1                    # 托盘行不在事实块里再出现一遍
    assert "note://0eecee3d7b94" in user and "[导入「周会.md」]" in user and "[摘录]" in user
    # 托盘空着：一个字不加
    assert "托盘" not in prompts.note_harness_continue_user("s", ["b"], "正文", ["[terrence-1-1F1] x"], [], tray=[])


def test_3_块_harness_托盘在取材和写块两发都在_从托盘写多一句范围(monkeypatch, no_skills):
    """量程：`hooks/block.prepare` 的 `st.bag["tray_lines"]` + `return tray + …`；`_user` 里的 `tray_block` / 【范围】。"""
    captured: list[list[dict]] = []

    async def gather(msgs, ctx, **kw):
        captured.append(msgs)
        tr = ToolTrace()
        tr.calls.append(("search_memory", {"query": "q"}, "[terrence-1-1F1] 查到的\n"))
        return [], tr
    monkeypatch.setattr("app.harness.hooks.block.agent_loop.gather_context", gather)
    mode = Mode(key="prompt", label="p", task="写一段", skill_scope="test_scope",
                dims=(Dimension("coherence", "..."),), groups=("memory",))
    st = State(mode=mode, ctx=ToolContext(user="p14", note_id="n", note_title="t", content="前文", cursor=2, tray=FOUR),
               before="前文", after="")
    facts, _ = asyncio.run(BlockHooks(prompt="写一段", title="t", from_tray=True).prepare(st))
    assert facts[:4] == TRAY_LINES and any("terrence-1-1F1" in f for f in facts[4:])
    plan_user = captured[0][-1]["content"]
    assert "【用户摊在桌上的材料（托盘）" in plan_user and "【范围】这一块**只用上面托盘里的材料**" in plan_user
    # 不是「从托盘写」：托盘块在、范围那句不在
    st2 = State(mode=mode, ctx=ToolContext(user="p14", note_id="n", note_title="t", tray=FOUR), before="前文")
    st2.bag["tray_lines"] = TRAY_LINES
    u2 = BlockHooks(prompt="写一段", title="t")._user(st2, facts="[terrence-1-1F1] 查到的")
    assert "【用户摊在桌上的材料（托盘）" in u2 and "【范围】" not in u2
    assert u2.find("托盘）") < u2.find("【工具查到的东西】")


def test_3_续写_magic_tap_user_托盘块在前():
    u = prompts.magic_tap_user("s", ["b"], "正文", TRAY_LINES + ["[terrence-1-1F1] 检索"], [], title="t", tray=TRAY_LINES)
    assert u.find("【用户摊在桌上的材料（托盘）") < u.find("【知识库中的相关事实】")
    assert u.count(TRAY_LINES[1]) == 1


# ============================================================ 4. 跟 intent 同一条路进 ctx ===

def _capture_ctx(monkeypatch, module):
    got: dict = {}

    async def fake_run(st, hooks):
        got["tray"] = st.ctx.tray
        got["hooks"] = hooks
        if False:
            yield None
    monkeypatch.setattr(module.loop, "run", fake_run)
    return got


def test_4_note_harness_从库里装托盘(client, monkeypatch, no_skills):
    """量程：`routers/note_harness.py` 装 `ToolContext(tray=store.list_tray(...))` 那一行。"""
    n = client.post("/api/notes", headers=H, json={"title": "创业一年的回顾", "content": "正文" * 30}).json()
    client.put(f"/api/notes/{n['id']}/tray", headers=H, json={"items": FOUR})
    got = _capture_ctx(monkeypatch, note_harness)

    async def fake_skel(self, st):
        if False:
            yield None
    monkeypatch.setattr(NoteHooks, "skeleton", fake_skel)
    r = client.post("/api/note-harness/run", headers=H, json={"note_id": n["id"], "content": n["content"]})
    assert r.status_code == 200, r.text
    assert [t["kind"] for t in got["tray"]] == ["note", "fact", "import", "selection"]
    assert tray.lines_of(got["tray"]) == TRAY_LINES


def test_4_compose_block_从库里装托盘_从托盘写空托盘400(client, monkeypatch, no_skills):
    """量程：`routers/compose_block.py` 的 `tray = store.list_tray(...)` / `if body.from_tray and not tray: 400` / `BlockHooks(from_tray=)`。"""
    n = client.post("/api/notes", headers=H, json={"title": "t", "content": "正文"}).json()
    got = _capture_ctx(monkeypatch, compose_block)
    body = {"note_id": n["id"], "title": "t", "content": "正文", "cursor": 2, "mode": "prompt", "prompt": "写一段"}
    r = client.post("/api/compose/block", headers=H, json=dict(body, from_tray=True))
    assert r.status_code == 400 and "托盘是空的" in r.text            # 一次模型调用不花
    client.put(f"/api/notes/{n['id']}/tray", headers=H, json={"items": FOUR})
    r = client.post("/api/compose/block", headers=H, json=dict(body, from_tray=True))
    assert r.status_code == 200, r.text
    assert tray.lines_of(got["tray"]) == TRAY_LINES and got["hooks"].from_tray is True
    r = client.post("/api/compose/block", headers=H, json=body)
    assert r.status_code == 200 and got["hooks"].from_tray is False and tray.lines_of(got["tray"]) == TRAY_LINES


def test_4_magic_tap_带note_id时_托盘在材料最前_meta也报(client, monkeypatch):
    """量程：`routers/compose.magic_tap` 里 `facts = tray + …` / `ids = tray_ids + …` 两行。"""
    n = client.post("/api/notes", headers=H, json={"title": "t", "content": "正文" * 20}).json()
    client.put(f"/api/notes/{n['id']}/tray", headers=H, json={"items": FOUR})
    monkeypatch.setattr(compose, "_retrieve", lambda *a, **k: (["[terrence-1-1F1] 检索来的"], ["terrence-1-1F1"], 1.0))
    seen: list[str] = []

    async def fake_stream(messages, **kw):
        seen.append(messages[-1]["content"])
        yield "续写的一句。"
    monkeypatch.setattr(compose.llm, "stream", fake_stream)
    r = client.post("/api/magic-tap", headers=H, json={"content": "正文" * 20, "title": "t", "note_id": n["id"]})
    assert r.status_code == 200, r.text
    meta = next(ln for ln in r.text.splitlines() if ln.startswith("data:") and '"sources"' in ln)
    assert meta.index(TRAY_LINES[0][:20]) < meta.index("检索来的")
    assert '"fact_ids": ["terrence-2046-12F1", "terrence-1-1F1"]' in meta
    assert seen and seen[0].find("【用户摊在桌上的材料（托盘）") < seen[0].find("【知识库中的相关事实】")
    # 不带 note_id：一个字不加（老调用方照旧）
    r = client.post("/api/magic-tap", headers=H, json={"content": "正文" * 20, "title": "t"})
    assert r.status_code == 200 and "托盘" not in seen[-1]


def test_4_快照带着托盘走(no_skills):
    st = _st()
    st2 = snapshot.loads(snapshot.dumps(st), st.mode)
    assert st2.ctx.tray == FOUR and tray.lines_of(st2.ctx.tray) == TRAY_LINES


def test_4_expand_verify_带note_id时_托盘先摆(client, monkeypatch):
    """量程：`routers/compose.expand` / `verify` 各自那两行 `facts = tray + …`。"""
    n = client.post("/api/notes", headers=H, json={"title": "t", "content": "前文 选中的一段 后文"}).json()
    client.put(f"/api/notes/{n['id']}/tray", headers=H, json={"items": FOUR})
    monkeypatch.setattr(compose, "_retrieve", lambda *a, **k: (["[terrence-1-1F1] 检索来的"], ["terrence-1-1F1"], 1.0))
    seen: list[str] = []

    async def fake_complete(messages, **kw):
        seen.append(messages[-1]["content"])
        return "{}"
    monkeypatch.setattr(compose.llm, "complete", fake_complete)
    r = client.post("/api/expand", headers=H, json={"content": n["content"], "selection": "选中的一段", "note_id": n["id"]})
    assert r.status_code == 200, r.text
    assert seen[-1].find(TRAY_LINES[0]) < seen[-1].find("检索来的")

    class _Mem:
        def __init__(self, user): ...
        def fact_by_id(self, fid): return None
        def recall(self, q, limit=6, scope="all"): return ([{"id": "terrence-1-1F1", "text": "检索来的"}], [], 1.0)
    monkeypatch.setattr(compose, "UserMemory", _Mem)
    r = client.post("/api/verify", headers=H, json={"content": n["content"], "selection": "选中的一段", "note_id": n["id"]})
    assert r.status_code == 200, r.text
    assert seen[-1].find(TRAY_LINES[0]) < seen[-1].find("检索来的")
