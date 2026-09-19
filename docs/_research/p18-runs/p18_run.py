"""P18 #1 真跑（p15_run.py 改路径 + 记 BestOf）：done_criteria 挪到材料族之后、重复族之前 + citations_present 认 note:// 之后，同一份 harness 跑两篇：
  · 0eecee3d7b94 创业反思（P13 那句意图，勾过第二条，无托盘）
  · da080ca847cf 创业一年的回顾（P11/P14 那句意图 + 「每个节点有出处」，托盘 = P14 那三条，从 scratch 库里取）
看：done_criteria 响没响、排第几、下一轮补没补出处；note:// 引用有没有再被 citations_present 短路。

Usage: p15_run.py <note_id> <tag> [intent-text] [max_rounds] [wall_budget_seconds]
照 routers/note_harness.py::run（scope=all、库里的 spine/beats/profile）+ rails_off=("save",)；
KITE_DATA_DIR=<scratch>/p15/p15real（p14/p14data 的拷贝 = 真库 cp 出来的）；真库只做指纹（db_guard，只读）。
"""
from __future__ import annotations

import os, sys, json, time, asyncio, dataclasses, hashlib, re, sqlite3
from pathlib import Path

S = Path("/private/tmp/claude-501/-Users-huilong-Skills-Bugfixing-Feishu/401a09f3-c80d-446c-a096-c81ed0fa949a/scratchpad/p18")
DATA = S / "p18real"
os.environ["KITE_DATA_DIR"] = str(DATA)
os.chdir(str(DATA))

WT = Path("/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-aa8e51b7bb76f8dd6/backend")
sys.path.insert(0, str(WT / "scripts"))
sys.path.insert(0, str(WT))
REAL_DB = Path("/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/backend/data/notes.sqlite3")

import db_guard                                              # noqa: E402
from app.database import store                               # noqa: E402
from app.editor import intent as doc_intent                  # noqa: E402
from app.harness import loop, modes, tools                   # noqa: E402
from app.harness.checks import done as D                     # noqa: E402
from app.harness.checks import citations as C                # noqa: E402
from app.harness.events import EventType                      # noqa: E402
from app.harness.hooks.note import NoteHooks                  # noqa: E402
from app.harness.state import State                           # noqa: E402
from app.routers.note_harness import _score_context, MAX_ROUNDS_CAP  # noqa: E402
from app.editor.profile import entries as _profile            # noqa: E402

USER = "terrence"


def fp_line(fp) -> str:
    dd = hashlib.sha256(json.dumps(fp.digests, sort_keys=True).encode()).hexdigest()[:16]
    return (f"notes={fp.rows['notes']} note_revisions={fp.rows['note_revisions']} "
            f"max(updated_at)={fp.latest['notes']} chars={fp.chars} digest={dd}")


