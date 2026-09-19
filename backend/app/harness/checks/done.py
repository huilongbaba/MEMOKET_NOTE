"""「完成标准」清单里代码判得了的那几条 → 智能续写的一条判据（P13 #1；P12 下一步③）。

P12 把文档意图里的「完成标准」拆成一条条摆在右栏「计划」第一格：字数上下限 / 每条有日期 /
有出处 / 「X、Y 各有一节」/ 结论在前 由代码当场判并说清为什么，判不了的留一个勾给用户。
那份判定只活在浏览器里——智能续写（harness）跑的时候，模型手里只有 prompt 里一句
`DONE_HINT`，写完了达没达标它自己说了算，右栏那个 ✗ 只能等用户回头看。

**这里是同一份判定的后端版**，两边逐条对拍（`shared/done-cases.json` 一张用例表两边各跑一遍
+ `tests/test_p13.py` 逐句核对前端 `util/doneChecks.ts` 里的正则和措辞——P1 `block_precondition`
立的纪律：前端不能 import 后端，那就两边各一份、闸盯着别漂）。命中的那一条走 `check_hit`
事件（界面「代码判据 你定的完成标准 判了…」）+ `Verdict.message` 进下一轮的修订 / 检索
（`bag["focus_note"]`），跟别的代码判据一模一样。

**量程**（§20 ④ / P6 那条「报不报和动不动是同一条量程」）：
  · 「每条有日期 / 出处」按单位判——**只判这次跑新写的单位**（不在 `content_at_start` 里的）。
    用户自己写的几条没出处，修订那条线碰不了它们（P6 守卫），判了只会连响两轮然后停机；
    右栏那份照旧看整篇，那是给用户看的，这份是给模型的。
  · 字数上下限 / 各有一节 / 结论在前 看整篇——它们本来就是整篇的要求，而且模型有权改善
    （多写一节 / 把结论提前 / 删自己写的复述）；超长是用户原文造成的那一档会连响两轮，
    `check_stuck` 会把它停下来并说清是哪条。
  · 用户勾过的（`intent.checked`）一律不判——勾了就是「我认了」。
  · 打磨模式（只修不写）不判「至少 N 字」「各有一节」「写下来就算完」——那是要它写。

它不写死在 `Mode.checks` 上，是 `middleware/done.DoneCriteria` 在 `before_run` 挂上去的
（跟 `instruction_constraints` 同一条理由：内容来自用户写的那句话，`Mode` 必须是纯数据）。
"""

from __future__ import annotations

import re
from typing import Callable

from ...database.wordcount import word_count
from ...editor import outline
from ..state import State
from ..types import Verdict
from .pick import pick_dimension

