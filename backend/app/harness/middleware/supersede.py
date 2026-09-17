"""被取代的事实：取材时把「这条已经过时了」这件事补上（计划 2.2 / [LED] §10②）。

## 它治的是什么

`kb_conflicts` 这张表就在库里（`store.py` 的 `_SCHEMA`），摄入时由
`kb/inbox.scan_session` 写、由 `routers/kb.py` 的冲突收件箱读，用户在收件箱里
裁决之后落成事实上的 `superseded_by` 属性（`kite_memory.set_fact_attr`）。

**而写作 harness 全仓没有一处读它。**

后果很具体：知识库知道「8 月 5 日那条取代了 6 月 3 日那条」，而续写的时候
没人问，**两条都可能被取出来、都可能被写进正文**。`factual_grounding` 的判词
要的正是「没有跟事实矛盾的说法」——**而它自己判不出哪条是旧的**：两条在材料
块里长得一模一样，都带 id、都带日期、都真实存在于知识库。

## 两个来源，两种待遇，因为它们的可信度差一整档

| 来源 | 是什么 | 这里怎么用 |
|---|---|---|
| `mem.fact_attrs("superseded_by")` | **人已经裁决过**（收件箱点了 new_wins / old_wins，或者合并过） | 标进账本，**并把取代它的那条一起带回来** |
| `kb_conflicts` 里 `status='open'` 的行 | 摄入时检出的**候选**，还没人裁决 | 只挂一句「这两条对不上，都别当定论」，**不声称谁取代谁** |

open 那一档为什么不敢当成取代——**依据只有一条，就是这一条**：
`harness/conflict_confirm.py` 开头记着的那次实拍，新用户导入**两篇真会议记录**，
收件箱里**两条候选全是误报**（「竞品 Plaud 的定价是 159 美元」跟「我们的定价是
199 美元」根本不是同一个量）。同一处还记着量级：20406 条的真库上抽 2500 条，
冲突候选一共只触发 4 次（0.16%）——**候选本来就稀少，而稀少的那几条里已知的
全是误报**。**拿未裁决的候选去把一条正确的事实标成「过时」，是误伤**，
而铁律写着「判据宁可窄一点，误伤比漏报贵」。

**这里原来写的是另一条依据，它是假的**（台账批 11 H1 自验）：上一版拿本机
开发库里那几行 open 冲突算了个「四分之三是误报」的比例当实证。那几行**全部**
属于 `fresh678` / `fresh678b` / `shot-demo` 三个**夹具用户**，真实用户名下
**一行都没有**——拿夹具的行去算比例，正是 `scripts/corpus_lineage.py` 整个模块
在禁止的那种数。顺带一个必须说出来的事实：**这条 middleware 的两条分支在真实
用户身上目前都是零流量**（已裁决的 `superseded_by` 属性一个都没有，真实用户名下
未裁决的冲突也一个都没有），它的价值要等收件箱真被用起来才兑现——
今天它是对的，但今天不产生收益。

闸在 `tests/test_corpus_lineage.py`：产品代码里不许再出现「拿本机库的行当依据」
的论断（那份名单是白名单制，每加一条都要写清楚这个数出自哪次真跑）。

## 为什么是单独一个 middleware，不是塞进 Ledger

账本那一版的承诺是「只记不改」，而这一条**会往 `st.facts` 里加东西**——它是
这一批唯一改变材料的改动。单独一个文件、单独一个名字，从 `BASE` 里拿掉一行
就能回退，回退之后账本照记不误。
"""

from __future__ import annotations

from .ledger import LINE_CHARS, ledger_of
from ..score_context import NOTICE_MARK
from ..state import State

# 一轮最多往材料里补几条。补的是「更正」，不是新材料——真出现十几条，
# 那是知识库自己该收拾的事，不该让更正把这一节的正文挤没。
MAX_ADDED = 6


def replacement_line(new_id: str, text: str, when: str, old_id: str) -> str:
    """带回来的那条长什么样。

    **必须明写「取代了谁」**：只把新的那条混进材料里，模型看到的就是两条
    并列的矛盾事实，跟不带回来时一样判不出哪条新——那等于白取一次。
    """
    head = f"[{new_id}] " if new_id else ""
    date = f"（{when}）" if when else ""
    # 记号 `NOTICE_MARK` 是给打分那一侧的截断看的（`score_context.material`
    # 按它优先保留），不是装饰：不带记号的更正会被 6000 字那一刀切掉，
    # 而被它更正的那条旧事实留在前面——台账批 11 H2。
    return (f"{head}{text}{date}{NOTICE_MARK}"
            f"这条取代了 [{old_id}]，写的时候以这条为准")


