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

# 单位表。P4（第 771 轮）在 4 篇真实笔记 162 个含数字段上复盘：**71 段的数字没被认成「量」**，
# 因为表里没有 年 / 卡 / 辆 / 秒 / TB / 度 / kW / MW / 平方公里——「100辆矿卡…42.35平方公里…-50度」
# 一个量都抽不出来，连「缺依据」都不判。P7 按那 71 段逐条补。**长的写在前面**（正则按顺序取第一个
# 能匹配的：`个月` 要排在 `个` 前、`平方公里` 排在 `公里` 前、`kWh` 排在 `kW` 前）。
_UNITS = (r"mAh|mm|cm|km|kg|TB|PB|GB|MB|MHz|GHz|Hz|kWh|kW|kV|MW|GW|W|V|tps|fps|ms|"
          r"平方公里|平方米|公里|万吨|万元|亿元|美元|美金|块钱|个月|"
          r"元|万|亿|台|人|天|周|小时|分钟|秒|次|条|页|版|批|套|%|％|"
          r"年|卡|辆|度|吨|米|个|项|家|场|位|名|篇|张|份|倍|轮|件|层|级|期|座|颗|顆|款|种|步|根")
# 「50000+tps」「8+%」「200多家」「2000余套」：数和单位之间的 + / 多 / 余 不挡单位
#
# **`re.I`（P22 #10）**：表里写的是 `kWh` / `kV`，而人手打出来的是 `567kwh`、`10KV`——
# 大小写差一个字母就一个量都抽不出来，那一段连「缺依据」都不判。在真库 482 篇上量过前后
# （`<scratch>/p25/scan_num_ic.py`）：`_NUM` 命中 **2053 → 2059**，新增 6 处、全部逐条读过：
# `10KV 光伏站点` ×3（千伏，对）、`单个电池容量是 567kwh` ×3（千瓦时，对），**误伤 0 处**。
# 特别核过会不会把别的东西当量：`1w`（中文里常写成「1w = 1万」）、`KB`/`Kb`、人名里的字母——
# 全库一处都没有（新增命中只有 `KV` / `kwh` 两个单位）。
_NUM = re.compile(rf"(?<![\d.])(-?\d+(?:\.\d+)?)[+多余]?\s*({_UNITS})(?![A-Za-z])", re.IGNORECASE)
# 开了 `re.I` 就必须把大小写收回来：`by_unit` 是按单位**字符串**分桶的，
# 不归一的话「9kWh」和「567kwh」会落进两个桶，同一个单位互相印证不了——
# 那等于用一个修好的抽取换来一个新的漏判。按单位表里的写法为准。
_UNIT_CANON = {u.lower(): u for u in _UNITS.split("|")}
_UNIT_ALIAS = {"％": "%", "顆": "颗"}
_DATE_FULL = re.compile(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})日?")
_DATE_MD = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日?")
# 月级 / 年级的日期（P4 #5：「6月末/7月」「六月末或七月」「2020年」都不算日期，库里一模一样的话没出来）。
#   `2026年8月` → 2026-8；`7月份` / `6月末` / `6月` → 6；`2020年` → 2020（4 位、19xx/20xx 才算年份，「投入3年」是量）。
_DATE_YM = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月(?!\s*\d)")
_DATE_M = re.compile(r"(?<![\d年])(\d{1,2})\s*月(?:末|初|中|底|份)?(?!\s*\d)")
_DATE_Y = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*年(?!\s*\d{1,2}\s*月)")
_EN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}")
_CJK = re.compile(r"[一-鿿]")
_STOP = set("的了在是和与及或把被对到从这那我们你他她它就也都还又很不没有个一了着过为以及以")
# `<|start|>` 这种转写残留的乱码（P4 表 A #3）被 `_EN` 当成英文词 `start`，跟「why we start this company」
# 一重合就压掉了「缺依据」。查询词和重合度都先剥掉它。
_GARBAGE = re.compile(r"<\|[^|>]*\|>")

