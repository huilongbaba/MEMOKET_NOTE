"""所有写作功能的多轮回归：每个功能跑多个不同种子，看聚合结果。

单次跑出来的好坏说明不了什么——这一晚上反复吃过 n=1 的亏（一次好就以为
修好了，换个种子又崩）。这里每个功能跑 3 个不同种子，统计各维度打分、
结构保护、机制泄漏、审计腔、工具选择分布，最后给一张聚合表。

跑在 ``terrence-rewrite``（写作式抽取的新库）上，临时笔记跑完即删。

用法：
    python scripts/suite.py            # 全部
    python scripts/suite.py write      # 只跑某一组
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
USER = "terrence-rewrite"
H = {"X-User-Id": USER, "Content-Type": "application/json"}
OUT = Path(__file__).resolve().parents[2] / "samples"

_HEADING = re.compile(r"^(#{1,6})\s+(\S.*?)\s*$", re.M)
# 不该出现在用户笔记里的两类话：把工作机制写进正文，以及关于证据充分性的元评论。
# **词表从 app.grounding_check 导入，不在这里另写一份**——之前两边各写各的，
# 漂移出「无法判断」「仍需与」这两个 bench 报得出来、scrub 删不掉的词。
from app.grounding_check import AUDIT_PHRASES as AUDIT  # noqa: E402
from app.grounding_check import LEAK_PHRASES as LEAK  # noqa: E402
# 占位符：写了个坑没填，等于没写
PLACEHOLDER = re.compile(r"待指定|待倒排|待定|待补|待确认|待明确|TBD|（待|待填")
# 顾问腔：写的是"这件事应该怎么安排"而不是这件事本身。旧代码产出的真实笔记
# （samples/note-*.md、plan-*.md）基线是 4~11%，25% 以上就是跑偏了。
ADVICE = re.compile(r"[^。；\n]*?(?:应当|应该|应|需要|建议|必须)[^。；\n]{3,}")


def advice_ratio(text: str) -> int:
    ss = [x for x in re.split(r"[。；\n]", text) if len(x.strip()) > 8]
    return round(sum(1 for x in ss if ADVICE.search(x)) / max(1, len(ss)) * 100)

WRITE_SEEDS = [
    ("众筹节奏", "## 众筹的节奏怎么定\n\n三月上旬要启动，前后有一串依赖得理清楚。\n"),
    ("产品取舍", "## 这一轮产品取舍\n\n功能想做的很多，得先定哪些进这一版。\n"),
    ("团队协作", "## 协作里的卡点\n\n每次同步都说没问题，到节点才发现理解不一样。\n"),
]
POLISH_SEEDS = [
    ("重复标题", "## 众筹节奏\n\n三月上旬启动。\n\n## 众筹节奏\n\n三月上旬启动众筹。\n\n综上所述，要盯紧。\n\n## 还有\n\n媒体版本另算。\n"),
    ("多个结尾", "## 定价\n\n先看成本。\n\n综上所述，按成本加成。\n\n## 渠道\n\n渠道要报备。\n\n总而言之，报价前核对。\n"),
    ("编号错乱", "## 三件事\n\n### 1. 甲\n甲的说明。\n\n### 3. 乙\n乙的说明。\n\n### 2. 丙\n丙的说明。\n"),
]
OUTLINES = [
    ("三层大纲", "创业一年回顾\n\n## 时间线\n\n### 产品\n\n### 众筹\n\n## 团队\n\n## 反思\n"),
    ("两层大纲", "季度复盘\n\n## 做成了什么\n\n## 没做成什么\n\n## 下一步\n"),
    ("深层大纲", "产品规划\n\n## 现状\n\n### 已上线\n\n### 在做\n\n## 目标\n\n### 三个月\n\n### 半年\n"),
]
TAP_SEEDS = [
    "## 众筹准备\n\n三月上旬要启动。",
    "## 包装方案\n\n挂件和夹子两种形态还没定。",
    "## 邮件送达\n\n很多外发邮件进了垃圾箱。",
]


def sse(url: str, payload: dict, timeout: float = 3600) -> list[tuple[str, dict]]:
    buf = ""
    with httpx.Client() as c:
        with c.stream("POST", url, headers=H, json=payload, timeout=timeout) as r:
            for chunk in r.iter_text():
                buf += chunk
    ev, out = "", []
    for frame in buf.split("\n\n"):
        for line in frame.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:") and line[5:].strip():
                try:
                    out.append((ev, json.loads(line[5:].strip())))
                except json.JSONDecodeError:
                    pass
    return out


def run_note(title: str, seed: str, rounds: int, mode: str = "write") -> dict:
    n = httpx.post(f"{BASE}/api/notes", headers=H,
                   json={"title": f"suite-{title}", "content": seed, "folder_id": None},
                   timeout=30).json()
    t0 = time.monotonic()
    try:
        out = sse(f"{BASE}/api/note-harness/run",
                  {"note_id": n["id"], "content": seed, "max_rounds": rounds, "mode": mode})
        fin = httpx.get(f"{BASE}/api/notes/{n['id']}", headers=H, timeout=30).json()["content"]
    finally:
        httpx.delete(f"{BASE}/api/notes/{n['id']}", headers=H, timeout=30)

    evals = [p for e, p in out if e == "evaluate"]
    return {
        "title": title, "seed": seed, "final": fin, "secs": time.monotonic() - t0,
        "rounds": len(evals),
        "scores": {k: v["level"] for k, v in evals[-1]["scores"].items()} if evals else {},
        "done": next((p.get("reason") for e, p in out if e == "done"), ""),
        "tools": [c["tool"] for e, p in out if e == "tool-calls" for c in p["calls"]],
        "revisions": sum(1 for e, _ in out if e == "revision"),
        # 被确定性防线丢弃的修订，以及被删掉的元话语句子。后者是为了回答
        # "删句子有没有伤到连贯"——只看总分分不清噪声和真伤害。
        "dropped": sum(1 for e, _ in out if e == "dropped"),
        "meta_scrubbed": sum(1 for e, p in out if e == "dropped"
                             and "元话语" in (p.get("detail") or "")),
        "deltas": sum(1 for e, _ in out if e == "delta"),
        "leak": [w for w in LEAK if w in fin],
        "audit": [w for w in AUDIT if w in fin],
        "advice": advice_ratio(fin),
        "hollow": len(PLACEHOLDER.findall(fin)),
    }


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    report: list[str] = [f"# 写作功能多轮回归\n\n跑于 {datetime.now():%Y-%m-%d %H:%M} · 知识库 `{USER}`\n"]
    all_tools: Counter = Counter()

    def section(name: str, rows: list[dict], extra_cols: dict | None = None):
        report.append(f"\n## {name}\n")
        cols = ["种子", "轮", "耗时", "修订", "终止"] + list((extra_cols or {}).keys())
        report.append("| " + " | ".join(cols) + " |")
        report.append("|" + "---|" * len(cols))
        for r in rows:
            vals = [r["title"], str(r["rounds"]), f"{r['secs']:.0f}s",
                    str(r["revisions"]), r["done"]]
            vals += [str((extra_cols or {})[k](r)) for k in (extra_cols or {})]
            report.append("| " + " | ".join(vals) + " |")

    if only in ("", "write"):
        print("═══ 智能续写 ×3 ═══", flush=True)
        rows = []
        for t, s in WRITE_SEEDS:
            r = run_note(t, s, 3)
            all_tools.update(r["tools"])
            rows.append(r)
            print(f"  {t}: {r['rounds']}轮 {r['secs']:.0f}s {len(r['final'])}字 "
                  f"打分={r['scores']} 顾问腔{r['advice']}% 占位符{r['hollow']} "
                  f"泄漏={r['leak'] or '无'} 审计={r['audit'] or '无'}", flush=True)
        section("智能续写", rows, {
            "字数": lambda r: len(r["final"]),
            "material_use": lambda r: r["scores"].get("material_use", "-"),
            "coherence": lambda r: r["scores"].get("coherence", "-"),
            "顾问腔": lambda r: f"{r['advice']}%",
            "占位符": lambda r: r["hollow"],
            "泄漏/审计": lambda r: (r["leak"] + r["audit"]) or "无",
        })

    if only in ("", "polish"):
        print("\n═══ 打磨 ×3 ═══", flush=True)
        rows = []
        for t, s in POLISH_SEEDS:
            r = run_note(t, s, 3, mode="polish")
            rows.append(r)
            print(f"  {t}: {r['rounds']}轮 {r['secs']:.0f}s 修订{r['revisions']}条 "
                  f"续写={r['deltas']>0}(应False) 终止={r['done']}", flush=True)
        section("打磨（只修不写）", rows, {
            "误续写": lambda r: "❌" if r["deltas"] else "✅",
            "字数变化": lambda r: f"{len(r['seed'])}→{len(r['final'])}",
        })

    if only in ("", "outline"):
        print("\n═══ 大纲保护 ×3 ═══", flush=True)
        rows = []
        for t, s in OUTLINES:
            r = run_note(t, s, 3)
            orig = [(len(m.group(1)), m.group(2)) for m in _HEADING.finditer(s)]
            now = [(len(m.group(1)), m.group(2)) for m in _HEADING.finditer(r["final"])]
            r["struct_exact"] = now == orig
            r["text_ok"] = [t2 for _l, t2 in now if (_l, t2) in orig or any(t2 == o[1] for o in orig)] \
                and [t2 for _l, t2 in now if any(t2 == o[1] for o in orig)] == [o[1] for o in orig]
            rows.append(r)
            print(f"  {t}: 文字+顺序={r['text_ok']} 含层级={r['struct_exact']} "
                  f"泄漏={r['leak'] or '无'} 审计={r['audit'] or '无'} {len(r['final'])}字", flush=True)
        section("大纲结构保护", rows, {
            "标题+顺序": lambda r: "✅" if r["text_ok"] else "❌",
            "层级也对": lambda r: "✅" if r["struct_exact"] else "❌",
            "泄漏/审计": lambda r: (r["leak"] + r["audit"]) or "无",
        })

    if only in ("", "tap"):
        print("\n═══ magic tap ×3 ═══", flush=True)
        report.append("\n## magic tap\n\n| 种子 | 检索 | 用上 | 提示 |\n|---|---|---|---|")
        for s in TAP_SEEDS:
            buf = ""
            with httpx.Client() as c:
                with c.stream("POST", f"{BASE}/api/magic-tap", headers=H,
                              json={"content": s, "spine": "", "beats": [], "max_tokens": 300},
                              timeout=600) as r:
                    for chunk in r.iter_text():
                        buf += chunk
            g = {}
            for frame in buf.split("\n\n"):
                if "event: grounding" in frame:
                    try:
                        g = json.loads(frame.split("data:")[-1].strip())
                    except json.JSONDecodeError:
                        pass
            print(f"  {s[:14]}…: 检索{g.get('facts','?')}条 用上{g.get('used','?')}条 "
                  f"{'提示：'+g['hint'][:20] if g.get('hint') else '无提示'}", flush=True)
            report.append(f"| {s[:16]} | {g.get('facts','?')} | {g.get('used','?')} | "
                          f"{g.get('hint','') or '无'} |")

    if all_tools:
        report.append("\n## 工具选择分布\n")
        report.append("| 工具 | 次数 |\n|---|---|")
        for k, v in all_tools.most_common():
            report.append(f"| {k} | {v} |")
        print(f"\n工具分布: {dict(all_tools)}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "回归-写作功能.md").write_text("\n".join(report), encoding="utf-8")
    print(f"\n报告 → samples/回归-写作功能.md", flush=True)


if __name__ == "__main__":
    main()
