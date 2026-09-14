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


def test_跨时间回顾把缺日报的那几天写进正文(tmp_path, monkeypatch):
    """**这篇笔记之后会被读、被引用**，读的人得知道它是按哪些天写的——
    只在提示里说一句就过去不行（§4.2）。"""
    from app.routers import journey as J

    for d, md in (("2026-09-10", "## 推进了什么\n- 改了 a.py\n"),
                  ("2026-09-12", "## 推进了什么\n- 改了 b.py\n")):
        (tmp_path / d).mkdir()
        (tmp_path / d / "report.json").write_text(
            json.dumps({"report": md, "report_segments": 5}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)

    seen: dict = {}

    async def fake(messages, **kw):
        seen["user"] = messages[-1]["content"]
        return "## 这段时间主要在做什么\n- 在写 journey\n"

    monkeypatch.setattr(J.llm, "complete", fake)
    made: dict = {}
    monkeypatch.setattr(J.store, "journal_node", lambda user, day, depth=4: "月节点")
    monkeypatch.setattr(J.store, "create_note",
                        lambda user, title, content, parent="", **kw: made.update(
                            {"title": title, "content": content, "parent": parent}) or {"id": "n1"})

    out = asyncio.run(J.span(date_from="2026-09-10", date_to="2026-09-12", user="tester"))
    assert out.days == 2 and out.missing == ["2026-09-11"]
    assert "2026-09-11 这几天没有日报" in made["content"]
    assert made["parent"] == "月节点", "跨时间回顾要挂在那个月的日记下面，不是树根" 
    # 喂进去的是**日报**，不是原始的段
    assert "改了 a.py" in seen["user"] and "改了 b.py" in seen["user"]


def test_一份日报都没有就不写跨时间回顾(tmp_path, monkeypatch):
    """要的是「先去写日报」，不是一份空报告。"""
    from app.routers import journey as J

    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)
    with pytest.raises(HTTPException) as e:
        asyncio.run(J.span(date_from="2026-09-10", date_to="2026-09-12", user="tester"))
    assert e.value.status_code == 400 and "先在那几天各写一份" in e.value.detail