# 中文数字 → 阿拉伯数字，只做两处：月份（「六月末」「五月到六月」）和带硬单位的量（「三百台」「二十万」）。
# **单个数字字（「一个」「三类」）不带硬单位不转**——「一个工具」满篇都是，转了每段都成了「量」，
# 印证 / 冲突全是噪声。
_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}
_CN_NUM = re.compile(r"[零〇一二两三四五六七八九十百千]{1,8}")
_CN_MONTH = re.compile(r"(?<!\d)([一二三四五六七八九十]{1,2})\s*月")
_CN_HARD_UNITS = r"台|元|美元|美金|块钱|万|亿|天|周|个月|小时|分钟|人|公里|吨|度|次|条|套|张|份"
# 「统一台账」「唯一条件」「第一人」这种词里的「一」不是数：前面是 统 / 唯 / 单 / 同 / 第 / 每 就不转
_CN_QTY = re.compile(rf"(?<![统唯单同第每])([零〇一二两三四五六七八九十百千]{{1,8}})\s*({_CN_HARD_UNITS})(?![一-鿿]?[月日])")


def cn_to_int(s: str) -> int | None:
    """「三百二十」→ 320、「十五」→ 15、「二十万」→ 200000。不像数字的（「百」单独）回 None。"""
    if not s or not _CN_NUM.fullmatch(s):
        return None
    total, cur = 0, 0
    for ch in s:
        if ch in _CN_DIGIT:
            cur = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            unit = _CN_UNIT[ch]
            if unit >= 10000:
                total = (total + cur) * unit
            else:
                total += (cur if cur else 1) * unit
            cur = 0
        else:
            return None
    return total + cur


def _cn_numerals_to_digits(text: str) -> str:
    """把「六月末」「三百台」换成「6月末」「300台」，其余原样。只在抽量 / 日期前用，不改用户正文。"""
    def _m(m):
        n = cn_to_int(m.group(1))
        return f"{n}月" if n and 1 <= n <= 12 else m.group(0)
    text = _CN_MONTH.sub(_m, text)

    def _q(m):
        n = cn_to_int(m.group(1))
        return f"{n}{m.group(2)}" if n is not None else m.group(0)
    return _CN_QTY.sub(_q, text)


def extract_values(text: str) -> dict:
    """数字（带单位）和日期。日期统一成：年-月-日 / 月-日 / 年-月 / 月 / 年（后三种是 P7 加的月级、年级）。"""
    text = _cn_numerals_to_digits(_GARBAGE.sub(" ", text or ""))
    nums: list[tuple[float, str]] = []
    for v, u in _NUM.findall(text):
        u = _UNIT_CANON.get(u.lower(), u)
        nums.append((float(v), _UNIT_ALIAS.get(u, u)))
    dates: list[str] = []
    for y, m, d in _DATE_FULL.findall(text):
        dates.append(f"{int(y)}-{int(m)}-{int(d)}")
    stripped = _DATE_FULL.sub(" ", text)
    for m, d in _DATE_MD.findall(stripped):
        if 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
            dates.append(f"{int(m)}-{int(d)}")
    stripped = _DATE_MD.sub(" ", stripped)
    for y, m in _DATE_YM.findall(stripped):
        if 1 <= int(m) <= 12:
            dates.append(f"{int(y)}-{int(m)}")
    stripped = _DATE_YM.sub(" ", stripped)
    for m in _DATE_M.findall(stripped):
        if 1 <= int(m) <= 12:
            dates.append(f"{int(m)}")
    for y in _DATE_Y.findall(stripped):
        dates.append(y)
    # 「2020年」既是年份也会被 `_NUM` 当成 2020 年（量）——年份一律按日期算，不算量
    years = {float(y) for y in dates if len(y) == 4 and "-" not in y}
    nums = [(v, u) for v, u in nums if not (u == "年" and v in years)]
    return {"nums": nums, "dates": dates}


def fmt_date(d: str) -> str:
    """给人看的日期：'6' → '6月'，'2020' → '2020年'，'2026-8' → '2026年8月'，'6-3' / '2026-6-3' 原样。"""
    p = d.split("-")
    if len(p) == 1:
        return f"{d}年" if len(d) == 4 else f"{d}月"
    if len(p) == 2 and len(p[0]) == 4:
        return f"{p[0]}年{p[1]}月"
    return d


