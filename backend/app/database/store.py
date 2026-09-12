"""笔记持久化。SQLite 足够原型用，且零外部依赖。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..util.config import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',
    pinned      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, updated_at DESC);
-- 没有 folder_id：笔记归谁管由 branches 说了算。老库里那一列由
-- _drop_folder_remnants 删掉。

-- 一次性迁移的登记处。_ADDED_COLUMNS 那张表只能补列，做不了数据搬运
-- （把文件夹变成笔记这种），而数据搬运又必须**只跑一次**。
CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

-- 笔记引用了哪些事实。**整个「笔记 × 知识库」融合的承重墙。**
--
-- 方向是双向的：正文里的 `[terrence-1872-5F8]` 是「笔记 → 事实」，而这张表
-- 让「事实 → 哪些笔记用了我」也查得出来。没有反查，知识库就是个只进不出的
-- 仓库——而「这条事实还活着吗、改了它影响谁」是个真问题。
--
-- **保存笔记时扫正文重建，不给用户维护。** 引用写在正文里，正文才是唯一
-- 真相；手工维护的关联表迟早跟正文对不上。
CREATE TABLE IF NOT EXISTS note_citations (
    note_id  TEXT NOT NULL,
    fact_id  TEXT NOT NULL,
    user_id  TEXT NOT NULL,
    PRIMARY KEY (note_id, fact_id)
);
CREATE INDEX IF NOT EXISTS idx_citations_fact ON note_citations(user_id, fact_id);

-- 树的边。**照 Trilium 的模型：notes 表里没有父子关系，全在这儿。**
--
-- 一个笔记可以有多条 branch —— 那就是「克隆」：同一篇笔记同时出现在树的
-- 多个位置，改一处处处都变。这是 Trilium 的招牌特性，也是为什么父子关系
-- 不能是 notes 表上的一个 parent_id 列。
--
-- 「文件夹」不再是一种东西：**任何有子节点的笔记就是文件夹**。
CREATE TABLE IF NOT EXISTS branches (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    note_id         TEXT NOT NULL,
    parent_note_id  TEXT NOT NULL,       -- 'root' 表示挂在树根
    position        INTEGER NOT NULL DEFAULT 0,
    is_expanded     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    UNIQUE(note_id, parent_note_id)
);
CREATE INDEX IF NOT EXISTS idx_branches_parent
    ON branches(user_id, parent_note_id, position);
CREATE INDEX IF NOT EXISTS idx_branches_note ON branches(note_id);

-- 无限续写的 harness 状态：一个文件夹同一时间最多一个活跃 plan（旧的会先
-- 被标记 done/abandoned），sections 是它拆出来的有序写作单元，每个最终会
-- 落到某篇笔记里。这是可靠的机器状态——人看的进度是从这两张表渲染出的一篇
-- 笔记镜像（见 writing_plan.py 的 _sync_tracking_note），不是反过来解析
-- markdown 复选框当状态，那样在 harness 反复读写多轮之后太容易解析飘掉。
-- Skill *content* lives on disk as standard SKILL.md directories (see
-- app/skills.py for why). Only our own configuration lives here: which
-- scopes it applies to, whether it is on, what sandbox level the user
-- granted. Keeping them apart is what lets a third-party skill be installed
-- by dropping in a directory, and ours be exported by copying one out.
CREATE TABLE IF NOT EXISTS skill_config (
    user_id TEXT NOT NULL,
    slug    TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    scopes  TEXT NOT NULL DEFAULT '',
    sandbox TEXT NOT NULL DEFAULT 'none',
    source  TEXT NOT NULL DEFAULT 'user',
    -- 叠加顺序。skill 的 body 是按顺序拼进 system prompt 的，两条规则
    -- 冲突时排后面的那条更晚被读到——所以顺序是用户配置的一部分，不是
    -- 展示细节。
    idx     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, slug)
);

CREATE TABLE IF NOT EXISTS writing_plans (
    id             TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    -- 这个计划对着树上哪一棵子树跑。原来叫 folder_id——文件夹没了之后它
    -- 就是那棵子树根笔记的 id，值一个没变（迁移时旧文件夹沿用了原 id）。
    parent_note_id TEXT NOT NULL,
    goal        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active',
    doc_note_id TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
-- idx_writing_plans_parent 不在这儿建，在 connect() 里、**列改名之后**。
-- 老库上 `CREATE TABLE IF NOT EXISTS` 是空操作（表已经存在、列还是旧名），
-- 在这里建一个引用新列名的索引会当场 no such column。这个文件为
-- idx_notes_folder 写过同样的注释，我照样撞了一次。

CREATE TABLE IF NOT EXISTS writing_sections (
    id          TEXT PRIMARY KEY,
    plan_id     TEXT NOT NULL,
    idx         INTEGER NOT NULL,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    note_id     TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_writing_sections_plan ON writing_sections(plan_id, idx);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    status      TEXT NOT NULL,
    facts       INTEGER NOT NULL DEFAULT 0,
    detail      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ingest_items (
    id          TEXT PRIMARY KEY,
    job_id      TEXT NOT NULL,
    idx         INTEGER NOT NULL,
    filename    TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'queued',
    facts       INTEGER NOT NULL DEFAULT 0,
    detail      TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_job ON ingest_items(job_id, idx);

-- 轮末暂停的快照。跟 harness_runs 不是一回事：那张记的是「跑完了，结果
-- 如何」，供跨 run 的经验复用；这张记的是「跑到一半，等用户处置」，
-- 供恢复。一个 run 同一时刻最多一份快照，用户处置完就删。
CREATE TABLE IF NOT EXISTS harness_snapshots (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    note_id    TEXT NOT NULL DEFAULT '',
    mode       TEXT NOT NULL,
    round      INTEGER NOT NULL DEFAULT 0,
    state      TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_user ON harness_snapshots(user_id, created_at DESC);

-- 笔记历史版本（Trilium 的 note revisions）。保存时正文变了、且离上一版超过
-- 间隔就把**旧**正文存一份；恢复某版之前先把当前存一份，恢复永远可逆。
CREATE TABLE IF NOT EXISTS note_revisions (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    note_id    TEXT NOT NULL,
    title      TEXT NOT NULL DEFAULT '',
    content    TEXT NOT NULL DEFAULT '',
    reason     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_revisions_note ON note_revisions(user_id, note_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_profile (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_profile_user ON user_profile(user_id, created_at DESC);

-- 全局（不分用户）的 LLM 供应商选择——本地模型 or GPT。单行表，固定用
-- id='default' 存取，没有 SQLite 原生的"只允许一行"约束，靠约定遵守。
-- 没设置过（表是空的）就退回 .env 里配的本地模型默认值，见
-- get_active_llm_config()——这样没打开过设置页的用户行为完全不变。
CREATE TABLE IF NOT EXISTS provider_config (
    id           TEXT PRIMARY KEY,
    provider     TEXT NOT NULL DEFAULT 'local',
    gpt_api_key  TEXT NOT NULL DEFAULT '',
    gpt_model    TEXT NOT NULL DEFAULT 'gpt-4.1-mini',
    gpt_base_url TEXT NOT NULL DEFAULT 'https://api.openai.com/v1',
    asr_base_url TEXT NOT NULL DEFAULT '',
    auto_sync_notes INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL
);

-- harness.types.RunHistoryStore 的落地实现（见 app/harness_adapter.py）。
-- key 是调用方定的"同一件反复发生的事情"是什么——note_harness 传
-- note_id，writing_plan 传子树根笔记的 id，包本身不关心这个约定。
-- final_scores/weak_dimensions 存 JSON 文本，不是关系型列——评分维度是
-- 调用方配置出来的，不是这张表能提前知道的固定集合。
CREATE TABLE IF NOT EXISTS harness_runs (
    id              TEXT PRIMARY KEY,
    key             TEXT NOT NULL,
    status          TEXT NOT NULL,
    rounds          INTEGER NOT NULL,
    final_scores    TEXT NOT NULL,
    weak_dimensions TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_harness_runs_key ON harness_runs(key, created_at DESC);
"""