def conflict_line(fid: str, other_id: str, say: str) -> str:
    """未裁决的冲突：只提醒，不裁决。`say` 是摄入时写下的那句人话，
    里面已经带着另一边的日期和数值（「跟知识库 2026-03-04 的记录不一致：
    那里是 199美元，你写的是 159美元」），不用再去取一次事实。"""
    tail = f"：{say}" if say else ""
    return (f"{NOTICE_MARK}[{fid}] 跟 [{other_id}] 的记录对不上，**知识库里这条冲突"
            f"还没裁决，两条都别当定论**{tail}")


def _pairs(conflicts: list[dict]) -> dict[str, tuple[str, str]]:
    """`事实 id → (另一边的 id, 那句人话)`。两边都进——取回来的可能是任一边。"""
    out: dict[str, tuple[str, str]] = {}
    for row in conflicts or []:
        new_id, old_id = row.get("new_fact_id") or "", row.get("old_fact_id") or ""
        say = row.get("say") or ""
        if new_id and old_id:
            out.setdefault(old_id, (new_id, say))
            out.setdefault(new_id, (old_id, say))
    return out


def apply(led: dict, facts: list[str], *, superseded: dict[str, str],
          conflicts: dict[str, tuple[str, str]],
          lookup) -> tuple[list[str], int]:
    """纯函数那一半：账本 + 两张表 → 要补进材料的行。

    `lookup(fact_id) -> dict | None` 是「按 id 取一条事实」，由调用方注入——
    这样整条判断逻辑不用碰 KITE 就能测。
    """
    added: list[str] = []
    hits = 0
    for fid, row in list(led.get("facts", {}).items()):
        if len(added) >= MAX_ADDED:
            break
        new_id = superseded.get(fid)
        if new_id:
            if row.get("superseded_by") != new_id:
                row["superseded_by"] = new_id
            hits += 1
            fresh = lookup(new_id) or {}
            text = (fresh.get("text") or "").strip()
            if not text:
                # 取代它的那条自己都取不回来（id 漂了 / 被删了）。**不静默**：
                # 至少让写作知道这条已经不作数了，别拿它当定论。
                line = (f"{NOTICE_MARK}[{fid}] 已经被 [{new_id}] 取代，"
                        f"而那一条现在取不回来——这条别当定论。")
            else:
                when = fresh.get("when") or fresh.get("date") or ""
                line = replacement_line(new_id, text, when, fid)
                if new_id not in led["facts"]:
                    # 带回来的也是「我们手上有的材料」，账本要认得它。
                    led["facts"][new_id] = {"line": text[:LINE_CHARS],
                                            "state": "taken", "tool": "supersede",
                                            "when": when}
            if line not in facts and line not in added:
                added.append(line)
            continue
        pair = conflicts.get(fid)
        if pair:
            other, say = pair
            row["conflict_with"] = other
            line = conflict_line(fid, other, say)
            if line not in facts and line not in added:
                added.append(line)
    return added, hits


class Supersede:
    """取材之后、写作之前，把「这条已经被取代了」补进材料。"""

    name = "supersede"
    hooks = ("after_prepare",)
    # Facts 折完这一轮的 haul、Ledger 记完账之后才轮到它——它读的正是账本里
    # 那份「这次跑手上有哪些事实」。
    after: tuple[str, ...] = ("facts", "ledger")

    async def after_prepare(self, st: State) -> None:
        st.bag["superseded_round"] = 0
        led = ledger_of(st)
        if not led.get("facts") or not st.ctx.user:
            return
        try:
            from ...database import store
            from ...database.kite.kite_memory import UserMemory

            mem = UserMemory(st.ctx.user)
            attrs = mem.fact_attrs("superseded_by")
            open_rows = store.list_conflicts(st.ctx.user, status="open")
            added, hits = apply(
                led, st.facts,
                superseded={k: v for k, v in attrs.items() if k in led["facts"]},
                conflicts=_pairs(open_rows),
                lookup=mem.fact_by_id)
        except Exception:                                   # noqa: BLE001
            # 知识库读不出来不能让这一轮写不成。这条跟账本那条 try 是同一个
            # 原则：补充信息不承重。
            return
        st.bag["superseded_round"] = hits
        # **不按 `fact_budget` 再裁一刀**：这几行是更正，被挤掉的话，被更正的
        # 那条反而留在材料里，比不补更糟。条数已经封在 MAX_ADDED。
        #
        # 光在这儿不裁**不够**——台账批 11 H2：打分那一侧
        # （`score_context.material`）是从头累加、到 6000 字 `break`，而这里是
        # append 在末尾，于是「被更正的那条留下、更正行被切掉」在**那一侧原样
        # 发生**。修法不是改插入位置（写作那一侧不截断、打分那一侧截断，按位置
        # 修只对一个成立），是给每行打上 `NOTICE_MARK`，由截断那一侧认记号保留。
        st.facts = st.facts + added
