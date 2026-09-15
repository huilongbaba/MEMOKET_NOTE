"""实体去重——**只在展示 / 查询层归组，不改知识库**。

真实库里同一个东西抽出来好几个实体码：memo cat / MemoCat / memo_cat、Apple Watch / AppleWatch、
Facebook / facebook（第 235 轮实拍实体索引页）。归组规则只要三条零歧义的：

1. 大小写不分；
2. 空格 / 下划线 / 连字符 / 点 / 撇号忽略；
3. 词表里登记的别名（name / aliases）算同一个。

中英文对译（苹果手表 / Apple Watch）、缩写（PCBA / pcb）这类不碰——那需要人或模型判断，
等定了方案再说（用户 2026-09-13：先上规则，别太复杂）。

每组选一个**代表**：事实最多的那个码（并列取更短的），显示名用代表的 name。
"""

from __future__ import annotations

import re
from collections import Counter

_STRIP = re.compile(r"[\s_\-\.·'’]+")


def norm_key(s: str) -> str:
    return _STRIP.sub("", (s or "").lower())


class EntityGroups:
    """code → 代表码；代表码 → 成员码列表。"""

    def __init__(self, canon_of: dict[str, str], members_of: dict[str, list[str]],
                 names: dict[str, str], dropped: "set[str] | None" = None):
        self.canon_of = canon_of
        self.members_of = members_of
        self._names = names
        # 用户点过「这压根不该是实体」的那些码（`app` `device` `pro` `logo` 这类
        # 英文常用词被抽成了实体）。**没有干净的规则能分开它们**——`google` `apple`
        # `slack` 也是小写、也是真的（docs/kb-entities-plan.md §10）。所以只认人判的。
        self.dropped = dropped or set()

    def is_dropped(self, code: str) -> bool:
        return self.canon(code) in self.dropped or code in self.dropped

    def canon(self, code: str) -> str:
        return self.canon_of.get(code, code)

    def members(self, code: str) -> list[str]:
        return self.members_of.get(self.canon(code), [code])

    def name(self, code: str) -> str:
        c = self.canon(code)
        return self._names.get(c, c)

    def variants(self, code: str) -> list[str]:
        """除代表之外其它写法的显示名（页面上「同一实体的写法」那一行）。"""
        c = self.canon(code)
        return [self._names.get(m, m) for m in self.members_of.get(c, []) if m != c]


def build(vocab, entity_count: Counter | dict,
          extra_pairs: "list[tuple[str, str]] | tuple" = (),
          dropped: "set[str] | None" = None) -> EntityGroups:
    """`extra_pairs` 是**人判过「是同一个」的那些对**（docs/kb-entities-plan.md 第二部分）。

    三条零歧义的规则合不掉 `安克`/`Anker`、`MemoCat`/`MemoCad` 这类，而它们在真库里
    就是同一个东西——自家产品因此少算了一半。这些对由人裁决、落在 `kb_entity_merges`，
    在这里跟规则算出来的并到同一棵并查集里。**知识库本身不动，随时可逆。**
    """
    codes = list(vocab.entities.keys())
    parent = {c: c for c in codes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    seen: dict[str, str] = {}
    for code in codes:
        e = vocab.entities[code]
        keys = {norm_key(code), norm_key(getattr(e, "name", "") or code)}
        keys |= {norm_key(a) for a in (getattr(e, "aliases", None) or ())}
        keys.discard("")
        for k in keys:
            if k in seen:
                union(code, seen[k])
            else:
                seen[k] = code
    for a, b in extra_pairs or ():
        if a in parent and b in parent:
            union(a, b)

    groups: dict[str, list[str]] = {}
    for code in codes:
        groups.setdefault(find(code), []).append(code)
    canon_of: dict[str, str] = {}
    members_of: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    for members in groups.values():
        members.sort(key=lambda c: (-int(entity_count.get(c, 0)), len(c), c))
        canon = members[0]
        for m in members:
            canon_of[m] = canon
            e = vocab.entities[m]
            names[m] = getattr(e, "name", "") or m
        members_of[canon] = members
    return EntityGroups(canon_of, members_of, names, set(dropped or ()))


def user_decisions(user_id: str) -> tuple[list[tuple[str, str]], set[str]]:
    """人判过的：(是同一个的那些对, 压根不该是实体的那些码)。
    取不到就当没有——**这是加分项，不该拖垮索引**。"""
    if not user_id:
        return [], set()
    try:
        from .. import store as store_mod
        rows = store_mod.entity_decisions(user_id)
    except Exception:      # noqa: BLE001
        return [], set()
    same = [(d["code_a"], d["code_b"]) for d in rows if d["decision"] == "same"]
    drop = {d["code_a"] for d in rows if d["decision"] == "drop_a"}
    drop |= {d["code_b"] for d in rows if d["decision"] == "drop_b"}
    return same, drop


def for_store(store, vocab) -> EntityGroups:
    """按当前索引算一次、挂在 store 上；事实数变了再算。1220 个实体几毫秒。

    **人判过的合并只在算的那一次去查库**。第一版把「判过多少对」放进了缓存键，
    于是每次调用都要开一次 sqlite ——实测命中缓存时每次 0.454ms，其中 0.445ms
    是那次查询（98%），等于把缓存的意义抵消了；而这个函数被 `search.rank`、
    `pages`、`notes`、`memory` 四条热路径反复调（第 668 轮量的）。
    不需要放进键：用户在收件箱里判完一下，路由会 `UserMemory.invalidate()`，
    索引缓存一丢、下次 `_index()` 给的是**新的 store 对象**，这个属性自然不在了。
    """
    n = len(getattr(store, "facts", {}) or {})
    cached = getattr(store, "_memoket_entity_groups", None)
    if cached and cached[0] == n:
        return cached[1]
    pairs, drop = user_decisions(getattr(store, "_memoket_user", "") or "")
    count = Counter(c for f in store.facts.values() for c in f.entities)
    g = build(vocab, count, pairs, drop)
    try:
        store._memoket_entity_groups = (n, g)
    except Exception:      # noqa: BLE001 — 挂不上就每次算
        pass
    return g
