"""知识库各节点打开之后**里面是什么**（docs/kb-experience-plan.md §3）。

跟 virtual_tree.py 同一纪律：只读 ``mem._index()``，不碰 I/O，手搭 Store/Vocab
就能测。每个函数返回一页要画的数据——数字、月度计数、邻居、事实列表。

月度计数只给**近 12 个月**（有事实的月份少于 12 个就给全）：首页那张图是「最近
在往里装什么」，不是全史；全史在时间线页。
"""

from __future__ import annotations

from collections import Counter, defaultdict

MONTHS_ON_DASHBOARD = 12
TOP_N = 8
FACT_PAGE = 50


def _fact(f) -> dict:
    return {"id": f.id, "text": f.text, "when": f.when or "", "kind": f.kind or "",
            "who": f.who or "", "conf": f.conf or "", "topics": list(f.topics),
            "entities": list(f.entities), "unit": f.unit or ""}


def _months(facts, last: int | None = None) -> list[dict]:
    c = Counter(f.when[:7] for f in facts if f.when)
    rows = [{"month": m, "facts": n} for m, n in sorted(c.items())]
    return rows[-last:] if last else rows


def _page(facts, limit: int, offset: int) -> tuple[list[dict], int]:
    rows = sorted(facts, key=lambda f: (f.when or "", f.id), reverse=True)
    return [_fact(f) for f in rows[offset:offset + limit]], len(rows)


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
    page, total = _page(facts, limit, offset)
    return {
        "code": code, "aliases": sorted(t.aliases), "parents": [p for p in sorted(t.parents) if p in vocab.topics],
        "status": t.status, "facts_total": total, "facts": page, "limit": limit, "offset": offset,
        "months": _months(facts), "children": children,
        "entities": [{"code": c, "name": _entity_name(vocab, c), "facts": n} for c, n in ents.most_common(TOP_N)],
        "kinds": [{"kind": k or "?", "facts": n} for k, n in Counter(f.kind for f in facts).most_common()],
    }


# ----------------------------------------------------------------- 实体页

def entity_page(mem, code: str, limit: int = FACT_PAGE, offset: int = 0) -> dict | None:
    store, vocab = mem._index()
    e = vocab.entities.get(code)
    if e is None:
        return None
    facts = [f for f in store.facts.values() if code in f.entities]
    topics = Counter(c for f in facts for c in f.topics)
    page, total = _page(facts, limit, offset)
    return {
        "code": code, "name": e.name or e.code, "type": e.etype or "", "aliases": sorted(e.aliases),
        "relations": [{"rel": r, "target": tgt, "target_name": _entity_name(vocab, tgt)} for r, tgt in sorted(e.rels)],
        "facts_total": total, "facts": page, "limit": limit, "offset": offset,
        "months": _months(facts),
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
    page, total = _page(facts, limit, offset)
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
    store, _vocab = mem._index()
    page, _ = _page([f for f in store.facts.values() if f.when == date], limit, 0)
    return page
