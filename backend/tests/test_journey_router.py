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


def _day(root: Path, segs: list[dict], day: str = "2026-09-14") -> None:
    d = root / "journey" / day
    d.mkdir(parents=True, exist_ok=True)
    (d / "segments.json").write_text(json.dumps(segs, ensure_ascii=False), encoding="utf-8")


def _today() -> str:
    """今天。**要验「大图还在」的用例必须用近的日子**——`_expire_frames` 挂在
    `GET /day` 上，超过 `FRAME_KEEP_DAYS` 的那天一开就把 `frames` 清了、
    顺手写上 `skip: 截图已过期`，夹具里那个写死的 2026-09-14 早就过期了。"""
    from datetime import date

    return date.today().isoformat()


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


def _seg(day: str) -> dict:
    return {"start": f"{day}T09:00:00Z", "end": f"{day}T09:30:00Z",
            "app": "Code", "title": "", "n": 12, "frames": []}


def test_有记录的日子按新到旧列_没段落文件的目录不算(tmp_path, monkeypatch):
    """翻天要按这个列表走：**按日期加一减一会走进一串空日子**。
    它同时回答「有没有用过」——停掉记录之后如果只看当天，页面会退回那一屏
    知情选择，以前记的东西就既看不到也删不掉了。

    *（第 794 轮 / P52：三个夹具日原来写的是 `[]`，只是当时随手填的
    ——这条闸要的是「有没有那个文件」那一格。`[]` 现在另有一条闸，见下面那几条。）*"""
    from app.routers import journey as J

    for d in ("2026-09-04", "2026-09-11", "2026-09-14"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "segments.json").write_text(json.dumps([_seg(d)]), encoding="utf-8")
    (tmp_path / "2026-09-12").mkdir()            # 只有目录、没有段落文件
    (tmp_path / "_tmp").mkdir()                  # 壳的临时目录，不是日期
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)

    assert J.days(user="tester") == ["2026-09-14", "2026-09-11", "2026-09-04"]


# —— P52：「有记录」= 有活的段 / 有日报，**不是「有 segments.json」** ——————————
#
# 复现（`$S/p52/repro_tomb.py`，素材是 `journey_fixture.py` 的 `synthetic` 档）：
# 把一天的段**逐条**走 `DELETE /segment` 删光之后，盘上剩的是一串墓碑，
# `segments.json` 还在 → 那一天还留在翻天列表里，翻过去是「这一天没有记录」，
# 而「删掉这一天」因为 `segs` 是空的本来就置灰 —— **既看不到也删不掉**，
# 正是 `days()` 自己的 docstring 承诺要避免的那件事。

def test_段被逐条删光只剩墓碑的那一天不再算有记录(tmp_path, monkeypatch):
    from app.routers import journey as J

    (tmp_path / "2026-09-14").mkdir()
    (tmp_path / "2026-09-14" / "segments.json").write_text(json.dumps(
        [{"start": "2026-09-14T09:00:00Z", "end": "2026-09-14T09:30:00Z",
          "app": "", "title": "", "desc": "", "deleted": True, "n": 0}] * 3), encoding="utf-8")
    (tmp_path / "2026-09-11").mkdir()
    (tmp_path / "2026-09-11" / "segments.json").write_text(json.dumps([_seg("2026-09-11")]),
                                                           encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)

    assert J.days(user="tester") == ["2026-09-11"]


def test_一条活的段就够_墓碑混在里面照样算有记录(tmp_path, monkeypatch):
    """反面：**别把「删过几段」也读成「整天没了」**（误报比漏报更糟）。"""
    from app.routers import journey as J

    (tmp_path / "2026-09-14").mkdir()
    (tmp_path / "2026-09-14" / "segments.json").write_text(json.dumps(
        [{"start": "x", "end": "x", "app": "", "title": "", "deleted": True, "n": 0},
         _seg("2026-09-14")]), encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)

    assert J.days(user="tester") == ["2026-09-14"]


