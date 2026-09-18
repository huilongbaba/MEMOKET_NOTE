"""屏幕活动日报的判据：全是确定性的，零模型调用（计划 8.2）。

## 为什么这一步值得配判据

跟 `magic-tap` 同一条理由（[EVAL] 问题四）：15 个会产出文字的功能里只有 8 个
有 evaluator，而 `journey/report` 是最后那一档里**用户直接看得见产出**的两个
之一。它自己的提示词注释里早就写着一句话：

> 「这跟写作 harness 里 `material_used` 那条判据是同一场仗」

——方法是通的，**只是没有落成判据**。这一份就是把那句话落下来。

## 这条路有一半本来就是确定性的

「时间去哪了」那一节由 `journey/stats.render_time_block()` 算好、渲染好、原样
进正文，提示词里明说不要重算：**模型数时长会数错，而它数错的时候读起来跟数
对了一模一样**。所以判据只看**模型写的那一半**（`text`），代码渲染的那一节
不在分母里——判自己算的东西没有意义。

## 形态照 `checks/slides.py`

**判了不拦着落库**：日报是一次模型调用、一次成型的产物，不进多轮闭环。
判据结果跟着日报一起返回（`JourneyReportOut.notes`，并且落进 `report.json`，
刷新之后还在），用户自己决定要不要「重写」。

## 五条做、两条量完不做

阈值全在**真实产出**上量（`scripts/tap_report_denominator.py`）：
`<userData>/journey/<日期>/report.json` 里**两份真实日报**（2026-09-17 / 09-18，
一共 **18 条 bullet**），喂给模型的那份输入按 `group_runs` + 同一套行格式
**逐字重建**（09-17 重建出 52 行 / 声明 54 段，09-18 重建出 40 行 / 声明 41 段）。

| 判据 | 两份真实日报上开火 | 门槛 |
|---|---:|---|
| 模型自己算了时长 | **0** | 时长词不在输入里出现过 |
| 写出了规定之外的二级标题 | **0** | 白名单三节 |
| 有 bullet 一个具体东西都不带 | **0 / 18 条** | 一条锚点都没有 |
| 同一节里两条 bullet 说同一件事 | **0**（同节最高 0.264） | ≥ 0.55 |
| bullet 里的名字在记录里查无出处 | **0 个拉丁词** | 逐字比对 |

**两条量完之后不做**：

1. **数字查无出处不做。** 同一份重建上，拉丁词 0 个查无出处，**数字有 1 个**
   ——09-17 那份写着「`harness-evaluator-industry.md` 第 757 轮调研」，而重建出
   来的 52 行里没有 `757`。但它**不是编的**：原始 `segments.json` 里确实有一条
   描述带着 757，是 `group_runs` 合并同一件事时**只留了最长的那一句**，把它
   丢掉了。也就是说**这条判据的分母本身不干净**——它报的是「合并丢掉了什么」，
   不是「模型编了什么」。拉丁词那一条没有这个问题（0/两天），所以只留它。
2. **每节的条数上限不做。** 提示词要求「每节 2-4 条」，实测两天六节是
   4/1/4 和 4/2/3，**一次都没出过界**。分母只有六节，门槛只能拍——而「凑条数」
   这个毛病真出现的时候，凑出来的那几条通常一个具体名字都不带，
   上面那条锚点判据本来就会接住。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...journey.runs import similar

# 提示词规定的三节，白名单之外的标题都算多写的。**「时间去哪了」不在里面**：
# 那一节由代码渲染，模型再写一遍就是重算。
SECTIONS = ("推进了什么", "卡在哪", "计划外的")

# 两条 bullet 像到这个份上就是「同一件事写了两条」。**量出来的**：两天六节
# 里同一节内部两两最像的一对是 **0.264**，门槛放到 0.55 留了一倍的空当
# ——跟 `checks/skeleton.DUP_BEAT_RATIO` 同一个定法（那边观测 0.13–0.29、门槛
# 0.55）。跨节**不判**：09-18 真实日报里「推进了什么」和「卡在哪」各有一条
# 讲 `harness-upgrade-plan.md`，相似度 0.679，而那是两件事（推进到哪 / 卡在哪），
# 提示词那条规矩原话也是「这一节只说了一件事却占了两行」。
DUP_BULLET = 0.55

# 用 `journey/runs.similar` 而不是 difflib：那一份是**前后端对拍过**的二元组
# Dice（`frontend/scripts/check-journey-merge.mts` 钉着），而且分段本身就是拿
# 它并的——判「两条说的是不是同一件事」跟并段是同一个问题，不该有两套答案。

# 「每条都要带具体的东西：文件名、函数名、文档标题、人名、报错、数字」。
# 「落在具体内容上」唯一不需要读懂中文就能判的痕迹是这三种——跟
# `checks/skeleton._ANCHOR` 同一条理由、同一张表。
_ANCHOR = re.compile(r"\d|[A-Za-z]{2,}|[“\"「『《][^”\"」』》]{2,}[”\"」』》]")

# 时长：提示词明令「不要统计任何时长」。**只报输入里没出现过的那些**——
# 记录本身写着「30 分钟的会」时模型引用它是对的，自己算出来的才是错的。
_DURATION = re.compile(r"\d+(?:\.\d+)?\s*(?:分钟|小时|个小时|秒|min|hours?|mins?)")

_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)
_BULLET = re.compile(r"^\s*[-*]\s+(.+?)\s*$", re.M)


def _sections(text: str) -> list[tuple[str, str]]:
    """模型那一半按 `##` 切成 (标题, 这一节的正文)。标题前面的散文归 `""`。"""
    parts = re.split(r"(?m)^#{1,6}\s+(.+?)\s*$", text or "")
    out: list[tuple[str, str]] = []
    if parts and parts[0].strip():
        out.append(("", parts[0]))
    for i in range(1, len(parts) - 1, 2):
        out.append((parts[i].strip(), parts[i + 1]))
    return out


@dataclass(frozen=True)
class ReportCheck:
    """一份日报的体检。`notes()` 是给界面显示的人话，全合格就是空列表。"""

    bullets: int = 0
    """模型自己算出来的时长（输入的记录里没有这个数）。"""
    recomputed_durations: list[str] = field(default_factory=list)
    """规定之外的二级标题（含把代码渲染的那一节又写了一遍）。"""
    stray_sections: list[str] = field(default_factory=list)
    """一个具体的东西都不带的条目。"""
    vague_bullets: list[str] = field(default_factory=list)
    """同一节里说同一件事的两条：(第一条, 第二条, 相似度)。"""
    duplicate_bullets: list[tuple[str, str, float]] = field(default_factory=list)
    """条目里提到、而记录里查不到的名字。"""
    unsourced_terms: list[str] = field(default_factory=list)

    def notes(self) -> list[str]:
        out: list[str] = []
        if self.recomputed_durations:
            out.append("日报里出现了记录里没有的时长："
                       + "、".join(self.recomputed_durations[:4])
                       + "——「时间去哪了」那一节是程序按时间戳算的，"
                         "模型自己算的时长读起来跟算对了一模一样，但它是错的。")
        if self.stray_sections:
            out.append("多写了规定之外的小节："
                       + "、".join(f"「{s}」" for s in self.stray_sections[:3])
                       + "。这份日报只该有「推进了什么 / 卡在哪 / 计划外的」三节，"
                         "没内容的整节省掉。")
        if self.unsourced_terms:
            out.append("这几个名字在今天的记录里查不到："
                       + "、".join(self.unsourced_terms[:6])
                       + "——日报只能依据记录写，记录里没有的东西不该出现在里面。")
        if self.vague_bullets:
            out.append("这几条一个具体的东西都没写到（没有文件名、人名、报错或数字）："
                       + "；".join(f"「{b[:28]}…」" for b in self.vague_bullets[:2])
                       + "。「继续推进了开发工作」这种话等于没写。")
        for a, b, ratio in self.duplicate_bullets[:2]:
            out.append(f"同一节里有两条说的是同一件事（相似度 {ratio:.0%}）："
                       f"「{a[:26]}…」和「{b[:26]}…」——"
                       "一件事只写一条，换个角度再说一遍等于这一节少说了一件事。")
        return out


def check_report(text: str, lines: list[str]) -> ReportCheck:
    """一份日报的体检。**纯函数**：给模型写的那一半和喂给它的那几行就能测。

    `text` 是**模型写的那一半**，不含 `render_time_block()` 渲染的那一节；
    `lines` 是真正进了提示词的那几行（`group_runs` 并过的），不是原始 segments
    ——模型只可能依据它看见的东西写，判「查无出处」就必须按它看见的那一份判。
    """
    body = (text or "").strip()
    source = "\n".join(lines or [])
    low = source.lower()

    stray = [t for t in (m.group(1).strip() for m in _HEADING.finditer(body))
             if t not in SECTIONS]

    durations = [d for d in _DURATION.findall(body) if d not in source]

    vague: list[str] = []
    dups: list[tuple[str, str, float]] = []
    terms: list[str] = []
    total = 0
    for _title, chunk in _sections(body):
        items = [m.group(1).strip() for m in _BULLET.finditer(chunk)]
        total += len(items)
        for b in items:
            if not _ANCHOR.search(b):
                vague.append(b)
            # 拉丁词才查出处：中文短语在记录和日报之间必然被改写（记录是一句
            # 描述，日报是归纳），逐字比对只会全军覆没；而文件名 / 应用名 /
            # 函数名是**逐字搬过来**的那一类。批 18 在长文上砍掉「所有拉丁专名」
            # 是因为那边混着世界知识（`Zoom` / `Apple` / `GWh`），这边不混：
            # 提示词要求只依据记录写，记录就是这些名字的全部来源。
            # **按 `/` 切开再查**：09-17 那份真实日报里模型写了
            # `backend/app/harness/pick_dimension`，而记录里 `pick_dimension`
            # 和那几层目录是**分开出现**的——整条路径是模型拼的，四段却都有
            # 出处。不切的话这条判据在两天里唯一的一次开火就是误伤。
            for t in re.findall(r"[A-Za-z][A-Za-z0-9_.#-]{2,}", b):
                name = t.strip(".-")
                if len(name) >= 3 and name.lower() not in low and name not in terms:
                    terms.append(name)
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                ratio = similar(items[i], items[j])
                if ratio >= DUP_BULLET:
                    dups.append((items[i], items[j], round(ratio, 2)))

    return ReportCheck(bullets=total, recomputed_durations=durations,
                       stray_sections=stray, vague_bullets=vague,
                       duplicate_bullets=dups, unsourced_terms=terms)
