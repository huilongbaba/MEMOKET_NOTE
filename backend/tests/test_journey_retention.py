"""屏幕活动**留多久**（`app/journey/retention.py`，第 779 轮 / P21）。

在这之前这个功能**没有保留期**：`FRAME_KEEP_DAYS=3` 只管大图，段落描述和
缩略图一天都不删——用户机器上无限期堆着一份「他每天在屏幕上干了什么」的
文字记录，而那一屏知情选择上一个字都没提。

这里钉住的是**每一条都能让「留 30 天」变成假话**的性质：
  · 到期的整天连同**知识库里那几条记忆**一起删（只删文件 = 句子还在、还会被引用）
  · 缩略图到期要**连段落上的 `thumb` 一起抹**（只删文件 = 一页 404 的图）
  · 大图的过期清理不能只在「打开那一天」时才跑（实测 09-16 的 78MB 就这么留着）
  · **删不掉要吵**：`rmtree(ignore_errors=True)` 留下半个目录还回一句「删好了」
  · 今天那份**一个字都不许碰**——壳正在往里写
"""

from __future__ import annotations

import json
import os
import stat
from datetime import date
from pathlib import Path

import pytest

from app.journey import retention as keep


# ——— 判据（纯函数）———————————————————————————————————————————————

def test_默认不是一直留着():
    """**默认值决定了绝大多数人的实际隐私状态。**「一直留着」是一个选项，不是默认。"""
    p = keep.Policy()
    assert p.segment_days == 30 and p.thumb_days == 7
    assert keep.FOREVER in keep.SEGMENT_CHOICES and keep.FOREVER in keep.THUMB_CHOICES
    assert p.segment_days != keep.FOREVER and p.thumb_days != keep.FOREVER
    # 缩略图（屏幕长什么样）比段落（一句话描述）留得短
    assert p.thumb_days < p.segment_days


def test_到期的判据_今天和未来一律不碰():
    """今天那份壳正在往里写；时钟被调回去过时，「未来的日子」也不能删。"""
    today = date(2026, 9, 19)
    p = keep.Policy(segment_days=7, thumb_days=3)
    assert keep.due("2026-09-19", today, p) == (False, False)
    assert keep.due("2026-09-20", today, p) == (False, False)
    assert keep.due("2026-09-18", today, p) == (False, False)      # 1 天
    assert keep.due("2026-09-16", today, p) == (False, True)       # 3 天：只删缩略图
    assert keep.due("2026-09-12", today, p) == (True, False)       # 7 天：整天删
    assert keep.due("不是日期", today, p) == (False, False)
    # **第二道闸**：就算保留期是个负数（配置文件被改坏、以后多一档写错了），
    # 今天这一份也不许删——`read_policy` 那道闸之外，判据自己也不信这个数。
    assert keep.due("2026-09-19", today, keep.Policy(segment_days=-1, thumb_days=-1)) \
        == (False, False)


def test_一直留着就什么都不删():
    today = date(2026, 9, 19)
    p = keep.Policy(segment_days=keep.FOREVER, thumb_days=keep.FOREVER)
    assert keep.due("2020-01-01", today, p) == (False, False)


def test_坏的保留期退回默认_不是退回最宽松的那一档(tmp_path):
    """`clamp` 会把 `-1` 夹成 0 = 「一直留着」——**把坏数据解释成最宽松的一档**，
    方向正好反了。所以是「不认就退回默认」。"""
    (tmp_path / keep.POLICY_FILE).write_text('{"segment_days": -1, "thumb_days": 9999}')
    p = keep.read_policy(tmp_path)
    assert p.segment_days == 30 and p.thumb_days == 7
    (tmp_path / keep.POLICY_FILE).write_text("这不是 json")
    assert keep.read_policy(tmp_path) == keep.Policy()
    # 没这个文件也是默认
    assert keep.read_policy(tmp_path / "没有这个目录") == keep.Policy()


def test_存下来的只认列表里的档(tmp_path):
    out = keep.write_policy(tmp_path, keep.Policy(segment_days=14, thumb_days=99))
    assert out.segment_days == 14 and out.thumb_days == 7
    assert json.loads((tmp_path / keep.POLICY_FILE).read_text()) == \
        {"segment_days": 14, "thumb_days": 7}


# ——— 扫盘 ————————————————————————————————————————————————————