# 单个 job 里所有 item 都落到这些状态之一，才算 job 结束
_TERMINAL_ITEM_STATUSES = {"done", "failed", "cancelled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _db_path() -> Path:
    root = Path(get_settings().kite_data_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root / "notes.sqlite3"


def _add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """老库补一列。列已经在了就什么都不做。

    先查 PRAGMA 再决定，而不是「ALTER 一下、报错就 pass」。原来那种写法
    吞掉的是**整个** ``OperationalError``：库被锁上、磁盘满了、表名打错了，
    症状都一样——静默跳过，然后在几十行外以一个看不懂的方式炸。判断「这列
    在不在」不需要靠异常，PRAGMA 就能直接回答。
    """
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


# 老库要补的列。新库走 _SCHEMA 就已经带上了，这张表只为升级存在——
# 每一条都对应一次「功能加上了，可真实库里已经有数据」的时刻。
_ADDED_COLUMNS = (
    ("ingest_jobs", "cancel_requested", "INTEGER NOT NULL DEFAULT 0"),
    ("notes", "pinned", "INTEGER NOT NULL DEFAULT 0"),
    # 写作骨架（核心张力 + 结构节拍）跟着笔记走。
    #
    # 之前它只活在前端内存里，`open()` 一进新笔记就清空——换一篇、刷新页面、
    # 甚至无限续写开着「跟随」自动切到下一段，骨架就没了。而 harness 每轮都
    # 要拿它当主线依据，没了就得重新花一次模型调用生成，或者干脆没有主线跑。
    # beats 存成 JSON 数组字符串。
    ("notes", "spine", "TEXT NOT NULL DEFAULT ''"),
    ("notes", "beats", "TEXT NOT NULL DEFAULT ''"),
    # skill_config 是这一版新建的，但真实库里已经跑过一轮，
    # CREATE TABLE IF NOT EXISTS 不会给它补上后加的列。
    ("skill_config", "idx", "INTEGER NOT NULL DEFAULT 0"),
    # 这篇笔记什么时候被摄入进知识库的。空 = 没摄入过。树上据此标 ⇡，
    # 一眼看出哪些笔记「有据可依」、哪些还只是草稿。
    ("notes", "ingested_at", "TEXT NOT NULL DEFAULT ''"),
    # 语音服务地址进设置页：之前只能改 .env 重启，状态栏挂着「语音离线」用户却没处改。
    # 空 = 用 .env 的默认值。
    ("provider_config", "asr_base_url", "TEXT NOT NULL DEFAULT ''"),
    # 笔记改动后自动同步进知识库的开关（默认关：每次同步是一次抽取调用）
    ("provider_config", "auto_sync_notes", "INTEGER NOT NULL DEFAULT 0"),
    # 导入进度按块走（一篇 40 块的会议记录和一篇 2 块的随手记权重不一样）；
    # job 级记每块耗时 / 字数，算预估时间和 token 用量；payload 落盘的 job 能断点续跑。
    ("ingest_items", "chunks_total", "INTEGER NOT NULL DEFAULT 0"),
    ("ingest_items", "chunks_done", "INTEGER NOT NULL DEFAULT 0"),
    ("ingest_jobs", "payload_path", "TEXT NOT NULL DEFAULT ''"),
    ("ingest_jobs", "chunk_ms", "INTEGER NOT NULL DEFAULT 0"),
    ("ingest_jobs", "chunks_done", "INTEGER NOT NULL DEFAULT 0"),
    ("ingest_jobs", "chars_done", "INTEGER NOT NULL DEFAULT 0"),
    ("ingest_jobs", "started_at", "TEXT NOT NULL DEFAULT ''"),
)


ROOT_ID = "root"
"""树根。Trilium 里也是这个字面量——它不是一条真笔记，是「没有父节点」的写法。"""


def _drop_orphans(conn: sqlite3.Connection) -> None:
    """删掉指向已不存在笔记的引用 / 历史版本 / 暂停快照 / 运行记录。

    `delete_note` 以前只删 notes 和 branches，这些行在老库里已经攒了一批。只跑
    一次：从此以后 delete_note 自己会带走它们。"""
    conn.execute("DELETE FROM note_citations WHERE note_id NOT IN (SELECT id FROM notes)")
    conn.execute("DELETE FROM note_revisions WHERE note_id NOT IN (SELECT id FROM notes)")
    conn.execute("DELETE FROM harness_snapshots WHERE note_id<>'' AND note_id NOT IN (SELECT id FROM notes)")
    conn.execute("DELETE FROM harness_runs WHERE key LIKE 'note:%' AND substr(key, 6) NOT IN (SELECT id FROM notes)")


def _prune_runs(conn: sqlite3.Connection) -> None:
    """运行记录每个 key 只留最近 50 条。`record_harness_run` 以后每次写都会修剪，
    这里把老库里攒下的（实测一个开发库 4000 条）一次清掉。"""
    conn.execute(
        "DELETE FROM harness_runs WHERE rowid NOT IN ("
        " SELECT rowid FROM ("
        "  SELECT rowid, ROW_NUMBER() OVER (PARTITION BY key ORDER BY created_at DESC, rowid DESC) AS rn"
        "  FROM harness_runs) WHERE rn <= 50)")


def _migrate_once(conn: sqlite3.Connection, key: str, run) -> bool:
    """只跑一次的数据搬运。跑过了返回 False。

    跟 `_ADDED_COLUMNS` 分开：那张表是「补一列」，幂等、每次连接跑一遍也
    没关系；这里是**搬数据**（把文件夹变成笔记），跑第二遍就会把已经搬好的
    再搬一次。所以要有登记处。
    """
    done = conn.execute("SELECT 1 FROM meta WHERE key=?", (key,)).fetchone()
    if done:
        return False
    run(conn)
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                 (key, _now()))
    conn.commit()
    return True


def _folders_into_tree(conn: sqlite3.Connection) -> None:
    """把「文件夹 + 笔记」两层结构搬成一棵树。

    照 Trilium 的模型：**文件夹不再是一种东西**，任何有子节点的笔记就是
    文件夹。所以每个旧文件夹变成一篇笔记（正文为空），原来属于它的笔记
    变成它的子节点。

    **旧文件夹的 id 直接当新笔记的 id。** 这一点是有意的：``writing_plans``
    的 folder_id、前端记着的「当前文件夹」、知识库里按 folder 存的东西，
    全都还指向同一个 id，不用跟着改一遍。
    """
    has_folders = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='folders'"
    ).fetchone()
    folders = conn.execute(
        "SELECT id, user_id, name, created_at FROM folders").fetchall() \
        if has_folders else []
    for f in folders:
        # 同 id 的笔记可能已经存在（重跑、或者手工建过）——不覆盖。
        if conn.execute("SELECT 1 FROM notes WHERE id=?", (f["id"],)).fetchone():
            continue
        conn.execute(
            "INSERT INTO notes (id, user_id, title, content, pinned, folder_id,"
            " created_at, updated_at) VALUES (?,?,?,'',0,NULL,?,?)",
            (f["id"], f["user_id"], f["name"], f["created_at"], f["created_at"]))

    # 每篇笔记挂一条 branch：有 folder_id 的挂到那个（现在是笔记了）下面，
    # 没有的挂在树根。
    note_cols = {r[1] for r in conn.execute("PRAGMA table_info(notes)")}
    col = "folder_id" if "folder_id" in note_cols else "NULL AS folder_id"
    notes = conn.execute(
        f"SELECT id, user_id, {col}, created_at FROM notes").fetchall()
    seen: dict[tuple[str, str], int] = {}
    for n in notes:
        parent = n["folder_id"] or ROOT_ID
        key = (n["user_id"], parent)
        pos = seen.get(key, 0)
        seen[key] = pos + 1
        conn.execute(
            "INSERT OR IGNORE INTO branches (id, user_id, note_id,"
            " parent_note_id, position, is_expanded, created_at)"
            " VALUES (?,?,?,?,?,0,?)",
            (uuid.uuid4().hex[:12], n["user_id"], n["id"], parent, pos,
             n["created_at"]))


