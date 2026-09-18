"""P15 #4 量：这篇 143 段各自发给 kite 的查询长什么样——重复多少、grep 词命中几个 unit、多少段走行级回退。"""
import os, sys, re, time, json, collections
from pathlib import Path
S = Path("/private/tmp/claude-501/-Users-huilong-Skills-Bugfixing-Feishu/401a09f3-c80d-446c-a096-c81ed0fa949a/scratchpad/p15")
os.environ["KITE_DATA_DIR"] = str(S / "p15data")
os.chdir(str(S / "p15data"))
WT = Path("/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-a6d6a2a7e6304cf5a/backend")
sys.path.insert(0, str(WT))
from app.database import store as nstore
from app.database.kite.kite_memory import UserMemory
from app.database.kb import search

USER = "terrence"
NOTE = sys.argv[1] if len(sys.argv) > 1 else "309f19202309"
note = nstore.get_note(USER, NOTE)
paras = [p.strip() for p in re.split(r"\n\s*\n", note["content"]) if p.strip()]
paras = [p for p in paras if len(p) >= 8 and any(ch.isdigit() for ch in p)]
mem = UserMemory(USER)
kstore, vocab = mem._index()
print("facts", len(kstore.facts), "lines", len(kstore.lines), "units", len(kstore.units))

# 每个 unit 的事实文本 / 原话拼起来，量 grep 词落在几个 unit
unit_text = collections.defaultdict(list)
for f in kstore.facts.values():
    unit_text[f.unit].append(f.text.lower())
unit_blob = {u: "\n".join(t) for u, t in unit_text.items()}

total_q = 0
grep_terms = []
sym = 0
plans = []
for p in paras:
    q = search.clean_query(p)
    queries = search.plan(mem, q, vocab)[:3]        # kite parse_plan 只取前 3 条
    plans.append(queries)
    for qq in queries:
        total_q += 1
        w = qq.get("where") or {}
        if w.get("grep"):
            grep_terms.append(w["grep"])
        else:
            sym += 1
distinct = collections.Counter(grep_terms)
print(f"paras={len(paras)} subqueries={total_q} symbolic={sym} grep={len(grep_terms)} distinct_grep={len(distinct)}")
print("top repeated:", distinct.most_common(12))
hist = collections.Counter()
per_term_units = {}
for t in distinct:
    rx = re.compile(t, re.I)
    n = sum(1 for u, blob in unit_blob.items() if rx.search(blob))
    per_term_units[t] = n
    hist["0" if n == 0 else "1-8" if n <= 8 else "9-30" if n <= 30 else ">30"] += 1
print("grep term → #units hist:", dict(hist))
# 走行级回退的段：facts 为空
t0 = time.perf_counter()
fallback = 0
line_terms = []
for p in paras:
    rows, _terms, _took = mem.recall(p, limit=8, scope="all")
    # 复算：主通路 facts 空 = 回退（复刻 recall 里的判断）
    q = search.clean_query(p)
    queries = search.plan(mem, q, vocab)
    from memoket_kite.core.algebra import execute_plan
    rr, _ = execute_plan(kstore, vocab, {"queries": queries}, budget=search.POOL * 2) if queries else ([], None)
    facts = [r for r in rr if r.get("type") == "fact"]
    facts = search.rank(facts, q, mem, kstore, limit=32)
    if not facts:
        fallback += 1
        terms = (mem._cjk_terms(q) + mem._candidate_terms(q))[:12]
        line_terms += terms
print(f"fallback paras={fallback} line grep terms total={len(line_terms)} distinct={len(set(line_terms))} ({time.perf_counter()-t0:.1f}s)")