def _mkday(root: Path, day: str, *, thumbs=2, frames=1, described=True, report=True) -> Path:
    d = root / day
    (d / "thumbs").mkdir(parents=True)
    (d / "shots").mkdir()
    segs = []
    for i in range(thumbs):
        t = d / "thumbs" / f"{i:03d}.jpg"
        t.write_bytes(b"JPG")
        f = d / "shots" / f"{i:03d}.png"
        seg = {"start": f"{day}T0{i}:00:00Z", "end": f"{day}T0{i}:30:00Z", "app": "Code",
               "title": "", "n": 20, "thumb": str(t), "frames": []}
        if i < frames:
            f.write_bytes(b"PNG")
            seg["frames"] = [str(f)]
        if described:
            seg["desc"] = f"改 capture.ts 的第 {i} 处"
            seg["session"] = f"screen-{day.replace('-', '')}-{i:03d}"
        segs.append(seg)
    (d / "segments.json").write_text(json.dumps(segs, ensure_ascii=False), encoding="utf-8")
    if report:
        (d / "report.json").write_text('{"report": "# 今天\\n", "report_segments": 2}')
    return d


def _io(root: Path):
    def load(day: str) -> list[dict]:
        try:
            return json.loads((root / day / "segments.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    def save(day: str, segs: list[dict]) -> None:
        (root / day / "segments.json").write_text(json.dumps(segs, ensure_ascii=False),
                                                  encoding="utf-8")
    return load, save


def test_过期的一天连它抽进知识库的记忆一起删(tmp_path):
    """**只删文件不删事实的话，「这些记录只留 30 天」就是假话**——
    那些句子还在知识库里，还会被召回、被写进用户的文稿（§1 ⑤）。"""
    old = _mkday(tmp_path, "2026-09-01")
    young = _mkday(tmp_path, "2026-09-18")
    forgotten: list[str] = []
    load, save = _io(tmp_path)

    rep = keep.sweep(tmp_path, keep.Policy(segment_days=7, thumb_days=30), date(2026, 9, 19),
                     load=load, save=save,
                     forget=lambda s: (forgotten.append(s), 2)[1])

    assert not old.exists() and young.exists()
    assert rep.days_removed == ["2026-09-01"]
    assert forgotten == ["screen-20260901-000", "screen-20260901-001"]
    assert rep.facts_removed == 4
    assert rep.failures == []


def test_缩略图过期要连段落上的_thumb_一起抹(tmp_path):
    """只删文件不改段落的话 `has_thumb` 还是 true，页面上每行挂一个 404 的
    `<img>`——看起来像坏了，而不是「过期了」。"""
    d = _mkday(tmp_path, "2026-09-10")
    load, save = _io(tmp_path)

    rep = keep.sweep(tmp_path, keep.Policy(segment_days=30, thumb_days=7), date(2026, 9, 19),
                     load=load, save=save)

    assert rep.thumbs_removed == 2 and rep.days_removed == []
    assert not (d / "thumbs").exists()
    segs = json.loads((d / "segments.json").read_text())
    assert [s["thumb"] for s in segs] == ["", ""]
    assert [s["desc"] for s in segs] == ["改 capture.ts 的第 0 处", "改 capture.ts 的第 1 处"]
    assert (d / "report.json").is_file(), "缩略图过期不该带走这一天的日报"


def test_缩略图指到目录外面就不删_但要说一声(tmp_path):
    """段落文件是壳写的。真被改过的话，这里就是一个「按路径删任意文件」的口子。"""
    d = _mkday(tmp_path, "2026-09-10", thumbs=1)
    outside = tmp_path / "别人的照片.jpg"
    outside.write_bytes(b"JPG")
    segs = json.loads((d / "segments.json").read_text())
    segs[0]["thumb"] = str(outside)
    (d / "segments.json").write_text(json.dumps(segs, ensure_ascii=False))
    load, save = _io(tmp_path)

    rep = keep.sweep(tmp_path, keep.Policy(segment_days=30, thumb_days=7), date(2026, 9, 19),
                     load=load, save=save)

    assert outside.exists()
    assert any("不在 2026-09-10 的目录里" in f for f in rep.failures)


def test_大图的过期清理不只在打开那一天时才跑(tmp_path):
    """原来 `_expire_frames` 只挂在 `GET /day` 上——**而没人会去翻三天前**。
    实测 09-16 那天的 78MB 大图就这么一直留着。"""
    d = _mkday(tmp_path, "2026-09-14", thumbs=2, frames=2, described=False)
    load, save = _io(tmp_path)
    big = d / "shots" / "000.png"
    assert big.exists()

    def expire(day: str, segs: list[dict]) -> int:
        n = 0
        for s in segs:
            for f in s.get("frames") or []:
                Path(f).unlink(missing_ok=True)
            if s.get("frames"):
                s["frames"] = []
                s["skip"] = "截图已过期"
                n += 1
        return n

    rep = keep.sweep(tmp_path, keep.Policy(segment_days=30, thumb_days=30), date(2026, 9, 19),
                     load=load, save=save, expire_frames=expire)

    assert rep.frames_removed == 2 and not big.exists()
    assert json.loads((d / "segments.json").read_text())[0]["skip"] == "截图已过期"


def test_今天那份一个字都不许碰(tmp_path):
    """壳正在往今天这一份里写。"""
    today = date(2026, 9, 19)
    d = _mkday(tmp_path, today.isoformat())
    load, save = _io(tmp_path)
    before = (d / "segments.json").read_text()

    rep = keep.sweep(tmp_path, keep.Policy(segment_days=7, thumb_days=1), today,
                     load=load, save=save)

    assert rep.days_removed == [] and rep.thumbs_removed == 0
    assert (d / "segments.json").read_text() == before
    assert (d / "thumbs" / "000.jpg").exists()


def test_不是日期的东西不碰(tmp_path):
    """`_tmp`（正在拍的那张原图）、`on`（开关）、`deny.json`（黑名单）都在同一层。"""
    (tmp_path / "_tmp").mkdir()
    (tmp_path / "_tmp" / "now.png").write_bytes(b"PNG")
    (tmp_path / "on").write_text("1")
    (tmp_path / "deny.json").write_text('{"apps": ["我们公司那个系统"]}')
    _mkday(tmp_path, "2026-09-01")
    load, save = _io(tmp_path)

    keep.sweep(tmp_path, keep.Policy(segment_days=7, thumb_days=1), date(2026, 9, 19),
               load=load, save=save)

    assert (tmp_path / "_tmp" / "now.png").exists()
    assert (tmp_path / "on").read_text() == "1"
    assert json.loads((tmp_path / "deny.json").read_text())["apps"] == ["我们公司那个系统"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root 删得掉任何东西")
def test_删不掉要吵_不许静默(tmp_path):
    """`shutil.rmtree(ignore_errors=True)` 会留下半个目录，而调用方拿到的是
    「成功」——用户按的是「删掉」。这个功能里「我以为删干净了」是最不能出的错。"""
    d = _mkday(tmp_path, "2026-09-01")
    (d / "thumbs").chmod(stat.S_IRUSR | stat.S_IXUSR)      # 只读目录：里面的删不掉
    load, save = _io(tmp_path)
    try:
        rep = keep.sweep(tmp_path, keep.Policy(segment_days=7, thumb_days=1), date(2026, 9, 19),
                         load=load, save=save)
        assert rep.failures, "删不掉却一句话不说 = 静默失败"
        # 删不掉的**文件**要报出来
        assert any(f.split("：")[0].endswith(".jpg") for f in rep.failures)
        # 删不掉的**目录**也要报出来（只报文件的话，「目录还在」这件事没人说）
        assert any(f.split("：")[0].endswith("/thumbs") for f in rep.failures)
        assert rep.days_removed == [], "没删干净就不能报告「这一天删掉了」"
        assert d.exists()
    finally:
        (d / "thumbs").chmod(stat.S_IRWXU)


def test_全部删掉_留下设置不留记录(tmp_path):
    """「把我记下来的都删掉」不等于「把我的设置也恢复出厂」。"""
    _mkday(tmp_path, "2026-09-01")
    _mkday(tmp_path, "2026-09-18")
    (tmp_path / "on").write_text("1")
    (tmp_path / "deny.json").write_text('{"apps": []}')
    keep.write_policy(tmp_path, keep.Policy(segment_days=14, thumb_days=3))
    (tmp_path / "_tmp").mkdir()
    (tmp_path / "_tmp" / "now.png").write_bytes(b"PNG")
    load, _ = _io(tmp_path)
    gone: list[str] = []

    rep = keep.wipe_all(tmp_path, load=load, forget=lambda s: (gone.append(s), 1)[1])

    assert sorted(rep.days_removed) == ["2026-09-01", "2026-09-18"]
    assert len(gone) == 4 and rep.facts_removed == 4
    assert not (tmp_path / "2026-09-01").exists() and not (tmp_path / "2026-09-18").exists()
    assert not (tmp_path / "_tmp").exists()
    assert (tmp_path / "on").exists() and (tmp_path / "deny.json").exists()
    assert keep.read_policy(tmp_path).segment_days == 14


def test_体量数出来的是给用户看的那几个数(tmp_path):
    """「段落留 30 天」单独一句是个抽象设置；「30 天 · 现在 2 天 4 段 · 若干 KB」
    才是用户能据此做决定的东西。"""
    _mkday(tmp_path, "2026-09-18")
    _mkday(tmp_path, "2026-09-10", described=False, report=False)
    load, _ = _io(tmp_path)

    u = keep.usage(tmp_path, load)

    assert u.days == 2 and u.segments == 4 and u.described == 2
    assert u.thumbs == 4 and u.reports == 1
    assert u.oldest == "2026-09-10" and u.bytes > 0


# ——— 路由 ————————————————————————————————————————————————————

def _router(tmp_path, monkeypatch):
    """把路由指到临时目录，并把知识库换成数得清的假的。"""
    from app.routers import journey as J

    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)
    monkeypatch.setattr(J, "_swept_at", 0.0)
    gone: list[str] = []
    monkeypatch.setattr(J, "UserMemory", lambda user: type(
        "M", (), {"remove_sessions": lambda self, s: (gone.append(s), 1)[1]})())
    return J, gone


def test_留多久这一栏同时给出现在盘上有多少东西(tmp_path, monkeypatch):
    """「段落留 30 天」单独一句是个抽象设置。用户要做的决定需要第二个数。"""
    J, _ = _router(tmp_path, monkeypatch)
    _mkday(tmp_path, "2026-09-18")

    out = J.get_retention(user="tester")

    assert out.segment_days == 30 and out.thumb_days == 7
    assert out.frame_days == J.FRAME_KEEP_DAYS == 3
    assert keep.FOREVER in out.segment_choices          # 「一直留着」有这一档
    assert out.days == 1 and out.segments == 2 and out.thumbs == 2 and out.reports == 1
    assert out.bytes > 0 and out.oldest == "2026-09-18"


def test_把保留期改小_当场生效(tmp_path, monkeypatch):
    """改小了不立刻生效的话，用户把 30 天改成 7 天、那几天还在页面上——
    他没有任何办法知道这个开关到底有没有用。"""
    J, gone = _router(tmp_path, monkeypatch)
    old = _mkday(tmp_path, "2026-09-01")
    _mkday(tmp_path, "2026-09-18")

    out = J.put_retention(J.JourneyRetentionIn(segment_days=7, thumb_days=7), user="tester")

    assert not old.exists(), "改完没当场清 = 这个开关看不出有没有生效"
    assert out.swept["days_removed"] == ["2026-09-01"]
    assert out.swept["facts_removed"] == 2 and len(gone) == 2
    assert out.days == 1 and out.segment_days == 7
    assert json.loads((tmp_path / keep.POLICY_FILE).read_text())["segment_days"] == 7


def test_全部删掉_连知识库里的记忆一起(tmp_path, monkeypatch):
    J, gone = _router(tmp_path, monkeypatch)
    _mkday(tmp_path, "2026-09-01")
    _mkday(tmp_path, "2026-09-18")

    out = J.delete_all(user="tester")

    assert sorted(out.swept["days_removed"]) == ["2026-09-01", "2026-09-18"]
    assert len(gone) == 4 and out.swept["facts_removed"] == 4
    assert out.days == 0 and out.segments == 0 and out.bytes == 0
    assert J.days(user="tester") == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root 删得掉任何东西")
def test_删一天没删干净要报_500_不能回一句删好了(tmp_path, monkeypatch):
    """原来是 `shutil.rmtree(ignore_errors=True)`：被占着的文件留在盘上，
    而用户拿到的是「删掉了这一天」。"""
    J, _ = _router(tmp_path, monkeypatch)
    d = _mkday(tmp_path, "2026-09-18")
    (d / "thumbs").chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(Exception) as e:
            J.delete_day(date="2026-09-18", user="tester")
        assert "没删干净" in str(e.value.detail) and "thumbs" in str(e.value.detail)
        assert d.exists()
    finally:
        (d / "thumbs").chmod(stat.S_IRWXU)


def test_翻天那一下会顺手清一遍过期的(tmp_path, monkeypatch):
    """清理挂在**读的路径**上，不另起定时器。挂在 `/day` 上不够：那个接口只看
    用户正打开的那一天，而没人会去翻三天前（实测 09-16 的 78MB 就这么留着）。"""
    from app.routers import journey as J

    called: list[str] = []
    monkeypatch.setattr(J, "journey_root", lambda: tmp_path)
    monkeypatch.setattr(J, "_sweep_if_due", lambda user: called.append(user))

    J.days(user="tester")

    assert called == ["tester"]


def test_清理十分钟才跑一遍_不是每次轮询都扫盘(tmp_path, monkeypatch, _no_journey_sweep):
    """这一页每 30 秒轮询一次。每次都 `rglob` 一遍整根目录是拿用户的磁盘
    换一个没人要的即时性。（`_no_journey_sweep` 给回的是**真的那个**。）"""
    J, _ = _router(tmp_path, monkeypatch)
    ran: list[int] = []
    monkeypatch.setattr(J, "_sweep", lambda user, policy=None: ran.append(1))

    _no_journey_sweep("tester")
    monkeypatch.setattr(J, "_swept_at", 1e9)      # 刚扫过
    _no_journey_sweep("tester")

    assert len(ran) == 1
