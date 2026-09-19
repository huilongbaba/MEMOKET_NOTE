"""P18 #1 量：p5–p15 全部真跑里「有判过分的轮之后出现判据命中轮 → BestOf 交更早的轮」发生几次。"""
import json, re, glob, os
ROOT = "/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-aa8e51b7bb76f8dd6/docs/_research"
runs = []
for md in sorted(glob.glob(ROOT + "/p*-d3-runs/*.md")):
    txt = open(md).read()
    head = txt.splitlines()[0]
    m = re.search(r"orig (\d+) → final (\d+) · stopped=(\S+)", head)
    if not m: continue
    final = int(m.group(2)); stopped = m.group(3)
    rounds = []
    for rm in re.finditer(r"^## round (\d+)\s+t=.*?len_after=(\d+)\n(.*?)(?=^## round |\Z)", txt, re.S | re.M):
        n, la, body = int(rm.group(1)), int(rm.group(2)), rm.group(3)
        cm = re.search(r"^checks: (\[.*\])$", body, re.M)
        checks = json.loads(cm.group(1)) if cm else []
        fired = [c["check"] for c in checks if not c.get("stuck_rounds")]
        levels = [int(x) for x in re.findall(r"^  - \w+: (\d) — ", body, re.M)]
        rounds.append(dict(n=n, len=la, fired=fired, levels=levels))
    runs.append(dict(name=os.path.relpath(md, ROOT), final=final, stopped=stopped, rounds=rounds))
for js in sorted(glob.glob(ROOT + "/p15-runs/*.json")) + sorted(glob.glob(ROOT + "/p13-runs/*.json")):
    d = json.load(open(js))
    rs = d["rounds"]; items = sorted(rs.items(), key=lambda kv: int(kv[0])) if isinstance(rs, dict) else list(enumerate(rs, 1))
    rounds = []
    for k, r in items:
        fired = [c["check"] for c in (r.get("checks") or []) if not c.get("stuck_rounds")]
        ev = r.get("eval") or {}
        levels = [v["level"] for v in (ev.get("scores") or {}).values()] if not fired else []
        rounds.append(dict(n=int(k), len=r["content_len"], fired=fired, levels=levels))
    runs.append(dict(name=os.path.relpath(js, ROOT), final=d["final_len"], stopped=d["stopped"], rounds=rounds))

def rank(r):
    if r["fired"] or not r["levels"]: return (0, 0.0) if r["fired"] else (-1, -1.0)
    return (sum(1 for v in r["levels"] if v >= 2), sum(r["levels"]) / len(r["levels"]))

tot = 0; hit = 0; by_check = {}
for run in runs:
    rs = run["rounds"]
    if len(rs) < 2: continue
    tot += 1
    best = None
    for r in rs:
        rk = rank(r)
        if best is None or rk >= best[0]: best = (rk, r)
    shipped = best[1]
    later = [r for r in rs if r["n"] > shipped["n"]]
    later_hit = [r for r in later if r["fired"]]
    flag = bool(later_hit) and shipped["levels"] and not shipped["fired"] and all(r["fired"] for r in later)
    line = " ".join(f"r{r['n']}:{(r['fired'][0] if r['fired'] else ('J'+str(rank(r)[0]) if r['levels'] else '?'))}/{r['len']}" for r in rs)
    mark = ""
    if flag:
        hit += 1
        for r in later_hit:
            by_check[r["fired"][0]] = by_check.get(r["fired"][0], 0) + 1
        mark = f"  <== 交 r{shipped['n']}({shipped['len']}字)，后面 {len(later)} 轮全命中、最长 {max(r['len'] for r in later)} 字"
    print(f"{run['name']:38s} stopped={run['stopped']:16s} final={run['final']:5d} | {line}{mark}")
print(f"\n多轮跑 {tot}，「判过分的轮之后全是命中轮 → 交更早那轮」{hit} 次；后面那些命中轮按判据：{by_check}")
