"""P101 A（第 819 轮）：**轮次卡读回来那条只读 API**（收 P99 B 判②）。

── P99 量清楚、判好形状的那件事 ───────────────────────────────────────────
  > `harness_rounds` **早就逐轮记着骨架**（round / scores / status / weakest /
  > content_len / tool_calls / fired_checks / cite_*），而且 `record_harness_round`
  > **自己按 key 修剪到最近 400 行**。实测那一篇 **6 runs / 12 rounds**，
  > 界面重开之后 **0 张卡**——**前端一行都没读，也没有那条 API。**
  > **判**：不新开表、不把卡整个落库；补的是**读回来那条路**
  > （只读 API `key='note:<id>'` + 前端重建骨架），**零迁移 / 零新表 / 零体积增长**；
  > **缺的明细在卡上照实标**。

这份文件盯五件事：

* **它真的只读**：调完前后 `notes` / `harness_runs` / `harness_rounds` 三张表的
  指纹逐字相同。⚠️ **先喂一个真会写的反例**证明那条闸看得见写——不然它是一条
  永远绿的闸（「闸跑绿不等于闸有用」）。
* **`key` 逐字匹配**：库里真有 `note:stage3-<id>-<n>` 这种 key（分段跑的），
  而它**里头含着那一篇的 id** ——`like '%'||<id>||'%'` 会把分段跑的那几轮当成整篇的端上来。
* **三档「读不到」分得开**（**「选不到 ≠ 没有」**）：`ok` / `no_rounds` / `no_run_id`。
  尤其 `no_run_id`（没挂 `Ledger` 的老跑法，按 run 分不开）**不是**「这一篇没跑过」。
* **只读最近那一次跑**，而且 `runsTotal` / `roundsTotal` 照实报（库里一共多少）。
* **接得上**：路由真的挂在 app 上、别人的笔记 404、`missing` 逐条回来
  ——建了不接等于没建（P32 / P34 / P36 / P37 各栽过一次）。

**它答不了**：前端拿到之后摆成什么样（那在 `frontend/src/components/__tests__/p101.test.tsx`）、
真壳上关掉重开之后屏幕上是什么（那在走查的 `steps/rounds101.mjs`）。
"""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app.database import store
from app.main import app

USER = "p101"
OTHER = "p101-other"


@pytest.fixture()
def client():
    with TestClient(app, headers={"X-User-Id": USER}) as c:
        yield c


def _note(user: str = USER, content: str = "甲乙丙丁") -> str:
    return store.create_note(user, "P101", content)["id"]


def _round(note_id: str, run_id: str, n: int, **kw) -> None:
    kw.setdefault("scores", {"coverage": 2, "non_repetition": 1})
    kw.setdefault("status", "continue")
    kw.setdefault("weakest", "non_repetition")
    kw.setdefault("content_len", 446)
    store.record_harness_round(key=f"note:{note_id}", run_id=run_id, round_=n, **kw)


def _fp() -> str:
    """三张表的指纹。**三张一起**：只看行数改内容不涨行，只看内容删一行加一行正好抵消。"""
    h = hashlib.sha256()
    with store.connect() as c:
        for t in ("notes", "harness_runs", "harness_rounds"):
            for r in c.execute(f"SELECT * FROM {t} ORDER BY rowid"):
                h.update(repr(tuple(r)).encode("utf-8"))
            h.update(f"|{t}|".encode())
    return h.hexdigest()


# ═══════════════ ① 它真的只读（**先喂反例**）═══════════════

def test_那条只读闸自己看得见写_先喂一个真会写的反例():
    """**「闸跑绿不等于闸有用」**：先证明 `_fp()` 抓得到一次写。

    不先喂这一条的话，下面那条「调完前后指纹相同」在**指纹算错**的情况下
    也照样绿——而那正是它唯一要防的事。
    """
    nid = _note()
    before = _fp()
    _round(nid, "run-neg", 1)            # ← 这就是那个反例：真往 harness_rounds 写一行
    assert _fp() != before, "往 `harness_rounds` 写了一行，指纹却没变 —— 这条闸是瞎的"


def test_调那条api前后三张表逐字相同(client):
    nid = _note()
    store.record_harness_run(key=f"note:{nid}", status="complete", rounds=2,
                             final_scores={}, weak_dimensions=[], run_id="run-1")
    _round(nid, "run-1", 1)
    _round(nid, "run-1", 2)
    before = _fp()
    r = client.get(f"/api/notes/{nid}/rounds")
    assert r.status_code == 200, r.text
    assert len(r.json()["rounds"]) == 2
    assert _fp() == before, "那条 API 动了库 —— 它必须是只读的"


def test_那个store函数的源码里一条写sql都没有():
    """**判据宁可窄**：不是「我没写」，是**去源码里数**。"""
    import inspect
    src = inspect.getsource(store.last_note_run_rounds).upper()
    for w in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "CREATE ", "REPLACE "):
        assert w not in src, f"`last_note_run_rounds` 里出现了 `{w.strip()}` —— 它该是只读的"


# ═══════════════ ② key 逐字匹配 ═══════════════

def test_分段跑那种key不许被模糊匹配端上来(client):
    """库里真有 `note:stage3-92d07b760f1e-67861` 这种 key（走查那份库里就有），
    而它**里头含着那一篇的 id**。

    `WHERE key LIKE '%'||<id>||'%'` 会把分段跑的那几轮当成整篇的端上来
    —— **判据比产品宽的那张脸**。
    ⚠️ 前缀匹配（`'note:<id>%'`）在这个形状上咬不到它，所以**拿前缀当反例是砍空的**
    （P101 砍刀第 ⑫ 刀实拍）。
    """
    nid = _note()
    store.record_harness_round(key=f"note:stage3-{nid}-67861", run_id="run-stage", round_=1,
                               scores={}, status="continue", weakest="", content_len=1)
    r = client.get(f"/api/notes/{nid}/rounds").json()
    assert r["reason"] == "no_rounds", r
    assert r["rounds"] == []
    assert r["roundsTotal"] == 0