def _drop_folder_remnants(conn: sqlite3.Connection) -> None:
    """文件夹时代的残留清干净：`folders` 表、`notes.folder_id` 列。

    **必须排在 `_folders_into_tree` 后面**——那次迁移正是靠读这两样把旧数据
    搬成树的。顺序由 connect() 里的调用顺序保证。

    留着不删是不行的：一个还在的 `folder_id` 列会让下一个读代码的人以为
    「笔记还有个文件夹字段」，然后写出一半走树、一半走 folder_id 的代码。
    这个仓库的主人为这种「新旧混着」付过账。
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(notes)")}
    if "folder_id" in cols:
        conn.execute("DROP INDEX IF EXISTS idx_notes_folder")
        conn.execute("ALTER TABLE notes DROP COLUMN folder_id")
    conn.execute("DROP INDEX IF EXISTS idx_folders_user")
    conn.execute("DROP TABLE IF EXISTS folders")


def _plan_folder_to_parent(conn: sqlite3.Connection) -> None:
    """`writing_plans.folder_id` 改名成 `parent_note_id`。

    值一个都不用动：迁移时旧文件夹沿用了原 id，所以那一列里存的本来就已经
    是一个笔记 id 了。改的只是名字——留着 `folder_id` 这个名字会让人以为
    还有文件夹这种东西。
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(writing_plans)")}
    if "folder_id" in cols and "parent_note_id" not in cols:
        conn.execute("ALTER TABLE writing_plans RENAME COLUMN folder_id"
                     " TO parent_note_id")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    for table, column, decl in _ADDED_COLUMNS:
        _add_column(conn, table, column, decl)
    # 顺序有意义：先把旧数据搬成树（要读 folders 和 notes.folder_id），
    # 再把那两样删掉。
    _migrate_once(conn, "folders-into-tree-v1", _folders_into_tree)
    _migrate_once(conn, "plan-folder-to-parent-v1", _plan_folder_to_parent)
    _migrate_once(conn, "drop-folder-remnants-v1", _drop_folder_remnants)
    _migrate_once(conn, "drop-orphans-v1", _drop_orphans)
    _migrate_once(conn, "prune-runs-v1", _prune_runs)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_writing_plans_parent"
                 " ON writing_plans(user_id, parent_note_id, status)")
    return conn


# ---------------------------------------------------------------- 笔记

def _note(row) -> dict:
    """行 → dict。**beats 在库里是 JSON 字符串，出去必须是数组**——不转的话
    Note 这个响应模型会校验失败，整个笔记接口 500。"""
    d = dict(row)
    try:
        d["beats"] = json.loads(d.get("beats") or "[]")
    except (TypeError, ValueError):
        d["beats"] = []
    if not isinstance(d["beats"], list):
        d["beats"] = []
    d["spine"] = d.get("spine") or ""
    return d


def list_notes(user_id: str, q: str = "") -> list[dict]:
    with connect() as c:
        if q:
            like = f"%{q}%"
            rows = c.execute(
                "SELECT * FROM notes WHERE user_id=? AND (title LIKE ? OR content LIKE ?) "
                "ORDER BY pinned DESC, updated_at DESC",
                (user_id, like, like)).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM notes WHERE user_id=? ORDER BY pinned DESC, updated_at DESC",
                (user_id,)).fetchall()
    return [_note(r) for r in rows]


def get_note(user_id: str, note_id: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM notes WHERE user_id=? AND id=?",
                        (user_id, note_id)).fetchone()
    return _note(row) if row else None


def create_note(user_id: str, title: str, content: str,
                parent_id: str = ROOT_ID) -> dict:
    """建一篇笔记，**同时把它挂到树上**。

    照 Trilium：笔记总是创建在某个父节点下面，没有「建完再决定放哪」这个
    中间态。不挂的话它就不在树上的任何位置——存在于库里但用户看不见，
    那不是一篇笔记，是一条垃圾数据。
    """
    note = {"id": uuid.uuid4().hex[:12], "user_id": user_id, "title": title,
            "content": content, "pinned": 0,
            "created_at": _now(), "updated_at": _now()}
    with connect() as c:
        c.execute(
            "INSERT INTO notes (id,user_id,title,content,pinned,created_at,updated_at) "
            "VALUES (:id,:user_id,:title,:content,:pinned,:created_at,:updated_at)", note)
        pos = _next_position(c, user_id, parent_id)
        c.execute("INSERT INTO branches (id,user_id,note_id,parent_note_id,"
                  "position,is_expanded,created_at) VALUES (?,?,?,?,?,0,?)",
                  (uuid.uuid4().hex[:12], user_id, note["id"], parent_id, pos,
                   note["created_at"]))
        c.commit()
    # 带着引用建出来的笔记（导入、回顾存为笔记）也要进反查表——之前只有
    # update_note 会同步，这类笔记在下次保存前反查不到。
    if content:
        sync_citations(user_id, note["id"], content)
    return {**note, "spine": "", "beats": []}


REVISION_INTERVAL_S = 600
"""两次自动快照的最小间隔（Trilium 的 revisionSnapshotTimeInterval 默认也是 600s）。
自动保存每几秒一次，不设间隔一篇笔记一小时就是几百版。"""
REVISION_KEEP = 100


def _snapshot_locked(c: sqlite3.Connection, user_id: str, note_id: str, title: str,
                     content: str, reason: str, *, force: bool) -> bool:
    """在已开的连接里存一版。不强制时受间隔限制；空正文不存。"""
    if not (content or "").strip():
        return False
    if not force:
        last = c.execute(
            "SELECT created_at FROM note_revisions WHERE user_id=? AND note_id=?"
            " ORDER BY created_at DESC, rowid DESC LIMIT 1", (user_id, note_id)).fetchone()
        if last:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])).total_seconds()
            if age < REVISION_INTERVAL_S:
                return False
    c.execute("INSERT INTO note_revisions (id,user_id,note_id,title,content,reason,created_at)"
              " VALUES (?,?,?,?,?,?,?)",
              (uuid.uuid4().hex[:12], user_id, note_id, title, content, reason, _now()))
    c.execute("DELETE FROM note_revisions WHERE user_id=? AND note_id=? AND id NOT IN ("
              "SELECT id FROM note_revisions WHERE user_id=? AND note_id=?"
              " ORDER BY created_at DESC, rowid DESC LIMIT ?)",
              (user_id, note_id, user_id, note_id, REVISION_KEEP))
    return True


def update_note(user_id: str, note_id: str, title: str, content: str) -> dict | None:
    with connect() as c:
        old = c.execute("SELECT title, content FROM notes WHERE user_id=? AND id=?",
                        (user_id, note_id)).fetchone()
        if not old:
            return None
        # 正文变了才留版本；只改标题不算
        if old["content"] != content:
            _snapshot_locked(c, user_id, note_id, old["title"], old["content"], "auto", force=False)
        cur = c.execute(
            "UPDATE notes SET title=?, content=?, updated_at=? "
            "WHERE user_id=? AND id=?",
            (title, content, _now(), user_id, note_id))
        if cur.rowcount == 0:
            return None
    # 正文变了就重建引用。**在这里做而不是让调用方记得调**——保存是
    # 唯一会改正文的入口，放这儿就不会漏；漏一次，反查结果就开始不可信。
    sync_citations(user_id, note_id, content)
    return get_note(user_id, note_id)


def snapshot_note(user_id: str, note_id: str, reason: str = "manual") -> dict | None:
    """手动存一版（不受间隔限制）。返回这一版的摘要，没这篇 / 正文为空返回 None。"""
    with connect() as c:
        row = c.execute("SELECT title, content FROM notes WHERE user_id=? AND id=?",
                        (user_id, note_id)).fetchone()
        if not row:
            return None
        if not _snapshot_locked(c, user_id, note_id, row["title"], row["content"], reason, force=True):
            return None
    return list_revisions(user_id, note_id)[0]


def list_revisions(user_id: str, note_id: str) -> list[dict]:
    """新的在前。不带正文——列表只要知道什么时候、多少字。"""
    with connect() as c:
        rows = c.execute(
            "SELECT id, note_id, title, reason, created_at, length(content) AS chars"
            # 同一秒内可能存两版（恢复前的强制快照紧跟手动版），rowid 兜底定序
            " FROM note_revisions WHERE user_id=? AND note_id=? ORDER BY created_at DESC, rowid DESC",
            (user_id, note_id)).fetchall()
    return [dict(r) for r in rows]


def get_revision(user_id: str, note_id: str, rev_id: str) -> dict | None:
    with connect() as c:
        row = c.execute(
            "SELECT id, note_id, title, content, reason, created_at FROM note_revisions"
            " WHERE user_id=? AND note_id=? AND id=?", (user_id, note_id, rev_id)).fetchone()
    return dict(row) if row else None


