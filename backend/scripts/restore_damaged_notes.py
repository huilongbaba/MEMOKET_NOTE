"""把跑批时被写坏的真实笔记恢复回跑批前的样子。

**这个脚本被用过两次了**（批 14 和批 16），所以它不再写死批 13 那一组：
要恢复哪几篇、从哪一份备份恢复，都从命令行给。

## 第二次：批 16（2026-09-18）

批 16 的实施 agent 自己写了一个真跑脚本，拿**真实 note_id** 装 `ToolContext`、
只靠 `rails_off=("save",)` 挡写，结果两篇又被写坏：

    309f19202309 「公司汇报：」 30588 字 → 4085 字
    06647b9c2031 「未命名」      2762 字 → 2937 字   （标题双双被改成「批16对照」）

**这一次闸是好的**：`db_guard.Watch()` 在收尾时如实抛了 `NotesTouched`，
四样差异一条不落地列了出来。**但那声报警被吞掉了**——跑批命令写成
`python run.py | tail -20`，管道的退出码是 `tail` 的，恒为 0，
于是"跑完了、退出码 0"看起来一切正常。
教训写进了 `tests/test_db_guard.py`：**别让闸的输出经过任何会改写退出码的管道。**

根因在产品侧：`rails_off=("save",)` 只摘掉 `Save` 这一个 middleware，
而 `hooks/note.NoteHooks.skeleton()` 自己也写库（它要把 spine/beats 和标题落下去）。
**「挡住 Save 就等于不写库」这个假设是错的**，批 14 的复盘也只猜到了一半。

---

原始那一次（批 13 → 批 14 收拾）的记录：

把第 13 批跑批时被写坏的两篇真实笔记恢复回跑批前的样子。

**背景（2026-09-17）**：批 13 的实施 agent 报告写着「一篇笔记都没写」，
而事后核对 `notes.max(updated_at)` 从 `2026-09-16T02:53` 变成了 `2026-09-17T15:54`。
查下来两篇 terrence 的真实笔记被改了：

    e78306202d78 「产品取舍」   1976 字 → 650 字    ← **丢了 1326 字用户自己写的内容**
    06647b9c2031 「未命名」     2762 字 → 5279 字   ← 被 harness 产出污染

这正是 `harness_quality_sample.py` 开头那段警告说的失效模式
（「之前三篇真实笔记的原文因为『备份-还原』机制的结构性盲区永久丢失」）。
这次没有永久丢失——`data/backups/notes-20260917.sqlite3` 是 09-17 启动时做的，
两篇都还是跑批前的原样（`updated_at` 停在 2026-09-02 / 09-03）。

**这个脚本不会被自动跑。** 写笔记库是用户的数据，要用户自己决定。

用法：
    cd backend && .venv/bin/python scripts/restore_damaged_notes.py --dry-run   # 先看会改什么
    cd backend && .venv/bin/python scripts/restore_damaged_notes.py             # 真的改

恢复本身也是可逆的：改之前会把「现在这份（被写坏的）」存成一条
`reason='before_restore'` 的 `note_revisions`，跟产品里「恢复某版之前先存一份」
同一条规矩。
"""

from __future__ import annotations

import argparse
import datetime
import sys
import uuid
from pathlib import Path

import db_guard      # 只读 / 可写两条路都从这里出（批 15）

HERE = Path(__file__).resolve().parent
DB = HERE.parent / "data" / "notes.sqlite3"
BACKUPS = HERE.parent / "data" / "backups"

# 批 13 那次的默认值，留着当例子。**要恢复哪几篇一律显式给**——
# **不做「凡是 updated_at 晚于 X 的都恢复」这种事**，那会把用户自己在这期间
# 真的编辑过的东西一起回滚掉。
DAMAGED = ("e78306202d78", "06647b9c2031")
DEFAULT_BACKUP = "notes-20260917.sqlite3"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印会改什么，不写")
    ap.add_argument("--notes", nargs="+", default=None,
                    help="要恢复的 note id（写死，不许用范围）")
    ap.add_argument("--backup", default=DEFAULT_BACKUP,
                    help="从 data/backups/ 下的哪一份恢复")
    args = ap.parse_args()
    backup = BACKUPS / args.backup
    damaged = tuple(args.notes or DAMAGED)

    if not backup.is_file():
        print(f"找不到跑批前的备份：{backup}")
        return 1

    src = db_guard.readonly(backup)
    # **这个脚本是少数真的该写真库的**（按写死的 id 恢复被跑批写坏的笔记），
    # 所以走 `writable(why=...)` 那条显式路径——理由是必填参数，为的是让
    # 「顺手写一下」变成「先想清楚」（批 15 接线）。
    dst = db_guard.writable("按写死的 id 把被跑批写坏的笔记恢复成备份里那一份", db=DB)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    changed = 0

    for nid in damaged:
        orig = src.execute("SELECT user_id,title,content,updated_at FROM notes WHERE id=?",
                           (nid,)).fetchone()
        cur = dst.execute("SELECT user_id,title,content FROM notes WHERE id=?", (nid,)).fetchone()
        if orig is None or cur is None:
            print(f"  {nid}: 备份或当前库里找不到，跳过")
            continue
        if cur[2] == orig[2]:
            print(f"  {nid} 「{orig[1][:14]}」：已经是原样，不用动")
            continue

        print(f"  {nid} 「{orig[1][:14]}」：{len(cur[2])} 字 → {len(orig[2])} 字（跑批前那一份）")
        if args.dry_run:
            continue

        # 恢复要可逆：先把现在这份存成一个版本
        dst.execute(
            "INSERT INTO note_revisions (id,user_id,note_id,title,content,reason,created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, cur[0], nid, cur[1], cur[2], "before_restore", now))
        dst.execute("UPDATE notes SET title=?, content=?, updated_at=? WHERE id=?",
                    (orig[1], orig[2], orig[3], nid))
        changed += 1

    if not args.dry_run and changed:
        dst.commit()
        print(f"\n恢复了 {changed} 篇。现在：")
        for nid in damaged:
            r = dst.execute("SELECT title,length(content),updated_at FROM notes WHERE id=?",
                            (nid,)).fetchone()
            if r:
                print(f"  {r[0][:14]:<16} {r[1]:>6} 字  {r[2][:19]}")
    elif args.dry_run:
        print("\n（--dry-run，什么都没写）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