# ------------------------------------------------------------------ 规则 ---
#
# **每一条正则的字面跟前端 `util/doneChecks.ts::DONE_RULES` 一字不差**（那边是 `String.raw`，
# 这边是 r""；`tests/test_p13.py` 逐条核对）。JS 和 Python 在这几条上语义一样：
# `\d` / `\s` / `(?:)` / 字符类 / `\b`。全角数字两边都先换成半角再匹配（JS 的 `\d` 不认全角，
# Python 的认——不先换的话「≤ ８００ 字」两边判得不一样）。
RULES: dict[str, str] = {
    "max": r"(?:≤|<=|不超过|不多于|少于|控制在|最多)(\d+)字",
    "max2": r"(\d+)字(?:以内|以下|之内|内)",
    "min": r"(?:≥|>=|至少|不少于|不低于|最少)(\d+)字",
    "min2": r"(\d+)字(?:以上|起)",
    "nonempty": r"写下来就算完|写了就算",
    "sections": r"^(.+?)各有一节",
    "sections2": r"^(.+?)(?:各|都)?(?:单独)?(?:有|成)一节",
    "section_split": r"[、，,和与及]",
    "section_lead": r"^(?:要|需要|得)",
    "conclusion": r"结论在前|先说结论|结论先行|开头.*结论",
    "conclusion_head": r"结论|总结|摘要|TL;?DR|一句话",
    "conclusion_open": r"结论|总之|一句话|判断是|建议",
    "date_want": r"有日期|有时间|带日期|标日期",
    "cite_want": r"有依据|有出处|有引用|事实支撑|有来源|有证据|引用或出处|标出处|注明出处",
    "numeric_only": r"数字|数据",
    "date": r"\d{1,2}\s*[月/.-]\s*\d{1,2}|\d{4}\s*[-/年]\s*\d{1,2}|\d{1,2}\s*月(?:底|初|末|中)?|今天|昨天|前天|明天|本周|上周|下周|周[一二三四五六日天]|星期[一二三四五六日天]|Q[1-4]\b|\d+\s*号",
    "link": r"\[[^\]\n]*\]\([^)\s]+\)|https?://\S+",
    "cite": r"\[([A-Za-z][A-Za-z0-9_-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+)\]",
    "note_link": r"\]\(note://([0-9a-f]{12})\)",
    "item": r"^\s*(?:[-*+]|\d+[.)])\s+\S",
    "item_strip": r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s*)?",
    "fence": r"^\s*(`{3,}|~{3,})",
    "split": r"[；;。\n]+",
}
# 「为什么」的措辞——两边一字不差（前端模板字符串里 `${x}` 对应这里的 `{x}`）。
WHY: dict[str, str] = {
    "max_ok": "现在 {words} 字",
    "max_over": "现在 {words} 字，超出 {over} 字",
    "min_ok": "现在 {words} 字",
    "min_short": "现在 {words} 字，还差 {short} 字",
    "nonempty_ok": "写了 {words} 字",
    "nonempty_no": "正文还是空的",
    "sections_missing": "标题里没有：{missing}",
    "sections_ok": "{n} 节都有",
    "conclusion_ok": "开头就是结论",
    "conclusion_no": "开头没看到「结论」",
    "no_units": "正文里还没有条目",
    "no_numbers": "正文里没有数字",
    "date_miss": "{n} {unit}里 {miss} {unit}没有日期",
    "date_ok": "{n} {unit}都有日期",
    "cite_miss": "{n} {unit}里 {miss} {unit}没有出处",
    "cite_ok": "{n} {unit}都有出处",
}
_R = {k: re.compile(v) for k, v in RULES.items()}
_HEAD_I = re.compile(RULES["conclusion_head"], re.I)
_FULLWIDTH = {ord(c): str(i) for i, c in enumerate("０１２３４５６７８９")}
PARA_MIN = 20          # 没有列表时按段落，短于这个字数的段不算「一条」


def split_done(done: str) -> list[str]:
    """「完成标准」一句拆成几条：分号 / 句号 / 换行分开；逗号不拆（「有日期、有依据」是一条里的两件事）。"""
    return [s.strip() for s in _R["split"].split(done or "") if s.strip()]


def units(content: str) -> tuple[str, list[str]]:
    """「每条」的单位：列表项优先；一条列表都没有就按 ≥ PARA_MIN 字的段落（标题、围栏不算）。

    **紧跟在一条列表项后面的段落算给那一条**（P13 #2 / P12 下一步①）：周会那种「要点列表 +
    带出处的展开段」（`f5e34e385aac`）第一版被判「7 条里 7 条没有出处」，出处全在列表下面的
    展开段里。空行隔开也算「紧跟」；下一条列表项 / 标题一出现就断。
    """
    lines = (content or "").split("\n")
    items: list[str] = []
    paras: list[str] = []
    fenced = False
    cur: list[str] = []
    last_item = -1

    def flush() -> None:
        nonlocal cur
        if cur:
            paras.append("\n".join(cur))
            cur = []

    for line in lines:
        if _R["fence"].match(line):
            fenced = not fenced
            flush()
            continue
        if fenced:
            continue
        is_head = bool(re.match(r"^#{1,6}\s", line))
        if not line.strip() or is_head:
            flush()
            if is_head:
                last_item = -1
            continue
        if _R["item"].search(line):
            items.append(_R["item_strip"].sub("", line, count=1))
            last_item = len(items) - 1
        elif last_item >= 0:
            items[last_item] += "\n" + line
        cur.append(line)
    flush()
    if items:
        return "item", items
    return "paragraph", [p for p in paras if len(re.sub(r"\s", "", p)) >= PARA_MIN]