def restore_revision(user_id: str, note_id: str, rev_id: str) -> dict | None:
    """恢复到某一版。先把**现在**的正文强制存一版（reason=before_restore），
    恢复永远可以再恢复回来。"""
    rev = get_revision(user_id, note_id, rev_id)
    if not rev:
        return None
    snapshot_note(user_id, note_id, "before_restore")
    with connect() as c:
        c.execute("UPDATE notes SET title=?, content=?, updated_at=? WHERE user_id=? AND id=?",
                  (rev["title"], rev["content"], _now(), user_id, note_id))
    sync_citations(user_id, note_id, rev["content"])
    return get_note(user_id, note_id)


def set_skeleton(user_id: str, note_id: str, spine: str, beats: list[str]) -> None:
    """写作骨架跟着笔记存。**只在真的有内容时写**——空骨架不该覆盖已有的：
    前端切笔记时会把内存里的 spine/beats 清空，那个"空"不代表用户想删掉它。"""
    with connect() as c:
        c.execute("UPDATE notes SET spine=?, beats=? WHERE user_id=? AND id=?",
                  (spine, json.dumps(beats, ensure_ascii=False), user_id, note_id))


def get_skeleton(user_id: str, note_id: str) -> tuple[str, list[str]]:
    note = get_note(user_id, note_id)
    if not note:
        return "", []
    return note["spine"], [str(b) for b in note["beats"] if str(b).strip()]


def set_pinned(user_id: str, note_id: str, pinned: bool) -> dict | None:
    with connect() as c:
        cur = c.execute(
            "UPDATE notes SET pinned=? WHERE user_id=? AND id=?",
            (1 if pinned else 0, user_id, note_id))
        if cur.rowcount == 0:
            return None
    return get_note(user_id, note_id)


def delete_note(user_id: str, note_id: str) -> list[str]:
    """删一篇笔记**以及它的整棵子树**，返回被删掉的所有 id。

    子树必须一起删。只删自己的话，孩子们的 branch 指向一个不存在的父节点
    ——它们既不在树根、也不在任何看得见的地方，是一批用户再也找不到、
    却还在库里占着的笔记。Trilium 也是删整棵子树。

    **克隆是例外**：一个孩子如果在别处还有 branch，就只摘掉这条边，笔记
    本身留着——它在别的位置还长着，删掉就是把用户在那边看得见的东西弄没了。
    """
    removed: list[str] = []
    with connect() as c:
        if not c.execute("SELECT 1 FROM notes WHERE user_id=? AND id=?",
                         (user_id, note_id)).fetchone():
            return removed

        def drop(nid: str) -> None:
            kids = [r[0] for r in c.execute(
                "SELECT note_id FROM branches WHERE parent_note_id=? AND user_id=?",
                (nid, user_id))]
            for kid in kids:
                others = c.execute(
                    "SELECT COUNT(*) FROM branches WHERE note_id=? AND user_id=?"
                    " AND parent_note_id<>?", (kid, user_id, nid)).fetchone()[0]
                if others:
                    # 别处还长着：只摘这条边
                    c.execute("DELETE FROM branches WHERE note_id=? AND"
                              " parent_note_id=? AND user_id=?", (kid, nid, user_id))
                else:
                    drop(kid)
            c.execute("DELETE FROM branches WHERE note_id=? AND user_id=?",
                      (nid, user_id))
            c.execute("DELETE FROM notes WHERE id=? AND user_id=?", (nid, user_id))
            # 挂在这篇上的东西一起走：引用、历史版本、暂停快照、运行记录。
            # 留着就是一堆指向不存在笔记的孤儿行，越攒越多。
            c.execute("DELETE FROM note_citations WHERE user_id=? AND note_id=?", (user_id, nid))
            c.execute("DELETE FROM note_revisions WHERE user_id=? AND note_id=?", (user_id, nid))
            c.execute("DELETE FROM harness_snapshots WHERE user_id=? AND note_id=?", (user_id, nid))
            c.execute("DELETE FROM harness_runs WHERE key=?", (f"note:{nid}",))
            removed.append(nid)

        drop(note_id)
        c.commit()
    return removed
def child_notes(user_id: str, parent_id: str, exclude_id: str = "",
                limit: int = 5) -> list[dict]:
    """某个节点下面的直接子笔记。无限续写拿它当「同一批内容」的参考上下文。

    走 branches 而不是 notes.folder_id：**克隆之后一篇笔记可以同时属于好几个
    父节点**，folder_id 那个单值字段表达不了。
    """
    with connect() as c:
        rows = c.execute(
            "SELECT n.* FROM notes n JOIN branches b ON b.note_id = n.id"
            " WHERE b.user_id=? AND b.parent_note_id=? AND n.id != ?"
            " ORDER BY n.updated_at DESC LIMIT ?",
            (user_id, parent_id, exclude_id, limit)).fetchall()
    return [_note(r) for r in rows]


# ------------------------------------------------------- 笔记 × 知识库
#
# 双向链接。设计见 docs/kb-fusion-design.md。

import re as _re

# 事实 id 的形状：`<用户>-<数字>-<十六进制>`。跟前端 editor/factCite.ts 里那条
# **必须一致**——两边认的不是同一批引用的话，树上的角标和正文里的高亮会对不上。
# 用户名段以字母开头：不然 [2026-01-01] 这种日期也会被当成引用（01 是合法十六进制）。
_CITE = _re.compile(r"\[([A-Za-z][A-Za-z0-9_-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+)\]")


def cited_fact_ids(content: str) -> list[str]:
    """正文里引用了哪些事实。去重，保持出现顺序。"""
    seen: dict[str, None] = {}
    for m in _CITE.finditer(content or ""):
        seen.setdefault(m.group(1), None)
    return list(seen)


def sync_citations(user_id: str, note_id: str, content: str) -> list[str]:
    """按正文重建这篇笔记的引用。返回引用到的事实 id。

    **整篇替换而不是增量。** 用户删掉一句话就等于撤销了那条引用，增量更新
    会把删掉的引用永远留在表里——那种「幽灵引用」会让反查结果越来越不可信。
    """
    ids = cited_fact_ids(content)
    with connect() as c:
        c.execute("DELETE FROM note_citations WHERE note_id=? AND user_id=?",
                  (note_id, user_id))
        c.executemany(
            "INSERT OR IGNORE INTO note_citations (note_id, fact_id, user_id)"
            " VALUES (?,?,?)", [(note_id, f, user_id) for f in ids])
        c.commit()
    return ids


def notes_citing(user_id: str, fact_id: str) -> list[dict]:
    """哪些笔记引用了这条事实。**反查——融合的关键。**

    回答的是「这条事实还活着吗、改了它会影响谁」。没有它，知识库就是个只进
    不出的仓库。对标 Trilium 右栏的 Backlinks。
    """
    with connect() as c:
        rows = c.execute(
            "SELECT n.id, n.title, n.updated_at, substr(n.content,1,80) AS preview FROM note_citations k"
            " JOIN notes n ON n.id = k.note_id"
            " WHERE k.user_id=? AND k.fact_id=? ORDER BY n.updated_at DESC",
            (user_id, fact_id)).fetchall()
    return [dict(r) for r in rows]


_NOTE_LINK = _re.compile(r"\]\(note://([0-9a-f]{12})\)")


def note_links_in(content: str) -> list[str]:
    """正文里链到的笔记 id（`[标题](note://<id>)`），按出现顺序去重。"""
    seen: list[str] = []
    for m in _NOTE_LINK.finditer(content or ""):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def backlinks(user_id: str, note_id: str) -> list[dict]:
    """哪些笔记链到了这篇（Trilium 的 Referenced by）。

    直接 LIKE 扫正文而不是维护一张链接表：几千篇笔记一次 LIKE 几毫秒，
    而链接表要在每次保存 / 删除 / 克隆时同步，多一处会漂的状态。
    """
    with connect() as c:
        rows = c.execute(
            "SELECT id, title, updated_at, substr(content,1,80) AS preview FROM notes"
            " WHERE user_id=? AND id<>? AND content LIKE ? ORDER BY updated_at DESC",
            (user_id, note_id, f"%](note://{note_id})%")).fetchall()
    return [dict(r) for r in rows]


def citation_counts(user_id: str) -> dict[str, int]:
    """每篇笔记引用了几条事实。树上画角标用——一次查完，不要每个节点问一次。"""
    with connect() as c:
        rows = c.execute(
            "SELECT note_id, COUNT(*) AS n FROM note_citations WHERE user_id=?"
            " GROUP BY note_id", (user_id,)).fetchall()
    return {r["note_id"]: r["n"] for r in rows}


