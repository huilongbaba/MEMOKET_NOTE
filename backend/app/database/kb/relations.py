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
    # 中文那边一直在剔虚词（`_STOP`），英文这边只按长度 ≥2 收——于是
    # `is` `the` `in` `us` 全算实词。实拍（第 614 轮）：
    #   「The German friend app tester is a US MBA student studying in Chicago Booth.」
    #   「The Chicago Booth app tester is supportive.」
    # 共有词 app / booth / chicago / **is** / tester / **the**，一半不带意思，
    # 于是被提议「合成一条」——一条说他是谁、一条说他支持，合了就丢信息。
    # 用召回那边同一份词表（`kb/search._EN_STOP`），别再各写各的。
    from .search import _EN_STOP

    out = {w.lower() for w in _EN.findall(text)
           if len(w) >= 2 and w.lower() not in _EN_STOP}
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


# 判「冲突」要比判「沾边」严得多。**它是这套系统做出的最有破坏性的判断**——
# 冲突卡上摆着「新的取代旧的」，点一下就把一条正确的事实作废掉。原来它跟
# 「这两条有没有关系」共用同一个 0.12。
#
# 在 terrence 的真库上量过（20406 条，抽 2500 条各自当新写的一段跑一遍，
# 第 678 轮）：只触发 14 次，按重合度读一遍——
#   < 0.20（5 条）：全错。「差300元」对上「成本要5元美金」；「只有5%的场合
#           可以录音」对上「95%以上没问题」（还正反各报一次）。
#   0.20–0.35（4 条）：3 错 1 勉强。「2月1号上线」对上「2月10号刷出 UI 2.0」。
#   0.35–0.60（2 条）：同一对，勉强算真的。
#   ≥ 0.60（3 条）：有真的——「open rate 6.8%」对上「过去两周都超过 18%」。
# 0.35 这条线砍掉 9 条里全部明确错的，留下勉强的和真的。
CONFLICT_MIN_OVERLAP = 0.35

# **试过一条「词元太少不判冲突」，撤了——记在这儿免得有人再试一遍。**
# 起因是实测到一条 overlap=1.00 的冲突：「emc 15美金64 G。」对上「…故意跟 EMC
# 差个 5 美金左右的一个趋势」，前者只切出 {emc, 美金} 两个词元，两个都在对面。
# 看起来像「分母太小、比值没意义」，于是加了「两边都要 ≥4 个词元」。
# 但单测当场抓到它砍掉了一条**真**冲突：「DVT 定在 9 月 1 日。」只有
# {dvt, 月日} 两个词元，而它跟「DVT 从 6 月 3 日调整到 8 月 5 日」是货真价实
# 的冲突。回头看，emc 那条误报的真正原因根本不是词元少——那两句**确实都在说
# EMC 的价钱**，错在一个是差价、一个是单价。**规则在一个例子上答对，但答对的
# 理由不成立**，那就不是规则。


def detect(passage: str, facts: list[dict], *, min_overlap: float = 0.12,
           conflict_min_overlap: float = CONFLICT_MIN_OVERLAP) -> list[dict]:
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
            # **这一段里另一个同单位的数已经跟它对上了，就不要再报冲突。**
            # 真实误报（第 678 轮，新用户导入两篇会议记录后的冲突收件箱实拍）：
            #   记录：「这一版产品的定价定在 199 美元」
            #   新写：「竞品 Plaud 的同档位价格是 159 美元，而我们的价格是 199 美元」
            # 循环对 `pv["nums"]` 里的每个数各判一次，159 那次判成冲突、199 那次
            # 判成印证——**对同一条事实、同一个单位同时说「你不同意」和「你也这么说」**。
            # 那句话根本没有反驳知识库，它在补一个别人的数。
            diff = [r for r in diff if r[2] >= conflict_min_overlap]
            if not diff:
                continue
            agreed = {r[1]["id"] for r in rows
                      if any(abs(x - q) < 1e-9 for x in r[3] for q, u2 in pv["nums"] if u2 == unit)}
            diff = [r for r in diff if r[1]["id"] not in agreed]
            if not diff:
                continue
            v, f, _s, _vals = max(diff, key=lambda r: r[2])
            out.append({"relation": "conflict", "unit": unit,
                        "say": f"跟知识库 {f.get('date') or '某天'} 的记录不一致：那里是 {_fmt(v)}{unit}，你写的是 {_fmt(pval)}{unit}。",
                        "fact_ids": [f["id"]], "values": [_fmt(v) + unit, _fmt(pval) + unit]})

    # **同一条事实只报一次冲突。** 实测（第 678 轮）：「一台霍克成本四十美金,
    # 40美金要300块钱」对着同一条记录报了两张卡（100块钱↔300块钱、6美金↔40美金）
    # ——同一句话、同一条记录，没有理由让用户分诊两遍。留重合度最高的那条。
    seen: set[str] = set()
    deduped = []
    for r in out:
        if r["relation"] == "conflict":
            fid = r["fact_ids"][0]
            if fid in seen:
                continue
            seen.add(fid)
        deduped.append(r)
    out = deduped

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
            # **只有冲突要过那两道更严的关，印证不用。** 第一版把门槛加在
            # `strong` 上，连「日期一致」这种无害的印证一起挡了——单测当场抓到
            # （`test_corroborated_and_date_conflict`）。判据越严，越要只严在
            # 该严的那一侧：冲突卡上摆着「新的取代旧的」，印证卡上什么都没有。
            #
            # 实测的日期误报跟数字那边同一类：「2月1号之前上线」对上
            # 「2月10号之前把 UI 2.0 刷出来」，两件不同的事各有各的日期，重合度 0.27。
            if s >= conflict_min_overlap:
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


# 双向重合的下限。`overlap` 用 min 归一，短句被长句「包住」时会虚高——
# 「Speaker A's cohort group is 100 people.」和「Speaker C says there are Google
# people in there.」min 归一有 0.5，可它们只是共用了主语。
#
# 0.55 是量出来的（第 614 轮，真实库 work / project / learning / personal 四个
# 主题 800 条事实两两比）：双向重合 0.25~0.50 那一大段（约 700 对）抽查**全是**
# 「同一个主语的不同陈述」；0.57 往上才开始出现真重复（「Colin's father dreams
# of his wife coming home to his garden.」vs「Colin's father dreams of his wife.」），
# 0.7 往上抽查全是真的。原来的 0.35 把那一整段都放行了。
#
# 代价是会漏掉少数真重复（0.5 那档里有一对是真的）。这个取舍是有意的：
# 这里**只提议**，漏一条提议没什么，提错一条要用户来挡。
MIN_TWO_WAY = 0.55


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
                    if len(ta_ & tb_) / max(len(ta_), len(tb_)) < MIN_TWO_WAY:
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