def test_段全删光但日报还在的那一天要留着_否则那份日报被藏起来了(tmp_path, monkeypatch):
    """`JourneyPage` 对 `day?.report` 单独画一张卡：段一条不剩、日报还在的那一天，
    页面上照样有东西看。把它从列表里摘掉 = 把那份日报藏了，也删不掉了。"""
    from app.routers import journey as J

    d = tmp_path / "2026-09-14"
    d.mkdir()
    (d / "segments.json").write_text(json.dumps(
        [{"start": "x", "end": "x", "app": "", "title": "", "deleted": True, "n": 0}]),
        encoding="utf-8")
    (d / "report.json").write_text(json.dumps({"report": "## 推进了什么\n- 写了 P52\n"}),
                                   encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)

    assert J.days(user="tester") == ["2026-09-14"]


# —— P52：**文件删不掉时，记忆一条都不许动** ——————————————————————
#
# 走查里用只读目录（`chmod 500`）摆出来的（P50「留给下一批」③ 结案）：
# 后端确实吵了——toast 逐字「没删成 2026-09-19，这一天还在：这一天没删干净，
# 下面这些删不掉：… Permission denied」，盘上那一天原封不动。
# 顺手读出来的第二件事才是这条闸守的：原来 `delete_day` **先删记忆再删文件**，
# 于是失败那一路「这一天还在」是真的，而那些句子**已经没了**——
# 用户以为什么都没发生，实际上知识库被删了一半。

def test_这一天删不掉时_抽进知识库的记忆一条都不许动(tmp_path, monkeypatch):
    import os
    import stat

    from fastapi import HTTPException

    from app.routers import journey as J

    day = tmp_path / "2026-09-14"
    day.mkdir()
    (day / "segments.json").write_text(json.dumps([
        {"start": "2026-09-14T01:00:00Z", "end": "2026-09-14T02:00:00Z", "app": "A",
         "desc": "一", "session": "screen-20260914-000"},
    ], ensure_ascii=False), encoding="utf-8")
    forgot: list[str] = []
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)
    monkeypatch.setattr(J, "UserMemory", lambda user: type(
        "M", (), {"remove_sessions": lambda self, s: (forgot.append(s), 3)[1]})())

    os.chmod(day, stat.S_IRUSR | stat.S_IXUSR)            # r-x：读得进来，删不掉
    try:
        with pytest.raises(HTTPException) as e:
            J.delete_day(date="2026-09-14", user="tester")
    finally:
        os.chmod(day, stat.S_IRWXU)

    assert e.value.status_code == 500
    assert "这一天没删干净" in str(e.value.detail)
    assert (day / "segments.json").is_file()              # 盘上原封不动
    assert forgot == []                                   # **记忆一条都没动**


def test_真删掉了才轮到删记忆(tmp_path, monkeypatch):
    """反面：正常那一路一个字没变——文件没了，记忆跟着没（§1 ⑤ 那条承诺）。"""
    from app.routers import journey as J

    day = tmp_path / "2026-09-14"
    day.mkdir()
    (day / "segments.json").write_text(json.dumps([
        {"start": "2026-09-14T01:00:00Z", "end": "2026-09-14T02:00:00Z", "app": "A",
         "desc": "一", "session": "screen-20260914-000"},
    ], ensure_ascii=False), encoding="utf-8")
    forgot: list[str] = []
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)
    monkeypatch.setattr(J, "UserMemory", lambda user: type(
        "M", (), {"remove_sessions": lambda self, s: (forgot.append(s), 3)[1]})())

    out = J.delete_day(date="2026-09-14", user="tester")
    assert out.removed_facts == 3
    assert forgot == ["screen-20260914-000"]
    assert not day.exists()


