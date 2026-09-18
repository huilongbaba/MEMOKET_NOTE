"""跑批脚本碰真库的两道闸。

**为什么有这个文件**（2026-09-17，批 13）：一个实施 agent 的报告写着
「一篇笔记都没写」，而事后核对发现 **两篇 terrence 的真实笔记被改了**——
`e78306202d78`「产品取舍」从 1976 字掉到 650 字（丢了 1326 字用户自己写的内容），
`06647b9c2031` 从 2762 字涨到 5279 字（被 harness 产出污染）。
原文靠 `data/backups/notes-20260917.sqlite3` 救回来了，但这已经是这个仓
**第二次**踩同一个坑——`harness_quality_sample.py` 开头记着第一次：
「之前三篇真实笔记的原文因为『备份-还原』机制的结构性盲区永久丢失」。

**教训不是「下次小心点」。** 第一次之后写的是一段警告注释，第二次照样发生了。
所以这次写成两道能跑的闸：

  1. `readonly()` —— 跑批脚本开真库一律只读。要写就必须显式走
     `writable(why=...)`，那条路会把理由打出来。**默认安全，越权要出声。**
  2. `Watch` —— 每批收尾自动核对笔记表的指纹（行数 + max(updated_at) +
     内容总长 + **每篇正文的摘要**），变了就抛。**不靠任何人自报。**
     批 15 把它接进了八个跑批脚本，于是「这次跑批有没有动用户的笔记」
     不再是一句自报，而是每次自动核对的事；同时补了第四样（逐篇摘要）
     和 `restores=True` 这一档（备份-还原型跑批：过程中可写，出来时正文
     必须逐字回到原样）。

第 2 条尤其要紧：这次能查出来纯粹是因为我按惯例核对了 `max(updated_at)`；
而 agent 的自我报告在这件事上是**错的**。**凡是只能靠自报来保证的性质，
迟早会被报错一次。**
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "notes.sqlite3"

# 笔记表的指纹里包含哪些表。`notes` 是用户写的东西，`note_revisions` 是它的历史
# ——两张都不许被跑批悄悄改。`harness_runs` / `harness_rounds` / `llm_usage`
# **故意不在这里**：跑批本来就该往那几张写，把它们算进来会让闸天天误报。
WATCHED = ("notes", "note_revisions")


def readonly(db: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    """开一个**写不了**的连接。跑批脚本一律用这个。

    用 `mode=ro` 而不是「自己记得别写 SQL」：后者靠人自觉，而这次出事
    正是因为有人以为自己没写。sqlite 在 `mode=ro` 下任何写操作直接抛
    `OperationalError: attempt to write a readonly database`——**吵闹地失败，
    比安静地写坏强得多。**
    """
    conn = sqlite3.connect(f"file:{Path(db)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def writable(why: str, db: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    """真的要写真库时走这条，并且**必须说出理由**。

    理由不是给日志看的，是给写代码的人看的：一个必须填的参数会让
    「顺手写一下」这件事变得需要先想清楚。
    """
    if not (why or "").strip():
        raise ValueError("要写真库就得说清楚为什么——这个参数不许留空")
    print(f"[db_guard] 正在以**可写**方式打开真库：{why}")
    conn = sqlite3.connect(str(Path(db)))
    conn.row_factory = sqlite3.Row
    return conn


@dataclass(frozen=True)
class Fingerprint:
    rows: dict[str, int]
    latest: dict[str, str]
    chars: int
    # 每篇笔记正文的摘要（id → sha256 前 16 位）。**第四样，批 15 补的**：
    # 前三样里只有 `chars` 在看正文，而它是**总和**——删 A 的 300 字、给 B
    # 加 300 字，总数一个不差。批 14 那次事故正好是一篇变短一篇变长
    # （1976→650、2762→5279），只是两边的数没恰好抵消才被总字数抓到。
    # 逐篇比就没有"恰好抵消"这回事。
    digests: dict[str, str] = field(default_factory=dict)

    def diff(self, other: "Fingerprint") -> list[str]:
        out = []
        for t in WATCHED:
            if self.rows.get(t) != other.rows.get(t):
                out.append(f"{t} 行数 {self.rows.get(t)} → {other.rows.get(t)}")
            if self.latest.get(t) != other.latest.get(t):
                out.append(f"{t} 最后修改 {self.latest.get(t)} → {other.latest.get(t)}")
        if self.chars != other.chars:
            out.append(f"笔记正文总字数 {self.chars} → {other.chars}（差 {other.chars - self.chars:+d}）")
        out.extend(self.content_diff(other))
        return out

    def content_diff(self, other: "Fingerprint") -> list[str]:
        """**只看正文本身**：哪几篇的内容变了 / 多了 / 少了。

        单独拆出来是给「确实要写、但写完必须原样还原」的跑批用
        （`harness_stress_test.py` 的备份-还原三篇真实笔记）。那条路走完
        `updated_at` 必然前进、`note_revisions` 必然多几行——**那两样变了是
        正常的，正文变了才是事故**。拿整份指纹去卡它会天天误报，而一个天天
        误报的闸等于没有闸（`WATCHED` 不收 `harness_runs` 是同一条理由）。
        """
        out = []
        mine, theirs = self.digests or {}, other.digests or {}
        changed = sorted(k for k in set(mine) & set(theirs) if mine[k] != theirs[k])
        for k in changed:
            out.append(f"笔记 {k} 的正文变了")
        for k in sorted(set(theirs) - set(mine)):
            out.append(f"多出一篇笔记 {k}")
        for k in sorted(set(mine) - set(theirs)):
            out.append(f"少了一篇笔记 {k}")
        return out


def fingerprint(db: Path | str = DEFAULT_DB) -> Fingerprint:
    """笔记库现在长什么样。

    四样一起看，因为**任何一样单独都骗得过**：只看行数，改内容不涨行；
    只看 `max(updated_at)`，改完再把时间戳写回去就看不见；
    只看总字数，删一段加一段正好抵消；**只看前三样，一篇变短另一篇变长
    正好抵消也照样看不见**——批 14 那次事故正是一短一长，只是没恰好抵消。
    第四样是逐篇正文摘要，"恰好抵消"在它面前不成立。
    """
    conn = readonly(db)
    rows, latest = {}, {}
    for t in WATCHED:
        rows[t] = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        # **时间列按表实际有什么来挑，不写死。** 第一版把 `notes` 的时间列写成
        # `updated_at`、`note_revisions` 写成 `created_at`——在真库上碰巧都对，
        # 单测的最小表上当场 `no such column`。**「在真库上碰巧对」不是对。**
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        col = next((c for c in ("updated_at", "created_at") if c in cols), None)
        latest[t] = (conn.execute(f"SELECT coalesce(max({col}), '') FROM {t}").fetchone()[0]
                     if col else "")
    chars = conn.execute("SELECT coalesce(sum(length(content)), 0) FROM notes").fetchone()[0]
    digests = {
        str(r[0]): hashlib.sha256((r[1] or "").encode("utf-8")).hexdigest()[:16]
        for r in conn.execute("SELECT id, content FROM notes")
    }
    conn.close()
    return Fingerprint(rows=rows, latest=latest, chars=chars, digests=digests)


class Watch:
    """把一段跑批夹在中间，出来时核对笔记库没被动过。

        with Watch():
            ...跑批...

    动过就抛 `NotesTouched`，异常信息里直接写清楚差在哪——
    **不需要任何人记得去核对，也不接受任何人的口头保证。**
    """

    def __init__(self, db: Path | str = DEFAULT_DB, *, allow: bool = False,
                 restores: bool = False):
        self.db = db
        self.allow = allow          # 确实要写笔记的跑批（比如压测）显式传 True
        # **「写了但必须还原」这一档**（批 15）。`harness_stress_test.py` 是真的
        # 要写真实笔记：它备份 → 跑 → 还原。用 `allow=True` 的话，**还原失败
        # 也照样放行**——而批 14 那场事故的形状恰恰就是「以为还原了，其实没有」
        # （`harness_stress_test.py` 自己的注释记着第一次：进程被外层超时杀掉，
        # finally 没跑，一篇真实笔记的原文永久丢失）。
        # 所以这一档的规矩是：跑的过程中随便写，**出来的时候每一篇笔记的正文
        # 必须逐字回到原样**；`updated_at` 和 `note_revisions` 允许前进
        # （还原本身就是一次写，那两样必然动，卡它们等于天天误报）。
        self.restores = restores
        self.before: Fingerprint | None = None

    def __enter__(self) -> "Watch":
        self.before = fingerprint(self.db)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            return False            # 本来就炸了，别用这个盖住真异常
        after = fingerprint(self.db)
        if self.before is None:
            return False
        if self.restores:
            broken = self.before.content_diff(after)
            if broken:
                raise NotesTouched(
                    "这次跑批写了真实笔记（声明过），但**还原没把正文放回原样**：\n  "
                    + "\n  ".join(broken)
                    + "\n（备份在 scripts/harness_stress_inflight_backup.json 或 "
                      "data/backups/，先恢复再继续）")
            moved = [c for c in self.before.diff(after) if "正文" not in c]
            if moved:
                print("[db_guard] 正文已逐字还原；下面这些是还原本身留下的痕迹，"
                      "属正常：\n  " + "\n  ".join(moved))
            return False
        changed = self.before.diff(after)
        if changed and not self.allow:
            raise NotesTouched(
                "这次跑批动了用户的笔记库，而它不该动：\n  " + "\n  ".join(changed)
                + "\n（真要写就用 Watch(allow=True)，并在台账里写清楚为什么）")
        if changed:
            print("[db_guard] 笔记库有变动（已声明允许）：\n  " + "\n  ".join(changed))
        return False


class NotesTouched(RuntimeError):
    """跑批动了不该动的东西。"""
