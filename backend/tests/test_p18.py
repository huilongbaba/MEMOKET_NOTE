"""P18（`docs/TRACELOG-product.md` P18 节）：后端 harness 与导出的遗留。

  1. `done_criteria` 命中的轮不作废：`BestOf` 让它沿用上一轮的排名（不升不降），平手归后来者 → 交更长的那份；
     别的判据照旧打到底。`Checks` 把「这一轮是哪条短路的」写进 `bag["short_circuit"]`（`fired_checks` 被 Ledger pop 掉）。
  2. 跑完只落一行收尾：`Edits` 的 `harness` 行带 `round_no`，`round_snapshot` 看到它就不再存 `run_end`；
     暂停（没进 harness_runs）的跑仍是 `run_end`——每个取值都真写真读一遍（§21）。
  4. 飞书 mermaid → 图：`mermaid_key` / `mermaid_blocks`、`md_to_feishu_children(md, renders)`、`FeishuWriter` 传内存里的 PNG、
     `POST /api/export/mermaid` + `/renders` + 导回时用掉。
  5. Notion 本地图片走 File Upload API 两步 → `file_upload` 图片块；文件不在 / 传不上退回一行说明。

每条断言的量程写在 docstring 里（撤掉哪一行它红）。
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.database import exporters, store                               # noqa: E402
from app.harness import loop, modes                                     # noqa: E402
from app.harness.events import Event                                    # noqa: E402
from app.harness.middleware.best_of import BestOf, NOT_A_VETO           # noqa: E402
from app.harness.middleware.checks import Checks, STUCK_ROUNDS          # noqa: E402
from app.harness.middleware.edits import Edits                          # noqa: E402
from app.harness.round_snapshot import with_round_snapshots             # noqa: E402
from app.harness.state import State                                     # noqa: E402
from app.harness.tools import ToolContext                               # noqa: E402
from app.harness.types import DimensionScore, Evaluation, Verdict       # noqa: E402
from app.routers import export as export_router                         # noqa: E402

USER = "p18"
DIMS = ("spine_fidelity", "beat_coverage", "non_repetition", "factual_grounding", "coherence", "material_use")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app
    return TestClient(app, headers={"X-User-Id": USER})


# ================================================================ 1. done_criteria 命中不作废

def _st(**kw) -> State:
    mode = dataclasses.replace(modes.NOTE, dims=DIMS, max_rounds=4, **kw)
    return State(mode=mode, ctx=ToolContext(user=USER, note_id="n", note_title="t"))


def _judged(**levels) -> Evaluation:
    lv = {d: 2 for d in DIMS} | levels
    return Evaluation(scores={d: DimensionScore(level=lv[d], note="") for d in DIMS},
                      status="continue", weakest=min(lv, key=lv.get))


def _hit(st: State, check: str, content: str) -> None:
    """像 `Checks.before_judge` 短路时那样摆好状态：单维 0 分的伪造评分 + skip_judge + 是哪条短路的。"""
    st.ev = Evaluation(scores={"factual_grounding": DimensionScore(level=0, note="…")}, status="continue", weakest="factual_grounding")
    st.skip_judge = True
    st.bag["short_circuit"] = check
    st.content = content


def _judge(st: State, content: str, **levels) -> None:
    st.ev, st.skip_judge, st.bag["short_circuit"], st.content = _judged(**levels), False, "", content


def _round(st: State, n: int) -> None:
    st.round = n
    asyncio.run(BestOf().after_judge(st))
    st.ev, st.skip_judge = None, False


# P15 真跑 da080ca847cf 的形状（`docs/_research/p15-runs/da080ca847cf-p15.json`）：
# r1 判过分 (5, 1.83)、2 段；r2 / r3 `done_criteria`；r4 `no_placeholder`。修前交 r1。
def test_1_done_criteria短路的轮沿用上一轮排名_交更长的那份():
    """量程：`BestOf.after_judge` 里「短路的是 NOT_A_VETO 就沿用 prev_rank」那两行；撤掉 → best 钉在 r1。"""
    st = _st()
    _judge(st, "r1", beat_coverage=1); _round(st, 1)
    assert st.best[0] == (5, pytest.approx(1.833, abs=0.01))
    _hit(st, "done_criteria", "r1 r2"); _round(st, 2)
    _hit(st, "done_criteria", "r1 r2 r3"); _round(st, 3)
    _hit(st, "no_placeholder", "r1 r2 r3 r4"); _round(st, 4)
    assert st.best[1] == "r1 r2 r3", "r2 / r3 只是用户标准有缺口，沿用 r1 的排名、平手归后来者；r4 是占位句，作废"
    assert st.best[0] == (5, pytest.approx(1.833, abs=0.01)), "沿用的是排名，不是凭空升一档"
    assert st.bag["best_coverage_unmet"] is True, "「最好那轮写够了没有」也跟着 r1 走（r1 beat_coverage=1）"


def test_1_别的判据照旧打到底():
    """反向闸：把 NOT_A_VETO 改成「所有判据」也能让上面两条绿。这一条钉住重复段 / 占位句仍然作废。

    **`citations_present` P55 #3 挪到上面那条正例去了**：它说的是「缺了编号」，不是
    「这一轮坏了」——量的数在 `middleware/best_of.NOT_A_VETO` 上面（72 轮 / 32,700 字）。
    留在这张表里的三条是 p5–p15 21 次真跑人读判定「确实不该交」的那几种。"""
    for check in ("no_same_sources_twice", "no_placeholder", "no_repeated_lists"):
        st = _st()
        _judge(st, "r1"); _round(st, 1)
        _hit(st, check, "r1 r2"); _round(st, 2)
        assert st.best[1] == "r1", check
    assert NOT_A_VETO == ("done_criteria", "citations_present")


# P53 真跑 `603dca25403a` 的形状（`<scratch>/p53/runs/603dca25403a.json`）：
# r1 五维真打分 (4, 1.8)；r2 / r3 被 `citations_present` 短路各写 343 / 358 字；
# r4 四维真打分 (3, 1.75) 追不上；r5 又被 `citations_present` 短路 → `check_stuck` 停。
# 修前交 r1 的 1,158 字，r2–r5 的 1,469 字全扔。
def test_1_citations_present短路的轮也沿用上一轮排名():
    """量程：把 `citations_present` 从 `NOT_A_VETO` 里拿掉 → best 钉死在 r1，这条红。"""
    st = _st()
    _judge(st, "r1"); _round(st, 1)
    r1 = st.best[0]
    _hit(st, "citations_present", "r1 r2"); _round(st, 2)
    assert st.best[1] == "r1 r2", "沿用 r1 的排名、平手归后来者 → 交更长的那份"
    _hit(st, "citations_present", "r1 r2 r3"); _round(st, 3)
    assert st.best[1] == "r1 r2 r3"
    assert st.best[0] == r1, "**排名一格没变**：换的只是交哪一份正文"
    # r4 真打分但维度少一个，排名更低 → best 不动；r5 沿用 r4 的低排名，也不动。
    _judge(st, "r1 r2 r3 r4", coherence=0, non_repetition=0); _round(st, 4)
    assert st.best[1] == "r1 r2 r3", "真打分打低了就是低了，沿用不等于免检"
    _hit(st, "citations_present", "r1 r2 r3 r4 r5"); _round(st, 5)
    assert st.best[1] == "r1 r2 r3", "沿用的是**上一轮**那个低排名，不是 best"


def test_1_第一轮就被done_criteria短路_没有上一轮可沿用_照旧最低():
    st = _st()
    _hit(st, "done_criteria", "r1"); _round(st, 1)
    assert st.best == ((0, 0.0), "r1")
    _judge(st, "r1 r2"); _round(st, 2)
    assert st.best[1] == "r1 r2", "真打过分的轮赢过它"


def test_1_沿用的排名不算退步_regressed不因它开火():
    """r1 (5,1.83) → r2 done_criteria 沿用 → 这一轮 `_regressed` 不看 skip_judge 的轮；r3 真判更低才算退步、交 r2（不是 r1）。"""
    st = _st()
    _judge(st, "r1"); _round(st, 1)                          # 六维全 2：覆盖写够了，武装
    _hit(st, "done_criteria", "r1 r2")
    st.round = 2
    asyncio.run(BestOf().after_judge(st))
    assert loop._regressed(st) is None, "短路的轮从来不算退步"
    st.ev, st.skip_judge = None, False
    _judge(st, "r1 r2 r3", non_repetition=1, coherence=1)
    st.round = 3
    asyncio.run(BestOf().after_judge(st))
    assert loop._regressed(st) == "regressed"
    assert st.best[1] == "r1 r2", "退步时交出去的是沿用了排名的 r2（更长），不是 r1"


def test_1_快照进出后prev_rank是列表也能比():
    st = _st()
    _judge(st, "r1"); _round(st, 1)
    st.bag["prev_rank"] = list(st.bag["prev_rank"])          # snapshot 往返把元组变成列表
    _hit(st, "done_criteria", "r1 r2"); _round(st, 2)
    assert st.best[1] == "r1 r2" and isinstance(st.best[0], tuple)


def test_1_打上限1分那个候选量过不成立():
    """「判据命中打 1 分而不是 0 分」：单维 1 分的 `rank()` 是 (0, 1.0)，仍输给任何一维达标的真评分——用户拿到的还是 r1。"""
    st = _st()
    st.ev = Evaluation(scores={"factual_grounding": DimensionScore(level=1, note="")}, status="continue", weakest="factual_grounding")
    assert st.rank() == (0, 1.0) < (5, 1.83)


def _mode_with(checks: tuple) -> State:
    mode = dataclasses.replace(modes.NOTE, checks=checks)
    return State(mode=mode, ctx=ToolContext(user=USER, note_id="n", note_title="t"), content="正文")


def test_1_Checks把这一轮是哪条短路的写进bag():
    """量程：`Checks.before_judge` 里 `st.bag["short_circuit"] = fired` 那一行 + 每轮先清空那一行。"""
    def done_criteria(st):
        return Verdict(dimension="factual_grounding", message="没出处")
    def quiet(st):
        return None

    st = _mode_with((quiet, done_criteria))
    asyncio.run(_drain(Checks().before_judge(st)))
    assert st.bag["short_circuit"] == "done_criteria" and st.skip_judge
    # 卡死放行（连响 > STUCK_ROUNDS）的那一轮：判据还在响，但没短路 → 不算
    st2 = _mode_with((done_criteria,))
    st2.bag["check_streak"] = {"factual_grounding\x00没出处": STUCK_ROUNDS}
    st2.bag["short_circuit"] = "done_criteria"               # 上一轮留下的
    asyncio.run(_drain(Checks().before_judge(st2)))
    assert st2.bag["short_circuit"] == "" and not st2.skip_judge


async def _drain(agen):
    return [e async for e in agen]


# ================================================================ 2. 收尾只落一行

@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")


def _rows(note_id: str) -> list[dict]:
    with store.connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT reason, run_id, round_no, content FROM note_revisions WHERE note_id=? ORDER BY rowid", (note_id,))]


def _note_state(nid: str) -> State:
    return State(mode=modes.NOTE, ctx=ToolContext(user=USER, note_id=nid, note_title="标题"), content="v0")


async def _run_like_loop(st: State, stopped: str, with_edits: bool):
    """像 loop.run：每轮 STEP_STARTED → 改正文；收尾 commit（落库）→ after_run（Edits）→ RUN_FINISHED。"""
    for n in (1, 2, 3):
        yield Event.step_started(n, "智能续写")
        st.round = n
        st.content = f"v{n}"
    st.stopped = stopped
    store.update_note(USER, st.ctx.note_id, "标题", st.content, source="harness")
    if with_edits:
        await Edits().after_run(st)
    yield Event.run_finished(st.content, stopped)


def _collect(st: State, events) -> None:
    async def go():
        return [e async for e in with_round_snapshots(events, st)]
    asyncio.run(go())


def test_2_跑完只有一行收尾_是Edits的harness行_带round_no(_db):
    """量程：`round_snapshot` 收尾前 `find_run_revision(... 'harness')` 那句；撤掉 → 同一份正文两行。"""
    nid = store.create_note(USER, "标题", "v0")["id"]
    st = _note_state(nid)
    st.bag["run_id"] = "run-p18"
    _collect(st, _run_like_loop(st, "complete", with_edits=True))
    rows = _rows(nid)
    assert [(r["reason"], r["round_no"]) for r in rows] == [("round", 1), ("round", 2), ("round", 3), ("harness", 3)]
    assert rows[-1]["content"] == "v3" and rows[-1]["run_id"] == "run-p18"
    assert not [r for r in rows if r["reason"] == "run_end"], "同一份正文不再存第二行"
    # 接口上：第 3 轮的「之后」就是这一行
    api = store.list_revisions(USER, nid)
    assert [(r["reason"], r["round_no"], r["run_id"]) for r in api][0] == ("harness", 3, "run-p18")


def test_2_暂停等处置的跑没有Edits行_收尾仍是run_end(_db):
    """`records_this_run` 把 awaiting_review 排除在外 → Edits 不落行 → 收尾行是 run_end（这一档取值真写得进去）。"""
    nid = store.create_note(USER, "标题", "v0")["id"]
    st = _note_state(nid)
    st.bag["run_id"] = "run-pause"
    _collect(st, _run_like_loop(st, "awaiting_review", with_edits=True))
    rows = _rows(nid)
    assert [(r["reason"], r["round_no"]) for r in rows] == [("round", 1), ("round", 2), ("round", 3), ("run_end", 3)]


def test_2_find_run_revision_只认同一次跑同一个reason(_db):
    nid = store.create_note(USER, "标题", "v0")["id"]
    store.snapshot_content(USER, nid, "标题", "v3", "harness", run_id="a", round_no=3)
    assert store.find_run_revision(USER, nid, "a", "harness")
    assert not store.find_run_revision(USER, nid, "b", "harness")
    assert not store.find_run_revision(USER, nid, "a", "run_end")
    assert not store.find_run_revision(USER, nid, "", "harness"), "没有 run_id 的跑别把别人的行当自己的"


# ================================================================ 4. 飞书 mermaid → 图

MD = "# 标题\n\n段落。\n\n```mermaid\ngraph TD\nA-->B\n```\n\n```python\nprint(1)\n```\n\n```mermaid\npie\n\"a\" : 1\n```\n"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def test_4_mermaid_key按源码算_两边同一个口径():
    """哈希 = strip 后源码的 sha256 前 24 位；前端只用后端给的键，这里钉住后端自己不漂。"""
    assert exporters.mermaid_key("graph TD\nA-->B\n") == exporters.mermaid_key("\ngraph TD\nA-->B") == "f202f94e8104ac38b446dbb2"
    blocks = exporters.mermaid_blocks(MD)
    assert set(blocks.values()) == {"graph TD\nA-->B", 'pie\n"a" : 1'} and len(blocks) == 2
    assert exporters.mermaid_blocks("```python\nprint(1)\n```") == {}


def test_4_飞书_有渲染先放图再放源码_没渲染代码块加一行说明():
    """量程：`md_to_feishu_children` 的 mermaid 分支。"""
    key = exporters.mermaid_key("graph TD\nA-->B")
    with_png = exporters.md_to_feishu_children(MD, {key: PNG})
    kinds = [b["block_type"] for b in with_png]
    assert kinds == [3, 2, 27, 14, 14, 14, 2], "第一张图有渲染：图 + 源码；第二张没有：源码 + 一行说明"
    assert with_png[2]["_asset_bytes"] == PNG and with_png[2]["_asset_name"] == f"mermaid-{key}.png"
    assert "mermaid" in with_png[6]["text"]["elements"][0]["text_run"]["content"]
    without = exporters.md_to_feishu_children(MD)
    assert [b["block_type"] for b in without] == [3, 2, 14, 2, 14, 14, 2]
    assert not any(b.get("_asset_bytes") for b in without)


class _FeishuFake:
    def __init__(self):
        self.calls: list = []
        self.uploads: list = []
        self.n = 0

    def __call__(self, method, path, json):
        self.calls.append((method, path))
        if "/auth/" in path:
            return {"tenant_access_token": "t"}
        if method == "UPLOAD":
            self.uploads.append((json["parent_node"], json["file_name"], json["_data"], json["_mime"]))
            return {"data": {"file_token": "tok"}}
        if method == "GET" and "/children" in path:
            return {"data": {"items": [], "has_more": False}}
        if method == "POST" and path.endswith("/descendant"):
            return {"data": {"children": [{"block_id": f"real-{i}"} for i in json["children_id"]]}}
        return {}


def test_4_飞书writer把内存里的PNG按三步传上去_块里不带下划线字段():
    """量程：`flatten` 挑 `_asset_bytes`、`replace_children` 里 `upload_image(data=...)` 那几行。"""
    fake = _FeishuFake()
    w = exporters.FeishuWriter("a", "b", call=fake)
    key = exporters.mermaid_key("graph TD\nA-->B")
    children = exporters.md_to_feishu_children("```mermaid\ngraph TD\nA-->B\n```", {key: PNG})
    ids, flat, images = w.flatten(children)
    assert [(i, b.get("_asset_bytes") is not None) for i, b in images] == [("b1", True)]
    assert all(not k.startswith("_") for node in flat for k in node), "送出去的块里没有 _asset_bytes 这种自用字段"
    w.replace_children("doc1", children)
    assert fake.uploads == [("real-b1", f"mermaid-{key}.png", PNG, "image/png")]
    assert ("PATCH", "/docx/v1/documents/doc1/blocks/real-b1") in fake.calls


def test_4_png_from_data_url_只认PNG_魔数_上限():
    good = "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert export_router.png_from_data_url(good) == PNG
    assert export_router.png_from_data_url("data:image/jpeg;base64," + base64.b64encode(PNG).decode()) is None
    assert export_router.png_from_data_url("data:image/png;base64," + base64.b64encode(b"GIF89a").decode()) is None
    assert export_router.png_from_data_url("data:image/png;base64,***") is None
    big = PNG + b"\0" * exporters.MERMAID_RENDER_MAX
    assert export_router.png_from_data_url("data:image/png;base64," + base64.b64encode(big).decode()) is None


def test_4_路由_mermaid列源码_renders只收PNG_导回时用掉(client, monkeypatch):
    """端到端：`/mermaid` 给键 → `/renders` 收 PNG（坏的退回）→ `/feishu` 把它传上去、暂存清空。"""
    fake = _FeishuFake()
    monkeypatch.setattr(exporters.FeishuWriter, "_req", lambda self, m, p, j=None, auth=True: fake(m, p, j))
    monkeypatch.setattr(exporters.FeishuWriter, "create_document", lambda self, folder, title: "doc1")
    monkeypatch.setattr(exporters.FeishuWriter, "doc_url", lambda self, did: "https://x.feishu.cn/docx/doc1")
    monkeypatch.setattr(exporters.FeishuWriter, "edited_time", lambda self, did: "1")
    monkeypatch.setattr(exporters.FeishuWriter, "_count_children", lambda self, did: 0)
    a = client.post("/api/notes", json={"title": "M", "content": MD}).json()
    keys = client.post("/api/export/mermaid", json={"note_ids": [a["id"]]}).json()
    assert set(keys.values()) == {"graph TD\nA-->B", 'pie\n"a" : 1'}
    k1 = exporters.mermaid_key("graph TD\nA-->B")
    good = "data:image/png;base64," + base64.b64encode(PNG).decode()
    r = client.post("/api/export/renders", json={"renders": {k1: good, "zz": good, exporters.mermaid_key("x"): "data:text/plain,hi"}}).json()
    assert r == {"stored": 1, "rejected": ["zz", exporters.mermaid_key("x")]}
    body = {"app_id": "cli_x", "app_secret": "s3", "folder_token": "fld", "note_ids": [a["id"]]}
    j = client.post("/api/export/feishu", json=body).json()
    assert j["created"] == 1
    assert [(u[1], u[2]) for u in fake.uploads] == [(f"mermaid-{k1}.png", PNG)], "只传了交上来的那一张；没交的 pie 退化成代码块"
    # 用完就扔：再导一次（更新那条路）没有图可传——按接口观测，不读模块全局（全量跑时别的测试会重载路由模块，
    # 这里 import 到的那份 `_RENDERS` 跟 app 里在用的不是同一个 dict）
    j = client.post("/api/export/feishu", json=body).json()
    assert j["updated"] == 1 and len(fake.uploads) == 1, "上次交的那张不能再被用第二次"


# ================================================================ 5. Notion 本地图片走 File Upload API

class _NotionFake:
    def __init__(self, upload_ok=True):
        self.calls: list = []
        self.uploads: list = []
        self.children: list = []
        self.upload_ok = upload_ok

    def __call__(self, method, path, json):
        self.calls.append((method, path))
        if path == "/file_uploads" and method == "POST":
            if not self.upload_ok:
                raise exporters.RemoteError("Notion 拒绝了这次上传（quota）", status=400, code="validation_error")
            return {"object": "file_upload", "id": f"fu-{len(self.uploads) + 1}", "status": "pending", "upload_url": "…"}
        if method == "UPLOAD":
            self.uploads.append((path, json["_name"], json["_data"], json["_mime"]))
            return {"object": "file_upload", "id": path.split("/")[2], "status": "uploaded"}
        if method == "POST" and path == "/pages":
            self.children = list(json["children"])
            return {"id": "page1", "url": "https://www.notion.so/page1", "last_edited_time": "2026-01-01T00:00:00.000Z"}
        if method == "GET" and path.startswith("/blocks/"):
            return {"results": [], "has_more": False}
        if method == "PATCH" and path.startswith("/blocks/"):
            self.children = list(json["children"])
        if method == "GET" and path.startswith("/pages/"):
            return {"id": "page1", "url": "https://www.notion.so/page1", "last_edited_time": "2026-01-01T00:00:00.000Z"}
        return {}


IMG = "![示意图](/api/assets/1b92815398ecb037dc2561f3.png)\n\n段落。"


def test_5_Notion_本地图片两步上传_挂成file_upload图片块(tmp_path):
    """量程：`NotionWriter.prepare` / `upload_file`；撤掉任一步 → children 里没有 file_upload 块。
    形状按 developers.notion.com/reference/create-a-file-upload、send-a-file-upload、docs/uploading-small-files 核过。"""
    (tmp_path / "1b92815398ecb037dc2561f3.png").write_bytes(PNG)
    fake = _NotionFake()
    w = exporters.NotionWriter("ntn_x", call=fake, asset_dir=tmp_path)
    r = w.create_page("parent", "T", exporters.md_to_notion_blocks(IMG))
    assert r["id"] == "page1"
    assert fake.calls[:2] == [("POST", "/file_uploads"), ("UPLOAD", "/file_uploads/fu-1/send")]
    assert fake.uploads == [("/file_uploads/fu-1/send", "1b92815398ecb037dc2561f3.png", PNG, "image/png")]
    assert fake.children[0] == {"object": "block", "type": "image", "image": {"type": "file_upload", "file_upload": {"id": "fu-1"}}}
    assert fake.children[1]["type"] == "paragraph"
    assert not any(k.startswith("_") for b in fake.children for k in b), "送出去的块里没有 _asset 标记"
    # 更新那条路也走 prepare
    fake2 = _NotionFake()
    w2 = exporters.NotionWriter("ntn_x", call=fake2, asset_dir=tmp_path)
    w2.replace_children("page1", "T", exporters.md_to_notion_blocks(IMG))
    assert fake2.children[0]["image"]["type"] == "file_upload"


def test_5_Notion_文件不在本机或传不上_退回一行说明_不拦整篇(tmp_path):
    fake = _NotionFake()
    w = exporters.NotionWriter("ntn_x", call=fake, asset_dir=tmp_path)          # 目录里没有这张图
    w.create_page("parent", "T", exporters.md_to_notion_blocks(IMG))
    assert fake.uploads == [] and fake.children[0]["type"] == "paragraph"
    assert "文件不在本机" in fake.children[0]["paragraph"]["rich_text"][0]["text"]["content"]
    (tmp_path / "1b92815398ecb037dc2561f3.png").write_bytes(PNG)
    fake = _NotionFake(upload_ok=False)
    w = exporters.NotionWriter("ntn_x", call=fake, asset_dir=tmp_path)
    r = w.create_page("parent", "T", exporters.md_to_notion_blocks(IMG))
    assert r["id"] == "page1", "一张图传不上不拦整篇"
    assert "传不上 Notion" in fake.children[0]["paragraph"]["rich_text"][0]["text"]["content"]


def test_5_Notion_外链图片照旧是external块():
    b = exporters.md_to_notion_blocks("![a](https://x.com/a.png)")[0]
    assert b["image"] == {"type": "external", "external": {"url": "https://x.com/a.png"}}