async def run_one(note_id: str, intent_text: str, checked: tuple[str, ...], max_rounds: int, budget: float) -> dict:
    note = store.get_note(USER, note_id)
    assert note, note_id
    content = note["content"] or ""
    spine = note.get("spine") or ""
    beats = note.get("beats") or []
    if isinstance(beats, str):
        try:
            beats = json.loads(beats or "[]")
        except Exception:
            beats = []
    profile = _profile(USER)
    mode = dataclasses.replace(
        modes.for_run(modes.NOTE, has_profile=bool(profile), polish=False),
        max_rounds=max(1, min(max_rounds, MAX_ROUNDS_CAP)), review_each_round=False,
        rails_off=("save",))
    tray = store.list_tray(USER, note_id)
    st = State(mode=mode,
               ctx=tools.ToolContext(user=USER, note_id=note_id, scope="all",
                                     note_title=note["title"], intent=intent_text,
                                     intent_checked=checked, tray=tray),
               request=None, content=content)
    hooks = NoteHooks(polish=False, spine=spine, beats=beats, profile=profile)
    st.bag["polish"] = False

    rounds: dict[int, dict] = {}
    cur = 0
    t0 = time.perf_counter()
    stopped = ""
    finished = None
    async for ev in hooks.skeleton(st):
        pass
    st.bag["score_context"] = _score_context(st)
    print(f"intent = {st.ctx.intent!r}\nchecked = {st.ctx.intent_checked}\ntray = {len(tray)} checks_before_run = {len(st.mode.checks)}", flush=True)

    async for ev in loop.run(st, hooks):
        et = getattr(ev.type, "value", ev.type)
        d = ev.data or {}
        if et == EventType.STEP_STARTED.value:
            cur = int(d.get("step") or d.get("round") or cur + 1) if isinstance(d, dict) else cur + 1
            rounds[cur] = {"round": cur, "t_start": round(time.perf_counter() - t0, 1), "streamed": "",
                           "checks": [], "eval": None, "summary": None, "revisions": [], "policy": []}
            names = [getattr(c, "__name__", "") for c in st.mode.checks]
            pos = names.index("done_criteria") + 1 if "done_criteria" in names else 0
            print(f"--- round {cur} start ({rounds[cur]['t_start']}s) checks_total={len(st.mode.checks)} done_criteria_at={pos}", flush=True)
        elif et == EventType.TEXT_MESSAGE_CONTENT.value:
            rounds.setdefault(cur, {"streamed": ""})["streamed"] += d.get("delta", "") or d.get("content", "") or ""
        elif et == EventType.STEP_FINISHED.value:
            r = rounds.setdefault(cur, {})
            r["t_end"] = round(time.perf_counter() - t0, 1)
            r["content_after"] = st.content
            r["content_len"] = len(st.content)
            fresh_units = [u for u in D.units(st.content)[1] if u.strip() not in content]
            r["fresh_units"] = fresh_units
            r["fresh_units_cited"] = sum(1 for u in fresh_units if C.has_citation(u))
            r["note_links"] = C.note_link_ids(st.content)
            r["best_rank"] = list(st.best[0]) if st.best else None
            r["best_len"] = len(st.best[1]) if st.best else None
            r["short_circuit"] = st.bag.get("short_circuit", "")
            print(f"--- round {cur} end best={r['best_rank']}/{r['best_len']} sc={r['short_circuit']!r} len={len(st.content)} fresh_units={len(fresh_units)} cited={r['fresh_units_cited']} "
                  f"note_links={r['note_links']} checks={[c.get('check') for c in r.get('checks', [])]} focus={str(st.bag.get('focus'))[:120]!r}", flush=True)
            if time.perf_counter() - t0 > budget:
                stopped = "p15_wall_budget"
                break
        elif et == EventType.RUN_FINISHED.value:
            stopped = d.get("reason", "") or ""
            finished = {k: v for k, v in d.items() if k != "content"}
        elif et == EventType.RUN_ERROR.value:
            stopped = "error"
            print("RUN_ERROR", d, flush=True)
        elif et == EventType.CUSTOM.value:
            name, val = d.get("name"), d.get("value")
            r = rounds.setdefault(cur, {})
            if name == "check_hit":
                r.setdefault("checks", []).append(val)
                print(f"    check_hit: {json.dumps(val, ensure_ascii=False)[:400]}", flush=True)
            elif name == "evaluate":
                r["eval"] = val
            elif name == "round_summary":
                r["summary"] = val
            elif name == "revision":
                r.setdefault("revisions", []).append(val)
            elif name == "policy":
                r.setdefault("policy", []).append(val)
            elif name == "warning":
                print("    warning:", val, flush=True)
    seconds = round(time.perf_counter() - t0, 1)
    return {"note_id": note_id, "title": note["title"], "intent": st.ctx.intent,
            "intent_checked": list(st.ctx.intent_checked), "tray_lines": list(st.bag.get("tray_lines") or []),
            "orig_len": len(content), "final_len": len(st.content),
            "orig": content, "final": st.content, "rounds": [rounds[k] for k in sorted(rounds)],
            "stopped": stopped, "finished": finished, "seconds": seconds,
            "checks_total_end": len(st.mode.checks), "run_id": st.bag.get("run_id")}


def usage_since(db: Path, min_id: int) -> dict:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cols = [r[1] for r in c.execute("pragma table_info(llm_usage)")]
    rows = list(c.execute("select * from llm_usage where id > ?", (min_id,)))
    out = {"calls": len(rows)}
    for k in ("prompt_tokens", "cached_tokens", "completion_tokens"):
        if k in cols:
            out[k] = sum((r[cols.index(k)] or 0) for r in rows)
    return out


if __name__ == "__main__":
    note_id = sys.argv[1]
    tag = sys.argv[2]
    intent_text = sys.argv[3] if len(sys.argv) > 3 else ""
    max_rounds = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    budget = float(sys.argv[5]) if len(sys.argv) > 5 else 600
    checked = tuple(x for x in (os.environ.get("P15_CHECKED") or "").split("|") if x)
    print("real db before:", fp_line(db_guard.fingerprint(REAL_DB)), flush=True)
    scratch_db = DATA / "notes.sqlite3"
    c = sqlite3.connect(f"file:{scratch_db}?mode=ro", uri=True)
    min_id = c.execute("select coalesce(max(id),0) from llm_usage").fetchone()[0]
    c.close()
    res = asyncio.run(run_one(note_id, intent_text, checked, max_rounds, budget))
    res["usage"] = usage_since(scratch_db, min_id)
    print("real db after: ", fp_line(db_guard.fingerprint(REAL_DB)), flush=True)
    out = S / "runs"
    out.mkdir(exist_ok=True)
    (out / f"{note_id}-{tag}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("stopped", "seconds", "final_len", "orig_len", "checks_total_end", "usage")}, ensure_ascii=False))
    for r in res["rounds"]:
        print(f"round {r.get('round')}: checks={[(c.get('check'), c.get('ran'), (c.get('note') or '')[:110]) for c in r.get('checks', [])]} "
              f"fresh={len(r.get('fresh_units', []))} cited={r.get('fresh_units_cited')} note_links={r.get('note_links')} eval={(r.get('eval') or {}).get('status')}")
