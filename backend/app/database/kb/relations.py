"""记忆的关系：一段正文跟知识库里的事实是什么关系（docs/agent-native-editor.md §3.3.1）。

「相关」太弱——写作者要的是「跟过去的记录是什么关系」：

  conflict       冲突    同一个量（同单位 / 日期）值不一样
  continuation   延续    同一个量在知识库里有一条随时间变的线（150 → 200 → 300），你写的是下一个点
  corroborated   印证    同一个量、同一个值
  unsupported    缺依据  正文里有具体的数字 / 日期，知识库里找不到沾边的记录
  accumulation   叠加    同一件事，知识库里还有你没写的条件（别的单位的量 / 日期）
  merge          合并    知识库里有两条说的是同一件事（词面高度重合），提议合成一条

这一层是**纯代码、毫秒级**：只产出候选和一句人话；要不要再让模型确认一遍由调用方
决定（routers/memory.py 只对 conflict 候选打一次 LLM）。不依赖 app 的其它模块。
"""

from __future__ import annotations

import re
from collections import defaultdict

_UNITS = (r"mAh|mm|cm|kg|km|GB|MB|MHz|Hz|kWh|W|V|元|块钱|万|亿|台|人|天|周|个月|小时|分钟|"
          r"次|条|页|版|批|套|%|％|美元|美金")
_NUM = re.compile(rf"(\d+(?:\.\d+)?)\s*({_UNITS})")
_DATE_FULL = re.compile(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})日?")
_DATE_MD = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日?")
_EN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}")
_CJK = re.compile(r"[一-鿿]")
_STOP = set("的了在是和与及或把被对到从这那我们你他她它就也都还又很不没有个一了着过为以及以")


def extract_values(text: str) -> dict:
    """数字（带单位）和日期。日期统一成 M-D（有年份的带年份）。"""
    nums: list[tuple[float, str]] = []
    for v, u in _NUM.findall(text):
        u = "%" if u == "％" else u
        nums.append((float(v), u))
    dates: list[str] = []
    for y, m, d in _DATE_FULL.findall(text):
        dates.append(f"{int(y)}-{int(m)}-{int(d)}")
    stripped = _DATE_FULL.sub(" ", text)
    for m, d in _DATE_MD.findall(stripped):
        if 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
            dates.append(f"{int(m)}-{int(d)}")
    return {"nums": nums, "dates": dates}


def _terms(text: str) -> set[str]:
    out = {w.lower() for w in _EN.findall(text) if len(w) >= 2}
    cjk = "".join(_CJK.findall(text))
    for i in range(len(cjk) - 1):
        g = cjk[i:i + 2]
        if g[0] not in _STOP and g[1] not in _STOP:
            out.add(g)
    return out


