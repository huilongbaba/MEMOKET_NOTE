"""P15 #1 量：p11/p13/p14 三组真跑逐轮离线重放 done_criteria（只判这次写的单位），对照实际响的判据。"""
import json, sys
sys.path.insert(0, "/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-a6d6a2a7e6304cf5a/backend")
from app.harness.checks import done as D
from app.editor import intent as doc_intent
S = "/private/tmp/claude-501/-Users-huilong-Skills-Bugfixing-Feishu/401a09f3-c80d-446c-a096-c81ed0fa949a/scratchpad"
runs = {
    "p11-intent da080": (S + "/p11/runs/da080ca847cf-intent.json"),
    "p13 0eecee": (S + "/p13/runs/0eecee3d7b94.json"),
    "p14-tray da080": (S + "/p14/runs/da080ca847cf-tray.json"),
}
MATERIAL = {"no_placeholder", "no_audit_voice", "citations_hold", "citations_exist", "material_thin",
            "citations_present", "material_used"}
for name, path in runs.items():
    d = json.load(open(path))
    intent = d.get("intent") or ""
    done = doc_intent.done_of(intent)
    checked = tuple(d.get("intent_checked") or ())
    start = d["orig"]
    rounds = d["rounds"]
    items = sorted(rounds.items(), key=lambda kv: int(kv[0])) if isinstance(rounds, dict) else list(enumerate(rounds, 1))
    print(f"== {name}: done=「{done}」 judgeable={D.judgeable(done, checked)}")
    for k, r in items:
        content = r.get("content_after") or r.get("content") or ""
        fired = [c.get("check") for c in (r.get("checks") or []) if not c.get("stuck_rounds")]
        fresh_only = (lambda s: s.strip() not in start)
        verd = None
        for text in D.judgeable(done, checked):
            res = D.check_done_item(text, content, unit_filter=fresh_only)
            if res and res["status"] == "fail":
                verd = (text, res["kind"], res["why"])
                break
            elif res:
                verd = verd or ("pass:" + text, res["kind"], res["why"])
        fam = "material" if fired and fired[0] in MATERIAL else ("repeat/other" if fired else "-")
        print(f"  r{k}: fired={fired} [{fam}]  done→ {verd}")
