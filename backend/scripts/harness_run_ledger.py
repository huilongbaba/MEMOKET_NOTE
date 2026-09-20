"""**跑批台账**：把 `harness_runs` / `harness_rounds` 蒸馏成一份**进 git 的 JSONL**，逐批追加。

    .venv/bin/python scripts/harness_run_ledger.py --stats
    .venv/bin/python scripts/harness_run_ledger.py --append --label p63 --db <某个 notes.sqlite3>

## 为什么要它（P63 #3）

P61 #4 要答「那 6 个 block 模式要不要也停 `check_stuck`」，量出来的是
**「判据连响到底然后跑满」= 0 次**——可那个 0 的**分母只有 3 轮**，
因为「判据真响过的轮」库里总共就 3 轮。P59 明明跑过 **284 轮 / 61 份跑**，
但那些跑落在 `KITE_DATA_DIR=$S/p59/…` 里，**`$S/p59/` 跟着 scratch 一起清掉了**。

这是同一个形状的第三次：P34 那 47 条标注、P60 的圆点尺子、P59 的 run json。
**进不了仓库的东西，下一批就当它没存在过。**

## 为什么是「蒸馏成 JSONL」而不是「把 run json 整份收进来」

三个理由，都是量出来的：

1. **体积**（两个数都是称出来的，不是估的）。P61 手上那份 `runs_uniq.json`
   **2,115,770 字节 / 489 轮 = 4,326 字节一轮**，大头是每轮的正文和材料清单；
   照这个速度十批就是 20 MB 进 git，而且每批都是新的一份。
   蒸馏之后这份台账 **110,116 字节 / 489 轮 = 225 字节一轮**，**小 19 倍**；
   十批（按这一批的规模）约 1.1 MB。
2. **要答的问题不需要正文**。P59 ②③④、P61 #3 #4 那几条问的全是
   「判据哪几轮响了 / 连响几轮 / 这一跑怎么停的 / 停在第几轮」——
   全是 `fired_checks` + `status` + `stopped` + `round` 这几栏。
   正文一个字都用不上。**留用不上的东西是在给下一批添噪声，不是给它留证据。**
3. **正文里有用户自己写的字**。台账要进 git、要跨机器看，
   **少一样能少一样**：这份里**一个字的正文都没有**，只有判据名、状态、几个计数。

> 那正文真用得上的时候怎么办？**那一批自己去 scratch 里留**，并在台账里写清楚
> 「这一栏的原件只活到这一批为止」。这份 JSONL 管的是**能跨批累加的那几个分母**。

## 追加、不覆盖

按 `run` 去重合并：**同一份跑第二次导入不会重复**，新的跑追加在后面，
按 `(created, run)` 排序落盘。每条带 `src`（哪一批导的）——出身跟着数走。
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts import db_guard  # noqa: E402

LEDGER = BACKEND / "tests" / "fixtures" / "harness_runs.jsonl"
DEFAULT_DB = BACKEND / "data" / "notes.sqlite3"

# key 前缀 → 模式名（`app/harness/modes.py` 里那几个 `Mode`）。
MODE_OF_PREFIX = {"note": "NOTE", "section": "SECTION", "analysis": "ANALYSIS",
                  "chart": "CHART", "custom": "CUSTOM", "eda": "EDA",
                  "prompt": "PROMPT", "table": "TABLE"}


def safe_key(key: str) -> str:
    """跑的 key 只留 ASCII 那一份，非 ASCII 的尾巴换成 sha8。

    **这一条是量出来才加的**：真库 53 个 key 里有一个是 `note:stage3-量产未决项-74921`
    ——跑的 key 有一档是拿**笔记标题**拼的。五个字不算多，但这份台账顶上写着
    「一个字的正文都没有」，那句话要么是真的、要么就别写。
    换成哈希之后同一篇的多次跑还是并得起来（同一个标题 → 同一个 sha8），
    而闸 `test_p63::test_跑批台账里没有用户写的字` 每次都核一遍。
    """
    if key.isascii():
        return key
    import hashlib
    head, _, tail = key.partition(":")
    if head.isascii() and tail:
        return f"{head}:x{hashlib.sha256(tail.encode()).hexdigest()[:8]}"
    return "x" + hashlib.sha256(key.encode()).hexdigest()[:8]


def _fired(raw: str | None) -> list[str]:
    """`fired_checks` 有两种写法：JSON 数组（今天）和逗号分隔（老行）。两种都认。"""
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return [str(x) for x in v] if isinstance(v, list) else []
    except Exception:  # noqa: BLE001
        return [x for x in raw.split(",") if x]


def distill(db: Path, label: str) -> list[dict]:
    """一份库 → 一批「判据形状」的跑记录。**不带任何正文。**"""
    conn = db_guard.readonly(db)
    meta = {r["id"]: r for r in conn.execute(
        "SELECT id, key, status, rounds, stopped, created_at, tokens, calls FROM harness_runs")}
    rounds: dict[str, list] = collections.defaultdict(list)
    for r in conn.execute(
            "SELECT run_id, key, round, fired_checks, status, content_len, tool_calls, "
            "repeat_calls, abstained, cite_located, cite_marked, cite_matched, weakest, "
            "created_at FROM harness_rounds"):
        rounds[r["run_id"]].append(r)
    conn.close()

    out: list[dict] = []
    for run_id, rs in rounds.items():
        rs.sort(key=lambda x: x["round"])
        m = meta.get(run_id)
        key = m["key"] if m else (rs[0]["key"] or "")
        prefix = (rs[0]["key"] or ":").split(":")[0]
        out.append({
            "run": run_id,
            "src": label,
            "key": safe_key(key),
            "mode": MODE_OF_PREFIX.get(prefix, "?"),
            "created": (m["created_at"] if m else rs[0]["created_at"]) or "",
            "status": (m["status"] if m else "") or "",
            "stopped": (m["stopped"] if m else "") or "",
            "tokens": (m["tokens"] if m else None),
            "calls": (m["calls"] if m else None),
            "rounds": [{
                "r": x["round"],
                "status": x["status"] or "",
                "fired": _fired(x["fired_checks"]),
                "len": x["content_len"],
                "tools": x["tool_calls"],
                "repeat": x["repeat_calls"],
                "abstained": x["abstained"],
                "cite": [x["cite_located"], x["cite_marked"], x["cite_matched"]],
                "weakest": x["weakest"] or "",
            } for x in rs],
        })
    out.sort(key=lambda d: (d["created"], d["run"]))
    return out


def load() -> list[dict]:
    if not LEDGER.is_file():
        return []
    return [json.loads(ln) for ln in LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()]


def append(fresh: list[dict]) -> tuple[int, int]:
    """并进台账，按 `run` 去重。返回 (新增, 合计)。**已有的那一条不动**（先到先得）。"""
    have = {d["run"]: d for d in load()}
    added = 0
    for d in fresh:
        if d["run"] not in have:
            have[d["run"]] = d
            added += 1
    merged = sorted(have.values(), key=lambda d: (d["created"], d["run"]))
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text("".join(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n"
                              for d in merged), encoding="utf-8")
    return added, len(merged)


def stats(runs: list[dict]) -> str:
    """P61 #4 那几个分母，**一次算齐**。"""
    n_rounds = sum(len(d["rounds"]) for d in runs)
    fired_rounds = sum(1 for d in runs for x in d["rounds"] if x["fired"])
    by_mode = collections.Counter(d["mode"] for d in runs)
    by_src = collections.Counter(d["src"] for d in runs)
    stops = collections.Counter(d["stopped"] or d["status"] for d in runs)
    # 「判据连响到底然后跑满」：每一轮都响、而且 ≥3 轮（`check_stuck` 要 3 轮才够得着）
    all_fired = [d for d in runs
                 if len(d["rounds"]) >= 3 and all(x["fired"] for x in d["rounds"])]
    dates = sorted(d["created"] for d in runs if d["created"])
    return (f"ledger={LEDGER.name} runs={len(runs)} rounds={n_rounds} "
            f"fired_rounds={fired_rounds} span={dates[0][:16] if dates else '—'}~"
            f"{dates[-1][:16] if dates else '—'}\n"
            f"  by_mode={dict(sorted(by_mode.items()))}\n"
            f"  by_src={dict(sorted(by_src.items()))}\n"
            f"  stopped={dict(sorted(stops.items()))}\n"
            f"  判据连响到底且 ≥3 轮的跑: {len(all_fired)} / {len(runs)}"
            + (f"  {[d['run'][:12] for d in all_fired]}" if all_fired else ""))


def main(argv: list[str]) -> int:
    db = Path(argv[argv.index("--db") + 1]) if "--db" in argv else DEFAULT_DB
    label = argv[argv.index("--label") + 1] if "--label" in argv else "unlabeled"
    if "--append" in argv:
        if not db.is_file():
            print(f"没有这份库：{db}", file=sys.stderr)
            return 2
        fresh = distill(db, label)
        added, total = append(fresh)
        print(f"从 {db} 蒸馏出 {len(fresh)} 份跑（label={label}）；"
              f"新增 {added}，台账合计 {total} 份")
    print(stats(load()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