def overlap(a: str, b: str) -> float:
    ta, tb = _terms(a), _terms(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _md(date: str) -> str:
    """'2026-6-3' / '6-3' → '6-3'：日期比对只看月日（年份常常一边有一边没有）。"""
    parts = date.split("-")
    return "-".join(parts[-2:])


def _fmt(v: float) -> str:
    return str(int(v)) if v == int(v) else str(v)


def detect(passage: str, facts: list[dict], *, min_overlap: float = 0.12) -> list[dict]:
    """给一段正文和召回的事实（至少要有 id / text / date），产出关系候选。

    每条：{relation, say, fact_ids, unit?, values?}。同一种关系只报最有把握的那条，
    延续报整条线。没有具体的量（数字 / 日期）就不报缺依据——空话没法核。
    """
    pv = extract_values(passage)
    scored = []
    for f in facts:
        text = f.get("text") or ""
        s = overlap(passage, text)
        scored.append((s, f, extract_values(text)))
    related = [(s, f, fv) for s, f, fv in scored if s >= min_overlap]
    if not pv["nums"] and not pv["dates"]:
        # 没有具体的量就没法核冲突 / 印证；但「两条记录说的是同一件事」跟正文有没有数字无关，
        # 只要这段跟它们都沾边（阈值抬高，免得空话也触发）
        m = _merge_candidate([(s, f) for s, f, _fv in related if s >= max(min_overlap, 0.3)])
        return [m] if m else []
    out: list[dict] = []

    # 同一个单位的量：冲突 / 印证 / 延续
    # 一条事实对一个单位的「值」= 它文本里这个单位的最后一个数（「从 300 改到 380」的值是 380）；
    # 所有出现过的数留作印证用。
    by_unit: dict[str, list[tuple[float, dict, float, list[float]]]] = defaultdict(list)
    for s, f, fv in related:
        per_unit: dict[str, list[float]] = defaultdict(list)
        for v, u in fv["nums"]:
            per_unit[u].append(v)
        for u, vals in per_unit.items():
            by_unit[u].append((vals[-1], f, s, vals))
    for pval, unit in pv["nums"]:
        rows = by_unit.get(unit) or []
        if not rows:
            continue
        same = [r for r in rows if any(abs(x - pval) < 1e-9 for x in r[3])]
        if same:
            f = max(same, key=lambda r: r[2])[1]
            out.append({"relation": "corroborated", "unit": unit,
                        "say": f"知识库 {f.get('date') or '某天'} 记的也是 {_fmt(pval)}{unit}。",
                        "fact_ids": [f["id"]], "values": [_fmt(pval) + unit]})
        # 延续：≥2 条事实（不同时间）给了不同的值，你写的是下一个点
        distinct: dict[str, dict] = {}
        ordered = sorted(rows, key=lambda r: r[1].get("date") or "")
        if ordered and len(ordered[0][3]) > 1:          # 最早那条的起点（「从 150 提到 200」的 150）
            distinct.setdefault(_fmt(ordered[0][3][0]), ordered[0][1])
        for v, f, _s, _vals in ordered:
            distinct.setdefault(_fmt(v), f)
        diff = [r for r in rows if abs(r[0] - pval) >= 1e-9]
        if len(ordered) >= 2 and len(distinct) >= 2:      # 一条记录里的「从 300 改到 380」不算线，得是两条不同时间的记录
            chain = [f"{k}{unit}" for k in distinct] + ([f"{_fmt(pval)}{unit}（你写的）"] if _fmt(pval) not in distinct else [])
            out.append({"relation": "continuation", "unit": unit,
                        "say": "这个量在变：" + " → ".join(chain),
                        "fact_ids": [f["id"] for f in distinct.values()], "values": chain})
        elif diff and not same:
            v, f, _s, _vals = max(diff, key=lambda r: r[2])
            out.append({"relation": "conflict", "unit": unit,
                        "say": f"跟知识库 {f.get('date') or '某天'} 的记录不一致：那里是 {_fmt(v)}{unit}，你写的是 {_fmt(pval)}{unit}。",
                        "fact_ids": [f["id"]], "values": [_fmt(v) + unit, _fmt(pval) + unit]})

    # 日期：同一件事（词面重合高）两边的日期不一样 → 冲突；一样 → 印证。
    # 同一条记录已经按数字印证过了，日期就不再单独报一次（实拍：两张一样的印证卡）。
    already = {fid for r in out for fid in r["fact_ids"] if r["relation"] == "corroborated"}
    if pv["dates"]:
        p_md = {_md(d) for d in pv["dates"]}
        strong = [(s, f, fv) for s, f, fv in related if fv["dates"] and s >= max(min_overlap, 0.2)]
        for s, f, fv in sorted(strong, key=lambda r: -r[0])[:3]:
            f_md = {_md(d) for d in fv["dates"]}
            if p_md & f_md:
                if f["id"] in already:
                    break
                out.append({"relation": "corroborated", "unit": "date",
                            "say": f"日期跟知识库 {f.get('date') or '某天'} 的记录一致。",
                            "fact_ids": [f["id"]], "values": sorted(p_md & f_md)})
                break
            out.append({"relation": "conflict", "unit": "date",
                        "say": f"日期跟知识库 {f.get('date') or '某天'} 的记录不一致：那里是 {'、'.join(sorted(f_md))}，你写的是 {'、'.join(sorted(p_md))}。",
                        "fact_ids": [f["id"]], "values": sorted(f_md) + sorted(p_md)})
            break

    # 叠加：同一件事，知识库里还有你没写的条件——别的单位的量、或你这段没写日期而它有。
    # 跟正文同单位的量走上面的冲突 / 印证 / 延续，这里只看正文**没提**的维度。
    p_units = {u for _v, u in pv["nums"]}
    extras: list[tuple[float, dict, list[str]]] = []
    for s, f, fv in related:
        if s < max(min_overlap, 0.2):
            continue
        missing = [_fmt(v) + u for v, u in fv["nums"] if u not in p_units]
        if not pv["dates"]:
            missing += [d for d in fv["dates"]]
        if missing:
            extras.append((s, f, missing))
    if extras:
        extras.sort(key=lambda r: -r[0])
        values: list[str] = []
        for _s, _f, miss in extras[:3]:
            for m in miss:
                if m not in values:
                    values.append(m)
        out.append({"relation": "accumulation", "unit": "",
                    "say": f"知识库里关于这个还有 {len(values)} 个条件你没写：{'、'.join(values[:4])}{'…' if len(values) > 4 else ''}",
                    "fact_ids": [f["id"] for _s, f, _m in extras[:3]], "values": values})

    # 合并：召回的记录里有两条说的是同一件事
    m = _merge_candidate([(s, f) for s, f, _fv in related])
    if m:
        out.append(m)

    # 缺依据：有具体的量，却没有一条沾边的记录
    if not related:
        out.append({"relation": "unsupported", "unit": "",
                    "say": "知识库里没有记录支持这句——不是说它错，是它没根。",
                    "fact_ids": [], "values": [_fmt(v) + u for v, u in pv["nums"]] + pv["dates"]})
    # 去重：同一种关系 + 同一个单位只留一条
    seen = set()
    uniq = []
    for r in out:
        key = (r["relation"], r.get("unit"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    order = {"conflict": 0, "continuation": 1, "unsupported": 2, "accumulation": 3, "merge": 4, "corroborated": 5}
    uniq.sort(key=lambda r: order.get(r["relation"], 9))
    return uniq


def _merge_candidate(related: list[tuple[float, dict]], *, min_pair: float = 0.5) -> dict | None:
    """两条记录词面重合 ≥ min_pair 且不是同一条 → 合并候选。只报最像的一对，早的在前。
    去重是写作者的活，不是抽取器的（docs/agent-native-editor.md §3.3.1）——这里只提议。"""
    best: tuple[float, dict, dict] | None = None
    for i in range(len(related)):
        for j in range(i + 1, len(related)):
            a, b = related[i][1], related[j][1]
            if a["id"] == b["id"]:
                continue
            ta, tb = a.get("text") or "", b.get("text") or ""
            if ta == tb:
                s = 1.0
            else:
                s = overlap(ta, tb)
                # 短句的 min-归一化容易虚高：还要求双向都过半
                if s >= min_pair:
                    ta_, tb_ = _terms(ta), _terms(tb)
                    if len(ta_ & tb_) / max(len(ta_), len(tb_)) < 0.35:
                        continue
            if s >= min_pair and (best is None or s > best[0]):
                best = (s, a, b)
    if not best:
        return None
    _s, a, b = best
    a, b = sorted((a, b), key=lambda f: f.get("date") or "")
    da, db = a.get("date") or "某天", b.get("date") or "某天"
    # 同一天的两条别说成「3-10 和 3-10」（第 134 轮实拍）
    when = f"{da} 有两条" if da == db else f"{da} 和 {db} 这两条"
    return {"relation": "merge", "unit": "",
            "say": f"知识库里 {when}说的像是同一件事，合成一条？",
            "fact_ids": [a["id"], b["id"]], "values": []}
