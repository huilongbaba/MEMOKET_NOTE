"""批 21 的分母：`no_audit_voice` / 落盘 scrub 在**用户自己写的字**上误伤多少。

    cd backend && .venv/bin/python scripts/audit_voice_misfire.py

**只读**（`db_guard.readonly()` + `Watch()`），一次模型调用都不发。

## 为什么要有这么一个脚本

批 20 量 magic tap 的时候顺手发现：`AUDIT_PHRASES` + `LEAK_PHRASES` 在 18 篇
`origin=user` 真实笔记上命中 **5 篇（27.8%）**，而这条判据挂在 `note` / `section`
上、**会短路打分并要求模型改写**；同一张词表还挂在落盘那一路
（`scrub_meta_sentences_v`），那一路是**直接删句子**。

铁律第 3 条：阈值和误伤率一律在真实产出上量，不拍脑袋；而量出来的数必须**能重跑**。

## 四段，各自量什么

| 段 | 量什么 | 语料 | 血缘 |
|---|---|---|---|
| ① 整篇口径 | 现在这条判据在 18 篇真实笔记上开火几篇、几句 | `origin=user` 非空笔记 | `user` |
| ② 一次真跑的形状 | 18 篇 × 34 份续写：命中的句子来自**用户原文**还是**这一轮写的** | 同上 + 单次续写 | `user` × `script` |
| ③ 真阳性回归 | 四句**真实的**审计腔 / 机制泄漏当这一轮的产出，改完还认不认得 | 代码注释和 bench 里记着的原话 | — |
| ④ 落盘 scrub | 同一张词表在落盘那一路会删掉用户原文里的几句 | `origin=user` 非空笔记 | `user` |

②「34 份续写」是 `script` 血缘：**只能看形状，不能算比例**
（`corpus_lineage` 的规矩）。所以②报的是「误伤句次」的绝对下降，
比例只在①和④上算——那两段的语料全是 `user`。
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import corpus_lineage as cl  # noqa: E402
import db_guard  # noqa: E402
from tap_report_denominator import continuations  # noqa: E402

from app.harness.checks import grounding_rules as gr  # noqa: E402

# 四句**真实的**缺陷原文，出处逐条写在后面。它们是这条判据的真阳性样本：
# 改完之后一句都不许漏（放宽判据必须先证明没把该抓的放掉——[EVAL] §3④）。
TRUE_POSITIVES = [
    # `scripts/dimension_sensitivity_bench.py:AUDIT_SENTENCE`，原样来自
    # `ecfac1f3c0aa` 那篇真产出。
    "现有材料不足以说明这一判断，仍需与对应的会议记录核对后再写入。",
    # `checks/grounding_rules.py` 注释里记着的文件夹级 bench 两次实拍。
    "即使面向发货的相关功能已经可用，也不能据此判断用户已经完成硬件交付。",
    "Lassie 的能力扩展仍缺少对应的版本与测试记录，因此不能据此断言它已经可用。",
    # 同一段注释里记着的机制泄漏原话。
    "目前 KB 中可核对的记录集中在四月那几周。",
]


def user_notes() -> list[dict]:
    kept, _dropped = cl.load_notes(keep={cl.ORIGIN_USER})
    return [r for r in kept if (r["content"] or "").strip()]


def section_whole(notes: list[dict]) -> None:
    print(f"\n=== ① 整篇口径（现状）：{len(notes)} 篇 `origin=user` 真实笔记 ===")
    fired = [(n["id"], gr.audit_voice_lines(n["content"])) for n in notes]
    fired = [(i, ls) for i, ls in fired if ls]
    total = sum(len(ls) for _i, ls in fired)
    print(f"开火 {len(fired)} 篇 / {len(notes)} 篇 = {len(fired) * 100 / len(notes):.1f}%"
          f"，共 {total} 句")
    for i, ls in fired:
        for line in ls:
            print(f"  {i}  {line[:76]}")
    print("\n  改后（同一批笔记当作『这次跑开始时就有的正文』）：")
    after = [(n["id"], gr.audit_voice_lines(n["content"], before=n["content"]))
             for n in notes]
    after = [(i, ls) for i, ls in after if ls]
    print(f"  开火 {len(after)} 篇，共 {sum(len(ls) for _i, ls in after)} 句")


def section_run_shape(notes: list[dict]) -> None:
    """一次真跑的形状：用户原文在前，这一轮写的接在后面。"""
    cont = continuations()
    print(f"\n=== ② 一次真跑的形状：{len(notes)} 篇 × {len(cont)} 份续写 ===")
    before_hits = after_hits = from_user = from_fresh = 0
    for n in notes:
        head = n["content"] or ""
        for _name, fresh in cont:
            whole = head + "\n\n" + fresh
            old = gr.audit_voice_lines(whole, limit=50)
            new = gr.audit_voice_lines(whole, before=head, limit=50)
            before_hits += len(old)
            after_hits += len(new)
            for line in old:
                if "".join(line.split()) in "".join(head.split()):
                    from_user += 1
                else:
                    from_fresh += 1
    print(f"  整篇口径：{before_hits} 句命中"
          f"（其中来自用户原文 {from_user} 句 = {from_user * 100 / max(1, before_hits):.1f}%，"
          f"来自这一轮写的 {from_fresh} 句）")
    print(f"  只判这一轮写的：{after_hits} 句命中"
          f"（应当等于上面的『来自这一轮写的』{from_fresh}）")


def section_true_positives() -> None:
    print("\n=== ③ 真阳性回归：四句真实缺陷当这一轮的产出 ===")
    head = ("## 四月的交付节奏\n\n四月上旬定下对外对齐点，硬件那一批的到货排在六月。\n"
            "这一段是用户自己早就写在笔记里的话。\n")
    ok = True
    for sentence in TRUE_POSITIVES:
        whole = head + "\n" + sentence
        hit = gr.audit_voice_lines(whole, before=head)
        print(f"  {'认得' if hit else '**漏了**'}  {sentence[:52]}")
        ok = ok and bool(hit)
    print(f"  → {'四句一句没漏' if ok else '有漏，不许改'}")
    # 反过来：同一句话如果是用户开跑前就写在那儿的，一句都不许报。
    stale = [s for s in TRUE_POSITIVES
             if gr.audit_voice_lines(head + "\n" + s, before=head + "\n" + s)]
    print(f"  同样四句挪到开跑前：报 {len(stale)} 句（要 0）")


def section_scrub(notes: list[dict]) -> None:
    print("\n=== ④ 落盘 scrub：会删掉用户原文里的几句 ===")
    old_n = old_s = new_n = new_s = 0
    for n in notes:
        body = n["content"] or ""
        _out, gone = gr.scrub_meta_sentences_v(body)
        if gone:
            old_n += 1
            old_s += len(gone)
        _out2, gone2 = gr.scrub_meta_sentences_v(body, before=body)
        if gone2:
            new_n += 1
            new_s += len(gone2)
    print(f"  现状：{old_n} 篇 / {len(notes)} 篇被删，共 {old_s} 句")
    print(f"  改后：{new_n} 篇被删，共 {new_s} 句")


if __name__ == "__main__":
    # 这个脚本不该写任何用户笔记——写了就抛（批 14 的事故）。
    with db_guard.Watch():
        ns = user_notes()
        section_whole(ns)
        section_run_shape(ns)
        section_true_positives()
        section_scrub(ns)