def _has_cite(s: str) -> bool:
    return bool(_R["cite"].search(s) or _R["note_link"].search(s) or _R["link"].search(s))


def _headings(content: str) -> list[str]:
    return [t for _, t in outline.headings(content or "")]


def _opening(content: str) -> str:
    lines = [l for l in (content or "").split("\n") if l.strip() and not re.match(r"^#{1,6}\s", l)]
    return "\n".join(lines[:2])


def check_done_item(item: str, content: str, *,
                    unit_filter: Callable[[str], bool] | None = None) -> dict | None:
    """判一条。回 None = 代码判不了（要用户判）。

    `unit_filter`（只有 harness 用）：「每条有日期 / 出处」只看过滤后的单位。前端那份没有这个参数，
    共享用例表都在不带它的情况下跑。
    """
    t = re.sub(r"\s+", "", item or "").translate(_FULLWIDTH)
    words = word_count(content or "")
    m = _R["max"].search(t) or _R["max2"].search(t)
    if m:
        n = int(m.group(1))
        return ({"kind": "max", "status": "pass", "why": WHY["max_ok"].format(words=words)} if words <= n
                else {"kind": "max", "status": "fail", "why": WHY["max_over"].format(words=words, over=words - n), "n": n})
    m = _R["min"].search(t) or _R["min2"].search(t)
    if m:
        n = int(m.group(1))
        return ({"kind": "min", "status": "pass", "why": WHY["min_ok"].format(words=words)} if words >= n
                else {"kind": "min", "status": "fail", "why": WHY["min_short"].format(words=words, short=n - words), "n": n})
    if _R["nonempty"].search(t):
        return ({"kind": "nonempty", "status": "pass", "why": WHY["nonempty_ok"].format(words=words)} if words > 0
                else {"kind": "nonempty", "status": "fail", "why": WHY["nonempty_no"]})
    m = _R["sections"].search(t) or _R["sections2"].search(t)
    if m:
        names = [_R["section_lead"].sub("", s).strip() for s in _R["section_split"].split(m.group(1))]
        names = [s for s in names if s and len(s) <= 8]
        if names:
            heads = _headings(content)
            missing = [n for n in names if not any(n in h for h in heads)]
            return ({"kind": "sections", "status": "fail", "why": WHY["sections_missing"].format(missing="、".join(missing)), "missing": missing}
                    if missing else {"kind": "sections", "status": "pass", "why": WHY["sections_ok"].format(n=len(names))})
    if _R["conclusion"].search(t):
        heads = _headings(content)
        first_head = heads[0] if heads else ""
        ok = bool(_HEAD_I.search(first_head) or _R["conclusion_open"].search(_opening(content)))
        return ({"kind": "conclusion", "status": "pass", "why": WHY["conclusion_ok"]} if ok
                else {"kind": "conclusion", "status": "fail", "why": WHY["conclusion_no"]})
    want_date = bool(_R["date_want"].search(t))
    want_cite = bool(_R["cite_want"].search(t))
    if want_date or want_cite:
        kind, texts = units(content)
        unit = "条" if kind == "item" else "段"
        if not texts:
            return {"kind": "cite" if want_cite else "date", "status": "fail", "why": WHY["no_units"]}
        scope = [s for s in texts if re.search(r"\d", s)] if (_R["numeric_only"].search(t) and want_cite) else texts
        if unit_filter is not None:
            scope = [s for s in scope if unit_filter(s)]
            if not scope:
                return None            # 这次跑还没写出一个新单位：无从判断，不开火
        if not scope:
            return {"kind": "cite", "status": "pass", "why": WHY["no_numbers"]}
        parts: list[str] = []
        bad_date: list[str] = []
        bad_cite: list[str] = []
        if want_date:
            bad_date = [s for s in scope if not _R["date"].search(s)]
            parts.append(WHY["date_miss"].format(n=len(scope), unit=unit, miss=len(bad_date)) if bad_date
                         else WHY["date_ok"].format(n=len(scope), unit=unit))
        if want_cite:
            bad_cite = [s for s in scope if not _has_cite(s)]
            parts.append(WHY["cite_miss"].format(n=len(scope), unit=unit, miss=len(bad_cite)) if bad_cite
                         else WHY["cite_ok"].format(n=len(scope), unit=unit))
        fail = bool(bad_date or bad_cite)
        # 两件事写在一条里（「有日期、有依据」）：先报没日期的那半（提示词只说一件事）
        kind_out = "date" if bad_date else "cite" if bad_cite else ("cite" if want_cite else "date")
        return {"kind": kind_out, "status": "fail" if fail else "pass", "why": "；".join(parts),
                "bad": bad_date or bad_cite, "unit": unit}
    return None