def mark_ingested(user_id: str, note_id: str) -> None:
    """记下这篇被摄入进知识库了。树上据此标 ⇡。"""
    with connect() as c:
        c.execute("UPDATE notes SET ingested_at=? WHERE id=? AND user_id=?",
                  (_now(), note_id, user_id))
        c.commit()


# ---------------------------------------------------------------- 笔记树
#
# 照 Trilium 的模型：树的边全在 branches 里，notes 表不存父子关系。一个笔记
# 有多条 branch 就是「克隆」——同时出现在树的多个位置，改一处处处都变。
#
# 这里的函数都只认 branches，不看 notes.folder_id。folder_id 是迁移前的遗物，
# 迁移之后由 branches 说了算（见 _folders_into_tree）。


def _next_position(c: sqlite3.Connection, user_id: str, parent_id: str) -> int:
    row = c.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM branches"
                    " WHERE user_id=? AND parent_note_id=?",
                    (user_id, parent_id)).fetchone()
    return int(row[0])


def attach(user_id: str, note_id: str, parent_id: str = ROOT_ID,
           position: int | None = None) -> dict:
    """把一篇笔记挂到某个父节点下面。已经挂过就原样返回那条 branch。

    **同一对 (note, parent) 只能有一条 branch**（表上有 UNIQUE 约束）：
    同一篇笔记在同一个位置出现两次没有任何意义，而放任它出现会让树里出现
    两个看起来一样、删一个另一个还在的节点。
    """
    with connect() as c:
        row = c.execute("SELECT * FROM branches WHERE note_id=? AND parent_note_id=?",
                        (note_id, parent_id)).fetchone()
        if row:
            return dict(row)
        bid = uuid.uuid4().hex[:12]
        pos = _next_position(c, user_id, parent_id) if position is None else position
        c.execute("INSERT INTO branches (id, user_id, note_id, parent_note_id,"
                  " position, is_expanded, created_at) VALUES (?,?,?,?,?,0,?)",
                  (bid, user_id, note_id, parent_id, pos, _now()))
        c.commit()
        return dict(c.execute("SELECT * FROM branches WHERE id=?", (bid,)).fetchone())


def detach(user_id: str, note_id: str, parent_id: str) -> bool:
    """摘掉一条 branch（不删笔记本身）。

    **最后一条不给摘。** 摘掉之后那篇笔记就不在树上的任何位置了，用户再也
    找不到它，而它还在库里占着——这不是删除，是丢失。要删笔记走 delete_note。
    """
    with connect() as c:
        n = c.execute("SELECT COUNT(*) FROM branches WHERE note_id=? AND user_id=?",
                      (note_id, user_id)).fetchone()[0]
        if n <= 1:
            return False
        cur = c.execute("DELETE FROM branches WHERE note_id=? AND parent_note_id=?"
                        " AND user_id=?", (note_id, parent_id, user_id))
        c.commit()
        return cur.rowcount > 0


def _would_cycle(c: sqlite3.Connection, note_id: str, new_parent: str) -> bool:
    """把 note 挂到 new_parent 下面会不会成环。

    **必须查。** 树里成环之后，任何一次深度遍历（渲染树、算路径、删子树）
    都会无限转下去——症状是界面直接卡死，而不是报一个错。
    """
    seen = {new_parent}
    frontier = [new_parent]
    while frontier:
        cur = frontier.pop()
        if cur == note_id:
            return True
        for row in c.execute("SELECT parent_note_id FROM branches WHERE note_id=?",
                             (cur,)):
            if row[0] not in seen:
                seen.add(row[0])
                frontier.append(row[0])
    return False


def move_branch(user_id: str, note_id: str, old_parent: str, new_parent: str,
                position: int | None = None) -> bool:
    """把一条 branch 换个父节点。成环就拒绝。"""
    with connect() as c:
        if note_id == new_parent or _would_cycle(c, note_id, new_parent):
            return False
        if c.execute("SELECT 1 FROM branches WHERE note_id=? AND parent_note_id=?"
                     " AND user_id=?", (note_id, new_parent, user_id)).fetchone():
            # 目标位置已经有它了：这次移动等于「从旧位置摘掉」
            return detach(user_id, note_id, old_parent)
        pos = _next_position(c, user_id, new_parent) if position is None else position
        cur = c.execute("UPDATE branches SET parent_note_id=?, position=?"
                        " WHERE note_id=? AND parent_note_id=? AND user_id=?",
                        (new_parent, pos, note_id, old_parent, user_id))
        c.commit()
        return cur.rowcount > 0


def reorder(user_id: str, parent_id: str, order: list[str]) -> int:
    """把一个父节点下的子节点按给定顺序重新编号 0..n-1。

    拖拽排序用。**不做「插到第 k 个位置」这种相对操作**：位置一旦有重复
    （克隆、并发、老数据），相对插入就不知道插到哪；整体重编号一次就把
    脏数据也顺手洗干净了。没列在 order 里的子节点排在后面，保持原相对顺序。
    """
    with connect() as c:
        rows = c.execute("SELECT note_id FROM branches WHERE parent_note_id=? AND user_id=?"
                         " ORDER BY position", (parent_id, user_id)).fetchall()
        existing = [r["note_id"] for r in rows]
        seen = set()
        final = [n for n in order if n in existing and not (n in seen or seen.add(n))]
        final += [n for n in existing if n not in seen]
        for i, nid in enumerate(final):
            c.execute("UPDATE branches SET position=? WHERE note_id=? AND parent_note_id=?"
                      " AND user_id=?", (i, nid, parent_id, user_id))
        c.commit()
        return len(final)


def set_expanded(user_id: str, note_id: str, parent_id: str, expanded: bool) -> None:
    """树节点的展开状态存在库里，不在前端内存里——刷新一次就全收起来的树
    在几十个节点之后就没法用了。"""
    with connect() as c:
        c.execute("UPDATE branches SET is_expanded=? WHERE note_id=? AND"
                  " parent_note_id=? AND user_id=?",
                  (1 if expanded else 0, note_id, parent_id, user_id))
        c.commit()


def tree(user_id: str) -> list[dict]:
    """整棵树的边 + 每个节点的显示信息，一次查完。

    **不做成「按需展开时再查一层」。** 笔记数量在几千这个量级，一次查完是
    几毫秒的事；而按层查会让「展开一个节点」变成一次网络往返，树用起来就
    是一顿一顿的。真到了十万节点再说，那时候改的是这一个函数。
    """
    with connect() as c:
        rows = c.execute(
            "SELECT b.id, b.note_id, b.parent_note_id, b.position, b.is_expanded,"
            "       n.title, n.pinned, n.updated_at,"
            # 正文开头。**树上标题为空或还是占位符时拿它当显示名**——真实
            # 库里 18 篇有 15 篇标题字面就是「未命名」（旧界面建笔记时的
            # 默认值），一列二十个「未命名」的树是没法用的。
            # 只取前 80 字：树是导航，不是预览器。
            "       substr(n.content, 1, 80) AS preview,"
            # 跟知识库的连接，树上直接看得见：引用了几条、摄入过没有。
            # 一次查完，不要每个节点问一次。
            "       n.ingested_at,"
            "       (SELECT COUNT(*) FROM note_citations k"
            "          WHERE k.note_id = b.note_id) AS cite_count,"
            "       (SELECT COUNT(*) FROM branches k WHERE k.parent_note_id=b.note_id)"
            "         AS child_count,"
            "       (SELECT COUNT(*) FROM branches m WHERE m.note_id=b.note_id)"
            "         AS branch_count"
            " FROM branches b JOIN notes n ON n.id = b.note_id"
            " WHERE b.user_id=? ORDER BY b.parent_note_id, b.position, n.title",
            (user_id,)).fetchall()
    return [dict(r) for r in rows]


def note_paths(user_id: str, note_id: str) -> list[list[str]]:
    """这篇笔记在树上的所有位置，每个位置是一条从根到它的 id 路径（含自己）。

    **是 list 不是单个**：克隆之后一篇笔记同时长在好几个地方，「它在哪」
    没有唯一答案。面包屑要显示的是用户**当前是从哪条路径点进来的**，所以
    调用方得自己挑一条。
    """
    out: list[list[str]] = []
    with connect() as c:
        def walk(nid: str, below: list[str]) -> None:
            if len(below) > 64:      # 环的兜底；_would_cycle 应该已经挡住了
                return
            trail = [nid] + below
            parents = [r[0] for r in c.execute(
                "SELECT parent_note_id FROM branches WHERE note_id=? AND user_id=?",
                (nid, user_id))]
            if not parents:
                return               # 不在树上（不该发生，除非数据被外力改过）
            for parent in parents:
                if parent == ROOT_ID:
                    out.append(trail)
                else:
                    walk(parent, trail)

        walk(note_id, [])
    return out


