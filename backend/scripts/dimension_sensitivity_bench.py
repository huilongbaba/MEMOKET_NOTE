"""25 个评分维度的**灵敏度**评测台：往真实产出里植入已知缺陷，看对应那一维掉不掉分。

## 为什么是这个形状（计划 1.6 / [IND] §8④）

CriticGPT 的训练数据是「让人往代码里塞一个 bug，再写下对这个 bug 的批评」。
套到我们这儿：**拿过去的真实产出，机械地植入一个已知缺陷，看负责抓它的那一维
会不会掉分。** 一维抓不住自己该抓的东西 = 那一维不合格。

这正好能回答 `harness-evaluators.md` 留下的那个问题——实测里
`material_use` 25 次 24 次满分、`fits_context` / `follows_prompt` /
`no_fabrication` / `table_validity` / `data_grounding` 100% 满分，
到底是**判据废了**，还是**那个条件很少出现**。这两件事的处理方式完全相反
（前者该改判据，后者该补上下文），而现有数据分不开它们。

所以每一行结果都带一个 `condition` 列：
* `as-deployed`：跟生产里 `loop._evaluate` 一模一样的上下文（长文两条 harness
  给 `score_context`，六个 block 模式**什么都不给**）；
* `with-evidence`：额外把那一维的判词里**明确提到、而生产从不提供**的证据
  塞进 context（【知识库事实】块、个人偏好、用户那条指令、前后文）。

同一个缺陷在两种条件下的差值，就是「判据废了」和「条件没出现」的分界线。

## 跟旁边两个 bench 的分工

* `writing_quality_bench.py`：干净种子 → 跑一整趟 harness → 用**确定性判定**
  检查产出里有没有长出缺陷。考的是 **写作**。
* `editing_quality_bench.py`：带已知缺陷的文本 → 跑编辑 → 看缺陷修没修掉。
  考的是 **编辑**。
* 这一个：真实产出 + 机械植入的已知缺陷 → 只跑 `evaluate()` 一次 →
  看**打分维度**掉不掉分。考的是 **评判者自己**。前两个都默认评判者是准的。

## 三条硬规矩（都是踩过的坑）

1. **绝对不碰用户的真实笔记。** 只读；植入全部发生在内存里的字符串副本上。
   `harness_quality_sample.py` 的开头写着理由：三篇真实笔记的原文因为
   「备份-还原」的结构性盲区永久丢失过。这个脚本连 `update_note` 都没 import。
2. **先排掉夹具 / 探针用户**（批 4 定下的规矩）。`shot-perf` 一个人就有 413 篇
   合成笔记、其中一篇 47k 字的性能探针是 100 个逐字相同的自动生成小节——
   不排掉，任何在「真实数据」上量出来的数都被它支配。上一批的阈值就是栽在这上面。
3. **能用代码判准的不交给模型。** 植入器自己是否真的把缺陷植进去了，
   一律用仓里已有的确定性判据（`grounding_rules.placeholder_lines` /
   `audit_voice_lines`、`blockcheck.fake_charts` / `unauthorized_charts` /
   `has_table`）现场自验——干净版必须干净、植入版必须被抓到，否则这一条
   probe 直接跳过并记下原因，而不是拿一个没植进去的"缺陷"去说维度不灵敏。

## 用法

    cd backend && .venv/bin/python scripts/dimension_sensitivity_bench.py \
        --notes 2 --repeats 3 --time-budget-seconds 500

可断点续跑（照 `harness_stress_test.py` 的路子）：每完成一次 `evaluate()` 就往
`dimension_sensitivity_log.jsonl` 追一行，下次调用跳过已经有的格子。
`--report` 只读日志出表，不发一次调用。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "dimension_sensitivity_log.jsonl"
OUT_DIR = ROOT / "sensitivity_results"
DB_PATH = ROOT.parent / "data" / "notes.sqlite3"


# =========================================================== 语料筛选 ===
#
# 批 4 的规矩：在真实数据上量任何东西之前，先排掉夹具 / 探针用户。
# 名单来自 `notes` 表里实际存在的 user_id，逐个看过内容之后定的，
# **宁可多排一个**——漏掉一个夹具会让整张表失真，多排一篇只是少一个样本。

FIXTURE_USERS = frozenset({
    "shot-perf",        # 413 篇合成笔记，含 47k 字的性能探针（批 4 的教训）
    "shot-demo",        # 截图演示用
    "harness-test-2",   # harness 自测
    "cancel-test3",     # 取消路径自测，2 篇共 26k 字全是自动生成
    "journey-probe",    # 探针
    "cleanup-test",     # 清理路径自测
    "search-test",      # 搜索自测
    "editing-bench",    # 旁边那个 bench 自己跑出来的
    "writing-bench",    # 同上
    "quality-sample",   # harness_quality_sample.py 的临时用户
    "fresh673", "fresh678", "fresh678b", "fresh678c",   # 新用户首屏的夹具
})

# 真实用户名下也会有一次性的自测笔记，标题里自己写着。窄判据：只认这两种
# 明确的自我标注，不做任何"看起来像测试"的推断。
FIXTURE_TITLE = re.compile(r"[（(]可删[）)]|^harness 测试|^链接测试")

# 太短的产出上植入不了几种缺陷（没有第二节可删、没有第二段可复制），
# 而且短文本上一次打分的方差最大。
MIN_CHARS = 600


def fixture_reason(user_id: str, title: str) -> str:
    """这篇是不是夹具 / 探针。返回原因字符串；空串 = 是真实产出。"""
    if user_id in FIXTURE_USERS:
        return f"夹具用户 {user_id}"
    if FIXTURE_TITLE.search(title or ""):
        return f"标题自标注为自测：{title[:20]}"
    return ""


def select_corpus(rows: list[dict], *, min_chars: int = MIN_CHARS) -> tuple[list[dict], list[dict]]:
    """纯函数：把 `(id, user_id, title, content, spine, beats)` 行分成留下的和排掉的。

    返回 `(kept, dropped)`，`dropped` 每项带 `reason`——**排掉了什么必须能报出来**，
    批 4 的问题正是"语料脏"这件事本身没有任何地方看得见。
    """
    kept: list[dict] = []
    dropped: list[dict] = []
    for row in rows:
        reason = fixture_reason(row.get("user_id", ""), row.get("title", ""))
        if not reason and len((row.get("content") or "")) < min_chars:
            reason = f"太短（{len(row.get('content') or '')} < {min_chars} 字）"
        if reason:
            dropped.append({**row, "reason": reason})
        else:
            kept.append(row)
    kept.sort(key=lambda r: -len(r.get("content") or ""))
    return kept, dropped


def load_corpus(db_path: Path = DB_PATH) -> tuple[list[dict], list[dict]]:
    """跑过 harness 的笔记（`harness_runs.key`），**只读**打开。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        # key 是 note_id，block 模式带 `<mode>:` 前缀（见 store.py 的注释）
        ids = {r["key"].split(":")[-1] for r in conn.execute("SELECT DISTINCT key FROM harness_runs")}
        rows = []
        for r in conn.execute("SELECT id, user_id, title, content, spine, beats FROM notes"):
            if r["id"] in ids:
                rows.append(dict(r))
    finally:
        conn.close()
    return select_corpus(rows)


