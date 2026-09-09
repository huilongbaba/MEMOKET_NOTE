"""连续跑 N 轮全量回归，看的是**分布**，不是某一次的好坏。

单次结果说明不了问题——这一晚上反复吃过 n=1 的亏（一次好就以为修好了，
换个种子又崩）。这里把 suite 的四组（续写/打磨/大纲/tap）每组每个种子跑
N 轮，统计各维度打分分布、终止原因分布、以及五类确定性缺陷的出现率：

    破字   修订切错位置留下的残骸（标点连缀），正文可见损坏
    泄漏   把工作机制写进正文（"知识库""可核对的事实"）
    审计   关于证据充分性的元评论（"不能证明""待核对"）
    顾问腔 写"这件事应该怎么安排"而不是这件事本身；旧代码基线 4~11%
    占位符 写了个坑没填（"待指定""待倒排"）

4 路并行：backend 是 async、模型在远端，串行跑 20 轮要三小时，并行 50 分钟。
每个任务用独立笔记标题，跑完即删，互不干扰。

用法：
    python scripts/soak.py 20        # 20 轮，4 路并行
    python scripts/soak.py 20 6      # 20 轮，6 路并行
    python scripts/soak.py 1 2 plan  # 只跑文件夹级那一组
"""

from __future__ import annotations

import difflib
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from suite import (AUDIT, BASE, H, LEAK, OUT, OUTLINES, POLISH_SEEDS,  # noqa: E402
                   PLACEHOLDER, TAP_SEEDS, WRITE_SEEDS, _HEADING,
                   run_note, sse)
from app.editor import outline# noqa: E402
from app.harness.revision import _BROKEN  # noqa: E402  修订的定位与应用搬到这里了

# 收束段：以"因此/所以/综上…"起头的段落。假设是每轮写完都想收个尾，三轮就有
# 三个收束，而它们必然重述前文——这是 non_repetition 的一个待验证的候选根因。
# **先测相关性再决定要不要动它**（顾问腔那次拍阈值白追了一批）。
_CLOSER = re.compile(r"^\s*(?:因此|所以|综上|总的来说|总而言之|归根结底|这样一来|由此|"
                     r"总之|最终|概括起来|一句话)")


def max_dup(text: str) -> float:
    """最终正文里段落两两的最高相似度。**这是校准打分判据时的证伪指标。**

    放宽 non_repetition 的判据（不再把"结尾重申核心结论"当缺陷）有"为了刷分
    而降标准"的风险。兜底是这条：分数升了而这个数不涨，说明放宽的是判据里
    罚错的那部分；这个数跟着涨，就是在放水。

    判 1 分那批产出实测是 0.29——一处字面重复都没有。
    """
    # 代码块/表格排除在外：两张 mermaid 图共享语法骨架就能到 0.55，而内容
    # 完全不同。前三批这个指标一直报"3 篇 >0.5"，抓原文一看全是这种假阳性
    # ——我还据此改了真实机制的阈值。测量指标本身也要防假阳性。
    ps = [x.strip() for x in re.split(r"\n\s*\n", text or "")
          if len(x.strip()) >= 40 and not outline._is_block(x.strip())]
    return max((difflib.SequenceMatcher(None, a, b).ratio()
                for i, a in enumerate(ps) for b in ps[i + 1:]), default=0.0)


def closers(text: str) -> int:
    return sum(1 for p in re.split(r"\n\s*\n", text or "") if _CLOSER.match(p.strip()))


def one(kind: str, name: str, seed: str, tag: str) -> dict:
    """跑一个种子，返回这一次的全部观测。异常也返回，不能让一次失败带走整轮。"""
    try:
        if kind == "tap":
            buf = ""
            with httpx.Client() as c:
                with c.stream("POST", f"{BASE}/api/magic-tap", headers=H,
                              json={"content": seed, "spine": "", "beats": [],
                                    "max_tokens": 300}, timeout=600) as r:
                    for chunk in r.iter_text():
                        buf += chunk
            import json
            g = {}
            for frame in buf.split("\n\n"):
                if "event: grounding" in frame:
                    try:
                        g = json.loads(frame.split("data:")[-1].strip())
                    except json.JSONDecodeError:
                        pass
            return {"kind": kind, "name": name, "facts": g.get("facts", 0),
                    "used": g.get("used", 0), "hint": bool(g.get("hint"))}

        r = run_note(f"{name}-{tag}", seed, 3, mode="polish" if kind == "polish" else "write")
        r["kind"], r["name"] = kind, name
        r["broken"] = len(_BROKEN.findall(r["final"]))
        r["closers"] = closers(r["final"])
        r["dup_max"] = round(max_dup(r["final"]), 3)
        if kind == "outline":
            orig = [(len(m.group(1)), m.group(2)) for m in _HEADING.finditer(seed)]
            now = [(len(m.group(1)), m.group(2)) for m in _HEADING.finditer(r["final"])]
            r["struct_exact"] = now == orig
            r["text_ok"] = [t for _l, t in now if any(t == o[1] for o in orig)] == [o[1] for o in orig]
        return r
    except Exception as exc:                       # noqa: BLE001
        return {"kind": kind, "name": name, "error": f"{type(exc).__name__}: {exc}"}


