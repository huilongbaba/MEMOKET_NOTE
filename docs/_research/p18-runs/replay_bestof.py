"""P18 #1 离线重放：拿 P15 那次真跑（da080ca847cf-p15.json，逐轮记了 checks / eval / content_after）
喂给**真的** `BestOf`，看修前（NOT_A_VETO 空）/ 修后各交哪一轮。零模型调用。"""
import asyncio, json, sys, dataclasses
W = "/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-aa8e51b7bb76f8dd6/backend"
sys.path.insert(0, W)
from app.harness import modes
from app.harness.middleware import best_of
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import DimensionScore, Evaluation

DIMS = ("spine_fidelity", "beat_coverage", "non_repetition", "factual_grounding", "coherence", "material_use")


def replay(path: str, veto: tuple) -> tuple[int, dict]:
    d = json.load(open(path))
    rs = d["rounds"]
    items = sorted(rs.items(), key=lambda kv: int(kv[0])) if isinstance(rs, dict) else list(enumerate(rs, 1))
    st = State(mode=dataclasses.replace(modes.NOTE, dims=DIMS, max_rounds=len(items)),
               ctx=ToolContext(user="u", note_id=d["note_id"], note_title=d["title"]))
    best_of.NOT_A_VETO = veto
    shipped = None
    for k, r in items:
        fired = [c["check"] for c in (r.get("checks") or []) if not c.get("stuck_rounds")]
        ev = r.get("eval") or {}
        scores = {n: DimensionScore(level=v["level"], note="") for n, v in (ev.get("scores") or {}).items()}
        st.round = int(k)
        st.content = r["content_after"]
        st.ev = Evaluation(scores=scores, status=ev.get("status", "continue"), weakest=ev.get("weakest", ""))
        st.skip_judge = bool(fired)
        st.bag["short_circuit"] = fired[-1] if fired else ""
        asyncio.run(best_of.BestOf().after_judge(st))
        if st.best and st.best[1] == st.content:
            shipped = int(k)
        st.ev, st.skip_judge = None, False
    return shipped, {"best_rank": st.best[0], "best_len": len(st.best[1]), "final_len": d["final_len"], "stopped": d["stopped"]}


if __name__ == "__main__":
    for p in sys.argv[1:]:
        old = replay(p, ())
        new = replay(p, ("done_criteria",))
        print(f"{p.split('/')[-1]}: 修前交 r{old[0]} {old[1]} | 修后交 r{new[0]} {new[1]}")
