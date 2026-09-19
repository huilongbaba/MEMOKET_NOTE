"""屏幕活动**留多久**（docs/daily-journey-plan.md §1、§8.3 ③）。

**为什么这个文件存在**（第 779 轮 / P21）：在这之前，这个功能**没有保留期**。
`FRAME_KEEP_DAYS=3` 只管那张送给模型看的大图；**段落描述和缩略图一天都不删**——
真实数据里 09-16 那 38 张缩略图三天后还躺着，09-16 的 78MB 大图也还在
（因为过期清理只在「打开那一天」时才跑，而没人会去翻三天前）。
也就是说这台机器上无限期堆着一份「这个人每天在屏幕上干了什么」的文字记录，
而那一屏知情选择上的四条里**没有一条告诉用户留多久**——计划 §8.3 写的是五条，
少的正是这条。**功能没有，那句话就写不上去**；先有清理，才敢承诺。

定下来的默认值和理由（真实数据量在 docs/daily-journey-plan.md §1 里）：

  · **缩略图 7 天。** 它是「这句描述是不是编的」的凭据，而核对这件事发生在
    当天到几天内——没有任何一条产品路径会去读两周前的缩略图。
    真实数据：99–170 张 / 天、1.2–2.0MB / 天，7 天 ≈ 700–1200 张 ≈ 10–14MB。
  · **段落描述 30 天。** 比缩略图久，因为它是「回顾」这条路的原料，而且体量
    小得多（30–60KB / 天，30 天 ≈ 1.2MB）。**为什么正好 30**：这个功能自己就
    摆着一个「最近 30 天」的回顾按钮，保留期短于产品自己给的最长回顾窗口，
    那个按钮就会变成一句假话。
  · **大图仍然 3 天**（`FRAME_KEEP_DAYS`，没改）：描述做完当场就删，3 天是给
    「看图那台一直连不上」留的窗口。

「一直留着」是**一个选项，不是默认**：默认值决定了绝大多数人的实际隐私状态。

**删不掉要吵。** 这一层的每个删除都把失败收进 `failures`，交给界面原样说出来
（`shutil.rmtree(ignore_errors=True)` 那种「安静地删不掉」正是让用户以为已经
删干净了的做法——这跟 `DELETE /day` 之后那一天自己长回来是同一类事故）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path
from typing import Callable, Iterable

#: 「一直留着」。0 而不是 None：它要能原样落进 json、也能直接 `if not days`。
FOREVER = 0

DEFAULT_SEGMENT_DAYS = 30
DEFAULT_THUMB_DAYS = 7

#: 设置里能选的档。**「一直留着」在列表里、但不在默认值上**。
SEGMENT_CHOICES = (7, 14, 30, 90, 180, FOREVER)
THUMB_CHOICES = (1, 3, 7, 14, 30, FOREVER)

POLICY_FILE = "retention.json"


@dataclass(frozen=True)
class Policy:
    """留多久。天数 = 「这么多天以前的就删掉」，`FOREVER`（0）= 一直留着。"""

    segment_days: int = DEFAULT_SEGMENT_DAYS
    thumb_days: int = DEFAULT_THUMB_DAYS

    def as_dict(self) -> dict:
        return {"segment_days": self.segment_days, "thumb_days": self.thumb_days}


def _pick(value, choices: Iterable[int], fallback: int) -> int:
    """只认列表里的档。**乱数一律退回默认**，不做 clamp——
    `segment_days: -1` clamp 成 0 就成了「一直留着」，那是把坏数据解释成
    最宽松的那一档，方向正好反了。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return fallback
    return n if n in tuple(choices) else fallback


