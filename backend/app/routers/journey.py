"""屏幕活动（Daily Journey，docs/daily-journey-plan.md）。

**这条路由只干「壳采到的段 → 知识库里的一条记录」这一步。**
日报、跨时间报告一律不在这里另起炉灶——`compose/digest` 本来就是
「一段时间的事实 → 核心结论 / 关键决定 / 待跟进 / 变化」，写作 harness 本来
就会写长报告。段落一旦变成跟会议记录同形状的东西（`screen-<日期>-<序号>`
这个 session），那两条免费复用（§0）。

三个动作：
  · `GET  /api/journey/days`     —— 哪几天有记录（翻天用，也用来判断「有没有用过」）
  · `GET  /api/journey/day`      —— 某天有哪些段（给「今天」页）
  · `POST /api/journey/catch-up` —— 把还没描述的段描述掉，并写进知识库
  · `POST /api/journey/report`   —— 写这一天的日报（时长走代码、结论走模型）
  · `POST /api/journey/span`     —— 一段时间的回顾：**日报 → 长报告 → 一篇笔记**
  · `GET/PUT /api/journey/deny`  —— 用户自己加的黑名单（壳读同一个文件）
  · `DELETE /api/journey/day`    —— 删这一天，**连它抽出来的事实一起删**

最后那条是隐私承诺的一部分：删完还留着事实的话，「我删了那天的记录」是假的
（§1 ⑤）。
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date as _date
from datetime import datetime as _dt
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse


from ..util import llm
from ..harness import prompts
from ..database import store
from ..database.kite.kite_memory import UserMemory
from ..editor.vision import VisionError, ask_image
from ..journey import day_stats, group_runs, render_time_block
from ..journey.stats import _at, render_churn
from ..journey.prompt import REPORT_SYSTEM, SPAN_SYSTEM, report_user, span_user
from ..harness.checks.journey import check_report
from .deps import current_user
from .schemas import (JourneyDayOut, JourneyDenyIn, JourneyDenyOut, JourneyReportOut,
                      JourneyRunOut, JourneySegment, JourneySpanOut)

router = APIRouter(prefix="/api/journey", tags=["journey"])

# 描述这一步的要求**必须放 system**：拼在图旁边那段文字里时，本地视觉模型会把
# 要求原样复述一遍再用英文自言自语，压根不输出描述（第 631 轮实测）。
# 而且得留一个「答案：」的标记——它会边想边说，真答案在最后（第 631 轮）。
# 第 749 轮按真实产出重写了一遍。旧版第一句是「你只回一句中文，说**这个人**在
# 做什么」——模型就照着这五个字起头：实测 14 条描述 **14 条**都以
# 「这个人在 / 人在 / 他在 …」开头。那是一行里视线第一落点上的十几个字，
# 每行都一样，真正的新东西被挤到末尾。而且旧版一边说「一句」一边又要
# 「结论 / 决定 / 报错 / 待办一并写进去」，实测中位 201 字、最长 388 字，
# 页面上一段占六行——这就不是「记成一句话」了。
#
# **还有一层：这些描述会原样变成知识库里的事实。** 十四条事实前十五个字一模一样，
# 召回时那些 n-gram 命中一切（第 747 轮刚在查询侧修过口水词，内容侧不能再造一遍）。
DESCRIBE_SYSTEM = (
    "你是屏幕活动记录助手。用户给你一张屏幕截图，你回一句中文，说屏幕前的人在做什么。"
    "**直接从动词起头，不要主语**：写「改 capture.ts 的落盘逻辑」，"
    "不要写「这个人在改 capture.ts 的落盘逻辑」。"
    "必须带看得见的具体名字：文件名、函数名、文档标题、网页标题、人名、数字。"
    "「在使用代码编辑器」「在浏览网页」这种话一点用都没有。实在看不清就只回「看不清」。"
    "**一句就是一句，四十字上下，只说屏幕中央在干的那件事。**"
    "旁边的标签页、侧栏里的文件名、状态栏的数字，不是这句话要讲的东西。"
    "屏幕上如果有结论、决定、报错、待办，那件事就是主语，写它。"
    "想什么都可以，但最后必须另起一行，以「答案：」开头写出那一句话。"
)
ANSWER = "答案："

# 提示词管不住的那一半，代码管。**这个仓的老教训：「模型返回什么就用什么」
# 是一类 bug**（第 574–579 轮扫过一轮）。这两条都是纯删，不改语义：
_SUBJECT = re.compile(r"^(这个人|那个人|这位|用户|某人|人|他|她|TA|Ta)\s*(正在|在|则在|当前在)?\s*")
_SENT_END = "。！？"


def tighten(desc: str) -> str:
    """把一条描述收成**一句**。

    ① 去掉开头的主语。「这个人在 X」和「X」信息量完全一样，而前者占掉每一行
       视线第一落点上的十几个字，还让十几条事实共享同一串前缀。
       只在**后面还剩得下东西**时才去——「他」单独一条不动它。
    ② 只留第一句。方案里写的就是「记成一句话」（docs/daily-journey-plan.md）。
       **不在句子中间砍**：截一半比长更难读，宁可留着那一句长的。
    """
    d = (desc or "").strip()
    cut = _SUBJECT.sub("", d)
    if len(cut) >= 8:                 # 去完还得是句人话，别把「他在忙」削成「忙」
        d = cut
    for i, ch in enumerate(d):
        if ch in _SENT_END and i + 1 < len(d):
            return d[: i + 1]
    return d

# 一段描述里一个具体名词都没有 = 没用。**不入库。**
# 这跟写作 harness 里 `material_used` 那条判据是同一场仗：「在使用代码编辑器」
# 这种话读起来像个描述，其实什么都没说，而它会被召回、会被引用（§7 ①）。
VAGUE = ("看不清", "无法辨认", "看不出", "不清楚")
MIN_DESC = 12

# 内置黑名单（跟 `desktop/src/capture.ts` 的 DENY_APPS / DENY_TITLE_WORDS 同一份）。
# **摆出来只为了给界面显示**——真正拦截发生在壳里，因为命中时连截图都不该拍。
# 两处要同时改；只改一处的后果是界面上写着「不记」而实际在记。
BUILTIN_DENY_APPS = ("1Password", "1Password 7", "Keychain Access", "钥匙串访问",
                     "Bitwarden", "LastPass", "Dashlane", "Enpass")
BUILTIN_DENY_WORDS = ("密码", "password", "隐私浏览", "private browsing", "无痕",
                      "incognito", "银行", "online banking", "转账", "账单")


def journey_root() -> Path:
    """壳把段落落在 `<userData>/journey/`；开发时可以用环境变量指过去。"""
    return Path(os.environ.get("MEMOKET_JOURNEY_DIR")
                or (Path.home() / "Library" / "Application Support"
                    / "memoket-note-desktop" / "journey"))


def _day_dir(day: str) -> Path:
    if not _ok_day(day):
        raise HTTPException(400, "日期要写成 2026-09-14 这样")
    return journey_root() / day


def _ok_day(day: str) -> bool:
    try:
        _date.fromisoformat(day)
        return True
    except ValueError:
        return False


def _hhmm_local(iso: str) -> str:
    """段落时间戳是壳写的 UTC（`toISOString()`），**给模型、进知识库的都得是本地时刻**。

    第 778 轮（P20）读真实日报读出来的：09-18 那份写着「凌晨浏览了 Amazon 的
    Gem Wearable…」——那一段是 18:12 本地时间（10:12Z）。喂给模型的行是
    `start[11:16]` 切出来的 UTC，页面上的时间轴和「时间去哪了」那一节却是本地的，
    于是模型嘴里的「凌晨 / 上午」跟用户看到的时间轴对不上，整份日报读起来是错的。
    """
    t = _at(iso)
    return t.astimezone().strftime("%H:%M") if t else iso[11:16]


def _load(day: str) -> list[dict]:
    f = _day_dir(day) / "segments.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


# 大图留多久。**没描述也不能永远留着**：8 小时 ≈ 960 张 ≈ 300MB/天，
# 一个月 9GB，而且那是把风险留在磁盘上（§1 ③）。过了这个天数还没描述的，
# 图删掉、段标记成过期——那一段仍然在时间轴上，只是没法再补描述了。
FRAME_KEEP_DAYS = 3


def _drop_frame(seg: dict) -> None:
    """删掉这一段的大图。缩略图（256px）留着——一句没有任何凭据的描述，
    用户没法判断它是不是编的。"""
    for f in seg.get("frames") or []:
        try:
            Path(f).unlink()
        except OSError:
            pass
    seg["frames"] = []


def _expire_frames(day: str, segs: list[dict]) -> int:
    """把过了 `FRAME_KEEP_DAYS` 还没描述的大图删掉。改了几段就返回几段。"""
    try:
        stale = (_date.today() - _date.fromisoformat(day)).days >= FRAME_KEEP_DAYS
    except ValueError:
        return 0
    if not stale:
        return 0
    n = 0
    for seg in segs:
        if seg.get("deleted"):
            continue
        if seg.get("frames") and not seg.get("desc"):
            _drop_frame(seg)
            seg["skip"] = "截图已过期"
            n += 1
        elif seg.get("frames"):
            _drop_frame(seg)
            n += 1
    return n


def _load_report(day: str) -> dict:
    """这一天写过的日报，连同**它是按几段写的**。

    后者不是锦上添花：日报是某一刻的快照，而这一天还在长。不说清楚它按多少
    段写的，用户下午看到的还是上午那份，却没有任何迹象表明它已经过期了。
    """
    try:
        return json.loads((_day_dir(day) / "report.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# 这份文件**有两个写的人**：壳每切一段就落一次盘（`capture.ts` 的 `flush`），
# 后端描述完一段也要写回去。谁后写谁赢 = 谁先写谁被抹掉。
# 第 750 轮实拍到的就是这一幕：日志里「自动描述了 1 段」刷了 90 次，
# 而 `segments.json` 里 71 段**一条描述都没有**——描述一段要 15–20 秒，
# 这期间壳早把没有 `desc` 的那份内存副本盖回去了，下一轮再描述同一批。
#
# 规矩：**各写各的字段。** 后端只认这几个，别的一律以盘上那份为准
# （段落表本身归壳——它在往后长，我们手里这份是 20 秒前的旧快照）。
_MINE = ("desc", "skip", "session", "deleted", "frames")


def _merge_back(disk: list[dict], ours: list[dict]) -> list[dict]:
    """把我们改过的字段贴回**盘上最新的**那份段落表。

    按 `start` 对齐：它是这一段建出来那一刻的时间戳，壳之后再不会改它。
    盘上有、我们手里没有的段 = 这 20 秒里新采的，原样留着。
    墓碑（`deleted`）整条覆盖——删段那一步会把 app / title / n 一起清掉。
    """
    if not disk:                       # 文件没了 / 空的：只能写我们这份
        return ours
    mine = {s["start"]: s for s in ours if s.get("start")}
    out: list[dict] = []
    for seg in disk:
        m = mine.get(seg.get("start", ""))
        if m is None:
            out.append(seg)
        elif m.get("deleted"):
            out.append(m)
        else:
            out.append({**seg, **{k: m[k] for k in _MINE if k in m}})
    return out


def _save(day: str, segs: list[dict]) -> None:
    d = _day_dir(day)
    merged = _merge_back(_load(day), segs)
    # 一段都没有、盘上也没有这一天：别为它建一个空文件——`days()` 会把它数成
    # 「有记录的日子」（实拍 09-19 零点过后 catch-up 写出一个 `[]`，翻天时多出一格空日）
    if not merged and not (d / "segments.json").exists():
        return
    d.mkdir(parents=True, exist_ok=True)
    (d / "segments.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1),
                                     encoding="utf-8")


def pick_answer(raw: str) -> str:
    """从模型输出里把那一句捞出来。它会边想边说，真答案在「答案：」后面。"""
    text = (raw or "").strip()
    if ANSWER in text:
        return text.rsplit(ANSWER, 1)[1].strip().split("\n")[0].strip()
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    cjk = [ln for ln in lines if any("一" <= c <= "鿿" for c in ln)]
    return (cjk[-1] if cjk else (lines[-1] if lines else text))[:300]


def worth_keeping(desc: str) -> bool:
    """这段描述值不值得进知识库。见 VAGUE 上面那段注释。"""
    d = (desc or "").strip()
    return len(d) >= MIN_DESC and not any(v in d for v in VAGUE)


@router.get("/days")
def days(limit: int = 400, user: str = Depends(current_user)) -> list[str]:
    """有记录的日期，新的在前。

    两个用处，都不是锦上添花：
      · **翻天要跳过空的**——按日期加一减一会走进一串什么都没有的日子。
      · **判断「有没有用过」**。停掉记录之后如果只看当天，页面会退回那一屏
        知情选择，于是**以前记的东西既看不到也删不掉**（第 645 轮自查）。
    """
    root = journey_root()
    try:
        out = sorted((d.name for d in root.iterdir()
                      if d.is_dir() and _ok_day(d.name) and (d / "segments.json").is_file()),
                     reverse=True)
    except OSError:
        return []
    return out[:max(1, limit)]


# 用户自己加的黑名单：条数和长度都封顶。名单是要逐条比对的，几千条会拖慢每一次
# 采样；而真需要排除的东西通常就那么几个。
DENY_MAX = 100
DENY_LEN = 80


def _deny_file() -> Path:
    return journey_root() / "deny.json"


def _clean_list(v) -> list[str]:
    out: list[str] = []
    for x in (v or []):
        t = str(x).strip()[:DENY_LEN]
        if t and t not in out:
            out.append(t)
    return out[:DENY_MAX]


@router.get("/deny", response_model=JourneyDenyOut)
def get_deny(user: str = Depends(current_user)) -> JourneyDenyOut:
    """用户自己加的黑名单，连同内置那份（只读，给界面显示）。"""
    try:
        j = json.loads(_deny_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        j = {}
    return JourneyDenyOut(apps=_clean_list(j.get("apps")), words=_clean_list(j.get("words")),
                          builtin_apps=list(BUILTIN_DENY_APPS), builtin_words=list(BUILTIN_DENY_WORDS))


@router.put("/deny", response_model=JourneyDenyOut)
def put_deny(body: JourneyDenyIn, user: str = Depends(current_user)) -> JourneyDenyOut:
    """改黑名单。**只能往上加，内置那份拆不掉**——「把密码管理器加回记录范围」
    不是一个该给的选项。写的是 `<journey 根>/deny.json`，壳按文件改动时间重读。
    """
    root = journey_root()
    root.mkdir(parents=True, exist_ok=True)
    data = {"apps": _clean_list(body.apps), "words": _clean_list(body.words)}
    _deny_file().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return JourneyDenyOut(**data, builtin_apps=list(BUILTIN_DENY_APPS),
                          builtin_words=list(BUILTIN_DENY_WORDS))


@router.get("/day", response_model=JourneyDayOut)
def day(date: str = "", user: str = Depends(current_user)) -> JourneyDayOut:
    day_s = date or _date.today().isoformat()
    segs = _load(day_s)
    # 顺手清过期的大图：这是唯一一个每天都会被调到的接口，清理挂在这儿最省事，
    # 也不用为了一件「到点就该做」的事另起一个定时器。
    if _expire_frames(day_s, segs):
        _save(day_s, segs)
    return JourneyDayOut(
        date=day_s,
        **{k: v for k, v in _load_report(day_s).items() if k in
           ("report", "report_segments", "report_at", "report_notes")},
        # 以前存下来的那些也收一收（`tighten` 是纯删、幂等）。**不回写盘**：
        # 这一步纯粹是显示，不值得为它跟壳抢一次写。
        segments=[JourneySegment(**{k: s.get(k, "") for k in
                                    ("start", "end", "app", "title")},
                                 desc=tighten(s.get("desc") or ""),
                                 n=int(s.get("n") or 0),
                                 has_frame=bool(s.get("frames")),
                                 has_thumb=bool(s.get("thumb")),
                                 i=n)
                  for n, s in enumerate(segs) if not s.get("deleted")],
        minutes=round(sum(_secs(s) for s in segs if not s.get("deleted")) / 60),
    )


def _secs(s: dict) -> float:
    """这一段有多长。**一行坏数据不能把整页打成 500**——这个函数是给「今天」页
    算合计用的，算不出来就当 0，页面照样列得出这一段。

    `TypeError` 是实拍补上的（第 636 轮）：壳写的是 `toISOString()`（带 Z，
    带时区），手工塞进去的样例是不带时区的，一减就
    「can't subtract offset-naive and offset-aware datetimes」，整天的段一条都读不出来。
    """
    from datetime import datetime
    try:
        return (datetime.fromisoformat(s["end"]) - datetime.fromisoformat(s["start"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return 0.0


@router.post("/catch-up", response_model=JourneyRunOut)
async def catch_up(date: str = "", limit: int = 20,
                   user: str = Depends(current_user)) -> JourneyRunOut:
    """把还没描述的段描述掉，并写进知识库。

    **一次只做 limit 段**：一段要十几秒，一天几十段，全做完是十几分钟——
    界面上得能看见进度，而不是点一下等十分钟。
    """
    day_s = date or _date.today().isoformat()
    segs = _load(day_s)
    mem = UserMemory(user)
    described = ingested = skipped = 0
    failed: VisionError | None = None

    for i, seg in enumerate(segs):
        if described >= limit:
            break
        # `skip` 也算处理过了：没有截图的段重试多少次都还是没有截图，
        # 不标记的话每次补描述都会把它们再走一遍，而 `left` 永远归不了零。
        if seg.get("desc") or seg.get("skip") or seg.get("deleted"):
            continue
        frame = (seg.get("frames") or [None])[0]
        if not frame or not Path(frame).is_file():
            seg["desc"] = ""
            seg["skip"] = "没有截图"
            skipped += 1
            continue
        try:
            raw = await ask_image("这个人在做什么？", Path(frame).read_bytes(),
                                  max_tokens=600, system=DESCRIBE_SYSTEM)
        except VisionError as exc:
            # **先把这一批里已经做完的存下来，再报错。** 原来这里直接 raise，
            # `_save` 就没跑——而前面那几段的大图在描述完的当下就删了（`_drop_frame`），
            # 描述没落盘、图也没了，下一轮只能标成「没有截图」。看图服务一抖，
            # 一批里做完的那几段就这么丢了（第 778 轮 / P20）。
            failed = exc
            break
        desc = pick_answer(raw)
        seg["desc"] = desc
        described += 1
        _drop_frame(seg)          # **描述做完就删大图**（§1 ③），见那个函数的注释
        if not worth_keeping(desc):
            seg["skip"] = "没说出具体的东西"
            skipped += 1
            continue
        session = f"screen-{day_s.replace('-', '')}-{i:03d}"
        # 本地时刻：这个标题会出现在知识库「最近摄入」里，UTC 的 16:00 其实是半夜
        title = f"{_hhmm_local(seg.get('start', ''))}–{_hhmm_local(seg.get('end', ''))} · {seg.get('app', '')}"
        try:
            mem.remember([{"role": "user", "content": desc}],
                         session_id=session, date=day_s, title=title)
            seg["session"] = session
            ingested += 1
        except Exception as exc:                       # noqa: BLE001
            # 「已存在」是成功信号，跟 ingest 那边同一条规矩：稳定 session id
            # 的意义就是重跑时跳过、不花钱。
            if "already exists" not in str(exc):
                raise
            seg["session"] = session
    if described or skipped:
        _save(day_s, segs)
    if failed is not None and not described:
        raise HTTPException(502, f"看图失败：{failed}") from failed
    left = sum(1 for s in segs if not s.get("desc") and not s.get("skip") and not s.get("deleted"))
    return JourneyRunOut(date=day_s, described=described, ingested=ingested,
                         skipped=skipped, left=left)


@router.get("/thumb")
def thumb(date: str, i: int, user: str = Depends(current_user)):
    """某一段的缩略图（256px）。**只走本机**——这个接口跟别的接口一样只在
    127.0.0.1 上听，图片不经过任何外部服务（§1）。

    路径来自段落自己记的 `thumb`，但**必须落在这一天的目录里**才给：
    段落文件是壳写的，真要被改过，这里就是一个任意读文件的口子。
    """
    segs = _load(date)
    if not 0 <= i < len(segs):
        raise HTTPException(404, "没有这一段")
    raw = segs[i].get("thumb") or ""
    root = _day_dir(date).resolve()
    try:
        p = Path(raw).resolve()
        p.relative_to(root)
    except (OSError, ValueError):
        raise HTTPException(404, "这一段没有缩略图") from None
    if not p.is_file():
        raise HTTPException(404, "这一段没有缩略图")
    return FileResponse(p, media_type="image/jpeg")


@router.post("/report", response_model=JourneyReportOut)
async def report(date: str = "", user: str = Depends(current_user)) -> JourneyReportOut:
    """写这一天的日报。**一半是数出来的，一半才交给模型**（§4.1）。

    「时间去哪了」由 `journey.stats` 算好、渲染好，原样放在最前面，提示词里
    明说不要重算——模型数时长会数错，而它数错的时候读起来跟数对了一模一样。
    模型只负责它比代码强的那三节：推进了什么 / 卡在哪 / 计划外的。

    写完落在 `<那天>/report.md`：跟着这一天走，`DELETE /day` 一起删掉。
    """
    t0 = time.perf_counter()
    day_s = date or _date.today().isoformat()
    segs = _load(day_s)
    st = day_stats(day_s, [s for s in segs if not s.get("deleted")])
    told = [s for s in segs if (s.get("desc") or "").strip() and not s.get("deleted")]
    if not told:
        # 一段描述都没有就别花这次调用：模型只会拿应用名编一份出来。
        raise HTTPException(400, "这一天还没有任何描述，先点「描述这几段」。")

    # **连着说同一件事的并成一块再喂**（`journey/runs.py`）。不并的话同一件事
    # 会以八条近似重复的样子进提示词，而模型看到的是「这件事出现了八次」——
    # 这一天真正推进了什么反而被那八遍压下去。并完带上「N 段」，
    # 让它仍然知道这件事占了多少时间。第 752 轮在时间轴上做的是同一件事。
    runs = group_runs(sorted(told, key=lambda x: x.get("start") or ""))
    # **本地时刻**，跟「时间去哪了」那一节和页面上的时间轴同一个钟（`_hhmm_local`）
    lines = [f"{_hhmm_local(r['start'])}–{_hhmm_local(r['end'])} {r['app']} {r['desc']}"
             + (f"（{len(r['segs'])} 段）" if len(r["segs"]) > 1 else "")
             for r in runs]
    text = await llm.complete(
        [{"role": "system", "content": prompts.compose_system(REPORT_SYSTEM, "journey", user)},
         {"role": "user", "content": report_user(day_s, lines, render_churn(st))}],
        max_tokens=1200, temperature=0.3)

    md = render_time_block(st) + "\n" + text.strip() + "\n"
    # 确定性体检（计划 8.2，`harness/checks/journey.py`）。**判的是模型写的那
    # 一半**——`render_time_block` 那一节是程序算的，判自己算的东西没有意义；
    # 比对的也是**真正进了提示词的那几行**，模型只可能依据它看见的东西写。
    # **判了不拦**：日报是一次成型的产物，结果跟着它一起给用户（也落进
    # `report.json`，刷新之后还在），要不要「重写」由用户定。零模型调用。
    notes = check_report(text.strip(), lines).notes()
    d = _day_dir(day_s)
    d.mkdir(parents=True, exist_ok=True)
    meta = {"report": md, "report_segments": len(told),
            "report_at": _dt.now().astimezone().isoformat(timespec="seconds"),
            "report_notes": notes}
    (d / "report.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return JourneyReportOut(date=day_s, report=md, segments=len(told),
                            report_at=meta["report_at"], notes=notes,
                            took_ms=round((time.perf_counter() - t0) * 1000, 1))


@router.post("/span", response_model=JourneySpanOut)
async def span(date_from: str = "", date_to: str = "", days: int = 7,
               user: str = Depends(current_user)) -> JourneySpanOut:
    """一段时间的回顾。**喂给模型的是日报，不是原始记录**（§4.2）。

    30 天的段是几十万 token，而且只会换来一份平均值式的废话。两层：每天先
    有日报（那一层已经做完了），这里把日报们汇成一份长报告。

    产出**落成一篇笔记**，不是一段一次性的文字——它要能继续编辑、继续续写、
    被引用。这也是这个功能最后一步的意义：一段时间的屏幕活动，最终变成
    树上的一篇东西。
    """
    t0 = time.perf_counter()
    to_s = date_to or _date.today().isoformat()
    from_s = date_from or (_date.fromisoformat(to_s) - timedelta(days=max(1, days) - 1)).isoformat()
    if from_s > to_s:
        raise HTTPException(400, "起止日期反了")

    reports: list[tuple[str, str]] = []
    missing: list[str] = []
    d = _date.fromisoformat(from_s)
    while d <= _date.fromisoformat(to_s):
        key = d.isoformat()
        md = (_load_report(key).get("report") or "").strip()
        (reports.append((key, md)) if md else missing.append(key))
        d += timedelta(days=1)

    if not reports:
        # 一份日报都没有就不花这次调用。**要的是「先去写日报」，不是一份空报告**。
        raise HTTPException(400, f"{from_s} 到 {to_s} 还没有任何日报。先在那几天各写一份。")

    text = await llm.complete(
        [{"role": "system", "content": prompts.compose_system(SPAN_SYSTEM, "journey", user)},
         {"role": "user", "content": span_user(from_s, to_s, reports)}],
        max_tokens=2000, temperature=0.3)

    title = f"{from_s} – {to_s} 这段时间"
    body = text.strip() + "\n"
    if missing:
        # **缺了哪几天要写在正文里**，不能只在提示里说一句就过去：这篇笔记之后
        # 会被读、被引用，读的人得知道它是按哪些天写的。
        body += (f"\n---\n\n（这份回顾按 {len(reports)} 天的日报写成；"
                 f"{'、'.join(missing[:10])}{'…' if len(missing) > 10 else ''} 这几天没有日报。）\n")
    # **挂在那个月的日记下面**，不是树根：跨几天的回顾也是跟着日期走的东西
    parent = store.journal_node(user, _date.fromisoformat(to_s), depth=3)
    note = store.create_note(user, title, f"# {title}\n\n{body}", parent, source="journey")
    return JourneySpanOut(date_from=from_s, date_to=to_s, days=len(reports),
                          missing=missing, note_id=note["id"], title=title,
                          took_ms=round((time.perf_counter() - t0) * 1000, 1))


@router.post("/report/save", response_model=JourneySpanOut)
def save_report(date: str = "", user: str = Depends(current_user)) -> JourneySpanOut:
    """把这一天的回顾存成一篇笔记——**挂在当天那页日记下面**，不是树根。

    回顾是跟着日期走的东西，日记树就是按日期组织的；落在树根上的话，用几周
    之后树根全是「9 月 14 日这一天」。同名的直接覆盖：重写一次就该换掉上一份，
    而不是在树上留一串同名笔记。
    """
    day_s = date or _date.today().isoformat()
    md = (_load_report(day_s).get("report") or "").strip()
    if not md:
        raise HTTPException(400, "这一天还没有回顾，先写一份。")
    parent = store.journal_node(user, _date.fromisoformat(day_s), depth=4)
    note = store.upsert_child(user, parent, "屏幕活动回顾",
                              f"# {day_s} 屏幕活动\n\n{md}",
                              source="journey", icon="bx-desktop")
    return JourneySpanOut(date_from=day_s, date_to=day_s, days=1,
                          note_id=note["id"], title=note["title"])


@router.delete("/segment", response_model=JourneyRunOut)
def delete_segment(date: str, i: int, user: str = Depends(current_user)) -> JourneyRunOut:
    """删掉一段：它的图、它在时间轴上的位置、**以及它抽出来的那条事实**。

    为什么非有不可：黑名单挡不住所有东西——同事发来的一张截图、一封还没公开
    的邮件、一个忘了关的窗口。只能「删一整天」的话，用户为了抹掉一分钟会丢掉
    一整天，或者干脆把这个功能关掉。**能精确地删，才敢一直开着**（§1）。

    段是按下标寻址的，所以**不能真的从数组里抠掉**——那会让后面每一段的
    下标都挪一位，正在看这一页的人点第 5 段删掉的其实是第 6 段。标成已删，
    读的时候跳过。
    """
    segs = _load(date)
    if not 0 <= i < len(segs):
        raise HTTPException(404, "没有这一段")
    seg = segs[i]
    gone = UserMemory(user).remove_sessions(seg["session"]) if seg.get("session") else 0
    _drop_frame(seg)
    for f in (seg.get("thumb"),):
        if f:
            try:
                Path(f).unlink()
            except OSError:
                pass
    segs[i] = {"start": seg.get("start", ""), "end": seg.get("end", ""),
               "app": "", "title": "", "desc": "", "deleted": True, "n": 0}
    _save(date, segs)
    return JourneyRunOut(date=date, described=0, ingested=0, skipped=0,
                         left=sum(1 for x in segs if not x.get("desc") and not x.get("skip")
                                  and not x.get("deleted")),
                         removed_facts=gone)


@router.delete("/day", response_model=JourneyRunOut)
def delete_day(date: str, user: str = Depends(current_user)) -> JourneyRunOut:
    """删这一天：段、截图、**以及它抽进知识库的事实**。

    最后那一项是重点。只删文件不删事实的话，「我删了那天的记录」就是假的——
    那些句子还会被召回、被引用、写进用户的文稿（§1 ⑤）。
    """
    import shutil

    day_s = date
    segs = _load(day_s)
    mem = UserMemory(user)
    gone = 0
    for s in segs:
        if s.get("session"):
            gone += mem.remove_sessions(s["session"])
    d = _day_dir(day_s)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    return JourneyRunOut(date=day_s, described=0, ingested=0, skipped=0,
                         left=0, removed_facts=gone)
