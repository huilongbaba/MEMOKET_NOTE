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


def recall_query(content: str, paragraph: str) -> tuple[str, str]:
    """`recallContext.recallQuery` 的逐行 Python 对应。返回 (查询, 'cursor' | 'tail')。"""
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
        return clean((before + "\n" if before else "") + para).strip(), "cursor"
    return clean(content[-RECALL_TAIL_CHARS:]).strip(), "tail"


def users_with_codebook() -> list[str]:
    """`KITE_DATA_DIR` 下 codebook 像样的用户。1000 字节那道门槛挡的是 P29 那种空壳。"""
    root = data_dir()
    return sorted(d.name for d in root.iterdir()
                  if d.is_dir() and (d / "codebook.xml").is_file()
                  and (d / "codebook.xml").stat().st_size > 1000)


def queries(db: Path | None = None) -> list[tuple[str, str, str, str]]:
    """[(用户, 查询, 'cursor' | 'tail', 血缘)]，按 (用户, 查询) 全局去重、顺序稳定。

    血缘走 `corpus_lineage.classify`（**不另写一份夹具名单**——每个脚本各写一份
    正是批 6 出事的原因）。**一条都不筛**，理由在模块注释里。
    """
    conn = db_guard.readonly(db or (BACKEND / "data" / "notes.sqlite3"))
    users = set(users_with_codebook())
    lineage = corpus_lineage.load_lineage(conn)
    rows = conn.execute("SELECT id, user_id, title, content FROM notes ORDER BY id").fetchall()
    conn.close()
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str, str]] = []
    for nid, user, title, content in rows:
        if user not in users or not content:
            continue
        origin = corpus_lineage.classify(user, title or "", lineage.get(nid)).kind
        for para in re.split(r"\n\s*\n", content):
            q, mode = recall_query(content, para)
            if not q:
                continue
            key = (user, q)
            if key in seen:
                continue
            seen.add(key)
            out.append((user, q, mode, origin))
    return out


def by_origin(qs: list[tuple[str, str, str, str]]) -> dict[str, int]:
    from collections import Counter
    c = Counter(o for *_r, o in qs)
    return {k: c.get(k, 0) for k in corpus_lineage.ORIGINS}


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


def check(qs: list[tuple[str, str, str, str]]) -> list[str]:
    """量程对不对。返回对不上的那几条（空 = 对得上）。"""
    cur = sum(1 for _u, _q, m, _o in qs if m == "cursor")
    users = len({u for u, *_r in qs})
    bad = []
    for name, got, want in (("queries", len(qs), EXPECT_TOTAL), ("cursor", cur, EXPECT_CURSOR),
                            ("tail", len(qs) - cur, EXPECT_TAIL), ("users", users, EXPECT_USERS)):
        if got != want:
            bad.append(f"{name}: {got} ≠ {want}")
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
    if bad:
        print("尺子对不上钉死的量程：" + "；".join(bad), file=sys.stderr)
        print("**这一刻台账上所有拿它当分母的数都失效了**——先查口径 / 语料，别换尺子继续量。",
              file=sys.stderr)
        return 9
    print(f"ruler OK = {EXPECT_TOTAL} 条那把尺（P38–P61 逐格相同）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
