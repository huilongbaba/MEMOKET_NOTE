"""criteria drift 的重新校准入口（计划 10.3 / [IND] §8③ EvalGen）。

    cd backend && .venv/bin/python scripts/criteria_drift.py
    cd backend && .venv/bin/python scripts/criteria_drift.py --show no_audit_voice

**只读**（`db_guard.readonly()` + `Watch()`），一次模型调用都不发。
**只报，不改任何判据**——理由见下面「为什么只报」。

## 这个入口在回答什么

`EvalGen` / *Who Validates the Validators?*（UIST 2024）给这件事起了名字，
叫 **criteria drift**：

> 用户需要判据才能给产出打分，**而给产出打分这件事又反过来帮他定义判据**。
> 有些判据是**依赖于具体看到的那些产出**的，不是先验可定义的。

我们这套判据**正是这么长出来的**（`harness-evaluators.md` 第三节第 1 条：
每一个维度都是读产出读出来的；`checks/` 里每一条的 docstring 都写着它是哪一次
真跑实拍出来的）。所以判据一旦冻结，它就只对当初那批产出有效，而**没有任何
机制会告诉我们它什么时候失效**。批 20 / 21 的 `no_audit_voice` 是一次手工的
复查：整篇口径在 18 篇真实笔记上开火 27.8%，收了量程之后 0%。
这个脚本要的就是**把那次手工复查变成一个能反复跑的入口**。

## 为什么只报

批 21 的教训写死在 §21 里：**顺手量出来的数，当分母用之前得先逐条读。**
批 20 报的「4 篇命中的是业务词」，逐句读出来是 **2 篇业务词 + 3 篇真缺陷**，
而那 3 篇真缺陷**全是靠批 20 提议删掉的那个词抓住的**——照着那个数去改判据，
当场把真正要抓的三篇全漏掉。

所以这里：**每条判据都能一键列出原文命中片段**（`--show <判据名>`），
数字只用来排优先级，改不改由人逐条读完再定。

## 血缘必须分开

`user` / `script` / `fixture` 三类分别给数（`scripts/corpus_lineage.py`）。
批 4 / 批 6 两次栽在这——3/6 语料出自同一次 `soak.py`、31 篇里混着一篇 47k 字
的合成探针。**混着算出来的漂移率是假的。** 按那个模块的规矩：
`user` 才能算比例，`script` 只能看形状，`fixture` 是纯噪声。

## 三个口径，各自说什么

| 口径 | State 怎么摆 | 它回答什么 |
|---|---|---|
| **whole**「整篇都是这一轮写的」 | `content_at_start=""` · `fresh=正文` | 判据的**上界**：它一共会对这批文字开几次火 |
| **stale**「整篇都是开跑前就有的」 | `content_at_start=正文` · `fresh=""` | **量程**：这一档命中的每一句，都是判据在打**不是这次跑写的字**。批 21 收 `no_audit_voice` 收的就是这一档，其余判据从没人查过 |
| **reach**「喂得动吗」 | 一段**踩满毛病**的合成正文 | 前提检测：语料上一次没开火、探针也打不着，那它的 0% 不算数——是这份语料喂不动它，不是它不漂 |
| **facts**「换成手上有材料呢」 | 同 whole，但 `st.facts` 非空 | **把脚本自己造成的开火摘出去**：这个脚本不发调用，`st.facts` 恒空，而 `material_thin` 的第一个触发条件就是「手上一条材料都没有」——它 72.2% 的开火率说的是这个脚本的形态，不是这批文字 |

`whole − stale` 就是「靠『这次跑写的』这条边界挡下来的量」。

## 谁在名单里、谁不在

只跑**长文那两个模式**（`note` / `section`）的判据：只有它们的 `st.content`
真的就是这篇笔记的正文。六个 block 模式的判据判的是**光标旁边那一块**
（`ctx.content` + `cursor`），拿整篇笔记喂它们是个范畴错误——
`table_present` 会在每一篇没有表的笔记上开火，那个 100% 什么都不说明。
它们在报告里单独一栏列出来并说明「这份语料量不了」，**不是悄悄漏掉**。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import corpus_lineage as cl  # noqa: E402
import db_guard  # noqa: E402

from app.harness import modes  # noqa: E402
from app.harness.state import State  # noqa: E402
from app.harness.tools import ToolContext  # noqa: E402

# 上一次跑的数字存这儿。**进 `.local/` 不进 git**：里面带着命中片段和笔记 id，
# 那是用户内容（`.gitignore` 里 `data/` 和 `.local/` 是同一条理由）。
BASELINE = (pathlib.Path(__file__).resolve().parents[2]
            / ".local" / "criteria_drift" / "latest.json")

# 只量这两个模式的判据，理由见模块文档。
LONGFORM = (modes.NOTE, modes.SECTION)

# 「喂得动吗」那一档用的合成正文。**它只回答一个 yes/no（这条判据在这个
# State 形态下开不开得了火），不参与任何比例**——§21 那条「造语料时『看起来
# 像正文』和『统计性质像正文』是两件事」说的是拿合成语料算比例，不是拿它探
# 通路。每一段后面写着它是给哪条判据踩的。
PROBE = """## 一、四月的节奏

