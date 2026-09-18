"""P8b (same script as P8, only paths changed; RELEVANCE_FILTER default off): run 智能续写 (note mode) once on one real note, on the scratch copy.

Usage: p5_run.py <note_id> [wall_budget_seconds]

Mirrors routers/note_harness.py::run exactly (max_rounds=20 from the frontend,
scope=all, spine/beats as stored on the note, profile from store), plus
rails_off=("save",). Everything runs on KITE_DATA_DIR=<scratch>/p5data; the
real DB is only fingerprinted (db_guard.Watch) before/after.
"""
from __future__ import annotations

import os, sys, json, time, asyncio, dataclasses, hashlib, re, sqlite3
from pathlib import Path

S = Path("/private/tmp/claude-501/-Users-huilong-Skills-Bugfixing-Feishu/401a09f3-c80d-446c-a096-c81ed0fa949a/scratchpad/p8b")
DATA = S / "p8bdata"
os.environ["KITE_DATA_DIR"] = str(DATA)
os.chdir(str(DATA))

WT = Path("/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-a588b6af1373db574/backend")
sys.path.insert(0, str(WT / "scripts"))
sys.path.insert(0, str(WT))
REAL_DB = Path("/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/backend/data/notes.sqlite3")

import db_guard                                              # noqa: E402
from app.database import store                               # noqa: E402
from app.harness import loop, modes, tools                   # noqa: E402
from app.harness.events import EventType                      # noqa: E402
from app.harness.hooks.note import NoteHooks                  # noqa: E402
from app.harness.state import State                           # noqa: E402
from app.routers.note_harness import _score_context, MAX_ROUNDS_CAP, rounds_for  # noqa: E402
from app.editor.profile import entries as _profile            # noqa: E402
from app.database.kite.kite_memory import UserMemory          # noqa: E402

USER = "terrence"
CITE = re.compile(r"\[(terrence-[0-9A-Za-z-]+)\]")


def fp_line(fp) -> str:
    dd = hashlib.sha256(json.dumps(fp.digests, sort_keys=True).encode()).hexdigest()[:16]
    return (f"notes={fp.rows['notes']} note_revisions={fp.rows['note_revisions']} "
            f"max(updated_at)={fp.latest['notes']} chars={fp.chars} digest={dd}")