def _terms(text: str) -> set[str]:
    # 中文那边一直在剔虚词（`_STOP`），英文这边只按长度 ≥2 收——于是
    # `is` `the` `in` `us` 全算实词。实拍（第 614 轮）：
    #   「The German friend app tester is a US MBA student studying in Chicago Booth.」
    #   「The Chicago Booth app tester is supportive.」
    # 共有词 app / booth / chicago / **is** / tester / **the**，一半不带意思，
    # 于是被提议「合成一条」——一条说他是谁、一条说他支持，合了就丢信息。
    # 用召回那边同一份词表（`kb/search._EN_STOP`），别再各写各的。
    from .search import _EN_STOP

    text = _GARBAGE.sub(" ", text or "")
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


def shared_terms(a: str, b: str) -> int:
    """两段共用几个词元。`overlap` 按 min 归一，事实只有 3 个词时撞上 1 个就 0.33——P4 复盘 51 段
    被「wifi」「ai」一个词压掉了「缺依据」。相关与否还要看**绝对数**：至少共用 2 个。"""
    return len(_terms(a) & _terms(b))


# 「沾边」的下限：重合度之外还要共用 ≥ 2 个词元（P4 #4b）。
MIN_SHARED_TERMS = 2


def _fmt(v: float) -> str:
    return str(int(v)) if v == int(v) else str(v)


def _date_keys(dates: list[str]) -> dict[str, set[str]]:
    """一组日期拆成可比对的键：days（月-日）、months（月）、years（年），以及只到月级 / 年级的那部分
    （`mo_only` / `yr_only`）。月级印证允许「同月」（P4 #5：正文「6月末/7月」↔ 库里「6 月末或 7 月」）。"""
    k: dict[str, set[str]] = {"days": set(), "months": set(), "years": set(), "mo_only": set(), "yr_only": set()}
    for d in dates:
        p = d.split("-")
        if len(p) == 3:
            k["days"].add(f"{p[1]}-{p[2]}"); k["months"].add(p[1]); k["years"].add(p[0])
        elif len(p) == 2 and len(p[0]) == 4:
            k["months"].add(p[1]); k["years"].add(p[0]); k["mo_only"].add(p[1])
        elif len(p) == 2:
            k["days"].add(d); k["months"].add(p[0])
        elif len(d) == 4:
            k["years"].add(d); k["yr_only"].add(d)
        else:
            k["months"].add(d); k["mo_only"].add(d)
    return k


def _date_agreement(p: dict[str, set[str]], f: dict[str, set[str]]) -> list[str]:
    """两边日期哪里对上了：先按天，再按月（其中一边只到月级），再按年（其中一边只到年级）。"""
    if p["days"] & f["days"]:
        return sorted(p["days"] & f["days"])
    same_month = (p["mo_only"] & f["months"]) | (f["mo_only"] & p["months"])
    if same_month:
        return [f"{m}月" for m in sorted(same_month, key=int)]
    same_year = (p["yr_only"] & f["years"]) | (f["yr_only"] & p["years"])
    if same_year:
        return [f"{y}年" for y in sorted(same_year)]
    return []


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