def test_空的那一天也不算有记录_不管是谁写出来的(tmp_path, monkeypatch):
    """P20 #12 修的是**写的那一侧**（catch-up 不再落空文件）。这一条守**读的那一侧**：
    不管哪条路写出一个 `[]`，翻天都不该走进去。两道各守一半，缺一个就会再回来一次。"""
    from app.routers import journey as J

    (tmp_path / "2026-09-19").mkdir()
    (tmp_path / "2026-09-19" / "segments.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)

    assert J.days(user="tester") == []


def test_没有任何记录时列表是空的不是报错(tmp_path, monkeypatch):
    from app.routers import journey as J

    monkeypatch.setattr(J, "journey_root", lambda: tmp_path / "还不存在")
    assert J.days(user="tester") == []


def test_黑名单只能往上加_内置那份拆不掉(tmp_path, monkeypatch):
    """「把密码管理器加回记录范围」不是一个该给的选项（§1 ②）。"""
    from app.routers import journey as J
    from app.routers.schemas import JourneyDenyIn

    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)
    out = J.put_deny(JourneyDenyIn(apps=["Signal", "Signal", " "], words=["体检报告"]), user="t")
    assert out.apps == ["Signal"] and out.words == ["体检报告"]      # 去重、去空
    assert "1Password" in out.builtin_apps and "密码" in out.builtin_words

    # 再读一遍要拿得回来；内置那份照样在
    again = J.get_deny(user="t")
    assert again.apps == ["Signal"]
    assert again.builtin_apps == out.builtin_apps

    # 清空只清自己加的
    empty = J.put_deny(JourneyDenyIn(), user="t")
    assert empty.apps == [] and empty.builtin_apps


def test_黑名单条数和长度封顶(tmp_path, monkeypatch):
    """名单要逐条比对，几千条会拖慢每一次采样。"""
    from app.routers import journey as J
    from app.routers.schemas import JourneyDenyIn

    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)
    out = J.put_deny(JourneyDenyIn(apps=[f"App{i}" for i in range(500)],
                                   words=["x" * 300]), user="t")
    assert len(out.apps) == J.DENY_MAX
    assert len(out.words[0]) == J.DENY_LEN


def test_黑名单文件坏了当没加过_不是报错(tmp_path, monkeypatch):
    """壳和界面共用这个文件，手改坏了不该让整页打不开。"""
    from app.routers import journey as J

    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)
    (tmp_path / "deny.json").write_text("{坏的", encoding="utf-8")
    assert J.get_deny(user="t").apps == []


# ——— 描述收成一句（第 749 轮，量了真实产出之后加的）————————————————
#
# 旧提示词第一句是「你只回一句中文，说**这个人**在做什么」，模型照着起头：
# 实测 14 条描述 **14 条**都以「这个人在 / 人在 / 他在 …」开头。那是一行里
# 视线第一落点上的十几个字，每行都一样，真正的新东西被挤到末尾。
# 而且这些描述会**原样变成知识库里的事实**——十四条事实共享同一串前缀，
# 召回时那些 n-gram 命中一切（第 747 轮刚在查询侧修过口水词）。
#
# 提示词那一半改完当场 A/B 过（同一张截图，旧 200 字 → 新 32 字）；
# 下面测的是**提示词管不住时代码接住的那一半**。

def test_去掉开头的主语():
    from app.routers.journey import tighten
    for raw in ("这个人在改 capture.ts 的落盘逻辑",
                "人在改 capture.ts 的落盘逻辑",
                "他正在改 capture.ts 的落盘逻辑",
                "用户在改 capture.ts 的落盘逻辑"):
        assert tighten(raw) == "改 capture.ts 的落盘逻辑"


def test_去完主语得还是句人话_不然不去():
    """「他在忙」削成「忙」比原样更糟。判据宁可窄一点。"""
    from app.routers.journey import tighten
    assert tighten("他在忙") == "他在忙"


def test_只留第一句():
    from app.routers.journey import tighten
    assert tighten("改了 flush 的落盘逻辑。另外顺手清了无主截图。") == "改了 flush 的落盘逻辑。"


def test_不在句子中间砍():
    """截一半比长更难读。模型写的常常是一整个逗号连成的长句——
    这种就原样留着，长度那一半靠提示词，不靠切。"""
    from app.routers.journey import tighten
    long = "改 capture.ts 的 flush，加 keepBackendFields，再清掉无主截图"
    assert tighten(long) == long


def test_没有主语的原样不动():
    from app.routers.journey import tighten
    assert tighten("改 capture.ts 的落盘逻辑") == "改 capture.ts 的落盘逻辑"
    assert tighten("") == ""


