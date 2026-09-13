"""会议 / 材料的「段」：一篇长材料导入时按块切成 `<源>-<id>-0`、`-1`、… 好几个 session，
标题和日期一模一样。列表里要能分得清是第几段（第 143 轮实拍：最近摄入十行同名同日期）。"""

from __future__ import annotations

import re
from collections import defaultdict

_PART = re.compile(r"^(.*)-(\d+)$")


def part_labels(units) -> dict[str, str]:
    """unit id → 显示标题。同一份材料（id 去掉末尾 -<块号> 相同、标题日期相同）切成多段时，
    标题后带「（k/n）」；单段的照原样。"""
    groups: dict[tuple, list[tuple[int, str]]] = defaultdict(list)
    for u in units:
        m = _PART.match(u.id)
        stem, idx = (m.group(1), int(m.group(2))) if m else (u.id, 0)
        groups[(stem, u.date or "", u.title or "")].append((idx, u.id))
    out: dict[str, str] = {}
    for (stem, _date, title), members in groups.items():
        # 没标题的材料（纯音频转写 / 没首行的文本）：标签和页头别挂裸 id「note-674aa9a1b4b7-0」，用日期说人话
        base = title or (f"会议记录 · {_date}" if _date else stem)
        if len(members) == 1:
            out[members[0][1]] = base
            continue
        members.sort()
        n = len(members)
        for k, (_idx, uid) in enumerate(members, 1):
            out[uid] = f"{base}（{k}/{n}）"
    return out


def material_key(u) -> tuple:
    """同一份材料的几段：id 去掉末尾 -<块号> 相同、标题日期相同。"""
    m = _PART.match(u.id)
    return ((m.group(1) if m else u.id), u.date or "", u.title or "")


def part_index(uid: str) -> int:
    m = _PART.match(uid)
    return int(m.group(2)) if m else 0


def materials(units) -> list[dict]:
    """把 unit 按材料归组：[{"key", "date", "title", "parts": [unit, …按段号]}]，新的材料在前。
    最近摄入按材料列而不是按段列——一份 13 段的材料会把最近 15 场全占掉（第 267 轮实拍）。"""
    groups: dict[tuple, list] = defaultdict(list)
    for u in units:
        groups[material_key(u)].append(u)
    out = []
    for key, members in groups.items():
        members.sort(key=lambda u: part_index(u.id))
        out.append({"key": key, "date": key[1], "title": key[2] or key[0], "parts": members})
    out.sort(key=lambda m: (m["date"], m["key"][0]), reverse=True)
    return out


def parts_of(units, unit_id: str) -> list[str]:
    """跟 unit_id 同一份材料的所有段 id，按段号。找不到就只有它自己。"""
    me = next((u for u in units if u.id == unit_id), None)
    if me is None:
        return [unit_id]
    k = material_key(me)
    return [u.id for u in sorted((u for u in units if material_key(u) == k), key=lambda u: part_index(u.id))]