async def run_one(note_id: str, budget: float) -> dict:
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
        max_rounds=rounds_for(None, modes.NOTE), review_each_round=False,
        rails_off=("save",))
    st = State(mode=mode,
               ctx=tools.ToolContext(user=USER, note_id=note_id, scope="all",
                                     note_title=note["title"]),
               request=None, content=content)
    hooks = NoteHooks(polish=False, spine=spine, beats=beats, profile=profile)
    st.bag["polish"] = False

    log: list[dict] = []
    rounds: dict[int, dict] = {}
    cur = 0
    t0 = time.perf_counter()
    stopped = ""
    finished = None

    def rec(kind: str, **kw):
        log.append({"t": round(time.perf_counter() - t0, 1), "round": cur, "kind": kind, **kw})

    async for ev in hooks.skeleton(st):
        d = ev.data or {}
        rec("skeleton", name=d.get("name"), value=d.get("value"))
    st.bag["score_context"] = _score_context(st)
    rec("bag", outline_mode=st.bag.get("outline_mode"), spine=st.bag.get("spine"),
        beats=st.bag.get("beats"), profile_n=len(profile), dims=[d.name for d in mode.dims],
        skill_menu=list(getattr(st, "skill_menu", []) or []))

    try:
        async for ev in loop.run(st, hooks):
            et = getattr(ev.type, "value", ev.type)
            d = ev.data or {}
            if et == EventType.STEP_STARTED.value:
                cur = int(d.get("step") or d.get("round") or cur + 1) if isinstance(d, dict) else cur + 1
                rounds[cur] = {"round": cur, "t_start": round(time.perf_counter() - t0, 1),
                               "streamed": "", "scrub": [], "dedup": [], "checks": [],
                               "policy": [], "warnings": [], "summary": None, "eval": None,
                               "revisions": [], "dropped": [], "cost": None, "insert_at": None}
                rec("step_started", data=d)
            elif et == EventType.TEXT_MESSAGE_CONTENT.value:
                rounds.setdefault(cur, {"streamed": ""})["streamed"] += d.get("delta", "") or d.get("content", "") or ""
            elif et == EventType.STEP_FINISHED.value:
                r = rounds.setdefault(cur, {})
                r["t_end"] = round(time.perf_counter() - t0, 1)
                r["content_after"] = st.content
                r["content_len"] = len(st.content)
                rec("step_finished", content_len=len(st.content))
                if time.perf_counter() - t0 > budget:
                    stopped = "p5_wall_budget"
                    rec("p5_budget_break")
                    break
            elif et == EventType.RUN_FINISHED.value:
                stopped = d.get("reason", "") or ""
                finished = d
                rec("run_finished", data={k: v for k, v in d.items() if k != "content"})
            elif et == EventType.RUN_ERROR.value:
                stopped = "error"
                rec("run_error", data=d)
            elif et == EventType.CUSTOM.value:
                name, val = d.get("name"), d.get("value")
                r = rounds.setdefault(cur, {})
                if name == "evaluate":
                    r["eval"] = val
                elif name == "scrub":
                    r.setdefault("scrub", []).append(val)
                elif name == "dedup":
                    r.setdefault("dedup", []).append(val)
                elif name == "check_hit":
                    r.setdefault("checks", []).append(val)
                elif name == "policy":
                    r.setdefault("policy", []).append(val)
                elif name == "warning":
                    r.setdefault("warnings", []).append(val)
                elif name == "round_summary":
                    r["summary"] = val
                elif name == "revision":
                    r.setdefault("revisions", []).append(val)
                elif name == "dropped":
                    r.setdefault("dropped", []).append(val)
                elif name == "cost":
                    r["cost"] = val
                elif name == "insert_at":
                    r["insert_at"] = val
                else:
                    rec("custom", name=name, value=val)
            elif et == EventType.TOOL_CALL_RESULT.value:
                rounds.setdefault(cur, {}).setdefault("tool_calls", []).append(json.dumps(d, ensure_ascii=False)[:400])
            else:
                if et not in ("TEXT_MESSAGE_START", "TEXT_MESSAGE_END", "RUN_STARTED", "ACTIVITY_SNAPSHOT"):
                    rec("event", type=et, data=d if isinstance(d, dict) and len(json.dumps(d, ensure_ascii=False)) < 500 else "…")
    finally:
        pass
    seconds = round(time.perf_counter() - t0, 1)
    final = st.content
    new_cites = [c for c in CITE.findall(final) if c not in set(CITE.findall(content))]
    facts = {}
    mem = UserMemory(USER)
    for fid in dict.fromkeys(CITE.findall(final)):
        f = mem.fact_by_id(fid)
        facts[fid] = {"fact": f, "sources": mem.fact_sources(fid) if f else [],
                      "new": fid in set(new_cites)}
    return {"note_id": note_id, "title": note["title"], "orig_len": len(content),
            "final_len": len(final), "orig": content, "final": final,
            "stopped": stopped, "st_stopped": getattr(st, "stopped", ""),
            "finished": finished, "seconds": seconds, "rounds": rounds, "log": log,
            "facts_used": list(st.facts or []), "facts_index": st.bag.get("facts_index"),
            "citations": facts, "best": (st.best[0] if st.best else None)}


def usage_since(db: Path, since_id: int) -> dict:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT feature, model, count(*), sum(prompt_tokens), sum(completion_tokens), sum(cached_tokens), sum(ms) "
        "FROM llm_usage WHERE id > ? GROUP BY feature, model", (since_id,)).fetchall()
    tot = conn.execute(
        "SELECT count(*), coalesce(sum(prompt_tokens),0), coalesce(sum(completion_tokens),0), coalesce(sum(cached_tokens),0) "
        "FROM llm_usage WHERE id > ?", (since_id,)).fetchone()
    conn.close()
    return {"by_feature": [list(r) for r in rows],
            "calls": tot[0], "prompt": tot[1], "completion": tot[2], "cached": tot[3]}


def harness_rows(db: Path, note_id: str, since: str) -> dict:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    runs = [dict(zip([c[0] for c in cur.description], r)) for cur in [conn.execute(
        "SELECT * FROM harness_runs WHERE key=? AND created_at>=? ORDER BY created_at", (note_id, since))]
        for r in cur.fetchall()]
    rounds = [dict(zip([c[0] for c in cur.description], r)) for cur in [conn.execute(
        "SELECT round, status, weakest, content_len, facts_new, facts_total, tool_calls, repeat_calls, "
        "cached_calls, revisions_proposed, revisions_dropped, claim_atoms, fired_checks, abstained "
        "FROM harness_rounds WHERE key=? AND created_at>=? ORDER BY round", (note_id, since))]
        for r in cur.fetchall()]
    conn.close()
    return {"runs": runs, "rounds": rounds}


