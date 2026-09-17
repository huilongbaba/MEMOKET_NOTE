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
* `as-deployed`：跟生产里 `loop._evaluate` 一模一样的上下文。**这一档由生产
  代码自己拼**（`production_context()` 调 `app.harness.score_context`），
  不是脚本里硬编一份跟着抄——抄的那份跟生产同步全靠人记得改。
* `with-evidence`：额外把那一维的判词里**明确提到、而生产至今仍然不给**的
  证据塞进 context。批 8 之后这一档只剩 `style_fit` 的个人偏好一项。

同一个缺陷在两种条件下的差值，就是「判据废了」和「条件没出现」的分界线。

**批 8 把三样证据从 `with-evidence` 搬进了生产**（事实块 / block 的前后文 /
用户那条指令，计划 4.1）。于是那几行的对照关系变成：
**批 7 的 `with-evidence` 行 ⇄ 批 8 的 `as-deployed` 行**。三条 `with-evidence`
probe 因此删掉了——留着就是同一份上下文跑两遍。

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
2. **语料先按血缘分成三类，只留 `user` 那一类**（批 4 + 批 6，判据在
   `corpus_lineage.py`，所有测量脚本共用一份）。批 4 是夹具用户：`shot-perf`
   一个人 413 篇合成笔记、一篇 47k 字探针是 100 个逐字相同的小节。
   批 6 更阴：6 篇「干净语料」出自同一次 `soak.py` 压测，而 soak 是**拿真实
   user_id 跑的**——按 user_id / 标题筛一篇都挡不住，只有血缘判
   （`writing_sections` → plan → parent 标题 `soak-*`）能认出来。
   去掉那 3 篇重算，**批 5 有 4 条结论直接翻转**。
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
import hashlib
import json
import random
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus_lineage  # noqa: E402  （语料血缘判据，所有测量脚本共用这一份）
from app.harness import score_context  # noqa: E402  （as-deployed 那一档由生产代码自己拼）

ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "dimension_sensitivity_log.jsonl"
OUT_DIR = ROOT / "sensitivity_results"
DB_PATH = ROOT.parent / "data" / "notes.sqlite3"


# =========================================================== 语料筛选 ===
#
# 判据整个搬进 `corpus_lineage.py`，**所有测量脚本共用那一份**。
# 这里只留「太短」这一条 bench 自己的条件。
#
# 为什么不再在这里写 `FIXTURE_USERS`：批 6 就是栽在这上面——脚本各写一份
# 名单，而 `soak.py` 是**拿真实 user_id 跑的**，任何按 user_id / 标题的名单
# 都挡不住它。血缘判（`writing_sections` → plan → parent 标题 `soak-*`）
# 是唯一一条能穿透真实 user_id 的线索，它必须只有一份实现。

# 太短的产出上植入不了几种缺陷（没有第二节可删、没有第二段可复制），
# 而且短文本上一次打分的方差最大。
MIN_CHARS = 600


def select_corpus(rows: list[dict], lineage: dict[str, corpus_lineage.Lineage] | None = None,
                  *, min_chars: int = MIN_CHARS) -> tuple[list[dict], list[dict]]:
    """纯函数：`(id, user_id, title, content, spine, beats)` 行 → 留下的 / 排掉的。

    留下的**只有 `user` 那一类**：脚本跑出来的（`script`）形态是真的但分布不是，
    合成夹具（`fixture`）连模型都没过。三类的定义见 `corpus_lineage` 的模块文档。

    `dropped` 每项带 `reason`——**排掉了什么必须能报出来**，
    批 4 / 批 6 的问题都是「语料脏」这件事本身没有任何地方看得见。
    """
    kept: list[dict] = []
    dropped: list[dict] = []
    for row in corpus_lineage.annotate(rows, lineage or {}):
        reason = row["origin_reason"]
        if not reason and len((row.get("content") or "")) < min_chars:
            reason = f"太短（{len(row.get('content') or '')} < {min_chars} 字）"
            row = {**row, "origin": "too-short"}
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
        lineage = corpus_lineage.load_lineage(conn)
        # key 是 note_id，block 模式带 `<mode>:` 前缀（见 store.py 的注释）
        ids = {r["key"].split(":")[-1] for r in conn.execute("SELECT DISTINCT key FROM harness_runs")}
        rows = [dict(r) for r in conn.execute(
            "SELECT id, user_id, title, content, spine, beats FROM notes") if r["id"] in ids]
    finally:
        conn.close()
    return select_corpus(rows, lineage)


# =============================================================== 取材 ===
#
# 长文两条 harness 判的是整篇，六个 block 模式判的是**插进笔记里的一块**。
# 所以 block 那几个不能拿整篇去打分——从真实笔记里取出真实的那一块。
# 取不到就返回 None（这一条 probe 在这篇上跳过），**不合成假语料**。

_PARA_SPLIT = re.compile(r"\n\s*\n")
_HEADING = re.compile(r"(?m)^(#{1,6})\s+(.*)$")
_MERMAID = re.compile(r"```mermaid\n.*?```", re.S)
# 末尾那一行后面可能**没有换行**（表格就在正文结尾）。上一版写死 `\n`，
# 于是 `603dca25403a` 那张真实的表**最后一行整行落在匹配之外**——
# `drop_table_column` / `invent_table_cells` 都只改到了半张表，
# `table_column_mismatch` 也只数了半张。批 7 的成对自验才把它顶出来。
_TABLE_BLOCK = re.compile(r"(?m)^(\|.*\|[ \t]*(?:\n|$)){2,}")


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


def pick_chart_narrated(note: dict) -> Subject | None:
    """带**叙述**的图块：图 + 它前面那几段真实正文，而且那几段里至少点了一个节点的名。

    `covers_the_data` 判的是「句子里提到的分组要画全」——**没有句子提到它，
    这一维就没东西可判**（批 6 ③：上一版三篇正文没有一篇提过被删的节点，
    打分器判 2.0 是对的）。所以这个取材器只认「正文真的点过名」的图块，
    找不到就返回 None，**不合成一句引子出来**。
    """
    text = note["content"]
    m = _MERMAID.search(text)
    if not m:
        return None
    head = paragraphs(text[: m.start()])
    for back in range(1, min(6, len(head)) + 1):
        lead = "\n\n".join(head[-back:]).strip()
        block = (lead + "\n\n" + m.group(0).strip()).strip()
        if mentioned_nodes(block):
            return Subject(block)
    return None


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
    "chart-block-narrated": pick_chart_narrated,
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
    # `replace(tail, ..., 1)` 换的是**第一次**出现。`06647b9c2031` 那篇里
    # 最后一段的文字在正文中段也出现过，于是复制品被塞进了别人的段落中间，
    # 拼成一段四不像——「复制了一整段」这句话就不成立了。按最后一次出现插。
    at = text.rfind(tail)
    return text[:at] + src + "\n\n" + text[at:]


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
_DIGIT = re.compile(r"\d")
_FENCE_LINE = re.compile(r"^\s{0,3}```")
_HEADING_LINE = re.compile(r"^\s{0,3}#{1,6}\s")
_TABLE_LINE = re.compile(r"^\s{0,3}\|")


