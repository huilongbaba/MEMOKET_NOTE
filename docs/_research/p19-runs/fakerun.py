"""P19 #6 的零成本复核：用假模型把 harness 真跑一遍（`loop.run` 原样），只看
`done_criteria` 连响时那句话有没有换过。真模型那次（da080-p19hint）是在修 `check_name_streak_prev`
之前跑的，三轮都没升级措辞；这条用假模型把修好之后的接线验完，不再花一次真调用。
"""
import asyncio
import dataclasses
import json
import os
import sqlite3
import sys
from pathlib import Path

S = Path("/private/tmp/claude-501/-Users-huilong-Skills-Bugfixing-Feishu/401a09f3-c80d-446c-a096-c81ed0fa949a/scratchpad/p19")
DATA = S / "fakedata"
os.environ["KITE_DATA_DIR"] = str(DATA)
os.chdir(str(DATA))

WT = Path("/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-a5fdd08b1e5872b99/backend")
sys.path.insert(0, str(WT))

from app.database import store                                     # noqa: E402
from app.editor.profile import entries as _profile                 # noqa: E402
from app.harness import loop, modes, tools                         # noqa: E402
from app.harness.events import EventType                           # noqa: E402
from app.harness.hooks.note import NoteHooks                       # noqa: E402
from app.harness.state import State                                # noqa: E402
from app.routers.note_harness import _score_context, MAX_ROUNDS_CAP  # noqa: E402

USER = "terrence"
NOTE = sys.argv[1]
INTENT = sys.argv[2]


async def main():
    note = store.get_note(USER, NOTE)
    assert note, NOTE
    beats = note.get("beats") or []
    if isinstance(beats, str):
        beats = json.loads(beats or "[]")
    mode = dataclasses.replace(
        modes.for_run(modes.NOTE, has_profile=bool(_profile(USER)), polish=False),
        max_rounds=min(4, MAX_ROUNDS_CAP), review_each_round=False, rails_off=("save",))
    st = State(mode=mode,
               ctx=tools.ToolContext(user=USER, note_id=NOTE, scope="all", note_title=note["title"],
                                     intent=INTENT, intent_checked=(), tray=store.list_tray(USER, NOTE)),
               request=None, content=note["content"] or "")
    hooks = NoteHooks(polish=False, spine=note.get("spine") or "", beats=beats, profile=_profile(USER))
    st.bag["polish"] = False
    async for _ in hooks.skeleton(st):
        pass
    st.bag["score_context"] = _score_context(st)

    hits = []
    cur = 0
    async for ev in loop.run(st, hooks):
        et = getattr(ev.type, "value", ev.type)
        d = ev.data or {}
        if et == EventType.STEP_STARTED.value:
            cur = int(d.get("step") or d.get("round") or cur + 1) if isinstance(d, dict) else cur + 1
        elif et == EventType.CUSTOM.value and d.get("name") == "check_hit":
            v = d.get("value") or {}
            if v.get("check") == "done_criteria" and v.get("ran"):
                hits.append((cur, v.get("note") or ""))
    print(f"done_criteria 命中轮: {[h[0] for h in hits]}")
    print(f"几轮原话一字不差: {len(set(h[1] for h in hits)) == 1}（命中 {len(hits)} 次，去重 {len(set(h[1] for h in hits))} 句）")
    for rnd, msg in hits:
        print(f"  r{rnd} 「上一轮就提过」= {'上一轮就提过' in msg} | {msg[:90]}…")


asyncio.run(main())
