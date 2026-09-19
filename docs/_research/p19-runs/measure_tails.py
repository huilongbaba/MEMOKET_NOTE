"""P19 #5：量 p5–p18 所有真跑里「每轮写出来的正文末尾」长什么样——中文垃圾尾巴（「 日本一本道」）出现过几次、
还有没有别的形状。只读 docs/_research/*-runs/ 的日志（md 的 `### streamed text` / json 的 rounds[].streamed）。"""
import json, re, sys
from pathlib import Path

ROOT = Path("/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-a5fdd08b1e5872b99/docs/_research")
END = re.compile(r"[。！？!?…」』）)\]]\s*$")
CITE_TAIL = re.compile(r"(\[[^\]]+\]\s*)+$")

texts: list[tuple[str, int, str]] = []          # (run, round, streamed text)
for d in sorted(ROOT.glob("p*-runs")):
    for f in sorted(d.iterdir()):
        if f.suffix == ".md":
            s = f.read_text(encoding="utf-8")
            parts = re.split(r"^## round (\d+)", s, flags=re.M)
            for i in range(1, len(parts), 2):
                rnd = int(parts[i]); body = parts[i + 1]
                m = re.search(r"### streamed text\n(.*?)(?=\n## round |\Z)", body, re.S)
                if m:
                    texts.append((f"{d.name}/{f.stem}", rnd, m.group(1).strip()))
        elif f.suffix == ".json":
            try:
                j = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            for r in (j.get("rounds", []) if isinstance(j, dict) else []):
                if not isinstance(r, dict):
                    continue
                st = (r.get("streamed") or "").strip()
                if st:
                    texts.append((f"{d.name}/{f.stem}", int(r.get("round") or 0), st))

print(f"rounds with streamed text: {len(texts)} across {len({t[0] for t in texts})} runs")
# 1) 末尾那一行 / 最后一句之后的残段
odd = []
for run, rnd, t in texts:
    last = t.rstrip().split("\n")[-1].strip()
    stripped = CITE_TAIL.sub("", last).rstrip()
    if not stripped:
        continue
    if END.search(stripped):
        continue
    # 最后一个句末标点之后的残段
    frag = re.split(r"[。！？!?]", stripped)[-1].strip()
    odd.append((run, rnd, len(frag), frag[:60], last[-80:]))
print(f"\nrounds whose last line does not end with sentence punctuation: {len(odd)}")
for o in odd:
    print(f"  {o[0]} r{o[1]} frag_len={o[2]} frag={o[3]!r}  | line_tail={o[4]!r}")

# 2) 已知垃圾词 + 「末尾短残段跟前文零重合」形状
KNOWN = ["一本道", "日本一本道"]
hits = []
for run, rnd, t in texts:
    for w in KNOWN:
        for m in re.finditer(re.escape(w), t):
            hits.append((run, rnd, w, t[max(0, m.start() - 30):m.end() + 10].replace("\n", "⏎")))
print(f"\nknown junk word hits: {len(hits)}")
for h in hits:
    print("  ", h)

# 3) 段末「空格 + 2-6 个汉字」且这几个字跟本段其它部分零 2-gram 重合（不看词表）——看看这形状在真跑里有多少
shape = []
for run, rnd, t in texts:
    for para in [p for p in re.split(r"\n\s*\n", t) if p.strip()]:
        m = re.search(r"[。！？!?」）)]\s+([一-鿿]{2,8})\s*$", para)
        if not m:
            continue
        tail = m.group(1); rest = para[:m.start(1)]
        grams = {tail[i:i + 2] for i in range(len(tail) - 1)}
        overlap = sum(1 for g in grams if g in rest)
        shape.append((run, rnd, tail, overlap, para[-60:].replace("\n", "⏎")))
print(f"\nparagraph-end 'space + 2-8 CJK chars' shape: {len(shape)}")
for s_ in shape:
    print("  ", s_)