# ---------------------------------------------------------------- 文件夹
def get_active_plan(user_id: str, parent_note_id: str) -> dict | None:
    with connect() as c:
        row = c.execute(
            "SELECT * FROM writing_plans WHERE user_id=? AND parent_note_id=? AND status='active'",
            (user_id, parent_note_id)).fetchone()
    return dict(row) if row else None


def get_plan(user_id: str, plan_id: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM writing_plans WHERE user_id=? AND id=?",
                        (user_id, plan_id)).fetchone()
    return dict(row) if row else None


def create_plan(user_id: str, parent_note_id: str, goal: str) -> dict:
    """新建之前先把这个文件夹里任何还挂着 active 的旧 plan 标成
    abandoned——同一个文件夹同时只应该有一个活跃计划，不然 harness 不知道
    该跑哪个。"""
    plan = {"id": uuid.uuid4().hex[:12], "user_id": user_id, "parent_note_id": parent_note_id,
            "goal": goal, "status": "active", "doc_note_id": "",
            "created_at": _now(), "updated_at": _now()}
    with connect() as c:
        c.execute(
            "UPDATE writing_plans SET status='abandoned' WHERE user_id=? AND parent_note_id=? AND status='active'",
            (user_id, parent_note_id))
        c.execute(
            "INSERT INTO writing_plans (id,user_id,parent_note_id,goal,status,doc_note_id,created_at,updated_at) "
            "VALUES (:id,:user_id,:parent_note_id,:goal,:status,:doc_note_id,:created_at,:updated_at)", plan)
    return plan


def set_plan_doc_note(user_id: str, plan_id: str, note_id: str) -> None:
    with connect() as c:
        c.execute("UPDATE writing_plans SET doc_note_id=? WHERE user_id=? AND id=?",
                  (note_id, user_id, plan_id))


def set_plan_status(user_id: str, plan_id: str, status: str) -> None:
    with connect() as c:
        c.execute("UPDATE writing_plans SET status=?, updated_at=? WHERE user_id=? AND id=?",
                  (status, _now(), user_id, plan_id))


def list_sections(plan_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM writing_sections WHERE plan_id=? ORDER BY idx",
                         (plan_id,)).fetchall()
    return [_note(r) for r in rows]


def add_sections(plan_id: str, titles: list[str]) -> list[dict]:
    """追加新 section，idx 接着已有的往后编号——初次生成骨架、以及后续
    「还有没有更多可写」判定为是时的追加，都走这一个函数。"""
    with connect() as c:
        existing = c.execute("SELECT COALESCE(MAX(idx), -1) FROM writing_sections WHERE plan_id=?",
                             (plan_id,)).fetchone()[0]
        rows = []
        for offset, title in enumerate(titles):
            row = {"id": uuid.uuid4().hex[:12], "plan_id": plan_id, "idx": existing + 1 + offset,
                   "title": title, "status": "pending", "note_id": "", "summary": "",
                   "created_at": _now()}
            c.execute(
                "INSERT INTO writing_sections (id,plan_id,idx,title,status,note_id,summary,created_at) "
                "VALUES (:id,:plan_id,:idx,:title,:status,:note_id,:summary,:created_at)", row)
            rows.append(row)
    return rows


_SECTION_UPDATABLE_COLS = {"status", "note_id", "summary"}


def update_section(plan_id: str, section_id: str, **fields) -> None:
    """fields 支持 status/note_id/summary 任意子集——调用方按需传，别的列
    保持不变。列名白名单是防御性的——这几个 kwarg 目前只会是调用方硬编码
    传的字面量，但既然是拼进 SQL 的动态列名就不留操作空间。"""
    if not fields:
        return
    bad = set(fields) - _SECTION_UPDATABLE_COLS
    if bad:
        raise ValueError(f"update_section got unknown column(s): {bad}")
    cols = ", ".join(f"{k}=?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE writing_sections SET {cols} WHERE plan_id=? AND id=?",
                  (*fields.values(), plan_id, section_id))


# ---------------------------------------------------------------- 入库任务
#
# 单文件任务（/ingest/text /ingest/audio）只用 ingest_jobs 表，没有 items。
# 批量任务（/ingest/batch）额外在 ingest_items 里给每个文件建一行，job 的
# status/facts 由 update_job_from_items() 从 items 聚合出来。

def create_job(user_id: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    with connect() as c:
        c.execute("INSERT INTO ingest_jobs (id,user_id,status,facts,detail,created_at) "
                  "VALUES (?,?,?,?,?,?)",
                  (job_id, user_id, "queued", 0, "", _now()))
    return job_id


def set_job(job_id: str, status: str, facts: int = 0, detail: str = "") -> None:
    with connect() as c:
        c.execute("UPDATE ingest_jobs SET status=?, facts=?, detail=? WHERE id=?",
                  (status, facts, detail[:500], job_id))


def get_job(job_id: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM ingest_jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs(user_id: str, limit: int = 20) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM ingest_jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)).fetchall()
    return [_note(r) for r in rows]


def request_cancel(job_id: str) -> None:
    with connect() as c:
        c.execute("UPDATE ingest_jobs SET cancel_requested=1 WHERE id=?", (job_id,))


def is_cancel_requested(job_id: str) -> bool:
    job = get_job(job_id)
    return bool(job and job["cancel_requested"])


# ------------------------------------------------------------ 批量任务的 items

def create_batch_job(user_id: str, files: list[dict]) -> tuple[str, list[dict]]:
    """建一个 job + N 个 item（每个文件一行），全部初始状态 queued。"""
    job_id = uuid.uuid4().hex[:12]
    items: list[dict] = []
    with connect() as c:
        c.execute("INSERT INTO ingest_jobs (id,user_id,status,facts,detail,created_at) "
                  "VALUES (?,?,?,?,?,?)",
                  (job_id, user_id, "queued", 0, "", _now()))
        for idx, f in enumerate(files):
            item = {"id": uuid.uuid4().hex[:12], "job_id": job_id, "idx": idx,
                    "filename": f["filename"], "kind": f["kind"], "status": "queued",
                    "facts": 0, "detail": "", "updated_at": _now()}
            c.execute(
                "INSERT INTO ingest_items (id,job_id,idx,filename,kind,status,facts,detail,updated_at) VALUES "
                "(:id,:job_id,:idx,:filename,:kind,:status,:facts,:detail,:updated_at)",
                item)
            items.append(item)
    return job_id, items


def set_item(item_id: str, status: str, facts: int = 0, detail: str = "",
             chunks_total: int | None = None, chunks_done: int | None = None) -> None:
    with connect() as c:
        c.execute(
            "UPDATE ingest_items SET status=?, facts=?, detail=?, updated_at=? WHERE id=?",
            (status, facts, detail[:500], _now(), item_id))
        if chunks_total is not None:
            c.execute("UPDATE ingest_items SET chunks_total=? WHERE id=?", (chunks_total, item_id))
        if chunks_done is not None:
            c.execute("UPDATE ingest_items SET chunks_done=? WHERE id=?", (chunks_done, item_id))


# 没有历史数据时每块按这个估（GPT 实测 ~13s / 块）；token 按「固定提示 + 正文 / 1.5 + 输出」估
DEFAULT_CHUNK_MS = 13000
TOKENS_PER_CHUNK_FIXED = 1600


def bump_job_chunk(job_id: str, ms: int, chars: int) -> None:
    """一块抽完：累计耗时 / 字数 / 块数，预估时间和用量从这里算。"""
    with connect() as c:
        c.execute("UPDATE ingest_jobs SET chunk_ms=chunk_ms+?, chars_done=chars_done+?, chunks_done=chunks_done+?"
                  " WHERE id=?", (int(ms), int(chars), 1, job_id))


def mark_job_started(job_id: str) -> None:
    with connect() as c:
        c.execute("UPDATE ingest_jobs SET started_at=? WHERE id=? AND started_at=''", (_now(), job_id))


