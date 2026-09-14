"""屏幕活动进知识库这一段（docs/daily-journey-plan.md §3）。

两条最要紧的性质：
  · **没说出具体东西的描述不入库**——「在使用代码编辑器」读起来像个描述，
    其实什么都没说，而它会被召回、被引用（§7 ①）。
  · **删一天要连它抽出来的事实一起删**——只删文件不删事实的话，
    「我删了那天的记录」就是假的（§1 ⑤）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
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


def test_一行坏时间戳不能把整天打成_500(tmp_path, monkeypatch):
    """`_secs` 算不出来就当 0——**页面照样列得出这一天**。

    实拍（第 636 轮）：壳写的是 `toISOString()`（带 Z，带时区），手工塞进去的
    那几段不带时区，两者一减就 `can't subtract offset-naive and offset-aware
    datetimes`，`GET /day` 直接 500，整天一段都读不出来。合计分钟数算错一点
    没什么，一段都看不见才是真的坏。
    """
    from app.routers import journey as J

    day = tmp_path / "2026-09-14"
    day.mkdir()
    (day / "segments.json").write_text(json.dumps([
        {"start": "2026-09-14T01:00:00Z", "end": "2026-09-14T02:00:00Z", "app": "Code", "desc": "改 journey.py"},
        {"start": "2026-09-14T02:00:00", "end": "2026-09-14T02:30:00Z", "app": "Safari", "desc": "看文档"},  # 一头带时区一头不带
        {"start": "不是时间", "end": "也不是", "app": "Finder", "desc": ""},
        {"app": "飞书", "desc": "没有时间字段"},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)

    out = J.day(date="2026-09-14", user="tester")
    assert [s.app for s in out.segments] == ["Code", "Safari", "Finder", "飞书"]
    assert out.minutes == 60          # 只有第一段算得出来，其余当 0


def test_日报记下它是按几段写的(tmp_path, monkeypatch):
    """**日报是快照，这一天还在长。** 不带这个数，用户下午看到的还是上午那份，
    却没有任何迹象说明它已经过期了（第 637 轮）。"""
    from app.routers import journey as J

    day = tmp_path / "2026-09-14"
    day.mkdir()
    (day / "report.json").write_text(json.dumps(
        {"report": "## 推进了什么\n- 改了 a.py\n", "report_segments": 9,
         "report_at": "2026-09-14T18:00:00+08:00"}, ensure_ascii=False), encoding="utf-8")
    (day / "segments.json").write_text(json.dumps([
        {"start": "2026-09-14T01:00:00Z", "end": "2026-09-14T02:00:00Z", "app": "Code", "desc": "改 a.py"},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)

    out = J.day(date="2026-09-14", user="tester")
    assert out.report_segments == 9 and out.report_at.startswith("2026-09-14T18")
    assert "改了 a.py" in out.report


def test_一段描述都没有就别花那次模型调用(tmp_path, monkeypatch):
    """没有描述只剩应用名，模型只会拿应用名编一份出来——那比没有更糟。"""
    from app.routers import journey as J

    day = tmp_path / "2026-09-14"
    day.mkdir()
    (day / "segments.json").write_text(json.dumps([
        {"start": "2026-09-14T01:00:00Z", "end": "2026-09-14T02:00:00Z", "app": "Code", "desc": ""},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)

    with pytest.raises(HTTPException) as e:
        asyncio.run(J.report(date="2026-09-14", user="tester"))
    assert e.value.status_code == 400