def strip_sentences(text: str, hit: Callable[[str], bool],
                    heading_hit: Callable[[str], bool] | None = None) -> str:
    """逐**行**走，把 `hit` 命中的句子剔掉。围栏块 / 表格块整块处理。

    **为什么不按段落走**（批 6 的驳回理由 ②，我复现过）：
    上一版按 `\n\n` 切段，然后「以 `#` 或 `|` 开头、或含 ``` 的段整段留下」。
    而真实笔记里**标题和正文常常不隔空行**，于是「## 时间线\n4 月 16 日……」
    整节被当成「标题段」原样保留；mermaid 围栏那一段更是整张带 5 个日期的
    时间线原封不动。实测残留率 25%（`06647b9c2031` / `574f4ff29956` 两篇），
    「把带数字的句子全剔光」这句话当时**是假的**。

    现在的规矩：
    * 围栏块（```…```）和连续的表格行**整块删掉**——块里只要有一处命中就整块走。
      删半张表会让列数对不上，那是另一种缺陷，不能混进来。
    * 标题行按 `heading_hit` 判（默认跟正文同一条）。标题是结构不是材料，
      所以 `strip_specifics` 那边只在标题**带数字**时才删它。
    * 其余每一行按「。！？」切句，逐句筛。
    """
    heading_hit = heading_hit or hit
    lines = (text or "").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE_LINE.match(line):
            j = i + 1
            while j < len(lines) and not _FENCE_LINE.match(lines[j]):
                j += 1
            block = lines[i: min(j + 1, len(lines))]
            if not any(hit(x) for x in block):
                out.extend(block)
            i = j + 1
            continue
        if _TABLE_LINE.match(line):
            j = i
            while j < len(lines) and _TABLE_LINE.match(lines[j]):
                j += 1
            block = lines[i:j]
            if not any(hit(x) for x in block):
                out.extend(block)
            i = j
            continue
        if _HEADING_LINE.match(line):
            if not heading_hit(line):
                out.append(line)
            i += 1
            continue
        kept = "".join(x for x in re.split(r"(?<=[。！？])", line)
                       if x.strip() and not hit(x))
        if kept.strip():
            out.append(kept)
        i += 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def has_specific_material(text: str) -> bool:
    """正文里还剩不剩「带数字 / 外文名」的具体材料——`strip_specifics` 的自验闸。

    标题行只看数字：标题是结构不是材料（实测 5 篇真实用户笔记里**没有一个标题
    带数字**，`## APP定义` 这类外文词是栏目名不是材料）。
    """
    for line in (text or "").splitlines():
        if _HEADING_LINE.match(line):
            if _DIGIT.search(line):
                return True
            continue
        if _SPECIFIC.search(line):
            return True
    return False


def inj_strip_specifics(text: str, donor: str) -> str | None:
    """把所有带数字 / 外文名的句子删掉——只剩谁都能写的通用内容。→ material_use"""
    new = strip_sentences(text, lambda x: bool(_SPECIFIC.search(x)),
                          heading_hit=lambda x: bool(_DIGIT.search(x)))
    # 没删掉多少就等于没植入——宁可跳过，也不要拿一个没成形的缺陷去下结论
    if not new or len(new) > len(text) * 0.6:
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


_NODE = re.compile(r"([A-Za-z][A-Za-z0-9_]*)\s*[\[(\{]([^\]\)\}]+)[\]\)\}]")


def _squash(s: str) -> str:
    """比对节点标签和正文时去掉空白：图里写 `6月15日 10台到货`，
    正文写「6 月 15 日 10 台到货」，中间的空格是排版不是内容。"""
    return re.sub(r"\s+", "", s or "")


def chart_nodes(chart: str) -> dict[str, str]:
    """mermaid 里 `ID[标签]` 的所有节点。同一个 ID 出现多次取第一次的标签。"""
    out: dict[str, str] = {}
    for m in _NODE.finditer(chart or ""):
        out.setdefault(m.group(1), m.group(2).strip())
    return out


def mentioned_nodes(text: str) -> list[tuple[str, str]]:
    """图里有、**而且正文里点了名**的节点（按标签长度从长到短）。"""
    m = _MERMAID.search(text or "")
    if not m:
        return []
    prose = _squash(text[: m.start()] + text[m.end():])
    hits = [(nid, label) for nid, label in chart_nodes(m.group(0)).items()
            if len(_squash(label)) >= 4 and _squash(label) in prose]
    return sorted(hits, key=lambda x: -len(x[1]))


def subject_missing_from_chart(clean: str, dirty: str) -> bool:
    """**成对**判：正文点了名、干净版图里画了、植入版图里没了。

    `covers_the_data` 的判词原话就是这个形状——「the groups mentioned in the
    sentence must all be plotted — **the subject of the sentence is missing**」。

    上一版植入器（`drop_chart_series`，删掉图里第一条边）造不出这个缺陷：
    批 6 自验发现**三篇正文里没有一篇提到过被删的那个节点**，
    打分器判 2.0 是对的，根本没东西可抓。这条闸就是钉住那次驳回。
    """
    mc, md = _MERMAID.search(clean or ""), _MERMAID.search(dirty or "")
    if not mc or not md:
        return False
    dirty_prose = _squash((dirty or "")[: md.start()] + (dirty or "")[md.end():])
    dirty_chart = _squash(md.group(0))
    for _nid, label in mentioned_nodes(clean or ""):
        lab = _squash(label)
        if lab in dirty_prose and lab not in dirty_chart:
            return True
    return False


def inj_drop_mentioned_node(text: str, donor: str) -> str | None:
    """把**正文点了名的那个**节点从图里删掉。→ covers_the_data

    跟上一版的区别就是选谁：上一版删第一条边，删掉的节点正文根本没提过，
    于是「句子的主语在图里缺了」这个缺陷从来没被造出来（批 6 ③）。
    这一版只删「标签在正文里逐字出现过」的节点，正文一个字不动。
    """
    m = _MERMAID.search(text)
    if not m:
        return None
    hits = mentioned_nodes(text)
    if not hits:
        return None
    chart = m.group(0)
    edges = [l for l in chart.splitlines() if "-->" in l or "---" in l]
    if len(edges) < 2:
        return None
    for nid, label in hits:
        kept, removed = [], 0
        for line in chart.splitlines():
            # 整行提到这个节点（ID 或标签）就删掉——留半条边会画不出来，
            # 那是「图坏了」不是「图漏了一个主角」，两种缺陷不能混。
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(nid)}(?![A-Za-z0-9_])", line) \
                    or _squash(label) in _squash(line):
                removed += 1
                continue
            kept.append(line)
        if not removed or len(kept) < 3:
            continue
        new_chart = "\n".join(kept)
        if not new_chart.rstrip().endswith("```"):
            new_chart = new_chart.rstrip() + "\n```"
        if _squash(label) in _squash(new_chart):
            continue
        return text[: m.start()] + new_chart + text[m.end():]
    return None


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


