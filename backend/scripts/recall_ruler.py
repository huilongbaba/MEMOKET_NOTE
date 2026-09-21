"""**那把 765 条查询的尺子**：全库每一段正文按前端的口径生成召回查询，去重之后当量程。

    .venv/bin/python scripts/recall_ruler.py            # 打出身 + 核对，对不上 exit 9
    .venv/bin/python scripts/recall_ruler.py --list 20  # 顺带看前 20 条长什么样

**为什么它必须在仓库里**（P63，这是第三次为同一件事付钱）：
P34 / P38 / P42 / P44 / P46 / P48 / P60 / P61 八批的「全库对拍」全是拿这把尺量的，
而这把尺每批都是各自在 scratch 里现写一份 `ruler.py`。scratch 每批都会被清掉，于是：

  · P60 记的「圆点 172 段 / 判出 140 / 真画 34」**下一批复现不出来**——
    量它的脚本跟着 `$S/p60/` 一起没了（P61 拿新写的尺量到的是 166 / 137 / 31）；
  · P34 那 47 条标注、P59 那 284 轮 run json，都是同一个形状。

**一把量具进不了仓库，它量出来的数下一批就复现不出来。** 所以这一份带三样东西：
**口径写死在代码里**、**出身跟着数一起打出来**、**对不上就 `exit 9`**。

---

## 口径（跟前端逐行对应）

`frontend/src/util/recallContext.ts` 的 `recallQuery`：

  · 光标所在段落（`clean_query` 之后）≥ `RECALL_MIN_CHARS` 字、且不是 `#` 标题 →
    **前一段最多 `RECALL_CONTEXT_BEFORE` 字 + 本段**，记 `cursor`；
  · 否则退回**正文末 `RECALL_TAIL_CHARS` 字**，记 `tail`。

段落 = 空行分隔。按 `(用户, 查询)` **全局去重**、顺序稳定（按 `notes.id`）。
**只算 `KITE_DATA_DIR` 下 codebook 非空的用户**——没有知识库的人召回恒空，
算进去只会把分母灌水。

## 血缘：**带着走，但不筛掉**

每一条查询都带一个 `origin`（`corpus_lineage` 判的 `user` / `script` / `fixture`）。
**为什么不筛**：这把尺的用途是**同一组查询上两版代码的对拍**——
「改完之后哪几条的 top-8 变了」。分母是查询集合本身，不是用户数据的分布，
所以筛掉夹具只会让这把尺跟 P34–P61 八批的数**对不上**，而那正是它存在的理由。

**为什么还是要带着**：`corpus_lineage` 顶上那两条教训
（批 4 的 33.3% → 8.3%、批 6 的四条结论翻转）说的是**另一件事**——
「**拿这些查询算出来的比例**」。所以凡是要从这把尺上读出一个**比率**的，
必须先按 `origin` 分开看；`identity()` 每次都把三类各几条打出来，
省得下一批忘了这回事。**尺子不筛，读数的人分。**

## 出身

每次都打一行：三个参数 + **笔记库指纹** + **每个用户的 codebook 指纹** + 血缘分布。
照 `recall_selfcheck.py` 那条规矩——「同样的参数在不同语料上是不同的数」，
所以**整行抄进台账，出身跟着走**。
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
# `corpus_lineage` 里是 `import db_guard`（裸的），直接跑脚本时 `scripts/` 是 sys.path[0]
# 所以碰巧能跑；被 `from scripts import recall_ruler` 导进来时就没有了。
# **「直接跑能过」不等于「能用」**——把 `scripts/` 显式摆上去。
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database.kb import search as kb_search  # noqa: E402
from scripts import corpus_lineage, db_guard  # noqa: E402

# 三个参数逐字抄自 `frontend/src/util/recallContext.ts`。**改那边就得改这边**，
# 闸在 `tests/test_p63.py::test_765条尺子的三个参数跟前端逐字一致`（读的是真源文件）。
RECALL_TAIL_CHARS = 500
RECALL_MIN_CHARS = 8
RECALL_CONTEXT_BEFORE = 200

# 钉死的量程。**这四个数是这把尺自己的身份**：对不上说明口径或语料变了，
# 那一刻台账上所有拿它当分母的数全部失效——所以宁可 `exit 9`，不许悄悄换一把尺继续量。
# 出处：P38 / P42 / P44 / P46 / P48 / P60 / P61 七批收尾**逐格相同**。
EXPECT_TOTAL = 765
EXPECT_CURSOR = 727
EXPECT_TAIL = 38
EXPECT_USERS = 6

# ── **按库 × 血缘的分母**（P82 ①，新加）────────────────────────────────────────
#
# **为什么这一格要单独存在**：P81 ① 那一跤是「比率按血缘分，把 62.8% 平成了 6.9%」。
# 血缘（`user` / `script` / `fixture`）说的是**这段文字谁写的**，
# 而 `UserMemory.common_term()` / `_grep_index` / `unit_df` 全是**按人**建的——
# 同一个旋钮在 2362 unit 的 `terrence` 上翻 6.9%、在 193 unit 的 `terrence-rewrite`
# 上翻 62.8%。**要读比率，先看这张表，不是上面那行血缘分布。**
EXPECT_BY_LIB = {
    ("fresh678", "fixture"): 6,
    ("fresh678b", "fixture"): 6,
    ("fresh678c", "fixture"): 6,
    ("shot-demo", "fixture"): 20,
    ("terrence", "script"): 92,
    ("terrence", "user"): 549,
    ("terrence-rewrite", "script"): 86,
}

# ── **`common_term()` 那个旋钮的全库对拍**（P82 ①，`--cf-common`）──────────────
#
# 反事实：`kb/relations.py` 那段注释原来写着「库不到 333 个 unit 时这条判据等于不启用」。
# 这一支**把它真的做出来**（`unit_count * COMMON_DF_RATIO < COMMON_DF_MIN` 就回 `None`），
# 然后跟 HEAD 逐条比 top-8。**产品代码一个字节没改**——这里是尺子，不是那一刀。
#
# **这几个数是 P82 ① 判「换不了」的全部分量**（49 条逐条读完：变好 16 / 变差 23 / 中性 10，
# 标注在 `tests/fixtures/memory_sample.jsonl` 的 `p82-off333-49`）。任何一个动了，
# 那条判就得重读——尤其 `EXPECT_CF_COMMON_LIBS`：它说的是**这个旋钮只够得着一个库**，
# 一旦够得着第二个库，「按库分」那张表和 49 条标注的分母全部换人。
EXPECT_CF_COMMON_CHANGED = 49       # top-8 变了的查询数
EXPECT_CF_COMMON_DROP = 52          # 掉了的召回对
EXPECT_CF_COMMON_ADD = 140          # 进来的召回对
EXPECT_CF_COMMON_HIT = (341, 347)   # 有召回的查询数：HEAD → 反事实
EXPECT_CF_COMMON_LIBS = (("terrence-rewrite", 49),)   # 变了的那几条落在哪几个库上

# ── **P84 那条轴的全库对拍**（`--cf-spread`）──────────────────────────────────
#
# 反事实：**把 P84 那一问拆掉**——`common_term()` 回到「只看 df」。
# 于是这几个数读的是「**HEAD 相对于没有这条轴的样子**」：
# `变了` = top-8 变了的查询数；`进` / `掉` = HEAD 比反事实**多**了多少对 / **少**了多少对。
#
# **这几个数是 P84 判「接」的全部分量**（28 条逐条读完：变好 14 / 变差 7 / 中性 7，
# 标注在 `tests/fixtures/memory_sample.jsonl` 的 `p84-spread-28`）。任何一个动了，
# 那条判就得重读——尤其 `EXPECT_CF_SPREAD_LIBS`：它说的是**这条轴只够得着小库那一档**
# （`total * COMMON_DF_RATIO < COMMON_DF_MIN`），一旦够得着 `terrence`，
# **四栏那四个数就不再是「对这一刀是瞎的」，而是真被动过了**，得整批重读。
EXPECT_CF_SPREAD_CHANGED = 28       # top-8 变了的查询数
EXPECT_CF_SPREAD_ADD = 36           # HEAD 比「没有这条轴」多出来的召回对
EXPECT_CF_SPREAD_DROP = 16          # HEAD 比「没有这条轴」少掉的召回对
EXPECT_CF_SPREAD_HIT = (345, 341)   # 有召回的查询数：HEAD → 反事实
EXPECT_CF_SPREAD_LIBS = (("terrence-rewrite", 28),)   # 变了的那几条落在哪几个库上
# 这条轴在 `terrence-rewrite` 上真的从 `common` 手里捞回来的串。**63 一动**说明
# 语料、`SPREAD_GENERIC` 或者「只问汉字」那一条变了，28 条标注的分母跟着换人。
EXPECT_CF_SPREAD_RESCUED = 63

# ── **大库那一档到底接不接**（P86 ①，`--cf-bigcorpus`）────────────────────────
#
# P84 ⑤ 留的账：「大库上这条轴**一个反事实都没跑**……不限库大小那一版全库变 175 条
# （其中 `terrence` 134 条）——**量了形状，一条都没读**」。这一支把那 175 条**跑出来**，
# 而且把它**拆成两档**——因为「大库那一档接不接」和「英文那一半问不问」是**两个旋钮**，
# P84 那个 175 是**两个一起拆**量出来的，直接拿它去判大库会把两笔账混成一笔。
#
#   基准 V0 = 没有这条轴（`_df_only_common`，跟 `--cf-common` / `--cf-spread` 共用一份）
#   SIZE   = 只拆**库大小**那道闸，「只问汉字」那一条**原样留着** ← 判大库真正要看的那一档
#   BOTH   = 两道闸全拆                                        ← P84 ⑤ 记的那个 175
#
# 自检：`SIZE` / `BOTH` 在 `terrence-rewrite` 上必须跟 `EXPECT_CF_SPREAD_CHANGED`(28) /
# P84 ② 那个 41 各自对得上——小库那一档两支都不动它，对不上就是这一支接错层了。
#
# **这几个数是 P86 ① 判「大库不接」的全部分量**（175 条逐条读完，标注
# `tests/fixtures/memory_sample.jsonl` 的 `p86-bigcorpus-175`）：
# SIZE 那一档大库 25 条 **变好 8 / 中性 7 / 变差 10**（不是赢，是净亏，
# 跟小库那一档 14:7 的形状**相反**）；BOTH 那一档大库 134 条 **变好 14 / 中性 27 / 变差 93**。
EXPECT_CF_BIG_SIZE_CHANGED = 53      # 只拆库大小闸：top-8 变了的查询数
EXPECT_CF_BIG_SIZE_ADD = 108         # 它比「没有这条轴」多进来的召回对
EXPECT_CF_BIG_SIZE_DROP = 33         # 它比「没有这条轴」少掉的召回对
EXPECT_CF_BIG_SIZE_LIBS = (("terrence", 25), ("terrence-rewrite", 28))
EXPECT_CF_BIG_BOTH_CHANGED = 175     # 两闸全拆：**这就是 P84 ⑤ 记的那个 175**
EXPECT_CF_BIG_BOTH_ADD = 577         # 进 577 / 掉 80 —— 这个 7:1 的不对称本身就是判据：
EXPECT_CF_BIG_BOTH_DROP = 80         # 它不是「多召回一点」，是**把空屏灌满**（93/134 条变差）
EXPECT_CF_BIG_BOTH_LIBS = (("terrence", 134), ("terrence-rewrite", 41))

_HEAD = re.compile(r"^#{1,6}\s")


def data_dir() -> Path:
    """`KITE_DATA_DIR`（实验语料）或 `backend/data`（真语料）。"""
    return Path(os.environ.get("KITE_DATA_DIR") or (BACKEND / "data"))


def corpus_tag(user: str) -> str:
    """这个人的 codebook 有多大、内容摘要是什么（同 `recall_selfcheck._corpus_tag`）。

    P29 抓到过一份「拷贝」里 codebook 是 718 字节的空壳，而那一批所有「全库」的数
    都建在它上面——**症状是静默变差不是报错**。所以语料指纹跟数字绑在一起。
    """
    cb = data_dir() / user / "codebook.xml"
    if not cb.is_file():
        return "no-codebook"
    return f"{cb.stat().st_size}B/{hashlib.sha256(cb.read_bytes()).hexdigest()[:8]}"


def notes_tag(db: Path | None = None) -> str:
    """笔记库的出身：篇数 / 正文总长 / 逐篇摘要的哈希（口径走 `db_guard.fingerprint`）。

    **不自己另拼一个哈希**——P62 踩过：随手拼的那个口径不同、跟台账对不上，
    看起来像库变了，其实只是两把尺。
    """
    fp = db_guard.fingerprint(db or (BACKEND / "data" / "notes.sqlite3"))
    import json
    h = hashlib.sha256(json.dumps(fp.digests, sort_keys=True,
                                  ensure_ascii=False).encode()).hexdigest()[:16]
    return f"{fp.rows['notes']}篇/{fp.chars}字/{h}"


def clean(s: str) -> str:
    """前端 `stripForRecall` 的对应物（同一份实现：后端 `kb.search.clean_query`）。"""
    return kb_search.clean_query(s or "")


def recall_query3(content: str, paragraph: str) -> tuple[str, str, str]:
    """`recallContext.recallQuery` 的逐行 Python 对应。

    返回 (查询, `'cursor' | 'tail'`, **这一趟真的拼进查询的那一截前一段**)。
    第三格逐字对应前端 `RecallQuery.before`（已 `clean` 过；`tail` 档恒为 `''`）。

    **为什么是三格而不是另写一份**（P83 A）：判「这张记忆卡是不是前一段带回来的」
    要的正是那一截前一段，而它原来只活在这个函数的局部变量里。再抄一份切法出去
    就是**同一个口径两份实现**——`corpus_lineage` 顶上那条「每个脚本各写一份正是
    批 6 出事的原因」说的就是这件事。所以这儿只多交出一格，`recall_query`
    原样保留（它的两格返回值有六处调用点在用，签名一个字没动）。
    """
    para = (paragraph or "").strip()
    p = clean(para).strip()
    if len(p) >= RECALL_MIN_CHARS and not _HEAD.match(p):
        idx = content.find(para)
        before = content[max(0, idx - RECALL_CONTEXT_BEFORE):idx] if idx > 0 else ""
        before = re.sub(r"\s+$", "", before)
        cut = before.rfind("\n\n")
        if cut >= 0:
            before = before[cut + 2:]
        before = before.strip()
        if _HEAD.match(before):
            before = ""
        return clean((before + "\n" if before else "") + para).strip(), "cursor", clean(before).strip()
    return clean(content[-RECALL_TAIL_CHARS:]).strip(), "tail", ""


def recall_query(content: str, paragraph: str) -> tuple[str, str]:
    """`recall_query3` 的前两格。**实现只有一份**，这里只是把第三格丢掉。"""
    q, mode, _before = recall_query3(content, paragraph)
    return q, mode


def users_with_codebook() -> list[str]:
    """`KITE_DATA_DIR` 下 codebook 像样的用户。1000 字节那道门槛挡的是 P29 那种空壳。"""
    root = data_dir()
    return sorted(d.name for d in root.iterdir()
                  if d.is_dir() and (d / "codebook.xml").is_file()
                  and (d / "codebook.xml").stat().st_size > 1000)


def queries_ctx(db: Path | None = None) -> list[tuple[str, str, str, str, str, str]]:
    """`queries()` 再多带两格：**发这一问时的那两段**。

    [(用户, 查询, 'cursor' | 'tail', 血缘, **光标这段（原样，没 clean）**, **前一段那一截（clean 过）**)]

    去重、顺序、筛不筛**跟 `queries()` 逐字同一条**——因为它就是这一份，
    `queries()` 只是把后两格丢掉。**一份走法，两个投影**（P83 A：
    两份走法一定会在某一批悄悄飘开，而那时两边的数谁也不知道该信哪个）。
    """
    conn = db_guard.readonly(db or (BACKEND / "data" / "notes.sqlite3"))
    users = set(users_with_codebook())
    lineage = corpus_lineage.load_lineage(conn)
    rows = conn.execute("SELECT id, user_id, title, content FROM notes ORDER BY id").fetchall()
    conn.close()
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str, str, str, str]] = []
    for nid, user, title, content in rows:
        if user not in users or not content:
            continue
        origin = corpus_lineage.classify(user, title or "", lineage.get(nid)).kind
        for para in re.split(r"\n\s*\n", content):
            q, mode, before = recall_query3(content, para)
            if not q:
                continue
            key = (user, q)
            if key in seen:
                continue
            seen.add(key)
            out.append((user, q, mode, origin, para, before))
    return out


def queries(db: Path | None = None) -> list[tuple[str, str, str, str]]:
    """[(用户, 查询, 'cursor' | 'tail', 血缘)]，按 (用户, 查询) 全局去重、顺序稳定。

    血缘走 `corpus_lineage.classify`（**不另写一份夹具名单**——每个脚本各写一份
    正是批 6 出事的原因）。**一条都不筛**，理由在模块注释里。

    **它是 `queries_ctx()` 的前四格**——走法只有一份（P83 A）。
    """
    return [(u, q, m, o) for u, q, m, o, _p, _b in queries_ctx(db)]


def by_origin(qs: list[tuple[str, str, str, str]]) -> dict[str, int]:
    from collections import Counter
    c = Counter(o for *_r, o in qs)
    return {k: c.get(k, 0) for k in corpus_lineage.ORIGINS}


def by_lib(qs: list[tuple[str, str, str, str]]) -> dict[tuple[str, str], int]:
    """**(库, 血缘) -> 条数**（P82 ①）。要从这把尺上读比率，分母在这儿。"""
    from collections import Counter
    c = Counter((u, o) for u, _q, _m, o in qs)
    return dict(sorted(c.items()))


def identity(qs: list[tuple[str, str, str, str]]) -> str:
    """出身 + 量程，一行。**整行抄进台账。**"""
    users = sorted({u for u, *_r in qs})
    cur = sum(1 for _u, _q, m, _o in qs if m == "cursor")
    corp = " ".join(f"{u}={corpus_tag(u)}" for u in users)
    lin = " ".join(f"{k} {v}" for k, v in by_origin(qs).items())
    return (f"ruler=recall tail={RECALL_TAIL_CHARS} min={RECALL_MIN_CHARS} "
            f"before={RECALL_CONTEXT_BEFORE} notes={notes_tag()} corpus[{corp}]: "
            f"queries {len(qs)} (cursor {cur} / tail {len(qs) - cur}) users {len(users)} "
            f"血缘[{lin}]  ⚠️ 要算比率先按血缘分开")


# ---------------------------------------------------------------- 这把尺跟产品差在哪（P79 ③）
#
# **P78 ⑤ 留的那笔账**：「产品窗口是光标段 + 前一段约 200 字，而离线尺子喂的是整段 300 字
# ——两头量的不是同一条」。**这件事影响的是过去所有离线数**，所以它得先被量出来。
#
# 量法：两处**分段**口径逐行摆出来比。
#   · 离线（`queries()`）：`re.split(r"\n\s*\n", content)` ——**只按空行分段**；
#   · 产品（`frontend/src/components/MarkdownEditor.paragraphAt`）：光标那一行往上往下走到
#     空行为止，**标题行也算边界，而且标题行自己单独算一段**。
# 分完段两边喂的都是同一个 `recall_query`（三个参数逐字一致，`test_p63` 钉着）。
#
# ⚠️ **量出来跟 P78 ⑤ 的判断相反，照实记**（P79 ③）：
# 765 条里产品**产不出来的只有 1 条**（i=630：离线把一个前面没空行的 `### 标题`
# 粘进了段里）；剩下 764 条产品**原样产得出来**。P78 点名的 i=80 那 300 字
# **产品照样产得出来**，壳上读到的那条「约 200 字」是**下一段**（i=81）的查询
# ——同 P78 自己问题 #3 那个「右栏读回来的是上一段」的形状。**是量具，不是两把尺。**
# 反过来产品能产出 16 条离线没有的（全是「标题分节」那一档 + 3 条 tail 档）。
EXPECT_PROD_TOTAL = 780
EXPECT_ONLY_OFFLINE = 1
EXPECT_ONLY_PRODUCT = 16


def paragraph_at(lines: list[str], n: int) -> str:
    """`MarkdownEditor.paragraphAt` 的逐行 Python 对应（行号 1-based）。

    **改那边就得改这边**——闸在 `tests/test_p79.py`，读的是真源文件。
    """
    cur = lines[n - 1]
    if not cur.strip():
        return ""
    if _HEAD.match(cur):
        return cur.strip()
    a = b = n
    while a > 1 and lines[a - 2].strip() and not _HEAD.match(lines[a - 2]):
        a -= 1
    while b < len(lines) and lines[b].strip() and not _HEAD.match(lines[b]):
        b += 1
    return "\n".join(lines[a - 1:b]).strip()


def product_queries(db: Path | None = None) -> set[tuple[str, str]]:
    """产品那一头**光标停在任何一行**都能产生的 (用户, 查询)，同样全局去重。"""
    conn = db_guard.readonly(db or (BACKEND / "data" / "notes.sqlite3"))
    users = set(users_with_codebook())
    rows = conn.execute("SELECT user_id, content FROM notes ORDER BY id").fetchall()
    conn.close()
    out: set[tuple[str, str]] = set()
    for user, content in rows:
        if user not in users or not content:
            continue
        lines = content.split("\n")
        for n in range(1, len(lines) + 1):
            q, _mode = recall_query(content, paragraph_at(lines, n))
            if q:
                out.add((user, q))
    return out


def window_gap(db: Path | None = None) -> dict:
    """离线这把尺和产品那一头**差在哪几条**。"""
    off = {(u, q) for u, q, _m, _o in queries(db)}
    prod = product_queries(db)
    return {"offline": len(off), "product": len(prod),
            "only_offline": sorted(off - prod), "only_product": sorted(prod - off)}


def check_paragraph_at_source() -> list[str]:
    """产品那个 `paragraphAt` 还是不是我们抄的这一份（同 `test_p63` 那三个参数的做法）。"""
    src = (BACKEND.parent / "frontend" / "src" / "components" / "MarkdownEditor.tsx")
    if not src.is_file():
        return ["找不到 MarkdownEditor.tsx——`paragraph_at` 抄的那一份没法核"]
    t = src.read_text(encoding="utf-8")
    bad = []
    for need in ("export function paragraphAt(",
                 "if (!cur.text.trim()) return ''",
                 "if (/^#{1,6}\\s/.test(cur.text)) return cur.text.trim()",
                 "while (a > 1 && doc.line(a - 1).text.trim() && !/^#{1,6}\\s/.test(doc.line(a - 1).text)) a--",
                 "while (b < doc.lines && doc.line(b + 1).text.trim() && !/^#{1,6}\\s/.test(doc.line(b + 1).text)) b++"):
        if need not in t:
            bad.append(f"`paragraphAt` 里找不到 `{need[:60]}`")
    return bad


# ---------------------------------------------------------------- `common_term()` 反事实（P82 ①）

def _df_only_common(self):
    """**P84 之前那一版 `common_term()`：只看 df，一个字不多问。**

    P84 给 `UserMemory.common_term()` 加了第二段（小库那一档问一句「泛词还是主题词」），
    于是 `--cf-common` 的基准不能再是 HEAD——**P82 那 49 条量的是「只看 df」对「整条关掉」**，
    拿今天的 HEAD 当基准会把两条判据的差混进去，那 49 就不是 P82 那个 49 了。
    所以两支反事实共用这一份，P82 的数**逐格复现**。
    """
    from app.database.kb import relations as R

    store, _v = self._index()
    idx = self._grep_index(store)
    if idx is None or not idx.unit_count:
        return None
    total = idx.unit_count

    def is_common(term: str) -> bool:
        n = idx.unit_df(term, floor=R.COMMON_DF_MIN)
        return (n is not None and n >= R.COMMON_DF_MIN
                and n / total >= R.COMMON_DF_RATIO)
    return is_common


def cf_common_off(qs: list[tuple[str, str, str, str]] | None = None) -> dict:
    """「库不到 `COMMON_DF_MIN / COMMON_DF_RATIO` 个 unit 就不启用 `common`」的全库对拍。

    **两趟都是反事实、同一组查询、同一份索引缓存**：基准是 `_df_only_common`
    （P84 之前那一版），对照是「小库整条关掉」。**P84 之后基准不再是 HEAD**——
    理由逐字写在 `_df_only_common` 上面。
    回的是逐条的 top-8 差，读数的人按 `by_lib` 分（**别按血缘分**，理由在 `EXPECT_BY_LIB`）。
    """
    from collections import Counter

    from app.database.kb import relations as R
    from app.database.kite.kite_memory import UserMemory

    qs = qs or queries()
    mems: dict[str, UserMemory] = {}

    def run() -> list[list[str]]:
        out = []
        for user, q, _m, _o in qs:
            m = mems.get(user) or mems.setdefault(user, UserMemory(user))
            facts, _t, _ms = m.recall(q, limit=8, evidence=True)
            out.append([f.get("id") for f in facts])
        return out

    orig = UserMemory.common_term
    UserMemory.common_term = _df_only_common
    try:
        head = run()
    finally:
        UserMemory.common_term = orig

    def patched(self):
        fn = _df_only_common(self)     # ← 基准也是「只看 df」，两边只差「小库关不关」这一条
        if fn is None:
            return None
        store, _v = self._index()
        idx = self._grep_index(store)
        # **注释原来答应的那件事**：小到 6% 那条线够不着 `COMMON_DF_MIN` 时，整条判据不启用
        if idx is None or idx.unit_count * R.COMMON_DF_RATIO < R.COMMON_DF_MIN:
            return None
        return fn

    UserMemory.common_term = patched
    try:
        cf = run()
    finally:
        UserMemory.common_term = orig

    changed, drop, add = [], 0, 0
    for i, (a, b) in enumerate(zip(head, cf)):
        if a == b:
            continue
        changed.append(i)
        drop += sum(1 for x in a if x not in b)
        add += sum(1 for x in b if x not in a)
    libs = Counter(qs[i][0] for i in changed)
    return {"changed": changed, "drop": drop, "add": add,
            "hit": (sum(1 for x in head if x), sum(1 for x in cf if x)),
            "libs": tuple(sorted(libs.items()))}


def cf_spread_off(qs: list[tuple[str, str, str, str]] | None = None) -> dict:
    """「把 P84 那一问拆掉，`common_term()` 回到只看 df」的全库对拍。

    **先跑 HEAD 再跑反事实，同一组查询、同一份索引缓存**，只换 `UserMemory.common_term`。
    `add` / `drop` 读的是 **HEAD 相对反事实**：HEAD 多进来多少对、少掉多少对。
    读数的人按 `by_lib` 分（**别按血缘分**，理由在 `EXPECT_BY_LIB`）。
    """
    from collections import Counter

    from app.database.kb import relations as R
    from app.database.kite.kite_memory import UserMemory

    qs = qs or queries()
    mems: dict[str, UserMemory] = {}
    rescued: set[tuple[str, str]] = set()

    def run() -> list[list[str]]:
        out = []
        for user, q, _m, _o in qs:
            m = mems.get(user) or mems.setdefault(user, UserMemory(user))
            facts, _t, _ms = m.recall(q, limit=8, evidence=True)
            out.append([f.get("id") for f in facts])
        return out

    orig = UserMemory.common_term

    def watched(self):
        """HEAD 那一趟：顺手记下**哪些串真的被这条轴从 `common` 手里捞回来了**。"""
        fn = orig(self)
        if fn is None:
            return None
        store, _v = self._index()
        idx = self._grep_index(store)
        if idx is None or idx.unit_count * R.COMMON_DF_RATIO >= R.COMMON_DF_MIN:
            return fn
        total = idx.unit_count

        def wrap(term: str) -> bool:
            r = fn(term)
            if not r:
                n = idx.unit_df(term, floor=R.COMMON_DF_MIN)
                if (n is not None and n >= R.COMMON_DF_MIN
                        and n / total >= R.COMMON_DF_RATIO):
                    rescued.add((self.user_id, term))
            return r
        return wrap

    df_only = _df_only_common      # 反事实：P84 之前那一版（跟 `--cf-common` 共用一份）

    UserMemory.common_term = watched
    try:
        head = run()
    finally:
        UserMemory.common_term = orig
    UserMemory.common_term = df_only
    try:
        cf = run()
    finally:
        UserMemory.common_term = orig

    changed, drop, add = [], 0, 0
    for i, (a, b) in enumerate(zip(head, cf)):
        if a == b:
            continue
        changed.append(i)
        add += sum(1 for x in a if x not in b)     # HEAD 多出来的
        drop += sum(1 for x in b if x not in a)    # HEAD 少掉的
    libs = Counter(qs[i][0] for i in changed)
    return {"changed": changed, "drop": drop, "add": add,
            "hit": (sum(1 for x in head if x), sum(1 for x in cf if x)),
            "libs": tuple(sorted(libs.items())),
            "rescued": tuple(sorted(rescued))}


def _axis_variant(ask_size: bool, ask_cjk: bool):
    """`common_term()` 的一个反事实版本：那条轴的**两道闸各开各关**。

    `ask_size=True` = 只在小库问（HEAD 今天的样子）；`ask_cjk=True` = 只对汉字串问（同）。
    两个都 `True` 时**必须跟产品那一份逐条同结果**——`cf_bigcorpus()` 每次跑都拿这个自检，
    对不上就是这一支复刻错了，下面所有数当场作废（P84 那一课：接错层的量具会静静地给出漂亮的数）。
    """
    from app.database.kb import relations as R
    from app.database.kb import topic_face as TF

    def common_term(self):
        store, _v = self._index()
        idx = self._grep_index(store)
        if idx is None or not idx.unit_count:
            return None
        total = idx.unit_count
        small = total * R.COMMON_DF_RATIO < R.COMMON_DF_MIN

        def is_common(term: str) -> bool:
            n = idx.unit_df(term, floor=R.COMMON_DF_MIN)
            if not (n is not None and n >= R.COMMON_DF_MIN
                    and n / total >= R.COMMON_DF_RATIO):
                return False
            if ask_size and not small:
                return True
            if ask_cjk and not TF.has_cjk(term):
                return True
            face = self._topic_face(store, idx)
            if face is None:
                return True
            return face.generic(term) is not False
        return is_common
    return common_term


def cf_bigcorpus(qs: list[tuple[str, str, str, str]] | None = None) -> dict:
    """**大库那一档接不接**的全库对拍（P86 ①）。

    基准是 `_df_only_common`（没有这条轴），对照两档：只拆库大小闸 / 两道闸全拆。
    读数的人按 `by_lib` 分（**别按血缘分**，理由在 `EXPECT_BY_LIB`）。

    ⚠️ **两个旋钮别混成一个**：P84 ⑤ 记的那个 175 是**两闸全拆**量出来的，
    而「大库接不接」只该看 `size` 那一档。这也正是这一支要拆开跑的理由。
    """
    from collections import Counter

    from app.database.kite.kite_memory import UserMemory

    qs = qs or queries()
    mems: dict[str, UserMemory] = {}

    def run() -> list[list[str]]:
        out = []
        for user, q, _m, _o in qs:
            m = mems.get(user) or mems.setdefault(user, UserMemory(user))
            facts, _t, _ms = m.recall(q, limit=8, evidence=True)
            out.append([f.get("id") for f in facts])
        return out

    orig = UserMemory.common_term
    runs: dict[str, list[list[str]]] = {}
    for name, fn in (("v0", _df_only_common),
                     ("head_copy", _axis_variant(True, True)),
                     ("size", _axis_variant(False, True)),
                     ("both", _axis_variant(False, False)),
                     ("head", orig)):
        UserMemory.common_term = fn
        try:
            runs[name] = run()
        finally:
            UserMemory.common_term = orig

    # **接线自检**：复刻的 HEAD 必须跟产品那一份逐条同结果。
    mismatch = sum(1 for a, b in zip(runs["head_copy"], runs["head"]) if a != b)

    out: dict = {"selfcheck_mismatch": mismatch}
    for name in ("size", "both"):
        changed, drop, add = [], 0, 0
        for i, (a, b) in enumerate(zip(runs["v0"], runs[name])):
            if a == b:
                continue
            changed.append(i)
            add += sum(1 for x in b if x not in a)     # 对照多进来的
            drop += sum(1 for x in a if x not in b)    # 对照少掉的
        out[name] = {"changed": changed, "add": add, "drop": drop,
                     "libs": tuple(sorted(Counter(qs[i][0] for i in changed).items()))}
    return out


def check(qs: list[tuple[str, str, str, str]]) -> list[str]:
    """量程对不对。返回对不上的那几条（空 = 对得上）。"""
    cur = sum(1 for _u, _q, m, _o in qs if m == "cursor")
    users = len({u for u, *_r in qs})
    bad = []
    for name, got, want in (("queries", len(qs), EXPECT_TOTAL), ("cursor", cur, EXPECT_CURSOR),
                            ("tail", len(qs) - cur, EXPECT_TAIL), ("users", users, EXPECT_USERS)):
        if got != want:
            bad.append(f"{name}: {got} ≠ {want}")
    got_lib = by_lib(qs)
    if got_lib != EXPECT_BY_LIB:
        bad.append(f"按库分的分母变了: {got_lib} ≠ {EXPECT_BY_LIB}")
    return bad


def main(argv: list[str]) -> int:
    qs = queries()
    print(identity(qs))
    if "--list" in argv:
        i = argv.index("--list")
        n = int(argv[i + 1]) if len(argv) > i + 1 else 10
        for user, q, mode, origin in qs[:n]:
            print(f"  [{mode}/{origin}] {user} {q[:90]!r}")
    bad = check(qs)
    if "--by-lib" in argv:
        print("  按库 × 血缘（**要读比率就看这张，别看上面那行血缘分布**）：")
        for (u, o), n in by_lib(qs).items():
            print(f"    {u:18s}/{o:8s} {n:4d}")
    if "--cf-common" in argv:
        g = cf_common_off(qs)
        print(f"  `common` 小库不启用 那个反事实：top-8 变了 {len(g['changed'])} 条 / {EXPECT_TOTAL}"
              f"；掉 {g['drop']} 进 {g['add']}；有召回 {g['hit'][0]} → {g['hit'][1]}")
        print(f"    变了的落在：{g['libs']}  ⚠️ **这个旋钮只够得着这几个库**")
        print("    （49 条逐条读完：变好 16 / 变差 23 / 中性 10 → P82 ① 判「换不了」，"
              "理由在 `kb/relations.COMMON_DF_MIN` 那段注释）")
        for name, got, want in (("变了", len(g["changed"]), EXPECT_CF_COMMON_CHANGED),
                                ("掉", g["drop"], EXPECT_CF_COMMON_DROP),
                                ("进", g["add"], EXPECT_CF_COMMON_ADD),
                                ("有召回", g["hit"], EXPECT_CF_COMMON_HIT),
                                ("落在哪几个库", g["libs"], EXPECT_CF_COMMON_LIBS)):
            if got != want:
                bad.append(f"cf-common {name}: {got} ≠ {want}")
    if "--cf-spread" in argv:
        g = cf_spread_off(qs)
        print(f"  P84 那条轴（拆掉它）那个反事实：top-8 变了 {len(g['changed'])} 条 / {EXPECT_TOTAL}"
              f"；HEAD 多进 {g['add']} 少掉 {g['drop']}；有召回 {g['hit'][0]} → {g['hit'][1]}")
        print(f"    变了的落在：{g['libs']}  ⚠️ **这条轴只够得着小库那一档**")
        print(f"    真被捞回来的串 {len(g['rescued'])} 种："
              f"{'、'.join(t for _u, t in g['rescued'][:12])}…")
        print("    （28 条逐条读完：变好 14 / 变差 7 / 中性 7 → P84 判「接」，"
              "理由在 `kite_memory.common_term` 和 `kb/topic_face` 两段注释）")
        for name, got, want in (("变了", len(g["changed"]), EXPECT_CF_SPREAD_CHANGED),
                                ("多进", g["add"], EXPECT_CF_SPREAD_ADD),
                                ("少掉", g["drop"], EXPECT_CF_SPREAD_DROP),
                                ("有召回", g["hit"], EXPECT_CF_SPREAD_HIT),
                                ("落在哪几个库", g["libs"], EXPECT_CF_SPREAD_LIBS),
                                ("捞回来的串", len(g["rescued"]), EXPECT_CF_SPREAD_RESCUED)):
            if got != want:
                bad.append(f"cf-spread {name}: {got} ≠ {want}")
    if "--cf-bigcorpus" in argv:
        g = cf_bigcorpus(qs)
        if g["selfcheck_mismatch"]:
            bad.append(f"cf-bigcorpus 接线自检: 复刻的 HEAD 跟产品那一份差了 "
                       f"{g['selfcheck_mismatch']} 条 —— **下面的数全部作废**")
        print("  大库那一档（P86 ①）—— 基准都是「没有这条轴」，**两个旋钮分开跑**：")
        for name, label in (("size", "只拆库大小闸（汉字闸留着）← 判大库要看的就是这一档"),
                            ("both", "两道闸全拆 ← P84 ⑤ 记的那个 175")):
            d = g[name]
            print(f"    {label}")
            print(f"      变了 {len(d['changed'])} 条 / {EXPECT_TOTAL}；"
                  f"多进 {d['add']} 少掉 {d['drop']}；落在：{d['libs']}")
        print("    （175 条逐条读完 → **P86 ① 判「大库不接」**：`size` 那一档大库 25 条"
              " 变好 8 / 中性 7 / 变差 10（净亏，跟小库 14:7 形状相反）；"
              "`both` 那一档大库 134 条 变好 14 / 中性 27 / **变差 93**。"
              "理由在 `kb/topic_face` 文件头第 ④ 格）")
        for name, got, want in (
                ("size 变了", len(g["size"]["changed"]), EXPECT_CF_BIG_SIZE_CHANGED),
                ("size 多进", g["size"]["add"], EXPECT_CF_BIG_SIZE_ADD),
                ("size 少掉", g["size"]["drop"], EXPECT_CF_BIG_SIZE_DROP),
                ("size 落在哪几个库", g["size"]["libs"], EXPECT_CF_BIG_SIZE_LIBS),
                ("both 变了", len(g["both"]["changed"]), EXPECT_CF_BIG_BOTH_CHANGED),
                ("both 多进", g["both"]["add"], EXPECT_CF_BIG_BOTH_ADD),
                ("both 少掉", g["both"]["drop"], EXPECT_CF_BIG_BOTH_DROP),
                ("both 落在哪几个库", g["both"]["libs"], EXPECT_CF_BIG_BOTH_LIBS)):
            if got != want:
                bad.append(f"cf-bigcorpus {name}: {got} ≠ {want}")
    if "--window" in argv:
        bad += check_paragraph_at_source()
        g = window_gap()
        idx = {(u, q): i for i, (u, q, _m, _o) in enumerate(qs)}
        print(f"  离线 {g['offline']} 条 · 产品那一头 {g['product']} 条"
              f"（离线覆盖 {(g['offline'] - len(g['only_offline'])) / g['product'] * 100:.1f}%）")
        print(f"  **离线有、产品产不出来的：{len(g['only_offline'])} 条**"
              f"（该打折扣的就这几条）")
        for u, q in g["only_offline"]:
            print(f"    i={idx.get((u, q))} user={u} {q[:120]!r}")
        print(f"  产品有、离线没有的：{len(g['only_product'])} 条（离线**少覆盖**的那一档）")
        for u, q in g["only_product"][:6]:
            print(f"    user={u} len={len(q)} {q[:90]!r}")
        for name, got, want in (("产品条数", g["product"], EXPECT_PROD_TOTAL),
                                ("只在离线", len(g["only_offline"]), EXPECT_ONLY_OFFLINE),
                                ("只在产品", len(g["only_product"]), EXPECT_ONLY_PRODUCT)):
            if got != want:
                bad.append(f"{name}: {got} ≠ {want}")
    if bad:
        print("尺子对不上钉死的量程：" + "；".join(bad), file=sys.stderr)
        print("**这一刻台账上所有拿它当分母的数都失效了**——先查口径 / 语料，别换尺子继续量。",
              file=sys.stderr)
        return 9
    print(f"ruler OK = {EXPECT_TOTAL} 条那把尺（P38–P61 逐格相同）"
          + ("；窗口口径 OK（P79 ③ 逐格相同）" if "--window" in argv else "")
          + ("；`common` 反事实 OK（P82 ① 逐格相同）" if "--cf-common" in argv else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
