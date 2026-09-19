"""P23 #1 前后对比（零调用）：拿 p15 / p18b / p19hint 三批**真跑录下来的每一轮正文**，
把真的 `Checks.before_judge` 中间件原样跑一遍，看 `done_criteria` 每轮说了什么、正文动没动。

`--before` 走一个把 P23 修法整条撤掉的猴补丁（date_pending_ok 恒 False + 不给 fix），
不带这个参数就是修后。两边跑同一份录像，差在判据自己。
"""
from __future__ import annotations
import asyncio, dataclasses, json, sys
from pathlib import Path

WT = Path("/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-ae5706de412997857/backend")
sys.path.insert(0, str(WT))

BEFORE = "--before" in sys.argv

from app.harness import modes, tools                       # noqa: E402
from app.harness.checks import done as D                   # noqa: E402
from app.harness.middleware.checks import Checks           # noqa: E402
from app.harness.state import State                        # noqa: E402
from app.harness.events import CUSTOM_CHECK_HIT            # noqa: E402

if BEFORE:
    _orig_item = D.check_done_item

    def _no_pending(item, content, *, unit_filter=None, date_pending_ok=False):
        return _orig_item(item, content, unit_filter=unit_filter, date_pending_ok=False)

    D.check_done_item = _no_pending
    _orig_verdict = D.Verdict

    class _NoFix(_orig_verdict):          # type: ignore[misc]
        pass

    def _verdict(dimension, message, fix=None, fix_done=None):
        return _orig_verdict(dimension=dimension, message=message)

    D.Verdict = _verdict                  # type: ignore[assignment]

RUNS = [
    ("p15  da080", "docs/_research/p15-runs/da080ca847cf-p15.json"),
    ("p18b da080", "docs/_research/p18-runs/da080ca847cf-p18b.json"),
    ("p19  da080", "docs/_research/p19-runs/da080ca847cf-p19hint.json"),
]


async def replay(tag: str, path: str) -> None:
    d = json.load(open(WT.parent / path))
    mode = dataclasses.replace(
        modes.for_run(modes.NOTE, has_profile=False, polish=False),
        max_rounds=len(d["rounds"]), review_each_round=False, rails_off=("save",))
    st = State(mode=mode,
               ctx=tools.ToolContext(user="terrence", note_id=d["note_id"], scope="all",
                                     note_title=d["title"], intent=d["intent"],
                                     intent_checked=tuple(d.get("intent_checked") or ()), tray=()),
               request=None, content=d["orig"])
    st.bag["polish"] = False
    st.bag["content_at_start"] = d["orig"]
    from app.harness.middleware.done import DoneCriteria
    await DoneCriteria().before_run(st)
    assert D.done_criteria in st.mode.checks, "done_criteria 没挂上"
    mw = Checks()
    print(f"\n===== {tag} ({'修前' if BEFORE else '修后'}) =====")
    for r in d["rounds"]:
        st.round = r["round"]
        st.content = r["content_after"] or ""
        before_len = len(st.content)
        st.ev = None
        st.skip_judge = False
        hits = []
        async for ev in mw.before_judge(st):
            v = (ev.data or {}).get("value") or {}
            if (ev.data or {}).get("name") == CUSTOM_CHECK_HIT:
                hits.append(v)
        marked = st.content.count(D.DATE_PENDING)
        changed = len(st.content) - before_len
        line = f"  r{r['round']}: "
        if not hits:
            line += "（没有判据命中）"
        for v in hits:
            line += f"[{v.get('check')}] {(v.get('note') or '')[:95]}"
        print(line)
        if changed:
            print(f"        >> 判据自己改了正文：{before_len} -> {len(st.content)} 字符，"
                  f"「{D.DATE_PENDING}」共 {marked} 处")


async def main() -> None:
    for tag, path in RUNS:
        await replay(tag, path)


asyncio.run(main())
