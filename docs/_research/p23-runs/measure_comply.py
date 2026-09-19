"""P23 #2 的替代量法（真模型那台连不上，见台账）：把 p15 / p18b / p19hint 三批真跑录下来的
每一轮正文重放一遍，逐轮量**两侧各自的照做率**——「上一轮点名的那几条，这一轮改了没有」。

零调用。这不是 P19 问的那个数（「带『上一轮就提过』之后模型照做率变没变」要一次新的真跑），
但它把**修之前的基线**钉死：出处那一侧在补、日期那一侧一条没补。
"""
from __future__ import annotations
import json, sys
from pathlib import Path

WT = Path("/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-ae5706de412997857/backend")
sys.path.insert(0, str(WT))
from app.harness.checks import done as D
from app.harness.checks.grounding_rules import abstention_lines
from app.editor import intent as doc_intent

RUNS = [("p15  da080", "docs/_research/p15-runs/da080ca847cf-p15.json"),
        ("p18b da080", "docs/_research/p18-runs/da080ca847cf-p18b.json"),
        ("p19  da080", "docs/_research/p19-runs/da080ca847cf-p19hint.json")]

tot = {"date": [0, 0], "cite": [0, 0]}     # [改掉的, 上一轮点过名的]
for tag, path in RUNS:
    d = json.load(open(WT.parent / path))
    done = doc_intent.done_of(d["intent"])
    start = d["orig"]
    fresh = lambda s: s.strip() not in start and not abstention_lines(s)
    texts = D.judgeable(done, tuple(d.get("intent_checked") or ()))
    prev = {"date": set(), "cite": set()}
    print(f"\n===== {tag} =====")
    for r in d["rounds"]:
        content = r.get("content_after") or ""
        now = {"date": set(), "cite": set()}
        for t in texts:
            res = D.check_done_item(t, content, unit_filter=fresh)
            if not res or res["status"] != "fail":
                continue
            # 一条判据同时管两件事：`bad` 只带走一侧，另一侧从 why 里读数不够，
            # 所以这里各算各的
            kind, texts_ = res["kind"], res.get("bad", [])
            for b in texts_:
                now[kind].add(b.strip()[:40])
        line = f"  r{r['round']}: 没日期 {len(now['date'])} 条 / 没出处 {len(now['cite'])} 条"
        for k in ("date", "cite"):
            if prev[k]:
                fixed = len([x for x in prev[k] if x not in now[k]])
                tot[k][0] += fixed
                tot[k][1] += len(prev[k])
                line += f"　| 上一轮点名的 {len(prev[k])} 条{'没日期' if k == 'date' else '没出处'}，这一轮改掉 {fixed} 条"
        print(line)
        prev = now

print("\n===== 三批合计（修前基线）=====")
for k, name in (("date", "日期"), ("cite", "出处")):
    f, n = tot[k]
    print(f"  {name}那一侧照做率：{f} / {n} = {0 if not n else f / n:.0%}")
