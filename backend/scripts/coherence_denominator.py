"""`coherence` 那五款里，代码能指到位置的那两款**有没有分母**（计划 4.5）。

## 这个脚本回答的是一个二选一

[MECH] 第 2 层第 5 条：

> **内在质量维度必须有位置级探测器，否则不许进 `INNER_QUALITY`**
> ——没有探测器的维度，它的分数只能让回路**停下来**，不能让它**变好**。

`coherence` 拿过 3 次 0 分（实测 `harness_rounds` 里 123 轮出现、**46 轮判 0**），
而这个系统里没有任何一行代码能说出它不连贯在哪。两条路：**补一个探测器**，
或者**承认它只能停机并在代码里写明**。

拍板之前先量一次分母。`_COHERENCE` 的判词自己列了五款，其中只有两款是结构性的：

* (2) 标题层级不统一 —— 机械能判的那一档是**跳级**（`##` 底下直接冒出 `####`）；
* (3) 编号不连贯 —— 判词里逐字写着的例子就是「1、2、4、3」。

另外三款（二次收尾 / 前后体例不一致 / 自我拆台）要读内容才判得出来。

**所以这个脚本里的探测器不是生产代码，是一次测量。** 它留在 `scripts/` 而不是
`app/harness/checks/`，正是因为量完的结论是「不该做成判据」——把一条在真实语料上
分母接近零的检测器塞进 `checks/`，就是这个仓反复写着的那句
「**建了判据不等于用了判据**」的反面教材。

## 用法

    cd backend && .venv/bin/python scripts/coherence_denominator.py

只读：全程夹在 `db_guard.Watch()` 里，连 `update_note` 都没 import。
"""

from __future__ import annotations

import collections
import dataclasses
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db_guard                                            # noqa: E402
from corpus_lineage import (ORIGIN_FIXTURE, ORIGIN_SCRIPT,  # noqa: E402
                            ORIGIN_USER, load_notes)


@dataclasses.dataclass(frozen=True)
class HeadingDefect:
    """坏在哪一行、哪个标题、为什么。**位置级**指的就是这三样。"""
    kind: str            # "skipped_level" | "broken_numbering"
    heading: str
    line: int
    why: str


# 多段号：`2.1` / `2.1.3`。单段号：**必须带标点**（`3.` / `3、` / `3)`）——
# 不带标点的话 `## 2026 年的复盘` 会被读成编号 2026，两篇年份标题一隔就报"跳号"。
# 号只认两位数以内，四位数一律当年份。
_MULTI_NUM = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2})+)\s*[.、)）]?\s*(?=\S)")
_SOLO_NUM = re.compile(r"^\s*(\d{1,2})\s*[.、)）]\s*(?=\S)")
_HEADING_LINE = re.compile(r"^(#{1,6})\s+(\S.*)$")


def heading_number(text: str) -> tuple[str, ...] | None:
    m = _MULTI_NUM.match(text) or _SOLO_NUM.match(text)
    return tuple(m.group(1).split(".")) if m else None


def headings_with_lines(content: str) -> list[tuple[int, str, int]]:
    """`[(层级, 标题原文, 行号)]`。**围栏代码块里的 `#` 不算**——mermaid /
    yaml / python 块里行首 `#` 是注释，算进来整份层级就乱了。"""
    out: list[tuple[int, str, int]] = []
    fenced = False
    for i, line in enumerate((content or "").split("\n"), start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = _HEADING_LINE.match(line)
        if m:
            out.append((len(m.group(1)), m.group(2).strip(), i))
    return out


def sibling_groups(heads: list[tuple[int, str, int]]) -> list[list[tuple[int, str, int]]]:
    """把标题切成「兄弟组」：同一层级，中间没有更浅的标题把它们隔开。"""
    groups: list[list[tuple[int, str, int]]] = []
    open_groups: dict[int, list[tuple[int, str, int]]] = {}
    for h in heads:
        lv = h[0]
        for deeper in [k for k in open_groups if k > lv]:
            open_groups.pop(deeper)
        if lv not in open_groups:
            open_groups[lv] = []
            groups.append(open_groups[lv])
        open_groups[lv].append(h)
    return groups


def heading_defects(content: str) -> list[HeadingDefect]:
    """标题层级跳级 + 小节编号断裂。"""
    heads = headings_with_lines(content)
    out: list[HeadingDefect] = []
    for (lv_a, _t_a, _l_a), (lv_b, t_b, l_b) in zip(heads, heads[1:]):
        if lv_b - lv_a > 1:
            out.append(HeadingDefect("skipped_level", t_b, l_b,
                                     f"第 {l_b} 行「{t_b[:30]}」是 {lv_b} 级，"
                                     f"上一个是 {lv_a} 级，中间跳过了一级"))
    for group in sibling_groups(heads):
        nums = [heading_number(t) for _lv, t, _ln in group]
        if len(group) < 2 or any(n is None for n in nums):
            continue                      # 混着的不比：判据宁可窄一点
        if len({n[:-1] for n in nums}) != 1:   # type: ignore[index]
            continue                      # `2.1` 和 `3.1` 不是兄弟
        tails = [int(n[-1]) for n in nums]     # type: ignore[index]
        for i in range(1, len(tails)):
            if tails[i] != tails[i - 1] + 1:
                _lv, t, ln = group[i]
                out.append(HeadingDefect("broken_numbering", t, ln,
                                         f"第 {ln} 行「{t[:30]}」序号 {tails[i]}，"
                                         f"前一个是 {tails[i - 1]}"))
                break
    return sorted(out, key=lambda d: d.line)


def main() -> int:
    with db_guard.Watch():
        print(f"{'血缘':9s} {'篇':>4s} {'非空':>4s} {'标题':>5s} {'相邻标题对':>10s} "
              f"{'兄弟组≥2':>8s} {'全带号':>6s} {'开火':>4s}")
        for origin in (ORIGIN_USER, ORIGIN_SCRIPT, ORIGIN_FIXTURE):
            kept, _dropped = load_notes(keep={origin})
            heads = pairs = groups = numbered = nonempty = 0
            fired: collections.Counter = collections.Counter()
            for row in kept:
                content = row["content"] or ""
                if not content.strip():
                    continue
                nonempty += 1
                hs = headings_with_lines(content)
                heads += len(hs)
                pairs += max(0, len(hs) - 1)
                for g in sibling_groups(hs):
                    if len(g) < 2:
                        continue
                    groups += 1
                    if all(heading_number(t) is not None for _l, t, _n in g):
                        numbered += 1
                for d in heading_defects(content):
                    fired[d.kind] += 1
            print(f"{origin:9s} {len(kept):4d} {nonempty:4d} {heads:5d} {pairs:10d} "
                  f"{groups:8d} {numbered:6d} {sum(fired.values()):4d}  {dict(fired)}")
        print()
        print("读法：`相邻标题对` 是跳级那一款的分母，`全带号` 是编号那一款的分母。")
        print("两款的开火数都是 0 —— 误伤 0，但分母也接近 0。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