def set_job_payload(job_id: str, path: str) -> None:
    with connect() as c:
        c.execute("UPDATE ingest_jobs SET payload_path=? WHERE id=?", (path, job_id))


def avg_chunk_ms(user_id: str) -> int:
    """这个用户最近几个任务每块平均多少毫秒；没跑过就用默认值。开始前的预估靠它。"""
    with connect() as c:
        row = c.execute(
            "SELECT SUM(chunk_ms) AS ms, SUM(chunks_done) AS n FROM ("
            "  SELECT chunk_ms, chunks_done FROM ingest_jobs WHERE user_id=? AND chunks_done>0"
            "  ORDER BY created_at DESC LIMIT 5)", (user_id,)).fetchone()
    if row and row["n"]:
        return max(1000, int(row["ms"] / row["n"]))
    return DEFAULT_CHUNK_MS


def estimate(chunks: int, chars: int, chunk_ms: int = DEFAULT_CHUNK_MS) -> dict:
    """开始前 / 跑的时候都用这个：剩多少块、大概多久、大概多少 token。"""
    return {"chunks": chunks, "seconds": int(chunks * chunk_ms / 1000),
            "tokens": int(chunks * TOKENS_PER_CHUNK_FIXED + chars / 1.5)}


def job_progress(job_id: str) -> dict:
    """进度 / 预估 / 用量，全从已有的表算：块数看 items，耗时看 job 累计。"""
    job = get_job(job_id)
    if not job:
        return {}
    items = get_items(job_id)
    total = sum(int(i.get("chunks_total") or 0) for i in items)
    done = sum(int(i.get("chunks_done") or 0) for i in items)
    n = int(job.get("chunks_done") or 0)
    per = int(job["chunk_ms"] / n) if n and job.get("chunk_ms") else avg_chunk_ms(job["user_id"])
    remaining = max(0, total - done)
    elapsed = 0
    if job.get("started_at"):
        try:
            elapsed = int((datetime.now(timezone.utc) - datetime.fromisoformat(job["started_at"])).total_seconds())
        except ValueError:
            elapsed = 0
    est = estimate(remaining, 0, per)
    return {
        "chunks_total": total, "chunks_done": done, "eta_s": est["seconds"] if job["status"] in ("queued", "running") else 0,
        "elapsed_s": elapsed,
        "tokens_est": int(n * TOKENS_PER_CHUNK_FIXED + int(job.get("chars_done") or 0) / 1.5),
        "resumable": bool(job.get("payload_path")) and job["status"] == "interrupted",
        "current": next((i["filename"] for i in items if i["status"] not in _TERMINAL_ITEM_STATUSES and i["status"] != "queued"), ""),
    }


def get_items(job_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM ingest_items WHERE job_id=? ORDER BY idx", (job_id,)).fetchall()
    return [_note(r) for r in rows]


def update_job_from_items(job_id: str) -> None:
    """把 job 的 status/facts 从它的 items 聚合出来。批量流程每次 item 变化都调一次。"""
    items = get_items(job_id)
    if not items:
        return
    total_facts = sum(i["facts"] for i in items)
    if any(i["status"] == "failed" for i in items):
        status = "error"
    elif all(i["status"] in _TERMINAL_ITEM_STATUSES for i in items):
        status = "cancelled" if all(i["status"] == "cancelled" for i in items) else "done"
    else:
        # 收到取消请求但还有 item 没停干净时，状态是「正在停止」而不是「处理中」。
        # 后台可能卡在一次 LLM 调用或 KITE 写锁里几十秒，这段时间界面必须如实
        # 说「在停了」，否则跟没点一样。
        job = get_job(job_id)
        status = "cancelling" if (job and job["cancel_requested"]) else "running"
    detail = "; ".join(f"{i['filename']}: {i['detail']}" for i in items if i["detail"])
    set_job(job_id, status, facts=total_facts, detail=detail)


# ---------------------------------------------------------------- 个人偏好
#
# 故意不进 KITE codebook——那边是"从文档/笔记里抽事实"，异步、经模型取舍、
# 走 LLM 抽取排队。这里是用户自己直接说的"我喜欢/我倾向于..."，不需要抽取，
# 写完立刻生效，跟知识库是两个独立的存储。

def list_profile(user_id: str) -> list[dict]:
    with connect() as c:
        # created_at has 1-second resolution (_now()), and preferences are
        # plausibly added back-to-back within the same second -- rowid (SQLite's
        # implicit, monotonically-increasing insertion order) breaks the tie so
        # "newest first" still holds even when the timestamps are identical.
        rows = c.execute(
            "SELECT * FROM user_profile WHERE user_id=? ORDER BY created_at DESC, rowid DESC",
            (user_id,)).fetchall()
    return [_note(r) for r in rows]


def add_profile_entry(user_id: str, text: str) -> dict:
    entry = {"id": uuid.uuid4().hex[:12], "user_id": user_id, "text": text, "created_at": _now()}
    with connect() as c:
        c.execute("INSERT INTO user_profile VALUES (:id,:user_id,:text,:created_at)", entry)
    return entry


def delete_profile_entry(user_id: str, entry_id: str) -> bool:
    with connect() as c:
        cur = c.execute("DELETE FROM user_profile WHERE user_id=? AND id=?",
                        (user_id, entry_id))
    return cur.rowcount > 0


# ---------------------------------------------------------------- LLM 供应商配置
#
# 全局设置，不分用户——选的是"这台部署用哪个 LLM 后端"，不是个人偏好。

_PROVIDER_CONFIG_ID = "default"
_PROVIDER_CONFIG_DEFAULTS = {
    "provider": "local", "gpt_api_key": "", "gpt_model": "gpt-4.1-mini",
    "gpt_base_url": "https://api.openai.com/v1", "asr_base_url": "", "auto_sync_notes": 0,
}


def get_provider_config() -> dict:
    """没设置过就是这几个默认值（provider='local'，之后由
    get_active_llm_config() 退回 .env 配置）——不代表 GPT 那几个字段
    生效了，只有 provider 真的是 'gpt' 才会用它们。"""
    with connect() as c:
        row = c.execute(
            "SELECT * FROM provider_config WHERE id=?", (_PROVIDER_CONFIG_ID,)).fetchone()
    if not row:
        return dict(_PROVIDER_CONFIG_DEFAULTS)
    return {k: row[k] for k in _PROVIDER_CONFIG_DEFAULTS}


def set_provider_config(provider: str, gpt_api_key: str | None = None,
                        gpt_model: str | None = None, gpt_base_url: str | None = None,
                        asr_base_url: str | None = None, auto_sync_notes: bool | None = None) -> dict:
    """更新全局供应商配置。gpt_api_key/gpt_model/gpt_base_url 传 None（不传）
    时保留原值——比如只是把 provider 从 'gpt' 切回 'local' 再切回来，不用
    重新填一遍已经存过的 key。"""
    if provider not in ("local", "gpt"):
        raise ValueError("provider must be 'local' or 'gpt'")
    current = get_provider_config()
    merged = {
        "provider": provider,
        "gpt_api_key": current["gpt_api_key"] if gpt_api_key is None else gpt_api_key,
        "gpt_model": current["gpt_model"] if gpt_model is None else (gpt_model or current["gpt_model"]),
        "gpt_base_url": current["gpt_base_url"] if gpt_base_url is None else (gpt_base_url or current["gpt_base_url"]),
        # 语音地址跟 key 一样：不传=保留；传空串=清掉、退回 .env 默认
        "asr_base_url": current["asr_base_url"] if asr_base_url is None else asr_base_url.strip().rstrip("/"),
        "auto_sync_notes": int(current["auto_sync_notes"]) if auto_sync_notes is None else int(bool(auto_sync_notes)),
    }
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO provider_config "
            "(id, provider, gpt_api_key, gpt_model, gpt_base_url, asr_base_url, auto_sync_notes, updated_at) "
            "VALUES (:id,:provider,:gpt_api_key,:gpt_model,:gpt_base_url,:asr_base_url,:auto_sync_notes,:updated_at)",
            {"id": _PROVIDER_CONFIG_ID, "updated_at": _now(), **merged})
    return merged


