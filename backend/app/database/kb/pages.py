"""知识库各节点打开之后**里面是什么**（docs/kb-experience-plan.md §3）。

跟 virtual_tree.py 同一纪律：只读 ``mem._index()``，不碰 I/O，手搭 Store/Vocab
就能测。每个函数返回一页要画的数据——数字、月度计数、邻居、事实列表。

月度计数只给**近 12 个月**（有事实的月份少于 12 个就给全）：首页那张图是「最近
在往里装什么」，不是全史；全史在时间线页。
"""

from __future__ import annotations


from collections import Counter, defaultdict
from datetime import date as _date

from .who import is_speaker_tag, norm_who
from . import entities as entities_mod
from .units import materials, part_labels, parts_of

MONTHS_ON_DASHBOARD = 12
MONTHS_ON_PAGE = 24
TOP_N = 8
FACT_PAGE = 50



def _speakers(facts, top_n: int) -> list[dict]:
    """按归一化后的说话人分组计数，显示最常见的原写法（kb/who.py）。"""
    by_key: Counter = Counter()
    spelling: dict[str, Counter] = defaultdict(Counter)
    for f in facts:
        k = norm_who(f.who)
        by_key[k] += 1
        spelling[k][f.who or ""] += 1
    return [{"who": (spelling[k].most_common(1)[0][0] or "?"), "facts": n} for k, n in by_key.most_common(top_n)]


def _fact(f, vocab=None, groups=None) -> dict:
    d = {"id": f.id, "text": f.text, "when": f.when or "", "kind": f.kind or "",
         "who": f.who or "", "conf": f.conf or "", "topics": list(f.topics),
         "entities": list(f.entities), "unit": f.unit or ""}
    # 事实卡上的实体 chip 之前显示的是代码（facebook / speaker_a），带上显示名
    if vocab is not None:
        d["entity_names"] = [_entity_name(vocab, c, groups) for c in f.entities]
    # 从笔记摄入的：知识库页面反链回那篇（session 命名见 routers/ingest.py）
    nid = note_id_of_unit(f.unit)
    if nid:
        d["note_id"] = nid
        d["manual"] = f.unit.endswith("-manual")
    return d


def note_id_of_unit(unit: str) -> str:
    """`note-<noteId>-<块号|manual>` → noteId；不是笔记来的给空串。"""
    if not unit.startswith("note-"):
        return ""
    rest = unit[5:]
    return rest.rsplit("-", 1)[0] if "-" in rest else ""



# 窗口最多能往未来伸几个月。事实里的日期有相当一部分是**计划**（「8 月 5 日 DVT」
# 「7 月上市」），这是这个产品的常态，所以未来月份得画出来。但不能让它无界：
# 窗口的右端原本直接取「有数据的最晚月份」，于是笔记里一句「2028 年上市」就能把
# 整张图平移十几个月，2026 年的真实月份一根不剩。第 124 轮修过镜像的另一半——
# 一条 2005 年的错抽日期把横轴拉成 2005-11 → 2026-12——这一侧当时没修。
FUTURE_MONTHS = 3


def _month_add(ym: str, delta: int) -> str:
    y, m = (int(x) for x in ym.split("-"))
    n = y * 12 + (m - 1) + delta
    return f"{n // 12:04d}-{n % 12 + 1:02d}"


def _months(facts, last: int | None = None, today: str | None = None) -> list[dict]:
    """按月计数。``last`` 给了就是**连续的**最近 N 个日历月（没数据的月份补 0），而不是「有数据
    的最近 N 个月」——后者会把一条 2005 年的错抽日期和 2026 年并排画成等宽的条，横轴写着
    2005-11 → 2026-12，看不出任何形状（第 124 轮实拍 work 主题页）。不给 ``last`` = 全部有数据的月。

    右端最远只到「这个月 + ``FUTURE_MONTHS``」：计划里的未来日期要画得出来，但一条
    远期日期不该把整个窗口拖走。手上全是旧数据时（最晚的月份就在过去）照旧贴着数据的
    右端走——那种情况下锚在今天只会画出一排空条，然后被下面的空月裁剪全部吃掉。
    """
    c = Counter(f.when[:7] for f in facts if f.when)
    if not c:
        return []
    if not last:
        return [{"month": m, "facts": n} for m, n in sorted(c.items())]
    now = today or _date.today().strftime("%Y-%m")
    y, m = (int(x) for x in min(max(c), _month_add(now, FUTURE_MONTHS)).split("-"))
    months = []
    for _ in range(last):
        months.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()
    rows = [{"month": mo, "facts": c.get(mo, 0)} for mo in months]
    # 开头一串空月份砍掉：一个只有近三个月数据的主题不该画 21 根空条
    while rows and rows[0]["facts"] == 0:
        rows.pop(0)
    return rows


