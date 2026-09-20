"""P56 #2：`p7_skeleton_dryrun.py --include-non-user` 那一档。

**为什么需要这一档**（P53 #8 那条建议本身报错了）：P25-apply 之后真库里只剩
`shot-demo/f5e34e385aac`（血缘 `fixture`）和 `terrence/df3b4f7e987d`（血缘 `script`）
两篇半句骨架，而 `scan()` 按 `corpus_lineage` 只留 `user` 血缘——
**`--apply --yes` 跑完会改 0 篇**，而当时的提示行逐字写着「要修：加 --apply --yes」。
一条跑完什么都不会变的命令被写进报告，比没有命令更坏。

所以这里钉三条：

1. 默认那一档**一篇都不并进来**（写笔记库是用户的决定，这条不许被开关带歪）；
2. `--include-non-user` 之后它们才进待修列表，**而且血缘判词跟着一起打出来**
   （「哪一篇本来会被跳过」不该因为加了个开关就看不见）；
3. 没有 `--apply` 时**一个字都不写**：三把钥匙（`--include-non-user` + `--apply` + `--yes`）
   少一把就只列不改，指纹逐格不动。

P56 #4：「删不掉」那条 toast 的长度（`routers/journey.delete_day`）。

P52 走查实拍的那条是 **5 行绝对路径、每行 100+ 字符**，而五行的前 90 个字符逐字相同——
摊开的是公共前缀，不是信息。**收法不是「详情看日志」**：P21 立的规矩是「删不掉要吵」
（`shutil.rmtree(ignore_errors=True)` 那种安静失败正是它修的），把清单挪进日志
等于把那次修的问题原样放回去。所以这里钉的是**两头都不许塌**：
一个都不许少（5 个文件报 5 行），公共前缀只许出现一次。
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

dryrun = pytest.importorskip("p7_skeleton_dryrun")

HALF = "已写：以 5G 切换 2.4G、结构增厚 0.4mm、电池从 150mAh 扩至 200mAh 为变更起点，指出三项改动"
WHOLE = "已写：把三项硬件改动摊平成一条时间线。"


def _db(tmp_path: Path) -> Path:
    """一个最小的笔记库：一篇 user 血缘（骨架完整）、一篇夹具用户（骨架半句）。

    表只建 `fingerprint` / `load_notes` 真读的那几张——`writing_sections` /
    `writing_plans` 是 `load_lineage` 的 JOIN 要的，空表就够。
    """
    p = tmp_path / "notes.sqlite3"
    conn = sqlite3.connect(p)
    conn.executescript("""
        CREATE TABLE notes (id TEXT PRIMARY KEY, user_id TEXT, title TEXT,
                            content TEXT, spine TEXT, beats TEXT, updated_at TEXT);
        CREATE TABLE note_revisions (id TEXT PRIMARY KEY, created_at TEXT);
        CREATE TABLE writing_sections (note_id TEXT, plan_id TEXT);
        CREATE TABLE writing_plans (id TEXT PRIMARY KEY, goal TEXT, parent_note_id TEXT);
    """)
    conn.execute("INSERT INTO notes VALUES (?,?,?,?,?,?,?)",
                 ("realnote", "terrence", "真的一篇", "正文" * 50, "脊", json.dumps([WHOLE]),
                  "2026-09-16T02:53:27+00:00"))
    conn.execute("INSERT INTO notes VALUES (?,?,?,?,?,?,?)",
                 ("demonote", "shot-demo", "4 月 10 日产品周会", "演示" * 50, "脊",
                  json.dumps([HALF]), "2026-09-16T02:53:27+00:00"))
    conn.commit()
    conn.close()
    return p


def _run(monkeypatch, capsys, db: Path, *flags: str) -> str:
    monkeypatch.setattr(sys, "argv", ["p7_skeleton_dryrun.py", "--db", str(db), *flags])
    assert dryrun.main() == 0
    return capsys.readouterr().out


def test_半句那条判据认得出这条60字的节拍():
    """先钉判据本身：`HALF` 必须真的是「长度正好 60 且不以句读收尾」那一档，
    不然下面三条测的是一个不成立的前提。"""
    assert len(HALF) == 60 and dryrun.half_sentence_beats([HALF]) == [1]
    assert dryrun.half_sentence_beats([WHOLE]) == []


def test_默认那一档一篇都不并进来(tmp_path, monkeypatch, capsys):
    db = _db(tmp_path)
    out = _run(monkeypatch, capsys, db)
    assert "半句骨架：0 篇（另有 1 篇非 user 血缘，不动）" in out
    assert "跳过（非 user 血缘）shot-demo/demonote" in out
    # **提示行不许报一条跑完改 0 篇的命令**——这正是 P53 #8 那条建议出错的地方
    assert "--include-non-user --apply --yes" in out


def test_加了开关才进待修列表而且血缘判词跟着打出来(tmp_path, monkeypatch, capsys):
    db = _db(tmp_path)
    out = _run(monkeypatch, capsys, db, "--include-non-user")
    assert "半句骨架：1 篇" in out and "--include-non-user：非 user 血缘的也算进来了" in out
    assert "shot-demo/demonote" in out
    # 血缘不许在并列之后消失
    assert "血缘 fixture" in out and "截图演示夹具" in out
    assert "跳过（非 user 血缘）" not in out


def test_没有apply时一个字都不写(tmp_path, monkeypatch, capsys):
    """三把钥匙少一把就只列不改：跑完 `notes` 的指纹**逐格**跟跑前相同。"""
    db = _db(tmp_path)
    before = dryrun.db_guard.fingerprint(db)
    _run(monkeypatch, capsys, db, "--include-non-user")
    after = dryrun.db_guard.fingerprint(db)
    assert before.diff(after) == []
    assert (before.rows, before.latest, before.chars, before.digests) == (
        after.rows, after.latest, after.chars, after.digests)
    # 骨架那两列也逐字没动（`diff` 只看正文那几样，spine/beats 不在里头——
    # 这一条是专门补那个盲区的）
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT beats FROM notes WHERE id='demonote'").fetchone()[0] == json.dumps([HALF])
    conn.close()


def test_apply没带yes时也不写(tmp_path, monkeypatch, capsys):
    db = _db(tmp_path)
    monkeypatch.setattr(sys, "argv", ["p7_skeleton_dryrun.py", "--db", str(db),
                                      "--include-non-user", "--apply"])
    assert dryrun.main() == 2
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT beats FROM notes WHERE id='demonote'").fetchone()[0] == json.dumps([HALF])
    conn.close()


# ---------------------------------------- P56 #4：那条 toast 的长度 -------

@pytest.mark.skipif(os.geteuid() == 0, reason="root 删得掉任何东西")
def test_删不掉那条消息一个文件都不许少而公共前缀只说一次(tmp_path, monkeypatch):
    """P52 实拍的形状：5 行绝对路径，前 90 个字符逐字相同。

    两头都钉：**5 个文件报 5 行**（不许收成「详情看日志」——那是把 P21 修的
    问题放回去），**目录只出现一次**（不许每行再摊一遍）。
    """
    from fastapi import HTTPException

    from app.routers import journey as J

    day = tmp_path / "2026-09-14"
    thumbs = day / "thumbs"
    thumbs.mkdir(parents=True)
    for i in range(5):
        (thumbs / f"shot-{i}.png").write_bytes(b"x")
    (day / "segments.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)
    monkeypatch.setattr(J, "UserMemory", lambda user: type("M", (), {})())

    thumbs.chmod(stat.S_IRUSR | stat.S_IXUSR)             # r-x：列得出来，删不掉
    try:
        with pytest.raises(HTTPException) as e:
            J.delete_day(date="2026-09-14", user="tester")
    finally:
        thumbs.chmod(stat.S_IRWXU)

    detail = str(e.value.detail)
    head, *body = detail.split("\n")
    # ① 一个都不许少：5 张缩略图 + `thumbs` + 这一天的目录本身 = 7 行，
    #    而且每一张都说得出是哪一张
    assert len(body) == 7, body
    for i in range(5):
        assert any(f"thumbs/shot-{i}.png" in ln for ln in body), (i, body)
    assert any(ln.startswith("thumbs：") for ln in body), body
    assert any(ln.startswith("这一天的目录本身：") for ln in body), body
    assert "这 7 个删不掉" in head, head
    # ② 公共前缀只说一次：抬头里有绝对路径，正文里**一行都没有**
    #    （目录自己那一行没有结尾 `/`，最早那版就漏在这里）
    assert str(day) in head
    assert all(str(day) not in ln for ln in body), body
    # ③ 收完每一行都短得能读（P52 实拍是 100+）
    assert max(len(ln) for ln in body) < 60, body


# ------------------------- P56 #5⑤：`emptyday` 这个档摆得出哪一屏 -------

def test_emptyday_这个档必须让days非空_否则摆出来的是知情屏(tmp_path, monkeypatch):
    """P52「留给下一批」⑤：`emptyday` 原来只造「今天 = `[]`」。

    P32 的 A2 之后 `[]` 不算「有记录的一天」，于是整个库一天都没有 →
    `days()` 空 → 前端 `state === 'off' && known.length === 0` 走**知情选择屏**
    （`JourneyPage.tsx:377`），而这个档要摆的是它后面那一屏
    「今天还没有记录——现在没在记录…」（`:579`）。

    所以这条闸判的是**两头**：昨天得有记录（`days()` 非空），今天得是空的
    （`segs.length === 0` 那一支）。少哪一头都摆不出那句话。
    """
    import subprocess
    from datetime import date, timedelta

    from app.routers import journey as J

    scripts = Path(__file__).resolve().parent.parent / "scripts"
    dest = Path("/private/tmp/claude-501") / f"p56-emptyday-{os.getpid()}"
    try:
        r = subprocess.run([sys.executable, str(scripts / "journey_fixture.py"),
                            str(dest), "--variant", "emptyday"],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        monkeypatch.setenv("MEMOKET_JOURNEY_DIR", str(dest / "journey"))
        today = date.today().isoformat()
        yday = (date.today() - timedelta(days=1)).isoformat()
        known = J.days(user="tester")
        assert known == [yday], known          # 非空 → 不退回知情屏
        assert today not in known              # 今天仍然不算「有记录的一天」
        assert J._load(today) == []            # 今天确实是 `[]`
        assert not J._has_records(today)
    finally:
        import shutil
        shutil.rmtree(dest, ignore_errors=True)
