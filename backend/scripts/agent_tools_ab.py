"""A/B：agent 自主检索（MEMOKET_AGENT_TOOLS=1）vs 预装配检索（=0）。

必须跑在**有真实知识库**的用户上，否则两边都查不到东西，`factual_grounding`
这一维没有区分度——writing bench 那个 `writing-bench` 用户是空库，测不出
这个改动的效果。所以这里用 terrence（20000+ 条事实），种子也挑跟他记录
实际相关的方向。

安全：每次都新建一次性笔记，`finally` 删除，绝不碰任何已有笔记。

用法（开关是模块级常量，改了要重启服务）：
    MEMOKET_AGENT_TOOLS=1 uvicorn ... ; python scripts/agent_tools_ab.py tools
    MEMOKET_AGENT_TOOLS=0 uvicorn ... ; python scripts/agent_tools_ab.py preassembled
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import writing_quality_bench as wb  # noqa: E402  —— 复用那 8 项写作质量检查

BASE_URL = "http://localhost:8000"
USER = "terrence"
OUT = Path(__file__).resolve().parent / "agent_tools_ab.jsonl"
ROUNDS = 2

SEEDS = [
    {"id": "量产未决项", "seed": (
        "## 硬件量产前的未决项\n\n"
        "样机阶段暴露的问题还没收敛完，得先把哪些是必须在量产前解决的列清楚。\n")},
    {"id": "定价与成本", "seed": (
        "## 定价要覆盖哪些成本\n\n"
        "报价不能只看物料，配件、渠道报备和汇率波动都得算进去，"
        "不然看着有毛利实际在亏。\n")},
    {"id": "团队对齐", "seed": (
        "## 进度对不齐的根源\n\n"
        "每次同步都说没问题，到节点才发现两边理解的完成标准不一样。\n")},
]


def parse_sse(text: str):
    events, ev = [], ""
    for frame in text.split("\n\n"):
        for line in frame.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:") and line[5:].strip():
                try:
                    events.append((ev, json.loads(line[5:].strip())))
                except json.JSONDecodeError:
                    pass
    return events


def run_one(client: httpx.Client, seed: dict, label: str) -> dict:
    H = {"X-User-Id": USER, "Content-Type": "application/json"}
    note = httpx.post(f"{BASE_URL}/api/notes", headers=H,
                      json={"title": f"ab-{label}-{seed['id']}", "content": seed["seed"],
                            "folder_id": None}, timeout=30).json()
    t0 = time.monotonic()
    try:
        buf = ""
        with client.stream("POST", f"{BASE_URL}/api/note-harness/run", headers=H,
                           json={"note_id": note["id"], "content": seed["seed"],
                                 "max_rounds": ROUNDS}, timeout=1800.0) as r:
            for chunk in r.iter_text():
                buf += chunk
        events = parse_sse(buf)
        final = httpx.get(f"{BASE_URL}/api/notes/{note['id']}", headers=H, timeout=30).json()
        text = final.get("content", "")
    finally:
        httpx.delete(f"{BASE_URL}/api/notes/{note['id']}", headers=H, timeout=30)

    evals = [p for e, p in events if e == "evaluate"]
    toolcalls = [p for e, p in events if e == "tool-calls"]
    policies = [p for e, p in events if e == "policy"]
    last = evals[-1]["scores"] if evals else {}
    checks = [(n, *(fn(text, seed["seed"]) if n == "数字无据" else fn(text)))
              for n, fn in wb.CHECKS]
    rec = {
        "label": label, "seed": seed["id"],
        "elapsed_s": round(time.monotonic() - t0, 1),
        "rounds_run": len(evals),
        "final_status": evals[-1]["status"] if evals else "",
        "scores": {k: v["level"] for k, v in last.items()},
        "grounding_note": (last.get("factual_grounding") or {}).get("note", ""),
        "tool_calls": sum(len(t["calls"]) for t in toolcalls),
        "tools_used": sorted({c["tool"] for t in toolcalls for c in t["calls"]}),
        "checks_failed": [n for n, ok, _ in checks if not ok],
        "per_round_grounding": [ev["scores"].get("factual_grounding", {}).get("level")
                                for ev in evals],
        "policy_events": [{"round": pe["round"], "reasons": pe["reasons"],
                           "tool_iters": pe["policy"]["tool_iters"],
                           "temp": pe["policy"]["continue_temperature"]}
                          for pe in policies],
        "chars": len(text),
    }
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"  [{label}] {seed['id']}: grounding={rec['scores'].get('factual_grounding','?')} "
          f"status={rec['final_status']} 工具={rec['tool_calls']} "
          f"检查失败={rec['checks_failed'] or '无'} {rec['elapsed_s']}s", flush=True)
    for pe in rec["policy_events"]:
        print(f"      ↻ 第{pe['round']}轮后调整 → 工具预算{pe['tool_iters']} 温度{pe['temp']}"
              f" ｜ {'；'.join(pe['reasons'])}", flush=True)
    return rec


def main() -> None:
    label = sys.argv[1] if len(sys.argv) > 1 else "tools"
    client = httpx.Client()
    print(f"=== {label} ===", flush=True)
    for seed in SEEDS:
        try:
            run_one(client, seed, label)
        except Exception as exc:
            print(f"  失败 {seed['id']}: {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
