"""冲突收件箱（docs/agent-native-editor.md §3.3.1）：摄入时就检测新事实跟旧事实的冲突，
放进「待处理」而不是静默入库。用户点一下「新的取代旧的」/「旧的算数」/「两条都留」。

只用 relations.detect 的 conflict 候选（纯代码，零 LLM），每条新事实一次召回（几毫秒）。
扫描失败不能拖垮摄入——调用方 try/except。
"""

from __future__ import annotations

from .. import store
from . import relations


def scan_session(mem, user_id: str, session_id: str, *, source: str = "") -> int:
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
        for c in relations.detect(text, others):
            if c["relation"] != "conflict":
                continue
            for old_id in c["fact_ids"]:
                if store.add_conflict(user_id, nf["id"], old_id, c.get("unit") or "", c["say"], source):
                    added += 1
    return added
