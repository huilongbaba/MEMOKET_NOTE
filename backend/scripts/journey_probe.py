"""Daily Journey 的 P0：采一小时，看看这个功能到底成不成立。

    cd backend && .venv/bin/python scripts/journey_probe.py --minutes 60

**这不是功能，是一次测量。** 不入库、不进界面、不常驻——跑完在
`data/journey-probe/<时间戳>/` 留一份 markdown，人去读。

方案（docs/daily-journey-plan.md §6）说得很清楚：现在有三个数字全是猜的，
而它们决定这个功能该怎么设计、甚至该不该做：

  1. **一天多少段？** 30 段和 300 段是两种产品。
  2. **一段描述值多少钱？** 决定它能不能一直开着。
  3. **描述有没有用？** 最要紧的一条——模型看着一屏 Xcode 只会说「用户在使用
     代码编辑器」的话，整个功能就是个花钱的噪声源。

所以这个脚本的产出不是「能跑」，是**一份给人读的东西**。

—— 四层漏斗（§2），越靠前越便宜 ————————————————————————————————
  第 1 层  前台应用 + 窗口标题（osascript，零成本）
  第 2 层  截图 + 感知哈希，跟上一帧比，没变化就丢（不外发）
  第 3 层  分段：连续的相似帧收成一段，**描述的单位是段不是帧**
  第 4 层  每段挑几帧送视觉模型，产出一句「在做什么」

—— 隐私（§1）————————————————————————————————————————————————
  · 黑名单命中时**连截图都不拍**，不是拍了再删
  · 原图跑完就删，只留每段代表帧的缩略图（长边 640，给人读报告时认路）
  · 图走 `editor.vision.ask_image` —— 那条路是独立的视觉端点，默认本机
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image                                          # noqa: E402

from app.editor.vision import VisionError, ask_image           # noqa: E402

# 默认不记的：命中就连截图都不拍。宁可少记，不可记错。
DENY_APPS = {
    "1Password", "1Password 7", "Keychain Access", "钥匙串访问",
    "Bitwarden", "LastPass", "Dashlane", "Enpass",
}
DENY_TITLE_WORDS = ("密码", "password", "隐私浏览", "private browsing",
                    "无痕", "incognito", "网上银行", "online banking")

HASH_SIZE = 8           # dHash 的边长：8 → 64 位
SAME_FRAME_BITS = 6     # 汉明距离 ≤ 这个数就算「没变化」
NEW_SEG_BITS = 18       # 超过这个数算「画面换了」，切段
MAX_SEG_MIN = 20        # 一段最长多久，强制切
MIN_SEG_SEC = 45        # 比这还短的段不描述（一闪而过的切换，不是「在做什么」）


def front_app() -> tuple[str, str]:
    """前台应用名 + 窗口标题。**这一层是免费的，而且信息量很大**——
    `Xcode — MemoketApp.swift` 本身就回答了大半个「在做什么」。"""
    script = '''
    tell application "System Events"
      set p to first application process whose frontmost is true
      set appName to name of p
      try
        set winTitle to name of front window of p
      on error
        set winTitle to ""
      end try
    end tell
    return appName & "\\n" & winTitle
    '''
    try:
        out = subprocess.run(["osascript", "-e", script], capture_output=True,
                             text=True, timeout=5).stdout.strip().split("\n")
    except (subprocess.SubprocessError, OSError):
        return "?", ""
    return (out[0] if out else "?"), (out[1] if len(out) > 1 else "")


def denied(app: str, title: str) -> bool:
    if app in DENY_APPS:
        return True
    low = f"{app} {title}".lower()
    return any(w in low for w in DENY_TITLE_WORDS)


def grab(path: Path) -> bool:
    """截一张主屏。`-x` 不发快门声，`-C` 不带光标。"""
    try:
        r = subprocess.run(["screencapture", "-x", "-C", "-t", "png", str(path)],
                           capture_output=True, timeout=20)
        return r.returncode == 0 and path.exists() and path.stat().st_size > 0
    except (subprocess.SubprocessError, OSError):
        return False


def dhash(path: Path) -> int:
    """感知哈希：缩到 9×8 灰度，比较每行相邻像素的大小关系。
    纯本地、微秒级——**绝大多数帧应该死在这一步**，一天里屏幕大部分时间不动。"""
    img = Image.open(path).convert("L").resize((HASH_SIZE + 1, HASH_SIZE))
    px = img.load()
    bits = 0
    for y in range(HASH_SIZE):
        for x in range(HASH_SIZE):
            bits = (bits << 1) | (1 if px[x, y] > px[x + 1, y] else 0)
    return bits


def dist(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


WIDE_RATIO = 2.1        # 比 16:9 还宽这么多就按「两个窗口并排」处理


def panes(img: Image.Image) -> list[Image.Image]:
    """把一张截图切成「大概是一个窗口」的几块。

    超宽屏上人几乎总是并排开两个窗口，而**整屏送过去模型什么都读不出来**
    （实测：空响应）。取不到前台窗口坐标要 Accessibility 权限，P0 不为它去要
    ——按宽高比切半是等价的近似，而且不需要任何权限。
    """
    w, h = img.size
    if w / h < WIDE_RATIO:
        return [img]
    return [img.crop((0, 0, w // 2, h)), img.crop((w // 2, 0, w, h))]


def busiest(cur: Image.Image, prev: Image.Image | None) -> Image.Image:
    """哪一半在动，就送哪一半——人在动的那块屏就是他在干活的那块。
    没有上一帧可比时给左边（主屏通常在左）。"""
    parts = panes(cur)
    if len(parts) == 1 or prev is None:
        return parts[0]
    old = panes(prev)
    if len(old) != len(parts):
        return parts[0]
    scored = [(dist(dhash_img(a), dhash_img(b)), a) for a, b in zip(parts, old)]
    scored.sort(key=lambda t: -t[0])
    return scored[0][1] if scored[0][0] > 0 else parts[0]


def dhash_img(img: Image.Image) -> int:
    g = img.convert("L").resize((HASH_SIZE + 1, HASH_SIZE))
    px = g.load()
    bits = 0
    for y in range(HASH_SIZE):
        for x in range(HASH_SIZE):
            bits = (bits << 1) | (1 if px[x, y] > px[x + 1, y] else 0)
    return bits


def save_frame(src: Path, dst: Path, prev: Path | None) -> None:
    """存一帧给描述用：只存「在动的那一块」，缩到模型读得动的尺寸。
    原图不留（§1：图片默认不留）。"""
    img = Image.open(src)
    prev_img = Image.open(prev) if prev and prev.exists() else None
    part = busiest(img, prev_img)
    part.thumbnail((DESCRIBE_LONG, DESCRIBE_LONG))
    part.save(dst, "PNG")


# —— 两条实测出来的东西（P0 第一次跑，2026-09-14）————————————————
#
# ① **要求必须放 system，不能拼在图旁边的那段文字里。**
#    拼在一起时本地的 muse-glimmer-30b 会把要求原样复述一遍，然后用英文自言自语
#    （「We need describe what person doing...」），压根没在输出描述。挪到 system
#    之后立刻守规矩了。
#
# ② **别送整屏，送一个窗口。** 同一台机器（3840×1080 超宽屏）实测：
#      整屏  → 空响应（读不动）
#      左半屏 → 「在 VS Code 中查看 Skills-Bugfixing-Feishu 工作区里的 MEMOKET_NOTE
#               项目，选中了 PRD.md 文件」
#      右半屏 → 「在 amazon.com 的搜索框输入 memoket 进行搜索」
#    **这一个决定就把功能从「不可用」变成「可用」**，而且顺带更隐私：另外半边
#    根本不发出去。真正的变量是「一行字占多少像素」，不是长边多少 px。
DESCRIBE_SYSTEM = (
    "你是屏幕活动记录助手。用户给你一张屏幕截图，你只回一句中文，说这个人在做什么。"
    "必须带看得见的具体名字：文件名、函数名、文档标题、网页标题、人名、数字。"
    "「在使用代码编辑器」「在浏览网页」这种话一点用都没有。实在看不清就只回「看不清」。"
    "如果屏幕上有明显的结论、决定、报错、待办，一并写进那句话里。"
    # ③ **必须用标记把答案圈出来。** 光说「只回一句话」按不住——这个模型会边想
    #    边说，把推理过程（还常常是英文）全写进输出，真答案藏在最后。与其跟它
    #    较劲，不如让它想，然后只取标记后面那一段。
    "想什么都可以，但最后必须另起一行，以「答案：」开头写出那一句话。"
)
ANSWER = "答案："
DESCRIBE_LONG = 1600        # 送过去的图长边。一个窗口 1920×1080 缩到这个尺寸刚好读得动


def pick_answer(raw: str) -> str:
    """从模型的输出里把那一句捞出来。

    它会边想边说（常常是英文），真答案在「答案：」后面。没有标记时退回**最后
    一行有实质内容的中文**——那通常就是它想完之后说的那句。两条都落空就原样给，
    读报告的人自己判断（P0 的产出是给人读的，不是给程序用的）。
    """
    text = (raw or "").strip()
    if ANSWER in text:
        return text.rsplit(ANSWER, 1)[1].strip().split("\n")[0].strip()
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    cjk = [ln for ln in lines if re.search(r"[\u4e00-\u9fff]", ln)]
    return (cjk[-1] if cjk else (lines[-1] if lines else text))[:300]


async def describe(frames: list[Path], app: str, title: str) -> tuple[str, float]:
    """一段送一次模型。挑段首那一帧。"""
    t0 = time.perf_counter()
    hint = f"这个人在做什么？（前台应用：{app}"
    if title:
        hint += f"；窗口标题：{title}"
    hint += "）"
    try:
        text = pick_answer(await ask_image(
            hint, frames[0].read_bytes(), max_tokens=600, system=DESCRIBE_SYSTEM))
    except VisionError as exc:
        text = f"（看图失败：{exc}）"
    return text.strip(), (time.perf_counter() - t0)


async def main() -> int:
    ap = argparse.ArgumentParser(description="Daily Journey P0 采样")
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--interval", type=float, default=10, help="几秒采一次")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    root = Path(args.out) if args.out else (
        Path(__file__).resolve().parent.parent / "data" / "journey-probe"
        / datetime.now().strftime("%Y%m%d-%H%M%S"))
    shots = root / "shots"
    shots.mkdir(parents=True, exist_ok=True)

    print(f"采样 {args.minutes} 分钟，每 {args.interval} 秒一次 → {root}")
    print("（第一次跑 macOS 会要屏幕录制权限；黑名单里的应用连截图都不会拍）\n")

    segments: list[dict] = []
    cur: dict | None = None
    prev_hash: int | None = None
    prev_full = shots / "_prev.png"
    frames_taken = frames_kept = skipped_deny = 0
    end_at = time.time() + args.minutes * 60
    tmp = shots / "_tmp.png"

    while time.time() < end_at:
        now = datetime.now()
        app, title = front_app()

        if denied(app, title):
            skipped_deny += 1
            if cur:
                cur["end"] = now
            await asyncio.sleep(args.interval)
            continue

        if not grab(tmp):
            await asyncio.sleep(args.interval)
            continue
        frames_taken += 1
        h = dhash(tmp)

        same_screen = prev_hash is not None and dist(prev_hash, h) <= SAME_FRAME_BITS
        long_enough = cur and (now - cur["start"]).total_seconds() > MAX_SEG_MIN * 60
        changed = (cur is None or app != cur["app"] or title != cur["title"]
                   or (prev_hash is not None and dist(prev_hash, h) > NEW_SEG_BITS)
                   or long_enough)

        if changed:
            cur = {"start": now, "end": now, "app": app, "title": title,
                   "frames": [], "n": 0}
            segments.append(cur)
            keep = shots / f"{len(segments):03d}.png"
            save_frame(tmp, keep, prev_full)
            cur["frames"].append(keep)
            frames_kept += 1
            dump_segments(root, segments)          # 每切一段落一次盘
        else:
            cur["end"] = now
            if not same_screen:            # 同一段里画面变了一点：留一帧备用
                frames_kept += 1
        cur["n"] += 1
        prev_hash = h
        tmp.replace(prev_full)          # 留一帧做「哪半边在动」的比对，下轮覆盖
        await asyncio.sleep(args.interval)

    tmp.unlink(missing_ok=True)
    prev_full.unlink(missing_ok=True)

    # —— 描述（第 4 层）。太短的段跳过：一闪而过的切换不是「在做什么」——
    long_segs = [s for s in segments
                 if (s["end"] - s["start"]).total_seconds() >= MIN_SEG_SEC]
    print(f"\n采完：{frames_taken} 帧 → {len(segments)} 段，其中 {len(long_segs)} 段够长要描述")
    took = 0.0
    for i, s in enumerate(long_segs, 1):
        print(f"  描述 {i}/{len(long_segs)}：{s['app']} · {s['title'][:30]}")
        s["desc"], dt = await describe(s["frames"], s["app"], s["title"])
        took += dt

    mins = lambda s: max(1, round((s["end"] - s["start"]).total_seconds() / 60))   # noqa: E731
    lines = [
        f"# Daily Journey 采样 · {datetime.now():%Y-%m-%d %H:%M}", "",
        "> 这是 P0 的产出，**给人读的**。读的时候盯三件事：段切得对不对、",
        "> 描述里有没有具体的东西、以及这些描述汇起来能不能写出一份有用的日报。", "",
        "## 数字", "",
        f"- 采样 {args.minutes:.0f} 分钟，每 {args.interval:.0f} 秒一次",
        f"- 截了 {frames_taken} 帧，黑名单跳过 {skipped_deny} 次",
        f"- 切出 **{len(segments)} 段**，其中 {len(long_segs)} 段够长（≥{MIN_SEG_SEC}s）",
        f"- 描述调用 {len(long_segs)} 次，合计 {took:.1f} 秒",
        "",
        f"**按这个速率外推一天（8 小时）**：约 {round(len(segments) * 8 * 60 / args.minutes)} 段、"
        f"{round(len(long_segs) * 8 * 60 / args.minutes)} 次模型调用。",
        "", "## 时间轴", "",
    ]
    for i, s in enumerate(segments, 1):
        mark = "" if s in long_segs else "（太短，没描述）"
        lines.append(f"### {i}. {s['start']:%H:%M}–{s['end']:%H:%M} · {s['app']} "
                     f"· {s['title'] or '（无标题）'} {mark}")
        lines.append(f"约 {mins(s)} 分钟，{s['n']} 帧")
        if s.get("desc"):
            lines += ["", s["desc"]]
        if s["frames"]:
            lines.append(f"\n![]({s['frames'][0].relative_to(root)})")
        lines.append("")

    (root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    dump_segments(root, segments)
    print(f"\n写好了：{root / 'report.md'}")
    return 0


def dump_segments(root: Path, segments: list[dict]) -> None:
    """段落落盘。**采样中每切一段就写一次**——一小时的采样中途崩掉不该血本无归，
    而且人可以中途 `cat segments.json` 看看切得对不对，不用等到最后。"""
    (root / "segments.json").write_text(json.dumps(
        [{k: (str(v) if isinstance(v, (datetime, Path)) else
              [str(x) for x in v] if isinstance(v, list) else v)
          for k, v in s.items()} for s in segments],
        ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
