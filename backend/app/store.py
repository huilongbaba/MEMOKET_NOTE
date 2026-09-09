"""笔记持久化。SQLite 足够原型用，且零外部依赖。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',
    pinned      INTEGER NOT NULL DEFAULT 0,
    folder_id   TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, updated_at DESC);
-- idx_notes_folder is created in connect(), AFTER the folder_id migration
-- below runs -- on an already-existing (pre-migration) notes table,
-- CREATE TABLE IF NOT EXISTS is a no-op, so an index on folder_id right
-- here would reference a column that doesn't exist yet on that table.

CREATE TABLE IF NOT EXISTS folders (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_folders_user ON folders(user_id, created_at);

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
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    folder_id   TEXT NOT NULL,
    goal        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active',
    doc_note_id TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_writing_plans_folder ON writing_plans(user_id, folder_id, status);

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
    updated_at   TEXT NOT NULL
);

-- scoring.RunHistoryStore 的落地实现（见 app/harness_adapter.py）。
-- key 是调用方定的"同一件反复发生的事情"是什么——note_harness 传
-- note_id，writing_plan 传 folder_id，包本身不关心这个约定。
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


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    try:
        conn.execute("ALTER TABLE ingest_jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # 列已存在——老库升级用，新库走 _SCHEMA 就已经带这一列
    try:
        conn.execute("ALTER TABLE notes ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE notes ADD COLUMN folder_id TEXT")
    except sqlite3.OperationalError:
        pass
    # 写作骨架（核心张力 + 结构节拍）跟着笔记走。
    #
    # 之前它只活在前端内存里，`open()` 一进新笔记就清空——换一篇、刷新页面、
    # 甚至无限续写开着「跟随」自动切到下一段，骨架就没了。而 harness 每轮都
    # 要拿它当主线依据，没了就得重新花一次模型调用生成，或者干脆没有主线跑。
    # beats 存成 JSON 数组字符串。
    try:
        conn.execute("ALTER TABLE notes ADD COLUMN spine TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE notes ADD COLUMN beats TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_folder ON notes(user_id, folder_id, updated_at DESC)")
    # skill_config 是这一版新建的，但真实库里已经跑过一轮，
    # CREATE TABLE IF NOT EXISTS 不会给它补上后加的列。
    try:
        conn.execute("ALTER TABLE skill_config ADD COLUMN idx INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
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


def create_note(user_id: str, title: str, content: str, folder_id: str | None = None) -> dict:
    note = {"id": uuid.uuid4().hex[:12], "user_id": user_id, "title": title,
            "content": content, "pinned": 0, "folder_id": folder_id,
            "created_at": _now(), "updated_at": _now()}
    with connect() as c:
        c.execute(
            "INSERT INTO notes (id,user_id,title,content,pinned,folder_id,created_at,updated_at) "
            "VALUES (:id,:user_id,:title,:content,:pinned,:folder_id,:created_at,:updated_at)", note)
    return {**note, "spine": "", "beats": []}


def update_note(user_id: str, note_id: str, title: str, content: str) -> dict | None:
    with connect() as c:
        cur = c.execute(
            "UPDATE notes SET title=?, content=?, updated_at=? "
            "WHERE user_id=? AND id=?",
            (title, content, _now(), user_id, note_id))
        if cur.rowcount == 0:
            return None
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


def delete_note(user_id: str, note_id: str) -> bool:
    with connect() as c:
        cur = c.execute("DELETE FROM notes WHERE user_id=? AND id=?",
                        (user_id, note_id))
    return cur.rowcount > 0


def set_note_folder(user_id: str, note_id: str, folder_id: str | None) -> dict | None:
    with connect() as c:
        cur = c.execute(
            "UPDATE notes SET folder_id=?, updated_at=? WHERE user_id=? AND id=?",
            (folder_id, _now(), user_id, note_id))
        if cur.rowcount == 0:
            return None
    return get_note(user_id, note_id)


def notes_in_folder(user_id: str, folder_id: str, exclude_id: str = "", limit: int = 5) -> list[dict]:
    """无限续写用来把同文件夹里的其他笔记当参考上下文——只取标题+正文，
    按最近更新排在前面，数量封顶避免把 prompt 撑爆。"""
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM notes WHERE user_id=? AND folder_id=? AND id != ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (user_id, folder_id, exclude_id, limit)).fetchall()
    return [_note(r) for r in rows]


# ---------------------------------------------------------------- 文件夹

def list_folders(user_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM folders WHERE user_id=? ORDER BY created_at",
            (user_id,)).fetchall()
    return [_note(r) for r in rows]


def create_folder(user_id: str, name: str) -> dict:
    folder = {"id": uuid.uuid4().hex[:12], "user_id": user_id, "name": name, "created_at": _now()}
    with connect() as c:
        c.execute(
            "INSERT INTO folders (id,user_id,name,created_at) VALUES (:id,:user_id,:name,:created_at)",
            folder)
    return folder


def rename_folder(user_id: str, folder_id: str, name: str) -> dict | None:
    with connect() as c:
        cur = c.execute(
            "UPDATE folders SET name=? WHERE user_id=? AND id=?",
            (name, user_id, folder_id))
        if cur.rowcount == 0:
            return None
        row = c.execute("SELECT * FROM folders WHERE user_id=? AND id=?",
                        (user_id, folder_id)).fetchone()
    return dict(row) if row else None


def delete_folder(user_id: str, folder_id: str) -> bool:
    with connect() as c:
        # 笔记不跟着删——文件夹只是分类，删文件夹时笔记退回「未分类」
        c.execute("UPDATE notes SET folder_id=NULL WHERE user_id=? AND folder_id=?",
                  (user_id, folder_id))
        cur = c.execute("DELETE FROM folders WHERE user_id=? AND id=?",
                        (user_id, folder_id))
    return cur.rowcount > 0


# ---------------------------------------------------------------- 无限续写计划

def get_active_plan(user_id: str, folder_id: str) -> dict | None:
    with connect() as c:
        row = c.execute(
            "SELECT * FROM writing_plans WHERE user_id=? AND folder_id=? AND status='active'",
            (user_id, folder_id)).fetchone()
    return dict(row) if row else None


def get_plan(user_id: str, plan_id: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM writing_plans WHERE user_id=? AND id=?",
                        (user_id, plan_id)).fetchone()
    return dict(row) if row else None


def create_plan(user_id: str, folder_id: str, goal: str) -> dict:
    """新建之前先把这个文件夹里任何还挂着 active 的旧 plan 标成
    abandoned——同一个文件夹同时只应该有一个活跃计划，不然 harness 不知道
    该跑哪个。"""
    plan = {"id": uuid.uuid4().hex[:12], "user_id": user_id, "folder_id": folder_id,
            "goal": goal, "status": "active", "doc_note_id": "",
            "created_at": _now(), "updated_at": _now()}
    with connect() as c:
        c.execute(
            "UPDATE writing_plans SET status='abandoned' WHERE user_id=? AND folder_id=? AND status='active'",
            (user_id, folder_id))
        c.execute(
            "INSERT INTO writing_plans (id,user_id,folder_id,goal,status,doc_note_id,created_at,updated_at) "
            "VALUES (:id,:user_id,:folder_id,:goal,:status,:doc_note_id,:created_at,:updated_at)", plan)
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
                "INSERT INTO ingest_items VALUES "
                "(:id,:job_id,:idx,:filename,:kind,:status,:facts,:detail,:updated_at)",
                item)
            items.append(item)
    return job_id, items


def set_item(item_id: str, status: str, facts: int = 0, detail: str = "") -> None:
    with connect() as c:
        c.execute(
            "UPDATE ingest_items SET status=?, facts=?, detail=?, updated_at=? WHERE id=?",
            (status, facts, detail[:500], _now(), item_id))


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
    "gpt_base_url": "https://api.openai.com/v1",
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
                        gpt_model: str | None = None, gpt_base_url: str | None = None) -> dict:
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
    }
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO provider_config "
            "(id, provider, gpt_api_key, gpt_model, gpt_base_url, updated_at) "
            "VALUES (:id,:provider,:gpt_api_key,:gpt_model,:gpt_base_url,:updated_at)",
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


# ---------------------------------------------------------------- scoring 落地存储

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
        n = c.execute(
            "UPDATE ingest_items SET status='failed', "
            "detail='服务重启，任务中断' WHERE status NOT IN ('done','failed','cancelled')"
        ).rowcount
        c.execute("UPDATE ingest_jobs SET status='error', "
                  "detail='服务重启，任务中断' "
                  "WHERE status NOT IN ('done','error','cancelled')")
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
    run_id = uuid.uuid4().hex[:12]
    with connect() as c:
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