# 叠加：没共用单位时至少共用这么多词元（P4 #9）。
ACCUMULATION_MIN_SHARED = 3
# 合并候选两条都要跟正文重合到这个份上（P4 #9）；无量的段落原来就是 0.3。
MERGE_MIN_PASSAGE_OVERLAP = 0.3

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
    p_days = _date_keys(pv["dates"])["days"]

    def _same_quantity(fv: dict) -> bool:
        # 同一个值 + 同一个单位（「199美元」↔「199美元」）、或同一天，本身就是很硬的共用证据——
        # 词面只共用一个词也算沾边。不然「竞品 159 美元、我们 199 美元」对「定价定在 199 美元」判不成印证。
        if any(abs(v - q) < 1e-9 and u == w for v, u in fv["nums"] for q, w in pv["nums"]):
            return True
        return bool(p_days and p_days & _date_keys(fv["dates"])["days"])

    scored = []
    for f in facts:
        text = f.get("text") or ""
        s = overlap(passage, text)
        scored.append((s, f, extract_values(text), shared_terms(passage, text)))
    related = [(s, f, fv) for s, f, fv, n in scored
               if s >= min_overlap and (n >= MIN_SHARED_TERMS or _same_quantity(fv))]
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
        p_keys = _date_keys(pv["dates"])
        # 原来只看重合度 ≥ 0.2；P4 表 A #7 正文「以6月末/7月销售上市窗口为验收边界」对库里
        # 「应该在 6 月末或 7 月会在网站上开始销售产品」共用 销售 / 月末 两个词、重合 0.18——差在这 0.02 上。
        # 改成看**绝对数**：共用 ≥ 2 个词元（`MIN_SHARED_TERMS`）。不再拿 0.2 兜底——短事实只共用一个词也能到 0.33
        # （「2月1号上线」↔「2月1号发工资」），同一天的两件不相干的事会被判成「日期一致」（突变验抓出来的）。
        strong = [(s, f, fv) for s, f, fv in related
                  if fv["dates"] and shared_terms(passage, f.get("text") or "") >= MIN_SHARED_TERMS]
        # **一段里有两个日期、一个对上一个对不上时，冲突要报出来**（P19 #4 / P17 #12）。
        # 原来这个循环在**第一条**事实上就 `break`：重合度最高的那条碰巧是对上的（或者已经按数字
        # 印证过、走 `already` 那条 break），后面那条对不上的就永远轮不到判。实拍（P17 第 3 步）：
        # 「众筹页面定在 3月12号 上线，EVT 样品 4月10 号出」对着库里「3月10号上众筹」+「EVT 是 4月10号」
        # ——圆点画的是绿色「印证 4-10」，而 3-12 跟 3-10 的冲突一个字都没说。
        # 改成把 top-3 都看一遍，印证 / 冲突各留最有把握的一条；两个都在时收尾的 `order`
        # 把冲突排前面（P1-1d 定的顺序，有闸钉着），圆点自然画冲突。
        got_ok = got_bad = False
        # 这一段里已经被**某条记录**对上的那几天：报冲突时不该再把它们算进「你写的是」
        agreed_days: set[str] = set()
        ordered_strong = sorted(strong, key=lambda r: -r[0])[:3]
        for _s, _f, _fv in ordered_strong:
            agreed_days |= p_keys["days"] & _date_keys(_fv["dates"])["days"]
        for s, f, fv in ordered_strong:
            if got_ok and got_bad:
                break
            f_keys = _date_keys(fv["dates"])
            agreed = _date_agreement(p_keys, f_keys)
            if agreed:
                if got_ok or f["id"] in already:
                    continue
                got_ok = True
                out.append({"relation": "corroborated", "unit": "date",
                            "say": f"日期跟知识库 {f.get('date') or '某天'} 的记录一致（{'、'.join(agreed)}）。",
                            "fact_ids": [f["id"]], "values": agreed})
                continue
            # **只有冲突要过那两道更严的关，印证不用。** 第一版把门槛加在
            # `strong` 上，连「日期一致」这种无害的印证一起挡了——单测当场抓到
            # （`test_corroborated_and_date_conflict`）。判据越严，越要只严在
            # 该严的那一侧：冲突卡上摆着「新的取代旧的」，印证卡上什么都没有。
            #
            # 实测的日期误报跟数字那边同一类：「2月1号之前上线」对上
            # 「2月10号之前把 UI 2.0 刷出来」，两件不同的事各有各的日期，重合度 0.27。
            # 月级 / 年级的日期不判冲突——「7月」对「7月21日」不是不一致，是粒度不同。
            if got_bad or not (s >= conflict_min_overlap and p_keys["days"] and f_keys["days"]):
                continue
            # 报冲突时**只列真对不上的那几个日期**：这一段里已经跟别的记录对上的那个（4-10）
            # 摆进「你写的是」里，读起来像是它也错了（原来一股脑列 `p_keys["days"]` 全部）。
            mine = sorted(p_keys["days"] - f_keys["days"] - agreed_days) or sorted(p_keys["days"] - f_keys["days"]) or sorted(p_keys["days"])
            got_bad = True
            out.append({"relation": "conflict", "unit": "date",
                        "say": f"日期跟知识库 {f.get('date') or '某天'} 的记录不一致：那里是 {'、'.join(sorted(f_keys['days']))}，你写的是 {'、'.join(mine)}。",
                        "fact_ids": [f["id"]], "values": sorted(f_keys["days"]) + mine})

    # 叠加：同一件事，知识库里还有你没写的条件——别的单位的量、或你这段没写日期而它有。
    # 跟正文同单位的量走上面的冲突 / 印证 / 延续，这里只看正文**没提**的维度。
    # P4 #9 实拍三张叠加卡全不相干（「用户规模超400万」叠加「我10秒打一个，过10分钟又打了一下」）：
    # 光看重合度 ≥ 0.2 不够，还得**跟正文共用一个单位、或共用 ≥ 3 个词元**，才算「同一件事」。
    p_units = {u for _v, u in pv["nums"]}
    extras: list[tuple[float, dict, list[str]]] = []
    for s, f, fv in related:
        if s < max(min_overlap, 0.2):
            continue
        same_unit = any(u in p_units for _v, u in fv["nums"])
        if not same_unit and shared_terms(passage, f.get("text") or "") < ACCUMULATION_MIN_SHARED:
            continue
        missing = [_fmt(v) + u for v, u in fv["nums"] if u not in p_units]
        if not pv["dates"]:
            missing += [fmt_date(d) for d in fv["dates"]]
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

    # 合并：召回的记录里有两条说的是同一件事。**两条都得跟正文沾边（≥ 0.3）**——P4 #9 实拍
    # 一张合并卡是「这个也是新加坡的」×2（转写成「社会社会」的废录音），跟正文那段反欺诈毫无关系。
    m = _merge_candidate([(s, f) for s, f, _fv in related if s >= MERGE_MIN_PASSAGE_OVERLAP])
    if m:
        out.append(m)

    # 缺依据：有具体的量，却**没有一条记录带同样的量**（同单位的数、或日期）。
    # 原来是「related 非空就不报」——P4 复盘 51 段被一个弱重合压掉：正文「每年投入营收的10%…21万员工」
    # 的 top 事实是「他的通信就是要通过WiFi」（只因为 wifi），于是既不缺依据、也判不出别的 → 空。
    # 「有出处」= 已经有一条记录**对上了**这段里的某个量或日期（印证 / 冲突 / 延续三种之一）。
    # 只是同单位、或只是也带个日期，不算——那是「沾边」，不是「带同样的量」。
    #
    # **「缺依据」分两档，是两件不同的事**（P22 #8 / P25 #4）。P7 修好了「该有点没点」之后，
    # 真库最长那篇（`715266c1fcb4`，26.7k 字的展厅讲解词）136 个含数字段挂出 **106 个灰点**，
    # 逐条读过（`<scratch>/p25/read_unsupported.py`）：
    #   · **89 段 `no_record`**：召回回来的 8 条**没有一条**过沾边门槛——昇腾份额 38%、NVL72 单柜
    #     72 卡、深圳 25 万路摄像头，知识库里根本没有这个话题。这一段一个点，说的不是「这一段」
    #     的事，是「这篇笔记跟知识库不搭界」这一件事**说了 89 遍**——页边一整列灰圈 = 噪声。
    #   · **17 段 `no_value`**：有沾边的记录，但**那条记录里没有这段的量**（「每年投入营收的 10%…
    #     21 万员工」沾着库里「把更多资金投入研发」）。这一条才是「这个数还没有出处，值得去核」。
    # 判法零模型、就是 `related` 空不空，本来就算好了；这里把它记进候选，前端据此决定画不画点
    # （`frontend/src/editor/marginMemory.ts` `DOT_WORTHY`）。**右栏的关系卡两档都照说**——
    # 光标停在那一段上仍然告诉你「知识库里没有记录支持这句」，只是不在页边逐段画。
    supported = any(r["relation"] in ("conflict", "continuation", "corroborated") for r in out)
    if not supported:
        out.append({"relation": "unsupported", "unit": "",
                    "why": "no_record" if not related else "no_value",
                    "say": ("知识库里没有记录支持这句——不是说它错，是它没根。" if not related
                            else "知识库里沾边的记录都没带这段里的量——这几个数还没有出处。"),
                    "fact_ids": [], "values": [_fmt(v) + u for v, u in pv["nums"]] + [fmt_date(d) for d in pv["dates"]]})
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
