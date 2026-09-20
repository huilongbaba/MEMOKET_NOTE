"""P15（`docs/TRACELOG-product.md` P15 节）：harness / 后端侧 P13、P14、P11 的遗留。

  1. `done_criteria` 排第几：插在 `material_used` 之后、`no_repeated_lists` 之前（P13 排最后 4 轮一次没轮到）；
     `Checks` 的「第一条响的赢」不改。
  2. 引笔记也是引用：`citations_present` / `material_thin`(b) 认 `[标题](note://id)`（`has_citation` 一个谓词两处读）；
     `citations_hold` 核 note://——那篇得在、引它那句在那篇里找得到依据（词法，`MIN_NOTE_SHARED`）。
  3. 导入默认进托盘的后端一半：`ingest_items.note_id` 真写真读、`IngestItemOut` 带出去；网页剪藏 `POST /tray/clip`；
     托盘项 ref_id 放得下网址；`tray.lines_of` 笔记项标题占位时退回正文首行（跟前端 `displayTitle` 一套）。
  4. 首开圆点：`recall` 的 grep 子查询按调用侧 2-gram 倒排表带 `units`（≤ 8 个）或占位 unit（零命中），条数 / 顺序不动；
     `_recall_via_lines` 零命中的词不发；判定对拍（假 store 上 kite 真跑：预筛前后 rows 一样）。

每条断言的量程写在 docstring 里（撤掉哪一行它红）。
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.database import store                                          # noqa: E402
from app.database.ingest import importers                               # noqa: E402
from app.database.kite import kite_memory                               # noqa: E402
from app.harness import modes, tray                                     # noqa: E402
from app.harness.checks import citations as C                           # noqa: E402
from app.harness.checks import done as D                                # noqa: E402
from app.harness.checks import grounding as G                           # noqa: E402
from app.harness.middleware import DoneCriteria                         # noqa: E402
from app.harness.middleware.done import insert_done                     # noqa: E402
from app.harness.state import State                                     # noqa: E402
from app.harness.tools import ToolContext                               # noqa: E402
from app.harness.types import Dimension, Mode                           # noqa: E402
from app.routers import import_sources, notes as notes_router           # noqa: E402

H = {"X-User-Id": "p15"}
NOTE_DIMS = ("spine_fidelity", "beat_coverage", "non_repetition", "factual_grounding", "coherence", "material_use")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app
    return TestClient(app)


def _st(content: str = "", *, fresh: str = "", facts=("[f-1-A] 材料一",), intent: str = "", **bag) -> State:
    mode = Mode(key="t", label="t", skill_scope="test_scope",
                dims=tuple(Dimension(d, "...") for d in NOTE_DIMS), groups=("memory",))
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="创业一年的回顾", intent=intent))
    st.content = content or fresh
    st.fresh = fresh
    st.facts = list(facts)
    st.bag.update(bag)
    return st


# ==================================================================== 1. done_criteria 排第几 ===

def test_1_done_criteria_插在材料族之后_重复族之前():
    """量程：`middleware/done.insert_done` 那个 `names.index(_AFTER) + 1`。退回「排最后」这条红。"""
    checks = insert_done(modes.NOTE.checks)
    names = [c.__name__ for c in checks]
    i = names.index("done_criteria")
    assert names.index("citations_present") < i and names.index("material_used") == i - 1
    assert i < names.index("no_repeated_lists") < names.index("no_same_sources_twice")
    assert len(checks) == len(modes.NOTE.checks) + 1 and names.count("done_criteria") == 1
    # 一个没有 material_used 的模式：排最后（别炸）
    assert insert_done(())[-1] is D.done_criteria


def test_1_DoneCriteria_挂上去的位置就是那一位_第几条跟着变():
    """量程：`DoneCriteria.before_run` 调的是 `insert_done` 而不是 `+ (done_criteria,)`。"""
    mode = modes.for_run(modes.NOTE, has_profile=False, polish=False)
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="t",
                                          intent="目标：x；读者：y；完成标准：每个结论有事实支撑"))
    asyncio.run(DoneCriteria().before_run(st))
    names = [c.__name__ for c in st.mode.checks]
    assert names.index("done_criteria") == names.index("material_used") + 1
    assert names[-1] != "done_criteria"
    asyncio.run(DoneCriteria().before_run(st))
    assert names == [c.__name__ for c in st.mode.checks]                  # 幂等


def test_1_第一条响的赢_没改_P13_那一轮材料族先响时说的是同一件事():
    """量程：`Checks.before_judge` 里**短路那一支的 `return`**（一轮一条**硬**指令）。

    **P58 A 改了这条的读数，原话留在下面。** 原来钉的是「一轮只有一条 `check_hit`」：
    P13 真跑第 1 轮 `citations_present` 先响、`done_criteria` 也会响，两条说的都是
    「补编号」，同时报只是重复。P58 把 `citations_present` 的 `located==0` 那两档改成
    `advisory`（报了**不**收这一轮，理由和数在 `types.Verdict.advisory`），于是这个局面
    变成：advisory 先报一条**软**的，`done_criteria` 再短路报一条**硬**的。

    「一轮一个指令」这条纪律一个字没松，只是量程换了载体：
      · **硬指令**（进 steer、决定下一轮改什么）仍然**只有一条**——短路是唯一会 `return`
        的出口，`short_circuit` 就是那一条；
      · 软的那条走 `bag["advisories"]` → `prompts/note.advisory_block`，措辞里自带
        「做不到就跳过，不用为它停下来」。
    这跟 `STUCK_ROUNDS` / `JUDGE_FLOOR` 两条放行支本来就是同一个形状（它们也 `continue`，
    后面的判据照样能再报一条），advisory 没有新开一种行为。
    """
    from app.harness.middleware.checks import Checks
    long = "这一轮写满一整段没有编号的内容。" * 30
    st = _st(fresh=long, intent="目标：x；读者：y；完成标准：每个结论有事实支撑", content_at_start="")
    st.mode = Mode(key="t", label="t", skill_scope="s", dims=st.mode.dims, groups=("memory",),
                   checks=insert_done((G.citations_present,)))

    async def go():
        return [e async for e in Checks().before_judge(st)]
    events = asyncio.run(go())
    vals = [e.data["value"] for e in events if e.data.get("name") == "check_hit"]
    hits = [v["check"] for v in vals]
    assert hits == ["citations_present", "done_criteria"]
    assert st.bag["fired_checks"] == ["citations_present", "done_criteria"]
    # **硬指令只有一条**：advisory 那条不 return、不短路，短路的是后面那条。
    assert [v["check"] for v in vals if v.get("advisory")] == ["citations_present"]
    assert st.bag["short_circuit"] == "done_criteria"
    assert st.skip_judge is True
    # 软的那条不进 steer，进 advisories（不这么写就等于闭嘴，见 `advisory_block`）。
    assert st.bag["advisories"] and "编号补不出来" in st.bag["advisories"][0]
    assert st.ev is not None and st.ev.scores["factual_grounding"].note == vals[1]["note"]


def test_1_照着提示弃答的那几条不再算没出处_右栏那份照旧():
    """量程：`done.done_criteria` 的 `fresh_only` 里那个 `not abstention_lines(s)`。P15 真跑第 3 轮：模型把两条编不出
    出处的结论改成「这里需要补上…的记录」，判据照数「6 条里 4 条没有出处」——跟自己的提示打架。"""
    start = "创业反思：\n\n## 检验标准\n\n用户自己写的一条。\n"
    fresh = ("- **继续**：这里需要补上“非用户在3秒内找到一键路径”的评审记录；在没有这两项记录前，不把结论写成“继续”。\n"
             "- **修改**：用户能完成操作，但需要解释。[terrence-1431-9F5]\n"
             "- **停止**：必须依靠“未来会好”才能说明价值。\n")
    st = _st(start + fresh, fresh=fresh, intent="目标：x；读者：y；完成标准：每个结论有事实支撑", content_at_start=start)
    v = D.done_criteria(st)
    assert v is not None and "这次写的 2 条里 1 条没有出处" in v.message and "「**停止**" in v.message
    # 全部弃答 / 全部有出处：不响
    st = _st(start + "- 这里需要补上“录音场景”的记录。\n", fresh="- 这里需要补上“录音场景”的记录。\n",
             intent="目标：x；读者：y；完成标准：每个结论有事实支撑", content_at_start=start)
    assert D.done_criteria(st) is None
    # 右栏那份（`check_done`）不带量程：照旧把弃答句数进去——那是给用户看的
    assert D.check_done("每个结论有事实支撑", start + fresh)[0]["why"] == "3 条里 2 条没有出处"


# ==================================================================== 2. 引笔记也是引用 ===

LONG = "托盘里那篇笔记讲了佩戴方式的讨论，我们意识到持续增加动效并不能替代功能体感。" * 8


def test_2_citations_present_认_note链接():
    """量程：`grounding.citations_present` 里的 `has_citation`。退回 `cited_ids` 这条红（第一个断言）。"""
    assert G.citations_present(_st(fresh=LONG + " [创业反思](note://0eecee3d7b94)")) is None
    assert G.citations_present(_st(fresh=LONG + " [f-1-A]")) is None
    v = G.citations_present(_st(fresh=LONG))
    assert v is not None and "note://" in v.message


def test_2_has_citation_两处读同一个谓词_material_thin_b_档也认():
    """量程：`grounding.material_thin` (b) 档用的是 `has_citation`（不是 `cited_ids`）。"""
    import inspect
    src = inspect.getsource(G.material_thin) + inspect.getsource(G.citations_present)
    assert "cited_ids(fresh)" not in src and src.count("has_citation(fresh)") == 2
    assert C.has_citation("x [a](note://0123456789ab)") and C.has_citation("x [t-1-A]") and not C.has_citation("x [a](https://x)")
    assert C.note_link_ids("[a](note://0123456789ab) [b](note://0123456789ab) [c](note://ffffffffffff)") == ["0123456789ab", "ffffffffffff"]


def test_2_note_citations_unsupported_那篇不在_或那句在那篇里找不到依据():
    """量程：`citations.note_citations_unsupported` 的 `_terms(sent) & terms` 门槛（`MIN_NOTE_SHARED`）。"""
    body = "创业反思：佩戴方式的动静结合方案被讨论后，我意识到自己一直在用「全部都在动」来掩盖功能体感的缺失。录音功能在职业场景里只有 5% 的情况能被光明正大使用。"
    get = {"0eecee3d7b94": body}.get
    ok = "佩戴方式的讨论让我们意识到，持续增加动效并不能替代功能体感。[创业反思](note://0eecee3d7b94)"
    assert C.note_citations_unsupported(ok, get) == []
    bad = C.note_citations_unsupported(
        "那篇里说过 2027 年要上市，融资五千万。[创业反思](note://0eecee3d7b94)\n\n见 [不存在](note://ffffffffffff)。", get)
    assert [(b["id"], b["why"]) for b in bad] == [("0eecee3d7b94", "unsupported"), ("ffffffffffff", "missing")]
    assert bad[0]["sentence"].startswith("那篇里说过") and bad[0]["shared"] < C.MIN_NOTE_SHARED
    # 链接顶在列表项开头 / 句子太短：退回整行
    assert C.note_citations_unsupported("- [创业反思](note://0eecee3d7b94) 录音功能在职业场景里只有 5% 的情况能被光明正大使用", get) == []


def test_2_citations_hold_核_note链接_只看这一轮写的_读库那一条路():
    """量程：`grounding.citations_hold` 开头那段 note:// 核对 + `_note_body_reader`（bag 有 `note_bodies` 就不碰库）。"""
    body = "佩戴方式的动静结合方案被讨论后，我意识到自己一直在用全部都在动来掩盖功能体感的缺失。"
    st = _st(fresh="那篇里说过 2027 年要上市，融资五千万。[创业反思](note://0eecee3d7b94)",
             note_bodies={"0eecee3d7b94": body})
    v = G.citations_hold(st)
    assert v is not None and v.dimension == "factual_grounding" and "找不到它说的事" in v.message and "note://0eecee3d7b94" in v.message
    # 那句话在那篇里找得到依据 → 放行（claimed_sources 空，后半段也不响）
    st = _st(fresh="佩戴方式被讨论后我意识到自己在用全部都在动掩盖功能体感的缺失。[创业反思](note://0eecee3d7b94)",
             note_bodies={"0eecee3d7b94": body})
    assert G.citations_hold(st) is None
    # 不存在的那篇
    st = _st(fresh="随便一句。[x](note://ffffffffffff)", note_bodies={})
    v = G.citations_hold(st)
    assert v is not None and "不存在的笔记" in v.message
    # 用户自己链的（不在 fresh 里）不判
    st = _st(content="用户自己写的 [x](note://ffffffffffff)", fresh="这一轮写的没有链接。", note_bodies={})
    assert G.citations_hold(st) is None