def _page(facts, limit: int, offset: int, vocab=None) -> tuple[list[dict], int]:
    rows = sorted(facts, key=lambda f: (f.when or "", f.id), reverse=True)
    return [_fact(f, vocab) for f in rows[offset:offset + limit]], len(rows)


def annotate(mem, rows: list[dict]) -> list[dict]:
    """给一页事实带上生命周期：被哪条取代（superseded_by）、是不是合并进去的（merged）。
    之前只有实体页带，主题页 / 会议页 / 某一天 / 事实表上一条已被取代的记录看着跟现行的一样。"""
    if rows:
        # 实体 chip 一律显示代表名（memo cat / MemoCat / memo_cat 都是 MemoCat，kb/entities.py）
        try:
            store, vocab = mem._index()
            g = entities_mod.for_store(store, vocab)
            for r in rows:
                if r.get("entities"):
                    r["entity_names"] = [g.name(c) for c in r["entities"]]
        except Exception:      # noqa: BLE001 — 假的 mem（测试）没有索引就跳过
            pass
    if not rows or not hasattr(mem, "fact_attrs"):
        return rows
    superseded = mem.fact_attrs("superseded_by")
    merged = mem.fact_attrs("merged")
    for row in rows:
        by = superseded.get(row["id"])
        if by:
            row["superseded_by"] = by
            if merged.get(row["id"]):
                row["merged"] = True
    return rows


def _entity_name(vocab, code: str, groups=None) -> str:
    """实体显示名。给了 groups 就用代表的名字（memo_cat / memocat 都显示成 MemoCat，kb/entities.py）。"""
    if groups is not None:
        return groups.name(code)
    e = vocab.entities.get(code)
    return (e.name or e.code) if e else code


# ----------------------------------------------------------------- 首页

def dashboard(mem) -> dict:
    store, vocab = mem._index()
    facts = list(store.facts.values())
    units = list(store.units.values())
    dates = sorted(f.when for f in facts if f.when)

    # 主题 Top 用闭包计数（含子主题），只看一级主题——126 个主题平铺出来看不出形状
    # 按「有多少条不同的事实」数，不是把闭包里每个主题的直接计数加起来：一条事实同时挂
    # work 和 work_marketing 会被加两次，首页 work 6151、主题页 6034（第 207 轮实拍）
    by_topic: dict[str, set[str]] = defaultdict(set)
    for f in facts:
        for c in f.topics:
            by_topic[c].add(f.id)
    roots = [t for t in vocab.topics.values() if not any(p in vocab.topics for p in t.parents)]
    top_topics = []
    for t in roots:
        closure = vocab.downset(t.code, include_candidates=True) or {t.code}
        n = len(set().union(*(by_topic.get(c, set()) for c in closure)))
        if n:
            top_topics.append({"code": t.code, "facts": n,
                               "children": sum(1 for x in vocab.topics.values() if t.code in x.parents)})
    top_topics.sort(key=lambda r: -r["facts"])

    groups = entities_mod.for_store(store, vocab)
    ent = Counter(groups.canon(c) for f in facts for c in set(groups.canon(x) for x in f.entities))
    # **说话人标签先剔掉再取前 N。** 之前是后端取前 8、前端再把 speaker a / 说话人 2
    # 这类滤掉——**先截断后过滤**，用户看到几个全看运气：真实库里前 8 个实体有 5 个
    # 是说话人标签，首页「实体」那栏只剩 3 个 chip，旁边「主题」有 6 个（第 615 轮
    # 截图实拍）。说话人在首页本来就有自己那一栏（`speakers`），不该再占实体的名额。
    # 其他地方（统计数字、知识库树）早就这么做了，只有这一处没跟上。
    top_entities = [{"code": c, "name": groups.name(c), "facts": n}
                    for c, n in ent.most_common()
                    if not is_speaker_tag(c) and not is_speaker_tag(groups.name(c))][:TOP_N]

    unit_facts = Counter(f.unit for f in facts if f.unit)
    recent_units = []
    for m in materials(u for u in units if u.date)[:6]:      # 按材料列，跟树一致（第 267 轮）
        n = len(m["parts"])
        recent_units.append({"id": m["parts"][0].id, "date": m["date"],
                             "title": f"{m['title']}（{n} 段）" if n > 1 else m["title"],
                             "facts": sum(unit_facts.get(p.id, 0) for p in m["parts"])})

    return {
        "stats": {"facts": len(facts), "topics": len(vocab.topics), "entities": sum(1 for c, e in vocab.entities.items() if not is_speaker_tag(c) and not is_speaker_tag(getattr(e, "name", ""))),
                  "units": len(units), "lines": len(store.lines),
                  "start_date": dates[0] if dates else "", "end_date": dates[-1] if dates else ""},
        "months": _months(facts, MONTHS_ON_DASHBOARD),
        "top_topics": top_topics[:TOP_N],
        "top_entities": top_entities,
        "recent_units": recent_units,
        "kinds": [{"kind": k or "?", "facts": n} for k, n in Counter(f.kind for f in facts).most_common()],
        "speakers": _speakers(facts, 6),
    }