def test_描述做完就删大图_缩略图留着(tmp_path, monkeypatch):
    """§1 ③：8 小时 ≈ 960 张 ≈ 300MB/天，一个月 9GB，而且那是把风险留在磁盘上。
    缩略图留着——**一句没有任何凭据的描述，用户没法判断它是不是编的**。"""
    from app.routers import journey as J

    day = tmp_path / "2026-09-14"
    (day / "shots").mkdir(parents=True)
    (day / "thumbs").mkdir()
    big, small = day / "shots" / "001.png", day / "thumbs" / "001.jpg"
    big.write_bytes(b"PNG"), small.write_bytes(b"JPG")
    (day / "segments.json").write_text(json.dumps([
        {"start": "2026-09-14T01:00:00Z", "end": "2026-09-14T01:10:00Z", "app": "Code",
         "frames": [str(big)], "thumb": str(small)},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)

    async def fake_img(*a, **kw):
        return "答案：在 VS Code 里改 journey.py 的 catch_up"

    monkeypatch.setattr(J, "ask_image", fake_img)
    monkeypatch.setattr(J, "UserMemory", lambda user: type(
        "M", (), {"remember": lambda *a, **k: None, "remove_sessions": lambda *a: 0})())

    asyncio.run(J.catch_up(date="2026-09-14", limit=5, user="tester"))
    assert not big.exists(), "大图应该在描述做完之后就删掉"
    assert small.exists(), "缩略图要留着"


def test_过期还没描述的大图也要删(tmp_path, monkeypatch):
    """没描述也不能永远留着。段仍然在时间轴上，只是标成过期、没法再补描述。"""
    from app.routers import journey as J

    day = tmp_path / "2026-09-01"
    (day / "shots").mkdir(parents=True)
    big = day / "shots" / "001.png"
    big.write_bytes(b"PNG")
    (day / "segments.json").write_text(json.dumps([
        {"start": "2026-09-01T01:00:00Z", "end": "2026-09-01T01:10:00Z", "app": "Code",
         "frames": [str(big)], "desc": ""},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)

    out = J.day(date="2026-09-01", user="tester")
    assert not big.exists()
    assert out.segments[0].app == "Code"          # 段还在
    assert json.loads((day / "segments.json").read_text())[0]["skip"] == "截图已过期"


def test_删一段不挪后面那些段的下标(tmp_path, monkeypatch):
    """**不能真的从数组里抠掉**：那会让后面每一段的下标挪一位，
    正在看这一页的人点第 2 段删掉的其实是第 3 段。"""
    from app.routers import journey as J

    day = tmp_path / "2026-09-14"
    day.mkdir()
    (day / "segments.json").write_text(json.dumps([
        {"start": "2026-09-14T01:00:00Z", "end": "2026-09-14T02:00:00Z", "app": "A", "desc": "一"},
        {"start": "2026-09-14T02:00:00Z", "end": "2026-09-14T03:00:00Z", "app": "B", "desc": "二",
         "session": "screen-20260914-001"},
        {"start": "2026-09-14T03:00:00Z", "end": "2026-09-14T04:00:00Z", "app": "C", "desc": "三"},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)
    monkeypatch.setattr(J, "UserMemory", lambda user: type(
        "M", (), {"remove_sessions": lambda self, s: 3})())

    out = J.delete_segment(date="2026-09-14", i=1, user="tester")
    assert out.removed_facts == 3
    after = J.day(date="2026-09-14", user="tester")
    assert [s.app for s in after.segments] == ["A", "C"]
    assert [s.i for s in after.segments] == [0, 2]        # C 还是 2，没往前挪
    assert after.minutes == 120                            # 删掉的那小时不算了


def test_全部记忆不含屏幕活动():
    """**这是屏幕活动这一档能不能存在的前提**（§7 ③）。一天几十段、一个月上千条，
    不默认排除的话，右栏浮现的「相关记忆」会从有用的会议结论变成
    「你上周二在看某个网页」，续写取到的材料也一样。

    第 641 轮补：这条规矩原来只写在注释里，`filter_rows` 在 `all` 时原样返回。
    """
    from app.database.kb.scope import SCOPE_LABEL, filter_rows

    rows = [{"unit": "terrence-1872-5F8"}, {"unit": "screen-20260914-003"},
            {"unit": "note-abc-0"}, {"unit": "obsidian-x-1"}]
    for scope in ("", "all", "不认识的"):
        got = [r["unit"] for r in filter_rows(rows, scope)]
        assert "screen-20260914-003" not in got, scope
        assert len(got) == 3, scope
    # 要看它就明确选
    assert [r["unit"] for r in filter_rows(rows, "screen")] == ["screen-20260914-003"]
    # 标签上也得写出来——代码里做了的事，界面上不能说成别的
    assert "不含屏幕" in SCOPE_LABEL["all"]


def test_日报存成笔记挂在当天那页日记下面_重写覆盖不留一串同名(tmp_path, monkeypatch):
    """回顾是跟着日期走的东西，日记树就是按日期组织的。落在树根上的话，
    用几周之后树根全是「9 月 14 日这一天」。"""
    from app.database import store
    from app.routers import journey as J

    day = tmp_path / "2026-09-14"
    day.mkdir()
    (day / "report.json").write_text(json.dumps(
        {"report": "## 推进了什么\n- 改了 a.py\n", "report_segments": 5}, ensure_ascii=False),
        encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)

    out = J.save_report(date="2026-09-14", user="tester")
    note = store.get_note("tester", out.note_id)
    assert "改了 a.py" in note["content"]

    # 挂在 日记 / 2026 / 09 月 / 09-14 … 下面
    rows = {r["note_id"]: r for r in store.tree("tester")}
    chain, cur = [], rows[out.note_id]
    while cur and cur["parent_note_id"] in rows:
        cur = rows[cur["parent_note_id"]]
        chain.append(cur["title"])
    assert chain[-3:] == ["09 月", "2026", "日记"], chain

    # 再存一次：覆盖，不是第二篇
    (day / "report.json").write_text(json.dumps(
        {"report": "## 推进了什么\n- 改了 b.py\n"}, ensure_ascii=False), encoding="utf-8")
    again = J.save_report(date="2026-09-14", user="tester")
    assert again.note_id == out.note_id
    assert "改了 b.py" in store.get_note("tester", again.note_id)["content"]