# ——— 日报喂进去的是「块」不是「段」（第 753 轮）————————————————————
#
# 同一件事以八条近似重复的样子进提示词，模型看到的是「这件事出现了八次」——
# 这一天真正推进了什么反而被那八遍压下去。第 752 轮在时间轴上做的是同一件事。
# 判据本身跟前端那份逐位对拍（`frontend/scripts/check-journey-merge.mts`），
# 这里只测**后端这一侧真的用上了**。

def test_日报把连着说同一件事的段并成一块(tmp_path, monkeypatch):
    from app.journey import group_runs
    d = "2026-09-17"
    a = "查看 PRD.md#70-81 的日本 Android 崩溃分析"
    segs = [
        {"start": f"{d}T07:00:00Z", "end": f"{d}T07:05:00Z", "app": "Code", "desc": a},
        {"start": f"{d}T07:05:00Z", "end": f"{d}T07:11:00Z", "app": "Code",
         "desc": "阅读 PRD.md#70-81 的日本 Android 崩溃分析结论"},
        {"start": f"{d}T07:11:00Z", "end": f"{d}T07:20:00Z", "app": "Code", "desc": a},
        {"start": f"{d}T07:20:00Z", "end": f"{d}T07:25:00Z", "app": "Code",
         "desc": "改需求文档中 [项目名称] 的背景与问题模板"},
    ]
    runs = group_runs(segs)
    assert [len(r["segs"]) for r in runs] == [3, 1]
    assert runs[0]["start"].endswith("07:00:00Z") and runs[0]["end"].endswith("07:20:00Z")


def test_块上取信息最多的那一句():
    """它们说的是同一件事，具体的文件名 / 报错往往只出现在其中一条里。"""
    from app.journey import group_runs
    d = "2026-09-17"
    runs = group_runs([
        {"start": f"{d}T07:00:00Z", "end": f"{d}T07:05:00Z", "app": "Code",
         "desc": "查看 PRD.md 的崩溃分析"},
        {"start": f"{d}T07:05:00Z", "end": f"{d}T07:09:00Z", "app": "Code",
         "desc": "查看 PRD.md 的崩溃分析，Crashlytics 匹配到 4 条"},
    ])
    assert len(runs) == 1
    assert "Crashlytics" in runs[0]["desc"]


def test_时间戳读不出来就不并():
    """宁可多出一行，也不要把两段隔了很久的事并成一块——并错了用户看不出来。"""
    from app.journey import group_runs
    a = "查看 PRD.md#70-81 的日本 Android 崩溃分析"
    runs = group_runs([{"start": "坏的", "end": "坏的", "app": "Code", "desc": a},
                       {"start": "也坏", "end": "也坏", "app": "Code", "desc": a}])
    assert len(runs) == 2


# ---------------------------------------------------------------- P20（第 778 轮）走查修的几条

def _local(iso: str) -> str:
    from app.journey.stats import _at
    return _at(iso).astimezone().strftime("%H:%M")


