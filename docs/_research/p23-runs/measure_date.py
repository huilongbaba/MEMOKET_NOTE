"""P23 #1 先量：p13 / p15 / p18 / p19 四批真跑里「日期那一侧」一共几处，fix 补上去会不会误伤。

零调用：只读 docs/_research/*-runs/*.json 里已经跑完的每一轮正文，拿 checks/done.py 原样重放。
"""
from __future__ import annotations
import json, glob, sys, re
from pathlib import Path

WT = Path("/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-ae5706de412997857/backend")
sys.path.insert(0, str(WT))
from app.harness.checks import done as D
from app.harness.checks.grounding_rules import abstention_lines
from app.editor import intent as doc_intent

FILES = sorted(glob.glob(str(WT.parent / "docs/_research/p1[3589]*-runs/*.json")))

total_hits = 0
units_seen = {}
for f in FILES:
    d = json.load(open(f))
    rounds = d["rounds"]
    if not rounds or not isinstance(rounds[0], dict):
        continue
    done = doc_intent.done_of(d["intent"])
    checked = tuple(d.get("intent_checked") or ())
    start = d["orig"]
    fresh = lambda s: s.strip() not in start and not abstention_lines(s)
    texts = D.judgeable(done, checked)
    tag = Path(f).stem
    for r in rounds:
        content = r.get("content_after") or ""
        for t in texts:
            res = D.check_done_item(t, content, unit_filter=fresh)
            if not res or res["status"] != "fail" or res["kind"] != "date":
                continue
            total_hits += 1
            bad = res.get("bad", [])
            print(f"[{tag}] r{r['round']} 「{t}」 {res['why']}  bad={len(bad)}")
            for b in bad:
                head = b.strip().splitlines()[0][:38]
                key = f"{tag}::{head}"
                units_seen.setdefault(key, {"tag": tag, "head": head, "rounds": [], "text": b, "file": f})
                units_seen[key]["rounds"].append(r["round"])
                print(f"        . {head}...")

print(f"\n日期那一侧命中总数（轮 x 判据）：{total_hits}")
print(f"不同的「没日期」单位：{len(units_seen)}")
print("\n每个单位在后面的轮里有没有被模型真的补上日期：")
never = 0
for k, v in units_seen.items():
    d = json.load(open(v["file"]))
    last_round = d["rounds"][-1]["round"]
    final = d["final"]
    probe = v["text"].strip()[:30]
    still_in_final = probe in final
    has_date_in_final = False
    if still_in_final:
        for para in re.split(r"\n\s*\n", final):
            if probe in para:
                has_date_in_final = bool(D._R["date"].search(para))
                break
    print(f"  [{v['tag']}] 点名轮次 {v['rounds']}（这一跑共 {last_round} 轮）"
          f" 还在终稿里={still_in_final} 终稿里有日期={has_date_in_final} :: {v['head']}...")
    if still_in_final and not has_date_in_final:
        never += 1
print(f"\n**模型一次都没补上真日期的单位：{never} / {len(units_seen)}**")