# 文件夹级无限续写。单篇 harness 已经跑了上千次，而 writing_plan 一次没测过——
# 它跟单篇共用 EDIT_SYSTEM、apply_revision 和那四道丢弃防线，而今晚"两条路径
# 共用一个函数、只修了一边"的缺陷已经出现过三次。没有 bench 等于这条路径在裸奔。
# 一次计划要写好几篇笔记、几分钟起步，所以每批只跑一遍，不跟着 rounds 翻。
PLAN_GOALS = [
    "把这一年的硬件量产过程写成一份复盘",
    "整理一份众筹前后的完整时间线",
]


def run_plan(goal: str) -> dict:
    """跑一次文件夹级计划，返回观测；跑完把新建的笔记和文件夹都清掉。"""
    f = httpx.post(f"{BASE}/api/folders", headers=H,
                   json={"name": f"soak-{goal[:8]}"}, timeout=30).json()
    # get_active_plan 在 plan-done 之后就查不到了，而 delete_folder 不级联——
    # 所以用前后快照的差集找出这次真正新建的笔记（早期版本按 folder_id 查，
    # 而 /api/notes 会**静默忽略** folder_id，差点把用户所有笔记删了）。
    before = {n["id"] for n in httpx.get(f"{BASE}/api/notes", headers=H, timeout=30).json()}
    try:
        r = httpx.post(f"{BASE}/api/writing-plan/start", headers=H,
                       json={"folder_id": f["id"], "goal": goal}, timeout=300)
        if r.status_code != 200:
            # 不检查状态码的代价：start 失败（比如模型没生成出有效的分段列表，
            # 后端返回 502）之后 run 找不到活动计划，立刻 done——报出来是
            # "0 分段 0 笔记"，看着像 harness 坏了，其实是启动那一步就没成。
            # 沉默看起来像成功，这里必须说出真正的原因。
            raise RuntimeError(f"start 返回 {r.status_code}: {r.text[:120]}")
        out = sse(f"{BASE}/api/writing-plan/run", {"folder_id": f["id"]})
        mine = [n for n in httpx.get(f"{BASE}/api/notes", headers=H, timeout=30).json()
                if n["id"] not in before]
        text = "\n\n".join(
            httpx.get(f"{BASE}/api/notes/{n['id']}", headers=H, timeout=30).json()["content"]
            for n in mine)
    finally:
        for n in [x for x in httpx.get(f"{BASE}/api/notes", headers=H, timeout=30).json()
                  if x["id"] not in before]:
            httpx.delete(f"{BASE}/api/notes/{n['id']}", headers=H, timeout=30)
        httpx.delete(f"{BASE}/api/folders/{f['id']}", headers=H, timeout=30)
    return {
        "goal": goal, "notes": len(mine), "text": text,
        "sections": sum(1 for e, _p in out if e == "section-done"),
        "stop": next((p.get("reason", "") for e, p in out if e in ("done", "plan-done")), "done"),
        "dropped": sum(1 for e, _p in out if e == "dropped"),
        "errors": [p.get("detail", "")[:80] for e, p in out if e == "error"],
    }


