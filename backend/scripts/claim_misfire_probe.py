"""7.1 的误伤探针：在真实用户笔记上量 `claims.unsupported_specifics` 会不会开火。

**这一批最大的风险就是误伤**（铁律：把一句有出处的话判成「编造」，会逼模型把
真内容删掉，比漏判严重得多）。所以这个脚本照批 16 量 `checks/numbers` 那一套
做，一字不改：

* **语料**：`origin=user` 那一类，走 `corpus_lineage`（**「真实产出」≠「用户
  写的」**，批 6 栽过：6 篇"干净语料"出自同一次拿真实 user_id 跑的 `soak`）。
* **自源头档**：每篇**同时当产出和源头**——笔记里的每个日期 / 名字按定义都追得到
  这篇笔记，所以**一次都不该开火**。这是"零误伤"那条验收的原文。
* **严苛档**（批 18 自己加的）：每篇后 30% 当「这一轮写的」、前 70% 当**唯一**
  源头。生产里源头还包含全部事实和工具返回，所以这一档是**上界不是生产值**
  ——但它是唯一能在没有真跑的情况下逼出"新写的内容"这种形状的档，
  拆解粒度和原子选类那几个数就是在它上面量出来的。
* **反向那一半**：把笔记里一个真日期改掉再跑，**必须抓住**。
  「判据没开火」和「判据坏了」是两件事，只量前者等于没量。

**只读。** 连 `update_note` 都没 import，整段夹在 `db_guard.Watch()` 里。

用法：

    cd backend && .venv/bin/python scripts/claim_misfire_probe.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus_lineage  # noqa: E402  （语料血缘判据，所有测量脚本共用这一份）
import db_guard  # noqa: E402

from app.harness import modes  # noqa: E402
from app.harness.agent_loop import ToolTrace  # noqa: E402
from app.harness.checks import claims  # noqa: E402
from app.harness.state import State  # noqa: E402
from app.harness.tools import ToolContext  # noqa: E402


def make_state(fresh: str, source: str) -> State:
    """一个只够跑这条判据的 State：`fresh` 是"这一轮写的"，`source` 是全部出处。"""
    st = State(mode=modes.for_run(modes.NOTE), ctx=ToolContext(user="probe", note_id="probe"))
    st.fresh = fresh
    st.content = fresh
    st.bag["content_at_start"] = source
    # 手上得有 oracle，否则判据按设计直接 return None（模块文档窄化第 3 条）。
    st.facts = ["[probe-0] 一条占位材料，不含任何日期和名字"]
    st.trace = ToolTrace()
    return st


def count(fresh: str, source: str) -> tuple[int, list[str]]:
    """(候选原子数, 开火的那几个)。"""
    st = make_state(fresh, source)
    cands = claims.relevant(claims.atoms(fresh))
    verdict = claims.unsupported_specifics(st)
    keys = claims.source_keys(claims.sources(st))
    fired = [a.surface for a in cands if not claims.supported(a, keys)]
    if verdict is None and fired:
        # 判据自己有字数下限等别的闸；报出来免得两个数对不上还没人知道。
        fired = [f"{x}（判据未开火：正文太短或没有 oracle）" for x in fired]
    return len(cands), fired


_A_DATE = re.compile(r"(?<![\d])(\d{4})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})\s*[日号]?(?![\d])")


def inject(text: str) -> str | None:
    """把正文里第一个完整日期的年份挪走——植入一条**已知**的编造。"""
    m = _A_DATE.search(text)
    if not m:
        return None
    y = int(m.group(1))
    return text[:m.start()] + m.group(0).replace(str(y), str(y + 5), 1) + text[m.end():]


def main() -> None:
    kept, dropped = corpus_lineage.load_notes(keep={corpus_lineage.ORIGIN_USER})
    notes = [r for r in kept if (r["content"] or "").strip()]
    print(f"语料：`origin=user` {len(kept)} 篇（排掉 {len(dropped)} 篇），非空 {len(notes)} 篇")

    self_c = self_f = 0
    strict_c = strict_f = 0
    fires: list[str] = []
    for n in notes:
        body = n["content"]
        c, f = count(body, body)
        self_c += c
        self_f += len(f)
        fires += [f"自源头档 {n['id']}: {x}" for x in f]
        cut = int(len(body) * 0.7)
        c, f = count(body[cut:], body[:cut])
        strict_c += c
        strict_f += len(f)
        fires += [f"严苛档 {n['id']}: {x}" for x in f]

    print(f"\n自源头档（整篇同时当产出和源头，按定义一次都不该开火）："
          f"候选 {self_c}，**开火 {self_f}**")
    print(f"严苛档（后 30% 当产出、前 70% 当唯一源头，上界不是生产值）："
          f"候选 {strict_c}，开火 {strict_f}")
    for line in fires:
        print("   ", line)

    # 反向：植入一条已知的编造，必须抓住
    hit = miss = skipped = 0
    for n in notes:
        body = n["content"]
        bad = inject(body)
        if bad is None:
            skipped += 1
            continue
        _c, f = count(bad, body)
        if f:
            hit += 1
        else:
            miss += 1
    print(f"\n反向（把一个真日期的年份挪走，必须抓住）：抓住 {hit}，漏 {miss}，"
          f"没有完整日期可植入 {skipped}")


if __name__ == "__main__":
    with db_guard.Watch():
        main()
