"""用面向写作的 prompt 重新抽取事实，**抽到独立 codebook**，分批停下来评估。

为什么要重抽：库自带的抽取 prompt 第一句是 "Extract durable, atomic
structured facts"，目标是"以后能被问答召回"——原子化、可精确定位、保留
说话人。写作要的恰恰相反：自足、带因果和约束、合并同一件事的多次提及、
不要说话人标签。实测现有 20361 条里 16% 对写作直接无用，剩下的也是问答形态。

**安全**：新事实写进 ``{user}-rewrite`` 这个独立 codebook，原始那份一个字
不动。评估满意之前不会有任何替换动作。

用法（渐进式，每一批跑完停下来看）：
    python scripts/reextract.py 10      # 先 10 个 session
    python scripts/reextract.py 50      # 扩到 50（跳过已抽过的）
    python scripts/reextract.py 100

每批跑完会打印新旧对照，并把明细写到 samples/reextract-<n>.md。
"""

from __future__ import annotations

import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.kite_memory import UserMemory, _export_provider_env  # noqa: E402
from app.kite_profile import WritingProfile  # noqa: E402
from app import store  # noqa: E402

USER = "terrence"
NEW_USER = f"{USER}-rewrite"
OUT = Path(__file__).resolve().parents[2] / "samples"

_FILLER = re.compile(r"(那个那个|就是就是|他他他|要要|嗯嗯|呃呃|我说那个|这个这个)")
_SPEAKER_ONLY = re.compile(r"^Speaker [A-Z] (说|表示|认为|提到)?\s*[「\"']?.{0,12}[」\"']?$")
_SPEAKER_IN_TEXT = re.compile(r"Speaker [A-Z]")


def unusable(t: str) -> str | None:
    """对写作基本无用的形态。跟诊断时用的是同一套判据，便于新旧直接比。"""
    if len(t) < 16:
        return "太短"
    if _FILLER.search(t):
        return "口语填充/ASR 噪声"
    if t.rstrip().endswith(("？", "?")):
        return "是提问不是事实"
    if _SPEAKER_ONLY.match(t):
        return "只有说话人+短语"
    return None


def profile_of(um: UserMemory):
    from memoket_kite import Memory

    st, vc = um._index()
    base = Memory.load([str(um.path)])._reasoner()._profile
    return WritingProfile(base, st, vc)


def meetings_from(um: UserMemory, limit: int, skip: set[str]) -> list[tuple[str, str, list[dict]]]:
    """把分块重组成**整场会议**再抽。

    这是重抽真正的关键，比换 prompt 更重要：入库时一场会议被切成约 1125
    字符的小块，每块单独当一个 session 抽取（实测 200 场会议被切成 2427 块，
    每场中位 7 块、最多 64 块）。抽取模型每次只看到一千多字的片段，看不到
    整场会议——**无法合并同一件事的多次提及，也无法补上因果和约束**，因为
    那些往往在别的块里。它只能产出碎片。

    unit id 形如 ``terrence-268-0``/``terrence-268-1``：去掉末尾的分块序号
    就是会议 id。按它分组、按序号排序拼接，一场会议一次抽取。
    """
    st, _vc = um._index()
    by_line: dict[str, list] = {}
    for line in st.lines.values():
        by_line.setdefault(line.unit, []).append(line)

    groups: dict[str, list] = {}
    for u in st.units.values():
        m = re.match(r"^(.*)-(\d+)$", u.id)
        key = m.group(1) if m else u.id
        groups.setdefault(key, []).append((int(m.group(2)) if m else 0, u))

    out = []
    for mid, items in sorted(groups.items()):
        if mid in skip:
            continue
        items.sort()
        msgs, date = [], ""
        for _idx, u in items:
            date = date or (getattr(u, "date", "") or "")
            for ln in by_line.get(u.id, []):
                txt = (ln.text or "").strip()
                if txt:
                    msgs.append({"role": "user", "name": ln.who or "speaker", "content": txt})
        if not msgs:
            continue
        out.append((mid, date, msgs))
        if len(out) >= limit:
            break
    return out


