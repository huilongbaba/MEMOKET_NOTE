"""冲突收件箱（docs/agent-native-editor.md §3.3.1）：摄入时就检测新事实跟旧事实的冲突，
放进「待处理」而不是静默入库。用户点一下「新的取代旧的」/「旧的算数」/「两条都留」。

候选由 `relations.detect` 出（纯代码、零 LLM、每条新事实一次召回，几毫秒），
**再由一个确认器过一遍才进收件箱**。确认器由调用方注入（`routers/` 那一层才
认识模型；知识库这一层不许往上依赖，`test_layering` 会拦——第一版我就是这么
被拦下来的）。不注入就是原来的纯代码行为。扫描失败不能拖垮摄入——调用方 try/except。

## 为什么这里要多花一次模型调用（第 678 轮）

原来这条路是纯代码、不确认的，而右栏那张**只是给你看**的关系卡反倒会让模型
确认一遍（`routers/memory.py` 的 `body.confirm`）。**把关把反了**：收件箱这张
卡上摆着「新的取代旧的」，点一下就把一条正确的事实作废掉。

实拍（新用户导入两篇真会议记录）：收件箱里两条**都是误报**。纯词面重合看不出
「竞品 Plaud 的定价是 159 美元」和「我们的定价是 199 美元」说的不是一件事——
**这正是模型一眼就能判的**。

代价可以忽略：在 20406 条的真库上抽 2500 条量过，冲突候选只触发 4 次
（0.16%），一次全库导入也就几十次调用。
"""

from __future__ import annotations

from .. import store
from . import relations


# 确认器：`(正文, 候选, {事实 id: 事实}) -> 留下来的候选`。
Confirm = "Callable[[str, list[dict], dict[str, dict]], list[dict]]"


def scan_session(mem, user_id: str, session_id: str, *, source: str = "",
                 confirm=None) -> int:
    """把 `session_id` 里刚抽出来的事实跟知识库里其它的比一遍，冲突的记进收件箱。返回新记的条数。"""
    new_facts = [f for f in mem.facts_for_prefix(session_id) if f.get("unit") == session_id]
    if not new_facts:
        return 0
    stem = session_id.rsplit("-", 1)[0] + "-"          # 同一篇 / 同一份材料的别的块不算「旧记录」
    superseded = mem.fact_attrs("superseded_by")
    added = 0
    for nf in new_facts:
        text = nf.get("text") or ""
        if not any(ch.isdigit() for ch in text):
            continue
        rows, _terms, _took = mem.recall(text, limit=8)
        others = [r for r in rows
                  if r["id"] != nf["id"] and not (r.get("unit") or "").startswith(stem) and r["id"] not in superseded]
        cands = [c for c in relations.detect(text, others) if c["relation"] == "conflict"]
        if not cands:
            continue
        if confirm is not None:
            cands = confirm(text, cands, {r["id"]: r for r in others})
        for c in cands:
            for old_id in c["fact_ids"]:
                if store.add_conflict(user_id, nf["id"], old_id, c.get("unit") or "", c["say"], source):
                    added += 1
    return added