ASSERTION_SENTENCE = "这三组数据已经足以证明趋势成立，不存在其他解释。"


def has_hedge(text: str) -> bool:
    """还剩不剩保留措辞——`strip_caveats` 的自验闸。"""
    return bool(_HEDGE.search(text or ""))


def inj_strip_caveats(text: str, donor: str) -> str | None:
    """删掉所有带保留措辞的句子，再补一句断言。→ honest_caveats / states_limits

    跟 `strip_specifics` 同一条教训：按行走、围栏和表格整块处理，
    不再让「以 # 或 | 开头的段」原样直通（那会把保留措辞留在正文里，
    然后拿一个没成形的缺陷去说维度不灵敏）。
    """
    new = strip_sentences(text, has_hedge)
    if not new or len(new) > len(text) * 0.97:
        return None
    return new + "\n\n" + ASSERTION_SENTENCE + "\n"


_ACTION = re.compile(r"(下一步|接下来|应|需要|建议|值得|应当)")


def has_next_step(text: str) -> bool:
    """还剩不剩「接下来该做什么」——`strip_next_steps` 的自验闸。"""
    return bool(_ACTION.search(text or ""))


def inj_strip_next_steps(text: str, donor: str) -> str | None:
    """删掉所有"接下来该做什么"的句子。→ actionable（同上，按行走）"""
    new = strip_sentences(text, has_next_step)
    if not new or len(new) > len(text) * 0.97:
        return None
    return new + "\n"


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


# ------------------------------------------- 每个植入器的成对自验 verify ---
#
# **批 6 ⑤ 逼出来的**：27 个植入器里 13 个没有任何闸，审查把
# `inj_drop_chart_series` 换成**恒等函数**（什么都不植入），44 条单测**全绿存活**。
# 植入器是整张灵敏度表的承重墙——它要是没植入声称的那个缺陷，
# 表上每一行都是空的，而且**看不出任何症状**。
#
# 所以现在每个植入器都必须有一条判据，形式两种之一：
#   * `gate`：单边判据（干净版必须判不出、植入版必须判得出），复用 `checks/` 里现成的；
#   * `verify(clean, dirty, donor) -> bool`：成对判据，写"这次植入到底改了什么"。
# 两个都没有的植入器**根本注册不进来**（`Injector.__post_init__` 直接抛）。

