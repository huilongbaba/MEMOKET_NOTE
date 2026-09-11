"""知识库变成笔记树上的一棵**虚拟子树**。

设计见 docs/kb-fusion-design.md §3.2。「虚拟」= 不落库：这里只是把 KITE 的
数据呈现成跟 `store.tree()` 同一种行，前端同一个树控件画，收益是白拿的——
标签页、右栏、右键菜单、⌘J，这些肌肉记忆对知识库同样生效。

    知识库/
    ├── 主题/      KITE 的 topic 本来就是层级的，直接当树；多个父主题 = 克隆
    ├── 实体/      按类型分组（人 / 公司 / 产品…）
    ├── 时间线/    按月聚合
    └── 最近摄入/  最近的几次会议（unit）

**只有分类层一次给全**，事实按需展开（`children()`）：几千条事实全塞进
树的初始加载里，用户没展开的那些全是浪费，而分类层几百个节点一次给全
是便宜的、而且要它才能画出树的形状。

节点 id 的形状（前端靠前缀 `kb` 认出「这不是一篇真笔记」）：

    kb                 根
    kb:topics / kb:entities / kb:timeline / kb:recent
    kb:topic:<code>    kb:etype:<type>   kb:entity:<code>
    kb:month:<YYYY-MM> kb:unit:<id>      kb:fact:<id>

branch id 跟 note id 分开（`kbb:…`）——一个 topic 有几个父主题就有几条
branch，跟真笔记的克隆一模一样，树上照样标 ⧉。
"""

from __future__ import annotations

from collections import Counter

KB_ROOT = "kb"
ROOT_POSITION = 1_000_000
"""排在所有真笔记后面。真笔记的 position 是从 0 起的小整数。"""

CATEGORIES = [
    ("kb:topics", "主题"),
    ("kb:entities", "实体"),
    ("kb:timeline", "时间线"),
    ("kb:recent", "最近摄入"),
]

# 可视化与配套工具，也长在树上——「打开一张图」跟「打开一篇笔记」是同一个
# 动作。它们没有子节点，前端按 id 决定画什么（KbNoteView）。
TOOLS = [
    ("kb:facts", "事实表"),
    ("kb:graph", "主题地图"),
    ("kb:digest", "定期回顾"),
]

ETYPE_LABELS = {
    "person": "人", "org": "组织", "product": "产品", "place": "地点",
    "event": "事件", "project": "项目", "": "其他",
}

RECENT_UNITS = 15
FACT_TITLE_CHARS = 60
MAX_CHILDREN = 300


def _row(note_id: str, parent: str, title: str, *, position: int = 0,
         preview: str = "", child_count: int = 0, branch_count: int = 1,
         updated_at: str = "", branch_id: str = "", fact_count: int = 0) -> dict:
    return {
        "id": branch_id or f"kbb:{note_id[3:]}:{parent}",
        "note_id": note_id, "parent_note_id": parent, "position": position,
        "is_expanded": False, "title": title, "preview": preview,
        "cite_count": 0, "ingested_at": "", "pinned": False,
        "updated_at": updated_at, "child_count": child_count,
        "branch_count": branch_count, "fact_count": fact_count,
    }


def _clip(s: str, n: int = FACT_TITLE_CHARS) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _fact_row(f, parent: str, position: int) -> dict:
    return _row(f"kb:fact:{f.id}", parent, _clip(f.text), position=position,
                preview=f.text, updated_at=f.when or "",
                branch_id=f"kbb:fact:{f.id}:{parent}")


