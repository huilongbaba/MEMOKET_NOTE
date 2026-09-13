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

    def __init__(self, canon_of: dict[str, str], members_of: dict[str, list[str]], names: dict[str, str]):
        self.canon_of = canon_of
        self.members_of = members_of
        self._names = names

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


def build(vocab, entity_count: Counter | dict) -> EntityGroups:
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
    return EntityGroups(canon_of, members_of, names)


def for_store(store, vocab) -> EntityGroups:
    """按当前索引算一次、挂在 store 上；事实数变了再算。1220 个实体几毫秒。"""
    n = len(getattr(store, "facts", {}) or {})
    cached = getattr(store, "_memoket_entity_groups", None)
    if cached and cached[0] == n:
        return cached[1]
    count = Counter(c for f in store.facts.values() for c in f.entities)
    g = build(vocab, count)
    try:
        store._memoket_entity_groups = (n, g)
    except Exception:      # noqa: BLE001 — 挂不上就每次算
        pass
    return g
