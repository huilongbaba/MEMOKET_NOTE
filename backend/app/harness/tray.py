"""材料托盘进 harness 的那一小段（P14，`docs/agent-native-editor.md` §3.4）。

托盘 = 用户把这篇笔记要用的材料**显式摊在桌上**：别的笔记、一条事实、导入的一段、摘的一段。
它跟知识库检索回来的材料是两回事——检索是 agent 猜的，托盘是用户说的。所以 harness 取材料时
托盘里的只加三条规矩、别的一概不动（**不碰 checks，不改 loop 的循环结构**）：

  1. **优先**：进 prompt 排在检索材料前面，单独一块（`prompts/fragments.tray_block`），说明它是用户放的；
  2. **不筛**：不过 `checks/relevance.gate`——「相关不相关」量的是来处，托盘的来处就是用户；
  3. **不滚出窗口**：`middleware/facts.py` 的 `fact_budget` 窗口只对检索材料滚，托盘钉在 `st.facts` 头上，
     也不压进「更早几轮」的一行索引。

跟账本（`harness-fact-ledger.md` §10）的关系：托盘 ≠ 账本。账本记的是「查过什么、取到过什么」，
托盘不经过工具循环，不进账本；`facts_irrelevant` 也数不到它。

托盘项怎么变成一行材料（`lines_of`）：

  fact       →  ``[terrence-2046-12F1] [2026-04-16] EVT 的大节点是 4 月 16 号``   跟检索回来的一模一样（`retrieval.format_fact`），
                所以引用规则（句末照抄 [编号]）对它同样成立、`check_citations` 也认得
  note       →  ``[笔记「创业反思」](note://0eecee3d7b94) 开头几百字…``              正文里链回去的写法就是 ``[标题](note://id)``
  import     →  ``[导入「xxx.md」] 那一段``
  selection  →  ``[摘录] 那一段``
"""

from __future__ import annotations

from typing import Iterable

KINDS = ("note", "fact", "import", "selection")


def lines_of(items: Iterable[dict] | None) -> list[str]:
    """托盘项 → 进 prompt 的材料行，保持托盘顺序；形状不对的跳过。"""
    out: list[str] = []
    for it in items or ():
        kind = str((it or {}).get("kind") or "")
        ref = str(it.get("ref_id") or "").strip()
        title = " ".join(str(it.get("title") or "").split())
        excerpt = " ".join(str(it.get("excerpt") or "").split())
        if kind == "fact" and ref:
            when = f"[{title}] " if title and _looks_like_date(title) else ""
            line = f"[{ref}] {when}{excerpt}".rstrip()
        elif kind == "note" and ref:
            line = f"[笔记「{title or '未命名'}」](note://{ref}) {excerpt}".rstrip()
        elif kind == "import" and excerpt:
            line = f"[导入「{title}」] {excerpt}" if title else f"[导入] {excerpt}"
        elif kind == "selection" and excerpt:
            line = f"[摘录] {excerpt}"
        else:
            continue
        if line not in out:
            out.append(line)
    return out


def _looks_like_date(s: str) -> bool:
    return len(s) >= 7 and s[:4].isdigit() and s[4] == "-"


def is_tray_line(line: str, tray: Iterable[str] | None) -> bool:
    return bool(tray) and line in set(tray)