def test_日报喂给模型的时刻是本地时间_不是UTC(tmp_path, monkeypatch):
    """读真实日报读出来的：09-18 写着「凌晨浏览了 Amazon…」，那一段其实是 18:12。
    喂进去的行是 `start[11:16]` 切的 UTC，而「时间去哪了」和页面时间轴都是本地钟。"""
    from app.routers import journey as J

    day = tmp_path / "2026-09-18"
    day.mkdir()
    (day / "segments.json").write_text(json.dumps([
        {"start": "2026-09-18T10:12:18Z", "end": "2026-09-18T10:25:48Z", "app": "Feishu",
         "desc": "浏览 Amazon 搜索 memoket 的 Gem Wearable AI Voice Recorder"},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)
    seen: dict = {}

    async def fake_complete(messages, **kw):
        seen["user"] = messages[-1]["content"]
        return "## 计划外的\n- 浏览 Amazon 的 Gem Wearable\n"

    monkeypatch.setattr(J.llm, "complete", fake_complete)
    monkeypatch.setattr(J.prompts, "compose_system", lambda base, *a, **k: base)
    asyncio.run(J.report(date="2026-09-18", user="tester"))
    want = f"{_local('2026-09-18T10:12:18Z')}–{_local('2026-09-18T10:25:48Z')} Feishu"
    assert want in seen["user"], seen["user"]
    # 东八区下这一行是 18:12–18:25；不管跑测试的机器在哪个时区，都不该再出现 UTC 的 10:12
    if _local("2026-09-18T10:12:18Z") != "10:12":
        assert "10:12–10:25" not in seen["user"]


def test_看图失败先把这一批做完的存下来再报错(tmp_path, monkeypatch):
    """原来 `raise` 在 `_save` 之前：前面几段的大图已经删了、描述却没落盘，
    下一轮只能标成「没有截图」——看图服务一抖，做完的那几段就丢了。"""
    from app.editor.vision import VisionError
    from app.routers import journey as J

    day = tmp_path / "2026-09-14"
    (day / "shots").mkdir(parents=True)
    a, b = day / "shots" / "001.png", day / "shots" / "002.png"
    a.write_bytes(b"PNG"), b.write_bytes(b"PNG")
    (day / "segments.json").write_text(json.dumps([
        {"start": "2026-09-14T01:00:00Z", "end": "2026-09-14T01:10:00Z", "app": "Code", "frames": [str(a)]},
        {"start": "2026-09-14T01:10:00Z", "end": "2026-09-14T01:20:00Z", "app": "Code", "frames": [str(b)]},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)
    calls = {"n": 0}

    async def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return "答案：在 VS Code 里改 journey.py 的 catch_up"
        raise VisionError("看图服务 502")

    monkeypatch.setattr(J, "ask_image", flaky)
    monkeypatch.setattr(J, "UserMemory", lambda user: type(
        "M", (), {"remember": lambda *a, **k: None, "remove_sessions": lambda *a: 0})())

    out = asyncio.run(J.catch_up(date="2026-09-14", limit=5, user="tester"))
    assert out.described == 1 and out.left == 1
    saved = json.loads((day / "segments.json").read_text())
    assert saved[0]["desc"].startswith("在 VS Code"), "第一段的描述必须落盘"
    assert not a.exists() and b.exists(), "只删描述做完那一段的大图"

    # 一段都没做成才是 502——而且这一次就该报出来，不是吞掉
    with pytest.raises(HTTPException) as e:
        asyncio.run(J.catch_up(date="2026-09-14", limit=5, user="tester"))
    assert e.value.status_code == 502 and "看图失败" in e.value.detail
    assert json.loads((day / "segments.json").read_text())[0]["desc"].startswith("在 VS Code")


def test_入库标题用本地时刻(tmp_path, monkeypatch):
    """这个标题会出现在知识库「最近摄入」里——UTC 的 16:00 其实是半夜。"""
    from app.routers import journey as J

    day = tmp_path / "2026-09-17"
    (day / "shots").mkdir(parents=True)
    big = day / "shots" / "001.png"
    big.write_bytes(b"PNG")
    (day / "segments.json").write_text(json.dumps([
        {"start": "2026-09-16T16:00:14Z", "end": "2026-09-16T16:05:00Z", "app": "Code", "frames": [str(big)]},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)
    got: dict = {}

    async def fake_img(*a, **kw):
        return "答案：在 VS Code 里改 journey.py 的 catch_up"

    class M:
        def remember(self, msgs, **kw):
            got.update(kw)

    monkeypatch.setattr(J, "ask_image", fake_img)
    monkeypatch.setattr(J, "UserMemory", lambda user: M())
    asyncio.run(J.catch_up(date="2026-09-17", limit=5, user="tester"))
    assert got["title"] == f"{_local('2026-09-16T16:00:14Z')}–{_local('2026-09-16T16:05:00Z')} · Code"


def test_一段都没有的一天不落一个空文件(tmp_path, monkeypatch):
    """实拍 09-19 零点过后 catch-up 写出一个 `[]`，`days()` 就把它数成有记录的一天。"""
    from app.routers import journey as J

    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)
    out = asyncio.run(J.catch_up(date="2026-09-19", limit=5, user="tester"))
    assert out.described == 0 and out.left == 0
    assert not (tmp_path / "2026-09-19").exists()
    assert J.days(user="tester") == []


# ---------------------------------------------------------------- P50（第 793 轮）
#
# 「描述这 N 段」那个死胡同（P20 清单 #5）**从另一扇门原样回来了**，
# 而且它自己还会不断造出新的：`catch_up` 判定「没有截图」时只写了 `skip`，
# 那条指向不存在的文件的路径留在 `frames` 里 → `has_frame` 照样是 true →
# 页面 `describable()` 照样把它数进「描述这 N 段」→ 点下去只回
# 「没有要描述的了」，**点多少次都一样**。
#
# 真实数据上实拍到的量（`~/Library/Application Support/.../journey`，只读）：
# 09-16 **37 段**、09-17 **71 段**、09-18 **2 段**正是这个形状。


def test_判成没有截图时_那条悬空的大图路径也要抹掉(client, tmp_path):
    """真因那一条：`skip` 写了、`frames` 没清，`has_frame` 于是一直在骗人。"""
    _day(tmp_path, [{"start": "2026-09-14T09:00:00", "end": "2026-09-14T09:30:00",
                     "app": "Code", "title": "", "n": 12,
                     "frames": [str(tmp_path / "早就没了.png")]}])
    r = client.post("/api/journey/catch-up?date=2026-09-14").json()
    assert r["skipped"] == 1 and r["described"] == 0

    disk = json.loads((tmp_path / "journey" / "2026-09-14" / "segments.json").read_text())
    assert disk[0]["skip"] == "没有截图"
    assert disk[0]["frames"] == []                  # ← 这一行就是判据本身

    seg = client.get("/api/journey/day?date=2026-09-14").json()["segments"][0]
    assert seg["has_frame"] is False                # 页面按它数「描述这 N 段」
    assert seg["skip"] == "没有截图"


def test_接口要把_skip_交给界面_别让它拿_has_frame_去猜(client, tmp_path):
    """**判据守来源**：补不了是后端知道的事实，不该由界面拿一个替身推出来。

    这里故意摆一个**图真的在、却已经被判出局**的段：只看 `has_frame` 的话
    它是「等着描述」，只有 `skip` 说得出真话。
    """
    day = _today()
    frame = tmp_path / "在的.png"
    frame.write_bytes(b"\x89PNG\r\n\x1a\n")
    _day(tmp_path, [{"start": f"{day}T09:00:00", "end": f"{day}T09:30:00",
                     "app": "Code", "title": "", "n": 12,
                     "frames": [str(frame)], "skip": "没说出具体的东西"}], day)
    seg = client.get(f"/api/journey/day?date={day}").json()["segments"][0]
    assert seg["has_frame"] is True and seg["desc"] == ""
    assert seg["skip"] == "没说出具体的东西"


def test_没被判出局的段_skip_是空串(client, tmp_path):
    """反面：**别把「还没轮到它」也说成补不了**（误报比漏报更糟）。"""
    day = _today()
    _day(tmp_path, [{"start": f"{day}T09:00:00", "end": f"{day}T09:30:00",
                     "app": "Code", "title": "", "n": 12, "frames": ["/还在/的.png"]}], day)
    seg = client.get(f"/api/journey/day?date={day}").json()["segments"][0]
    assert seg["skip"] == ""


def test_已经判出局的段_再点多少次描述都不会被重新数进去(client, tmp_path):
    """死胡同那个循环本身：连点两次，第二次盘上不该再多出任何变化。"""
    _day(tmp_path, [{"start": "2026-09-14T09:00:00", "end": "2026-09-14T09:30:00",
                     "app": "Code", "title": "", "n": 12,
                     "frames": [str(tmp_path / "没了.png")]}])
    first = client.post("/api/journey/catch-up?date=2026-09-14").json()
    before = (tmp_path / "journey" / "2026-09-14" / "segments.json").read_text()
    second = client.post("/api/journey/catch-up?date=2026-09-14").json()
    after = (tmp_path / "journey" / "2026-09-14" / "segments.json").read_text()
    assert first["skipped"] == 1 and second["skipped"] == 0
    assert before == after
