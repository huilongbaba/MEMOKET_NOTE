"""语料血缘：把一篇笔记判成 `user` / `script` / `fixture` 三类，并说明理由。

## 为什么会有这个模块（连着栽两批逼出来的）

**批 4**：在「31 篇真实笔记」上量出来的句级查重阈值是假的——那 31 篇里有一篇
`shot-perf` 的 47k 字合成性能探针（100 个逐字相同、只有周数不同的小节），
排掉夹具用户之后同一个数从 33.3% 掉到 8.3%，**差一个数量级**。
于是定了第一条规矩：**量任何东西之前先排掉夹具用户**。

**批 6**：那条规矩不够。灵敏度 bench 的「13 篇干净语料」里有 6 篇出自
**同一次 `soak.py` 压测**，而 soak 是**拿真实 user_id（`terrence-rewrite`）跑的**——
按 user_id 和标题筛一个都挡不住。自验的血缘链是：

    notes.id → writing_sections.note_id → writing_sections.plan_id
             → writing_plans.parent_note_id → 那篇「文件夹笔记」的标题
             = `soak-整理一份众筹前后`（`soak.py:123` 的 `f"soak-{goal[:8]}"`）

去掉这 3 篇重算，**4 条结论直接翻转**。于是定了第二条规矩，也就是这个模块：

> **「真实产出」不等于「用户写的」。** 这个仓里三类东西长得一模一样：
> ① 用户真的在用的产出；② `soak` / `suite` / 各个 bench **用真实 user_id
> 跑出来的**；③ `shot-perf` 那种纯合成夹具。
> 三类必须分开，而且**所有测量脚本共用这一份判据**——
> 每个脚本各写一份 `FIXTURE_USERS` 正是这次出事的原因。

## 三类怎么分（分法本身是有用途的，不是为了好听）

| 类 | 是什么 | 为什么要单独一类 |
|---|---|---|
| `user` | 用户真的在用的笔记（他自己建的、他自己跑的 harness） | **只有这一类能用来量判据 / 阈值** |
| `script` | 内容确实是模型真跑出来的，但触发者是测量脚本或用户自己的一次性自测 | 形态是真的，**分布不是**：三篇最坏的可以出自同一个种子。可以用来看「形状」，不能用来算比例 |
| `fixture` | 内容由脚本用模板 / 常量硬生成，根本没过模型 | 拿它量任何跟文字质量有关的数都是**纯噪声**（批 4 那篇 47k 探针） |

## 判据宁可窄一点

这里**只认具体的生成器签名**——某个脚本里写死的那个 f-string、那个用户名、
那条 goal 常量——**不做任何「看起来像测试」的推断**。
判不出来的一律留在 `user`：误伤一篇真实产出，比多跑一篇脚本产出贵。
反过来说，每加一个新的测量脚本，就要往下面的名单里补一条它的签名，
否则它的产出会被当成用户笔记——`test_corpus_lineage.py` 里有闸钉着几条已知的。
**这条承诺自己也栽过一次**（台账批 11 M5）：`harness_stress_test` / `agent_tools_ab`
/ `full_output_sample` 三个脚本都拿真实 user_id `terrence` 建笔记，名单里却一条
都没有——今天没出事只是因为它们跑完把笔记清掉了。批 12 补齐，并且加了一条闸：
**名单里的前缀必须逐字出现在对应脚本的源码里**（`test_corpus_lineage.py`）。

## 为什么放在 `scripts/` 而不是 `app/database/`

这里的知识全部是**关于测量脚本的**（soak 的 goal 常量、各个 bench 的标题前缀、
历史上跑过的探针用户），产品代码一行都不该依赖它。放进 `app/` 会让
「哪些用户是夹具」这种只在开发机上成立的事实变成生产依赖。

## 用法

    from corpus_lineage import load_notes, ORIGIN_USER

    kept, dropped = load_notes(keep={ORIGIN_USER})    # 只读打开，绝不写
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import db_guard      # 只读连接只有一处实现（批 15）

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "notes.sqlite3"

ORIGIN_USER = "user"
ORIGIN_SCRIPT = "script"
ORIGIN_FIXTURE = "fixture"
ORIGINS = (ORIGIN_USER, ORIGIN_SCRIPT, ORIGIN_FIXTURE)


# --------------------------------------------------------------- 名单 ---
#
# 每一条后面都写清楚它是**哪个脚本的什么签名**。写不出签名的不许进名单
# （那就是「看起来像测试」的推断）。

# ③ 纯合成夹具：内容是脚本用模板 / 常量拼的，没过模型。
FIXTURE_USERS: dict[str, str] = {
    "shot-perf": "截图/性能探针，413 篇合成笔记，含 47k 字的「超长笔记」（批 4 的教训）",
    "shot-demo": "截图演示夹具，正文是写死的演示内容",
    "cancel-test3": "取消路径自测，2 篇共 26k 字全是自动生成",
    "journey-probe": "`journey_probe.py` 的探针笔记（正文只有几个字）",
    "cleanup-test": "清理路径自测",
    "search-test": "搜索自测，正文是几个关键词",
    "fresh673": "新用户首屏夹具（`新用户的第一篇 A/B/C`）",
    "fresh674": "新用户首屏夹具",
    "fresh674b": "新用户首屏夹具",
    "fresh674c": "新用户首屏夹具",
    "fresh674d": "新用户首屏夹具",
    "fresh678": "新用户首屏夹具",
    "fresh678b": "新用户首屏夹具",
    "fresh678c": "新用户首屏夹具",
    "fresh689": "新用户首屏夹具",
}

# ② 脚本跑出来的：内容是模型真写的，但触发者是测量脚本。
SCRIPT_USERS: dict[str, str] = {
    "writing-bench": "`writing_quality_bench.py` 的专用用户",
    "editing-bench": "`editing_quality_bench.py` 的专用用户",
    "quality-sample": "`harness_quality_sample.py` 的临时用户",
    "harness-test-2": "harness 自测用户",
    "sensitivity-bench": "本 bench 自己（`dimension_sensitivity_bench.py` 的 ctx_user）",
}

# 标题前缀：**逐字来自各脚本里的那个 f-string**，改脚本必须同步改这里。
SCRIPT_TITLE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("soak-", "`soak.py:123` 的 `f\"soak-{goal[:8]}\"`（文件夹笔记）"),
    ("suite-", "`suite.py:91` 的 `f\"suite-{title}\"`"),
    ("writing-", "`writing_quality_bench.py:269` 的 `f\"writing-{seed['id']}\"`"),
    ("editing-", "`editing_quality_bench.py:244` 的 `f\"editing-{case['id']}\"`"),
    ("质量采样-", "`harness_quality_sample.py:148` 的 `f\"质量采样-{label}\"`"),
    ("📋 写作追踪", "`writing_plan` 自己建的追踪文档，不是正文产出"),
    # 下面三条是批 12 补的（台账批 11 M5）。这三个脚本**都是拿真实 user_id
    # `terrence` 跑的**，跟 `soak.py` 是同一个形状：按 user_id 筛一个都挡不住，
    # 而它们又不建 writing_plan，连血缘那条线索也没有——只剩标题签名这一条。
    # 今天库里这三种一篇都不剩（跑完清理掉了），所以补上不改变现在那张表；
    # **补它们是因为下一次跑完忘了清就会静默混进「用户语料」**。
    ("压测-", "`harness_stress_test.py:274` 的 `f\"压测-{uuid.uuid4().hex[:6]}\"`"),
    ("ab-", "`agent_tools_ab.py:65` 的 `f\"ab-{label}-{seed[\'id\']}\"`"),
    ("sample-", "`full_output_sample.py:129` 的 `f\"sample-{spec[\'id\']}\"`"),
)

# 用户在自己名下建的一次性自测笔记，标题里**自己写着**。
# 只认这两种明确的自我标注，不做任何推断。归到 `script` 而不是 `user`：
# 它跟 suite 跑一次是同一件事（专门为了试 harness 建的），不是他在用的笔记。
SELF_TEST_TITLE = re.compile(r"[（(]可删[）)]|^harness\s*测试|^链接测试")

# `soak.py` 的 `PLAN_GOALS` 逐字复制。soak 建的文件夹笔记可能已经被删掉
# （`run_plan` 跑完会清理），那时候 parent 标题查不到，**只剩 goal 这一条线索**——
# 实测 `1da5a3c9767b` 正是这种：parent 已删、goal 逐字对上。
# `test_corpus_lineage.py` 有一条闸：这份名单必须跟 `soak.PLAN_GOALS` 完全相同。
SOAK_PLAN_GOALS: tuple[str, ...] = (
    "把这一年的硬件量产过程写成一份复盘",
    "整理一份众筹前后的完整时间线",
)


@dataclass(frozen=True)
class Lineage:
    """一篇笔记的写作计划血缘（查不到就是 `None`，不是空对象）。"""
    plan_id: str
    plan_goal: str
    parent_title: str | None          # None = parent 笔记已经被删掉


@dataclass(frozen=True)
class Origin:
    kind: str                         # ORIGINS 之一
    reason: str                       # 中文理由，**必须能报出来**

    @property
    def is_user(self) -> bool:
        return self.kind == ORIGIN_USER


def classify(user_id: str, title: str, lineage: Lineage | None = None) -> Origin:
    """纯函数：`(user_id, title, 血缘)` → 三类之一 + 理由。

    顺序有意义：夹具用户最硬（整个用户都是假的），其次是脚本用户，
    再次是标题签名，**最后才是血缘**——血缘是唯一一条能穿透「真实 user_id」的线索，
    也是批 6 唯一漏掉的那条。
    """
    title = title or ""
    if user_id in FIXTURE_USERS:
        return Origin(ORIGIN_FIXTURE, f"夹具用户 {user_id}：{FIXTURE_USERS[user_id]}")
    if user_id in SCRIPT_USERS:
        return Origin(ORIGIN_SCRIPT, f"脚本用户 {user_id}：{SCRIPT_USERS[user_id]}")
    for prefix, why in SCRIPT_TITLE_PREFIXES:
        if title.startswith(prefix):
            return Origin(ORIGIN_SCRIPT, f"标题前缀 `{prefix}` 出自 {why}")
    if SELF_TEST_TITLE.search(title):
        return Origin(ORIGIN_SCRIPT, f"标题自标注为自测：{title[:24]}")
    if lineage is not None:
        if (lineage.parent_title or "").startswith("soak-"):
            return Origin(ORIGIN_SCRIPT,
                          f"写作计划的文件夹笔记叫 `{lineage.parent_title}`"
                          f"（`soak.py` 的 `f\"soak-{{goal[:8]}}\"`）")
        if lineage.plan_goal in SOAK_PLAN_GOALS:
            return Origin(ORIGIN_SCRIPT,
                          f"写作计划的 goal 逐字等于 `soak.PLAN_GOALS`：{lineage.plan_goal}")
    return Origin(ORIGIN_USER, "")


# ----------------------------------------------------------- 读数据库 ---

def load_lineage(conn: sqlite3.Connection) -> dict[str, Lineage]:
    """`note_id → Lineage`。一次查完，别在循环里逐篇查（1000 篇就是 1000 次）。"""
    rows = conn.execute("""
        SELECT s.note_id AS note_id, p.id AS plan_id, p.goal AS goal,
               p.parent_note_id AS parent_id, pn.title AS parent_title
        FROM writing_sections s
        JOIN writing_plans p ON p.id = s.plan_id
        LEFT JOIN notes pn ON pn.id = p.parent_note_id
        WHERE s.note_id != ''
    """).fetchall()
    out: dict[str, Lineage] = {}
    for r in rows:
        out[r["note_id"]] = Lineage(r["plan_id"], r["goal"] or "", r["parent_title"])
    return out


def annotate(rows: list[dict], lineage: dict[str, Lineage]) -> list[dict]:
    """给每行补 `origin` / `origin_reason` 两个字段（**不改原 dict**）。"""
    out = []
    for row in rows:
        o = classify(row.get("user_id", ""), row.get("title", ""),
                     lineage.get(row.get("id", "")))
        out.append({**row, "origin": o.kind, "origin_reason": o.reason})
    return out


def split(rows: list[dict], lineage: dict[str, Lineage]) -> dict[str, list[dict]]:
    """三类各一桶。**空桶也要在，不然调用方分不清「没有」和「没判」。**"""
    buckets: dict[str, list[dict]] = {k: [] for k in ORIGINS}
    for row in annotate(rows, lineage):
        buckets[row["origin"]].append(row)
    return buckets


def load_notes(db_path: Path = DB_PATH, *, keep: set[str] | None = None,
               harness_only: bool = False) -> tuple[list[dict], list[dict]]:
    """从库里读笔记并分类，**只读打开**（`mode=ro`，连 `update_note` 都不 import）。

    返回 `(kept, dropped)`；`dropped` 每项带 `origin` / `origin_reason`，
    **排掉了什么必须能报出来**——批 4 的问题正是「语料脏」这件事没有任何地方看得见。

    `harness_only=True` 只取 `harness_runs` 跑过的那些笔记（灵敏度 bench 要的）。
    """
    keep = keep or {ORIGIN_USER}
    # **只读连接由 `db_guard.readonly()` 统一给**，不在这里再拼一遍
    # `mode=ro`（批 15）：拼 URI 这件事重复一次，就多一个地方可能漏掉
    # `mode=ro`——而批 14 那场事故的根因正是「以为自己没写」。
    conn = db_guard.readonly(db_path)
    try:
        lineage = load_lineage(conn)
        ids: set[str] | None = None
        if harness_only:
            # key 是 note_id，block 模式带 `<mode>:` 前缀（见 store.py 的注释）
            ids = {r["key"].split(":")[-1]
                   for r in conn.execute("SELECT DISTINCT key FROM harness_runs")}
        rows = [dict(r) for r in conn.execute(
            "SELECT id, user_id, title, content, spine, beats FROM notes")]
    finally:
        conn.close()
    if ids is not None:
        rows = [r for r in rows if r["id"] in ids]
    kept, dropped = [], []
    for row in annotate(rows, lineage):
        (kept if row["origin"] in keep else dropped).append(row)
    return kept, dropped