# ----------------------------------------------------------------- 主题页

def topic_page(mem, code: str, limit: int = FACT_PAGE, offset: int = 0) -> dict | None:
    store, vocab = mem._index()
    t = vocab.topics.get(code)
    if t is None:
        return None
    closure = vocab.downset(code, include_candidates=True) or {code}
    facts = [f for f in store.facts.values() if set(f.topics) & closure]
    direct = Counter(c for f in facts for c in f.topics)
    children = []
    for x in vocab.topics.values():
        if code in x.parents:
            sub = vocab.downset(x.code, include_candidates=True) or {x.code}
            children.append({"code": x.code, "facts": sum(direct.get(c, 0) for c in sub)})
    children.sort(key=lambda r: -r["facts"])
    _g = entities_mod.for_store(store, vocab)
    ents = Counter(c for f in facts for c in {_g.canon(x) for x in f.entities})   # 同一实体的几种写法算一个
    page, total = _page(facts, limit, offset, vocab)
    annotate(mem, page)
    return {
        "code": code, "aliases": sorted(t.aliases), "parents": [p for p in sorted(t.parents) if p in vocab.topics],
        "status": t.status, "facts_total": total, "facts": page, "limit": limit, "offset": offset,
        "months": _months(facts, MONTHS_ON_PAGE), "children": children,
        "entities": [{"code": c, "name": _entity_name(vocab, c), "facts": n} for c, n in ents.most_common(TOP_N)],
        "kinds": [{"kind": k or "?", "facts": n} for k, n in Counter(f.kind for f in facts).most_common()],
    }


# ----------------------------------------------------------------- 实体页

def resolve_entity_code(vocab, code: str) -> str | None:
    """实体代码容错：`Facebook` / `Speaker A` 这类显示名或大小写不同的写法也能落到
    `facebook` / `speaker_a`。实拍拿显示名开实体页得到「没有这个实体」。"""
    if code in vocab.entities:
        return code
    norm = code.strip().lower().replace(" ", "_")
    if norm in vocab.entities:
        return norm
    for c, e in vocab.entities.items():
        if (e.name or "").strip().lower() == code.strip().lower():
            return c
        if any(a.strip().lower() == code.strip().lower() for a in (e.aliases or ())):
            return c
    return None


def evolution_chains(facts, vocab=None, *, min_len: int = 2, top: int = 5) -> list[dict]:
    """「这些事怎么变的」：按 obj（KITE 抽取给的对象类）把有日期的事实串成线，只留 ≥ min_len
    条的，按长度排。实体页 / 主题页用——20406 条平铺时用户看到的是三条互相矛盾的日期，
    不知道哪条算数；串成线至少能看出先后。"""
    by_obj: dict[str, list] = defaultdict(list)
    for f in facts:
        if not f.when:
            continue
        for o in f.obj:
            by_obj[o].append(f)
    chains = []
    for o, fs in by_obj.items():
        if len(fs) < min_len:
            continue
        fs = sorted(fs, key=lambda f: (f.when, f.id))
        chains.append({"obj": o, "facts": [_fact(f, vocab) for f in fs[-8:]], "total": len(fs)})
    chains.sort(key=lambda c: -c["total"])
    return chains[:top]