def test_隔壁那一篇的轮次一行都不许串过来(client):
    a, b = _note(), _note()
    _round(a, "run-a", 1)
    _round(b, "run-b", 1, content_len=999)
    assert client.get(f"/api/notes/{a}/rounds").json()["rounds"][0]["contentLen"] == 446
    assert client.get(f"/api/notes/{b}/rounds").json()["rounds"][0]["contentLen"] == 999


# ═══════════════ ③ 三档「读不到」分得开 ═══════════════

def test_没跑过是no_rounds(client):
    r = client.get(f"/api/notes/{_note()}/rounds").json()
    assert r["reason"] == "no_rounds"
    assert (r["runsTotal"], r["roundsTotal"]) == (0, 0)


def test_run_id空的老跑法回no_run_id_而且它不是没跑过(client):
    """`rounds_of_run('')` 会把**所有**空 run_id 的行一锅端回来（好几次跑混在一起）。

    所以这一档**不摆**——但它跟「这一篇没跑过」是两件事，
    `roundsTotal` 照实报着 3，**两件事不许长成同一个 0**。
    """
    nid = _note()
    for n in (1, 2, 3):
        _round(nid, "", n)
    r = client.get(f"/api/notes/{nid}/rounds").json()
    assert r["reason"] == "no_run_id"
    assert r["rounds"] == []
    assert r["roundsTotal"] == 3, "「分不开」被写成了「没有」"


def test_读的是最近那一次跑_而且总数照实报(client):
    nid = _note()
    _round(nid, "run-old", 1)
    _round(nid, "run-old", 2)
    _round(nid, "run-new", 1)
    r = client.get(f"/api/notes/{nid}/rounds").json()
    assert r["runId"] == "run-new"
    assert len(r["rounds"]) == 1
    assert (r["runsTotal"], r["roundsTotal"]) == (2, 3)


# ═══════════════ ④ 缺的明细逐条回来 ═══════════════

def test_missing逐条回来_而且那几样正是卡上有库里没有的(client):
    nid = _note()
    _round(nid, "run-1", 1)
    got = client.get(f"/api/notes/{nid}/rounds").json()["missing"]
    assert "本轮写出的正文" in got
    assert "打分器的判词" in got
    assert set(got) == set(store.ROUND_SKELETON_MISSING)


def test_scores回的是档位不是判词(client):
    """库里 `ledger.after_judge` 存的是 `{n: s.level}` —— **判词从来没落过库**。"""
    nid = _note()
    _round(nid, "run-1", 1, scores={"coverage": 2})
    assert client.get(f"/api/notes/{nid}/rounds").json()["rounds"][0]["scores"] == {"coverage": 2}


def test_cite三列的负一原样带出来_不许变成0(client):
    """`-1` = 这一轮压根没走到 `before_judge`；`0` = 算过了、一句可引的都没有。

    折成同一个数就把「答不了」说成了「0%」（`citeCoverLine` 那两句话的全部理由）。
    """
    nid = _note()
    _round(nid, "run-1", 1)                                   # 默认三列都是 -1
    _round(nid, "run-1", 2, cite_located=0, cite_marked=0, cite_matched=0)
    rs = client.get(f"/api/notes/{nid}/rounds").json()["rounds"]
    assert rs[0]["citeLocated"] == -1
    assert rs[1]["citeLocated"] == 0


def test_fired_checks原样带出来(client):
    nid = _note()
    _round(nid, "run-1", 1, fired_checks=json.dumps(["citations_exist"]))
    assert client.get(f"/api/notes/{nid}/rounds").json()["rounds"][0]["firedChecks"] == '["citations_exist"]'


# ═══════════════ ⑤ 接得上 ═══════════════

def test_路由真的挂在app上():
    """**走 `app.openapi()` 不走 `app.routes`**：这个仓的路由是 `_IncludedRouter`
    套着的，`app.routes` 那一层里一条业务路径都读不到——**「选不到 ≠ 没有」**。
    openapi 那份是真正对外服务的那一张表。"""
    paths = set(app.openapi()["paths"])
    assert "/api/notes/{note_id}/rounds" in paths, \
        f"建了不接等于没建（带 rounds 的只有：{sorted(p for p in paths if 'rounds' in p)}）"


def test_别人的笔记404(client):
    other = _note(OTHER)
    assert client.get(f"/api/notes/{other}/rounds").status_code == 404


def test_不存在的笔记404(client):
    assert client.get("/api/notes/nope-nope-nope/rounds").status_code == 404


def test_轮次按round排(client):
    nid = _note()
    for n in (3, 1, 2):
        _round(nid, "run-1", n)
    assert [r["round"] for r in client.get(f"/api/notes/{nid}/rounds").json()["rounds"]] == [1, 2, 3]


def test_收工那一行读得到_没有也不炸(client):
    nid = _note()
    _round(nid, "run-1", 1)
    assert client.get(f"/api/notes/{nid}/rounds").json()["status"] == ""   # 跑到一半被关掉
    store.record_harness_run(key=f"note:{nid}", status="complete", rounds=1,
                             final_scores={}, weak_dimensions=[], stopped="complete", run_id="run-1")
    got = client.get(f"/api/notes/{nid}/rounds").json()
    assert got["status"] == "complete"
    assert got["stopped"] == "complete"
