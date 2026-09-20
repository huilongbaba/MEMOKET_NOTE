#!/usr/bin/env python3
"""**在 scratch 里造一天（几天）屏幕活动数据**（第 793 轮 / P50 · A）。以后每批走查都用它。

*（这一份进仓库是为了能重放；走查那一趟跑的是它的拷贝 `$S/p50/mkjourney.py`。）*

P47 那一格「没摆出来」的原因只有一个：走查用的是 Chromium `--user-data-dir`，
那底下 `journey/` 是空的，而真数据在 `~/Library/Application Support/memoket-note-desktop/journey/`，
走查**一个字节都不碰**那里。这个脚本把「造一天」这件事变成一条命令。

两条路都在这儿，选哪条看你要验什么：

  · `--variant full`（默认）：**只读**拷真数据的「骨架」——段落 + 缩略图 + 日报，
    **大图（shots/*.png）一张不拷**（103MB 里 100MB 是它，而且走查里没有一条路要看原图）。
  · `--variant synthetic`：一个字节都不读真目录，**现造**段落 / 缩略图 / 日报。
    真数据被清掉之后这条还能跑，也是唯一能精确摆出「闲置 / 假的连续 3 小时 / 空的一天」
    这类形状的办法。

三条硬规矩（都在代码里拦着，不是写在注释里靠自觉）：

  1. **目的地必须在 scratch 里**，否则直接退出。这个脚本会 `rm -rf` 目的地。
  2. **`on` 那个文件绝不拷**（P20 的做法）。它在 = 壳一起来就真开始录屏，
     scratch 那份会开始往盘上写、还会弹屏幕录制权限。收尾再断言一次它不在。
  3. **段落里的绝对路径必须改写**。`segments.json` 里 `frames` / `thumb` 存的是
     **绝对路径，指向真目录**。原样拷过去的话，scratch 那个 app 上点一下
     「删掉这一天」/「删一段」，后端 `_drop_frame` 删的就是**真目录里的图**。
     所以 `frames` 一律清空（大图本来就没拷）、`thumb` 改写到目的地。

用法：

    python3 mkjourney.py <userData 目录> [--variant full] [选项]

variant（决定摆出什么形状）：

    full       四天真数据的骨架，最富的那天搬成「今天」（走查主用）
    consent    journey 目录存在但空的 —— 那一屏知情选择
    emptyday   只有今天，且 segments.json 是 `[]` —— 「这一天没有记录」
    synthetic  现造三天（含一段假的「连续 3 小时」和一段闲置），不读真目录
    keep       full + 把 retention.json 写成短保留期（验到期清理）

选项：

    --src DIR        真 journey 目录（默认 ~/Library/Application Support/memoket-note-desktop/journey）
    --today DAY      把哪一天搬成「今天」（默认 full 时是段最多的那天）
    --no-shift       不搬，日期原样拷
    --keep-days S,T  写 retention.json（段落天数,缩略图天数）
    --deny           顺手写一份 deny.json（验「不记这些」那一栏）
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCRATCH = Path("/private/tmp/claude-501")
REAL = Path.home() / "Library/Application Support/memoket-note-desktop/journey"

# 1×1 的 JPEG，够 <img> 和 FileResponse 用，也够看出「有没有缩略图」这件事
JPG_1PX = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300ffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffffffc00011080001000103012200021101031101ffc4001f00"
    "00010501010101010100000000000000000102030405060708090a0bffc400b5100002010303020403"
    "050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f024"
    "6233627282090a161718191a25262728292a3435363738393a434445464748494a5354555657585960"
    "6364656667686970737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9"
    "aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3"
    "f4f5f6f7f8f9faffda0008010100003f00fbfe8a28a2803fffd9"
)


def guard_dest(dest: Path) -> Path:
    dest = dest.resolve()
    if SCRATCH not in dest.parents and dest != SCRATCH:
        sys.exit(f"拒绝：目的地不在 scratch 里（{dest}）。这个脚本会 rm -rf 它。")
    real = REAL.resolve()
    if real == dest or real in dest.parents:
        sys.exit(f"拒绝：目的地落在真目录里（{dest}）")
    return dest


def _is_day(name: str) -> bool:
    try:
        date.fromisoformat(name)
        return True
    except ValueError:
        return False


def read_real_days(src: Path) -> list[tuple[str, list[dict]]]:
    """**只读**。`json.loads` + `iterdir`，一个字节不写。"""
    out = []
    for name in sorted(p.name for p in src.iterdir() if p.is_dir() and _is_day(p.name)):
        try:
            segs = json.loads((src / name / "segments.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(segs, list):
            out.append((name, segs))
    return out


def _shift_iso(iso: str, days: int) -> str:
    if not days:
        return iso
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return (t + timedelta(days=days)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def stage_day(dst_root: Path, day: str, segs: list[dict], src_day: Path | None,
              shift: int, report: dict | None, stub_frames: bool = False) -> dict:
    """造一天。返回这一天造了什么。"""
    dd = dst_root / day
    (dd / "shots").mkdir(parents=True, exist_ok=True)
    (dd / "thumbs").mkdir(parents=True, exist_ok=True)
    thumbs = 0
    out: list[dict] = []
    for i, seg in enumerate(segs):
        s = dict(seg)
        s["start"] = _shift_iso(s.get("start", ""), shift)
        s["end"] = _shift_iso(s.get("end", ""), shift)
        if isinstance(s.get("session"), str) and shift:
            # session 里带着日期（screen-20260918-000），跟着一起搬——不然
            # 「删这一天连它抽进知识库的记忆一起删」那条对不上号
            old = (date.fromisoformat(day) - timedelta(days=shift)).strftime("%Y%m%d")
            s["session"] = s["session"].replace(old, date.fromisoformat(day).strftime("%Y%m%d"))
        # **大图一张不拷**，但 `frames` 这个**字段照搬**，只把路径改写到 scratch 里。
        #
        # ① 路径必须改写：留着真路径 = 给 scratch 那个 app 一条删真文件的路
        #    （后端 `_drop_frame` 直接 `Path(f).unlink()`）。
        # ② 字段**不能清空**：真机上这个字段正是「非空、但文件早就没了」——
        #    09-16 有 37 段、09-17 有 71 段、09-18 有 2 段是这个样子。
        #    清成 `[]` 就把 `has_frame` 从 true 改成了 false，
        #    而「描述这 N 段」那条路全靠 `has_frame`——一清就再也摆不出来。
        #    **造数据要造真机上那个形状，不是造一个干净的形状。**
        # `--stub-frames` 才真在 scratch 里放一张 1px 的占位图（要走「真去描述一段」时用）。
        if seg.get("frames"):
            p = dd / "shots" / f"{i + 1:03d}.png"
            if stub_frames:
                p.write_bytes(JPG_1PX)
            s["frames"] = [str(p)]                    # 不 stub 的话这就是个**悬空路径**，同真机
        else:
            s["frames"] = []
        old_thumb = seg.get("thumb")
        if old_thumb and src_day is not None:
            name = Path(str(old_thumb)).name
            srcf = src_day / "thumbs" / name
            if srcf.is_file():
                shutil.copy2(srcf, dd / "thumbs" / name)     # 源只读
                s["thumb"] = str(dd / "thumbs" / name)
                thumbs += 1
            else:
                s.pop("thumb", None)
        elif old_thumb and src_day is None:
            name = f"{i + 1:03d}.jpg"
            (dd / "thumbs" / name).write_bytes(JPG_1PX)
            s["thumb"] = str(dd / "thumbs" / name)
            thumbs += 1
        out.append(s)
    (dd / "segments.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if report:
        # **整份 report.json 照搬**，不是只搬 `report` 那一段：它还带着
        # `report_segments` / `report_at` / `report_notes`，而页面上「按 N 段写的、
        # 之后又记了 M 段」正是拿它们画的。第一版只搬了正文，页面于是写着
        # 「**按 0 段写的**，之后又记了 88 段」——那是量具造的假象，不是产品的毛病。
        r = dict(report)
        if shift and isinstance(r.get("report_at"), str):
            r["report_at"] = _shift_iso(r["report_at"], shift)
        (dd / "report.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"day": day, "segs": len(out), "thumbs": thumbs,
            "frames": sum(1 for s in out if s.get("frames")),
            "desc": sum(1 for s in out if s.get("desc")), "report": bool(report)}


def synth_days(today: date) -> list[tuple[str, list[dict], dict | None]]:
    """现造三天。形状是**照走查要摆的东西挑的**，不是随机数据：

      · 今天：两段有描述 + 一段「没截图补不了」 + 一段「还没描述但图还在」
      · 昨天：一段**时长对不上采样数**的（P20 #1 那种假的「连续 3 小时」）+ 一份日报
      · 前天：`[]`（空的一天）
    """
    def iso(d: date, h: int, m: int, s: int = 0) -> str:
        return datetime(d.year, d.month, d.day, h, m, s,
                        tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

    y = today - timedelta(days=1)
    dby = today - timedelta(days=2)
    t_segs = [
        {"start": iso(today, 1, 0), "end": iso(today, 1, 12), "app": "Code",
         "title": "capture.ts — MEMOKET_NOTE", "frames": [], "thumb": "x", "n": 49,
         "desc": "改 capture.ts 里 mergeBlips 的 touching 判据",
         "session": f"screen-{today:%Y%m%d}-000"},
        {"start": iso(today, 1, 12, 30), "end": iso(today, 1, 20), "app": "Safari",
         "title": "Electron 文档", "frames": [], "thumb": "x", "n": 30,
         "desc": "查 Electron app.getPath('userData') 在 --user-data-dir 下的行为",
         "session": f"screen-{today:%Y%m%d}-001"},
        # 没描述、也没大图：「描述这 N 段」那个死胡同（P20 #5）
        {"start": iso(today, 1, 21), "end": iso(today, 1, 24), "app": "Feishu",
         "title": "飞书", "frames": [], "thumb": "x", "n": 12, "skip": "没有截图"},
        # 没描述但**大图还在**：这一段才该被数进「描述这 N 段」
        {"start": iso(today, 1, 25), "end": iso(today, 1, 29), "app": "Code",
         "title": "journey.py", "frames": ["__FRAME__"], "thumb": "x", "n": 16},
    ]
    y_segs = [
        # **时长 184 分钟、n=21**（真跟了 5 分钟）——P20 #1 那种假的「连续 3 小时」
        {"start": iso(y, 0, 43), "end": iso(y, 3, 47), "app": "Feishu", "title": "飞书",
         "frames": [], "thumb": "x", "n": 21, "desc": "在飞书里翻用户反馈闭环群的消息",
         "session": f"screen-{y:%Y%m%d}-000"},
        {"start": iso(y, 10, 50), "end": iso(y, 11, 23), "app": "Code",
         "title": "MEMOKET_NOTE 项目继续", "frames": [], "thumb": "x", "n": 131,
         "desc": "把 P49 的走查表写进 TRACELOG-product.md",
         "session": f"screen-{y:%Y%m%d}-001"},
    ]
    rep = {"report": ("## 时间去哪了\n\n08:43 – 19:23，记到 3 小时 37 分钟。\n\n"
                      "- **Code** 32 分钟（1 段）\n- **Feishu** 3 小时 4 分钟（1 段）\n\n"
                      "连续没被打断的几块：\n- 08:43–11:47 Feishu 3 小时 4 分钟\n\n"
                      "## 推进了什么\n- 造数据脚本先摆一条假的「连续 3 小时」，走查时好对着看。\n"),
           "report_segments": 2,
           "report_at": f"{y.isoformat()}T23:59:00+08:00",
           "report_notes": []}
    return [(today.isoformat(), t_segs, None), (y.isoformat(), y_segs, rep),
            (dby.isoformat(), [], None)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dest", help="userData 目录（journey/ 会造在它底下）")
    ap.add_argument("--variant", default="full",
                    choices=("full", "consent", "emptyday", "synthetic", "keep"))
    ap.add_argument("--src", default=str(REAL))
    ap.add_argument("--today", default="")
    ap.add_argument("--no-shift", action="store_true")
    ap.add_argument("--keep-days", default="")
    ap.add_argument("--deny", action="store_true")
    ap.add_argument("--stub-frames", action="store_true",
                    help="原来有大图的那几段放一张 1px 占位图（「描述这 N 段」那条路才摆得出来）")
    a = ap.parse_args()

    dest = guard_dest(Path(a.dest))
    root = dest / "journey"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    made: list[dict] = []
    today = date.today()

    if a.variant == "consent":
        pass                                          # 空目录就是那一屏
    elif a.variant == "emptyday":
        made.append(stage_day(root, today.isoformat(), [], None, 0, None))
    elif a.variant == "synthetic":
        for day, segs, rep in synth_days(today):
            info = stage_day(root, day, segs, None, 0, rep)
            # 「还没描述、图还在」跟「没截图」要分得开：那一段真造一张图出来
            dd = root / day
            fixed = json.loads((dd / "segments.json").read_text(encoding="utf-8"))
            for i, s in enumerate(fixed):
                if s.get("frames") == ["__FRAME__"]:
                    p = dd / "shots" / f"{i + 1:03d}.png"
                    p.write_bytes(JPG_1PX)            # 内容无所谓，在不在才是判据
                    s["frames"] = [str(p)]
            (dd / "segments.json").write_text(json.dumps(fixed, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
            made.append(info)
    else:
        src = Path(a.src)
        if not src.is_dir():
            sys.exit(f"真 journey 目录不在：{src}")
        days = read_real_days(src)
        if not days:
            sys.exit(f"真目录里一天都没读到：{src}")
        # 默认搬「**描述最多**的那一天」到今天，不是段最多的那天：走查要看的是
        # 时间线上那些句子、日报、「描述这 N 段」，段多而一条描述都没有的那天摆不出来。
        pick = a.today or max(days, key=lambda kv: (sum(1 for s in kv[1] if s.get("desc")),
                                                    len(kv[1])))[0]
        shift = 0 if a.no_shift else (today - date.fromisoformat(pick)).days
        dropped = []
        for day, segs in days:
            nd = (date.fromisoformat(day) + timedelta(days=shift)).isoformat()
            if date.fromisoformat(nd) > today:        # 搬到未来的那些天丢掉
                dropped.append(day)
                continue
            rep = None
            rp = src / day / "report.json"
            if rp.is_file():
                try:
                    j = json.loads(rp.read_text(encoding="utf-8"))
                    rep = j if isinstance(j, dict) and j.get("report") else None
                except (OSError, json.JSONDecodeError):
                    rep = None
            made.append(stage_day(root, nd, segs, src / day, shift, rep, a.stub_frames))
        if dropped:
            print(f"（搬到未来、丢掉的几天：{', '.join(dropped)}；搬了 {shift:+d} 天，"
                  f"「今天」= 真数据的 {pick}）", file=sys.stderr)

    if a.variant == "keep" or a.keep_days:
        s, t = (a.keep_days or "7,1").split(",")
        (root / "retention.json").write_text(
            json.dumps({"segment_days": int(s), "thumb_days": int(t)}, ensure_ascii=False, indent=1),
            encoding="utf-8")
    if a.deny:
        (root / "deny.json").write_text(
            json.dumps({"apps": ["Messages"], "words": ["体检"]}, ensure_ascii=False, indent=1),
            encoding="utf-8")

    # ---- 收尾断言：三条硬规矩各核一遍 ----
    assert not (root / "on").exists(), "on 还在——scratch 那份会真开始录屏"
    bad = []
    for seg_file in root.glob("*/segments.json"):
        for s in json.loads(seg_file.read_text(encoding="utf-8")):
            for p in list(s.get("frames") or []) + ([s["thumb"]] if s.get("thumb") else []):
                if not str(p).startswith(str(dest)):
                    bad.append(p)
    assert not bad, f"段落里还留着不在 scratch 里的路径（{len(bad)} 条）：{bad[:3]}"
    if a.variant != "synthetic" and not a.stub_frames:
        assert not list(root.glob("*/shots/*.png")), "大图不该被拷进来"
    # 占位图必须是**现造的 1px**，不能是从真目录拷来的（一张也不许拷）
    for p in root.glob("*/shots/*.png"):
        assert p.stat().st_size == len(JPG_1PX), f"{p} 不是现造的占位图"

    size = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    print(json.dumps({"dest": str(root), "variant": a.variant, "days": made,
                      "thumbs": sum(m["thumbs"] for m in made), "bytes": size,
                      "on_file": (root / "on").exists()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
