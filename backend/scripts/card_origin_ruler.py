"""**底下那 5 张记忆卡里，哪几张是「前一段带回来的」**——P83 A 那把尺。

    KITE_DATA_DIR=... .venv/bin/python scripts/card_origin_ruler.py         # 核对，对不上 exit 9
    KITE_DATA_DIR=... .venv/bin/python scripts/card_origin_ruler.py --list 20   # 看前 20 条长什么样

## 它答的是哪一句

P80 查明：右栏那一行的词**有些是从前一段带进来的**（`RECALL_CONTEXT_BEFORE = 200` 把前一段
拼进了查询），并且**只改了那一行**——屏幕上现在会说「前一段带进来的」了。
**但底下那 5 张记忆卡还是混着的**：哪几张是因为「光标这一段」捞回来的、
哪几张是因为「前一段」捞回来的，用户一点提示都没有。

这把尺在真语料上把那句话量成数：**卡一共几张、其中几张属于「前一段」那一档、
几条查询是两种卡混着摆的、几条查询整屏全是前一段的**。

## 判据（跟前端 `recallContext.cardFromBefore` 逐行对应）

**两条都成立才算**，照抄 P80 立的形状：

  ① 这张卡里**一个「光标这段里的命中词」都没有**（**一票否决**，不是多数决）；
  ② 这张卡里**至少有一个「前一段带进来的命中词」**（`termFromBefore` 那两条：
     不在光标这段里 _且_ 确实在前一段那一截里）。

拿哪几个词去判，走 `evidence_pool`，**三档跟 `evidenceLine` 逐字同一条**
（有证据 → 证据的词；`[]` → 一个都不拿；没这一格 → 退回 `terms`）。

⚠️ **这把尺够不着什么**（照 P72 的规矩写在闸身上）：

  · **它量的是 `out[:8]` 的前 5 条，没走 `factInBody` 那道折叠**。产品那边
    `fresh` 会先把「已经写在正文里的原话」折起来再取 5 条，而那道门要**整篇正文**；
    这把尺按 `(用户, 查询)` 全局去重之后，一条查询对应的正文**不唯一**。
    所以这四个数是**上界口径**——「最多有这么多张卡会被盖戳」。
    要换成产品口径就得放弃去重，而去重正是 765 那把尺跟 P38–P81 十几批对得上的理由。
  · **这个戳该不该盖**：一条都答不了。它只管「照这条判据会盖几张、盖在哪儿」。
  · **前端那一份是不是还长这样**：`check_source()` 单独钉（读的是真源文件），
    跟 `recall_ruler.check_paragraph_at_source` 同一条路。
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database.kb import search as kb_search  # noqa: E402
from app.database.kite.kite_memory import UserMemory  # noqa: E402
from scripts import recall_ruler  # noqa: E402

# 两个数逐字抄自 `frontend/src/components/RelatedMemory.tsx`。**改那边就得改这边**，
# 闸在 `check_source()`（读的是真源文件）。
# **名字照 `kb_search_ruler.SHOW` 那条先例起**：这两个是「抄产品的数」，得能被
# `floor_ruler.WATCHED_NAME` 扒到并登记，不然它们是这把尺身上唯一没人守的数。
MAX_ASKED = 8   # 产品 `RelatedMemory.RECALL_LIMIT`：一次问后端要几条（`out[:8]`）
SHOW = 5        # 产品 `RelatedMemory.LIST_MAX`：屏幕上最多摆几张卡

# 钉死的量程。**这六个数是这把尺自己的身份**：对不上说明判据或语料变了，
# 那一刻 P83 A 那一节所有拿它当分母的数全部失效——所以宁可 `exit 9`。
# 出处：P83 A 在 `KITE_DATA_DIR=<scratch>/p83data`（= 真 `backend/data` 整棵拷）上实测。
EXPECT_CARDS = 977            # 727 条 cursor 查询一共摆出几张卡（上界口径，见文件头）
                              # ⚠️ P84 从 964 涨到 977：那条「泛词 vs 主题词」的轴在小库上
                              # 把 63 个串从 `common` 手里捞了回来，`terrence-rewrite` 上
                              # 多摆出 13 张卡。**P83 A 那四个数（133 / 62 / 29 / 33）一格没动**
                              # ——动的只有分母。
EXPECT_MARKED = 133           # 其中几张会被盖上「前一段带进来的」
EXPECT_QUERIES_WITH_MARK = 62 # 几条查询屏幕上至少有一张被盖
EXPECT_MIXED = 29             # **几条查询是两种卡混着摆的**（这一批要修的正是这一格）
EXPECT_ALL_MARKED = 33        # 几条查询整屏 5 张全是前一段带回来的
EXPECT_WITH_CARDS = 314       # 727 条里几条真摆出了卡（其余 413 条一张都没有）
                              # ⚠️ P84 从 312 涨到 314：两条原来 0 张卡的小库查询现在摆得出卡了


def term_from_before(term: str, paragraph: str, before: str) -> bool:
    """`recallContext.termFromBefore` 的逐行对应。两条都成立才算。"""
    if not term or not before:
        return False
    return (term not in recall_ruler.clean(paragraph or "")) and (term in before)


def evidence_pool(evidence: list[dict] | None, terms: list[str]) -> list[str]:
    """`recallContext.evidencePool` 的逐行对应。三档跟那一行同进同退。"""
    if evidence:
        return [e["term"] for e in evidence]
    if evidence is not None:
        return []
    return list(terms)


def card_from_before(text: str, pool: list[str], paragraph: str, before: str) -> bool:
    """`recallContext.cardFromBefore` 的逐行对应。"""
    body = recall_ruler.clean(text or "").lower()
    if not body or not before:
        return False
    in_para = recall_ruler.clean(paragraph or "")
    from_before = False
    for t in pool:
        if not t or t not in body:
            continue
        if term_from_before(t, paragraph, before):
            from_before = True
        elif t in in_para:
            return False      # ① 一票否决
    return from_before


def walk(db: Path | None = None) -> dict:
    """全语料走一趟。返回四个数 + 每条查询的明细。"""
    rows = [r for r in recall_ruler.queries_ctx(db) if r[2] == "cursor"]
    mems: dict[str, UserMemory] = {}
    cards = marked = with_cards = mixed = all_marked = 0
    detail: list[dict] = []
    for i, (user, q, _mode, origin, para, before) in enumerate(rows):
        mem = mems.get(user)
        if mem is None:
            mem = mems[user] = UserMemory(user)
        facts, terms, _took = mem.recall(q, limit=MAX_ASKED, evidence=True)
        if not facts:
            continue
        with_cards += 1
        try:
            ev: list[dict] | None = mem.recall_evidence(q, facts)
        except Exception:      # noqa: BLE001 — 解释是附赠的，跟 /recall 同一条
            ev = None
        pool = evidence_pool(ev, kb_search.display_terms(terms, q, segment=mem.segment()))
        shown = facts[:SHOW]
        hit = [bool(card_from_before(f.get("text") or "", pool, para, before)) for f in shown]
        cards += len(shown)
        marked += sum(hit)
        if any(hit):
            if all(hit):
                all_marked += 1
            else:
                mixed += 1
            detail.append({"i": i, "user": user, "origin": origin, "cards": len(shown),
                           "marked": sum(hit), "query": q[:70]})
    return {"queries": len(rows), "with_cards": with_cards, "cards": cards, "marked": marked,
            "mixed": mixed, "all_marked": all_marked,
            "queries_with_mark": mixed + all_marked, "detail": detail}


def check_source() -> list[str]:
    """前端那一份**还是不是我们抄的这一份**（同 `recall_ruler.check_paragraph_at_source`）。

    钉的是**那两条判据本身**和**它被真的用在了卡上**，不是一句注释——
    「文件里有这个串 ≠ 这段代码还在跑」，所以先把整行注释摘掉再找。
    """
    bad: list[str] = []
    ctx = BACKEND.parent / "frontend" / "src" / "util" / "recallContext.ts"
    comp = BACKEND.parent / "frontend" / "src" / "components" / "RelatedMemory.tsx"
    if not ctx.is_file() or not comp.is_file():
        return ["找不到 recallContext.ts / RelatedMemory.tsx——这把尺抄的那一份没法核"]
    def bare(p: Path) -> str:
        out = []
        block = False
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if block:
                if "*/" in s:
                    block = False
                continue
            if s.startswith("/*"):
                block = "*/" not in s
                continue
            if s.startswith("//") or s.startswith("*"):
                continue
            out.append(line)
        return "\n".join(out)
    t, c = bare(ctx), bare(comp)
    for need in ("export function cardFromBefore(",
                 "if (!body || !before) return false",
                 "if (termFromBefore(t, paragraph, before)) fromBefore = true",
                 "else if (inPara.includes(t)) return false",
                 "export function evidencePool("):
        if need not in t:
            bad.append(f"`recallContext.ts` 里找不到 `{need[:56]}`")
    for need in ("const pool = evidencePool(evidence, terms)",
                 "cardFromBefore(text, pool, qCtx.paragraph, qCtx.before)",
                 "fromBefore(f.text) &&",
                 "mem-card-from-before"):
        if need not in c:
            bad.append(f"`RelatedMemory.tsx` 里找不到 `{need[:56]}`（**盖戳那一步没在跑**）")
    for name, want in (("RECALL_LIMIT", MAX_ASKED), ("LIST_MAX", SHOW)):
        if f"const {name} = {want}" not in c:
            bad.append(f"`RelatedMemory.tsx` 的 `{name}` 不再是 {want}——这把尺抄的两个数飘了")
    return bad


def check(g: dict) -> list[str]:
    bad = []
    for name, got, want in (("卡总数", g["cards"], EXPECT_CARDS),
                            ("盖上戳的卡", g["marked"], EXPECT_MARKED),
                            ("有戳的查询", g["queries_with_mark"], EXPECT_QUERIES_WITH_MARK),
                            ("混着摆的查询", g["mixed"], EXPECT_MIXED),
                            ("整屏全是前一段", g["all_marked"], EXPECT_ALL_MARKED),
                            ("摆出了卡的查询", g["with_cards"], EXPECT_WITH_CARDS)):
        if got != want:
            bad.append(f"{name}: {got} ≠ {want}")
    return bad


def main(argv: list[str]) -> int:
    g = walk()
    print(recall_ruler.identity(recall_ruler.queries()))
    print(f"记忆卡那把尺：cursor {g['queries']} 条 / 摆出了卡 {g['with_cards']} 条 / "
          f"卡 {g['cards']} 张（{SHOW} 张封顶，`out[:{MAX_ASKED}]` 之后）；"
          f"盖上「{'前一段带进来的'}」{g['marked']} 张；"
          f"有戳的查询 {g['queries_with_mark']} 条（**混着 {g['mixed']}** · 整屏全是 {g['all_marked']}）")
    if "--list" in argv:
        i = argv.index("--list")
        n = int(argv[i + 1]) if len(argv) > i + 1 else 10
        for d in g["detail"][:n]:
            print(f"  i={d['i']} [{d['origin']}] {d['user']} {d['marked']}/{d['cards']} 张 {d['query']!r}")
    bad = check(g) + check_source()
    if bad:
        print("尺子对不上钉死的量程：" + "；".join(bad), file=sys.stderr)
        print("**这一刻 P83 A 那一节拿它当分母的数都失效了**——先查判据 / 语料，别换尺子继续量。",
              file=sys.stderr)
        return 9
    print(f"ruler OK = {EXPECT_CARDS} 张卡那把尺（P83 A 那四个数 "
          f"{EXPECT_MARKED}/{EXPECT_QUERIES_WITH_MARK}/{EXPECT_MIXED}/{EXPECT_ALL_MARKED} "
          f"逐格相同；分母 P84 从 964 抬到 977）；前端那两份判据还在原地")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
