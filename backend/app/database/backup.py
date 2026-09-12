"""笔记库的自动备份（Trilium 有 daily / weekly / monthly 三档）。

每次后端启动看一眼：今天还没备份就用 sqlite 的在线备份 API 拷一份
`backups/notes-YYYYMMDD.sqlite3`（拷的是一致快照，不是裸 cp）。留最近 7 个「日」
和最近 3 个「月」（每月第一份）。知识库（KITE 的 xml，几十 MB 一个用户）暂不进
这里——那是下一步。
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

from ..util.config import get_settings

KEEP_DAILY = 7
KEEP_MONTHLY = 3
_NAME = re.compile(r"^notes-(\d{8})\.sqlite3$")


def backup_dir() -> Path:
    d = Path(get_settings().kite_data_dir) / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _existing(d: Path) -> list[tuple[str, Path]]:
    out = []
    for p in d.iterdir():
        m = _NAME.match(p.name)
        if m:
            out.append((m.group(1), p))
    return sorted(out)


def maybe_backup(db_path: Path, today: date | None = None) -> Path | None:
    """今天没备份就备一份，然后修剪。返回新建的备份路径；今天已有则 None。"""
    today = today or datetime.now().date()
    stamp = today.strftime("%Y%m%d")
    d = backup_dir()
    target = d / f"notes-{stamp}.sqlite3"
    if target.exists() or not db_path.exists():
        return None
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    prune(d)
    return target


def prune(d: Path) -> list[Path]:
    """留最近 KEEP_DAILY 份，再加每月第一份（最近 KEEP_MONTHLY 个月）。返回删掉的。"""
    items = _existing(d)
    keep: set[Path] = {p for _s, p in items[-KEEP_DAILY:]}
    firsts: dict[str, Path] = {}
    for stamp, p in items:                       # 已按日期升序，第一次出现的就是当月第一份
        firsts.setdefault(stamp[:6], p)
    for _month, p in sorted(firsts.items())[-KEEP_MONTHLY:]:
        keep.add(p)
    gone = []
    for _s, p in items:
        if p not in keep:
            p.unlink(missing_ok=True)
            gone.append(p)
    return gone


# ---------------------------------------------------------------- 知识库（KITE codebook）

KEEP_KB_WEEKLY = 2
_KB_NAME = re.compile(r"^codebook-(\d{4}W\d{2})\.xml$")


def maybe_backup_kb(root: Path, today: date | None = None) -> list[Path]:
    """每个用户的 `codebook.xml` 一周一份：`backups/kb/<user>/codebook-YYYYWww.xml`，
    留最近 KEEP_KB_WEEKLY 份。十几 MB 一份、每周一次，两份封顶——不会把磁盘吃光。
    只拷 xml 本体（.lock / .bak-* 这些不是数据）。"""
    today = today or datetime.now().date()
    iso = today.isocalendar()
    stamp = f"{iso[0]}W{iso[1]:02d}"
    made: list[Path] = []
    for user_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name != "backups"):
        src = user_dir / "codebook.xml"
        if not src.is_file():
            continue
        dst_dir = backup_dir() / "kb" / user_dir.name
        dst_dir.mkdir(parents=True, exist_ok=True)
        target = dst_dir / f"codebook-{stamp}.xml"
        if target.exists():
            continue
        shutil.copy2(src, target)
        made.append(target)
        olds = sorted(p for p in dst_dir.iterdir() if _KB_NAME.match(p.name))
        for p in olds[:-KEEP_KB_WEEKLY]:
            p.unlink(missing_ok=True)
    return made