def get_active_llm_config() -> dict:
    """实际生效的 LLM 端点——选了 GPT 且填了 key 就用 GPT 的
    base_url/api_key/model，否则退回 .env 里配的本地模型默认值。

    llm.py 和 kite_memory.py 都从这里取，不直接读 Settings 的 llm_* 字段：
    Settings 走 pydantic-settings + @lru_cache，是进程启动时读一次 env
    定死的，改配置页不会让它实时生效，也不该为了这个改成运行时可变——
    那是给"部署环境切换"用的，跟"用户在设置页切供应商"是两件事，前者
    改 .env 重启，后者查这张表。"""
    cfg = get_provider_config()
    if cfg["provider"] == "gpt" and cfg["gpt_api_key"]:
        return {"base_url": cfg["gpt_base_url"], "api_key": cfg["gpt_api_key"], "model": cfg["gpt_model"]}
    s = get_settings()
    return {"base_url": s.llm_base_url, "api_key": s.llm_api_key, "model": s.llm_model}


def get_asr_base_url() -> str:
    """实际生效的语音服务地址：设置页填了就用它，没填退回 .env（同 get_active_llm_config 的思路）。"""
    return get_provider_config()["asr_base_url"] or get_settings().whisper_base_url


# ---------------------------------------------------------------- harness 的 run 历史

def record_harness_run(key: str, status: str, rounds: int,
                       final_scores: dict[str, int], weak_dimensions: list[str]) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO harness_runs "
            "(id, key, status, rounds, final_scores, weak_dimensions, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), key, status, rounds,
             json.dumps(final_scores, ensure_ascii=False),
             json.dumps(weak_dimensions, ensure_ascii=False), _now()))
        # 一个 key（一篇笔记 / 一个分段）只留最近 50 次：策略只看最近几次，
        # 再往前的除了占地方没有用
        c.execute("DELETE FROM harness_runs WHERE key=? AND id NOT IN ("
                  "SELECT id FROM harness_runs WHERE key=? ORDER BY created_at DESC, rowid DESC LIMIT 50)",
                  (key, key))


def recent_harness_runs(key: str, limit: int = 3) -> list[dict]:
    with connect() as c:
        # created_at is second-precision (see _now()) -- several rounds can
        # legitimately finish within the same second, so break ties with
        # rowid (monotonic with insertion order) rather than leaving SQLite
        # to pick an arbitrary order among equal timestamps.
        rows = c.execute(
            "SELECT * FROM harness_runs WHERE key=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (key, limit)).fetchall()
    return [
        {
            "key": row["key"], "status": row["status"], "rounds": row["rounds"],
            "final_scores": json.loads(row["final_scores"]),
            "weak_dimensions": json.loads(row["weak_dimensions"]),
            "timestamp": row["created_at"],
        }
        for row in rows
    ]


def sweep_orphan_jobs() -> int:
    """把上次进程退出时还没跑完的任务标记掉。启动时调一次。

    后台任务活在进程里，进程一没了它们就没了——但数据库里的状态还停在
    queued/running。不清理的话：进度面板永远显示「处理中…」，而"同时只跑一个
    导入任务"的检查会认为一直有任务在跑，**用户再也导不进任何东西**。
    """
    with connect() as c:
        # 有 payload 落盘的（导入任务）能断点续跑：没跑完的 item 回到 queued，job 标 interrupted，
        # 界面上给「继续」。其它的（批量上传的字节没落盘）只能标失败。
        resumable = [r["id"] for r in c.execute(
            "SELECT id FROM ingest_jobs WHERE payload_path<>'' AND status NOT IN ('done','error','cancelled','interrupted')")]
        n = 0
        for jid in resumable:
            n += c.execute("UPDATE ingest_items SET status='queued', detail='' WHERE job_id=? AND status NOT IN ('done','failed','cancelled')",
                           (jid,)).rowcount
            c.execute("UPDATE ingest_jobs SET status='interrupted', detail='服务重启，任务中断——可以继续' WHERE id=?", (jid,))
        n += c.execute(
            "UPDATE ingest_items SET status='failed', "
            "detail='服务重启，任务中断' WHERE status NOT IN ('done','failed','cancelled')"
            " AND job_id NOT IN (SELECT id FROM ingest_jobs WHERE status='interrupted')"
        ).rowcount
        c.execute("UPDATE ingest_jobs SET status='error', "
                  "detail='服务重启，任务中断' "
                  "WHERE status NOT IN ('done','error','cancelled','interrupted')")
    return n



# ------------------------------------------------------- skill configuration

def skill_configs(user_id: str) -> dict[str, dict]:
    """Our settings for each installed skill, keyed by directory name.

    Content is never in here -- it stays in the SKILL.md directory on disk.
    A skill with no row yet gets sensible defaults from the caller.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT slug, enabled, scopes, sandbox, source, idx FROM skill_config "
            "WHERE user_id = ?", (user_id,)).fetchall()
    return {
        r["slug"]: {
            "enabled": bool(r["enabled"]),
            "scopes": [s for s in (r["scopes"] or "").split(",") if s],
            "sandbox": r["sandbox"],
            "source": r["source"],
            "idx": r["idx"],
        }
        for r in rows
    }


def set_skill_config(user_id: str, slug: str, *, enabled: bool | None = None,
                     scopes: list[str] | None = None, sandbox: str | None = None,
                     source: str | None = None, idx: int | None = None) -> None:
    """Upsert one skill's configuration; unspecified fields keep their value.

    First-insert defaults are deliberately conservative: ``sandbox='none'``
    means an imported skill's scripts do not run until the user grants
    permission explicitly, the same way installing an app doesn't grant it
    the camera.
    """
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO skill_config (user_id, slug) VALUES (?, ?)",
                     (user_id, slug))
        for column, value in (("enabled", None if enabled is None else int(enabled)),
                              ("scopes", None if scopes is None else ",".join(scopes)),
                              ("sandbox", sandbox),
                              ("source", source),
                              ("idx", idx)):
            if value is not None:
                conn.execute(
                    f"UPDATE skill_config SET {column} = ? WHERE user_id = ? AND slug = ?",
                    (value, user_id, slug))
        conn.commit()


def delete_skill_config(user_id: str, slug: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM skill_config WHERE user_id=? AND slug=?",
                     (user_id, slug))
        conn.commit()


# ---------------------------------------------------------------- 轮末快照


def save_snapshot(user_id: str, note_id: str, mode: str, round_idx: int,
                  state: str) -> str:
    """存一份轮末暂停。**同一篇只留最新的一份**：正文已经往前走了，旧的那份
    恢复出来只会把新内容盖掉；探针实拍两次「逐轮我来定」就攒了两份。"""
    run_id = uuid.uuid4().hex[:12]
    with connect() as c:
        if note_id:
            c.execute("DELETE FROM harness_snapshots WHERE user_id=? AND note_id=?",
                      (user_id, note_id))
        c.execute(
            "INSERT INTO harness_snapshots (id,user_id,note_id,mode,round,state,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (run_id, user_id, note_id, mode, round_idx, state, _now()))
        c.commit()
    return run_id


def get_snapshot(user_id: str, run_id: str) -> dict | None:
    """Scoped by user on purpose: a run id is the only thing the resume
    endpoint takes, and one user must not be able to resume another's run."""
    with connect() as c:
        row = c.execute(
            "SELECT * FROM harness_snapshots WHERE id=? AND user_id=?",
            (run_id, user_id)).fetchone()
    return dict(row) if row else None


def list_snapshots(user_id: str, limit: int = 20) -> list[dict]:
    """State 本体不返回——它可以有几十 KB，而这个列表只是给用户看
    「有哪些跑到一半在等我」。"""
    with connect() as c:
        rows = c.execute(
            "SELECT id, note_id, mode, round, created_at FROM harness_snapshots "
            "WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, max(1, min(limit, 100)))).fetchall()
    return [dict(r) for r in rows]


def delete_snapshot(user_id: str, run_id: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM harness_snapshots WHERE id=? AND user_id=?",
                  (run_id, user_id))
        c.commit()


def prune_snapshots(user_id: str, keep: int = 20) -> int:
    """A paused run the user never came back to is dead weight. Keeping the
    most recent few per user is enough: resuming something from last month
    would apply month-old material to a note that has moved on."""
    with connect() as c:
        rows = c.execute(
            "SELECT id FROM harness_snapshots WHERE user_id=? "
            "ORDER BY created_at DESC", (user_id,)).fetchall()
        stale = [r["id"] for r in rows[keep:]]
        for run_id in stale:
            c.execute("DELETE FROM harness_snapshots WHERE id=?", (run_id,))
        c.commit()
    return len(stale)