def main() -> int:
    note_id = sys.argv[1]
    budget = float(sys.argv[2]) if len(sys.argv) > 2 else 520.0
    out_dir = S / "runs"
    out_dir.mkdir(exist_ok=True)
    scratch_db = DATA / "notes.sqlite3"
    conn = sqlite3.connect(f"file:{scratch_db}?mode=ro", uri=True)
    since_id = conn.execute("SELECT coalesce(max(id),0) FROM llm_usage").fetchone()[0]
    conn.close()
    import datetime as _dt
    since_ts = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    before = db_guard.fingerprint(REAL_DB)
    print("[fp before]", fp_line(before), flush=True)
    with db_guard.Watch(REAL_DB):
        res = asyncio.run(run_one(note_id, budget))
    after = db_guard.fingerprint(REAL_DB)
    print("[fp after ]", fp_line(after), flush=True)
    res["usage"] = usage_since(scratch_db, since_id)
    res["harness_rows"] = harness_rows(scratch_db, note_id, since_ts)
    res["fp_before"], res["fp_after"] = fp_line(before), fp_line(after)
    (out_dir / f"{note_id}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    # readable dump
    md = [f"# {note_id} · {res['title']!r} · orig {res['orig_len']} → final {res['final_len']} · stopped={res['stopped']} · {res['seconds']}s",
          f"usage: calls={res['usage']['calls']} prompt={res['usage']['prompt']} completion={res['usage']['completion']} cached={res['usage']['cached']}",
          f"by_feature: {res['usage']['by_feature']}", ""]
    for k, r in sorted(res["rounds"].items(), key=lambda kv: int(kv[0])):
        md.append(f"\n## round {k}  t={r.get('t_start')}→{r.get('t_end')}  len_after={r.get('content_len')}")
        if r.get("summary"):
            md.append(f"summary: {json.dumps(r['summary'], ensure_ascii=False)[:1500]}")
        md.append(f"tool_calls: {json.dumps(r.get('tool_calls'), ensure_ascii=False)[:3000]}")
        md.append(f"checks: {json.dumps(r.get('checks'), ensure_ascii=False)[:1500]}")
        md.append(f"policy: {json.dumps(r.get('policy'), ensure_ascii=False)[:1500]}")
        md.append(f"warnings: {json.dumps(r.get('warnings'), ensure_ascii=False)[:800]}")
        md.append(f"revisions: {len(r.get('revisions') or [])} dropped: {len(r.get('dropped') or [])} insert_at: {r.get('insert_at')}")
        md.append(f"scrub: {json.dumps(r.get('scrub'), ensure_ascii=False)[:1500]}")
        md.append(f"dedup: {json.dumps(r.get('dedup'), ensure_ascii=False)[:2500]}")
        ev = r.get("eval") or {}
        md.append(f"eval: status={ev.get('status')} weakest={ev.get('weakest')}")
        for dn, sc in (ev.get("scores") or {}).items():
            md.append(f"  - {dn}: {sc.get('level')} — {sc.get('note')}")
        md.append(f"cost: {r.get('cost')}")
        md.append("\n### streamed text\n")
        md.append(r.get("streamed", "") or "(nothing streamed)")
    md.append("\n\n# FINAL CONTENT\n")
    md.append(res["final"])
    md.append("\n\n# CITATIONS\n")
    for fid, c in res["citations"].items():
        f = c["fact"]
        md.append(f"- [{fid}] new={c['new']} → " + (json.dumps(f, ensure_ascii=False)[:600] if f else "**NOT FOUND**"))
        for s in c["sources"][:3]:
            md.append(f"    src: {s.get('unit')} {s.get('date')} {s.get('who')}: {s.get('text')[:300]}")
    md.append("\n\n# FACTS GIVEN TO MODEL (st.facts)\n")
    for f in res["facts_used"]:
        md.append(f"- {f}")
    md.append("\n\n# harness_rows\n" + json.dumps(res["harness_rows"], ensure_ascii=False, indent=1))
    (out_dir / f"{note_id}.md").write_text("\n".join(md), encoding="utf-8")
    print(f"[done] {note_id} stopped={res['stopped']} rounds={len(res['rounds'])} "
          f"len {res['orig_len']}→{res['final_len']} {res['seconds']}s usage={res['usage']['calls']} calls "
          f"prompt={res['usage']['prompt']} completion={res['usage']['completion']} cached={res['usage']['cached']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
