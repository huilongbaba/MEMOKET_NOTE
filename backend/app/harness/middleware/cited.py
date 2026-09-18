"""正文里已经引着的事实，展开成材料（P6 问题 2）。

P5 人读五篇真实笔记（`docs/TRACELOG-product.md` P5 节）读出来的第二种病：
**打分器和修订把正文里已有的 `[terrence-…]` 当成「知识库里没有」**——

* `a941efecd390`：用户自己贴的 9 条引用被删 8 条，理由全是「不在本轮提供的
  知识库事实中」，而 `fact_by_id` 8/8 存在；
* `603dca25403a` 第 6 轮：打分器说「正文引用的 terrence-1604-18F4 在知识库中
  没有对应事实」——它是第 1 轮检索回来的，只是滚出了 `st.facts` 的 40 行窗口
  进了索引（`middleware/facts.py`）；排名因此低于第 1 轮，第 2–6 轮的 1349 字
  + 11 条修订全被 `regressed` 扔掉。

打分（`loop._evaluate`）和修订（`middleware/revise.py`）拿到的材料都只有
`st.facts`——这次跑最近 `fact_budget` 条。**正文里带编号的句子，编号本身就是
出处**：`citations_exist` 已经逐个查过它们存在，这里把查到的正文一起带上。

顺序：先从这次跑攒下的全量 `facts_all`（`Facts` 中间件，一条不丢）里按 id 找
——滚出窗口的那些就在这儿，零 I/O；找不到的（用户自己贴的、上一次跑留下的）
才去 `UserMemory.fact_by_id`，查过的记在 bag 里，一次跑里每个 id 只查一次。

**不进 `st.facts`**：那一份是「这次跑检索回来的」，`Facts` 按它算 dry_rounds、
`material_used` 按它判「有没有用上」，混进去会让判据把用户自己引的当成这一轮
查到的。单独放 `bag["cited_facts"]`，读者是 `_evaluate` 和 `Revise`。
"""

from __future__ import annotations

import re

from ..state import State

_HEAD = re.compile(r"^\[([A-Za-z0-9_\-]+)\]")


def cited_lines(content: str, facts: list[str], pool: list[str], lookup,
                cache: dict[str, str]) -> list[str]:
    """纯函数那一半：正文引了、`facts` 里没有的 id → 一行一条的材料。

    `lookup(fact_id) -> dict | None` 由调用方注入（生产是 `UserMemory.fact_by_id`），
    `cache` 记「查过了」——值为空串表示查过、库里没有（`citations_exist` 会管它）。
    """
    from ..checks.citations import cited_ids, supplied_ids

    have = supplied_ids(facts)
    by_id: dict[str, str] = {}
    for f in pool:
        m = _HEAD.match(f or "")
        if m and m.group(1) not in by_id:
            by_id[m.group(1)] = f
    out: list[str] = []
    for fid in cited_ids(content):
        if fid in have:
            continue
        line = by_id.get(fid)
        if line is None:
            if fid not in cache:
                fact = lookup(fid) or {}
                text = str(fact.get("text") or "").strip()
                when = str(fact.get("when") or "").strip()
                cache[fid] = f"[{fid}] {text}" + (f"（{when}）" if when else "") if text else ""
            line = cache[fid]
        if line:
            out.append(line)
    return out


class Cited:
    name = "cited"
    hooks = ("after_prepare",)
    after: tuple[str, ...] = ("facts",)      # `facts_all` / `st.facts` 这一轮的样子要先定下来

    async def after_prepare(self, st: State) -> None:
        cache: dict[str, str] = st.bag.setdefault("cited_cache", {})
        lookup = _lookup_for(st)
        st.bag["cited_facts"] = cited_lines(
            st.content, list(st.facts), list(st.bag.get("facts_all") or []),
            lookup, cache)


def _lookup_for(st: State):
    user = getattr(st.ctx, "user", "")
    if not user:
        return lambda _fid: None
    try:
        from ...database.kite.kite_memory import UserMemory
        mem = UserMemory(user)
    except Exception:                                   # noqa: BLE001
        # 知识库读不出来不能让这一轮写不成——跟 `Supersede` 同一条原则：
        # 补充信息不承重。
        return lambda _fid: None

    def look(fid: str):
        try:
            return mem.fact_by_id(fid)
        except Exception:                               # noqa: BLE001
            return None
    return look