def main() -> None:
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    _export_provider_env()
    old = UserMemory(USER)
    new = UserMemory(NEW_USER)
    new.ensure()

    # 已经抽过的 session 跳过，方便分批扩大
    try:
        nst, _ = new._index()
        done = set(nst.units)
    except Exception:
        done = set()
    print(f"新 codebook 已有 {len(done)} 场会议，本次目标 {target}", flush=True)

    batch = meetings_from(old, target - len(done), done)
    if not batch:
        print("没有新的 session 要抽了。")
        return

    prof = profile_of(old)
    model = store.get_active_llm_config()["model"]
    print(f"用 {model} 抽 {len(batch)} 场会议（原来是按 ~1125 字符的分块抽的）…", flush=True)

    t0 = time.monotonic()
    for i, (uid, date, msgs) in enumerate(batch, 1):
        try:
            n = new.remember(msgs, session_id=uid, date=date or None, profile=prof)
            chars = sum(len(x["content"]) for x in msgs)
            print(f"  [{i}/{len(batch)}] {uid} {date} {len(msgs)}块/{chars:,}字 → {n} 条事实", flush=True)
        except TypeError:
            # remember() 还没接受 profile 参数时的兜底，见下面的说明
            print(f"  [{i}/{len(batch)}] {uid}: remember() 不接受 profile，需要先改 kite_memory", flush=True)
            return
        except Exception as exc:
            print(f"  [{i}/{len(batch)}] {uid} 失败: {type(exc).__name__}: {exc}", flush=True)
    dt = time.monotonic() - t0

    # ---------------- 新旧对照 ----------------
    ost, _ = old._index()
    new.invalidate()
    nst, _ = new._index()
    uids = {uid for uid, _d, _m in batch}
    def meeting_of(unit_id: str) -> str:
        m = re.match(r"^(.*)-(\d+)$", unit_id)
        return m.group(1) if m else unit_id

    old_facts = [f.text for f in ost.facts.values()
                 if f.src and ost.lines.get(f.src[0])
                 and meeting_of(ost.lines[f.src[0]].unit) in uids]
    # 只取**本批**抽出来的，不是新库里的全部——否则第二批开始，分母里混进了
    # 上一批的事实，跟"同样这 N 个 session"的旧事实比就不是同一批了
    # （实测第二批报成「旧 11647 条 / 新 2896 条」，而 2896 是两批合计）。
    new_facts = [f.text for f in nst.facts.values()
                 if f.src and nst.lines.get(f.src[0])
                 and meeting_of(nst.lines[f.src[0]].unit) in uids]

    def stats(facts: list[str]) -> dict:
        bad = Counter(unusable(t) for t in facts)
        lens = sorted(len(t) for t in facts) or [0]
        return {
            "条数": len(facts),
            "中位长度": lens[len(lens) // 2],
            "无用比例": f"{sum(v for k, v in bad.items() if k) / max(1, len(facts)) * 100:.0f}%",
            "含 Speaker 标签": f"{sum(1 for t in facts if _SPEAKER_IN_TEXT.search(t)) / max(1, len(facts)) * 100:.0f}%",
        }

    o, n = stats(old_facts), stats(new_facts)
    print(f"\n=== 同样这 {len(uids)} 个 session，{dt:.0f}s ===")
    for k in o:
        print(f"  {k:14} 旧 {str(o[k]):>8}   新 {str(n[k]):>8}")

    OUT.mkdir(parents=True, exist_ok=True)
    md = [f"# 重抽对照（{len(uids)} 个 session）", "",
          f"模型 {model} ｜ 耗时 {dt:.0f}s", "",
          "| 指标 | 旧 | 新 |", "|---|---|---|"]
    md += [f"| {k} | {o[k]} | {n[k]} |" for k in o]
    md += ["", "## 旧事实（抽样 20）", ""] + [f"- {t}" for t in old_facts[:20]]
    md += ["", "## 新事实（抽样 20）", ""] + [f"- {t}" for t in new_facts[:20]]
    (OUT / f"reextract-{len(uids)}.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\n明细 → samples/reextract-{len(uids)}.md")


if __name__ == "__main__":
    main()
