"""**页边圆点那把尺**：哪一段判出什么关系、画不画点、六档各几个。

    .venv/bin/python scripts/margin_dot_ruler.py           # 三档全跑，对不上 exit 9
    .venv/bin/python scripts/margin_dot_ruler.py dots      # 只跑五篇的圆点
    .venv/bin/python scripts/margin_dot_ruler.py walk      # 只跑走查第 ③ 步那篇
    .venv/bin/python scripts/margin_dot_ruler.py tableb    # 只跑 D2 表 B（末 500 字那一档）

**为什么它必须在仓库里**（P63）：P60 记的「圆点 172 段 / 判出 140 / 真画 34」
下一批**复现不出来**——量它的脚本跟 `$S/p60/` 一起被清了。P61 另写一把量到
166 / 137 / 31，并当场发现差在哪：**P4 那一版的「N1」跟今天的不是同一篇正文**
（26,714 字 / 136 段 → 30,588 字 / 140 段，同一个 note id）。

所以这一份把**哪五篇**钉到 `NOTES` 里，而且钉的不只是 id，还有**字数和正文 sha8**
——「同一个 id 两版正文」正是 P60 那个数复现不出来的全部原因。对不上就 `exit 9`。

---

## 口径（逐行对着产品里那条路）

**哪些段落拿去判**（`frontend/src/editor/marginMemory.ts` 的
`paragraphsWithLines` + `marginParagraphs`）：连续的非空行算一段；
`clean_query` 之后 **含数字 · 不是 `#` 标题 · ≥8 字**。
⚠️ 这跟 765 条那把尺的段落口径**不是一回事**（那边按空行 `\\n\\s*\\n` 切、不要求含数字），
两把尺量的是两件事，别互相套。

**怎么判**（`app/routers/memory.py` 的 `relations_batch` 逐字）：
`recall(limit=8, scope='all')` → `_live()` 滤掉被取代 / 合并掉的 → `kb_relations.detect()`
→ 取 `cands[0]`（`detect` 收尾已按 冲突 > 延续 > 缺依据 > 叠加 > 合并 > 印证 排好）。
**不开证据闸**（`evidence` 那一档是右栏「记忆」那条路走的，不是圆点这条）——
P32「差点砍错的那一刀」原样成立。

**画不画**（`marginMemory.dotWorthy`）：`unsupported` 且 `why == 'no_record'` **不画**
（那是整篇的属性不是这一段的，逐段画就是把同一句话说 89 遍）；其余都画。

## 六档，不是四档（P63 #2）

关系一共**六种**（`kb/relations.py` 顶上那张表、`marginMemory.RELATION_LABEL`
那六个键、`styles.css` 的 `.mm-conflict/.mm-continuation/.mm-corroborated/
.mm-unsupported/.mm-accumulation/.mm-merge`）。P52 / P58 / P60 三批的台账只摆了**四档**
（冲突 / 印证 / 缺依据 / 合并），**加起来对不上合计**——所以这把尺一律六档齐打，
少一档就不是一张能加得起来的表。
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
# `corpus_lineage` 里是裸的 `import db_guard`——见 `recall_ruler.py` 同一处的注释。
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database.kb import relations as kb_relations  # noqa: E402
from app.database.kite.kite_memory import UserMemory  # noqa: E402
from app.routers.memory import _live  # noqa: E402
from scripts import corpus_lineage, db_guard, recall_ruler  # noqa: E402

USER = "terrence"
RECALL_LIMIT = 8          # `relations_batch` 那一行
SCOPE = "all"             # 圆点走全库范围
MIN_CHARS = 8             # `marginParagraphs`
TABLEB_TAIL = 500         # D2 表 B：末 500 字
TABLEB_LIMIT = 5          # D2 表 B：`limit=5` + `evidence=True`

# 六档，顺序 = `detect()` 收尾那张排序表（最要紧的在前）。**一律六档齐打。**
KINDS = ("conflict", "continuation", "unsupported", "accumulation", "merge", "corroborated")
LABEL = {"conflict": "冲突", "continuation": "延续", "unsupported": "缺依据",
         "accumulation": "叠加", "merge": "合并", "corroborated": "印证"}

# **哪五篇、哪一版**。id 不够——P60 那个复现不出来的 172 就是「同一个 id 两版正文」。
# 字数 + 正文 sha8 一起钉，对不上 exit 9。
NOTES: dict[str, tuple[str, int, str]] = {
    "N1": ("309f19202309", 30588, "d912e3bc"),   # 「公司汇报：」——P4 那一版是 26,714 字的另一版
    "N2": ("92d07b760f1e", 4889, "2f798c10"),    # 「未命名」（我们产品当前遇到的挑战）
    "N3": ("c3464ab74c7d", 2767, "db88aa8e"),
    "N4": ("e78306202d78", 1976, "d8abf2df"),    # 批 14 那次事故里掉到 650 字、从备份救回来的那篇
    "N5": ("603dca25403a", 810, "0565827b"),     # P61 #2 那篇：换完量程召回仍然是 0
}

# 走查第 ③ 步那篇（`1bcd5b418142`）。它是**走查当场新建**的，真库里没有，
# 所以正文逐字写在这里：`$S/p60/steps/b1old.mjs` 的 `SEED` + 那一串按键
# （`# 标题` Enter Enter → ⌘End Enter Enter → 每段 Enter Enter）。
# 两处独立核过、都对得上 `$S/p60/log/b1b.txt`：**105 字**、**「预热名单」在第 8 行**（0 起）。
WALK_SEED = (
    "P58 走查：这一批在改屏幕活动那条线上的三处。",
    "众筹页面那一版文案是 3 月 12 号上线的，当天点击 12700。",
    "预热名单回收了 860 份，转化率按渠道排了一遍。",
)
WALK_CONTENT = "# P58 走查（可删）" + "\n\n\n\n" + "".join(s + "\n\n" for s in WALK_SEED)
WALK_CHARS = 105
WALK_DOT_LINE = 8

# 右栏「记忆」顶上的**图例**每一档一颗 `.mm-dot`（`components/RelatedMemory.tsx`
# 那个 `Object.keys(RELATION_LABEL).map`）——**六颗，而且不在落槽里**。
# 这个常数摆在这儿是因为它是 P52 / P58 / P60 三批那个「圆点 8 个」的一半以上，
# 详见下面 `walk` 那一档的注释。
LEGEND_DOTS = len(KINDS)

# 钉死的量程。出处：`dots` 那一档 = P61 收尾（166 / 137 / **31**）→ **P69 ① 改成 33**；
# `walk` / `tableb` 两档 = P63 第一次量（`tableb` 的 8 条跟 P61 记的逐条相同）。
#
# **31 → 33 那两颗，读完了才改的这个数**（P67 ① 量出来、这一批读的，账在
# `docs/TRACELOG-product.md` P69 ①）。伪相关反馈的种子从 `scored[:2]` 收到 `[:1]` 之后，
# N1（`309f19202309`）的**两段**从「判出 `unsupported`/`no_record`、不画」翻成
# 「`no_value`、画」——**翻的不是画不画那道门，是 `kb_relations.detect` 里 `related` 空不空**：
#
#   · **L350**「华为已经合作了 TOP100 里的 53 家银行……180 多家合作伙伴」
#     改之前召回回来的 8 条里有 5 条是**雇主华为**那堆闲聊（「一堆华为的人去了之后，
#     会议室永远都是拍马屁的声音」「我没有针对华为这家公司」），**一条都不沾边** → `no_record`；
#     改之后进来的是 `apple-…` 那篇**华为公司介绍**，其中「提供完整的产品组合和整体解决方案」
#     跟这一段共用 `解决方案` + `客户` 两条实词证据（overlap 0.154）→ 沾边了，
#     于是这句话变成「库里沾边的记录都没带这段里的量——53 家 / 75% 还没有出处」。**这一颗真该亮。**
#   · **L208**「广西南宁中国燃气交付中，一期交付 2000 套……深圳特安」
#     过门槛的只有一条「我们目前做国内大概做 200 家客户，70% 在深圳」（overlap 0.182），
#     而它那两条共用证据是 `深圳`（正文里是伙伴名「深圳特安」，事实里是「70% 在深圳」，
#     **同一个词面两个用法**）+ `200`（**是「2000 套」的子串**）。**这一颗勉强**——
#     但它说的那句话不假（「2000 套」库里确实没有出处），而改之前那一屏 8 条全是
#     ODI / 深圳发改委，比它更不相干。
#
# 两颗都不是**假的**「缺依据」，一颗真对一颗勉强 → 这一栏判为**没跌**，数改成 33。
# **判出那一档没动**（137，逐档也一样）：翻的只是 `unsupported` 的 `why`。
EXPECT = {
    "dots": {"segments": 166, "judged": 137, "drawn": 33},
    "walk": {"segments": 3, "judged": 2, "drawn": 2},
    "tableb": {"facts": 8},
}


def margin_paragraphs(content: str) -> list[tuple[int, str]]:
    """`paragraphsWithLines` + `marginParagraphs` 的逐行 Python 对应。[(1 起的行号, 正文)]"""
    out: list[tuple[int, str]] = []
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        start = i
        buf: list[str] = []
        while i < len(lines) and lines[i].strip():
            buf.append(lines[i])
            i += 1
        t = recall_ruler.clean("\n".join(buf)).strip()
        if re.search(r"\d", t) and not t.startswith("#") and len(t) >= MIN_CHARS:
            out.append((start + 1, t))
    return out


def dot_worthy(relation: str, why: str | None) -> bool:
    """`marginMemory.dotWorthy` 逐字。"""
    return not (relation == "unsupported" and why == "no_record")


def judge(mem: UserMemory, common, passage: str) -> dict | None:
    """`relations_batch` 里那一段逐字：召回 → `_live` → `detect` → `cands[0]`。"""
    rows, _terms, _took = mem.recall(passage, limit=RECALL_LIMIT, scope=SCOPE)
    cands = kb_relations.detect(passage, _live(mem, rows), common=common)
    return cands[0] if cands else None


def _note_contents() -> dict[str, str]:
    """把五篇读出来，**顺便核出身**：字数 + 正文 sha8 + **血缘**，对不上就抛。

    血缘走 `corpus_lineage.classify`（**不另写一份夹具名单**）。这五篇是台账上
    「四栏留下率」的语料，必须是**用户真写的**那一类：批 4 就栽在 31 篇里混进一篇
    47k 字的合成探针，同一个数差了一个数量级。这里不筛——五篇是点名的——
    但混进一篇 `script` / `fixture` 就当场抛，别等下一批拿着它算比例。
    """
    import hashlib
    conn = db_guard.readonly(BACKEND / "data" / "notes.sqlite3")
    lineage = corpus_lineage.load_lineage(conn)
    out: dict[str, str] = {}
    bad: list[str] = []
    for name, (nid, chars, sha8) in NOTES.items():
        row = conn.execute("SELECT user_id, title, content FROM notes WHERE id=?",
                           (nid,)).fetchone()
        if row is None:
            bad.append(f"{name} ({nid}) 这篇不在库里")
            continue
        c = row["content"] or ""
        got = hashlib.sha256(c.encode()).hexdigest()[:8]
        if (len(c), got) != (chars, sha8):
            bad.append(f"{name} ({nid}): {len(c)}字/{got} ≠ 钉死的 {chars}字/{sha8}")
        o = corpus_lineage.classify(row["user_id"], row["title"] or "", lineage.get(nid))
        if o.kind != corpus_lineage.ORIGIN_USER:
            bad.append(f"{name} ({nid}) 不是用户写的：{o.kind} —— {o.reason}")
        out[name] = c
    conn.close()
    if bad:
        raise SystemExit("五篇的出身对不上，这把尺量出来的数没有意义：\n  " + "\n  ".join(bad)
                         + "\n（P60 那个复现不出来的 172 就是「同一个 id 两版正文」）")
    return out


def _tally(mem, common, paras) -> tuple[Counter, Counter]:
    judged: Counter = Counter()
    drawn: Counter = Counter()
    for _ln, p in paras:
        top = judge(mem, common, p)
        if not top:
            continue
        judged[top["relation"]] += 1
        if dot_worthy(top["relation"], top.get("why")):
            drawn[top["relation"]] += 1
    return judged, drawn


def _tier_line(c: Counter) -> str:
    return " · ".join(f"{LABEL[k]} {c.get(k, 0)}" for k in KINDS) + f"  = {sum(c.values())}"


def run_dots(mem, common) -> dict:
    """五篇 · 逐篇 · 六档齐。"""
    contents = _note_contents()
    total_j: Counter = Counter()
    total_d: Counter = Counter()
    segs = 0
    for name in NOTES:
        paras = margin_paragraphs(contents[name])
        j, d = _tally(mem, common, paras)
        segs += len(paras)
        total_j += j
        total_d += d
        print(f"  {name}: {len(paras)} 段 · 判出 {sum(j.values())} · 真画 {sum(d.values())}"
              f"   [{_tier_line(d)}]")
    print(f"  合计 {segs} 段 · 判出 {sum(total_j.values())} · 真画 {sum(total_d.values())}")
    print(f"    判出逐档: {_tier_line(total_j)}")
    print(f"    真画逐档: {_tier_line(total_d)}")
    return {"segments": segs, "judged": sum(total_j.values()), "drawn": sum(total_d.values())}


def run_walk(mem, common) -> dict:
    """走查第 ③ 步那篇，逐段逐档。

    **这一档回答的是 P62 留下的第 3 条**：P52 / P58 / P60 三批都写着
    「圆点 **8** 个（冲突 2 / 印证 1 / 缺依据 2 / 合并 1）」，四档加起来只有 6。
    P62 判成「另外 2 颗落在 `.mm-continues` / `.mm-adds` 两个永远选不到的空档里」——
    **也不对**。真相是量具那一行读的是 `document.querySelectorAll('[class*="mm-"]')`
    （**全文档、通配**），而右栏「记忆」的图例每一档挂着一颗 `.mm-dot`：

        8 = 图例 6 颗 + 落槽里真的 2 颗

    逐档对得上：冲突 2 = 图例 1 + 落槽 1；缺依据 2 = 图例 1 + 落槽 1；
    印证 1 / 合并 1 = 图例各 1、落槽 0；延续 / 叠加 的图例那两颗被死选择器读成了 0。
    **「选到两个 ≠ 真有两个」**（P62 立的）在这儿是「选到八个 ≠ 真有八个」。
    """
    assert len(WALK_CONTENT) == WALK_CHARS, f"{len(WALK_CONTENT)} ≠ {WALK_CHARS}"
    assert "预热名单" in WALK_CONTENT.split("\n")[WALK_DOT_LINE]
    paras = margin_paragraphs(WALK_CONTENT)
    judged: Counter = Counter()
    drawn: Counter = Counter()
    for ln, p in paras:
        top = judge(mem, common, p)
        if not top:
            print(f"  L{ln} 判不出                        {p[:34]!r}")
            continue
        judged[top["relation"]] += 1
        d = dot_worthy(top["relation"], top.get("why"))
        drawn[top["relation"]] += d
        print(f"  L{ln} {LABEL[top['relation']]}{'（画点）' if d else '（不画）'} "
              f"why={top.get('why') or '—'}  {p[:34]!r}")
    print(f"  {len(paras)} 段 · 判出 {sum(judged.values())} · **落槽里真的圆点 "
          f"{sum(drawn.values())} 颗**")
    print(f"    真画逐档: {_tier_line(drawn)}")
    print(f"    右栏图例另有 {LEGEND_DOTS} 颗 `.mm-dot`（六档各一，**不在落槽里**）"
          f" → 通配选择器读出来的 {sum(drawn.values()) + LEGEND_DOTS} 就是这么来的")
    return {"segments": len(paras), "judged": sum(judged.values()),
            "drawn": sum(drawn.values())}


def run_tableb(mem) -> dict:
    """D2 表 B：五篇各取**末 500 字**当查询，`limit=5` + `evidence=True`，数召回对。

    这是四栏留下率的第二栏。P46 / P54 / P56 在旁边打过「这个数没带参数」——
    因为它跟圆点那把一样，一直只在 scratch 里。
    """
    contents = _note_contents()
    total = 0
    for name in NOTES:
        q = recall_ruler.clean(contents[name][-TABLEB_TAIL:]).strip()
        rows, _t, _tk = mem.recall(q, limit=TABLEB_LIMIT, evidence=True)
        print(f"  {name}: {len(rows)} 条")
        total += len(rows)
    print(f"  合计 {total} 条")
    return {"facts": total}


def main(argv: list[str]) -> int:
    which = argv[0] if argv else "all"
    mem = UserMemory(USER)
    common = mem.common_term()
    print(f"ruler=margin-dot user={USER} limit={RECALL_LIMIT} scope={SCOPE} "
          f"min_chars={MIN_CHARS} evidence=off "
          f"notes={recall_ruler.notes_tag()} corpus={recall_ruler.corpus_tag(USER)}")
    got: dict[str, dict] = {}
    if which in ("all", "dots"):
        print(f"[dots] 五篇（{' '.join(f'{k}={v[0]}' for k, v in NOTES.items())}）")
        got["dots"] = run_dots(mem, common)
    if which in ("all", "walk"):
        print(f"[walk] 走查第 ③ 步那篇（{WALK_CHARS} 字，正文钉在脚本里）")
        got["walk"] = run_walk(mem, common)
    if which in ("all", "tableb"):
        print(f"[tableb] D2 表 B（末 {TABLEB_TAIL} 字 · limit={TABLEB_LIMIT} · evidence=True）")
        got["tableb"] = run_tableb(mem)
    bad = [f"{k}.{n}: {v} ≠ {EXPECT[k][n]}"
           for k, d in got.items() for n, v in d.items() if v != EXPECT[k][n]]
    if bad:
        print("尺子对不上钉死的量程：" + "；".join(bad), file=sys.stderr)
        print("**先查是语料变了还是判据变了，别换一把尺继续量。**", file=sys.stderr)
        return 9
    print("ruler OK = 钉死的那几档")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
