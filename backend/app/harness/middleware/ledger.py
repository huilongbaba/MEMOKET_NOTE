"""材料账本：一次跑之内「我已经有什么」的那份状态。

**这一版只记不改。** 一行行为都不变——它存在的全部意义是让下面这些问题
从「未测」变成「有数」（docs/harness-fact-ledger.md §7 第 1 步）：

  · 一次跑里参数完全相同的重复查询占了多少？
  · 各主题 / 实体轴上，库里共 N 条、我们取了 M 条？
  · 第 2 轮起，查回来的里有多少是新的？

**为什么非要有这份状态**：`hooks/note.py` 每轮 `trace = ToolTrace()` 新建、
轮末丢掉，于是检索规划每一轮都从零开始。而 prompt 里明明写着「不要再取
上几轮已经写过的那些」——**要求写在文字里，清单没给**
（docs/harness-multiround-retrieval.md §1）。

**边界：只存 id + 一行 + 状态。全文永远回 kite 取。**
存全文就要维护一致性，那是自找的第二个真相来源。
"""

from __future__ import annotations

import json
import re

from ..state import State

# `_fmt_facts` 写出来的形状是 `[fact_id] 正文…`
_FACT_LINE = re.compile(r"^\[([A-Za-z0-9_\-]+)\]\s*(.+)$", re.M)
# `filter_facts` 的返回体第一行：「共 41 条，返回 15 条：」——**分母就在这里**，
# 我们以前每轮读一次、每轮扔一次。
_TOTAL = re.compile(r"共\s*(\d+)\s*条")
# `list_topics` 的每一行：「- 众筹（41 条，别名：…）」
_TOPIC_LINE = re.compile(r"^-\s*(\S+)（(\d+)\s*条", re.M)

LINE_CHARS = 60          # 账本里一条事实留多长的摘要
SEP = "\t"               # 查询身份里工具名和参数之间的分隔


def blank() -> dict:
    return {"queries": [], "axes": {}, "facts": {}}


def ledger_of(st: State) -> dict:
    led = st.bag.get("ledger")
    if not isinstance(led, dict):
        led = blank()
        st.bag["ledger"] = led
    return led


def _key(tool: str, args: dict) -> str:
    """一次查询的身份。**参数要按键排序**——同样的查询换个参数顺序写出来
    是两个字符串，那样重复查询永远统计不出来。"""
    try:
        return tool + SEP + json.dumps(args or {}, sort_keys=True, ensure_ascii=False)
    except TypeError:
        return tool + SEP + repr(sorted((args or {}).items()))


def _axis_of(tool: str, args: dict) -> str:
    if tool != "filter_facts":
        return ""
    for k in ("topic", "entity", "kind", "who"):
        if (args or {}).get(k):
            return f"{k}:{args[k]}"
    return ""


def fold(led: dict, calls: list[tuple[str, dict, str]]) -> dict:
    """把这一轮的工具调用折进账本。返回这一轮的几个计数。"""
    stat = {"tool_calls": 0, "repeat_calls": 0, "facts_new": 0}
    seen = {q["key"] for q in led["queries"]}
    for tool, args, result in calls or []:
        stat["tool_calls"] += 1
        k = _key(tool, args)
        ids = [m.group(1) for m in _FACT_LINE.finditer(result or "")]
        if k in seen:
            stat["repeat_calls"] += 1
        else:
            seen.add(k)
        led["queries"].append({"key": k, "tool": tool, "hit": len(ids),
                               "empty": not ids})
        for m in _FACT_LINE.finditer(result or ""):
            fid, text = m.group(1), m.group(2).strip()
            if fid not in led["facts"]:
                led["facts"][fid] = {"line": text[:LINE_CHARS], "state": "taken",
                                     "tool": tool}
                stat["facts_new"] += 1
        # 分母：`filter_facts` 自己在返回体里给了「共 N 条」
        axis = _axis_of(tool, args)
        if axis:
            total = _TOTAL.search(result or "")
            slot = led["axes"].setdefault(axis, {"total": 0, "taken": 0})
            if total:
                slot["total"] = max(slot["total"], int(total.group(1)))
            slot["taken"] = max(slot["taken"], len(ids))
        if tool == "list_topics":
            for m in _TOPIC_LINE.finditer(result or ""):
                slot = led["axes"].setdefault(f"topic:{m.group(1)}",
                                              {"total": 0, "taken": 0})
                slot["total"] = max(slot["total"], int(m.group(2)))
    return stat


def mark_used(led: dict, content: str) -> int:
    """正文里引到的事实标成 used。引用形如 `[terrence-1872-5F8]`，
    跟 `_FACT_LINE` 是同一种括号写法，所以直接扫 id。"""
    n = 0
    for fid, row in led["facts"].items():
        if f"[{fid}]" in (content or ""):
            row["state"] = "used"
            n += 1
    return n


class Ledger:
    """把每一轮的工具轨迹折进账本，并把这一轮记进 `harness_rounds`。

    **不读、不改任何 prompt。** 接进 prompt 是下一步的事，要单独验——
    有实测证据说明「把已经有什么摆给模型看」会**缩小它的搜索空间**
    （docs/harness-fact-ledger.md §10⑤），所以那一步必须能单独回退。
    """

    name = "ledger"
    hooks = ("after_prepare", "after_judge")
    # Facts 先把这一轮的 haul 折进 st.facts，账本再记——顺序反了的话
    # 「这一轮有多少是新的」算的是折叠前的数。
    after: tuple[str, ...] = ("facts",)

    async def after_prepare(self, st: State) -> None:
        # 一次跑的 id。放 `bag` 里**跟账本同生共死**：轮末暂停会把 bag 序列化
        # 进快照，恢复之后还是同一次跑，`harness_rounds` 里的行才连得起来。
        if not st.bag.get("run_id"):
            import uuid
            st.bag["run_id"] = uuid.uuid4().hex[:12]
        led = ledger_of(st)
        calls = st.trace.calls if st.trace is not None else []
        st.bag["ledger_round"] = fold(led, calls)

    async def after_judge(self, st: State) -> None:
        led = ledger_of(st)
        mark_used(led, st.content)
        stat = st.bag.get("ledger_round") or {}
        try:
            from ...database import store
            scores = ({n: s.level for n, s in st.ev.scores.items()} if st.ev else {})
            store.record_harness_round(
                key=f"{st.mode.key}:{st.ctx.note_id}",
                run_id=st.bag.get("run_id") or "",
                round_=st.round,
                scores=scores,
                status=(st.ev.status if st.ev else "unscored"),
                weakest=((st.ev.weakest or "") if st.ev else ""),
                content_len=len(st.content or ""),
                facts_new=int(stat.get("facts_new") or 0),
                facts_total=len(led["facts"]),
                tool_calls=int(stat.get("tool_calls") or 0),
                repeat_calls=int(stat.get("repeat_calls") or 0))
        except Exception:                                   # noqa: BLE001
            pass        # 记账不承重：写不进去也不能影响这一轮的产出
