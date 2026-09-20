"""走查那份**拷贝**起壳之前必做的两道手续（P74 从 scratch 搬进仓库）。

P23 那条教训写得很直白：*scratch 库里带着用户真的密钥，探针的第一步就该把它摘掉*
——那一批因为漏了这一步，**真往 api.openai.com 发了两次**。
两道是一件事的两半：**钥匙换掉**（`scrub_credentials`）**和地址指回本机**
（`point_provider_at_localhost`）。只换钥匙不换地址，照样会真连出去一次（401 也算连出去）。

从 P23 到 P72，这两件每批都在 scratch 里现写一份（`scrub52.py` / `setmode.py`）。
**现写的那一份跟上一批不一样**，于是「上一批那一趟到底扫没扫干净」谁也复现不了。

**为什么不并进 `walkthrough_udd.py`**：那一份进了
`test_corpus_lineage` 的白名单，理由是「它**一行 SQL 都不跑**」，
而 `test_p66.py` 有一条闸盯着这个理由（不许 `import sqlite3`、不许出现 SQL 关键字）。
把这两个函数塞进去等于把那条理由作废——**白名单的理由一旦作废，白名单就成了豁免**。
所以另起一份：这一份**该**跑 SQL，它的规矩是另一条（下面那条）。

**连接一律走 `db_guard`**（`test_db_guard::test_跑批脚本不许自己拼只读连接`）：
只读走 `readonly()`，要写走 `writable(why=...)`——那个必填的理由不是给日志看的，
是给写代码的人看的，它让「顺手写一下」这件事变得需要先想清楚。
这两个函数**只对着 scratch 里那份拷贝用**，理由串里写明了这一点。

跟 `walkthrough_udd.py` 同一条规矩：**核完才返回，核不上就抛**。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# **只读 / 可写连接只有一处实现**（`db_guard`，批 15 立的）。
# `sys.path` 那两行跟 `soak.py` / `corpus_lineage.py` 逐字同形：
# 这些脚本既会被当模块 import（`from scripts.walkthrough_db import …`），
# 也会被 `test_scripts_import.py` 按**单文件**加载一遍
# ——后者下相对 import 根本不成立（实拍 `ImportError: attempted relative import`）。
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db_guard  # noqa: E402

#: 「这像不像一枚真钥匙」。**宁可宽一点**，扫出来的逐条打印、自己看。
_KEY_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "sk- 前缀"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}"), "Bearer"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), "github token"),
    (re.compile(r"\bAKIA[0-9A-Z]{12,}"), "aws"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"), "slack"),
]
#: 列名本身就说明是凭据的，**值长什么样都换掉**。
_KEYISH_COL = re.compile(r"(api_?key|secret|token|password|passwd|credential)", re.I)
#: 换上去的那个值。**固定一个可搜的串**，这样「扫完再核一遍」才有东西可核。
SCRUB_VALUE = "fake-key-p74"

_WHY = ("走查用的 scratch 拷贝：扫全库换掉真凭据 / 把模型地址指回本机。"
        "**真库一个字节都不碰**，这个路径一律是 scratch 下的那一份")


def scrub_credentials(db: Path | str, *, value: str = SCRUB_VALUE) -> list[tuple]:
    """扫**全库每一张表的每一个文本列**，把真凭据换掉，**换完再扫一遍核 0**。

    为什么是全库而不是那一张表：凭据会出现在意想不到的地方（粘进笔记正文里的
    一行 curl、导出设置的 JSON、日志表）。**「我知道它在哪张表」正是这个仓栽过的那类判断**。
    """
    conn = db_guard.writable(_WHY, db)
    hits = _scan(conn)
    for t, col, rowid, _why, _peek in hits:
        conn.execute(f'UPDATE "{t}" SET "{col}" = ? WHERE rowid = ?', (value, rowid))
    conn.commit()
    left = _scan(conn)
    conn.close()
    if left:
        raise AssertionError(f"换完还剩 {len(left)} 处凭据没换掉：{left[:5]}")
    print(f"凭据：换掉 {len(hits)} 处 → {value}（换完再扫一遍：0 处）")
    return hits


def _scan(conn) -> list[tuple]:
    out = []
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for t in tables:
        for c in list(conn.execute(f"PRAGMA table_info({t})")):
            col = c[1]
            for row in conn.execute(f'SELECT rowid, "{col}" FROM "{t}" WHERE "{col}" IS NOT NULL'):
                v = row[1]
                if not isinstance(v, str) or not v.strip() or v == SCRUB_VALUE:
                    continue
                why = next((label for pat, label in _KEY_PATTERNS if pat.search(v)), "")
                if not why and _KEYISH_COL.search(col):
                    why = f"列名 {col}"
                if why:
                    out.append((t, col, row[0], why, v[:24]))
    return out


#: `provider_config` 里**所有**指向外网的地址列。少写一个就是「还会真连出去一次」。
#:
#: **`asr_base_url` 是这条闸第一次跑就抓出来的**（P74）：scratch 里那份
#: `setmode.py` 从 P23 起只改三列，而真库的 `provider_config` 有**四**列地址。
#: 那一趟真库里它正好是空串（所以没真连出去过），但「今天正好是空的」跟
#: 「这一列被管着」是两件事 —— 而这一整份的存在理由正是 P23 那次**真发出去了两次**。
BASE_URL_COLS = ("local_base_url", "vision_base_url", "gpt_base_url", "asr_base_url")


def point_provider_at_localhost(db: Path | str, port: int | str, *,
                                model: str = "fake-p52",
                                vision_model: str = "fake-vision-p52") -> dict:
    """把这份拷贝的模型供应商指到 **127.0.0.1:<port>**，**改完读回来核一遍**。

    核的是「所有地址列都指本机」这个**性质**，不是「我写了 N 条 UPDATE」这个写法
    ——库里哪天多一列地址，这里**当场抛**，而不是安静地漏掉那一列。
    """
    base = f"http://127.0.0.1:{port}/v1"
    conn = db_guard.writable(_WHY, db)
    cols = {c[1] for c in conn.execute("PRAGMA table_info(provider_config)")}
    unknown = [c for c in cols if c.endswith("_base_url") and c not in BASE_URL_COLS]
    if unknown:
        conn.close()
        raise AssertionError(
            f"provider_config 里多了没见过的地址列 {unknown} —— 不改它就是「还会真连出去一次」。"
            "把它加进 BASE_URL_COLS，别把这条改成「不核」")
    sets = ", ".join(f'"{c}" = ?' for c in BASE_URL_COLS)
    conn.execute(
        f"UPDATE provider_config SET provider='local', {sets}, local_model=?, vision_model=?",
        (*[base] * len(BASE_URL_COLS), model, vision_model))
    conn.commit()
    rows = [dict(r) for r in conn.execute("SELECT * FROM provider_config")]
    conn.close()
    bad = [(r.get("id"), c, r.get(c)) for r in rows for c in BASE_URL_COLS if r.get(c) != base]
    if bad:
        raise AssertionError(f"改完还有地址不指本机：{bad}")
    if not rows:
        raise AssertionError("provider_config 一行都没有 —— 那这一趟根本没配过模型，先想清楚")
    print(f"供应商 → {base}（{len(rows)} 行，{len(BASE_URL_COLS)} 个地址列都核过）")
    return {"base": base, "rows": len(rows)}