def build(mem) -> list[dict]:
    """分类层：根 + 四个分类 + 主题树 + 实体（按类型）+ 月份 + 最近的会议。"""
    store, vocab = mem._index()
    facts = list(store.facts.values())

    topic_direct = Counter(c for f in facts for c in f.topics)
    entity_count = Counter(c for f in facts for c in f.entities)
    month_count = Counter(f.when[:7] for f in facts if f.when)
    unit_count = Counter(f.unit for f in facts if f.unit)

    rows: list[dict] = []

    # ---- 主题：多个父主题 = 多条 branch = 克隆
    topic_rows: list[dict] = []
    children_of: Counter = Counter()
    for t in vocab.topics.values():
        parents = [p for p in sorted(t.parents) if p in vocab.topics] or [""]
        for p in parents:
            children_of[p] += 1
    for t in sorted(vocab.topics.values(), key=lambda t: t.code):
        parents = [p for p in sorted(t.parents) if p in vocab.topics] or [""]
        closure = vocab.downset(t.code, include_candidates=True) or {t.code}
        n_facts = sum(topic_direct.get(c, 0) for c in closure)
        for p in parents:
            parent_id = f"kb:topic:{p}" if p else "kb:topics"
            topic_rows.append(_row(
                f"kb:topic:{t.code}", parent_id, t.code,
                preview=" / ".join(sorted(t.aliases)),
                child_count=children_of.get(t.code, 0) + topic_direct.get(t.code, 0),
                branch_count=len(parents), fact_count=n_facts,
                branch_id=f"kbb:topic:{t.code}:{parent_id}"))

    # ---- 实体：按类型分组。**类型只有一种时不分组**——真实库里 1220 个实体
    # 全没标类型，分出来是一层只有「其他」的空壳，多点一下什么都没得到。
    entity_rows: list[dict] = []
    by_type: dict[str, list] = {}
    for e in vocab.entities.values():
        by_type.setdefault(e.etype or "", []).append(e)
    etype_rows: list[dict] = []
    grouped = len(by_type) > 1
    for i, (etype, ents) in enumerate(sorted(by_type.items(), key=lambda kv: -len(kv[1]))):
        eid = f"kb:etype:{etype or 'other'}" if grouped else "kb:entities"
        if grouped:
            etype_rows.append(_row(eid, "kb:entities", ETYPE_LABELS.get(etype, etype),
                                   position=i, child_count=len(ents)))
        for j, e in enumerate(sorted(ents, key=lambda e: (-entity_count.get(e.code, 0), e.code))):
            entity_rows.append(_row(
                f"kb:entity:{e.code}", eid, e.name or e.code, position=j,
                preview=" / ".join(sorted(e.aliases)),
                child_count=entity_count.get(e.code, 0),
                fact_count=entity_count.get(e.code, 0)))

    # ---- 时间线：按月，新的在前
    month_rows = [
        _row(f"kb:month:{m}", "kb:timeline", m, position=i, child_count=n,
             fact_count=n)
        for i, (m, n) in enumerate(sorted(month_count.items(), reverse=True))
    ]

    # ---- 最近摄入：最近的几次会议
    units = sorted((u for u in store.units.values() if u.date),
                   key=lambda u: (u.date, u.id), reverse=True)[:RECENT_UNITS]
    unit_rows = [
        _row(f"kb:unit:{u.id}", "kb:recent", f"{u.date} · {u.title or u.id}",
             position=i, child_count=unit_count.get(u.id, 0),
             fact_count=unit_count.get(u.id, 0), updated_at=u.date)
        for i, u in enumerate(units)
    ]

    rows.append(_row(KB_ROOT, "root", "知识库", position=ROOT_POSITION,
                     child_count=len(CATEGORIES) + len(TOOLS), fact_count=len(facts),
                     branch_id="kbb:root"))
    counts = {
        "kb:topics": children_of.get("", 0),
        "kb:entities": len(etype_rows) if grouped else len(entity_rows),
        "kb:timeline": len(month_rows),
        "kb:recent": len(unit_rows),
    }
    for i, (cid, label) in enumerate(CATEGORIES):
        rows.append(_row(cid, KB_ROOT, label, position=i, child_count=counts[cid]))
    for i, (cid, label) in enumerate(TOOLS):
        rows.append(_row(cid, KB_ROOT, label, position=len(CATEGORIES) + i))
    rows += topic_rows + etype_rows + entity_rows + month_rows + unit_rows
    return rows


def children(mem, node: str) -> list[dict]:
    """展开一个分类节点时才取的那一层：它名下的事实。

    主题走闭包（含子主题），跟 recall / facts_page 的语义一致——一个主题
    「有多少条」不该因为是在树上看还是在表里看而不一样。
    """
    store, vocab = mem._index()
    kind, _, key = node.partition(":")[2].partition(":")
    facts = store.facts.values()

    if kind == "topic":
        closure = vocab.downset(key, include_candidates=True) or {key}
        picked = [f for f in facts if set(f.topics) & closure]
    elif kind == "entity":
        picked = [f for f in facts if key in f.entities]
    elif kind == "month":
        picked = [f for f in facts if (f.when or "").startswith(key)]
    elif kind == "unit":
        picked = [f for f in facts if f.unit == key]
    else:
        return []
    picked.sort(key=lambda f: (f.when or "", f.id), reverse=True)
    return [_fact_row(f, node, i) for i, f in enumerate(picked[:MAX_CHILDREN])]


def is_virtual(note_id: str) -> bool:
    return note_id == KB_ROOT or note_id.startswith("kb:")