def entity_page(mem, code: str, limit: int = FACT_PAGE, offset: int = 0) -> dict | None:
    store, vocab = mem._index()
    code = resolve_entity_code(vocab, code) or code
    e = vocab.entities.get(code)
    if e is None:
        return None
    groups = entities_mod.for_store(store, vocab)
    code = groups.canon(code)                      # 任何一种写法进来都落到代表
    e = vocab.entities.get(code) or e
    members = set(groups.members(code))
    facts = [f for f in store.facts.values() if members & set(f.entities)]
    topics = Counter(c for f in facts for c in f.topics)
    page, total = _page(facts, limit, offset, vocab)
    annotate(mem, page)
    return {
        "code": code, "name": groups.name(code), "type": e.etype or "", "aliases": sorted(e.aliases),
        "variants": groups.variants(code),          # 同一实体的其它写法（规则归组，kb/entities.py）
        "relations": [{"rel": r, "target": tgt, "target_name": _entity_name(vocab, tgt)} for r, tgt in sorted(e.rels)],
        "facts_total": total, "facts": page, "limit": limit, "offset": offset,
        "chains": evolution_chains(facts, vocab),
        "months": _months(facts, MONTHS_ON_PAGE),
        "topics": [{"code": c, "facts": n} for c, n in topics.most_common(TOP_N)],
    }


# ----------------------------------------------------------------- 时间线

def timeline(mem) -> list[dict]:
    """月 → 日 的计数。日期字符串字典序就是时间序。"""
    store, _vocab = mem._index()
    by_day: dict[str, dict] = defaultdict(lambda: {"facts": 0, "units": 0})
    for f in store.facts.values():
        if f.when:
            by_day[f.when]["facts"] += 1
    for u in store.units.values():
        if u.date:
            by_day[u.date]["units"] += 1
    months: dict[str, dict] = {}
    for day in sorted(by_day):
        m = months.setdefault(day[:7], {"month": day[:7], "facts": 0, "units": 0, "days": []})
        d = by_day[day]
        m["facts"] += d["facts"]; m["units"] += d["units"]
        m["days"].append({"date": day, "facts": d["facts"], "units": d["units"]})
    return list(months.values())


# ----------------------------------------------------------------- 会议页

def unit_page(mem, unit_id: str, limit: int = FACT_PAGE, offset: int = 0) -> dict | None:
    store, vocab = mem._index()
    u = store.units.get(unit_id)
    if u is None:
        return None
    facts = [f for f in store.facts.values() if f.unit == unit_id]
    page, total = _page(facts, limit, offset, vocab)
    annotate(mem, page)
    label = part_labels(list(store.units.values())).get(unit_id) or u.title or ""
    topics = Counter(c for f in facts for c in f.topics)
    _g = entities_mod.for_store(store, vocab)
    ents = Counter(c for f in facts for c in {_g.canon(x) for x in f.entities})   # 同一实体的几种写法算一个
    parts = parts_of(store.units.values(), unit_id)
    # 一条事实都没抽出来的段（短录音 / 单句，第 287 轮实拍「没有事实。」一片空）：把原话给出来，
    # 页面上至少看得到这段说了什么。有事实的段原话走每条事实自己的「原话」，这里不重复给。
    raw_lines = []
    if total == 0:
        raw_lines = [{"who": getattr(ln, "who", "") or "", "text": getattr(ln, "text", "") or ""}
                     for ln in store.lines.values() if getattr(ln, "unit", "") == unit_id][:50]
    return {
        "id": u.id, "date": u.date or "", "title": label,
        "lines": raw_lines,
        # 分段导航：同一份材料的各段（第 267 轮）
        "parts": [{"id": pid, "k": k} for k, pid in enumerate(parts, 1)],
        "part_index": parts.index(unit_id) + 1, "part_total": len(parts),
        "speakers": sorted(s["who"] for s in _speakers([f for f in facts if f.who], 50)),
        "facts_total": total, "facts": page, "limit": limit, "offset": offset,
        "topics": [{"code": c, "facts": n} for c, n in topics.most_common(TOP_N)],
        "entities": [{"code": c, "name": _entity_name(vocab, c), "facts": n} for c, n in ents.most_common(TOP_N)],
    }


def day_facts(mem, date: str, limit: int = FACT_PAGE) -> list[dict]:
    """时间线上点开一天。"""
    store, vocab = mem._index()
    page, _ = _page([f for f in store.facts.values() if f.when == date], limit, 0, vocab)
    return annotate(mem, page)