def _para_counts(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in paragraphs(text):
        out[x.strip()] = out.get(x.strip(), 0) + 1
    return out


def _v_duplicate_paragraph(clean: str, dirty: str, donor: str) -> bool:
    """有一段长文本在干净版里出现一次、在植入版里出现两次（逐字）。"""
    before, after = _para_counts(clean), _para_counts(dirty)
    return any(len(k) >= 120 and after.get(k, 0) > v for k, v in before.items())


def _v_off_spine_graft(clean: str, dirty: str, donor: str) -> bool:
    """植入版多出来的那两段逐字来自 donor，而干净版里没有。"""
    dps = [x for x in paragraphs(donor) if len(x) > 150 and not x.startswith("#")][:2]
    return bool(dps) and all(x in dirty and x not in clean for x in dps)


def _v_drop_last_section(clean: str, dirty: str, donor: str) -> bool:
    """少了一个 `##` 小节，而且连正文一起少（只删标题不算）。"""
    before = [x for x in sections(clean) if x[0]]
    after = [x for x in sections(dirty) if x[0]]
    if len(after) != len(before) - 1:
        return False
    head, body = before[-1]
    return head not in dirty and (body.strip()[:60] not in dirty if body.strip() else True)


def _v_truncate_bodies(clean: str, dirty: str, donor: str) -> bool:
    """标题一个不少，正文明显变短。"""
    heads_before = [h for h, _ in sections(clean) if h]
    heads_after = [h for h, _ in sections(dirty) if h]
    return heads_before == heads_after and len(dirty) < len(clean) * 0.6


def _no_digits(text: str) -> str:
    return re.sub(r"\d", "", text)


def _v_shift_dates(clean: str, dirty: str, donor: str) -> bool:
    """日期变了，**别的一个字没动**（把所有数字抹掉之后两版应当几乎一样）。"""
    if _DATE.findall(clean) == _DATE.findall(dirty):
        return False
    a, b = _no_digits(clean), _no_digits(dirty)
    return len(a) and abs(len(a) - len(b)) <= len(a) * 0.02


def _v_scramble_numbers(clean: str, dirty: str, donor: str) -> bool:
    """带量词的数变了，非数字部分不动。"""
    if _QTY.findall(clean) == _QTY.findall(dirty):
        return False
    a, b = _no_digits(clean), _no_digits(dirty)
    return len(a) and abs(len(a) - len(b)) <= len(a) * 0.05


def _v_swap_section_bodies(clean: str, dirty: str, donor: str) -> bool:
    """前两节有实质正文的那两节，正文对调了（标题原地不动）。"""
    real = [x for x in sections(clean) if x[0] and len(x[1].strip()) >= 80]
    if len(real) < 2:
        return False
    (h1, b1), (h2, b2) = real[0], real[1]
    return (h1 + b2) in dirty and (h2 + b1) in dirty


def _v_heading_levels(clean: str, dirty: str, donor: str) -> bool:
    """**只**降了一个二级标题，别的标题一个没动（改多了就混进别的缺陷）。"""
    二级 = lambda t: len([m for m in _HEADING.finditer(t) if len(m.group(1)) == 2])
    四级 = lambda t: len([m for m in _HEADING.finditer(t) if len(m.group(1)) == 4])
    return 二级(dirty) == 二级(clean) - 1 and 四级(dirty) == 四级(clean) + 1 \
        and len(dirty) == len(clean) + 2


def _v_double_ending(clean: str, dirty: str, donor: str) -> bool:
    return "综上所述，" in dirty and "综上所述，" not in clean and len(dirty) > len(clean)


def _v_strip_specifics(clean: str, dirty: str, donor: str) -> bool:
    """**批 6 ② 就是这条不成立**：上一版的残留率 25%，
    「把带数字的句子全剔光」当时是假的。现在要求正文里一处具体材料都不剩。"""
    return has_specific_material(clean) and not has_specific_material(dirty)


def _v_break_mermaid_fence(clean: str, dirty: str, donor: str) -> bool:
    return dirty.count("```") == clean.count("```") - 1


def _v_duplicate_chart(clean: str, dirty: str, donor: str) -> bool:
    return dirty.count("```mermaid") == clean.count("```mermaid") + 1


def _v_drop_mentioned_node(clean: str, dirty: str, donor: str) -> bool:
    return subject_missing_from_chart(clean, dirty)


def _v_chart_to_image(clean: str, dirty: str, donor: str) -> bool:
    return dirty.count("```mermaid") == clean.count("```mermaid") - 1 \
        and bool(re.search(r"!\[[^\]]*\]\([^)]+\)", dirty))


def _v_invent_table_cells(clean: str, dirty: str, donor: str) -> bool:
    """只看**表格块内部**：引子段里出现「填写」两个字不该让这一格作废。"""
    mc, md = _TABLE_BLOCK.search(clean), _TABLE_BLOCK.search(dirty)
    return bool(mc and md) and "填写" in mc.group(0) and "填写" not in md.group(0) \
        and "842 万元" in md.group(0)


def _v_invent_statistic(clean: str, dirty: str, donor: str) -> bool:
    return "r=0.91" in dirty and "r=0.91" not in clean


def _v_strip_caveats(clean: str, dirty: str, donor: str) -> bool:
    return has_hedge(clean) and not has_hedge(dirty) and ASSERTION_SENTENCE in dirty


def _v_strip_next_steps(clean: str, dirty: str, donor: str) -> bool:
    return has_next_step(clean) and not has_next_step(dirty)


def _v_heading_flood(clean: str, dirty: str, donor: str) -> bool:
    return len(re.findall(r"(?m)^# 第 \d 部分$", dirty)) >= 2 \
        and not re.search(r"(?m)^# 第 \d 部分$", clean)


def _v_lead_in(clean: str, dirty: str, donor: str) -> bool:
    dps = [x for x in paragraphs(donor) if len(x) > 120]
    return dirty.startswith("好的，以下是修改后的版本：") and bool(dps) and dps[0] in dirty


def _v_fabricate_specifics(clean: str, dirty: str, donor: str) -> bool:
    return "HZ-2027-0409-11" in dirty and "HZ-2027-0409-11" not in clean


def _v_answer_swap(clean: str, dirty: str, donor: str) -> bool:
    """整块换成了 donor 的内容——干净版的开头在植入版里找不到。"""
    dps = [x for x in paragraphs(donor) if len(x) > 150 and not x.startswith("#")][:2]
    head = clean.strip()[:40]
    return len(dps) == 2 and all(x in dirty for x in dps) and head not in dirty


@dataclass(frozen=True)
class Injector:
    name: str
    apply: Callable[[str, str], str | None]
    gate: str = ""                  # GATES 里的键：单边判据
    verify: Callable[[str, str, str], bool] | None = None   # 成对判据

    def __post_init__(self) -> None:
        # **没有闸的植入器不许存在**（批 6 ⑤：恒等函数活过了 44 条单测）。
        # 放在构造里而不是测试里：测试只钉现在这 27 个，构造闸连以后新加的也拦得住。
        if not self.gate and self.verify is None:
            raise ValueError(f"植入器 {self.name} 没有任何自验闸——"
                             f"它要是没植入声称的缺陷，整张灵敏度表都是空的")

    def mutate(self, text: str, donor: str) -> tuple[str, str]:
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
        if self.verify is not None and not self.verify(text, out, donor):
            return ("", f"植入没成形：成对自验 {self.name} 没通过")
        return (out, "")


INJECTORS: dict[str, Injector] = {i.name: i for i in (
    Injector("duplicate_paragraph", inj_duplicate_paragraph, verify=_v_duplicate_paragraph),
    Injector("off_spine_graft", inj_off_spine_graft, verify=_v_off_spine_graft),
    Injector("drop_last_section", inj_drop_last_section, verify=_v_drop_last_section),
    Injector("truncate_bodies", inj_truncate_bodies, verify=_v_truncate_bodies),
    Injector("shift_dates", inj_shift_dates, verify=_v_shift_dates),
    Injector("scramble_numbers", inj_scramble_numbers, verify=_v_scramble_numbers),
    Injector("swap_section_bodies", inj_swap_section_bodies, verify=_v_swap_section_bodies),
    Injector("heading_levels", inj_heading_levels, verify=_v_heading_levels),
    Injector("double_ending", inj_double_ending, verify=_v_double_ending),
    Injector("strip_specifics", inj_strip_specifics, verify=_v_strip_specifics),
    Injector("audit_voice", inj_audit_voice, gate="audit"),
    Injector("placeholder", inj_placeholder, gate="placeholder"),
    Injector("handwrite_mermaid", inj_handwrite_mermaid, gate="handwritten_chart"),
    Injector("break_mermaid_fence", inj_break_mermaid_fence, verify=_v_break_mermaid_fence),
    Injector("chart_to_prose", inj_chart_to_prose, gate="fake_chart"),
    Injector("duplicate_chart", inj_duplicate_chart, verify=_v_duplicate_chart),
    Injector("drop_mentioned_node", inj_drop_mentioned_node, verify=_v_drop_mentioned_node),
    Injector("chart_to_image", inj_chart_to_image, verify=_v_chart_to_image),
    Injector("drop_table_column", inj_drop_table_column, gate="broken_table"),
    Injector("invent_table_cells", inj_invent_table_cells, verify=_v_invent_table_cells),
    Injector("invent_statistic", inj_invent_statistic, verify=_v_invent_statistic),
    Injector("strip_caveats", inj_strip_caveats, verify=_v_strip_caveats),
    Injector("strip_next_steps", inj_strip_next_steps, verify=_v_strip_next_steps),
    Injector("heading_flood", inj_heading_flood, verify=_v_heading_flood),
    Injector("lead_in", inj_lead_in, verify=_v_lead_in),
    Injector("fabricate_specifics", inj_fabricate_specifics, verify=_v_fabricate_specifics),
    Injector("answer_swap", inj_answer_swap, verify=_v_answer_swap),
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


# ------------------------------------------------- as-deployed 那一档 ---
#
# **这一档必须由生产代码自己拼**，脚本不许另写一份：批 8 之前它是脚本里
# 硬编的「长文两条给 spine/beats、六个 block 模式什么都不给」——那份硬编
# 跟生产同步全靠人记得改。现在前后文 / 指令 / 选区走
# `app.harness.score_context.for_block`、材料走 `score_context.material`，
# 跟 `loop._evaluate` 是同一份函数。生产那边的接线被撤掉，这张表会跟着变。

_BLOCK_MODES = ("eda", "chart", "table", "analysis", "prompt", "custom")

# 只有这三个模式在生产里**一定**有用户那条指令：`prompt` / `custom` 是用户
# 亲手打的，`analysis` 的 task 本身就是一个问题。其余三个（chart/table/eda）
# 用户常常什么都不打，给一句合成指令等于凭空多一个变量。
_HAS_INSTRUCTION = ("prompt", "custom", "analysis")


def derived_facts(subject: Subject) -> list[str]:
    """把干净正文里真的写着的日期 / 数字摘成这次跑的"材料"。

    **这是 `st.facts` 的替身**：bench 不跑 harness，手里没有真实检索结果，
    只能拿正文里那些带日期 / 数字的句子当作"写作那一步用过的材料"。
    对 `shift_dates` / `strip_specifics` / `invent_table_cells` 这类植入来说
    它是对的替身——植入改的正是这些句子，材料是照**干净版**摘的，
    于是"正文跟材料对不对得上"这件事真的可判。
    """
    facts: list[str] = []
    for sent in re.split(r"(?<=[。！？])", subject.text):
        s = sent.strip()
        if len(s) > 12 and (_DATE.search(s) or _QTY.search(s)):
            facts.append(f"[F{len(facts) + 1}] {s[:120]}")
        if len(facts) >= 12:
            break
    return facts


def surrounding(subject: Subject, note: dict) -> tuple[str, str]:
    """这一块在原笔记里的前后文。截多少由 `score_context` 定，这里给全的。"""
    content = note["content"]
    at = content.find(subject.text[:40]) if subject.text else -1
    if at < 0:
        at = len(content) // 2
    return content[:at], content[at + len(subject.text):]


def instruction_for(note: dict) -> str:
    head = (note.get("title") or "").strip() or "这篇笔记"
    return f"围绕《{head}》这篇笔记当前这一段，按原主题把它写清楚，不要写到别的主题上去。"


def production_context(probe: "Probe", subject: Subject, note: dict) -> dict[str, str]:
    """生产里 `loop._evaluate` 这一刻真正递给打分器的那份 context。

    三段拼起来，**每一段都走生产的那个函数**：
      ① 长文两条 harness 的 router 装的（spine / beats / 分段主题）——
         取材器已经按 router 抄好放在 `subject.context` 里；
      ② 六个 block 模式的前后文 / 指令（`score_context.for_block`，计划 4.1）；
      ③ 这次跑累积的材料（`score_context.material`）——**所有模式都有**，
         `loop._evaluate` 是不分模式拼的。

    **跟生产的两处已知差**，都记在这儿，别当成生产也这样：
    * `custom` 少了选区那一项——bench 手上没有真实的选中文本，合成一段等于
      凭空造一个变量。所以 `replaces_cleanly` 这一行比生产**保守**。
    * 材料是从正文里摘的（`derived_facts`），不是真实检索结果。
    """
    ctx = dict(subject.context)
    if probe.mode in _BLOCK_MODES:
        before, after = surrounding(subject, note)
        ctx.update(score_context.for_block(
            before=before, after=after,
            prompt=instruction_for(note) if probe.mode in _HAS_INSTRUCTION else ""))
    block = score_context.material(derived_facts(subject))
    if block:
        ctx[score_context.MATERIAL_KEY] = block
    return ctx


# ------------------------------------------------ with-evidence 那一档 ---
#
# 批 8 之后这一档只剩**生产至今仍然不给**的证据。原来挂在这儿的三样
# （事实块 / 前后文 / 用户那条指令）已经接进生产，它们的对照组
# 变成了上面那个 `production_context`——台账批 8 的前后对照就是拿
# 批 7 的 `with-evidence` 行去对批 8 的 `as-deployed` 行。

def _ev_profile(subject: Subject, note: dict) -> dict[str, str]:
    """`style_fit` 判的是"贴合用户的个人偏好"，而偏好档案生产里仍然没传给
    打分器——**没动它是有依据的**：批 7 实测这一维在补了偏好的那一臂只掉
    0.17（n=2，p=1.0），没有任何证据说明传了有用。判据宁可窄一点。"""
    return {"用户的个人偏好": "- 只写事情本身，不要旁白证据够不够\n"
                              "- 语气克制，不用套话\n- 能给结论就别给过程"}


PROBES: tuple[Probe, ...] = (
    # ---- note 模式（7 维）
    Probe("note", "whole", "duplicate_paragraph", ("non_repetition",)),
    Probe("note", "whole-with-spine", "off_spine_graft", ("spine_fidelity",)),
    Probe("note", "whole-with-beats", "drop_last_section", ("beat_coverage",)),
    Probe("note", "whole", "shift_dates", ("factual_grounding",)),
    Probe("note", "whole", "fabricate_specifics", ("factual_grounding",)),
    Probe("note", "whole", "heading_levels", ("coherence",)),
    Probe("note", "whole", "double_ending", ("coherence",)),
    Probe("note", "whole", "strip_specifics", ("material_use",)),
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
    Probe("eda", "chart-block-narrated", "drop_mentioned_node", ("covers_the_data",)),
    Probe("eda", "numeric-block", "strip_next_steps", ("actionable",)),
    Probe("eda", "numeric-block", "heading_flood", ("fits_context",)),
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
    Probe("analysis", "numeric-block", "strip_caveats", ("states_limits",)),
    # ---- prompt / custom 模式（follows_prompt / no_fabrication / replaces_cleanly）
    Probe("prompt", "paragraph", "answer_swap", ("follows_prompt",)),
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


def cell_fingerprint(text: str, context: dict[str, str]) -> str:
    """这一格**到底把什么交给了打分器**的指纹（正文 + 上下文）。"""
    blob = text + "\x00" + "\x00".join(f"{k}={v}" for k, v in sorted(context.items()))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]


def cell_key(note_id: str, probe_id: str, arm: str, rep: int,
             text: str = "", context: dict[str, str] | None = None) -> str:
    """格子的身份里**必须带正文指纹**。

    批 7 实施中撞出来的（计划里没写）：改了植入器之后断点续跑会**拿旧数据当新数据**。
    老的 key 是 `笔记|probe|arm|重复次数`——`strip_specifics` 修完之后，
    同一个 key 指向的已经是完全不同的一段正文了，而续跑那一步只看 key，
    于是「修好的植入器」和「没修的旧分数」会被拼在同一张表里，**毫无症状**。
    指纹进 key 之后，正文或上下文一变，那一格自动重跑；没变的一格钱也不白花。
    """
    return f"{note_id}|{probe_id}|{arm}|{rep}|{cell_fingerprint(text, context or {})}"


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
            ctx = production_context(probe, subject, note)
            if probe.evidence:
                extra = probe.evidence(subject, note)
                if not extra:
                    skips.append({"note": note["id"], "probe": probe.id,
                                  "skipped": "这篇上拼不出 with-evidence 要的那块证据"})
                    continue
                ctx.update(extra)
            for rep in range(repeats):
                for arm, text in (("clean", subject.text), ("dirty", dirty)):
                    key = cell_key(note["id"], probe.id, arm, rep, text, ctx)
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

# 「掉 ≥ 半档算抓住」这条线**原来是拍的**，批 6 把它量了出来：
# 拿 852 条日志做 permutation（打乱 clean/dirty 标签重算），
# **纯噪声下 |掉分| ≥ 0.5 的概率就有 10.1%**——38 条 probe 里按噪声就该有约 4 行越线。
#
# 批 7 按实测噪声重新标定：`calibrate_threshold()` 把每一行的 clean/dirty 标签
# 在**同一篇之内**打乱重算，取所有行合起来的 |掉分| 的 95 分位数当这条线。
# 下面这个数是在**只留 `user` 语料**的那份日志上算出来的（见台账批 7），
# 每次重算都会打印一遍；语料或重复次数变了就该重新标定。
CAUGHT = 0.89
# 标定用的分位数。95% = 「纯噪声下每 20 行才有 1 行能越过这条线」。
CAUGHT_QUANTILE = 0.95
# 逐行显著性。掉分够大但 p 不显著的行单独报成「掉了但不显著」——
# **判据宁可窄一点**：n=1 篇 × 3 次重复时排列总数只有 C(6,3)=20，
# 两侧 p 最小就是 0.10，**那种行在数学上不可能显著**，不能拿去当依据。
ALPHA = 0.05
PERM_RESAMPLES = 4000
PERM_SEED = 20260917

# 干净版本身低于这个分，就没法从"植入后没掉"推出"判据废了"——它更可能是
# 这一维在这份语料上本来就判不出好坏（条件没出现）。**这正是 1.6 要分开的
# 两件事**，所以它单独成一档，不许混进"没抓住"。
LOW_BASELINE = 1.0


def _paired_drop(pairs: list[tuple[list[int], list[int]]]) -> float:
    """每篇先各自取均值，再跨篇取均值——篇与篇之间等权，跑得多的篇不许占便宜。"""
    return statistics.fmean([statistics.fmean(c) - statistics.fmean(d) for c, d in pairs])


def permutation_p(pairs: list[tuple[list[int], list[int]]], *,
                  resamples: int = PERM_RESAMPLES, seed: int = PERM_SEED) -> float:
    """把 clean / dirty 标签**在同一篇之内**打乱，看观测到的掉分有多罕见。

    为什么在篇之内打乱：不同篇的绝对分本来就差一截，跨篇打乱会把「篇间差异」
    当成噪声算进来，p 值会假性变小。

    返回两侧 p = `(1 + #{|null| ≥ |obs|}) / (resamples + 1)`。
    分子加 1 是标准做法，保证 p 永远 > 0——**「p = 0」是不存在的**。
    随机数固定种子，同一份日志每次算出同一个 p（这张表要进台账）。
    """
    if not pairs:
        return 1.0
    obs = abs(_paired_drop(pairs))
    rng = random.Random(seed)
    hit = 0
    pools = [(list(c) + list(d), len(c)) for c, d in pairs]
    for _ in range(resamples):
        drops = []
        for pool, n_clean in pools:
            shuffled = pool[:]
            rng.shuffle(shuffled)
            drops.append(statistics.fmean(shuffled[:n_clean])
                         - statistics.fmean(shuffled[n_clean:]))
        if abs(statistics.fmean(drops)) >= obs - 1e-12:
            hit += 1
    return (hit + 1) / (resamples + 1)


def _pairs_by_row(records: list[dict], probes: tuple[Probe, ...]
                  ) -> dict[tuple[str, str], list[tuple[str, list[int], list[int]]]]:
    """`(probe, dim) → [(笔记, clean 各次, dirty 各次)]`。带 error 的行一律不算一次测量。"""
    by: dict[tuple[str, str], dict[str, list[int]]] = {}
    for r in records:
        if r.get("error") or "scores" not in r:
            continue
        slot = by.setdefault((r["probe"], r["note"]), {})
        for dim, lvl in r["scores"].items():
            slot.setdefault(f"{r['arm']}:{dim}", []).append(int(lvl))
    out: dict[tuple[str, str], list[tuple[str, list[int], list[int]]]] = {}
    for probe in probes:
        for dim in probe.targets:
            rows = []
            for (pid, note_id), slot in by.items():
                if pid != probe.id:
                    continue
                c, d = slot.get(f"clean:{dim}") or [], slot.get(f"dirty:{dim}") or []
                if c and d:
                    rows.append((note_id, c, d))
            out[(probe.id, dim)] = rows
    return out


def calibrate_threshold(records: list[dict], probes: tuple[Probe, ...] = PROBES, *,
                        quantile: float = CAUGHT_QUANTILE,
                        resamples: int = 400, seed: int = PERM_SEED) -> dict:
    """**按实测噪声重新标定「算抓住」那条线**，不再拍脑袋。

    对每一行做 permutation，把所有行的 null |掉分| 汇到一起，取 `quantile` 分位数。
    含义：**纯噪声下，每 20 行才会有 1 行的 |掉分| 越过这个数**。
    返回 `{"threshold", "n_rows", "n_samples", "p_over_half"}`，
    其中 `p_over_half` 是纯噪声下 |掉分| ≥ 0.5 的比例（批 6 量到 10.1% 的那个数）。
    """
    rng = random.Random(seed)
    nulls: list[float] = []
    rows = _pairs_by_row(records, probes)
    n_rows = 0
    for _, entries in rows.items():
        pairs = [(c, d) for _n, c, d in entries]
        if not pairs:
            continue
        n_rows += 1
        pools = [(list(c) + list(d), len(c)) for c, d in pairs]
        for _ in range(resamples):
            drops = []
            for pool, n_clean in pools:
                shuffled = pool[:]
                rng.shuffle(shuffled)
                drops.append(statistics.fmean(shuffled[:n_clean])
                             - statistics.fmean(shuffled[n_clean:]))
            nulls.append(abs(statistics.fmean(drops)))
    if not nulls:
        return {"threshold": CAUGHT, "n_rows": 0, "n_samples": 0, "p_over_half": 0.0}
    nulls.sort()
    idx = min(len(nulls) - 1, int(quantile * len(nulls)))
    return {"threshold": round(nulls[idx], 2), "n_rows": n_rows, "n_samples": len(nulls),
            "p_over_half": round(sum(1 for x in nulls if x >= 0.5) / len(nulls), 3)}


def _verdict(clean: float, drop: float, caught: float = CAUGHT) -> str:
    """一格的结论。顺序本身是判据的一部分，改动要连着下面几条用例一起读。"""
    if drop <= -caught:
        # 植入缺陷之后**反而涨了**。这比"没抓住"严重：不是看不见，是看反了。
        return "反着来了"
    if clean <= 0.0:
        return "无从判断"                 # 干净版就已经垫底，没有下降空间
    if drop >= caught:
        return "抓住"
    if clean < LOW_BASELINE:
        return "基线偏低"
    return "只动了一点" if drop > 0 else "没抓住"


def apply_significance(verdict: str, p: float | None, alpha: float = ALPHA) -> str:
    """掉分够大、但**在这点样本量上跟噪声分不开**的行，单独报成「掉了但不显著」。

    批 6 ⑥：38 条 probe 里 `p ≥ 0.05` 的有 20 行——包括全部三条 n=1 行和
    全部 5 条「只动了一点」。把它们跟真正抓住的行并排放在一张表里，
    就是在拿噪声当依据。**不显著不等于没效果**，所以也不能报成"没抓住"。
    """
    if p is None or p < alpha:
        return verdict
    return "掉了但不显著" if verdict in ("抓住", "反着来了") else verdict


def summarize(records: list[dict], probes: tuple[Probe, ...] = PROBES, *,
              caught: float = CAUGHT, alpha: float = ALPHA,
              resamples: int = PERM_RESAMPLES) -> list[dict]:
    """纯函数：日志行 → 每条 probe 每个目标维度一行灵敏度（带样本量和 p 值）。

    每行的 `n_notes` / `n_calls` / `p` 三个数**必须一起读**：批 6 驳回的
    `data_grounding`(table) 那一行掉了一整档，但 n=1 篇、干净版三次是 [0,2,1]、
    p=0.40——那是噪声，不是灵敏度。
    """
    rows = _pairs_by_row(records, probes)
    out: list[dict] = []
    for probe in probes:
        for dim in probe.targets:
            entries = rows.get((probe.id, dim)) or []
            if not entries:
                out.append({"probe": probe.id, "dim": dim, "verdict": "未跑",
                            "n_notes": 0, "n_calls": 0, "clean": None, "dirty": None,
                            "drop": None, "p": None, "notes": []})
                continue
            pairs = [(c, d) for _n, c, d in entries]
            clean = statistics.fmean([statistics.fmean(c) for c, _d in pairs])
            dirty = statistics.fmean([statistics.fmean(d) for _c, d in pairs])
            drop = clean - dirty
            pv = permutation_p(pairs, resamples=resamples)
            out.append({"probe": probe.id, "dim": dim,
                        "verdict": apply_significance(_verdict(clean, drop, caught), pv, alpha),
                        "n_notes": len(pairs),
                        "n_calls": sum(len(c) + len(d) for c, d in pairs),
                        "clean": round(clean, 2), "dirty": round(dirty, 2),
                        "drop": round(drop, 2), "p": round(pv, 4),
                        "notes": [n for n, _c, _d in entries]})
    return out


# 一维的最终结论 = 它**最好**的那一条 probe 的结论。一条 probe 抓住了，
# 这一维就不算不合格——剩下几条说明的是那种缺陷 / 那个条件的问题。
#
# **「未跑」挪到了最后一位**（批 7 ⑤）。原来它排在「没抓住」/「反着来了」前面，
# 于是一个维度只要有一条 probe 没跑，它真正测出来的**失败就被静默吞掉**——
# 表上显示"未跑"，看起来像"还没测"，其实是"测了，没抓住"。
VERDICT_RANK = ("抓住", "掉了但不显著", "只动了一点", "基线偏低", "无从判断",
                "没抓住", "反着来了", "未跑")


def roll_up(rows: list[dict]) -> list[dict]:
    """纯函数：每条 probe 一行 → **每个维度一行**。这才是 1.6 要交的那张表。

    「只动了一点」这一档要连着掉分一起读：`material_use` 掉 0.07 和
    `follows_prompt` 掉 0.33 都落在这一档里，前者等于噪声。所以这里把
    最好那条 probe 的掉分也带出来，不让一个档位名字把两种情况抹平。

    **这张表天然会盖掉东西**——同一维的另外几条 probe 各自的结论看不见了。
    所以报告里永远同时贴逐 probe 的全表，并且单列一节 `washed_out()`。
    """
    best: dict[str, dict] = {}
    for r in rows:
        cur = best.get(r["dim"])
        if cur is None or VERDICT_RANK.index(r["verdict"]) < VERDICT_RANK.index(cur["verdict"]):
            best[r["dim"]] = r
        elif r["verdict"] == cur["verdict"] and (r.get("drop") or -9) > (cur.get("drop") or -9):
            best[r["dim"]] = r
    return [best[k] for k in sorted(best)]


def washed_out(rows: list[dict]) -> list[dict]:
    """被 `roll_up` 洗掉的失败行：这一维最终报的是别的结论，而这一条是「没抓住 / 反着来了」。

    批 5 的台账只贴了 `roll_up` 之后那张表，**4 条「没抓住」被洗进了别的档**——
    其中 `factual_grounding` 对占位符 n=6 篇、掉 0.00，是当时样本量最大的一行，
    而台账上一个字都看不到。`sensitivity_results/` 又是 gitignore 的，
    进 git 的台账里更看不见。所以这一节必须单独出，而且必须贴进台账。
    """
    winners = {r["dim"]: r["probe"] for r in roll_up(rows)}
    return [r for r in rows
            if r["verdict"] in ("没抓住", "反着来了") and winners.get(r["dim"]) != r["probe"]]


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
                  dropped: list[dict], skips: list[dict], kept_total: int = 0,
                  calib: dict | None = None) -> str:
    by_origin: dict[str, int] = {}
    for d in dropped:
        by_origin[d.get("origin", "?")] = by_origin.get(d.get("origin", "?"), 0) + 1
    lines = ["# 维度灵敏度（植入已知缺陷）", "",
             f"生成：{datetime.now().isoformat(timespec='seconds')}", "",
             "## 语料", "",
             f"- 跑过 harness 的笔记里，按血缘只留 `user` 那一类之后剩 **{kept_total or len(used)}** 篇、"
             f"排掉 **{len(dropped)}** 篇（"
             + "、".join(f"{k} {v}" for k, v in sorted(by_origin.items()))
             + f"）；本次实际参与 **{len(used)}** 篇", ""]
    for d in dropped:
        lines.append(f"  - `{d['id']}` {d.get('user_id','')} [{d.get('origin','?')}]：{d['reason']}")
    lines += ["", f"- 实际参与：{'、'.join('`' + k['id'] + '`' for k in used)}", ""]
    if calib:
        lines += ["## 「算抓住」那条线（按实测噪声标定，不是拍的）", "",
                  f"- 打乱 clean/dirty 标签重算 {calib['n_rows']} 行 × "
                  f"{calib['n_samples'] // max(1, calib['n_rows'])} 次 = {calib['n_samples']} 个纯噪声掉分",
                  f"- 纯噪声下 |掉分| ≥ 0.5 的比例：**{calib['p_over_half']:.1%}**"
                  "（这就是原来那条 0.5 线为什么不能用）",
                  f"- {CAUGHT_QUANTILE:.0%} 分位数 = **{calib['threshold']}**；"
                  f"本次表里用的线是 `CAUGHT = {CAUGHT}`",
                  f"- 逐行还要过 p < {ALPHA}（permutation，{PERM_RESAMPLES} 次重排，"
                  f"种子 {PERM_SEED}）；过不了的报「掉了但不显著」", ""]
    lines += ["## 灵敏度（逐条 probe，**这张表才是原始结论**）", "",
              "| 维度 | probe | 条件 | 干净 | 植入 | 掉分 | 篇 | 次 | p | 结论 |",
              "|---|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for r in sorted(rows, key=lambda x: (VERDICT_RANK.index(x["verdict"]), x["dim"])):
        pid = r["probe"].split("/")
        lines.append(
            f"| `{r['dim']}` | {pid[0]}/{pid[2]} | {pid[-1]} | "
            f"{'' if r['clean'] is None else r['clean']} | "
            f"{'' if r['dirty'] is None else r['dirty']} | "
            f"{'' if r['drop'] is None else r['drop']} | {r['n_notes']} | "
            f"{r.get('n_calls', 0)} | {'' if r.get('p') is None else r['p']} | {r['verdict']} |")
    rolled = roll_up(rows)
    lines += ["", "## 每一维的最终结论（取它最好的那条 probe）", "",
              "| 维度 | 最好的 probe | 干净 | 植入 | 掉分 | 篇 | 次 | p | 结论 |",
              "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for r in sorted(rolled, key=lambda x: (VERDICT_RANK.index(x["verdict"]), x["dim"])):
        pid = r["probe"].split("/")
        lines.append(
            f"| `{r['dim']}` | {pid[0]}/{pid[2]}·{pid[-1]} | "
            f"{'' if r['clean'] is None else r['clean']} | "
            f"{'' if r['dirty'] is None else r['dirty']} | "
            f"{'' if r['drop'] is None else r['drop']} | {r['n_notes']} | "
            f"{r.get('n_calls', 0)} | {'' if r.get('p') is None else r['p']} | {r['verdict']} |")

    washed = washed_out(rows)
    lines += ["", "## 被上面那张表洗掉的失败行（**必须跟着一起读**）", ""]
    if washed:
        lines += ["| 维度 | probe | 干净 | 植入 | 掉分 | 篇 | 次 | p | 结论 |",
                  "|---|---|---:|---:|---:|---:|---:|---:|---|"]
        for r in sorted(washed, key=lambda x: (x["dim"], x["probe"])):
            pid = r["probe"].split("/")
            lines.append(f"| `{r['dim']}` | {pid[0]}/{pid[2]}·{pid[-1]} | {r['clean']} | "
                         f"{r['dirty']} | {r['drop']} | {r['n_notes']} | {r.get('n_calls', 0)} | "
                         f"{r.get('p')} | {r['verdict']} |")
    else:
        lines.append("（无）")

    def _only(name: str) -> str:
        dims = sorted(r["dim"] for r in rolled if r["verdict"] == name)
        return ("- " + "\n- ".join(f"`{d}`" for d in dims)) if dims else "（无）"

    lines += ["", "## 结论", "",
              "**抓不住自己该抓的东西**（干净版分数正常、植入缺陷后一分不掉）：", "",
              _only("没抓住"), "",
              "**反着来了**（植入缺陷之后分数反而涨）：", "",
              _only("反着来了"), "",
              "**掉了但不显著**（掉分够大，但在这点样本量上跟噪声分不开——"
              "n=1 篇 × 3 次时两侧 p 最小就是 0.10，**数学上不可能显著**）：", "",
              _only("掉了但不显著"), "",
              "**条件从不出现**（干净版就已经 0 分，判据要的证据打分器根本拿不到）：", "",
              _only("无从判断"), "",
              "**基线偏低、判不出来**（这份语料上这一维本来就分不出好坏）：", "",
              _only("基线偏低"), "",
              "**只动了一点**（掉分小于那条线；掉 0.1 以下的等于噪声）：", "",
              _only("只动了一点"), "",
              "**没跑**（取不到材料 / 植入器不适用，见最后一节）：", "",
              _only("未跑"), "",
              "**抓住**：", "", _only("抓住"), ""]
    if side:
        lines += ["## 顺带掉分（误伤 / 维度之间不独立）", "",
                  "| probe | 被顺带打低的维度 | 干净 | 植入 | 掉分 |", "|---|---|---:|---:|---:|"]
        for r in side:
            lines.append(f"| {r['probe']} | `{r['dim']}` | {r['clean']} | {r['dirty']} | {r['drop']} |")
        lines.append("")
    if skips:
        lines += ["## 跳过的格子", "", "| 笔记 | probe | 原因 |", "|---|---|---|"]
        for s_ in skips:
            lines.append(f"| `{s_['note']}` | {s_['probe']} | {s_['skipped']} |")
    return "\n".join(lines) + "\n"


# =============================================================== main ===

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notes", type=int, default=5, help="参与的真实笔记篇数（按长度取前 N）")
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
    # **统计只认现在这套取材 + 植入能重现出来的格子**。key 里带正文指纹，
    # 所以改了植入器之后的旧行、以及按血缘被排掉的那些笔记的行，
    # 会在这里自动掉出去——不会被拼进同一张表（批 7 撞出来的那个坑）。
    all_cells, _ = build_tasks(notes, probes, args.repeats, set())
    valid = {t.key for t in all_cells}
    stale = [r for r in records if r.get("key") not in valid]
    records = [r for r in records if r.get("key") in valid]
    print(f"待跑 {len(tasks)} 格（已完成 {len(done)}，日志里另有 {len(stale)} 行"
          f"对不上现在的语料/植入器，不进统计），跳过 {len(skips)} 条 probe×篇", flush=True)

    if not args.report and tasks:
        _llm.ctx_user.set("sensitivity-bench")
        _llm.ctx_feature.set("bench/sensitivity")
        deadline = time.monotonic() + args.time_budget_seconds
        ran = asyncio.run(run_tasks(tasks, concurrency=args.concurrency, deadline=deadline))
        print(f"\n本次跑了 {ran} 格", flush=True)
        records = [r for r in read_log() if r.get("key") in valid]

    calib = calibrate_threshold(records, probes)
    print(f"噪声标定：{calib}", flush=True)
    rows = summarize(records, probes)
    side = collateral(records, probes)
    report = render_report(rows, side, notes, dropped, skips, kept_total=len(kept), calib=calib)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{datetime.now().strftime('%m%d-%H%M%S')}-sensitivity.md"
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"→ {out}", flush=True)


if __name__ == "__main__":
    main()