def read_policy(root: Path) -> Policy:
    """读 `<journey 根>/retention.json`。没有 / 坏了都回默认——
    **默认是保守的那一档**，读不出来时宁可删得早一点。"""
    try:
        j = json.loads((root / POLICY_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Policy()
    if not isinstance(j, dict):
        return Policy()
    return Policy(
        segment_days=_pick(j.get("segment_days"), SEGMENT_CHOICES, DEFAULT_SEGMENT_DAYS),
        thumb_days=_pick(j.get("thumb_days"), THUMB_CHOICES, DEFAULT_THUMB_DAYS),
    )


def write_policy(root: Path, policy: Policy) -> Policy:
    clean = Policy(
        segment_days=_pick(policy.segment_days, SEGMENT_CHOICES, DEFAULT_SEGMENT_DAYS),
        thumb_days=_pick(policy.thumb_days, THUMB_CHOICES, DEFAULT_THUMB_DAYS),
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / POLICY_FILE).write_text(json.dumps(clean.as_dict(), ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    return clean


def age_days(day: str, today: _date) -> int | None:
    """这一天离今天几天。日期不合法返回 None（那种目录一律不碰）。"""
    try:
        return (today - _date.fromisoformat(day)).days
    except ValueError:
        return None


def due(day: str, today: _date, policy: Policy) -> tuple[bool, bool]:
    """`(整天该删了, 缩略图该删了)`。

    **纯函数，判据在这里**——扫盘那一层只负责执行。
    `age >= days`：`segment_days=7` 的意思是「七天前那天的记录不留了」，
    所以 09-19 这天在 09-26 被删，不是 09-25。

    今天和「未来的日子」（时钟被调回去过）一律不动：今天那份壳正在往里写。
    """
    age = age_days(day, today)
    if age is None or age <= 0:
        return False, False
    seg = bool(policy.segment_days) and age >= policy.segment_days
    thumb = bool(policy.thumb_days) and age >= policy.thumb_days
    # 整天都要删了就不用单说缩略图——一起走
    return seg, (thumb and not seg)


@dataclass
class SweepReport:
    """一次清理干了什么。**失败要能原样端到界面上。**"""

    days_removed: list[str] = field(default_factory=list)
    thumbs_removed: int = 0
    frames_removed: int = 0
    facts_removed: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def did_something(self) -> bool:
        return bool(self.days_removed or self.thumbs_removed or self.frames_removed)

    def as_dict(self) -> dict:
        return {"days_removed": self.days_removed, "thumbs_removed": self.thumbs_removed,
                "frames_removed": self.frames_removed, "facts_removed": self.facts_removed,
                "failures": self.failures}


def rm_file(p: Path, fails: list[str]) -> bool:
    """删一个文件。**删不掉就记一行**（谁、为什么），不吞。"""
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        fails.append(f"{p}：{exc.strerror or exc}")
        return False


def rm_tree(d: Path, fails: list[str]) -> bool:
    """删一整个目录，**自底向上、一个一个删**，每个删不掉的都记一行。

    不用 `shutil.rmtree(ignore_errors=True)`：那个会在删不掉时安静地留下半个
    目录，而调用方拿到的是「成功」。用户按的是「删掉」，删不掉必须说。
    """
    if not d.exists():
        return True
    ok = True
    for p in sorted(d.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        if p.is_dir():
            try:
                p.rmdir()
            except OSError as exc:
                fails.append(f"{p}：{exc.strerror or exc}")
                ok = False
        elif not rm_file(p, fails):
            ok = ok and not p.exists()
    try:
        d.rmdir()
    except OSError as exc:
        fails.append(f"{d}：{exc.strerror or exc}")
        ok = False
    return ok


def day_dirs(root: Path) -> list[str]:
    """journey 根下所有「看起来是一天」的目录名。`_tmp` / `on` / `deny.json` 不算。"""
    try:
        return sorted(d.name for d in root.iterdir()
                      if d.is_dir() and age_days(d.name, _date.today()) is not None)
    except OSError:
        return []


def drop_thumbs(day_dir: Path, segs: list[dict], fails: list[str]) -> int:
    """删这一天的缩略图，并把段上的 `thumb` 抹掉。

    **两件事必须一起做**：只删文件不改段落的话，页面上每行都会挂一个
    404 的 `<img>`（`has_thumb` 还是 true），看起来像坏了而不是「过期了」。
    """
    n = 0
    root = day_dir.resolve()
    for seg in segs:
        t = seg.get("thumb")
        if t:
            # **只删这一天目录里的东西。** 段落文件是壳写的，真被改过的话这里
            # 就是一个「按路径删任意文件」的口子；不在目录里的不删，但要说一声。
            try:
                p = Path(t).resolve()
                p.relative_to(root)
            except (OSError, ValueError):
                fails.append(f"{t}：不在 {day_dir.name} 的目录里，没删")
                seg["thumb"] = ""
                continue
            if rm_file(p, fails):
                n += 1
            seg["thumb"] = ""
    # 段落表里没记到的（并段时留下的无主缩略图）也一起清
    sub = day_dir / "thumbs"
    if sub.is_dir():
        for f in sorted(sub.iterdir()):
            if rm_file(f, fails):
                n += 1
        try:
            sub.rmdir()
        except OSError:
            pass          # 还有东西就留着，下一轮再说；rm_file 已经把真失败记过了
    return n


def sweep(root: Path, policy: Policy, today: _date, *,
          load: Callable[[str], list[dict]],
          save: Callable[[str, list[dict]], None],
          forget: Callable[[str], int] | None = None,
          expire_frames: Callable[[str, list[dict]], int] | None = None) -> SweepReport:
    """按保留期清一遍。**每天都要做的事挂在读的路径上**，不另起定时器。

    `forget` 是「把这一段抽进知识库的那条记忆也删掉」。**过期必须连它一起删**，
    否则「这些记录只留 30 天」是假的——句子还在知识库里，还会被召回、被引用。
    这跟 `DELETE /day` 连事实一起删是同一条承诺（§1 ⑤）。
    """
    rep = SweepReport()
    for day in day_dirs(root):
        drop_day, drop_thumb = due(day, today, policy)
        d = root / day
        if drop_day:
            segs = load(day)
            if forget:
                for s in segs:
                    if s.get("session"):
                        rep.facts_removed += forget(s["session"])
            if rm_tree(d, rep.failures):
                rep.days_removed.append(day)
            continue
        segs = load(day)
        if not segs:
            continue
        changed = 0
        if expire_frames:
            # 大图的过期（`FRAME_KEEP_DAYS`）原来只在**打开那一天**时才跑，
            # 于是没人去翻的那几天一直留着整屏截图（实测 09-16 三天后还有 78MB）。
            changed += expire_frames(day, segs)
            rep.frames_removed += changed
        if drop_thumb:
            n = drop_thumbs(d, segs, rep.failures)
            rep.thumbs_removed += n
            changed += n
        if changed:
            save(day, segs)
    return rep


def wipe_all(root: Path, *, load: Callable[[str], list[dict]],
             forget: Callable[[str], int] | None = None) -> SweepReport:
    """**全部删掉**：所有天的段落、描述、缩略图、大图、日报，连同它们抽进
    知识库的记忆。

    留下的只有三样**不是记录**的东西：开关（`on`）、用户自己加的黑名单
    （`deny.json`）、保留期（`retention.json`）——「把我记下来的都删掉」
    不等于「把我的设置也恢复出厂」。
    """
    rep = SweepReport()
    for day in day_dirs(root):
        segs = load(day)
        if forget:
            for s in segs:
                if s.get("session"):
                    rep.facts_removed += forget(s["session"])
        if rm_tree(root / day, rep.failures):
            rep.days_removed.append(day)
    rm_tree(root / "_tmp", rep.failures)
    return rep


@dataclass
class Usage:
    """现在盘上有多少东西。**「删掉」之前要能说清楚删的是什么**。"""

    days: int = 0
    segments: int = 0
    described: int = 0
    thumbs: int = 0
    reports: int = 0
    bytes: int = 0
    oldest: str = ""

    def as_dict(self) -> dict:
        return {"days": self.days, "segments": self.segments, "described": self.described,
                "thumbs": self.thumbs, "reports": self.reports, "bytes": self.bytes,
                "oldest": self.oldest}


def usage(root: Path, load: Callable[[str], list[dict]]) -> Usage:
    u = Usage()
    days = day_dirs(root)
    u.days = len(days)
    u.oldest = days[0] if days else ""
    for day in days:
        d = root / day
        segs = [s for s in load(day) if not s.get("deleted")]
        u.segments += len(segs)
        u.described += sum(1 for s in segs if (s.get("desc") or "").strip())
        u.thumbs += sum(1 for s in segs if s.get("thumb"))
        if (d / "report.json").is_file():
            u.reports += 1
        try:
            u.bytes += sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        except OSError:
            pass
    return u