这一段的详细内容待补充。

现有材料不足以说明这一判断，仍需与对应的会议记录核对后再写入。

我们在 2031 年 4 月 10 日完成了 37.5% 的交付，负责人是 Speaker Q。

引用一条不存在的事实 [terrence-9999-ZZZ] 看看。

- 第一条
- 第二条

- 第一条
- 第二条

## 一、四月的节奏

这一段的详细内容待补充。

```mermaid
bar
  title 手写的图
```
"""


def _mode_checks() -> tuple[list[tuple[str, object, object]], dict[str, str]]:
    """`[(判据名, 函数, 它所属的 Mode)]` + 「不在名单里的那些 → 为什么」。

    同一条判据被两个模式共用时只量一次（挑先出现的那个模式）——它是同一个
    函数，两个模式喂的 State 在这个脚本里也是同一份。
    """
    picked: list[tuple[str, object, object]] = []
    seen: set[str] = set()
    for mode in LONGFORM:
        run_mode = modes.for_run(mode, has_profile=False, polish=False)
        for check in mode.checks:
            name = check.__name__
            if name in seen:
                continue
            seen.add(name)
            picked.append((name, check, run_mode))

    skipped: dict[str, str] = {}
    for mode in modes.ALL:
        if mode in LONGFORM:
            continue
        for check in mode.checks:
            if check.__name__ not in seen:
                skipped.setdefault(
                    check.__name__,
                    f"只挂在块模式上（{mode.key}）：它判的是光标旁边那一块，"
                    "不是整篇笔记——拿笔记喂它量出来的数没有意义")
    return picked, skipped


def _state(mode, row: dict, *, text: str, before: str) -> State:
    """一篇笔记摆成「一次跑」的形状。

    `facts` 留空是**如实的**：这个脚本不发任何调用，这一轮手上就是没有材料。
    需要材料才开得了火的那几条（`citations_hold` / `material_used` …）因此会
    在「喂得动吗」那一档里被标出来，而不是伪装成 0%。
    """
    ctx = ToolContext(user=row.get("user_id", ""), note_id=row.get("id", ""),
                      note_title=row.get("title", ""), content=text, cursor=len(text))
    return State(
        mode=mode, ctx=ctx, round=1,
        before=text, content=text, fresh=(text if not before else ""),
        bag={"content_at_start": before,
             "spine": row.get("spine") or "",
             "beats": [b for b in (row.get("beats") or "").split("\n") if b.strip()]},
    )


# 「这条判据是不是靠 `st.facts` 为空才开的火」那一档喂的假材料。
# 只用来做 yes/no 的通路检测，不参与任何比例。
PROBE_FACTS = ["[probe-0001] 这是一条占位材料，只用来检测这条判据依不依赖手上有没有材料。"]


def _fire(check, mode, row: dict, *, text: str, before: str,
          facts: list[str] | None = None) -> str:
    """开火了就返回诊断原话，没开火返回空串。判据抛异常也算「没开火」，
    但**要说出来**——一条在真实语料上会抛的判据，在生产里是被 `loop._fire`
    吞成一条 warning 的。"""
    try:
        st = _state(mode, row, text=text, before=before)
        if facts:
            st.facts = list(facts)
            st.facts_new = list(facts)
        verdict = check(st)
    except Exception as exc:                      # noqa: BLE001
        return f"!! {type(exc).__name__}: {exc}"
    return verdict.message if verdict else ""


def measure(rows_by_origin: dict[str, list[dict]]) -> dict:
    checks, skipped = _mode_checks()
    probe_row = {"id": "(probe)", "user_id": "", "title": "探针", "spine": "", "beats": ""}
    out: dict = {"checks": {}, "skipped": skipped,
                 "corpus": {k: len(v) for k, v in rows_by_origin.items()}}

    for name, check, mode in checks:
        probe = bool(_fire(check, mode, probe_row, text=PROBE, before=""))
        entry: dict = {"probe": probe, "by_origin": {}}
        fired_anywhere = False
        for origin, rows in rows_by_origin.items():
            by_id = {r["id"]: r for r in rows}
            whole = [(r["id"], _fire(check, mode, r, text=r["content"], before=""))
                     for r in rows]
            whole = [(i, m) for i, m in whole if m]
            stale = [(r["id"], _fire(check, mode, r, text=r["content"],
                                     before=r["content"]))
                     for r in rows]
            stale = [(i, m) for i, m in stale if m]
            # 同一批开火的，换成「手上有材料」再判一次。全都不开火了，
            # 说明这条判据开的是**这个脚本没去检索**的火，不是这批文字的火。
            with_facts = [i for i, _m in whole
                          if _fire(check, mode, by_id[i], text=by_id[i]["content"],
                                   before="", facts=PROBE_FACTS)]
            fired_anywhere = fired_anywhere or bool(whole)
            entry["by_origin"][origin] = {
                "n": len(rows),
                "whole": len(whole),
                "stale": len(stale),
                "with_facts": len(with_facts),
                "whole_ids": [i for i, _m in whole],
                "stale_ids": [i for i, _m in stale],
                "samples": [{"id": i, "message": m[:200]} for i, m in whole[:3]],
            }
        # **「活着」不是探针说了算，是语料说了算。** 探针只在语料一次都没开火
        # 的时候才有话说：那时候它区分「前提根本不成立」和「这批文字真的干净」。
        entry["alive"] = fired_anywhere or probe
        out["checks"][name] = entry
    return out


# ----------------------------------------------------------------- 报告 ---

def _pct(n: int, d: int) -> str:
    return f"{n * 100 / d:5.1f}%" if d else "  n/a"


def report(cur: dict, prev: dict | None) -> None:
    corpus = cur["corpus"]
    print("=== 语料（分血缘，`user` 才能算比例）===")
    for origin in cl.ORIGINS:
        print(f"  {origin:<8} {corpus.get(origin, 0):>4} 篇")

    print("\n=== 每条判据的触发率 ===")
    print("  whole = 整篇当这一轮写的（上界） · stale = 整篇当开跑前就有的（量程，应当为 0）")
    print("  活 = 语料上开过火，或者探针打得着；否 = 这份语料的形态喂不动它，它的 0% 不算数")
    head = f"  {'判据':<24}{'活':<5}"
    for origin in cl.ORIGINS:
        head += f"{origin + ' whole':>15}{origin + ' stale':>15}"
    print(head)
    for name, e in cur["checks"].items():
        line = f"  {name:<24}{'活' if e['alive'] else '否':<5}"
        for origin in cl.ORIGINS:
            b = e["by_origin"].get(origin, {})
            n, w, s = b.get("n", 0), b.get("whole", 0), b.get("stale", 0)
            line += f"{w:>4}/{n:<4}{_pct(w, n):>7}"
            line += f"{s:>4}/{n:<4}{_pct(s, n):>7}"
        print(line)

    print("\n=== 该看的（排了优先级，**动判据之前先 `--show` 逐条读**）===")
    print("  §21：顺手量出来的数，当分母用之前得先逐条读。批 20 那 4 篇「业务词误伤」"
          "逐句读出来是 2 篇误伤 + 3 篇真缺陷。")
    flagged = []
    for name, e in cur["checks"].items():
        b = e["by_origin"].get(cl.ORIGIN_USER, {})
        n = b.get("n", 0)
        w, s, f = b.get("whole", 0), b.get("stale", 0), b.get("with_facts", 0)
        if s:
            flagged.append((3, name,
                            f"**量程**：{s}/{n} 篇在「整篇都是开跑前就有的」这一档还会开火"
                            "——它会去打不是这次跑写的字。**是真缺陷还是误伤，逐条读**"))
        elif w and not f:
            flagged.append((0, name,
                            f"开火 {w}/{n} 篇，但**换成手上有材料就一篇都不开火**"
                            "——这个数说的是「这个脚本没去检索」，不是这批文字"))
        elif not e["alive"]:
            flagged.append((2, name, "这份语料喂不动它（前提不成立），它的 0% 不算数"))
        elif n and w * 100 / n >= 20:
            flagged.append((1, name, f"在 {n} 篇真实笔记上开火 {w} 篇 = {w * 100 / n:.1f}%"
                                     "，该逐条读一遍是不是误伤"))
    for _rank, name, why in sorted(flagged, key=lambda x: (-x[0], x[1])):
        print(f"  {name:<24}{why}")
    if not flagged:
        print("  （没有）")

    print("\n=== 这份语料量不了的判据（不是漏掉，是范畴不对）===")
    for name, why in sorted(cur["skipped"].items()):
        print(f"  {name:<24}{why}")

    print("\n=== 跟上次跑比 ===")
    if not prev:
        print("  （没有上一次；这一次的数字已经存下，下次跑会跟它比）")
        return
    changed = False
    for name, e in cur["checks"].items():
        old = (prev.get("checks") or {}).get(name)
        if old is None:
            print(f"  {name:<24}新增的判据")
            changed = True
            continue
        for origin in cl.ORIGINS:
            a = old["by_origin"].get(origin, {})
            b = e["by_origin"].get(origin, {})
            for kind in ("whole", "stale"):
                if a.get(kind) != b.get(kind):
                    print(f"  {name:<24}{origin} {kind}: {a.get(kind)} → {b.get(kind)}")
                    changed = True
    for name in (prev.get("checks") or {}):
        if name not in cur["checks"]:
            print(f"  {name:<24}**没了**（判据被删掉或者从模式上摘了）")
            changed = True
    if not changed:
        print("  （一个数都没变）")


def show(cur: dict, rows_by_origin: dict[str, list[dict]], name: str) -> None:
    """一键列出原文命中片段——**这是「只报不改」那条规矩的兑现方式**。"""
    checks, _skipped = _mode_checks()
    found = [(n, c, m) for n, c, m in checks if n == name]
    if not found:
        print(f"没有叫 `{name}` 的判据。有的是：{', '.join(n for n, _c, _m in checks)}")
        return
    _n, check, mode = found[0]
    by_id = {r["id"]: r for rows in rows_by_origin.values() for r in rows}
    entry = cur["checks"][name]
    for origin in cl.ORIGINS:
        b = entry["by_origin"].get(origin, {})
        ids = b.get("whole_ids") or []
        print(f"\n=== {name} · {origin} · 开火 {len(ids)} / {b.get('n', 0)} 篇 ===")
        for nid in ids:
            row = by_id.get(nid)
            if row is None:
                continue
            msg = _fire(check, mode, row, text=row["content"], before="")
            stale = _fire(check, mode, row, text=row["content"], before=row["content"])
            print(f"\n  [{nid}] {row.get('title', '')[:40]}")
            print(f"    诊断：{msg[:300]}")
            print(f"    开跑前口径下：{'**还会开火**（量程没收住）' if stale else '不开火'}")
            for line in _snippets(row["content"], msg):
                print(f"    原文：{line}")


# 诊断原话里引用命中片段的分隔符。判据的措辞是「…本身：句一；句二。后面是建议」
# 这种形状，所以按这几个字符切开逐段去正文里找。
_SPLIT = re.compile(r"[：:；;\n]")
# 判据引用原文时**一律用直角引号**（`f"「{a[:40]}」和「{b[:40]}」"` 这种）。
# 先按引号取，再按分隔符切——一条命中里两段原文被「…」和「…」串在一起，
# 只按分隔符切的话整串当成一条去找，正文里当然找不到。
_QUOTED = re.compile(r"「([^「」]{4,})」")


def _snippets(content: str, message: str) -> list[str]:
    """诊断原话里通常逐字引着命中的片段；把它们在正文里定位一次，**连上下文
    一起**给出来——人要读的是原文，不是诊断的转述。

    **第一版是坏的**，而且是被突变验抓出来的：它只按 `；` 切，于是
    「…不是在谈事情本身：现有材料不足以…」整段作为一条去找，`piece[:30]`
    落在诊断自己的措辞上，正文里当然找不到——`--show` 从来没列出过一行原文，
    而那正是这个入口的全部价值。

    **第二版还是漏了一半**（真库上一跑就看见了）：`no_repeated_lists` 的判词是
    「…列了两遍：「甲」和「乙」。留下更完整的那一处…」，两段原文被引号串在一条
    里，按分隔符切完还是一整串。所以**先按直角引号取**，再退回按分隔符切。
    """
    out: list[str] = []
    pieces = _QUOTED.findall(message) + _SPLIT.split(message)
    seen: set[str] = set()
    for piece in pieces:
        piece = piece.strip().strip("。").strip("」").strip("「")
        if piece in seen:
            continue
        seen.add(piece)
        if len(piece) < 8:
            continue
        at = content.find(piece[:30])
        if at < 0:
            continue
        out.append(content[max(0, at - 40):at + len(piece) + 40].replace("\n", " ⏎ "))
        if len(out) >= 4:
            break
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--show", metavar="判据名", default="",
                    help="列出这条判据在每一篇上的命中片段，供逐条读")
    ap.add_argument("--no-save", action="store_true", help="不更新基线文件")
    args = ap.parse_args()

    kept, dropped = cl.load_notes(keep=set(cl.ORIGINS))
    rows = [r for r in kept + dropped if (r.get("content") or "").strip()]
    lineage = {}
    conn = db_guard.readonly()
    try:
        lineage = cl.load_lineage(conn)
    finally:
        conn.close()
    buckets = cl.split(rows, lineage)

    cur = measure(buckets)
    prev = None
    if BASELINE.exists():
        prev = json.loads(BASELINE.read_text(encoding="utf-8"))

    if args.show:
        show(cur, buckets, args.show)
        return

    report(cur, prev)
    if not args.no_save:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(cur, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        print(f"\n（这一次的数字存进 {BASELINE}，下次跑会跟它比）")


if __name__ == "__main__":
    # 这个脚本不该写任何用户笔记——写了就抛（批 14 的事故）。
    with db_guard.Watch():
        main()
