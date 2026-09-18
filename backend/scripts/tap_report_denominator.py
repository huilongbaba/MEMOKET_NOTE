"""批 20 的分母：`magic-tap` / `journey/report` / 分段字数预算的阈值都在这里量。

    cd backend && .venv/bin/python scripts/tap_report_denominator.py

**只读**（`db_guard.readonly()` + `Watch()`），一次模型调用都不发，也**不碰
用户的 journey 数据**——`<userData>/journey/` 下的东西只读不写。

## 为什么要有这么一个脚本

铁律第 3 条：**阈值一律在真实产出上量，不拍脑袋**。批 19（骨架那五条）和
批 18（原子选类）都是先量再定，而量出来的数必须**能重跑**——第 4 轮驳回
1.3 那次的教训是「报告里写的数没人能复现」。

## 三份语料，各自的局限写在这里

| 语料 | 量什么 | 血缘 | 局限 |
|---|---|---|---|
| `origin=user` 的非空笔记（18 篇） | magic tap 那几条的**误伤** | `user` | 是整篇，不是一次续写 |
| 34 份单次续写 | magic tap 那几条的**真阳性** | `script` | **只能看形状，不能算比例** |
| 两份真实日报 + 逐字重建的输入 | 日报那五条的全部阈值 | `user` | n=2，六节 18 条 |
| 13 条有正文的分段笔记 | 分段字数下限 | `script` | 分段模式**自己一行数据都没有** |

第三份的重建是这个脚本最要紧的一段：日报的判据要按**模型看见的那一份**判
（`group_runs` 并过的行），不是原始 `segments.json`——两者差一条描述，
就会把「合并丢掉的」报成「模型编的」（见 `checks/journey.py` 里不做的那一条）。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import corpus_lineage as cl  # noqa: E402
import db_guard  # noqa: E402

from app.harness.checks import grounding_rules as gr  # noqa: E402
from app.harness.checks.journey import DUP_BULLET, check_report  # noqa: E402
from app.harness.checks.tap import check_tap  # noqa: E402
from app.journey.runs import group_runs, similar  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
JOURNEY = (pathlib.Path.home() / "Library" / "Application Support"
           / "memoket-note-desktop" / "journey")
_INCREMENT = re.compile(r"\*\*本轮续写增量：\*\*\n\n```\n(.*?)\n```", re.S)
_SEED = re.compile(r"## 种子\n\n```\n(.*?)\n```", re.S)
_FINAL = re.compile(r"## 最终（\d+ 字）\n\n```\n(.*?)\n```", re.S)


def continuations() -> list[tuple[str, str]]:
    """单次续写形态的真实模型产出。**`script` 血缘**：形态是真的，分布不是。"""
    out: list[tuple[str, str]] = []
    for f in sorted((HERE / "harness_quality_samples").glob("*.md")):
        for b in _INCREMENT.findall(f.read_text(encoding="utf-8", errors="ignore")):
            out.append((f"增量:{f.name}", b))
    for f in sorted((HERE / "writing_bench_results").glob("*.md")):
        t = f.read_text(encoding="utf-8", errors="ignore")
        seed, final = _SEED.search(t), _FINAL.search(t)
        if seed and final:
            # 「最终正文减去种子」才是模型写的那一部分
            body = final.group(1)
            head = seed.group(1)
            out.append((f"bench:{f.name}",
                        body[len(head):] if body.startswith(head[:40]) else body))
    return out


def tap_section() -> None:
    kept, _dropped = cl.load_notes(keep={cl.ORIGIN_USER})
    notes = [r for r in kept if (r["content"] or "").strip()]
    cont = continuations()
    print(f"\n=== 8.1 magic-tap ===\n真实笔记 {len(notes)} 篇 · 单次续写 {len(cont)} 份")

    def fire(items, fn):
        return [k for k, v in items if fn(v)]

    rows = [
        ("停在半句上", lambda t: check_tap(t).unfinished),
        ("脚手架标题", lambda t: check_tap(t).scaffold_titles),
        ("提示词示例泄漏", lambda t: check_tap(t).leaked_examples),
        ("[不做] 审计腔/机制泄漏", gr.audit_voice_lines),
        ("[不做] 占位符", gr.placeholder_lines),
    ]
    print(f"{'判据':<26}{'18 篇真实笔记':>16}{'34 份续写':>12}")
    for name, fn in rows:
        a = fire([(n["id"], n["content"]) for n in notes], fn)
        b = fire(cont, fn)
        print(f"{name:<26}{len(a):>16}{len(b):>12}   {b[:2]}")

    # 复述：真实笔记里拿「最后一段 vs 前面各段」当分母——一次续写接在正文
    # 后面，形状就是这个。
    n_restate = 0
    for n in notes:
        paras = [p for p in (n["content"] or "").split("\n\n") if len(p.strip()) >= 20]
        if len(paras) < 2:
            continue
        if check_tap(paras[-1], "\n\n".join(paras[:-1])).restated:
            n_restate += 1
    print(f"{'复述光标前的段落':<26}{n_restate:>16}{'—':>12}")


def _rebuild_lines(day: str, segments: int) -> list[str]:
    """**逐字重建**那一次真正进了提示词的几行（`routers/journey.report` 同一段）。"""
    segs = json.loads((JOURNEY / day / "segments.json").read_text(encoding="utf-8"))
    told = [s for s in segs
            if (s.get("desc") or "").strip() and not s.get("deleted")]
    told = sorted(told, key=lambda x: x.get("start") or "")[:segments]
    runs = group_runs(told)
    return [f"{r['start'][11:16]}–{r['end'][11:16]} {r['app']} {r['desc']}"
            + (f"（{len(r['segs'])} 段）" if len(r["segs"]) > 1 else "")
            for r in runs]


def report_section() -> None:
    print("\n=== 8.2 journey/report ===")
    if not JOURNEY.is_dir():
        print("这台机器上没有 journey 数据，跳过")
        return
    for d in sorted(JOURNEY.glob("2*")):
        meta_path = d / "report.json"
        if not meta_path.is_file():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        md = meta["report"]
        # 模型那一半 = 第一个规定小节起（前面是 `render_time_block` 渲染的）
        cut = md.find("## 推进了什么")
        text = md[cut:] if cut >= 0 else md
        lines = _rebuild_lines(d.name, meta["report_segments"])
        chk = check_report(text, lines)
        print(f"\n{d.name}：声明 {meta['report_segments']} 段 → 重建 {len(lines)} 行"
              f"，{chk.bullets} 条 bullet")
        print(f"  自己算的时长 {len(chk.recomputed_durations)}"
              f" · 多余小节 {len(chk.stray_sections)}"
              f" · 没有锚点的条目 {len(chk.vague_bullets)}"
              f" · 同节撞车 {len(chk.duplicate_bullets)}"
              f" · 查无出处的名字 {len(chk.unsourced_terms)} {chk.unsourced_terms[:4]}")
        # 门槛留了多少空当：同节两两最高相似度 vs DUP_BULLET
        best = 0.0
        for chunk in re.split(r"(?m)^(?=##\s)", text):
            items = re.findall(r"(?m)^\s*[-*]\s+(.+?)\s*$", chunk)
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    best = max(best, similar(items[i], items[j]))
        print(f"  同节 bullet 两两最高相似度 {best:.3f}（门槛 {DUP_BULLET}）")
        # 不做的那一条：数字查无出处
        blob = "\n".join(lines)
        stray = sorted({n for n in re.findall(r"\d+(?:\.\d+)?", text)
                        if len(n) >= 2 and n not in blob})
        print(f"  [不做] 数字查无出处 {len(stray)} {stray[:6]}")


def budget_section() -> None:
    print("\n=== 7.3 分段的字数下限 ===")
    conn = db_guard.readonly()
    try:
        lineage = cl.load_lineage(conn)
        rows = [dict(r) for r in conn.execute(
            "SELECT s.title, s.status, n.id AS nid, n.user_id, n.title AS ntitle,"
            "       n.content FROM writing_sections s"
            "  LEFT JOIN notes n ON n.id = s.note_id")]
        rounds = conn.execute(
            "SELECT count(*) FROM harness_rounds WHERE key NOT LIKE '%:%'").fetchone()[0]
    finally:
        conn.close()
    # `没开写` = 这一条分段还没有对应的笔记（`status=pending`），正文无从谈起。
    lens: dict[str, list[int]] = {"user": [], "script": [], "fixture": [], "没开写": []}
    for r in rows:
        if not r["nid"]:
            lens["没开写"].append(0)
            continue
        origin = cl.classify(r["user_id"] or "", r["ntitle"] or "",
                             lineage.get(r["nid"]))
        kind = getattr(origin, "kind", origin)
        lens[kind].append(len(re.sub(r"\s", "", r["content"] or "")))
    print(f"分段模式在 harness_rounds 里的轮次：{rounds}（`note:` 前缀之外的键）")
    for kind, vals in lens.items():
        nonzero = sorted(v for v in vals if v)
        print(f"  {kind:<8} 共 {len(vals):>3} 条 · 有正文 {len(nonzero):>3} 条"
              f" · {nonzero if nonzero else '—'}")


if __name__ == "__main__":
    # 这个脚本不该写任何用户笔记——写了就抛（批 14 的事故）。
    with db_guard.Watch():
        tap_section()
        report_section()
        budget_section()
