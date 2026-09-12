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
        base = title or stem
        if len(members) == 1:
            out[members[0][1]] = base
            continue
        members.sort()
        n = len(members)
        for k, (_idx, uid) in enumerate(members, 1):
            out[uid] = f"{base}（{k}/{n}）"
    return out