# =============================================================== 取材 ===
#
# 长文两条 harness 判的是整篇，六个 block 模式判的是**插进笔记里的一块**。
# 所以 block 那几个不能拿整篇去打分——从真实笔记里取出真实的那一块。
# 取不到就返回 None（这一条 probe 在这篇上跳过），**不合成假语料**。

_PARA_SPLIT = re.compile(r"\n\s*\n")
_HEADING = re.compile(r"(?m)^(#{1,6})\s+(.*)$")
_MERMAID = re.compile(r"```mermaid\n.*?```", re.S)
_TABLE_BLOCK = re.compile(r"(?m)^(\|.*\|[ \t]*\n){2,}")


def paragraphs(text: str) -> list[str]:
    return [p for p in _PARA_SPLIT.split(text) if p.strip()]


def sections(text: str) -> list[tuple[str, str]]:
    """按 `##`+ 切成 (标题行, 正文) 对。标题之前的引子记成 ("", 引子)。"""
    marks = [m for m in _HEADING.finditer(text) if len(m.group(1)) >= 2]
    out: list[tuple[str, str]] = []
    if not marks:
        return [("", text)]
    if marks[0].start() > 0:
        out.append(("", text[: marks[0].start()]))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(0), text[m.end(): end]))
    return out


@dataclass(frozen=True)
class Subject:
    """一份拿去打分的正文 + 它在生产里会拿到的上下文。"""
    text: str
    context: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)   # with-evidence 才加的那一份


def pick_whole(note: dict) -> Subject | None:
    """整篇（note 模式）：上下文照抄 routers/note_harness.py 的 `_score_context`。"""
    ctx: dict[str, str] = {}
    if note.get("spine"):
        ctx["核心张力"] = note["spine"]
    beats = note.get("beats") or ""
    try:
        parsed = json.loads(beats) if beats else []
    except json.JSONDecodeError:
        parsed = []
    if parsed:
        ctx["结构节拍"] = "\n".join(f"- {b}" for b in parsed)
    return Subject(note["content"], ctx)


def pick_section(note: dict) -> Subject | None:
    """整篇（section 模式）：上下文照抄 routers/writing_plan.py 的 `_score_context`。"""
    title = (note.get("title") or "").strip()
    if not title or title == "未命名":
        heads = [m.group(2) for m in _HEADING.finditer(note["content"])]
        title = heads[0] if heads else ""
    if not title:
        return None
    return Subject(note["content"], {"这个分段的主题": title})


def _block_around(text: str, pat: re.Pattern) -> str | None:
    """真实笔记里的一块：`pat` 命中的那段 + 它前面那一段引子。"""
    m = pat.search(text)
    if not m:
        return None
    head = text[: m.start()].rstrip()
    lead = paragraphs(head)[-1] if paragraphs(head) else ""
    return (lead + "\n\n" + m.group(0).strip()).strip()


def pick_chart_block(note: dict) -> Subject | None:
    block = _block_around(note["content"], _MERMAID)
    return Subject(block) if block else None


def pick_table_block(note: dict) -> Subject | None:
    block = _block_around(note["content"], _TABLE_BLOCK)
    return Subject(block) if block else None


_NUM = re.compile(r"\d")


def pick_numeric_block(note: dict) -> Subject | None:
    """数字最密的那一节——eda / analysis 那几维要有数才判得动。"""
    best, best_n = None, 0
    for head, body in sections(note["content"]):
        n = len(_NUM.findall(body))
        if n > best_n:
            best, best_n = (head + "\n" + body).strip(), n
    if best_n < 6 or not best:
        return None
    return Subject(best)


