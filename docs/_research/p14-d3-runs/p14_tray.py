"""P14 真跑前：往 scratch 库（p14/p14data）里 da080ca847cf 的托盘放两篇相关笔记 + 一条事实。
走的是 `store.replace_tray`——跟 `PUT /api/notes/{id}/tray` 同一个函数。真库不碰（KITE_DATA_DIR 指向 scratch）。"""
import os, sys, json
from pathlib import Path

S = Path("/private/tmp/claude-501/-Users-huilong-Skills-Bugfixing-Feishu/401a09f3-c80d-446c-a096-c81ed0fa949a/scratchpad/p14")
os.environ["KITE_DATA_DIR"] = str(S / "p14data")
sys.path.insert(0, "/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-a4480709e2c7425c5/backend")
from app.database import store                      # noqa: E402
from app.database.kite.kite_memory import UserMemory  # noqa: E402
from app.harness import tray                          # noqa: E402

USER, NOTE = "terrence", "da080ca847cf"


def excerpt(content: str, max_chars: int = 600) -> str:
    import re
    plain = re.sub(r"\[([^\]\n]+)\]\(note://[0-9a-f]{12}\)", r"\1", content or "")
    plain = re.sub(r"^#+\s*", "", plain, flags=re.M)
    plain = re.sub(r"\n{2,}", "\n", plain).strip()
    return plain[:max_chars] + ("…" if len(plain) > max_chars else "")


items = []
for nid in ("0eecee3d7b94", "92d07b760f1e"):
    n = store.get_note(USER, nid)
    assert n, nid
    items.append({"kind": "note", "ref_id": nid, "title": n["title"] or "未命名", "excerpt": excerpt(n["content"])})
f = UserMemory(USER).fact_by_id("terrence-1238-7F4")
assert f, "fact missing"
items.append({"kind": "fact", "ref_id": f["id"], "title": f.get("when") or "", "excerpt": f["text"]})
got = store.replace_tray(USER, NOTE, items)
print(json.dumps([{k: (v[:80] if isinstance(v, str) else v) for k, v in g.items()} for g in got], ensure_ascii=False, indent=1))
print("--- lines ---")
for ln in tray.lines_of(got):
    print(ln[:160])