def test_2_citations_hold_真读库(client, monkeypatch):
    """量程：`_note_body_reader` 读 `store.get_note(user, id)` 那一行。"""
    n = client.post("/api/notes", headers=H, json={"title": "创业反思", "content": "佩戴方式的动静结合方案被讨论后，我意识到自己一直在用全部都在动来掩盖功能体感的缺失。"}).json()
    mode = Mode(key="t", label="t", skill_scope="s", dims=tuple(Dimension(d, "...") for d in NOTE_DIMS), groups=("memory",))
    st = State(mode=mode, ctx=ToolContext(user="p15", note_id="x", note_title="t"))
    st.fresh = st.content = f"佩戴方式被讨论后我意识到自己在用全部都在动掩盖功能体感的缺失。[创业反思](note://{n['id']})"
    assert G.citations_hold(st) is None
    st.fresh = st.content = f"那篇里说过 2027 年要上市，融资五千万。[创业反思](note://{n['id']})"
    assert G.citations_hold(st) is not None
    st.fresh = st.content = "随便一句。[x](note://ffffffffffff)"
    assert "不存在的笔记" in G.citations_hold(st).message


# ==================================================================== 3. 导入 / 剪藏进托盘的后端一半 ===

@pytest.fixture()
def iso(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    fake = SimpleNamespace(kite_data_dir=tmp_path, kite_extract_model="fake", whisper_base_url="http://x")
    monkeypatch.setattr(import_sources, "get_settings", lambda: fake)
    return tmp_path


def test_3_导入的每一条记下落成了哪篇_真写真读_同一份再导也记(iso):
    """量程：`import_sources._land` 里的 `landed_id` + `store.set_item(note_id=)` + `_ADDED_COLUMNS` 那一列。"""
    def note(title, sid):
        return importers.ImportedNote(title=title, content=f"{title} 的正文。", date="2026-03-10", source="obsidian", source_id=sid)
    job_id, items = store.create_batch_job("u1", [{"filename": "a.md", "kind": "obsidian"}, {"filename": "b.md", "kind": "obsidian"}])
    import_sources._land("u1", [note("周会", "vault/a.md"), note("复盘", "vault/b.md")], "notes", job_id, items)
    got = store.get_items(job_id)
    ids = [store.find_note_by_source("u1", "obsidian", s)["id"] for s in ("vault/a.md", "vault/b.md")]
    assert [g["note_id"] for g in got] == ids and all(g["status"] == "done" for g in got)
    # 同一份再导：不再建一篇，但 note_id 照记那篇
    job2, items2 = store.create_batch_job("u1", [{"filename": "a.md", "kind": "obsidian"}])
    import_sources._land("u1", [note("周会", "vault/a.md")], "notes", job2, items2)
    assert store.get_items(job2)[0]["note_id"] == ids[0]
    # 只进知识库、没建过笔记的：空串（`to=kb` 这条 UserMemory 会真抽——用假的 remember 挡住）
    from app.database.kite.kite_memory import UserMemory
    job3, items3 = store.create_batch_job("u1", [{"filename": "c.md", "kind": "obsidian"}])
    import_sources.UserMemory.remember = lambda self, *a, **k: 0        # type: ignore[assignment]
    try:
        import_sources._land("u1", [note("新篇", "vault/c.md")], "kb", job3, items3)
    finally:
        del UserMemory.remember
    assert store.get_items(job3)[0]["note_id"] == ""
    # 出参带着走
    from app.routers.schemas import IngestItemOut
    assert IngestItemOut(**got[0]).note_id == ids[0]


def test_3_网页剪藏进托盘_只进托盘_同一网址不重复_抓不到回400说人话(client, monkeypatch):
    """量程：`routers/notes.clip_to_tray` + `fetch_page` / `page_title` / `page_text`。"""
    n = client.post("/api/notes", headers=H, json={"title": "创业一年的回顾", "content": "## 历程\n"}).json()
    html = ("<html><head><title>Kickstarter 上线复盘 · 博客</title><style>p{}</style></head>"
            "<body><nav>首页 关于</nav><article><h1>上线复盘</h1><p>3 月 10 日上众筹，页面要放自己的 UI。</p>"
            "<ul><li>录音信任</li><li>即时反馈</li></ul></article><footer>版权</footer></body></html>")

    class _R:
        def __init__(self, status, content, ctype="text/html; charset=utf-8"):
            self.status_code, self.content, self.headers, self.encoding = status, content, {"content-type": ctype}, "utf-8"

    class _Client:
        def __init__(self, resp): self.resp = resp
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): return self.resp

    import httpx
    monkeypatch.setattr(httpx, "Client", lambda **k: _Client(_R(200, html.encode())))
    r = client.post(f"/api/notes/{n['id']}/tray/clip", headers=H, json={"url": "https://example.com/post"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["kind"] == "import" and items[0]["ref_id"] == "https://example.com/post"
    assert items[0]["title"] == "Kickstarter 上线复盘 · 博客"
    assert "3 月 10 日上众筹" in items[0]["excerpt"] and "- 录音信任" in items[0]["excerpt"]
    assert "首页" not in items[0]["excerpt"] and "版权" not in items[0]["excerpt"] and "p{}" not in items[0]["excerpt"]
    # 正文没动、没进知识库（托盘 ≠ 正文）
    assert client.get(f"/api/notes/{n['id']}", headers=H).json()["content"] == "## 历程\n"
    # 同一网址、正文没变再剪：还是一条（store 按 kind/ref_id/excerpt 去重，路由不另设守卫）
    r = client.post(f"/api/notes/{n['id']}/tray/clip", headers=H, json={"url": "https://example.com/post"})
    assert len(r.json()["items"]) == 1
    # 没有 <article> 的页：导航 / 页脚 / 脚本靠剥标签那一步去掉（有 <article> 时它们本来就在外面）
    bare = ("<html><head><title>无 article</title></head><body><nav>首页 关于</nav><script>var x=1</script>"
            "<div><p>正文一句：4 月 10 日拿到手板。</p></div><footer>版权</footer></body></html>")
    monkeypatch.setattr(httpx, "Client", lambda **k: _Client(_R(200, bare.encode())))
    r = client.post(f"/api/notes/{n['id']}/tray/clip", headers=H, json={"url": "https://example.com/bare"})
    ex = r.json()["items"][-1]["excerpt"]
    assert "4 月 10 日拿到手板" in ex and "首页" not in ex and "版权" not in ex and "var x" not in ex
    # 抓不到：400 + 人话；非网址 400
    monkeypatch.setattr(httpx, "Client", lambda **k: _Client(_R(404, b"")))
    r = client.post(f"/api/notes/{n['id']}/tray/clip", headers=H, json={"url": "https://example.com/gone"})
    assert r.status_code == 400 and "404" in r.json()["detail"]
    monkeypatch.setattr(httpx, "Client", lambda **k: _Client(_R(200, b"%PDF", "application/pdf")))
    assert client.post(f"/api/notes/{n['id']}/tray/clip", headers=H, json={"url": "https://example.com/a.pdf"}).status_code == 400
    assert client.post(f"/api/notes/{n['id']}/tray/clip", headers=H, json={"url": "ftp://x"}).status_code == 400
    assert client.post("/api/notes/nope/tray/clip", headers=H, json={"url": "https://x"}).status_code == 404
    assert len(client.get(f"/api/notes/{n['id']}/tray", headers=H).json()["items"]) == 2     # post + bare；失败的几次一条没加
    assert notes_router.page_title("<title> A &amp; B </title>") == "A & B"


def test_3_托盘项_ref_id_放得下网址(client):
    """量程：`store.normalize_tray_item` 的 `[:TRAY_REF_MAX]`（原来 80，一条网址就截断）。"""
    n = client.post("/api/notes", headers=H, json={"title": "t", "content": "x"}).json()
    url = "https://example.com/" + "a" * 200
    r = client.put(f"/api/notes/{n['id']}/tray", headers=H, json={"items": [{"kind": "import", "ref_id": url, "excerpt": "正文"}]})
    assert r.json()["items"][0]["ref_id"] == url and store.TRAY_REF_MAX >= 512


def test_3_托盘里笔记项标题是占位时退回正文首行():
    """量程：`harness/tray.display_title` + `lines_of` 用它。P14 真跑 prompt 里是 `[笔记「未命名」](note://92d07…)`。"""
    it = {"kind": "note", "ref_id": "92d07b760f1e", "title": "未命名",
          "excerpt": "我们产品当前遇到的挑战：四项核心挑战归纳为验证框架：录制信任、关联即时反馈"}
    assert tray.lines_of([it])[0].startswith("[笔记「我们产品当前遇到的挑战」](note://92d07b760f1e) ")
    assert tray.display_title("创业反思", "x") == "创业反思"
    assert tray.display_title("", "# 标题行\n正文") == "标题行"
    assert tray.display_title("Untitled", "") == "未命名"
    assert tray.display_title("note", "好的，那就这么定了，明天再说") == "好的，那就这么定了"     # 逗号太靠前不截，找下一个句读
    assert len(tray.display_title("", "一" * 80)) == tray.TITLE_FALLBACK_MAX
    assert tray.PLACEHOLDER_TITLES == {"", "未命名", "Untitled", "note"}                       # 跟前端 displayTitle.PLACEHOLDER 同一份


# ==================================================================== 4. 首开圆点：调用侧的词法预筛 ===

def _fake_store():
    F = SimpleNamespace
    facts = {
        "u1-F1": F(unit="u1", text="EVT 的大节点是 4 月 16 号"),
        "u1-F2": F(unit="u1", text="准备 4 台主机，15 套 PCBA"),
        "u2-F1": F(unit="u2", text="Kickstarter 众筹 3 月 10 号上线"),
        "u3-F1": F(unit="u3", text="录音功能在职业场景里只有 5%"),
    }
    lines = {"l1": F(unit="u1", text="四月十六号 EVT 是纯主机的"), "l2": F(unit="u2", text="3月10号上众筹")}
    return F(facts=facts, lines=lines)


def test_4_倒排表_命中的unit_跟_kite_同一个谓词_大小写不分():
    """量程：`_GrepIndex.units_for`（casefold 2-gram 交集 + 原文 `re.I` 复核）。"""
    idx = kite_memory._GrepIndex(_fake_store())
    assert idx.units_for("evt") == frozenset({"u1"}) and idx.units_for("pcba") == frozenset({"u1"})
    assert idx.units_for("众筹") == frozenset({"u2"}) and idx.units_for("众筹", lines=True) == frozenset({"u2"})
    assert idx.units_for("没有的词") == frozenset() and idx.units_for("evt", lines=True) == frozenset({"u1"})
    assert idx.units_for("a|b") is None and idx.units_for("e") is None       # 复杂正则 / 单字：不预筛


def test_4_grep_子查询按预筛改写_条数顺序不动_零命中给占位unit():
    """量程：`UserMemory._prescreen` / `_narrow_grep_query`。删一条子查询这条红（kite 只取前 3 条）。"""
    mem = kite_memory.UserMemory("p15-fake")
    st = _fake_store()
    mem._cache[f"{mem.path}#grepidx"] = (mem.path.stat().st_mtime if mem.path.exists() else 0, kite_memory._GrepIndex(st), st)
    import os
    os.makedirs(mem.dir, exist_ok=True)
    mem.ensure()
    mem._cache[f"{mem.path}#grepidx"] = (mem.path.stat().st_mtime, kite_memory._GrepIndex(st), st)
    q = [{"select": "facts", "where": {"topics": [{"code": "x", "closure": True}], "entities": []}, "pipe": []},
         {"select": "facts", "where": {"grep": "evt"}, "pipe": [{"op": "head", "n": 800}]},
         {"select": "facts", "where": {"grep": "没有的词"}, "pipe": [{"op": "head", "n": 800}]},
         {"select": "facts", "where": {"grep": "a|b"}, "pipe": [{"op": "head", "n": 800}]}]
    out = mem._prescreen(st, q)
    assert len(out) == 4 and out[0] == q[0] and out[3] == q[3]
    assert out[1]["where"] == {"grep": "evt", "units": ["u1"]}
    assert out[2]["where"] == {"grep": "没有的词", "units": [kite_memory._NO_UNIT]}
    assert q[1]["where"] == {"grep": "evt"}                                    # 原来那份没被改
    # > 8 个 unit：原样
    many = frozenset(f"u{i}" for i in range(9))
    assert kite_memory._narrow_grep_query(q[1], many) == q[1]


def test_4_真_kite_上预筛前后_rows_一样(tmp_path, monkeypatch):
    """量程：语义不变——拿一份真 codebook（`add_manual_fact` 建三个 session）让 kite 真执行，改写前后 `execute_plan`
    的 rows 逐条相等（含零命中那档的占位 unit 和 ≤ 8 个 unit 那档）；整条 `recall` 走一遍也一样。"""
    from memoket_kite.core.algebra import execute_plan
    fake = SimpleNamespace(kite_data_dir=tmp_path, kite_extract_model="fake", whisper_base_url="http://x")
    monkeypatch.setattr(kite_memory, "get_settings", lambda: fake)
    mem = kite_memory.UserMemory("u1")
    mem.add_manual_fact("u1-1-0", "EVT 的大节点是 4 月 16 号，准备 4 台主机。", date="2026-04-16", title="EVT 会")
    mem.add_manual_fact("u1-1-0", "准备 4 台主机，15 套 PCBA。", date="2026-04-16", title="EVT 会")
    mem.add_manual_fact("u1-2-0", "Kickstarter 众筹 3 月 10 号上线，主机页面要放 UI。", date="2026-03-10", title="众筹会")
    mem.add_manual_fact("u1-3-0", "录音功能在职业场景里只有 5% 能用。", date="2026-05-01", title="访谈")
    kstore, vocab = mem._index()
    idx = mem._grep_index(kstore)
    assert idx is not None and idx.units_for("没有的词") == frozenset() and len(idx.units_for("主机")) == 2
    for term in ("evt", "pcba", "众筹", "没有的词", "上线", "主机"):
        q = [{"select": "facts", "where": {"grep": term}, "pipe": [{"op": "head", "n": 800}]},
             {"select": "facts", "where": {"grep": "主机"}, "pipe": [{"op": "head", "n": 800}]}]
        before, _ = execute_plan(kstore, vocab, {"queries": q}, budget=1600)
        narrowed = mem._prescreen(kstore, q)
        after, _ = execute_plan(kstore, vocab, {"queries": narrowed}, budget=1600)
        assert [(r["id"], r["score"]) for r in after] == [(r["id"], r["score"]) for r in before], term
        assert narrowed[0]["where"].get("units") is not None                # 真的被改写了（不是原样跑两遍）
    assert len(before) > 0                                                  # 最后一轮（主机）真有结果，不是空对空
    # 整条 recall：预筛开 / 关（`_prescreen` 退回原样）结果一样
    rows_on = mem.recall("4 月 16 号 EVT 准备主机和 PCBA", limit=8)[0]
    monkeypatch.setattr(mem, "_prescreen", lambda store_, qs: qs)
    rows_off = mem.recall("4 月 16 号 EVT 准备主机和 PCBA", limit=8)[0]
    assert [r["id"] for r in rows_on] == [r["id"] for r in rows_off] and rows_on


def test_4_行级回退_零命中的词不发_命中的带units(monkeypatch):
    """量程：`_recall_via_lines` 里 `if units is not None and not units: continue` + `_narrow_grep_query`。"""
    mem = kite_memory.UserMemory("p15-fake2")
    st = _fake_store()
    calls: list[dict] = []

    def fake_exec(store_, vocab, plan, **kw):
        calls.append(plan["queries"][0]["where"])
        return [], None
    monkeypatch.setattr(kite_memory, "execute_plan", fake_exec)
    monkeypatch.setattr(mem, "_grep_index", lambda store_: kite_memory._GrepIndex(store_))
    monkeypatch.setattr(mem, "_cjk_terms", lambda q: ["众筹", "没有的词"])
    monkeypatch.setattr(mem, "_candidate_terms", lambda q: ["evt", "zzz"])
    assert mem._recall_via_lines(st, None, "众筹 evt", 8) == []
    assert calls == [{"grep": "众筹", "units": ["u2"]}, {"grep": "evt", "units": ["u1"]}]