def pick_paragraph(note: dict) -> Subject | None:
    """中间一段（prompt / custom 模式改写的就是这么一块）。"""
    ps = [p for p in paragraphs(note["content"]) if len(p) > 180 and not p.startswith("#")]
    if len(ps) < 2:
        return None
    return Subject(ps[len(ps) // 2])


def choose_notes(kept: list[dict], n: int,
                 selectors: dict[str, Callable[[dict], "Subject | None"]] | None = None) -> list[dict]:
    """取 N 篇，**再把取材器没人满足的那几种补上**。

    纯按长度取前 N 会漏掉整类 probe：真实语料里带 markdown 表的只有一篇，
    而且不长——那样 `table_validity` / `data_grounding` 永远是"未跑"，
    看上去像"没测出来"，其实是"没测"。两者必须分得开。
    """
    sel = selectors if selectors is not None else SELECTORS
    picked = list(kept[:n])
    for name, fn in sel.items():
        if any(fn(x) is not None for x in picked):
            continue
        for cand in kept:
            if cand in picked:
                continue
            if fn(cand) is not None:
                picked.append(cand)
                break
    return picked


def pick_whole_with_spine(note: dict) -> Subject | None:
    """`spine_fidelity` 判的是"紧扣核心张力"——**这篇得真的有核心张力**。

    实测踩过：前两篇最长的笔记 `spine` 都是空的，于是这一维是在"没有张力可扣"
    的条件下被打分的。那量出来的是"条件没出现"，不是"判据灵不灵"，两者必须分开。
    """
    return pick_whole(note) if (note.get("spine") or "").strip() else None


def pick_whole_with_beats(note: dict) -> Subject | None:
    """同理：`beat_coverage` 判的是"每条结构节拍都落到正文里"，没有节拍就无从判起。"""
    return pick_whole(note) if (note.get("beats") or "").strip() not in ("", "[]") else None


SELECTORS: dict[str, Callable[[dict], Subject | None]] = {
    "whole": pick_whole,
    "whole-with-spine": pick_whole_with_spine,
    "whole-with-beats": pick_whole_with_beats,
    "whole-section": pick_section,
    "chart-block": pick_chart_block,
    "table-block": pick_table_block,
    "numeric-block": pick_numeric_block,
    "paragraph": pick_paragraph,
}


# ============================================================= 植入器 ===
#
# 每个都是纯函数 `(text, donor) -> str | None`。返回 None = 这篇上植不了
# （没有第二节、没有表、没有数字……），这一格记成 skipped，不参与统计。
# `donor` 是**另一篇真实笔记**的正文，供"把别处的内容搬过来"那几种用。

def inj_duplicate_paragraph(text: str, donor: str) -> str | None:
    """复制一段放到别处（逐字）。→ non_repetition"""
    ps = paragraphs(text)
    if len(ps) < 4:
        return None
    src = max(ps[: len(ps) - 1], key=len)
    if len(src) < 120:
        return None
    tail = ps[-1]
    return text.replace(tail, src + "\n\n" + tail, 1)


def inj_off_spine_graft(text: str, donor: str) -> str | None:
    """把另一篇（另一个主题）的两段接到中间。→ spine_fidelity / topic_fidelity"""
    dps = [p for p in paragraphs(donor) if len(p) > 150 and not p.startswith("#")]
    ps = paragraphs(text)
    if len(dps) < 2 or len(ps) < 3:
        return None
    graft = "\n\n".join(dps[:2])
    mid = ps[len(ps) // 2]
    return text.replace(mid, mid + "\n\n" + graft, 1)


def inj_drop_last_section(text: str, donor: str) -> str | None:
    """删掉最后一个 `##` 小节（连标题带正文）。→ beat_coverage / section_coverage"""
    secs = sections(text)
    real = [s for s in secs if s[0]]
    if len(real) < 2:
        return None
    head, body = real[-1]
    return text.replace(head + body, "", 1).rstrip() + "\n"


def inj_truncate_bodies(text: str, donor: str) -> str | None:
    """每节只留第一句——"只开了个头就收尾"。→ section_coverage"""
    secs = sections(text)
    real = [s for s in secs if s[0]]
    if len(real) < 2:
        return None
    out = []
    for head, body in secs:
        if not head:
            out.append(body.strip())
            continue
        first = re.split(r"(?<=[。！？])", body.strip())
        keep = first[0] if first else ""
        # 本来就只有一句（或空）的节原样留着——砍不动的地方不算植入，
        # 但也不该让整条 probe 作废，下面还有总长度那道闸把关。
        out.append(head + "\n\n" + (keep if len(keep) >= 10 else body.strip()))
    new = "\n\n".join(x for x in out if x) + "\n"
    return new if len(new) < len(text) * 0.6 else None


_DATE = re.compile(r"(20\d\d)\s*年|(\d{1,2})\s*月\s*(\d{1,2})?\s*日?")


def inj_shift_dates(text: str, donor: str) -> str | None:
    """把年份和月份整体挪走（2026→2031，N 月→N+5 月）。→ factual_grounding / data_grounding

    只动数字不动别的：植入版和干净版逐字可比，掉分只可能来自"日期对不上"。
    """
    if len(_DATE.findall(text)) < 3:
        return None

    def bump(m: re.Match) -> str:
        if m.group(1):
            return f"{int(m.group(1)) + 5} 年"
        mon = (int(m.group(2)) + 5 - 1) % 12 + 1
        rest = m.group(0)[m.group(0).find("月"):]
        return f"{mon}{rest}"

    out = _DATE.sub(bump, text)
    return out if out != text else None


_QTY = re.compile(r"(\d+(?:\.\d+)?)\s*(万台|万|亿|%|％|台|人|条|美元|元)")


def inj_scramble_numbers(text: str, donor: str) -> str | None:
    """把每个量词数字改掉（×3 再 +7）。→ factual_grounding / numbers_from_tools / data_grounding"""
    hits = _QTY.findall(text)
    if len(hits) < 3:
        return None
    def bump(m: re.Match) -> str:
        v = float(m.group(1)) * 3 + 7
        s = f"{v:.1f}".rstrip("0").rstrip(".")
        return f"{s} {m.group(2)}"
    out = _QTY.sub(bump, text)
    return out if out != text else None


def inj_swap_section_bodies(text: str, donor: str) -> str | None:
    """把两节的正文对调——标题还在，讲的却是另一节的事。→ topic_fidelity / coherence

    取的是**前两节有实质正文的**，不是前两节：真实产出里第一个标题下面常常
    是空的（正文挂在它的子标题上），拿空的去换等于什么都没换。
    """
    real = [s for s in sections(text) if s[0] and len(s[1].strip()) >= 80]
    if len(real) < 2:
        return None
    (h1, b1), (h2, b2) = real[0], real[1]
    out = text.replace(h1 + b1, h1 + b2, 1)
    return out.replace(h2 + b2, h2 + b1, 1)


def inj_heading_levels(text: str, donor: str) -> str | None:
    """把第二个二级标题降成四级——标题层级混用。→ coherence"""
    marks = [m for m in _HEADING.finditer(text) if len(m.group(1)) == 2]
    if len(marks) < 3:
        return None
    m = marks[1]
    return text[: m.start()] + "#### " + m.group(2) + text[m.end():]


def inj_double_ending(text: str, donor: str) -> str | None:
    """把结尾那段复制到中间——正文里出现第二个结尾。→ coherence"""
    ps = paragraphs(text)
    if len(ps) < 5:
        return None
    ending = "综上所述，" + ps[-1].strip().lstrip("#").strip()[:180]
    mid = ps[len(ps) // 2]
    return text.replace(mid, mid + "\n\n" + ending, 1)


_SPECIFIC = re.compile(r"\d|[A-Za-z]{2,}")


def inj_strip_specifics(text: str, donor: str) -> str | None:
    """把所有带数字 / 外文名的句子删掉——只剩谁都能写的通用内容。→ material_use"""
    out_paras = []
    for p in paragraphs(text):
        if p.lstrip().startswith("#") or p.lstrip().startswith("|") or "```" in p:
            out_paras.append(p)
            continue
        sents = re.split(r"(?<=[。！？])", p)
        keep = [s for s in sents if s.strip() and not _SPECIFIC.search(s)]
        if keep:
            out_paras.append("".join(keep))
    new = "\n\n".join(out_paras)
    # 没删掉多少就等于没植入——宁可跳过，也不要拿一个没成形的缺陷去下结论
    if not new.strip() or len(new) > len(text) * 0.6:
        return None
    return new + "\n"


# 一句真实的审计腔，原样来自 ecfac1f3c0aa 那篇真产出（`AUDIT_PHRASES` 认得）
AUDIT_SENTENCE = "现有材料不足以说明这一判断，仍需与对应的会议记录核对后再写入。"


def inj_audit_voice(text: str, donor: str) -> str | None:
    """插一句审计腔。→ style_fit / coherence（`no_audit_voice` 的 pick 顺序）"""
    ps = paragraphs(text)
    if len(ps) < 3:
        return None
    mid = ps[len(ps) // 2]
    return text.replace(mid, mid + AUDIT_SENTENCE, 1)


PLACEHOLDER_LINE = "- 具体数字待补充"


def inj_placeholder(text: str, donor: str) -> str | None:
    """插一句占位符。→ `no_placeholder` 判据 + factual_grounding / no_fabrication"""
    ps = paragraphs(text)
    if len(ps) < 3:
        return None
    mid = ps[len(ps) // 2]
    return text.replace(mid, mid + "\n\n" + PLACEHOLDER_LINE, 1)


# 手写的 mermaid：y 轴范围是工具从不输出的写法（见 checks/charts.py 的原话）
HANDWRITTEN_MERMAID = (
    "```mermaid\nxychart-beta\n    title \"三档销量预测\"\n"
    "    x-axis [保守, 中性, 谨慎乐观]\n    y-axis \"万台\" 0 --> 12\n"
    "    bar [1.5, 3, 10]\n```")


def inj_handwrite_mermaid(text: str, donor: str) -> str | None:
    """加一张手写的 mermaid。→ chart_validity / `charts_from_tools` 判据"""
    return text.rstrip() + "\n\n" + HANDWRITTEN_MERMAID + "\n"


def inj_break_mermaid_fence(text: str, donor: str) -> str | None:
    """把 ```mermaid 的收尾去掉——一个截断的代码块。→ chart_validity"""
    m = _MERMAID.search(text)
    if not m:
        return None
    return text[: m.end() - 3] + text[m.end():]


def inj_chart_to_prose(text: str, donor: str) -> str | None:
    """把图换成一句"文字画的图"。→ has_charts / `no_fake_charts` 判据"""
    m = _MERMAID.search(text)
    if not m:
        return None
    # 形状照抄真实产出里被 `fake_charts` 抓到过的那一种（`[示意图：…]`）
    return text[: m.start()] + "[示意图：提交众筹 → 众筹版本 → 确认测试用户 → 回收反馈]" + text[m.end():]


def inj_duplicate_chart(text: str, donor: str) -> str | None:
    """同一张图再画一遍，只换标题。→ no_duplicate_charts"""
    m = _MERMAID.search(text)
    if not m:
        return None
    twin = m.group(0).replace("graph LR", "graph TD", 1)
    if twin == m.group(0):
        return None
    return text[: m.end()] + "\n\n换一个角度看同一组关系：\n\n" + twin + text[m.end():]


def inj_drop_chart_series(text: str, donor: str) -> str | None:
    """把图里第一条边删掉——正文提到的主角在图里没有了。→ covers_the_data"""
    m = _MERMAID.search(text)
    if not m:
        return None
    lines = m.group(0).splitlines()
    edges = [i for i, l in enumerate(lines) if "-->" in l]
    if len(edges) < 3:
        return None
    del lines[edges[0]]
    return text[: m.start()] + "\n".join(lines) + text[m.end():]


def inj_chart_to_image(text: str, donor: str) -> str | None:
    """把精确的图换成一张文生图。→ right_kind / chart_validity"""
    m = _MERMAID.search(text)
    if not m:
        return None
    return text[: m.start()] + "![节点关系示意图](/img/gen/timeline-7f3a.png)" + text[m.end():]


def inj_drop_table_column(text: str, donor: str) -> str | None:
    """表头少一列（数据行不动）。→ table_validity"""
    m = _TABLE_BLOCK.search(text)
    if not m:
        return None
    rows = m.group(0).rstrip("\n").split("\n")
    cells = rows[0].strip().strip("|").split("|")
    if len(cells) < 3:
        return None
    rows[0] = "|" + "|".join(cells[:-1]) + "|"
    return text[: m.start()] + "\n".join(rows) + "\n" + text[m.end():]


def inj_invent_table_cells(text: str, donor: str) -> str | None:
    """往表格里填笔记和材料里都没有的具体数。→ data_grounding"""
    m = _TABLE_BLOCK.search(text)
    if not m:
        return None
    body = m.group(0)
    if "填写" not in body:
        return None
    fills = iter(["842 万元", "2027 年 4 月 9 日", "13 组可比成交", "北向投资客"])
    def one(_m: re.Match) -> str:
        return next(fills, "31.7%")
    new = re.sub(r"填写[^|]*", one, body)
    return text[: m.start()] + new + text[m.end():]


def inj_invent_statistic(text: str, donor: str) -> str | None:
    """插一句没有任何工具算过的统计量。→ numbers_from_tools"""
    return text.rstrip() + "\n\n三档预测的均值为 4.83 万台，与投放预算的相关系数 r=0.91。\n"


_HEDGE = re.compile(r"(可能|预计|大致|尚不|不足以|需补|待确认|仍需|如果|若|假设|约)")


def inj_strip_caveats(text: str, donor: str) -> str | None:
    """删掉所有带保留措辞的句子，再补一句断言。→ honest_caveats / states_limits"""
    out = []
    dropped = 0
    for p in paragraphs(text):
        if p.lstrip().startswith(("#", "|")) or "```" in p:
            out.append(p)
            continue
        sents = re.split(r"(?<=[。！？])", p)
        keep = [s for s in sents if s.strip() and not _HEDGE.search(s)]
        dropped += len([s for s in sents if s.strip()]) - len(keep)
        if keep:
            out.append("".join(keep))
    if dropped < 3 or not out:
        return None
    return "\n\n".join(out) + "\n\n这三组数据已经足以证明趋势成立，不存在其他解释。\n"


_ACTION = re.compile(r"(下一步|接下来|应|需要|建议|值得|应当)")


def inj_strip_next_steps(text: str, donor: str) -> str | None:
    """删掉所有"接下来该做什么"的句子。→ actionable"""
    out, dropped = [], 0
    for p in paragraphs(text):
        if p.lstrip().startswith(("#", "|")) or "```" in p:
            out.append(p)
            continue
        sents = re.split(r"(?<=[。！？])", p)
        keep = [s for s in sents if s.strip() and not _ACTION.search(s)]
        dropped += len([s for s in sents if s.strip()]) - len(keep)
        if keep:
            out.append("".join(keep))
    if dropped < 2 or not out:
        return None
    return "\n\n".join(out) + "\n"


def inj_heading_flood(text: str, donor: str) -> str | None:
    """往一块里塞四个一级标题——体例跟周围对不上。→ fits_context"""
    ps = paragraphs(text)
    if len(ps) < 2:
        return None
    out = []
    for i, p in enumerate(ps):
        out.append(f"# 第 {i + 1} 部分" if i < 4 else "")
        out.append(p)
    return "\n\n".join(x for x in out if x) + "\n"


def inj_lead_in(text: str, donor: str) -> str | None:
    """加一句"好的，以下是修改后的版本"，再把选区之外的正文抄回来。→ replaces_cleanly"""
    dps = [p for p in paragraphs(donor) if len(p) > 120]
    if not dps:
        return None
    return "好的，以下是修改后的版本：\n\n" + text + "\n\n（以下保留原文）\n\n" + dps[0]


def inj_fabricate_specifics(text: str, donor: str) -> str | None:
    """插两句编造的人名 / 日期 / 金额。→ no_fabrication / factual_grounding"""
    return text.rstrip() + (
        "\n\n2027 年 4 月 9 日，Speaker K 在杭州与李文博确认了 2.7 亿元的首年采购额，"
        "并约定按季度分四次交付。该纪要编号为 HZ-2027-0409-11。\n")


def inj_answer_swap(text: str, donor: str) -> str | None:
    """正文整体换成另一篇的内容——答的不是问的那件事。→ answers_the_question / follows_prompt"""
    dps = [p for p in paragraphs(donor) if len(p) > 150 and not p.startswith("#")]
    if len(dps) < 2:
        return None
    return "\n\n".join(dps[:2]) + "\n"


# ------------------------------------------------- 植入器自验（确定性）---
#
# 「闸跑绿不等于闸有用」。这里反过来用：**植入器自己也要被确定性判据验过**。
# 干净版必须判过、植入版必须判不过，否则这一格跳过——不能拿一个根本没植进去
# 的"缺陷"去给维度定罪。

def _gate_placeholder(text: str) -> bool:
    from app.harness.checks import grounding_rules
    return bool(grounding_rules.placeholder_lines(text))


def _gate_audit(text: str) -> bool:
    from app.harness.checks import grounding_rules
    return bool(grounding_rules.audit_voice_lines(text))


def _gate_fake_chart(text: str) -> bool:
    from app.harness.checks import blockcheck
    return bool(blockcheck.fake_charts(text) or blockcheck.text_flow(text))


def _gate_handwritten_chart(text: str) -> bool:
    from app.harness.checks import blockcheck
    return bool(blockcheck.unauthorized_charts(text, []))


def table_column_mismatch(text: str) -> bool:
    """markdown 表的表头 / 分隔行 / 数据行列数对不对得上。

    `table_validity` 的达标线原话就是「header and rows have matching column
    counts」——**那是一句纯粹能用代码判准的话**，而仓里没有任何一处在判它：
    `checks/structure.py` 的 `table_present` 只查"有没有表"，
    `blockcheck.has_table` 只查"表头下面有没有分隔行"，两者都不数列。
    这里先在 bench 侧把它实现出来，用途是自验植入器真的把列数弄错了；
    它同时也是 5.x 那几条"有 oracle 的模式"要接进 `checks/` 的东西。
    """
    for m in _TABLE_BLOCK.finditer(text or ""):
        rows = [r for r in m.group(0).strip().split("\n") if r.strip()]
        widths = {len(r.strip().strip("|").split("|")) for r in rows}
        if len(widths) > 1:
            return True
    return False


def _gate_no_table(text: str) -> bool:
    return table_column_mismatch(text)


GATES: dict[str, Callable[[str], bool]] = {
    "placeholder": _gate_placeholder,
    "audit": _gate_audit,
    "fake_chart": _gate_fake_chart,
    "handwritten_chart": _gate_handwritten_chart,
    "broken_table": _gate_no_table,   # 表头 / 数据行列数对不上
}


@dataclass(frozen=True)
class Injector:
    name: str
    apply: Callable[[str, str], str | None]
    gate: str = ""          # GATES 里的键；空 = 没有确定性判据能验它

    def mutate(self, text: str, donor: str) -> tuple[str, str] | None:
        """返回 (植入版, 跳过原因)。跳过原因非空时第一个元素是空串。"""
        out = self.apply(text, donor)
        if out is None or out == text:
            return ("", "植入器在这篇上不适用")
        if self.gate:
            check = GATES[self.gate]
            if check(text):
                return ("", f"干净版本身就有这个缺陷（{self.gate}）")
            if not check(out):
                return ("", f"植入没成形：确定性判据 {self.gate} 没抓到")
        return (out, "")


INJECTORS: dict[str, Injector] = {i.name: i for i in (
    Injector("duplicate_paragraph", inj_duplicate_paragraph),
    Injector("off_spine_graft", inj_off_spine_graft),
    Injector("drop_last_section", inj_drop_last_section),
    Injector("truncate_bodies", inj_truncate_bodies),
    Injector("shift_dates", inj_shift_dates),
    Injector("scramble_numbers", inj_scramble_numbers),
    Injector("swap_section_bodies", inj_swap_section_bodies),
    Injector("heading_levels", inj_heading_levels),
    Injector("double_ending", inj_double_ending),
    Injector("strip_specifics", inj_strip_specifics),
    Injector("audit_voice", inj_audit_voice, gate="audit"),
    Injector("placeholder", inj_placeholder, gate="placeholder"),
    Injector("handwrite_mermaid", inj_handwrite_mermaid, gate="handwritten_chart"),
    Injector("break_mermaid_fence", inj_break_mermaid_fence),
    Injector("chart_to_prose", inj_chart_to_prose, gate="fake_chart"),
    Injector("duplicate_chart", inj_duplicate_chart),
    Injector("drop_chart_series", inj_drop_chart_series),
    Injector("chart_to_image", inj_chart_to_image),
    Injector("drop_table_column", inj_drop_table_column, gate="broken_table"),
    Injector("invent_table_cells", inj_invent_table_cells),
    Injector("invent_statistic", inj_invent_statistic),
    Injector("strip_caveats", inj_strip_caveats),
    Injector("strip_next_steps", inj_strip_next_steps),
    Injector("heading_flood", inj_heading_flood),
    Injector("lead_in", inj_lead_in),
    Injector("fabricate_specifics", inj_fabricate_specifics),
    Injector("answer_swap", inj_answer_swap),
)}


# ============================================================== probe ===
#
# 一条 probe = 「在哪个模式下、用哪一块正文、植入哪种缺陷、期望哪一维掉分」。
# `condition` 两档见模块文档字符串。`evidence` 那一档补的东西必须**逐条对得上
# 那一维的判词里点名、而生产从不提供的证据**，不是随便多给点上下文。

@dataclass(frozen=True)
class Probe:
    mode: str
    selector: str
    injector: str
    targets: tuple[str, ...]
    condition: str = "as-deployed"
    evidence: Callable[[Subject, dict], dict[str, str]] | None = None

    @property
    def id(self) -> str:
        return f"{self.mode}/{self.selector}/{self.injector}/{self.condition}"


def _ev_facts(subject: Subject, note: dict) -> dict[str, str]:
    """把干净正文里真的写着的日期 / 数字摘成【知识库事实】块。

    这是 `_MATERIAL_USE` / `_FACTUAL_GROUNDING` 判词里点名要的那一块，
    而 `loop._evaluate` **从来没给过**（它只传 `score_context`，里面没有事实）。
    """
    facts = []
    for i, sent in enumerate(re.split(r"(?<=[。！？])", subject.text)):
        s = sent.strip()
        if len(s) > 12 and (_DATE.search(s) or _QTY.search(s)):
            facts.append(f"[F{len(facts) + 1}] {s[:120]}")
        if len(facts) >= 12:
            break
    if not facts:
        return {}
    return {"知识库事实": "\n".join(facts)}


def _ev_profile(subject: Subject, note: dict) -> dict[str, str]:
    """`style_fit` 判的是"贴合用户的个人偏好"，而偏好档案生产里也没传给打分器。"""
    return {"用户的个人偏好": "- 只写事情本身，不要旁白证据够不够\n"
                              "- 语气克制，不用套话\n- 能给结论就别给过程"}


def _ev_instruction(subject: Subject, note: dict) -> dict[str, str]:
    """`follows_prompt` / `answers_the_question` 判的是"有没有照指令做"，
    而那条指令生产里同样没传给打分器（block 模式的 context 是空的）。"""
    head = (note.get("title") or "").strip() or "这篇笔记"
    return {"用户的指令": f"围绕《{head}》这篇笔记当前这一段，按原主题把它写清楚，不要写到别的主题上去。"}


def _ev_surrounding(subject: Subject, note: dict) -> dict[str, str]:
    """`fits_context` 判的是"跟周围合不合"，而周围没给它看（计划 4.1）。"""
    content = note["content"]
    at = content.find(subject.text[:40]) if subject.text else -1
    if at < 0:
        at = len(content) // 2
    return {"这一块前面的正文": content[max(0, at - 700): at].strip() or "（笔记开头）",
            "这一块后面的正文": content[at + len(subject.text): at + len(subject.text) + 500].strip() or "（笔记结尾）"}


PROBES: tuple[Probe, ...] = (
    # ---- note 模式（7 维）
    Probe("note", "whole", "duplicate_paragraph", ("non_repetition",)),
    Probe("note", "whole-with-spine", "off_spine_graft", ("spine_fidelity",)),
    Probe("note", "whole-with-beats", "drop_last_section", ("beat_coverage",)),
    Probe("note", "whole", "shift_dates", ("factual_grounding",)),
    Probe("note", "whole", "shift_dates", ("factual_grounding",),
          condition="with-evidence", evidence=_ev_facts),
    Probe("note", "whole", "fabricate_specifics", ("factual_grounding",)),
    Probe("note", "whole", "heading_levels", ("coherence",)),
    Probe("note", "whole", "double_ending", ("coherence",)),
    Probe("note", "whole", "strip_specifics", ("material_use",)),
    Probe("note", "whole", "strip_specifics", ("material_use",),
          condition="with-evidence", evidence=_ev_facts),
    Probe("note", "whole", "audit_voice", ("style_fit",)),
    Probe("note", "whole", "audit_voice", ("style_fit",),
          condition="with-evidence", evidence=_ev_profile),
    Probe("note", "whole", "placeholder", ("factual_grounding",)),
    # ---- section 模式（另外 2 维）
    Probe("section", "whole-section", "swap_section_bodies", ("topic_fidelity",)),
    Probe("section", "whole-section", "off_spine_graft", ("topic_fidelity",)),
    Probe("section", "whole-section", "truncate_bodies", ("section_coverage",)),
    # ---- eda 模式（7 维）
    Probe("eda", "numeric-block", "invent_statistic", ("numbers_from_tools",)),
    Probe("eda", "numeric-block", "scramble_numbers", ("numbers_from_tools",)),
    Probe("eda", "numeric-block", "strip_caveats", ("honest_caveats",)),
    Probe("eda", "chart-block", "chart_to_prose", ("has_charts",)),
    Probe("eda", "chart-block", "duplicate_chart", ("no_duplicate_charts",)),
    Probe("eda", "chart-block", "drop_chart_series", ("covers_the_data",)),
    Probe("eda", "numeric-block", "strip_next_steps", ("actionable",)),
    Probe("eda", "numeric-block", "heading_flood", ("fits_context",)),
    Probe("eda", "numeric-block", "heading_flood", ("fits_context",),
          condition="with-evidence", evidence=_ev_surrounding),
    # ---- chart 模式（4 维）
    Probe("chart", "chart-block", "break_mermaid_fence", ("chart_validity",)),
    Probe("chart", "chart-block", "handwrite_mermaid", ("chart_validity",)),
    Probe("chart", "chart-block", "chart_to_image", ("right_kind",)),
    Probe("chart", "chart-block", "shift_dates", ("data_grounding",)),
    # ---- table 模式（table_validity）
    Probe("table", "table-block", "drop_table_column", ("table_validity",)),
    Probe("table", "table-block", "invent_table_cells", ("data_grounding",)),
    # ---- analysis 模式（answers_the_question / states_limits）
    Probe("analysis", "numeric-block", "answer_swap", ("answers_the_question",)),
    Probe("analysis", "numeric-block", "answer_swap", ("answers_the_question",),
          condition="with-evidence", evidence=_ev_instruction),
    Probe("analysis", "numeric-block", "strip_caveats", ("states_limits",)),
    # ---- prompt / custom 模式（follows_prompt / no_fabrication / replaces_cleanly）
    Probe("prompt", "paragraph", "answer_swap", ("follows_prompt",)),
    Probe("prompt", "paragraph", "answer_swap", ("follows_prompt",),
          condition="with-evidence", evidence=_ev_instruction),
    Probe("prompt", "paragraph", "fabricate_specifics", ("no_fabrication",)),
    Probe("custom", "paragraph", "lead_in", ("replaces_cleanly",)),
)


def mode_dims(mode_key: str) -> list:
    """这个模式在生产里真正会用的维度（长文两条要过 `for_run`）。"""
    from app.harness import modes
    m = {x.key: x for x in modes.ALL}[mode_key]
    return list(modes.for_run(m, has_profile=True, polish=False).dims)


def covered_dimensions() -> dict[str, list[str]]:
    """每个维度被哪几条 probe 盯着——用来证明 25 维一条不落。"""
    out: dict[str, list[str]] = {}
    for p in PROBES:
        for t in p.targets:
            out.setdefault(t, []).append(p.id)
    return out


# ============================================================== 跑 ===

def log_line(obj: dict) -> None:
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_log(path: Path = LOG_PATH) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def cell_key(note_id: str, probe_id: str, arm: str, rep: int) -> str:
    return f"{note_id}|{probe_id}|{arm}|{rep}"


@dataclass
class Task:
    key: str
    note_id: str
    probe_id: str
    arm: str                    # "clean" / "dirty"
    rep: int
    mode: str
    text: str
    context: dict[str, str]


def build_tasks(notes: list[dict], probes: tuple[Probe, ...], repeats: int,
                done: set[str]) -> tuple[list[Task], list[dict]]:
    """纯函数：语料 × probe × 重复 → 还没跑的格子，外加一串 skipped 记录。"""
    tasks: list[Task] = []
    skips: list[dict] = []
    for idx, note in enumerate(notes):
        donor = notes[(idx + 1) % len(notes)]["content"] if len(notes) > 1 else ""
        for probe in probes:
            subject = SELECTORS[probe.selector](note)
            if subject is None:
                skips.append({"note": note["id"], "probe": probe.id,
                              "skipped": f"取不到 {probe.selector} 这一块"})
                continue
            inj = INJECTORS[probe.injector]
            dirty, why = inj.mutate(subject.text, donor)
            if why:
                skips.append({"note": note["id"], "probe": probe.id, "skipped": why})
                continue
            ctx = dict(subject.context)
            if probe.evidence:
                extra = probe.evidence(subject, note)
                if not extra:
                    skips.append({"note": note["id"], "probe": probe.id,
                                  "skipped": "这篇上拼不出 with-evidence 要的那块证据"})
                    continue
                ctx.update(extra)
            for rep in range(repeats):
                for arm, text in (("clean", subject.text), ("dirty", dirty)):
                    key = cell_key(note["id"], probe.id, arm, rep)
                    if key in done:
                        continue
                    tasks.append(Task(key, note["id"], probe.id, arm, rep,
                                      probe.mode, text, ctx))
    return tasks, skips


async def run_one(task: Task) -> dict:
    from app.harness import adapter
    from app.harness.checks.rubric import ScoreParseError, evaluate
    dims = mode_dims(task.mode)
    t0 = time.monotonic()
    try:
        ev = await evaluate(adapter.AppLLMClient(), content=task.text,
                            dimensions=dims, context=task.context)
        scores = {k: v.level for k, v in ev.scores.items()}
        rec = {"key": task.key, "note": task.note_id, "probe": task.probe_id,
               "arm": task.arm, "rep": task.rep, "scores": scores,
               "status": ev.status, "ms": int((time.monotonic() - t0) * 1000)}
    except ScoreParseError as exc:
        # **没打上分 ≠ 打了 0 分**（批 3 的 1.7）。这一格作废，不进统计。
        rec = {"key": task.key, "note": task.note_id, "probe": task.probe_id,
               "arm": task.arm, "rep": task.rep, "error": f"ScoreParseError: {exc}"}
    except Exception as exc:                            # noqa: BLE001
        rec = {"key": task.key, "note": task.note_id, "probe": task.probe_id,
               "arm": task.arm, "rep": task.rep, "error": f"{type(exc).__name__}: {exc}"}
    log_line(rec)
    return rec


async def run_tasks(tasks: list[Task], *, concurrency: int, deadline: float) -> int:
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def guarded(t: Task) -> None:
        nonlocal done
        if time.monotonic() > deadline:
            return
        async with sem:
            rec = await run_one(t)
            done += 1
            mark = "!" if rec.get("error") else "."
            print(mark, end="", flush=True)

    # 分批 await，好让时间预算到点就停，不必等所有协程都排完
    batch = concurrency * 4
    for i in range(0, len(tasks), batch):
        if time.monotonic() > deadline:
            break
        await asyncio.gather(*(guarded(t) for t in tasks[i: i + batch]))
        print(f" [{min(i + batch, len(tasks))}/{len(tasks)}]", flush=True)
    return done


# ============================================================== 统计 ===

# 掉一个整档（2→1 或 1→0）算抓住。三档制下 0.5 = 一半的配对掉了一整档；
# 判据宁可窄一点：0 < drop < 0.5 记成"只动了一点"，不算抓住。
CAUGHT = 0.5
# 干净版本身低于这个分，就没法从"植入后没掉"推出"判据废了"——它更可能是
# 这一维在这份语料上本来就判不出好坏（条件没出现）。**这正是 1.6 要分开的
# 两件事**，所以它单独成一档，不许混进"没抓住"。
LOW_BASELINE = 1.0


def _verdict(clean: float, drop: float) -> str:
    """一格的结论。顺序本身是判据的一部分，改动要连着下面几条用例一起读。"""
    if drop <= -CAUGHT:
        # 植入缺陷之后**反而涨了**。这比"没抓住"严重：不是看不见，是看反了。
        return "反着来了"
    if clean <= 0.0:
        return "无从判断"                 # 干净版就已经垫底，没有下降空间
    if drop >= CAUGHT:
        return "抓住"
    if clean < LOW_BASELINE:
        return "基线偏低"
    return "只动了一点" if drop > 0 else "没抓住"


def summarize(records: list[dict], probes: tuple[Probe, ...] = PROBES) -> list[dict]:
    """纯函数：日志行 → 每条 probe 每个目标维度一行灵敏度。"""
    by: dict[tuple[str, str], dict[str, list[int]]] = {}
    for r in records:
        if r.get("error") or "scores" not in r:
            continue
        slot = by.setdefault((r["probe"], r["note"]), {})
        for dim, lvl in r["scores"].items():
            slot.setdefault(f"{r['arm']}:{dim}", []).append(int(lvl))

    index = {p.id: p for p in probes}
    out: list[dict] = []
    for probe_id, probe in index.items():
        for dim in probe.targets:
            cleans: list[float] = []
            dirties: list[float] = []
            notes_used = []
            for (pid, note_id), slot in by.items():
                if pid != probe_id:
                    continue
                c = slot.get(f"clean:{dim}") or []
                d = slot.get(f"dirty:{dim}") or []
                if not c or not d:
                    continue
                cleans.append(statistics.fmean(c))
                dirties.append(statistics.fmean(d))
                notes_used.append(note_id)
            if not cleans:
                out.append({"probe": probe_id, "dim": dim, "verdict": "未跑",
                            "n_notes": 0, "clean": None, "dirty": None, "drop": None})
                continue
            clean = statistics.fmean(cleans)
            dirty = statistics.fmean(dirties)
            drop = clean - dirty
            verdict = _verdict(clean, drop)
            out.append({"probe": probe_id, "dim": dim, "verdict": verdict,
                        "n_notes": len(cleans), "clean": round(clean, 2),
                        "dirty": round(dirty, 2), "drop": round(drop, 2),
                        "notes": notes_used})
    return out


# 一维的最终结论 = 它**最好**的那一条 probe 的结论。一条 probe 抓住了，
# 这一维就不算不合格——剩下几条说明的是那种缺陷 / 那个条件的问题。
VERDICT_RANK = ("抓住", "只动了一点", "基线偏低", "无从判断", "未跑", "没抓住", "反着来了")


def roll_up(rows: list[dict]) -> list[dict]:
    """纯函数：每条 probe 一行 → **每个维度一行**。这才是 1.6 要交的那张表。

    「只动了一点」这一档要连着掉分一起读：`material_use` 掉 0.07 和
    `follows_prompt` 掉 0.33 都落在这一档里，前者等于噪声。所以这里把
    最好那条 probe 的掉分也带出来，不让一个档位名字把两种情况抹平。
    """
    best: dict[str, dict] = {}
    for r in rows:
        cur = best.get(r["dim"])
        if cur is None or VERDICT_RANK.index(r["verdict"]) < VERDICT_RANK.index(cur["verdict"]):
            best[r["dim"]] = r
        elif r["verdict"] == cur["verdict"] and (r.get("drop") or -9) > (cur.get("drop") or -9):
            best[r["dim"]] = r
    return [best[k] for k in sorted(best)]


def collateral(records: list[dict], probes: tuple[Probe, ...] = PROBES) -> list[dict]:
    """顺带掉分的维度——「判据宁可窄一点，误伤比漏报贵」那条要看的就是这个。"""
    index = {p.id: p for p in probes}
    agg: dict[tuple[str, str], list[float]] = {}
    by: dict[tuple[str, str, str], list[int]] = {}
    for r in records:
        if r.get("error") or "scores" not in r:
            continue
        for dim, lvl in r["scores"].items():
            by.setdefault((r["probe"], r["arm"], dim), []).append(int(lvl))
    for (pid, arm, dim), vals in by.items():
        if arm != "clean":
            continue
        d = by.get((pid, "dirty", dim))
        if not d:
            continue
        probe = index.get(pid)
        if not probe or dim in probe.targets:
            continue
        agg[(pid, dim)] = [statistics.fmean(vals), statistics.fmean(d)]
    out = []
    for (pid, dim), (c, d) in agg.items():
        if c - d >= CAUGHT:
            out.append({"probe": pid, "dim": dim, "clean": round(c, 2),
                        "dirty": round(d, 2), "drop": round(c - d, 2)})
    return sorted(out, key=lambda r: -r["drop"])


def render_report(rows: list[dict], side: list[dict], used: list[dict],
                  dropped: list[dict], skips: list[dict], kept_total: int = 0) -> str:
    lines = ["# 维度灵敏度（植入已知缺陷）", "",
             f"生成：{datetime.now().isoformat(timespec='seconds')}", "",
             "## 语料", "",
             f"- 跑过 harness 的笔记里，筛掉夹具后留下 **{kept_total or len(used)}** 篇、"
             f"排掉 **{len(dropped)}** 篇；本次实际参与 **{len(used)}** 篇", ""]
    for d in dropped:
        lines.append(f"  - `{d['id']}` {d.get('user_id','')}：{d['reason']}")
    lines += ["", f"- 实际参与：{'、'.join('`' + k['id'] + '`' for k in used)}", "",
              "## 灵敏度", "",
              "| 维度 | probe | 条件 | 干净 | 植入 | 掉分 | 篇 | 结论 |",
              "|---|---|---|---:|---:|---:|---:|---|"]
    for r in sorted(rows, key=lambda x: (x["verdict"] != "没抓住", x["dim"])):
        pid = r["probe"].split("/")
        cond = pid[-1]
        lines.append(
            f"| `{r['dim']}` | {pid[0]}/{pid[2]} | {cond} | "
            f"{'' if r['clean'] is None else r['clean']} | "
            f"{'' if r['dirty'] is None else r['dirty']} | "
            f"{'' if r['drop'] is None else r['drop']} | {r['n_notes']} | {r['verdict']} |")
    rolled = roll_up(rows)
    lines += ["", "## 每一维的最终结论（取它最好的那条 probe）", "",
              "| 维度 | 最好的 probe | 干净 | 植入 | 掉分 | 篇 | 结论 |",
              "|---|---|---:|---:|---:|---:|---|"]
    for r in sorted(rolled, key=lambda x: (VERDICT_RANK.index(x["verdict"]), x["dim"])):
        pid = r["probe"].split("/")
        lines.append(
            f"| `{r['dim']}` | {pid[0]}/{pid[2]}·{pid[-1]} | "
            f"{'' if r['clean'] is None else r['clean']} | "
            f"{'' if r['dirty'] is None else r['dirty']} | "
            f"{'' if r['drop'] is None else r['drop']} | {r['n_notes']} | {r['verdict']} |")

    def _only(name: str) -> str:
        dims = sorted(r["dim"] for r in rolled if r["verdict"] == name)
        return ("- " + "\n- ".join(f"`{d}`" for d in dims)) if dims else "（无）"

    lines += ["", "## 结论", "",
              "**抓不住自己该抓的东西**（干净版分数正常、植入缺陷后一分不掉）：", "",
              _only("没抓住"), "",
              "**反着来了**（植入缺陷之后分数反而涨）：", "",
              _only("反着来了"), "",
              "**条件从不出现**（干净版就已经 0 分，判据要的证据打分器根本拿不到）：", "",
              _only("无从判断"), "",
              "**基线偏低、判不出来**（这份语料上这一维本来就分不出好坏）：", "",
              _only("基线偏低"), "",
              "**只动了一点**（掉分小于半档；掉 0.1 以下的等于噪声，要连着上表的掉分一起看）：", "",
              _only("只动了一点"), "",
              "**抓住**：", "", _only("抓住"), ""]
    if side:
        lines += ["## 顺带掉分（误伤 / 维度之间不独立）", "",
                  "| probe | 被顺带打低的维度 | 干净 | 植入 | 掉分 |", "|---|---|---:|---:|---:|"]
        for r in side:
            lines.append(f"| {r['probe']} | `{r['dim']}` | {r['clean']} | {r['dirty']} | {r['drop']} |")
        lines.append("")
    if skips:
        lines += ["## 跳过的格子", "", "| 笔记 | probe | 原因 |", "|---|---|---|"]
        for s in skips:
            lines.append(f"| `{s['note']}` | {s['probe']} | {s['skipped']} |")
    return "\n".join(lines) + "\n"


# =============================================================== main ===

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notes", type=int, default=2, help="参与的真实笔记篇数（按长度取前 N）")
    ap.add_argument("--repeats", type=int, default=3, help="每格重复几次（打分有噪声）")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--time-budget-seconds", type=float, default=500)
    ap.add_argument("--only", default="", help="只跑 probe id 里含这个子串的")
    ap.add_argument("--report", action="store_true", help="只读日志出表，不发调用")
    ap.add_argument("--coverage", action="store_true", help="打印 25 维的覆盖检查后退出")
    args = ap.parse_args()

    from app.harness import modes
    from app.util import llm as _llm

    all_dims = {d.name for m in modes.ALL
                for d in modes.for_run(m, has_profile=True, polish=False).dims}
    cov = covered_dimensions()
    if args.coverage:
        print(f"模式里一共 {len(all_dims)} 个维度，probe 覆盖 {len(set(cov) & all_dims)} 个")
        for d in sorted(all_dims):
            print(f"  {'✅' if d in cov else '❌'} {d}: {len(cov.get(d, []))} 条 probe")
        extra = sorted(set(cov) - all_dims)
        if extra:
            print(f"  probe 盯着不存在的维度：{extra}")
        return

    kept, dropped = load_corpus()
    print(f"语料：留下 {len(kept)} 篇、排掉 {len(dropped)} 篇", flush=True)
    for d in dropped:
        print(f"  排掉 {d['id']} ({d['user_id']})：{d['reason']}", flush=True)
    notes = choose_notes(kept, args.notes)
    if not notes:
        print("没有可用语料", flush=True)
        return
    print(f"参与：{', '.join(n['id'] + '(' + str(len(n['content'])) + '字)' for n in notes)}", flush=True)

    probes = tuple(p for p in PROBES if args.only in p.id)
    records = read_log()
    done = {r["key"] for r in records if "key" in r and not r.get("error")}
    tasks, skips = build_tasks(notes, probes, args.repeats, done)
    print(f"待跑 {len(tasks)} 格（已完成 {len(done)}），跳过 {len(skips)} 条 probe×篇", flush=True)

    if not args.report and tasks:
        _llm.ctx_user.set("sensitivity-bench")
        _llm.ctx_feature.set("bench/sensitivity")
        deadline = time.monotonic() + args.time_budget_seconds
        ran = asyncio.run(run_tasks(tasks, concurrency=args.concurrency, deadline=deadline))
        print(f"\n本次跑了 {ran} 格", flush=True)
        records = read_log()

    rows = summarize(records, probes)
    side = collateral(records, probes)
    report = render_report(rows, side, notes, dropped, skips, kept_total=len(kept))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{datetime.now().strftime('%m%d-%H%M%S')}-sensitivity.md"
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"→ {out}", flush=True)


if __name__ == "__main__":
    main()