def main() -> None:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    par = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    # 第三个参数只跑某一组（write/polish/outline/tap/plan）。文件夹级一次要
    # 好几分钟，单独调它的时候不该陪跑 240 次单篇。
    only = sys.argv[3] if len(sys.argv) > 3 else ""

    jobs = []
    for i in range(rounds if only != "plan" else 0):
        for kind, seeds in (("write", WRITE_SEEDS), ("polish", POLISH_SEEDS),
                            ("outline", OUTLINES)):
            if only in ("", kind):
                jobs += [(kind, n, sd, f"r{i}") for n, sd in seeds]
        if only in ("", "tap"):
            jobs += [("tap", f"tap{j+1}", sd, f"r{i}") for j, sd in enumerate(TAP_SEEDS)]

    print(f"{rounds} 轮 × {len(jobs)//rounds} 个种子 = {len(jobs)} 次，{par} 路并行", flush=True)
    t0 = time.monotonic()
    done_n = 0
    res: list[dict] = []
    with ThreadPoolExecutor(max_workers=par) as ex:
        for r in ex.map(lambda a: one(*a), jobs):
            res.append(r)
            done_n += 1
            if r.get("error"):
                print(f"  [{done_n}/{len(jobs)}] ✗ {r['name']}: {r['error']}", flush=True)
            elif done_n % 6 == 0 or done_n == len(jobs):
                el = time.monotonic() - t0
                print(f"  [{done_n}/{len(jobs)}] {el/60:.0f}分，剩约 "
                      f"{el/done_n*(len(jobs)-done_n)/60:.0f}分", flush=True)

    # ---------------- 聚合 ----------------
    md = [f"# 连续 {rounds} 轮回归\n", f"跑于 {datetime.now():%Y-%m-%d %H:%M} · "
          f"共 {len(jobs)} 次 · 耗时 {(time.monotonic()-t0)/60:.0f} 分\n"]
    bad: list[str] = []
    errs = [r for r in res if r.get("error")]
    if errs:
        md += [f"\n**跑挂了 {len(errs)} 次**\n"] + [f"- {r['name']}: {r['error']}" for r in errs[:10]]
        bad.append(f"{len(errs)} 次异常")

    by = defaultdict(list)
    for r in res:
        if not r.get("error"):
            by[(r["kind"], r["name"])].append(r)

    def pct(xs) -> str:
        return f"{sum(xs)/max(1,len(xs))*100:.0f}%"

    for kind, header, cols in [
        ("write", "智能续写", None), ("polish", "打磨（只修不写）", None),
        ("outline", "大纲结构保护", None), ("tap", "magic tap", None),
    ]:
        rows = {k: v for k, v in by.items() if k[0] == kind}
        if not rows:
            continue
        md.append(f"\n## {header}\n")
        if kind == "tap":
            md.append("| 种子 | n | 平均检索 | 平均用上 | 一条没用上 |\n|---|---|---|---|---|")
            for (_k, name), v in sorted(rows.items()):
                nz = [x for x in v if x["facts"]]
                miss = pct([x["used"] == 0 for x in nz])
                md.append(f"| {name} | {len(v)} | {sum(x['facts'] for x in v)/len(v):.1f} | "
                          f"{sum(x['used'] for x in v)/len(v):.1f} | {miss} |")
                if nz and sum(x["used"] == 0 for x in nz) / len(nz) > 0.34:
                    bad.append(f"tap/{name} 有 {miss} 的次数检索到了却一条没用上")
            continue

        dims = sorted({d for v in rows.values() for x in v for d in x.get("scores", {})})
        extra = (["标题+顺序", "含层级"] if kind == "outline" else
                 ["误续写"] if kind == "polish" else [])
        md.append("| 种子 | n | 轮均 | 字均 | " + " | ".join(dims) +
                  " | 破字 | 顾问腔 | 占位 | 泄漏/审计 | " + " | ".join(extra) + " |")
        md.append("|" + "---|" * (10 + len(dims) + len(extra)))
        for (_k, name), v in sorted(rows.items()):
            cells = []
            for d in dims:
                lv = [x["scores"].get(d, 2) for x in v]
                cells.append(f"{sum(lv)/len(lv):.1f}")
                if sum(lv) / len(lv) < 1.7:
                    bad.append(f"{kind}/{name} 的 {d} 均分 {sum(lv)/len(lv):.1f}")
            brk = sum(x["broken"] for x in v)
            # 顾问腔是个比例，短文本上分母太小会剧烈跳动（打磨的种子只有
            # 一两百字，两句"应该"就 35%）。太短的直接不报，免得追一个假信号。
            long_enough = [x for x in v if len(x["final"]) >= 600]
            adv = (sum(x["advice"] for x in long_enough) / len(long_enough)
                   if long_enough else -1)
            hol = sum(x["hollow"] for x in v)
            lk = sum(1 for x in v if x["leak"] or x["audit"])
            ex = ([pct([x["text_ok"] for x in v]), pct([x["struct_exact"] for x in v])]
                  if kind == "outline" else
                  [pct([x["deltas"] > 0 for x in v])] if kind == "polish" else [])
            md.append(f"| {name} | {len(v)} | {sum(x['rounds'] for x in v)/len(v):.1f} | "
                      f"{sum(len(x['final']) for x in v)//len(v)} | " + " | ".join(cells) +
                      f" | {brk} | {'-' if adv < 0 else f'{adv:.0f}%'} | {hol} | {lk} | " + " | ".join(ex) + " |")
            if brk:
                bad.append(f"{kind}/{name} 有 {brk} 处破字")
            # 顾问腔**不报警**，只观察。20 轮 240 次量出来它跟内在质量几乎无关
            # （coherence r=-0.20、non_repetition r=-0.04），说明它只是文体偏好：
            # 对"这件事应该怎么安排"本来就是内容的规划类种子，写"应该"是对的。
            # 那个 25% 阈值是我按旧产出基线拍的，数据不支持，撤掉。
            if hol:
                bad.append(f"{kind}/{name} 有 {hol} 个占位符")
            if lk:
                bad.append(f"{kind}/{name} 有 {lk} 次泄漏或审计腔")
            if kind == "polish" and any(x["deltas"] > 0 for x in v):
                bad.append(f"打磨/{name} 误续写 {pct([x['deltas']>0 for x in v])}")
            if kind == "outline" and not all(x["text_ok"] for x in v):
                bad.append(f"大纲/{name} 有 {pct([not x['text_ok'] for x in v])} 改动了用户的标题")

        stops = Counter(x["done"] for v in rows.values() for x in v)
        md.append(f"\n终止原因：{dict(stops)}")

    # **新指标先测相关性，再决定要不要动手改代码。**
    #
    # 顾问腔那次是反面教材：我按旧产出的基线拍了个"超过 25% 算缺陷"，追了一整批
    # 60 分钟的回归，最后 240 次实测它跟 coherence 的相关系数只有 −0.20、跟
    # non_repetition −0.04——纯属文体偏好。对"这件事应该怎么安排"本来就是内容的
    # 规划类种子，写"应该"是对的。
    #
    # 真信号应该表现为：指标越高、对应维度分越低（负相关）。
    scored = [x for x in res if not x.get("error") and x.get("scores")
              and len(x.get("final", "")) >= 600]
    if len(scored) >= 20:
        md.append("\n## 确定性指标跟质量到底有没有关系\n")
        md.append("| 指标 × 维度 | 相关系数 | 读法 |\n|---|---|---|")
        for metric, dim in (("closers", "non_repetition"), ("dup_max", "non_repetition"),
                            ("meta_scrubbed", "coherence"), ("meta_scrubbed", "non_repetition")):
            xs = [x[metric] for x in scored]
            ys = [x["scores"].get(dim, 2) for x in scored]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
            vx = sum((a - mx) ** 2 for a in xs) ** 0.5
            vy = sum((b - my) ** 2 for b in ys) ** 0.5
            r = cov / (vx * vy) if vx and vy else 0.0
            how = ("负相关，这个指标高的确实写得差，是真信号，值得动手修" if r < -0.25 else
                   "几乎无关，只是文体偏好，不该当缺陷报" if abs(r) < 0.25 else
                   "正相关，方向跟预期相反，这个指标本身有问题")
            label = {"advice": "顾问腔", "closers": "收束段数",
                     "dup_max": "段落最高相似度", "meta_scrubbed": "删掉的元话语句数"}[metric]
            md.append(f"| {label} × {dim} | {r:+.2f} | {how} |")

    import json as _json
    (OUT / f"soak-{rounds}轮-raw.json").write_text(
        _json.dumps([{k: v for k, v in x.items() if k != "final"} for x in res],
                    ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------- 文件夹级 ----------------
    if only in ("", "plan"):
        print("\n═══ 文件夹级无限续写 ═══", flush=True)
        md.append("\n## 文件夹级无限续写（writing_plan）\n")
        md.append("| 目标 | 分段 | 笔记 | 总字 | 破字 | 收束段 | 占位 | 丢弃 | 泄漏/审计 | 终止 |")
        md.append("|---|---|---|---|---|---|---|---|---|---|")
        for goal in PLAN_GOALS:
            try:
                r = run_plan(goal)
            except Exception as exc:                    # noqa: BLE001
                print(f"  ✗ {goal[:14]}: {type(exc).__name__}: {exc}", flush=True)
                bad.append(f"计划/{goal[:12]} 跑挂了：{type(exc).__name__}: {exc}")
                continue
            t = r["text"]
            lk = [w for w in LEAK + AUDIT if w in t]
            brk = len(_BROKEN.findall(t))
            hol = len(PLACEHOLDER.findall(t))
            row = (f"| {goal[:14]} | {r['sections']} | {r['notes']} | {len(t)} | {brk} | "
                   f"{closers(t)} | {hol} | {r['dropped']} | {lk or '无'} | {r['stop']} |")
            print("  " + row, flush=True)
            md.append(row)
            if brk:
                bad.append(f"计划/{goal[:12]} 正文有 {brk} 处破字")
            if lk:
                bad.append(f"计划/{goal[:12]} 有泄漏或审计腔：{lk}")
            if hol:
                bad.append(f"计划/{goal[:12]} 有 {hol} 个占位符")
            if not r["notes"]:
                bad.append(f"计划/{goal[:12]} 一篇笔记都没产出")
            for e in r["errors"][:3]:
                bad.append(f"计划/{goal[:12]} 报错：{e}")

    md.append("\n## 需要处理的\n")
    md += [f"- {b}" for b in bad] if bad else ["- 无"]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"soak-{rounds}轮.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\n{'='*60}")
    print("需要处理的：" + ("\n  - " + "\n  - ".join(bad) if bad else "无"))
    print(f"报告 → samples/soak-{rounds}轮.md")


if __name__ == "__main__":
    main()
