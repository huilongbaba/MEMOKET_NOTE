"""把两条 harness 的**完整产出**存成 markdown，供人工评判质量。

跟其他两个脚本的分工：
  editing_quality_bench.py  已知缺陷 → 自动判定修没修掉（可跑量，出通过率）
  writing_quality_bench.py  干净种子 → 8 项自动检查（可跑量，出通过率）
  这个脚本                    **全文留档，不做任何判定**——自动检查只能抓已知
                             形态的缺陷，真正的写作质量只有人读得出来

覆盖两条 harness：
  文章内续写   note_harness   —— 一篇笔记内部的自动修订 + 自动续写
  文件夹内无限续写 writing_plan —— 拆分段、每段各写一篇、写完再判断还缺不缺

留档内容尽量完整，方便判断「产出好不好」和「为什么会这样」：
起始正文、自动生成的骨架、每一轮的每一条修订（op/锚点/改成什么/理由/依据的
事实）、agent 查了哪些工具查到什么、策略控制器每轮怎么调的参数、每轮六个
维度的分数和诊断、续写增量、最终全文。

跑在 terrence 上是刻意的：知识库是真的，`factual_grounding` 才有意义，
产出才值得评判。**创建的笔记和文件夹在 finally 里全部删除**，只删本脚本
自己建的那些 id，绝不碰任何已有笔记。
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import httpx

BASE_URL = "http://localhost:8000"
USER = "terrence"
OUT_DIR = Path(__file__).resolve().parents[2] / "samples"
H = {"X-User-Id": USER, "Content-Type": "application/json"}


# ---------------------------------------------------------------- 种子

NOTE_SEEDS = [
    {"id": "量产未决项", "rounds": 3, "seed": (
        "## 硬件量产前的未决项\n\n"
        "样机阶段暴露的问题还没收敛完，得先把哪些是必须在量产前解决的列清楚。\n")},
    {"id": "定价覆盖成本", "rounds": 3, "seed": (
        "## 定价要覆盖哪些成本\n\n"
        "报价不能只看物料，配件、渠道报备和汇率波动都得算进去，"
        "不然看着有毛利实际在亏。\n")},
    {"id": "空白起笔", "rounds": 3, "seed": (
        "## 这一轮产品设计的取舍\n\n")},
]

PLAN_GOALS = [
    {"id": "硬件量产复盘", "goal": "写一份硬件从样机到量产的复盘，说清楚哪些问题是设计带来的、"
                                "哪些是流程带来的，以及下一款该怎么避免"},
    {"id": "定价方案", "goal": "整理一套定价方案，覆盖成本结构、渠道报备、以及不同客户类型的报价逻辑"},
]


# ---------------------------------------------------------------- SSE

def parse_sse(text: str) -> list[tuple[str, dict]]:
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


def render_common(out: list[str], ev: str, p: dict) -> bool:
    """两条 harness 共用的事件渲染。返回是否处理了这个事件。"""
    if ev == "revision":
        out.append(f"- **修订（{p.get('op')}）**")
        out.append(f"  - 锚点：`{(p.get('anchor') or '')[:100]}`")
        out.append(f"  - 改成：{(p.get('text') or '')[:400]}")
        out.append(f"  - 理由：{p.get('reason') or ''}")
        if p.get("sources"):
            out.append(f"  - 依据的知识库事实：{'；'.join(s[:120] for s in p['sources'])}")
        out.append("")
        return True
    if ev == "tool-calls":
        out.append(f"**agent 自主检索**（{p.get('iters')} 轮循环，"
                   f"截断={p.get('truncated')}）：")
        for c in p.get("calls", []):
            out.append(f"- `{c['tool']}` {json.dumps(c['args'], ensure_ascii=False)}")
            body = (c.get("result") or "").strip().replace("\n", "\n      ")
            out.append(f"      {body[:500]}")
        out.append("")
        return True
    if ev == "policy":
        out.append(f"**策略调整**（第 {p.get('round')} 轮后）："
                   f"工具预算 {p['policy']['tool_iters']}、"
                   f"续写温度 {p['policy']['continue_temperature']:.2f}、"
                   f"修订额度 {p['policy']['max_revisions']}"
                   + ("、要求溯源核对" if p["policy"].get("require_verification") else ""))
        for r in p.get("reasons", []):
            out.append(f"  - {r}")
        if p["policy"].get("steer"):
            out.append(f"  - 注入下一轮的方向：{p['policy']['steer'][:300]}")
        out.append("")
        return True
    if ev == "evaluate":
        out.append("**本轮打分：**")
        out.append("")
        for name, sc in p.get("scores", {}).items():
            out.append(f"  - {name}: {sc['level']} — {sc.get('note','')}")
        out.append("")
        out.append(f"  状态：{p.get('status')}"
                   + (f"，最弱：{p.get('weakest')}" if p.get("weakest") else ""))
        out.append("")
        return True
    if ev == "error":
        out.append(f"> ⚠️ error: {p.get('detail')}")
        out.append("")
        return True
    return False


# ---------------------------------------------------------------- 文章内续写

def sample_note(client: httpx.Client, spec: dict) -> Path:
    note = httpx.post(f"{BASE_URL}/api/notes", headers=H,
                      json={"title": f"sample-{spec['id']}", "content": spec["seed"],
                            "folder_id": None}, timeout=30).json()
    t0 = time.monotonic()
    try:
        buf = ""
        with client.stream("POST", f"{BASE_URL}/api/note-harness/run", headers=H,
                           json={"note_id": note["id"], "content": spec["seed"],
                                 "max_rounds": spec.get("rounds", 3)},
                           timeout=3600.0) as r:
            for chunk in r.iter_text():
                buf += chunk
        events = parse_sse(buf)
        final = httpx.get(f"{BASE_URL}/api/notes/{note['id']}", headers=H, timeout=30).json()
        final_text = final.get("content", "")
    finally:
        httpx.delete(f"{BASE_URL}/api/notes/{note['id']}", headers=H, timeout=30)

    out = [f"# 文章内续写：{spec['id']}", "",
           f"采集时间：{datetime.now().isoformat(timespec='seconds')}　·　"
           f"用户：{USER}（真实知识库）　·　耗时 {time.monotonic() - t0:.0f}s", "",
           "> 读的时候可以重点看：续写有没有真正推进（而不是把已有内容换个说法重讲）、",
           "> 引用的具体人名日期数字是不是真的来自知识库、小节之间有没有主题撞车、",
           "> 结构是不是一以贯之。", "",
           "## 起始正文", "", "```markdown", spec["seed"].rstrip(), "```", ""]

    round_no = 0
    delta = ""
    for ev, p in events:
        if ev == "skeleton":
            out += ["## 自动生成的骨架", "",
                    f"**核心张力**：{p.get('spine') or '（空）'}", "", "**结构节拍：**", ""]
            out += [f"- {b}" for b in p.get("beats", [])] + [""]
            continue
        if ev == "round-start":
            round_no = p.get("round", round_no + 1)
            skipped = p.get("skipped_continue")
            out += [f"## 第 {round_no} 轮" + ("（跳过续写，只做清理）" if skipped else ""), "",
                    f"- 本轮已应用修订：{p.get('revisions_applied', 0)} 处",
                    f"- 喂给续写的知识库事实：{p.get('facts', 0)} 条", ""]
            delta = ""
            continue
        if ev == "delta":
            delta += p.get("text", "")
            continue
        if ev == "round-end":
            if delta.strip():
                out += ["**本轮续写增量：**", "", "```markdown", delta.strip(), "```", ""]
            delta = ""
            continue
        if ev == "done":
            out += [f"## 结束：{p.get('reason')}"
                    + (f" — {p.get('blocked_reason')}" if p.get("blocked_reason") else ""), ""]
            continue
        render_common(out, ev, p)

    out += ["## 最终正文", "", "```markdown", final_text.rstrip(), "```", ""]
    path = OUT_DIR / f"note-{spec['id']}.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"  ✓ 文章内续写 {spec['id']} → {path.name}（{len(final_text)} 字）", flush=True)
    return path


# ---------------------------------------------------------------- 文件夹内无限续写

def sample_plan(client: httpx.Client, spec: dict) -> Path:
    # 跑之前记下已有的全部笔记 id。清理时取差集——**不要依赖计划状态去反查
    # 分段笔记**：`get_active_plan` 只认 status='active'，计划一跑完就查不到，
    # 于是一篇都删不掉；而 `delete_folder` 明确不级联（文件夹只是分类，删了
    # 笔记退回「未分类」）。这两条叠加，真实后果是往用户账号里堆了几十篇
    # 残留笔记，跨越多次会话才被发现。
    before = {n["id"] for n in httpx.get(f"{BASE_URL}/api/notes", headers=H, timeout=30).json()}
    folder = httpx.post(f"{BASE_URL}/api/folders", headers=H,
                        json={"name": f"sample-{spec['id']}"}, timeout=30).json()
    created_notes: list[str] = []
    t0 = time.monotonic()
    try:
        started = httpx.post(f"{BASE_URL}/api/writing-plan/start", headers=H,
                             json={"folder_id": folder["id"], "goal": spec["goal"]},
                             timeout=300).json()
        buf = ""
        with client.stream("POST", f"{BASE_URL}/api/writing-plan/run", headers=H,
                           json={"folder_id": folder["id"]}, timeout=7200.0) as r:
            for chunk in r.iter_text():
                buf += chunk
        events = parse_sse(buf)
        # 差集 = 这次跑出来的所有笔记（分段笔记 + writing_plan 自己建的
        # 「📋 写作追踪」）。比反查计划可靠：不依赖计划状态，也不会漏掉
        # 追踪笔记那种不在 sections 列表里的产物。
        after = httpx.get(f"{BASE_URL}/api/notes", headers=H, timeout=30).json()
        notes = [n for n in after if n["id"] not in before]
        created_notes = [n["id"] for n in notes]
    finally:
        for nid in created_notes:
            httpx.delete(f"{BASE_URL}/api/notes/{nid}", headers=H, timeout=30)
        httpx.post(f"{BASE_URL}/api/writing-plan/{folder['id']}/abandon", headers=H, timeout=30)
        httpx.delete(f"{BASE_URL}/api/folders/{folder['id']}", headers=H, timeout=30)

    out = [f"# 文件夹内无限续写：{spec['id']}", "",
           f"采集时间：{datetime.now().isoformat(timespec='seconds')}　·　"
           f"用户：{USER}（真实知识库）　·　耗时 {time.monotonic() - t0:.0f}s", "",
           "> 读的时候可以重点看：分段拆得合不合理、**各分段之间有没有主题撞车**",
           "> （这是文件夹级最容易出问题的地方）、后开的分段是不是真的补了缺口",
           "> 而不是把前面的换个说法重写、每篇自己读起来完不完整。", "",
           "## 写作目标", "", f"> {spec['goal']}", "",
           "## 最初拆出的分段", ""]
    out += [f"{i + 1}. {s['title']}" for i, s in enumerate(started.get("sections", []))] + [""]

    sec_names = {s["id"]: s["title"] for s in started.get("sections", [])}
    cur, delta = "", ""
    for ev, p in events:
        if ev == "plan-extended":
            out += ["### ＋ 判断还缺分段，新开：", ""]
            for s in p.get("sections", []):
                sec_names[s["id"]] = s["title"]
                out.append(f"- {s['title']}")
            out.append("")
            continue
        if ev == "section-start":
            sid = p.get("section_id")
            title = sec_names.get(sid, sid)
            if sid != cur:
                out += [f"## 分段：{title}", ""]
                cur = sid
            out += ["### 一轮" + ("（跳过续写，只做清理）" if p.get("skipped_continue") else ""), ""]
            delta = ""
            continue
        if ev == "delta":
            delta += p.get("text", "")
            continue
        if ev == "round-end":
            if delta.strip():
                out += ["**本轮续写增量：**", "", "```markdown", delta.strip(), "```", ""]
            delta = ""
            continue
        if ev == "section-done":
            out += [f"**分段收尾**{'（撞轮数上限强制收尾）' if p.get('forced') else ''}"
                    + ("（判定 blocked）" if p.get("blocked") else ""), "",
                    f"小结：{p.get('summary', '')}", ""]
            continue
        if ev == "plan-done":
            out += ["## 计划完成：判断已无遗漏分段", ""]
            continue
        render_common(out, ev, p)

    out += ["## 各分段最终全文", ""]
    for n in notes:
        out += [f"### {n['title']}（{len(n.get('content') or '')} 字）", "",
                "```markdown", (n.get("content") or "").rstrip(), "```", ""]

    path = OUT_DIR / f"plan-{spec['id']}.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"  ✓ 文件夹内无限续写 {spec['id']} → {path.name}"
          f"（{len(notes)} 个分段）", flush=True)
    return path


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["note", "plan"], help="只跑其中一条 harness")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_index()          # 先写一版，免得采集期间目录是空的
    client = httpx.Client()
    made: list[Path] = []

    if args.only != "plan":
        print("=== 文章内续写（note_harness）===", flush=True)
        for spec in NOTE_SEEDS:
            try:
                made.append(sample_note(client, spec))
                write_index()
            except Exception as exc:
                print(f"  ✗ {spec['id']}: {type(exc).__name__}: {exc}", flush=True)

    if args.only != "note":
        print("=== 文件夹内无限续写（writing_plan）===", flush=True)
        for spec in PLAN_GOALS:
            try:
                made.append(sample_plan(client, spec))
                write_index()
            except Exception as exc:
                print(f"  ✗ {spec['id']}: {type(exc).__name__}: {exc}", flush=True)

    write_index()
    print(f"\n共 {len(made)} 份，索引：{OUT_DIR / 'README.md'}", flush=True)


def write_index() -> None:
    """索引在开跑前先写一次、跑完再写一次。

    第一版只在最后写，结果是整个采样期间目录完全是空的（每份样本要整轮
    跑完才落盘，一份要四五分钟），看的人以为没在跑。
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index = OUT_DIR / "README.md"
    notes = sorted(OUT_DIR.glob("note-*.md"))
    plans = sorted(OUT_DIR.glob("plan-*.md"))
    pending = (len(NOTE_SEEDS) - len(notes)) + (len(PLAN_GOALS) - len(plans))
    lines = ["# Harness 产出样本", "",
             "两条 harness 的完整产出留档，**不做任何自动判定**——自动检查只能抓已知",
             "形态的缺陷，真正的写作质量只有人读得出来。", "",
             f"最近一次采集：{datetime.now().isoformat(timespec='seconds')}　·　"
             f"用户 {USER}（真实知识库）", ""]
    if pending > 0:
        lines += [f"> ⏳ **正在采集**，还有 {pending} 份没跑完。每份样本要整轮跑完才落盘，",
                  "> 一份文章内续写约 4–5 分钟，一份文件夹级无限续写更久（要拆分段、",
                  "> 每段各跑几轮）。已经落盘的在下面，跑完这份索引会自动重写。", ""]
    lines += [
             "生成脚本：`backend/scripts/full_output_sample.py`。",
             "创建的笔记和文件夹在脚本结束时全部删除，只删脚本自己建的，不碰已有笔记。", "",
             "## 文章内续写（一篇笔记内部）", ""]
    for p in sorted(OUT_DIR.glob("note-*.md")):
        lines.append(f"- [{p.stem[5:]}]({p.name})")
    lines += ["", "## 文件夹内无限续写（拆分段、每段一篇）", ""]
    for p in sorted(OUT_DIR.glob("plan-*.md")):
        lines.append(f"- [{p.stem[5:]}]({p.name})")
    lines += ["", "## 每份留档里有什么", "",
              "起始正文 → 自动生成的骨架 → 每一轮的每一条修订（改了哪里、改成什么、",
              "为什么改、依据知识库哪条事实）→ agent 自主查了哪些工具、查到什么 →",
              "策略控制器每轮怎么调参数 → 六个维度的打分和诊断 → 续写增量 → 最终全文。", ""]
    index.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
