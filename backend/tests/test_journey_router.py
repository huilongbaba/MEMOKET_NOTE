"""屏幕活动进知识库这一段（docs/daily-journey-plan.md §3）。

两条最要紧的性质：
  · **没说出具体东西的描述不入库**——「在使用代码编辑器」读起来像个描述，
    其实什么都没说，而它会被召回、被引用（§7 ①）。
  · **删一天要连它抽出来的事实一起删**——只删文件不删事实的话，
    「我删了那天的记录」就是假的（§1 ⑤）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database.kb.scope import SCOPE_LABEL, classify
from app.routers.journey import pick_answer, worth_keeping


def test_屏幕活动是独立的一档记忆范围():
    """一天几十段，量很快会盖过会议记录，所以必须能单独筛出来、也能单独排除。"""
    assert classify("screen-20260914-003") == "screen"
    assert classify("terrence-1344-13F2") == "meetings"
    assert classify("note-abc-0") == "notes"
    assert SCOPE_LABEL["screen"] == "只看屏幕活动"


def test_从模型的碎碎念里把答案捞出来():
    """本地视觉模型会边想边说（常常是英文），真答案在「答案：」后面。"""
    assert pick_answer("We need to look. Hmm.\n答案：在 VS Code 里改 PRD.md") \
        == "在 VS Code 里改 PRD.md"
    # 没有标记：退回最后一行有实质内容的中文
    assert pick_answer("thinking...\n在 Safari 浏览 amazon.com") == "在 Safari 浏览 amazon.com"
    assert pick_answer("") == ""


def test_没说出具体东西的不入库():
    assert worth_keeping("在 VS Code 中查看 Skills-Bugfixing-Feishu 工作区的 PRD.md")
    assert not worth_keeping("看不清")
    assert not worth_keeping("屏幕上的文字无法辨认")
    assert not worth_keeping("在浏览网页")          # 太短
    assert not worth_keeping("")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.database import store
    from app.main import app

    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    monkeypatch.setenv("MEMOKET_JOURNEY_DIR", str(tmp_path / "journey"))
    with TestClient(app, headers={"X-User-Id": "j-test"}) as c:
        yield c


def _day(root: Path, segs: list[dict]) -> None:
    d = root / "journey" / "2026-09-14"
    d.mkdir(parents=True, exist_ok=True)
    (d / "segments.json").write_text(json.dumps(segs, ensure_ascii=False), encoding="utf-8")


def test_读某天_日期不合法要拦下来(client, tmp_path):
    _day(tmp_path, [{"start": "2026-09-14T09:00:00", "end": "2026-09-14T09:30:00",
                     "app": "Code", "title": "", "n": 12, "frames": ["/nope.png"]}])
    r = client.get("/api/journey/day?date=2026-09-14").json()
    assert r["minutes"] == 30 and len(r["segments"]) == 1
    assert r["segments"][0]["app"] == "Code"
    assert client.get("/api/journey/day?date=not-a-date").status_code == 400


def test_没有截图的段跳过_不当成失败(client, tmp_path):
    """壳那边存帧可能失败（磁盘满、权限）。这不该让整天的补描述挂掉。"""
    _day(tmp_path, [{"start": "2026-09-14T09:00:00", "end": "2026-09-14T09:30:00",
                     "app": "Code", "title": "", "n": 12, "frames": []}])
    r = client.post("/api/journey/catch-up?date=2026-09-14").json()
    assert r["skipped"] == 1 and r["described"] == 0 and r["left"] == 0


def test_删一天_目录没了(client, tmp_path):
    _day(tmp_path, [{"start": "2026-09-14T09:00:00", "end": "2026-09-14T09:30:00",
                     "app": "Code", "title": "", "n": 1, "frames": []}])
    assert (tmp_path / "journey" / "2026-09-14").exists()
    client.delete("/api/journey/day?date=2026-09-14")
    assert not (tmp_path / "journey" / "2026-09-14").exists()
    assert client.get("/api/journey/day?date=2026-09-14").json()["segments"] == []
