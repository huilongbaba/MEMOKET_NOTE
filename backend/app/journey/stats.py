"""一天的段落 → 数出来的事实。没有模型调用，没有 I/O。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# 两段之间隔这么久就算「没在记」（中午吃饭、开会、离开座位）。
# 跟前端 JourneyPage 的 GAP_MIN 是同一个数：同一条带，两边画出来要一致。
GAP_MIN = 15

# 一段连续专注至少这么长才值得单独拎出来说——3 分钟的「专注」不是专注。
FOCUS_MIN = 10

# 反复回到同一处：来回这么多次才算。2 次是正常的（写代码 ↔ 查文档），
# **3 次以上、中间还夹着别的地方**，才是「在同一处打转」这个信号。
CHURN_VISITS = 3


def _at(s: str) -> datetime | None:
    """把段落里的时间戳读成带时区的 datetime。读不出来就 None——
    一行坏数据不该让一天的统计整个塌掉（第 636 轮实拍：整天 500）。

    不带时区的当本地时间：壳写的一律是 UTC（`toISOString()`），
    不带时区的只可能是手工塞进去的。
    """
    try:
        t = datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    return t if t.tzinfo else t.astimezone()


def seg_secs(seg: dict) -> float:
    a, b = _at(seg.get("start", "")), _at(seg.get("end", ""))
    return max(0.0, (b - a).total_seconds()) if a and b else 0.0


@dataclass(frozen=True)
class AppSpan:
    """一个应用今天一共占了多久。"""

    app: str
    secs: float
    segments: int


@dataclass(frozen=True)
class Stretch:
    """一段没被打断的连续时间（同一个应用、中间没有空档）。

    `title` 是这块里占时间最长的那个窗口标题——**「下午有 52 分钟在 Code」
    几乎没有信息量，「在 capture.ts」才有**。没有标题就留空。
    """

    app: str
    start: datetime
    end: datetime
    secs: float
    title: str = ""


@dataclass(frozen=True)
class Churn:
    """一处被反复回来的地方：来回几次、一共花了多久。"""

    app: str
    title: str
    visits: int
    secs: float


@dataclass
class DayStats:
    date: str
    """真正记到的时长（各段之和，不含空档）。"""
    total_secs: float = 0.0
    """第一段到最后一段之间有多长（含空档）。"""
    span_secs: float = 0.0
    gap_secs: float = 0.0
    apps: list[AppSpan] = field(default_factory=list)
    stretches: list[Stretch] = field(default_factory=list)
    churn: list[Churn] = field(default_factory=list)
    first: datetime | None = None
    last: datetime | None = None


def day_stats(date: str, segs: list[dict]) -> DayStats:
    """把一天的段落数成一份统计。**顺序按时间重排**——落盘的顺序一般就是
    时间顺序，但补描述、跨天换目录这些路径都可能打乱它，而「连续专注」和
    「反复来回」两个信号都依赖顺序。"""
    usable = [s for s in segs if _at(s.get("start", "")) and _at(s.get("end", ""))]
    usable.sort(key=lambda s: _at(s["start"]))          # type: ignore[arg-type,return-value]
    out = DayStats(date=date)
    if not usable:
        return out

    out.first, out.last = _at(usable[0]["start"]), _at(usable[-1]["end"])
    out.total_secs = sum(seg_secs(s) for s in usable)
    if out.first and out.last:
        out.span_secs = max(0.0, (out.last - out.first).total_seconds())

    by_app: dict[str, list[float]] = {}
    for s in usable:
        by_app.setdefault(s.get("app") or "（未知）", []).append(seg_secs(s))
    out.apps = sorted((AppSpan(a, sum(v), len(v)) for a, v in by_app.items()),
                      key=lambda x: -x.secs)

    # 空档 + 连续专注：一次扫过去。相邻两段隔了 GAP_MIN 以上就断开，
    # 同一个应用连着的段并成一块。
    cur_app, cur_start, cur_end = usable[0].get("app"), _at(usable[0]["start"]), _at(usable[0]["end"])
    titles: dict[str, float] = {}

    def close() -> None:
        top = max(titles.items(), key=lambda kv: kv[1])[0] if titles else ""
        out.stretches.append(Stretch(cur_app or "", cur_start, cur_end,           # type: ignore[arg-type]
                                     (cur_end - cur_start).total_seconds(), top))  # type: ignore[operator]

    titles[(usable[0].get("title") or "").strip()] = seg_secs(usable[0])
    titles.pop("", None)
    for prev, s in zip(usable, usable[1:]):
        a, b = _at(s["start"]), _at(s["end"])
        idle = (a - _at(prev["end"])).total_seconds()    # type: ignore[operator]
        broke = idle >= GAP_MIN * 60
        if broke:
            out.gap_secs += idle
        if broke or s.get("app") != cur_app:
            close()
            cur_app, cur_start, titles = s.get("app"), a, {}
        t = (s.get("title") or "").strip()
        if t:
            titles[t] = titles.get(t, 0.0) + seg_secs(s)
        cur_end = b
    close()
    out.stretches = sorted((x for x in out.stretches if x.secs >= FOCUS_MIN * 60),
                           key=lambda x: -x.secs)

    out.churn = _churn(usable)
    return out


def _churn(segs: list[dict]) -> list[Churn]:
    """反复回到同一处：同一个 (应用, 标题) 走了又回、**中间还去过别处**。

    只数「回」的次数而不是段数：同一个地方连着的几段是一次停留，不是三次
    来回。这个信号是屏幕记录独有的——会议记录和笔记里没有「你在这儿打转」
    这回事（§4.1）。
    """
    visits: dict[tuple[str, str], list[float]] = {}
    prev_key: tuple[str, str] | None = None
    for s in segs:
        key = (s.get("app") or "", (s.get("title") or "").strip())
        if key != prev_key:
            visits.setdefault(key, []).append(0.0)
        visits[key][-1] += seg_secs(s)
        prev_key = key
    out = [Churn(app, title, len(v), sum(v))
           for (app, title), v in visits.items()
           if len(v) >= CHURN_VISITS and title]        # 没标题的分不清是不是同一处，不算
    return sorted(out, key=lambda c: (-c.visits, -c.secs))


# ---------------------------------------------------------------- 写给模型看的那一块

def say_span(sec: float) -> str:
    m = round(sec / 60)
    if m < 1:
        return "不到 1 分钟"
    if m < 60:
        return f"{m} 分钟"
    h, rest = divmod(m, 60)
    return f"{h} 小时 {rest} 分钟" if rest else f"{h} 小时"


def _hhmm(t: datetime | None) -> str:
    return t.astimezone().strftime("%H:%M") if t else "—"


def render_time_block(st: DayStats) -> str:
    """「时间去哪了」这一节**由代码写死**，不交给模型。

    模型数时长会数错，而它数错的时候读起来跟数对了一模一样。日报里这一节
    直接原样用这段 markdown，提示词里会明说「不要重算，也不要重复这一节」。
    """
    if not st.apps:
        return "## 时间去哪了\n\n这一天没有记录。\n"
    lines = [
        "## 时间去哪了",
        "",
        f"{_hhmm(st.first)} – {_hhmm(st.last)}，记到 {say_span(st.total_secs)}"
        + (f"，中间有 {say_span(st.gap_secs)}没在记。" if st.gap_secs >= GAP_MIN * 60 else "。"),
        "",
    ]
    lines += [f"- **{a.app}** {say_span(a.secs)}（{a.segments} 段）" for a in st.apps[:8]]
    if st.stretches:
        lines += ["", "连续没被打断的几块："]
        lines += [f"- {_hhmm(x.start)}–{_hhmm(x.end)} {x.app}"
                  + (f" · {x.title}" if x.title else "") + f" {say_span(x.secs)}"
                  for x in st.stretches[:5]]
    return "\n".join(lines) + "\n"


def render_churn(st: DayStats) -> str:
    """反复来回的地方，喂给模型当「卡在哪」的线索——**是线索不是结论**：
    来回八次可能是卡住了，也可能是那件事本来就需要两头对着看。"""
    if not st.churn:
        return ""
    lines = ["今天反复回去过的地方（走了又回，中间去过别处）："]
    lines += [f"- {c.app} · {c.title}：{c.visits} 次，共 {say_span(c.secs)}"
              for c in st.churn[:6]]
    return "\n".join(lines) + "\n"