def check_done(done: str, content: str, checked: list[str] | tuple[str, ...] = ()) -> list[dict]:
    """整句「完成标准」→ 逐条状态（跟前端 `checkDone` 同一形状：text / status / why / checked）。"""
    out = []
    for text in split_done(done):
        r = check_done_item(text, content)
        if r:
            out.append({"text": text, "status": r["status"], "why": r["why"], "checked": False})
        else:
            out.append({"text": text, "status": "manual", "why": "", "checked": text in checked})
    return out


# ------------------------------------------------------------- harness 判据 ---

# 打磨模式（只修不写）判不了的那几类：它们的修法是「写」。
_NEEDS_WRITING = {"min", "sections", "nonempty"}


def judgeable(done: str, checked: tuple[str, ...] = (), *, polish: bool = False) -> list[str]:
    """这篇的「完成标准」里，代码判得了、用户又没勾掉的那几条（挂不挂判据看它空不空）。"""
    out = []
    for text in split_done(done):
        if text in checked:
            continue
        r = check_done_item(text, "")
        if r is None:
            continue
        if polish and r["kind"] in _NEEDS_WRITING:
            continue
        out.append(text)
    return out


def _dimension(st: State, kind: str) -> str:
    # 每一类打翻的维度按当前模式真有的挑：没出处 / 没日期是材料的事（进检索规划的 steer）；
    # 不够长 / 缺一节是「还没写够」（覆盖那一族）；超长 / 结论没在前没有对应的评分轴——**不拿 coherence
    # 当兜底**（`tests/test_coherence_bucket.py` 的词法闸：它是评分维度不是垃圾桶），落 `MECHANICS`，
    # 诊断逐字在 message 里，修订那条线读的是 `focus_note`，不靠维度名。
    if kind in ("cite", "date"):
        return pick_dimension(st, "factual_grounding", "no_fabrication", "data_grounding")
    if kind in ("max", "conclusion"):
        return pick_dimension(st, "fits_context")
    return pick_dimension(st, "beat_coverage", "section_coverage", "material_use")


def _locate(bad: list[str], content: str, unit: str) -> list[str]:
    """把「没日期 / 没出处」的那几条定位成**第几段 + 原话头一句**（P19 #6）。

    P18 实拍（da080 p18b）：`done_criteria` 连响三轮，三轮的提示**一字不差**——
    「5 段里 2 段没有日期；…没日期的比如：「访谈把四项挑战进一步落到了使用过程，而不是功能清…」」。
    模型三轮都没照做，而它看到的确实是同一句话：提示没变，模型凭什么换个做法。
    两处没说清：① 「比如」那两条只有开头 24 个字，模型得自己回正文里找是哪一段；
    ② 「补上日期」说的是要什么，没说**怎么落到字面上**。

    这里给的是**位置**：按正文里段落的序号数出「第 N 段」，再贴那一段的头一句。
    """
    out: list[str] = []
    paras = [p for p in re.split(r"\n\s*\n", content or "") if p.strip()]
    for b in bad[:3]:
        head = b.strip().splitlines()[0]
        n = 0
        for i, para in enumerate(paras, start=1):
            if head[:20] and head[:20] in para:
                n = i
                break
        where = f"第 {n} 段" if n else "这一条"
        out.append(f"{where}「{head[:30]}{'…' if len(head) > 30 else ''}」")
    return out


