"""知识库各节点打开之后**里面是什么**（docs/kb-experience-plan.md §3）。

跟 virtual_tree.py 同一纪律：只读 ``mem._index()``，不碰 I/O，手搭 Store/Vocab
就能测。每个函数返回一页要画的数据——数字、月度计数、邻居、事实列表。

月度计数只给**近 12 个月**（有事实的月份少于 12 个就给全）：首页那张图是「最近
在往里装什么」，不是全史；全史在时间线页。
"""

from __future__ import annotations

from collections import Counter, defaultdict

MONTHS_ON_DASHBOARD = 12
MONTHS_ON_PAGE = 24
TOP_N = 8
FACT_PAGE = 50


def _fact(f, vocab=None) -> dict:
    d = {"id": f.id, "text": f.text, "when": f.when or "", "kind": f.kind or "",
         "who": f.who or "", "conf": f.conf or "", "topics": list(f.topics),
         "entities": list(f.entities), "unit": f.unit or ""}
    # 事实卡上的实体 chip 之前显示的是代码（facebook / speaker_a），带上显示名
    if vocab is not None:
        d["entity_names"] = [_entity_name(vocab, c) for c in f.entities]
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



def _months(facts, last: int | None = None) -> list[dict]:
    c = Counter(f.when[:7] for f in facts if f.when)
    rows = [{"month": m, "facts": n} for m, n in sorted(c.items())]
    return rows[-last:] if last else rows


def _page(facts, limit: int, offset: int, vocab=None) -> tuple[list[dict], int]:
    rows = sorted(facts, key=lambda f: (f.when or "", f.id), reverse=True)
    return [_fact(f, vocab) for f in rows[offset:offset + limit]], len(rows)


def annotate(mem, rows: list[dict]) -> list[dict]:
    """给一页事实带上生命周期：被哪条取代（superseded_by）、是不是合并进去的（merged）。
    之前只有实体页带，主题页 / 会议页 / 某一天 / 事实表上一条已被取代的记录看着跟现行的一样。"""
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


def _entity_name(vocab, code: str) -> str:
    e = vocab.entities.get(code)
    return (e.name or e.code) if e else code


# ----------------------------------------------------------------- 首页

def dashboard(mem) -> dict:
    store, vocab = mem._index()
    facts = list(store.facts.values())
    units = list(store.units.values())
    dates = sorted(f.when for f in facts if f.when)

    # 主题 Top 用闭包计数（含子主题），只看一级主题——126 个主题平铺出来看不出形状
    direct = Counter(c for f in facts for c in f.topics)
    roots = [t for t in vocab.topics.values() if not any(p in vocab.topics for p in t.parents)]
    top_topics = []
    for t in roots:
        closure = vocab.downset(t.code, include_candidates=True) or {t.code}
        n = sum(direct.get(c, 0) for c in closure)
        if n:
            top_topics.append({"code": t.code, "facts": n,
                               "children": sum(1 for x in vocab.topics.values() if t.code in x.parents)})
    top_topics.sort(key=lambda r: -r["facts"])

    ent = Counter(c for f in facts for c in f.entities)
    top_entities = [{"code": c, "name": _entity_name(vocab, c), "facts": n} for c, n in ent.most_common(TOP_N)]

    unit_facts = Counter(f.unit for f in facts if f.unit)
    recent = sorted((u for u in units if u.date), key=lambda u: (u.date, u.id), reverse=True)[:6]
    recent_units = [{"id": u.id, "date": u.date, "title": u.title or "", "facts": unit_facts.get(u.id, 0)} for u in recent]

    return {
        "stats": {"facts": len(facts), "topics": len(vocab.topics), "entities": len(vocab.entities),
                  "units": len(units), "lines": len(store.lines),
                  "start_date": dates[0] if dates else "", "end_date": dates[-1] if dates else ""},
        "months": _months(facts, MONTHS_ON_DASHBOARD),
        "top_topics": top_topics[:TOP_N],
        "top_entities": top_entities,
        "recent_units": recent_units,
        "kinds": [{"kind": k or "?", "facts": n} for k, n in Counter(f.kind for f in facts).most_common()],
        "speakers": [{"who": w or "?", "facts": n} for w, n in Counter(f.who for f in facts).most_common(6)],
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
    ents = Counter(c for f in facts for c in f.entities)
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
    facts = [f for f in store.facts.values() if code in f.entities]
    topics = Counter(c for f in facts for c in f.topics)
    page, total = _page(facts, limit, offset, vocab)
    annotate(mem, page)
    return {
        "code": code, "name": e.name or e.code, "type": e.etype or "", "aliases": sorted(e.aliases),
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
    topics = Counter(c for f in facts for c in f.topics)
    ents = Counter(c for f in facts for c in f.entities)
    return {
        "id": u.id, "date": u.date or "", "title": u.title or "",
        "speakers": sorted({f.who for f in facts if f.who}),
        "facts_total": total, "facts": page, "limit": limit, "offset": offset,
        "topics": [{"code": c, "facts": n} for c, n in topics.most_common(TOP_N)],
        "entities": [{"code": c, "name": _entity_name(vocab, c), "facts": n} for c, n in ents.most_common(TOP_N)],
    }


def day_facts(mem, date: str, limit: int = FACT_PAGE) -> list[dict]:
    """时间线上点开一天。"""
    store, vocab = mem._index()
    page, _ = _page([f for f in store.facts.values() if f.when == date], limit, 0, vocab)
    return annotate(mem, page)