def _hint(r: dict, content: str = "") -> str:
    kind = r["kind"]
    unit = r.get("unit", "段")
    if kind == "cite":
        where = "；".join(_locate(r.get("bad", []), content, unit))
        # **说清楚要往哪儿写、写成什么样**（P19 #6）：一条「补上出处」的指令模型连三轮没照做，
        # 而它需要的是「在这一句句末加 [编号]」这种手上的动作，不是「让它有出处」这种目标。
        return (f"没出处的是：{where}。逐条这么改：句末加一个材料里真有的 [事实编号]"
                "（照抄材料里那一串，别自己拼）；材料里查不到支撑的，把那句改写成"
                "「这里需要补上 XX 的记录」——**这两种改法只能选一种，别把没出处的句子原样留着**。")
    if kind == "date":
        where = "；".join(_locate(r.get("bad", []), content, unit))
        return (f"没日期的是：{where}。逐条这么改：在这一句里点明日期（「4月16日，EVT…」这样写在句首，"
                "只用材料里真有的日期）；材料里没有日期的，就在句末写「（日期待补）」"
                "——**别把没日期的句子原样留着**。")
    if kind == "max":
        return f"删到 {r.get('n')} 字以内：先删复述和铺垫，别删有依据的句子。"
    if kind == "min":
        return f"接着写还没写到的那一面，写够 {r.get('n')} 字，不要靠车轱辘话凑。"
    if kind == "sections":
        return "补上这几节的 # 标题和正文：" + "、".join(r.get("missing", [])) + "。"
    if kind == "conclusion":
        return "把结论提到开头：第一段或第一个标题直接给结论，背景往后放。"
    return "先把正文写出来。"


def done_criteria(st: State) -> Verdict | None:
    """把「完成标准」里代码判得了的那几条逐条对一遍，第一条没过的报出去（`Checks` 是「第一条响的赢」）。"""
    from ...editor import intent as doc_intent
    done = doc_intent.done_of(st.ctx.intent)
    if not done:
        return None
    checked = tuple(getattr(st.ctx, "intent_checked", ()) or ())
    polish = bool(st.bag.get("polish"))
    start = str(st.bag.get("content_at_start") or "")
    # 「这次跑新写的单位」：不在开跑前正文里的。开跑前正文还没记（测试里直接调）就看整篇。
    # **照着提示弃答的那几条不再算「没出处」**（P15 #1 真跑第 3 轮实拍）：`_hint` 说「编不出来的结论就改成
    # 『这里需要补上 XX 的记录』」，模型照做了，这条判据却把那几句又数成「6 条里 4 条没有出处」——判据跟自己的
    # 提示打架，跟 `material_thin` 那条「它已经照做了，别再拦一次」同一个形状。弃答句的认法就用
    # `grounding_rules.abstention_lines`（跟 `material_thin` 同一份）。右栏那份照旧看整篇、照旧数——那是给用户看的。
    from .grounding_rules import abstention_lines
    fresh_only = (lambda s: s.strip() not in start and not abstention_lines(s)) if start else None
    for text in judgeable(done, checked, polish=polish):
        r = check_done_item(text, st.content, unit_filter=fresh_only)
        if not r or r["status"] != "fail":
            continue
        scope = "这次写的 " if (fresh_only and r["kind"] in ("cite", "date")) else ""
        # **连响时把话换掉**（P19 #6）：同一条判据第二次、第三次响，说明上一轮那句话没起作用——
        # 一字不差地再说一遍，模型没有任何理由换个做法（P18 da080 p18b 实拍三轮原话全等）。
        # 第 2 轮起明说「上一轮提过、没改到」，并把「先改这一条再写别的」摆在前面。
        # 读**上一轮**那份（`check_name_streak` 在 `Checks.before_judge` 里已经被换成当轮的空表了）
        streak = int((st.bag.get("check_name_streak_prev") or {}).get("done_criteria", 0)) + 1
        again = ("上一轮就提过这条、这一轮还是没改到。**这一轮先只做这件事，别再往下写新段落**："
                 if streak >= 2 else "")
        return Verdict(
            dimension=_dimension(st, r["kind"]),
            message=f"你定的完成标准「{text}」还没满足：{scope}{r['why']}。{again}{_hint(r, st.content)}",
        )
    return None
