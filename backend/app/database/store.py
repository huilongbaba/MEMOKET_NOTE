"""笔记持久化。SQLite 足够原型用，且零外部依赖。"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .wordcount import word_count
from ..editor import intent as intent_mod
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

-- 材料托盘（P14，agent-native-editor §3.4）：这篇笔记显式「摊在桌上」的材料——别的笔记 / 一条事实 /
-- 导入的一段 / 从别处摘的一段。**跟 note_citations 相反：这张表是用户维护的，不从正文重建**——
-- 引用是「正文里写了」，托盘是「写之前先摆出来」。harness 取材料时托盘里的排最前、不受筛、不滚出窗口。
-- kind ∈ note | fact | import | selection；ref_id 是 note id / fact id（import / selection 可以为空）；
-- excerpt 是进 prompt 的那段（笔记是开头几百字、事实是原话）；position 是托盘里的顺序（用户拖的）。
CREATE TABLE IF NOT EXISTS note_tray (
    id        TEXT PRIMARY KEY,
    user_id   TEXT NOT NULL,
    note_id   TEXT NOT NULL,
    kind      TEXT NOT NULL,
    ref_id    TEXT NOT NULL DEFAULT '',
    title     TEXT NOT NULL DEFAULT '',
    excerpt   TEXT NOT NULL DEFAULT '',
    position  INTEGER NOT NULL DEFAULT 0,
    added_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tray_note ON note_tray(user_id, note_id, position);

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
-- 模型用量账本：每次调用一行（谁、哪个功能、哪个模型、token、耗时）。设置页「用量」看的就是它。
CREATE TABLE IF NOT EXISTS llm_usage (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL DEFAULT '',
    feature           TEXT NOT NULL DEFAULT '',
    model             TEXT NOT NULL DEFAULT '',
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    ms                INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_user_time ON llm_usage(user_id, created_at);

-- 最近删除（Trilium 的删除是可找回的）：删掉的笔记连同它的 branches 存一份快照，30 天内可恢复
CREATE TABLE IF NOT EXISTS note_trash (
    user_id     TEXT NOT NULL,
    note_id     TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    chars       INTEGER NOT NULL DEFAULT 0,
    payload     TEXT NOT NULL,
    deleted_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, note_id)
);

-- 导回记录：这篇在哪个平台有副本、远端 id / 路径、上次导回时间（docs/import-sync-plan.md §2）
CREATE TABLE IF NOT EXISTS note_remotes (
    user_id     TEXT NOT NULL,
    note_id     TEXT NOT NULL,
    platform    TEXT NOT NULL,
    remote_id   TEXT NOT NULL DEFAULT '',
    remote_path TEXT NOT NULL DEFAULT '',   -- Obsidian：vault 里的相对路径；Notion / 飞书：对面文档的 URL（P2-fix）
    exported_at TEXT NOT NULL,
    remote_rev  TEXT NOT NULL DEFAULT '',   -- 我们写完时对面的版本（Notion last_edited_time / 飞书 revision_id）：下次不一样 = 对方改过
    PRIMARY KEY (user_id, note_id, platform)
);

-- 冲突收件箱：摄入时新事实跟旧事实撞上的（docs/agent-native-editor.md §3.3.1）
-- 实体合并的裁决（docs/kb-entities-plan.md 第二部分）。
-- **只记「人怎么判的」，候选每次全量重算**——用户定的形状（第 659 轮）：
-- 一次性后处理，不做增量。重跑一遍扫描时，这张表里已经判过的那些对直接跳过，
-- 所以同一对**不会被问第二遍**，包括被否掉的那些。
-- 合并只在展示 / 查询层生效（跟 `kb/entities.EntityGroups` 一样），知识库不动、随时可逆。
CREATE TABLE IF NOT EXISTS kb_entity_merges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    code_a      TEXT NOT NULL,          -- 两个码按字典序存，跟谁在左谁在右无关
    code_b      TEXT NOT NULL,
    decision    TEXT NOT NULL,          -- same（是同一个）/ different（不是）/ drop_a / drop_b（那个压根不该是实体）
    why         TEXT NOT NULL DEFAULT '',   -- 哪条信号点出来的：initials / translit / spelling / substring
    decided_at  TEXT NOT NULL,
    UNIQUE (user_id, code_a, code_b)
);

CREATE TABLE IF NOT EXISTS kb_conflicts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    new_fact_id TEXT NOT NULL,
    old_fact_id TEXT NOT NULL,
    unit        TEXT NOT NULL DEFAULT '',
    say         TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'open',
    resolution  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    UNIQUE (user_id, new_fact_id, old_fact_id)
);

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

-- **每一轮**的分数。跟 harness_runs 不是一回事：那张一次跑一行、只有最后一轮。
--
-- 没有这张表，「第 N+1 轮比第 N 轮好吗」这个问题在现有数据里**无法回答**——
-- 每轮的评分只活在 SSE 的 CUSTOM_EVALUATE 事件里，跑完就没了。而这正是判断
-- 「多跑一轮买到了什么」唯一的依据（docs/harness-effect-plan.md P3）。
--
-- `content_len` 一起记：实测三篇笔记分数单调下滑的同时正文一直在长，
-- 两条曲线要能并排看。
CREATE TABLE IF NOT EXISTS harness_rounds (
    id           TEXT PRIMARY KEY,
    key          TEXT NOT NULL,
    run_id       TEXT NOT NULL DEFAULT '',
    round        INTEGER NOT NULL,
    scores       TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT '',
    weakest      TEXT NOT NULL DEFAULT '',
    content_len  INTEGER NOT NULL DEFAULT 0,
    facts_new    INTEGER NOT NULL DEFAULT 0,
    facts_total  INTEGER NOT NULL DEFAULT 0,
    tool_calls   INTEGER NOT NULL DEFAULT 0,
    repeat_calls INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_harness_rounds_run ON harness_rounds(run_id, round);
CREATE INDEX IF NOT EXISTS idx_harness_rounds_key ON harness_rounds(key, created_at DESC);

-- **用户拿到 AI 写的东西之后，对它做了什么**（计划 9.1 / [MECH] §5 / [IND] §8⑥）。
--
-- 这整个回路没有 ground truth：没有任何证据表明「五维全 2 分」等于「用户愿意
-- 留下这篇笔记」，而 Goodhart 已经发生过一次（`middleware/best_of.py` 开头记
-- 着：第 3 轮为了讨好打分器加了一张单值柱状图，然后第 3 轮被交付了）。唯一
-- 真实的信号是用户拿到结果之后对它做了什么——PRELUDE（NeurIPS 2024）和
-- coactive learning 给了现成的名字，后者的假设弱到只要求「编辑后的文本比提出
-- 的文本更好」，我们这儿天然成立。
--
-- **这张表只存 id + 一行数**，跟账本那条边界（只存 id + 一行，全文永远回
-- kite 取）是同一个道理：AI 那一份正文存在 `note_revisions` 里（跑完落的那
-- 一版，`reason='harness'`、`run_id` 指回这一行），这里只记指针和几个数。
-- **它不是第二份笔记副本。**
--
-- 一行的生命周期：跑完开一行（`status='open'`，AI 那一侧填好）→ 用户下一次
-- 真的改了正文再保存时关掉（`status='edited'`，填 `kept_chars` / `user_chars`）
-- → 同一篇又跑了一次而上一行还开着，上一行记 `status='superseded'`。
--
-- **只采集，不调参。** 样本不够时按它调参比不调更糟——这句话同时写在
-- `middleware/edits.py` 里，那儿是真会被下一个人读到的地方。
CREATE TABLE IF NOT EXISTS harness_edits (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    note_id      TEXT NOT NULL,
    run_id       TEXT NOT NULL DEFAULT '',   -- harness_runs.id / harness_rounds.run_id
    key          TEXT NOT NULL DEFAULT '',   -- `<模式>:<笔记 id>`，跟 harness_runs.key 同一个写法
    revision_id  TEXT NOT NULL DEFAULT '',   -- note_revisions 里 AI 那一版
    status       TEXT NOT NULL DEFAULT 'open',
    base_chars   INTEGER NOT NULL DEFAULT 0, -- 这次跑开跑时正文有多长（用户自己写的那部分）
    ai_chars     INTEGER NOT NULL DEFAULT 0, -- 跑完交出去多长
    user_chars   INTEGER NOT NULL DEFAULT 0, -- 用户改完存下来多长
    kept_chars   INTEGER NOT NULL DEFAULT 0, -- 两份逐字对齐后仍然一样的字数
    created_at   TEXT NOT NULL,
    edited_at    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_harness_edits_note ON harness_edits(user_id, note_id, status);
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
    # 命中了多少缓存的输入 token。**没有这一列，"缓存命中率"这个问题答不出来**
    # ——而两条长文 harness 占了全部模型调用的 91%，中位入 10537 / 出 184 token，
    # 输入侧是这个应用里唯一值得认真优化的地方（docs/harness-context-engineering.md）。
    # 字段名按 provider 走：/chat/completions 是 usage.prompt_tokens_details.cached_tokens。
    ("llm_usage", "cached_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("llm_usage", "cache_write_tokens", "INTEGER NOT NULL DEFAULT 0"),
    # **怎么停的**，跟"打分模型怎么裁决"不是一回事。原来只记 st.ev.status，
    # 于是 54% 的跑都记成 `continue`——而"跑满轮数还没达标"、"连着几轮没动静
    # 自己停了"、"比最好那轮更差主动停"三件事该采取的行动完全不同
    # （docs/harness-effect-plan.md P4）。
    ("harness_runs", "stopped", "TEXT NOT NULL DEFAULT ''"),
    # 查询级短路省掉了几次后端查询（计划 2.1）。**没有这一列，「短路做没做、
    # 省了多少」跟「模型这轮本来就没重复查」在数据上长得一模一样**——而
    # `repeat_calls` 只数得到进了 `trace.calls` 的那些，`hooks/note.prepare`
    # 里直接调的主题树 / 多跳根本不在里面。
    ("harness_rounds", "cached_calls", "INTEGER NOT NULL DEFAULT 0"),
    # 这一轮有几条取回来的事实是「已经被别的事实取代了」（计划 2.2）。
    # 库里 `kb_conflicts` 一直记着，而写作 harness 从来不问——
    # 于是 6 月 3 日那条和 8 月 5 日那条都可能被写进正文。
    ("harness_rounds", "superseded", "INTEGER NOT NULL DEFAULT 0"),
    # 这一轮模型提了几条修订、其中几条没落地（计划 11.3）。**两列一起加，
    # 因为只有分子说明不了任何事**：丢掉 3 条既可能是「提 4 条守卫拦了 3」，
    # 也可能是「提 30 条成了 27」。一次性抽样的分母在 `.local/samples` 的
    # 360 次 soak 跑里：落地 2280 条、`dropped` 事件 1032 条（45 条是元话语
    # 删除通知），**丢掉的约占提出的 30.2%**，71.4% 的跑至少丢过一条。
    # `revisions_dropped` 算的是**提出减落地**，不是发出去的事件数——
    # 应用循环里有四条路是 `continue` 掉的、一个事件都不发（不是 dict / op
    # 不认识 / **锚点在正文里找不到** / 改完跟原文一样），而那一档正是
    # 「用户看不到、我们也没统计」里最看不见的一半。
    ("harness_rounds", "revisions_proposed", "INTEGER NOT NULL DEFAULT 0"),
    ("harness_rounds", "revisions_dropped", "INTEGER NOT NULL DEFAULT 0"),
    # 这一轮工具循环里有几发被**深度门**丢掉（批 24）。`agent_loop._cap_calls`
    # 从第 2 轮起把纯广度的关键词撒网整批丢掉，而这件事故意不算进 `truncated`
    # （「那是刻意的取舍，不是资源不够」）——于是它此前**在任何一个数上都不
    # 存在**：「模型发了 4 个调用全被丢了」跟「模型一个都没发」落到库里长得
    # 一模一样。而 `DEPTH_TOOLS` 的注释说这是观测到的常态（4 次真实采样全部
    # 撞上限）。**一个被当成常态的行为，得有个数在数它**，否则「深度门是不是
    # 太狠」永远答不出来。
    ("harness_rounds", "depth_dropped", "INTEGER NOT NULL DEFAULT 0"),
    # P2-fix：Notion / 飞书也要「对方改过就先提示」（Obsidian 早就有）。记我们写完时对面的版本号。
    ("note_remotes", "remote_rev", "TEXT NOT NULL DEFAULT ''"),
    # ---- 三列探针（批 27 / §5 第 8、9 行）。加之前先把取值列全、逐个问
    # 「它真写得进去吗」——批 22 的 `stopped` 从加进来那天起就记不到
    # `max_rounds`，这条规矩就是那么来的。取值表在
    # `harness/checks/claims.py` 那段 `abstained` 注释里。
    #
    # `claim_atoms`：这一轮新写的正文里有几个**候选原子**（完整日期 / 署名里
    # 的那个名字）。§5 第 8 行「候选原子率」在探针语料上量过（`user` 0.89
    # 个/篇），**真跑那一档一直量不了**——批 18 报的「真跑 5 轮 0 候选」是
    # 一次性算出来的，没有落库，换一批跑就得重算一次。
    # **-1 = 这个模式压根没有那条判据**（六个 block 模式），跟「判了、0 个
    # 候选」严格分开：记成同一个 0 就又是一次 `stopped` 那种坏法。
    ("harness_rounds", "claim_atoms", "INTEGER NOT NULL DEFAULT -1"),
    # `fired_checks`：这一轮**哪几条确定性判据命中了**（JSON 数组）。
    # §5 第 9 行「这一节材料够不够写的照做率」批 26 报的是**量不了、分母 0**
    # ——299 个相邻轮对里能判定的 0 对，因为库里根本不知道上一轮是哪条判据
    # 在说话（`CUSTOM_CHECK_HIT` 只进 SSE，不落库），而五条判据全都落在
    # `factual_grounding` 这一维上，`weakest` 答不了这个问题。
    # 是**数组**不是单值：卡死放行（`STUCK_ROUNDS`）之后后面还能再命中一条。
    ("harness_rounds", "fired_checks", "TEXT NOT NULL DEFAULT ''"),
    # `abstained`：`unsupported_specifics` 这一轮判没判、没判是因为什么。
    # 「判据没开火」和「判据坏了」是两件事，**只量前者等于没量**（批 26 ④）
    # ——而这一列是把"没开火"再拆成四档的那一列。
    ("harness_rounds", "abstained", "TEXT NOT NULL DEFAULT ''"),
    # 这次跑一共花了多少（计划 12.3）。**没有这两列，「单次跑的成本」只能靠
    # 把 `llm_usage` 按时间窗口贴回 `harness_rounds` 来重建**——批 23 就是这么
    # 量的（158 次跑、1943 行用量，63 行贴不上），而那份重建在两次跑重叠时
    # 会把账算到隔壁（实测 158 次跑里 11 对相邻跑是重叠的）。落了库之后
    # 「一次跑花多少」就是一个能直接 SELECT 的数。
    #
    # **`tokens` 是入+出的原始 token，不折算价格**：库里没有价目表，而缓存
    # 命中的输入 token 便宜一档（`llm_usage.cached_tokens` 另记），所以这个
    # 数是**偏保守**的——真金白银只会比它少。
    ("harness_runs", "tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("harness_runs", "calls", "INTEGER NOT NULL DEFAULT 0"),
    # 这一版正文是哪一次跑交出来的（计划 9.1）。空串 = 用户自己保存时留的版本。
    ("note_revisions", "run_id", "TEXT NOT NULL DEFAULT ''"),
    # 这一版是哪一轮**烧进正文之前**的快照（P16，agent-native-editor §3.2「历史版本保留每次烧之前的快照」）。
    # `reason='round'` 的行每轮一行、`round_no` = 那一轮的序号；`reason='run_end'` 是这次跑收尾时的正文（round_no = 最后一轮）。
    # 0 = 跟轮次无关的版本（auto / manual / before_restore / harness）。
    ("note_revisions", "round_no", "INTEGER NOT NULL DEFAULT 0"),
    ("notes", "pinned", "INTEGER NOT NULL DEFAULT 0"),
    # 笔记图标（boxicons 的类名，如 bx-rocket；空 = 按文件夹 / 笔记默认）。Trilium 的 NoteIcon，
    # 那边存成 #iconClass 属性，我们没有属性系统就直接一列。
    ("notes", "icon", "TEXT NOT NULL DEFAULT ''"),
    # 写作骨架（核心张力 + 结构节拍）跟着笔记走。
    #
    # 之前它只活在前端内存里，`open()` 一进新笔记就清空——换一篇、刷新页面、
    # 甚至无限续写开着「跟随」自动切到下一段，骨架就没了。而 harness 每轮都
    # 要拿它当主线依据，没了就得重新花一次模型调用生成，或者干脆没有主线跑。
    # beats 存成 JSON 数组字符串。
    ("notes", "spine", "TEXT NOT NULL DEFAULT ''"),
    ("notes", "beats", "TEXT NOT NULL DEFAULT ''"),
    # 文档意图（P9，agent-native-editor §3.1）：目标 / 读者 / 完成标准 + 来源（prefill / user），JSON。
    # 标题下面常驻一行；所有作用在这篇上的 AI 动作把它当 system 的第一段。
    ("notes", "intent", "TEXT NOT NULL DEFAULT ''"),
    # skill_config 是这一版新建的，但真实库里已经跑过一轮，
    # CREATE TABLE IF NOT EXISTS 不会给它补上后加的列。
    ("skill_config", "idx", "INTEGER NOT NULL DEFAULT 0"),
    # 出厂技能**发出去的时候**是哪一版（SKILL.md 的 content_sha）。
    #
    # 播种一直是「目录已经在就跳过」——为的是别把用户改过的技能覆盖掉，这是对的。
    # 但代价是**出厂内容的修正永远到不了已经装过的用户**：第 613 轮把 11 个内置技能
    # 标题里缺的中西文空格补好了，界面上一个字都没变，因为它们早就播种进用户目录了。
    # 记下发出去那一版的 sha，升级时就能分清两件事——磁盘上还是我们发的那份（放心
    # 换成新的）还是用户动过（一个字都不碰）。跟 Obsidian 导回「对方改过就跳过」
    # 同一条路子。空 = 老库里播种时还没记，一律当成「用户可能动过」，不覆盖。
    ("skill_config", "seeded_sha", "TEXT NOT NULL DEFAULT ''"),
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
    # `note_id`：这一条导入落成了哪篇笔记（P15 #3：导入默认进托盘——前端等 job 跑完拿它把那几篇放进当前
    # 笔记的托盘）。只进知识库（`to=kb`）、同一份导第二次（`same`）都照记那篇的 id；本来就没建笔记的是空串。
    ("ingest_items", "note_id", "TEXT NOT NULL DEFAULT ''"),
    ("ingest_jobs", "payload_path", "TEXT NOT NULL DEFAULT ''"),
    ("ingest_jobs", "chunk_ms", "INTEGER NOT NULL DEFAULT 0"),
    ("ingest_jobs", "chunks_done", "INTEGER NOT NULL DEFAULT 0"),
    ("ingest_jobs", "chunks_total", "INTEGER NOT NULL DEFAULT 0"),   # 没有 item 的任务（笔记摄入 / 同步）自己记总块数
    ("ingest_jobs", "chars_done", "INTEGER NOT NULL DEFAULT 0"),
    ("ingest_jobs", "started_at", "TEXT NOT NULL DEFAULT ''"),
    # 笔记侧增量（docs/import-sync-plan.md §3）：这篇是从哪导来的、源侧稳定 id、上次导入时
    # 的正文哈希、上次导入时间。重导同一份：sha 没变整篇跳过；变了更新正文（本地没改过的话）。
    ("notes", "source", "TEXT NOT NULL DEFAULT ''"),
    ("notes", "source_id", "TEXT NOT NULL DEFAULT ''"),
    ("notes", "source_sha", "TEXT NOT NULL DEFAULT ''"),
    ("notes", "imported_at", "TEXT NOT NULL DEFAULT ''"),
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
    conn.execute("DELETE FROM harness_edits WHERE note_id NOT IN (SELECT id FROM notes)")


def _drop_orphan_runs(conn: sqlite3.Connection) -> None:
    """运行记录的 key 是 `<模式>:<笔记 id>`（note: / section: / prompt: / table: …），
    更早的版本就是光秃秃的笔记 id。v1 只认 `note:` 前缀，结果一个开发库里
    3858 条指向已删笔记的裸 id 行一直躺着（第 187 轮实测）。按「冒号后面那截
    （没冒号就整个）不在 notes 里」一次清掉。"""
    conn.execute(
        "DELETE FROM harness_runs WHERE "
        "(CASE WHEN instr(key, ':') > 0 THEN substr(key, instr(key, ':') + 1) ELSE key END) "
        "NOT IN (SELECT id FROM notes)")


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
    _migrate_once(conn, "drop-orphan-runs-v2", _drop_orphan_runs)
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
    # 文档意图同 beats：库里是 JSON 字符串，出去是 dict（坏 JSON 当空意图，别让整个接口 500）
    try:
        raw = json.loads(d.get("intent") or "{}")
    except (TypeError, ValueError):
        raw = {}
    d["intent"] = intent_mod.normalize(raw)
    return d


def _like(q: str) -> str:
    """用户输入拼进 LIKE：`%` `_` 是通配符，搜「_」「%」会把全库都匹配上（第 255 轮实测）。"""
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


PREVIEW_CHARS = 80      # 占位标题退回正文首行、重名补全带首句，80 字够；240 字在 413 篇的库上一次 300KB
BRIEF_MAX = 50          # 面板只画前 8 条，多给几十条让它排序就够；总数另给
_MD_MARK = re.compile(r"^\s*(#{1,6}|[-*>]|\d+\.)\s+", re.M)


def match_snippet(content: str, query: str, span: int = 40, before: int = 18) -> dict | None:
    """跟前端 util/snippet.ts 同一条规则：去掉标题井号 / 列表符，命中处前 `before` 后 `span` 字。"""
    q = (query or "").strip()
    if not q:
        return None
    text = re.sub(r"\s+", " ", _MD_MARK.sub("", content or ""))
    i = text.lower().find(q.lower())
    if i < 0:
        return None
    start, end = max(0, i - before), min(len(text), i + len(q) + span)
    return {"before": ("…" if start > 0 else "") + text[start:i], "hit": text[i:i + len(q)],
            "after": text[i + len(q):end] + ("…" if end < len(text) else "")}


def _first_body_line(content: str, title: str = "", limit: int = 60) -> str:
    """第一行有信息量的正文。`[[` 补全里同名笔记靠它分辨——三篇「创业一年回顾」（库里标题都是
    「未命名」、正文第一行就是这几个字）光看标题分不开（第 257 轮实拍）。
    规则：跳过跟显示名一样的那一行（占位标题的笔记显示名就是正文第一行）；优先取非标题的正文行，
    一行正文都没有（整篇只有骨架标题）就退回第一个小标题。"""
    lines = [ln.strip() for ln in (content or "").split("\n")[:60]]
    clean = lambda s: re.sub(r"[*_`\[\]]", "", re.sub(r"^([-*>+]|\d+\.|#{1,6})\s*", "", s)).strip()   # noqa: E731
    shown = (title or "").strip()
    if shown in ("", "未命名", "Untitled", "note"):
        shown = next((clean(ln) for ln in lines if ln), "")
    body, heads = [], []
    fenced = False
    for s in lines:
        if s.startswith("```"):          # 围栏里的是代码不是正文（第 544 轮：预览印出了 `code`）
            fenced = not fenced
            continue
        if fenced or not s or s.startswith("!["):
            continue
        c = clean(s)
        if len(c) <= 1 or c.lower() == shown.lower():
            continue
        (heads if s.startswith("#") else body).append(c)
    pick = body[0] if body else (heads[0] if heads else "")
    return pick[:limit]


def list_notes_brief(user_id: str, q: str = "") -> dict:
    """⌘K 和 `[[` 补全每敲一个字就拉一次列表：带全文的 `list_notes` 在 413 篇的库上是 580KB
    一次（第 197 轮量的）。这里只给标题 / 日期 / 前 240 字 / 有没有正文，正文命中的再附一截命中片段
    （在服务端算，只对命中的那几篇读全文）。"""
    with connect() as c:
        if q:
            like = _like(q)
            rows = c.execute(
                "SELECT id, title, updated_at, pinned, icon, content FROM notes WHERE user_id=? AND "
                "(title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\') ORDER BY pinned DESC, updated_at DESC",
                (user_id, like, like)).fetchall()
        else:
            rows = c.execute(
                "SELECT id, title, updated_at, pinned, icon, substr(content, 1, ?) AS content, "
                "length(trim(content)) > 0 AS has_body FROM notes WHERE user_id=? ORDER BY pinned DESC, updated_at DESC",
                (PREVIEW_CHARS * 8, user_id)).fetchall()   # 多取几行算 first_body，返回的 preview 仍只 80 字
    out = []
    for r in rows[:BRIEF_MAX]:
        content = r["content"] or ""
        d = {"id": r["id"], "title": r["title"] or "", "updated_at": r["updated_at"], "pinned": bool(r["pinned"]), "icon": r["icon"] or "",
             "preview": content[:PREVIEW_CHARS], "has_body": bool(r["has_body"]) if "has_body" in r.keys() else bool(content.strip()),
             "first_body": _first_body_line(content, r["title"] or ""), "snippet": None}
        if q and q.lower() not in (r["title"] or "").lower():
            d["snippet"] = match_snippet(content, q)
        out.append(d)
    return {"notes": out, "total": len(rows)}


def list_notes(user_id: str, q: str = "") -> list[dict]:
    with connect() as c:
        if q:
            like = _like(q)
            rows = c.execute(
                "SELECT * FROM notes WHERE user_id=? AND (title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\') "
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


def add_conflict(user_id: str, new_fact_id: str, old_fact_id: str, unit: str, say: str, source: str = "") -> bool:
    """同一对只记一次（重抽 / 重扫不会堆出重复的待办）。"""
    with connect() as c:
        cur = c.execute("INSERT OR IGNORE INTO kb_conflicts (user_id,new_fact_id,old_fact_id,unit,say,source,created_at) VALUES (?,?,?,?,?,?,?)",
                        (user_id, new_fact_id, old_fact_id, unit, say, source, _now()))
        return cur.rowcount > 0


# ---------------------------------------------------------- 实体合并的裁决
#
# 候选**不落库**：它是纯代码算出来的，每次扫描全量重算（用户定的形状，第 659 轮：
# 一次性后处理不做增量）。落库的只有人的判断，它有两个用处——合并生效、以及
# **不再问第二遍**。

def record_entity_decision(user_id: str, code_a: str, code_b: str, decision: str,
                           why: str = "") -> None:
    a, b = (code_a, code_b) if code_a <= code_b else (code_b, code_a)
    with connect() as c:
        c.execute("INSERT INTO kb_entity_merges (user_id,code_a,code_b,decision,why,decided_at)"
                  " VALUES (?,?,?,?,?,?)"
                  " ON CONFLICT(user_id,code_a,code_b) DO UPDATE SET decision=excluded.decision,"
                  " why=excluded.why, decided_at=excluded.decided_at",
                  (user_id, a, b, decision, why, _now()))


def entity_decisions(user_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT code_a,code_b,decision,why,decided_at FROM kb_entity_merges"
                         " WHERE user_id=? ORDER BY id", (user_id,)).fetchall()
    return [dict(r) for r in rows]


def forget_entity_decision(user_id: str, code_a: str, code_b: str) -> bool:
    """判错了要能撤——这是「可逆」那条承诺的一部分。"""
    a, b = (code_a, code_b) if code_a <= code_b else (code_b, code_a)
    with connect() as c:
        return c.execute("DELETE FROM kb_entity_merges WHERE user_id=? AND code_a=? AND code_b=?",
                         (user_id, a, b)).rowcount > 0


def list_conflicts(user_id: str, status: str = "open", limit: int = 100) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM kb_conflicts WHERE user_id=? AND status=? ORDER BY id DESC LIMIT ?",
                         (user_id, status, limit)).fetchall()
    return [dict(r) for r in rows]


def count_open_conflicts(user_id: str) -> int:
    with connect() as c:
        return int(c.execute("SELECT COUNT(*) FROM kb_conflicts WHERE user_id=? AND status='open'", (user_id,)).fetchone()[0])


def resolve_conflict(user_id: str, conflict_id: int, resolution: str) -> dict | None:
    with connect() as c:
        c.execute("UPDATE kb_conflicts SET status='resolved', resolution=? WHERE user_id=? AND id=?",
                  (resolution, user_id, conflict_id))
        row = c.execute("SELECT * FROM kb_conflicts WHERE user_id=? AND id=?", (user_id, conflict_id)).fetchone()
    return dict(row) if row else None


def drop_conflicts_for_facts(user_id: str, fact_ids: set[str]) -> int:
    """事实删了 / session 重抽了：指着它的待办一起收掉。"""
    if not fact_ids:
        return 0
    ids = list(fact_ids)
    with connect() as c:
        n = 0
        for i in range(0, len(ids), 400):
            part = ids[i:i + 400]
            q = ",".join("?" * len(part))
            n += c.execute(f"DELETE FROM kb_conflicts WHERE user_id=? AND (new_fact_id IN ({q}) OR old_fact_id IN ({q}))",
                           [user_id, *part, *part]).rowcount
        return n


def record_remote(user_id: str, note_id: str, platform: str, remote_id: str = "", remote_path: str = "", remote_rev: str = "") -> None:
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO note_remotes (user_id,note_id,platform,remote_id,remote_path,exported_at,remote_rev) VALUES (?,?,?,?,?,?,?)",
                  (user_id, note_id, platform, remote_id, remote_path, _now(), remote_rev))


def get_remote(user_id: str, note_id: str, platform: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM note_remotes WHERE user_id=? AND note_id=? AND platform=?",
                        (user_id, note_id, platform)).fetchone()
    return dict(row) if row else None


def list_remotes(user_id: str, note_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM note_remotes WHERE user_id=? AND note_id=? ORDER BY platform",
                         (user_id, note_id)).fetchall()
    return [dict(r) for r in rows]


def content_sha(content: str) -> str:
    import hashlib
    return hashlib.sha1(content.encode("utf-8")).hexdigest()[:16]


def find_note_by_source(user_id: str, source: str, source_id: str) -> dict | None:
    """这份源侧内容之前导成过哪篇笔记。"""
    if not source or not source_id:
        return None
    with connect() as c:
        row = c.execute("SELECT * FROM notes WHERE user_id=? AND source=? AND source_id=? ORDER BY created_at LIMIT 1",
                        (user_id, source, source_id)).fetchone()
    return _note(row) if row else None


def set_note_source(user_id: str, note_id: str, source: str, source_id: str, sha: str) -> None:
    with connect() as c:
        c.execute("UPDATE notes SET source=?, source_id=?, source_sha=?, imported_at=? WHERE id=? AND user_id=?",
                  (source, source_id, sha, _now(), note_id, user_id))


def update_note_from_source(user_id: str, note_id: str, title: str, content: str, sha: str) -> None:
    """源侧改了 → 更新正文（调用方已经确认本地没改过）。updated_at 也刷新。"""
    with connect() as c:
        c.execute("UPDATE notes SET title=?, content=?, source_sha=?, imported_at=?, updated_at=? WHERE id=? AND user_id=?",
                  (title, content, sha, _now(), _now(), note_id, user_id))
    sync_citations(user_id, note_id, content)   # 改正文的入口都要重建引用（第 284 轮：这条路漏了）


def create_note(user_id: str, title: str, content: str,
                parent_id: str = ROOT_ID, *, source: str = "") -> dict:
    """建一篇笔记，**同时把它挂到树上**。

    照 Trilium：笔记总是创建在某个父节点下面，没有「建完再决定放哪」这个
    中间态。不挂的话它就不在树上的任何位置——存在于库里但用户看不见，
    那不是一篇笔记，是一条垃圾数据。
    """
    note = {"id": uuid.uuid4().hex[:12], "user_id": user_id, "title": title,
            "content": content, "pinned": 0, "source": source,
            "created_at": _now(), "updated_at": _now()}
    with connect() as c:
        c.execute(
            "INSERT INTO notes (id,user_id,title,content,pinned,source,created_at,updated_at) "
            "VALUES (:id,:user_id,:title,:content,:pinned,:source,:created_at,:updated_at)", note)
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
                     content: str, reason: str, *, force: bool,
                     run_id: str = "", round_no: int = 0) -> str:
    """在已开的连接里存一版。不强制时受间隔限制；空正文不存。

    返回这一版的 id，没存返回空串。**原来返回的是 bool**——计划 9.1 要拿这个
    id 当指针（`harness_edits.revision_id`），而「存没存下」和「存下来的是哪
    一行」是同一个问题的两半，让调用方回头再查一次就是在制造第二个真相。
    """
    if not (content or "").strip():
        return ""
    if not force:
        last = c.execute(
            "SELECT created_at FROM note_revisions WHERE user_id=? AND note_id=?"
            " ORDER BY created_at DESC, rowid DESC LIMIT 1", (user_id, note_id)).fetchone()
        if last:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])).total_seconds()
            if age < REVISION_INTERVAL_S:
                return ""
    rev_id = uuid.uuid4().hex[:12]
    c.execute("INSERT INTO note_revisions (id,user_id,note_id,title,content,reason,run_id,round_no,created_at)"
              " VALUES (?,?,?,?,?,?,?,?,?)",
              (rev_id, user_id, note_id, title, content, reason, run_id, int(round_no or 0), _now()))
    c.execute("DELETE FROM note_revisions WHERE user_id=? AND note_id=? AND id NOT IN ("
              "SELECT id FROM note_revisions WHERE user_id=? AND note_id=?"
              " ORDER BY created_at DESC, rowid DESC LIMIT ?)",
              (user_id, note_id, user_id, note_id, REVISION_KEEP))
    return rev_id


# 这次保存是谁按下的。计划 9.1 的整份信号（「用户拿到 AI 写的东西之后改了
# 什么」）就靠这一个字段分辨「人按的」和「harness 自己写回去的」——**一份被
# harness 自己的写回污染的 ground truth 比没有更糟**。
#
# 默认是 `user`，理由是「保存一篇笔记」这件事在这个产品里默认就是人按的；
# 代价是**新加一处机器写入而忘了声明，会被当成一次用户编辑**。所以这不是
# 靠自觉：`app/` 下每一处 `store.update_note(` 在
# `tests/test_harness_edits.py` 里**逐处登记**（同批 21 那条「载荷不是字典
# 字面量的发射点逐处登记」），新增一处不登记，闸就红。
EDIT_SOURCES = ("user", "harness", "import")


def update_note(user_id: str, note_id: str, title: str, content: str,
                *, source: str = "user") -> dict | None:
    """保存正文。`source` 见 `EDIT_SOURCES`。

    **`source` 只影响采集，不影响写**：任何取值下正文都照写、版本照留。
    """
    if source not in EDIT_SOURCES:
        raise ValueError(f"update_note 的 source 得是 {EDIT_SOURCES} 之一，收到 {source!r}")
    with connect() as c:
        old = c.execute("SELECT title, content FROM notes WHERE user_id=? AND id=?",
                        (user_id, note_id)).fetchone()
        if not old:
            return None
        # 正文变了才留版本；只改标题不算
        if old["content"] != content:
            _snapshot_locked(c, user_id, note_id, old["title"], old["content"], "auto", force=False)
            if source == "user":
                # 用户真的改了正文并保存 —— 这正是计划 9.1 要采的那一下。
                # 在同一个连接、同一个事务里关，`notes` 和 `harness_edits`
                # 不会各存一半。
                _close_harness_edit_locked(c, user_id, note_id, content)
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


def snapshot_note(user_id: str, note_id: str, reason: str = "manual",
                  *, run_id: str = "", round_no: int = 0) -> dict | None:
    """手动存一版（不受间隔限制）。返回这一版的摘要，没这篇 / 正文为空返回 None。"""
    with connect() as c:
        row = c.execute("SELECT title, content FROM notes WHERE user_id=? AND id=?",
                        (user_id, note_id)).fetchone()
        if not row:
            return None
        if not _snapshot_locked(c, user_id, note_id, row["title"], row["content"],
                                reason, force=True, run_id=run_id, round_no=round_no):
            return None
    return list_revisions(user_id, note_id)[0]


def find_run_revision(user_id: str, note_id: str, run_id: str, reason: str) -> str:
    """这次跑已经存过这个 `reason` 的一版没有：有回版本 id，没有回空串（P18 #2）。

    `Edits.after_run`（跑完的 `harness` 行）和 `round_snapshot` 的收尾行说的是同一份正文；
    收尾那边先问一句，有了就不再存第二行。"""
    if not run_id:
        return ""
    with connect() as c:
        row = c.execute("SELECT id FROM note_revisions WHERE user_id=? AND note_id=? AND run_id=? AND reason=?"
                        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (user_id, note_id, run_id, reason)).fetchone()
    return str(row["id"]) if row else ""


# ------------------------------------------------- 用户的编辑（计划 9.1）
#
# **只采集，不调参。** 这几个函数往库里写的是「AI 交了什么 / 用户留下了
# 多少」，一行也不进任何 prompt、不喂任何策略。样本不够时按它调参比不调更糟
# ——判据依赖当初看到的那批产出（[IND] §8③ 的 criteria drift），而这份数据
# 现在的规模是零。

REVISION_REASON_HARNESS = "harness"
"""跑完落的那一版正文的 `reason`。用户在历史面板里看得见它，这是有意的：
「恢复到 AI 跑完那一版」本来就是这个产品该有的一步。
P18 #2 起它也带 `round_no`（= 最后一轮）：它就是最后一轮的「之后」，`round_snapshot` 不再另存一行
`run_end`（P16 那阵子同一份正文存了两行）。"""

REVISION_REASON_ROUND = "round"
"""智能续写 / 打磨**每一轮开始前**的正文（P16，agent-native-editor §3.2「历史版本保留每次烧之前的快照」）。
`run_id` 指回这次跑、`round_no` 是轮次。烧进正文之后，「回到第 N 轮之前」= 恢复这一版；
「只撤第 N 轮」= 拿这一版和它后面那一版做 diff 反向应用（前端 `editor/undoRound`）。"""

REVISION_REASON_RUN_END = "run_end"
"""这次跑收尾时的正文，`round_no` = 最后一轮。它是最后一轮的「之后」——
没有它，最后一轮只有「之前」，「只撤最后一轮」就没有另一端可比。
**P18 #2 起只在 `Edits` 没落 `harness` 行的跑上写**（暂停等用户处置、没进 `harness_runs` 的跑）；
正常跑完的跑收尾行就是 `harness`。老数据里两行都有的（P16–P17 那几天）前端两种都认。"""


def snapshot_content(user_id: str, note_id: str, title: str, content: str, reason: str,
                     *, run_id: str = "", round_no: int = 0) -> str:
    """把**给定的**正文强制存一版（不读 `notes` 表）。返回版本 id，空正文 / 存不下回空串。

    `snapshot_note` 存的是库里此刻的正文；harness 跑到第 N 轮开头时库里那份是上一轮落盘的、
    可能还被修订 pass 改过一截，**真正「烧之前」的是 loop 手里的 `st.content`**，所以要能直接给正文。
    """
    with connect() as c:
        return _snapshot_locked(c, user_id, note_id, title, content, reason, force=True,
                                run_id=run_id, round_no=round_no)


def open_harness_edit(user_id: str, note_id: str, *, run_id: str, key: str,
                      revision_id: str, base_chars: int, ai_chars: int) -> str:
    """跑完开一行。同一篇上还开着的旧行记 `superseded`。

    **同一篇只留一行开着**：用户下一次保存能回答的只有「相对最近那一次跑
    改了什么」。两行同时开着的话，那一次保存会被两次跑同时认领，而其中
    至少一个是错的。
    """
    row_id = uuid.uuid4().hex[:12]
    with connect() as c:
        c.execute("UPDATE harness_edits SET status='superseded', edited_at=?"
                  " WHERE user_id=? AND note_id=? AND status='open'",
                  (_now(), user_id, note_id))
        c.execute(
            "INSERT INTO harness_edits (id,user_id,note_id,run_id,key,revision_id,"
            "status,base_chars,ai_chars,user_chars,kept_chars,created_at,edited_at) "
            "VALUES (?,?,?,?,?,?,'open',?,?,0,0,?,'')",
            (row_id, user_id, note_id, run_id, key, revision_id,
             int(base_chars), int(ai_chars), _now()))
        c.commit()
    return row_id


def _close_harness_edit_locked(c: sqlite3.Connection, user_id: str, note_id: str,
                               content: str) -> None:
    """用户改完存了一次：把还开着的那一行关掉，记下他留下了多少。

    **只记数，不存第二份正文**（跟账本那条「只存 id + 一行」同一条边界）：
    AI 那一侧原样躺在 `note_revisions` 里、`revision_id` 指得到，用户那一侧
    就是 `notes.content` 本身。这里落的是两份对齐之后**逐字仍然一样的字数**，
    因为那是唯一一个下一次读它的人不用重新跑一遍 diff 就能用的数。

    **已知口径**：`kept_chars` 对的是整篇，而整篇里有一大半是这次跑开跑前就
    有的（`base_chars` 一起记着就是为了这个）。「用户删掉的是这次跑写的哪几
    段」要按段落对齐才答得出来——那是 9.2 的事，靠 `revision_id` 回头重算，
    不是现在多存一份正文。
    """
    row = c.execute("SELECT id, revision_id FROM harness_edits"
                    " WHERE user_id=? AND note_id=? AND status='open'"
                    " ORDER BY created_at DESC, rowid DESC LIMIT 1",
                    (user_id, note_id)).fetchone()
    if not row:
        return
    rev = c.execute("SELECT content FROM note_revisions WHERE id=? AND user_id=?",
                    (row["revision_id"], user_id)).fetchone()
    if not rev:
        # AI 那一版被历史修剪掉了（REVISION_KEEP）。**这一行就作废**——
        # 没有它就没有「AI 提出了什么」，剩下的数只是一次保存。
        c.execute("UPDATE harness_edits SET status='lost', edited_at=? WHERE id=?",
                  (_now(), row["id"]))
        return
    ai = rev["content"] or ""
    if ai == content:
        return          # 一个字没改（自动保存也会走到这儿）：这一行继续开着
    c.execute("UPDATE harness_edits SET status='edited', user_chars=?, kept_chars=?,"
              " edited_at=? WHERE id=?",
              (len(content), kept_chars(ai, content), _now(), row["id"]))


def kept_chars(before: str, after: str) -> int:
    """两份正文逐字对齐之后，仍然一样的字数。

    `difflib.SequenceMatcher` 的匹配块之和。**autojunk 关掉**：默认那条启发式
    会把出现频率高的字符当噪声跳过，而中文正文里高频字满篇都是——实拍 680 字
    的正文改掉 1 个字，开着它只认出 100 字「留下了」，关掉是 595。

    **这个数是下界，不是编辑距离。** `SequenceMatcher` 是贪心的，在高度重复
    的文本上给不出最优对齐（上面那个例子最优是 679）。要精确的对齐得回头拿
    `revision_id` 指的那一版重算——这也正是不在这儿多存一份正文的底气。
    """
    import difflib

    sm = difflib.SequenceMatcher(None, before or "", after or "", autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks())


def harness_edits(user_id: str = "", limit: int = 200) -> list[dict]:
    """采到的样本。**没有写回路**——这张表现在只有读者，没有任何一处拿它调参。"""
    with connect() as c:
        if user_id:
            rows = c.execute("SELECT * FROM harness_edits WHERE user_id=?"
                             " ORDER BY created_at DESC, rowid DESC LIMIT ?",
                             (user_id, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM harness_edits"
                             " ORDER BY created_at DESC, rowid DESC LIMIT ?",
                             (limit,)).fetchall()
    return [dict(r) for r in rows]


def list_revisions(user_id: str, note_id: str) -> list[dict]:
    """新的在前。不带正文——列表只要知道什么时候、多少字。"""
    with connect() as c:
        rows = c.execute(
            "SELECT id, note_id, title, reason, run_id, round_no, created_at, content"
            # 同一秒内可能存两版（恢复前的强制快照紧跟手动版），rowid 兜底定序
            " FROM note_revisions WHERE user_id=? AND note_id=? ORDER BY created_at DESC, rowid DESC",
            (user_id, note_id)).fetchall()
    # 「N 字」跟状态栏同一条规则（util/wordcount），不再是 length(content)——同一篇两个数（第 547 轮）
    out = []
    for r in rows:
        d = dict(r)
        d["chars"] = word_count(d.pop("content") or "")
        out.append(d)
    return out


def get_revision(user_id: str, note_id: str, rev_id: str) -> dict | None:
    with connect() as c:
        row = c.execute(
            "SELECT id, note_id, title, content, reason, run_id, round_no, created_at FROM note_revisions"
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
        # **恢复到旧版本也是一次用户编辑**（计划 9.1），而且是最重的一种：
        # 他把现在这一版整个扔了。恢复到 AI 那一版本身不算——那时正文跟
        # `revision_id` 指的那一份逐字相同，`_close_harness_edit_locked`
        # 自己会认出来并让这一行继续开着。
        _close_harness_edit_locked(c, user_id, note_id, rev["content"] or "")
    sync_citations(user_id, note_id, rev["content"])
    return get_note(user_id, note_id)


# 骨架会整份进每一轮的 prompt、并显示在右栏。模型抽风返回几千字的 spine 时，
# 既撑爆面板也白烧 token（第 576 轮）。
#
# **P7 改法（P4 #1）**：原来 `BEAT_MAX = 60`、按字数硬切，而 `POST /skeleton` 返回前不切——用户生成时
# 看到整句、重开笔记看到「…之间的断点，并将问」（真库 4 篇已是）。现在：
#   · 上限提到 200，高于实测分布（本轮 57–185、历史 28–185），生成侧先要求模型 ≤120 字
#     （`checks/skeleton.BEAT_TARGET_CHARS`）；
#   · 兜底**按句 / 顿号收**（`trim_to_boundary`），不按字数硬切；
#   · 落库（`set_skeleton`）**不再静默截断**：超上限就报错，让调用方（route → 400）看见。
SPINE_MAX = 200
BEAT_MAX = 200
_BOUNDARY = "。；;！？!?，,、"


def trim_to_boundary(text: str, limit: int) -> str:
    """超过 `limit` 时退到上限之前最后一个句读（句号 / 分号 / 逗号 / 顿号）处收尾；上限的前一半
    里都没有句读才按字数切并补「…」。不超过上限原样返回。"""
    s = " ".join((text or "").split())
    if len(s) <= limit:
        return s
    head = s[:limit]
    cut = max(head.rfind(ch) for ch in _BOUNDARY)
    if cut >= limit // 2:
        return head[:cut].rstrip("，,、；;") + "。" if head[cut] not in "。！？!?" else head[:cut + 1]
    return head[:limit - 1].rstrip() + "…"


def clamp_skeleton(spine: str, beats: list[str]) -> tuple[str, list[str]]:
    """骨架封顶——**生成侧**过一遍（`routers/compose.skeleton`、`hooks/note.skeleton`）。"""
    s = trim_to_boundary(spine, SPINE_MAX)
    bs = [trim_to_boundary(str(b), BEAT_MAX) for b in (beats or [])]
    return s, [b for b in bs if b]


def set_skeleton(user_id: str, note_id: str, spine: str, beats: list[str]) -> None:
    """写作骨架跟着笔记存。**只在真的有内容时写**——空骨架不该覆盖已有的：
    前端切笔记时会把内存里的 spine/beats 清空，那个"空"不代表用户想删掉它。

    **不截断**（P7）：生成侧已经按上限收过；这里再碰到超长的就是调用方绕过了生成侧，
    抛 ValueError 让它看见，别悄悄存成半句。"""
    spine = " ".join((spine or "").split())
    beats = [" ".join(str(b).split()) for b in (beats or [])]
    beats = [b for b in beats if b]
    if len(spine) > SPINE_MAX:
        raise ValueError(f"骨架的核心张力太长（{len(spine)} 字，上限 {SPINE_MAX}）")
    for i, b in enumerate(beats, 1):
        if len(b) > BEAT_MAX:
            raise ValueError(f"骨架第 {i} 条节拍太长（{len(b)} 字，上限 {BEAT_MAX}）")
    with connect() as c:
        c.execute("UPDATE notes SET spine=?, beats=? WHERE user_id=? AND id=?",
                  (spine, json.dumps(beats, ensure_ascii=False), user_id, note_id))


def set_pinned(user_id: str, note_id: str, pinned: bool) -> dict | None:
    with connect() as c:
        cur = c.execute(
            "UPDATE notes SET pinned=? WHERE user_id=? AND id=?",
            (1 if pinned else 0, user_id, note_id))
        if cur.rowcount == 0:
            return None
    return get_note(user_id, note_id)


def set_intent(user_id: str, note_id: str, intent: dict) -> dict | None:
    """存文档意图（P9）。三个字段各自收成一行、封顶；`source` 记的是这份是预填的还是用户改过的。"""
    d = intent_mod.normalize(intent)
    with connect() as c:
        cur = c.execute("UPDATE notes SET intent=? WHERE user_id=? AND id=?",
                        (json.dumps(d, ensure_ascii=False), user_id, note_id))
        if cur.rowcount == 0:
            return None
    return get_note(user_id, note_id)


# ---------------------------------------------------------------- 材料托盘（P14）

TRAY_KINDS = ("note", "fact", "import", "selection")
TRAY_MAX_ITEMS = 24          # 托盘是「摊在桌上的这几篇」，不是第二个知识库
TRAY_EXCERPT_MAX = 600       # 每条进 prompt 的那段；笔记开头几百字 / 事实原话都够
TRAY_TITLE_MAX = 120
TRAY_REF_MAX = 512           # 网页剪藏的 ref_id 是网址（P15 #3）


def _tray_row(row) -> dict:
    d = dict(row)
    return {"id": d["id"], "kind": d["kind"], "ref_id": d.get("ref_id") or "", "title": d.get("title") or "",
            "excerpt": d.get("excerpt") or "", "position": int(d.get("position") or 0), "added_at": d.get("added_at") or ""}


def normalize_tray_item(item: dict) -> dict | None:
    """一条托盘项收成能落库的形状；不成立的（kind 不认识、note / fact 没有 ref_id、什么都没有）回 None。

    **落库前先问「每个取值都写得进去吗」**（框架 §21）：四种 kind 各有一条测试真写真读。
    """
    kind = str((item or {}).get("kind") or "").strip()
    if kind not in TRAY_KINDS:
        return None
    # ref_id 放得下一条 URL（P15 #3 网页剪藏：import 项的 ref_id 是网址，「打开原文」要靠它）；笔记 / 事实 id 远短于此
    ref_id = str(item.get("ref_id") or "").strip()[:TRAY_REF_MAX]
    title = str(item.get("title") or "").strip()[:TRAY_TITLE_MAX]
    excerpt = str(item.get("excerpt") or "").strip()[:TRAY_EXCERPT_MAX]
    if kind in ("note", "fact") and not ref_id:
        return None                     # 指不到东西的笔记 / 事实没法「点开看原文」，也没法引用
    if kind in ("import", "selection") and not excerpt:
        return None                     # 摘录 / 导入段落的内容就是它本身
    iid = str(item.get("id") or "").strip()[:32] or uuid.uuid4().hex[:12]
    return {"id": iid, "kind": kind, "ref_id": ref_id, "title": title, "excerpt": excerpt}


def list_tray(user_id: str, note_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM note_tray WHERE user_id=? AND note_id=? ORDER BY position, added_at",
                         (user_id, note_id)).fetchall()
    return [_tray_row(r) for r in rows]


def replace_tray(user_id: str, note_id: str, items: list[dict]) -> list[dict]:
    """整份换掉（顺序 = 数组顺序）。同一个 ref 放两次只留一次；封顶 `TRAY_MAX_ITEMS`。
    保留原来的 `added_at`（同 id 的）——重排不该把「什么时候放进来的」抹掉。"""
    now = _now()
    seen: set[tuple[str, str, str]] = set()
    kept: list[dict] = []
    for raw in items or ():
        d = normalize_tray_item(raw)
        if not d:
            continue
        key = (d["kind"], d["ref_id"], d["excerpt"] if d["kind"] in ("import", "selection") else "")
        if key in seen:
            continue
        seen.add(key)
        kept.append(d)
        if len(kept) >= TRAY_MAX_ITEMS:
            break
    with connect() as c:
        old = {r["id"]: r["added_at"] for r in c.execute(
            "SELECT id, added_at FROM note_tray WHERE user_id=? AND note_id=?", (user_id, note_id))}
        c.execute("DELETE FROM note_tray WHERE user_id=? AND note_id=?", (user_id, note_id))
        for pos, d in enumerate(kept):
            c.execute("INSERT INTO note_tray (id,user_id,note_id,kind,ref_id,title,excerpt,position,added_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?)",
                      (d["id"], user_id, note_id, d["kind"], d["ref_id"], d["title"], d["excerpt"], pos,
                       old.get(d["id"]) or now))
        c.commit()
    return list_tray(user_id, note_id)


def delete_tray_item(user_id: str, note_id: str, item_id: str) -> bool:
    with connect() as c:
        cur = c.execute("DELETE FROM note_tray WHERE user_id=? AND note_id=? AND id=?", (user_id, note_id, item_id))
        c.commit()
    return cur.rowcount > 0


def set_icon(user_id: str, note_id: str, icon: str) -> dict | None:
    """给笔记设图标（boxicons 类名）。空串 = 清掉，回到默认。"""
    with connect() as c:
        cur = c.execute("UPDATE notes SET icon=? WHERE user_id=? AND id=?", (icon, user_id, note_id))
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
            # 删之前存一份快照进「最近删除」：笔记行 + 它的 branches + 历史版本。5 秒撤销窗口过了
            # 之后还能找回来（Trilium 的删除也是可撤销的）。
            note_row = c.execute("SELECT * FROM notes WHERE id=? AND user_id=?", (nid, user_id)).fetchone()
            # 没写过一个字、也没起名的空笔记（新建后没动就走了，前端自动扔掉的那种）不进「最近删除」：
            # 没什么可恢复的，只会攒出一排「未命名 · 0 字」（第 209 轮实拍）
            if note_row is not None and not (note_row["content"] or "").strip() \
                    and (note_row["title"] or "").strip() in ("", "未命名", "Untitled", "note"):
                note_row = None
            if note_row is not None:
                nd = dict(note_row)
                payload = {
                    "note": nd,
                    "branches": [dict(r) for r in c.execute(
                        "SELECT * FROM branches WHERE note_id=? AND user_id=?", (nid, user_id))],
                    "revisions": [dict(r) for r in c.execute(
                        "SELECT * FROM note_revisions WHERE user_id=? AND note_id=? ORDER BY created_at DESC LIMIT 20",
                        (user_id, nid))],
                }
                c.execute("INSERT OR REPLACE INTO note_trash (user_id,note_id,title,chars,payload,deleted_at) VALUES (?,?,?,?,?,?)",
                          (user_id, nid, nd.get("title") or "", word_count(nd.get("content") or ""),
                           json.dumps(payload, ensure_ascii=False), _now()))
            c.execute("DELETE FROM branches WHERE note_id=? AND user_id=?",
                      (nid, user_id))
            c.execute("DELETE FROM notes WHERE id=? AND user_id=?", (nid, user_id))
            # 挂在这篇上的东西一起走：引用、历史版本、暂停快照、运行记录。
            # 留着就是一堆指向不存在笔记的孤儿行，越攒越多。
            c.execute("DELETE FROM note_citations WHERE user_id=? AND note_id=?", (user_id, nid))
            c.execute("DELETE FROM note_revisions WHERE user_id=? AND note_id=?", (user_id, nid))
            c.execute("DELETE FROM harness_snapshots WHERE user_id=? AND note_id=?", (user_id, nid))
            # key 是 `<模式>:<id>`，不止 note: 一种（section: / prompt: / table:），老行还有裸 id
            c.execute("DELETE FROM harness_runs WHERE key=? OR key LIKE ?", (nid, f"%:{nid}"))
            # 采集来的编辑样本也一起走：它的两个指针（`note_revisions` 里那一版
            # 正文、`notes.content`）都刚被删掉，留着就是一行指向空气的数。
            c.execute("DELETE FROM harness_edits WHERE user_id=? AND note_id=?", (user_id, nid))
            # 托盘是这篇的（P14）：笔记没了，摊在它桌上的材料也一起收
            c.execute("DELETE FROM note_tray WHERE user_id=? AND note_id=?", (user_id, nid))
            removed.append(nid)

        drop(note_id)
        # 挂在被删子树上的写作计划一起作废：不然它永远 active、指着一个不存在的父节点
        # （dev 库里攒了 15 个这样的孤儿计划，第 172 轮实拍）
        if removed:
            q = ",".join("?" * len(removed))
            c.execute(f"UPDATE writing_plans SET status='abandoned' WHERE user_id=? AND status='active' AND parent_note_id IN ({q})",
                      [user_id, *removed])
        c.commit()
    return removed
def record_llm_usage(user_id: str, feature: str, model: str, prompt_tokens: int,
                     completion_tokens: int, ms: int, cached_tokens: int = 0,
                     cache_write_tokens: int = 0) -> None:
    with connect() as c:
        c.execute("INSERT INTO llm_usage (user_id,feature,model,prompt_tokens,completion_tokens,"
                  "ms,cached_tokens,cache_write_tokens,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                  (user_id, feature[:60], model[:80], int(prompt_tokens or 0),
                   int(completion_tokens or 0), int(ms or 0),
                   int(cached_tokens or 0), int(cache_write_tokens or 0), _now()))


EXTRACT_PROMPT_FIXED_TOKENS = 1200      # KITE 抽取 prompt 的固定开销（规则 + 词表）
EXTRACT_TOKENS_PER_FACT = 60            # 每条事实的 JSON 输出


def record_extract_estimate(user_id: str, chars: int, facts: int, ms: int) -> None:
    """KITE 抽取走它自己的 provider，拿不到 usage：按字数估一笔（中文约 1.5 字 / token），
    功能名带 `~` 表示估算，设置页单独标出来。"""
    try:
        model = get_active_llm_config().get("model", "")
    except Exception:      # noqa: BLE001
        model = ""
    record_llm_usage(user_id, "kb/extract~", model,
                     EXTRACT_PROMPT_FIXED_TOKENS + int(chars / 1.5), EXTRACT_TOKENS_PER_FACT * max(0, int(facts)), ms)


def usage_summary(user_id: str) -> dict:
    """24 小时 / 7 天 / 30 天 / 全部（都是滚动窗口；键名 today 留着不改）：调用次数、token；再按功能列前几个（30 天内）。"""
    now = datetime.now(timezone.utc)
    out: dict = {}
    with connect() as c:
        for key, days in (("today", 1), ("week", 7), ("month", 30), ("all", None)):
            if days is None:
                row = c.execute("SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0), COALESCE(SUM(ms),0)"
                                " FROM llm_usage WHERE user_id=?", (user_id,)).fetchone()
            else:
                since = (now - timedelta(days=days)).isoformat(timespec="seconds")
                row = c.execute("SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0), COALESCE(SUM(ms),0)"
                                " FROM llm_usage WHERE user_id=? AND created_at>=?", (user_id, since)).fetchone()
            out[key] = {"calls": row[0], "prompt_tokens": row[1], "completion_tokens": row[2], "ms": row[3]}
        since = (now - timedelta(days=30)).isoformat(timespec="seconds")
        rows = c.execute("SELECT feature, COUNT(*), COALESCE(SUM(prompt_tokens+completion_tokens),0)"
                         " FROM llm_usage WHERE user_id=? AND created_at>=? GROUP BY feature ORDER BY 3 DESC LIMIT 8",
                         (user_id, since)).fetchall()
        out["by_feature"] = [{"feature": r[0], "calls": r[1], "tokens": r[2]} for r in rows]
        out["models"] = [r[0] for r in c.execute("SELECT DISTINCT model FROM llm_usage WHERE user_id=? AND created_at>=?", (user_id, since)).fetchall()]
    return out


TRASH_KEEP_DAYS = 30


def prune_trash(user_id: str, days: int = TRASH_KEEP_DAYS) -> int:
    cutoff = (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days)).isoformat(timespec="seconds")
    with connect() as c:
        return c.execute("DELETE FROM note_trash WHERE user_id=? AND deleted_at < ?", (user_id, cutoff)).rowcount


def list_trash(user_id: str) -> list[dict]:
    """最近删除的笔记（新删的在前）。顺手把超过保留期的清掉。"""
    prune_trash(user_id)
    with connect() as c:
        rows = c.execute("SELECT note_id, title, chars, deleted_at FROM note_trash WHERE user_id=? ORDER BY deleted_at DESC",
                         (user_id,)).fetchall()
    return [dict(r) for r in rows]


def restore_from_trash(user_id: str, note_id: str) -> dict | None:
    """把一篇从「最近删除」放回去：笔记行原样、branches 原位、历史版本一起回来。
    父节点也在「最近删除」里（整棵子树一起删的）就先把父链恢复回来，笔记落回原位；
    父节点真没了才挂到树根。id 不变，所以别的笔记里的 [[链接]] 和知识库反链都还认得它。"""
    with connect() as c:
        if not _restore_one(c, user_id, note_id, set()):
            return None
        c.commit()
    return get_note(user_id, note_id)


def _restore_one(c, user_id: str, note_id: str, seen: set[str]) -> bool:
    """在同一个连接里恢复一篇（递归先恢复还在回收站里的父节点）。返回是否找到了快照。"""
    if note_id in seen:
        return False
    seen.add(note_id)
    row = c.execute("SELECT payload FROM note_trash WHERE user_id=? AND note_id=?", (user_id, note_id)).fetchone()
    if row is None:
        return False
    payload = json.loads(row["payload"])
    nd = payload["note"]
    if c.execute("SELECT 1 FROM notes WHERE id=?", (note_id,)).fetchone():
        c.execute("DELETE FROM note_trash WHERE user_id=? AND note_id=?", (user_id, note_id))
        return True          # 已经在了（撤销窗口里恢复过）：只清掉快照
    cols = [k for k in nd.keys()]
    c.execute(f"INSERT INTO notes ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [nd[k] for k in cols])
    branches = payload.get("branches") or []
    if not branches:
        branches = [{"note_id": note_id, "parent_note_id": ROOT_ID, "user_id": user_id}]
    for b in branches:
        parent = b.get("parent_note_id") or ROOT_ID
        if parent != ROOT_ID and not c.execute("SELECT 1 FROM notes WHERE id=?", (parent,)).fetchone():
            # 父节点跟它一起被删的：先把父链放回来（一路递归到还在的祖先），这篇才能落回原位
            if not _restore_one(c, user_id, parent, seen):
                parent = ROOT_ID
        if c.execute("SELECT 1 FROM branches WHERE note_id=? AND parent_note_id=?", (note_id, parent)).fetchone():
            continue
        bcols = [k for k in b.keys() if k != "parent_note_id"]
        vals = [b[k] for k in bcols]
        c.execute(f"INSERT INTO branches ({','.join(bcols)},parent_note_id) VALUES ({','.join('?' * len(bcols))},?)", [*vals, parent])
    for r in payload.get("revisions") or []:
        rcols = list(r.keys())
        c.execute(f"INSERT OR IGNORE INTO note_revisions ({','.join(rcols)}) VALUES ({','.join('?' * len(rcols))})", [r[k] for k in rcols])
    c.execute("DELETE FROM note_trash WHERE user_id=? AND note_id=?", (user_id, note_id))
    return True


def purge_trash(user_id: str, note_id: str) -> bool:
    with connect() as c:
        return c.execute("DELETE FROM note_trash WHERE user_id=? AND note_id=?", (user_id, note_id)).rowcount > 0


_WEEKDAYS = "周一 周二 周三 周四 周五 周六 周日".split()


def _child_titled(c, user_id: str, parent_id: str, title: str) -> str | None:
    row = c.execute("SELECT n.id FROM notes n JOIN branches b ON b.note_id=n.id"
                    " WHERE b.user_id=? AND b.parent_note_id=? AND n.title=? ORDER BY b.position LIMIT 1",
                    (user_id, parent_id, title)).fetchone()
    return row[0] if row else None


def journal_node(user_id: str, day, depth: int = 4) -> str:
    """日记树上某一层的 id：`日记 / 2026 / 09 月 / 09-13 周六`，没有就一路建出来。

    `depth` 决定走到哪一层（2=年、3=月、4=当天）。分出这个函数是因为**不是只有
    「今天的日记」要挂在这棵树上**：一天的屏幕活动回顾挂当天那一页下面，跨几天
    的回顾挂那个月下面——它们要是都落在树根上，用几周之后树根全是这种东西。

    按标题找，所以用户把「日记」改名之后会另起一棵，这跟 Trilium 用 #calendarRoot
    标签找根不同，是有意为之：没有属性系统就用最朴素的办法。
    """
    # 每层带一个默认图标（Trilium 的日记根 / 年 / 月 / 日也各有图标）
    chain = [("日记", "", "bx-calendar"), (f"{day.year}", "", "bx-folder"),
             (f"{day.month:02d} 月", "", "bx-folder"),
             (f"{day.month:02d}-{day.day:02d} {_WEEKDAYS[day.weekday()]}",
              f"# {day.month} 月 {day.day} 日 {_WEEKDAYS[day.weekday()]}\n\n", "bx-calendar-event")]
    parent = ROOT_ID
    note_id = ROOT_ID
    for title, content, icon in chain[:max(1, depth)]:
        with connect() as c:
            note_id = _child_titled(c, user_id, parent, title)
        if note_id is None:
            note_id = create_note(user_id, title, content, parent)["id"]
            set_icon(user_id, note_id, icon)
        parent = note_id
    return note_id


def today_note(user_id: str, today) -> dict:
    """今天的日记——同一天点多少次都是同一篇。"""
    return get_note(user_id, journal_node(user_id, today, depth=4))


def upsert_child(user_id: str, parent_id: str, title: str, content: str,
                 *, source: str = "", icon: str = "") -> dict:
    """父节点下这个标题的笔记：有就改写正文，没有就建。

    给「反复生成同一份东西」的路径用（屏幕活动的回顾就是——重写一次就该覆盖
    上一份，而不是在树上留一串同名笔记）。
    """
    with connect() as c:
        nid = _child_titled(c, user_id, parent_id, title)
    if nid:
        # 程序反复重写同一篇（屏幕活动回顾那种），不是用户编辑
        update_note(user_id, nid, title=title, content=content, source="harness")
        return get_note(user_id, nid)
    note = create_note(user_id, title, content, parent_id, source=source)
    if icon:
        set_icon(user_id, note["id"], icon)
    return get_note(user_id, note["id"])


# 这几种子笔记是**从父笔记派生出来的**，不是「同一批内容里的另一篇」：
# 幻灯片是这篇的另一种形态，屏幕活动回顾是那一天的汇总。
# 拿它们当参考上下文喂回去是**循环**——模型读到的是自己刚写过的话的浓缩版，
# 只会把重复写得更重（而 `non_repetition` 本来就是最难达标的那一维，
# 第 647 轮真跑连续四轮判 0）。
DERIVED_SOURCES = ("slides", "journey")


def child_notes(user_id: str, parent_id: str, exclude_id: str = "",
                limit: int = 5) -> list[dict]:
    """某个节点下面的直接子笔记。无限续写拿它当「同一批内容」的参考上下文。

    走 branches 而不是 notes.folder_id：**克隆之后一篇笔记可以同时属于好几个
    父节点**，folder_id 那个单值字段表达不了。

    **派生出来的那几种不算**（见 `DERIVED_SOURCES`）：它们是父笔记的产物，
    不是它的同伴。
    """
    holes = ",".join("?" * len(DERIVED_SOURCES))
    with connect() as c:
        rows = c.execute(
            "SELECT n.* FROM notes n JOIN branches b ON b.note_id = n.id"
            f" WHERE b.user_id=? AND b.parent_note_id=? AND n.id != ?"
            f" AND COALESCE(n.source,'') NOT IN ({holes})"
            " ORDER BY n.updated_at DESC LIMIT ?",
            (user_id, parent_id, exclude_id, *DERIVED_SOURCES, limit)).fetchall()
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


def reindex_citations() -> int:
    """启动时按正文重建每篇的引用表，返回修正了几篇。dev 库实拍两篇正文里一条引用都没有、
    表里却各挂着三条（历史上某条写正文的路没重建），树上就一直显示 ◆6（第 284 轮）。"""
    fixed = 0
    with connect() as c:
        rows = c.execute("SELECT id, user_id, content FROM notes").fetchall()
        for r in rows:
            want = set(cited_fact_ids(r["content"] or ""))
            have = {x["fact_id"] for x in c.execute("SELECT fact_id FROM note_citations WHERE note_id=? AND user_id=?", (r["id"], r["user_id"]))}
            if want != have:
                c.execute("DELETE FROM note_citations WHERE note_id=? AND user_id=?", (r["id"], r["user_id"]))
                c.executemany("INSERT OR IGNORE INTO note_citations (note_id, fact_id, user_id) VALUES (?,?,?)",
                              [(r["id"], f, r["user_id"]) for f in want])
                fixed += 1
        c.commit()
    return fixed


def notes_citing(user_id: str, fact_id: str) -> list[dict]:
    """哪些笔记引用了这条事实。**反查——融合的关键。**

    回答的是「这条事实还活着吗、改了它会影响谁」。没有它，知识库就是个只进
    不出的仓库。对标 Trilium 右栏的 Backlinks。
    """
    with connect() as c:
        rows = c.execute(
            "SELECT n.id, n.title, n.updated_at, n.icon, substr(n.content,1,80) AS preview FROM note_citations k"
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
            "SELECT id, title, updated_at, icon, substr(content,1,80) AS preview FROM notes"
            " WHERE user_id=? AND id<>? AND content LIKE ? ORDER BY updated_at DESC",
            (user_id, note_id, f"%](note://{note_id})%")).fetchall()
    return [dict(r) for r in rows]


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
        # 克隆到自己的子树里同样成环（move 早就拒了，attach 没拒——第 245 轮实测 200）
        if note_id == parent_id or _would_cycle(c, note_id, parent_id):
            raise ValueError("目标在这棵笔记自己的子树里，会成环")
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
            "       n.title, n.pinned, n.icon, n.updated_at,"
            # 这篇是哪来的（导入的 / 写作计划生成的 / 空 = 自己写的）。树上用它挑
            # 默认图标——**一个字形，不占宽度**。库里混着手写、飞书导入、自动生成的
            # 分段时，「这行是我写的还是机器来的」是唯一一个会改变你怎么读这行的信息：
            # 它决定你信不信里面的话、该不该直接改它。`created_at` **不查**——找东西的
            # 线索是修改时间，创建时间只在信息面板里有意义（docs/sidebar-ia-plan.md §3）。
            "       n.source,"
            # 正文开头。**树上标题为空或还是占位符时拿它当显示名**——真实
            # 库里 18 篇有 15 篇标题字面就是「未命名」（旧界面建笔记时的
            # 默认值），一列二十个「未命名」的树是没法用的。
            # 只取前 80 字：树是导航，不是预览器。
            # preview 只有占位标题（「未命名」那几种）的笔记才用得上——树 / 标签拿它当显示名；
            # 起了名的笔记 80 字白带：shot-perf 413 篇树 208KB，一半是这个（第 437 轮）
            "       CASE WHEN n.title IN ('', '未命名', 'Untitled', 'note') THEN substr(n.content, 1, 80) ELSE '' END AS preview,"
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


# 一份计划最多这么多分段，单次最多追加这么多。**每个分段最后都独立成一篇笔记、
# 各自跑若干轮模型调用**，所以模型抽风返回一百条标题的代价是一百篇笔记加一百轮调用。
# prompt 里写的正常范围是 3–8 个，这两个数远高于它，只挡失控（第 574 轮）。
MAX_PLAN_SECTIONS = 40
MAX_SECTIONS_PER_ADD = 20
# 分段标题会成为笔记标题
SECTION_TITLE_MAX = 80


# 分段标题会成为笔记标题，标题里不该有引用标记。第 595 轮实拍：加了「零引用要拦下」的判据之后，
# 模型连分段标题都开始带编号——「硬件线：设备与 APP 的连接稳定性及测试验证 [terrence-1850-6F6]」。
_TITLE_CITE = re.compile(r"\s*\[[A-Za-z][A-Za-z0-9_-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+\]")


def _clean_section_title(t: str) -> str:
    return " ".join(_TITLE_CITE.sub("", t or "").split())[:SECTION_TITLE_MAX]


def _section_key(t: str) -> str:
    return " ".join((t or "").split()).lower()


def add_sections(plan_id: str, titles: list[str]) -> list[dict]:
    """追加新 section，idx 接着已有的往后编号——初次生成骨架、以及后续
    「还有没有更多可写」判定为是时的追加，都走这一个函数。

    **跟已有分段同名的丢掉**：prompt 里反复交代过不要重复提同一个主题，实测照样会
    （「决策、冲突与升级机制」写完又提「决策与冲突处理规范」），用户拿到的是两篇雷同的笔记。
    字面同名是确定性可判的，先把这一层挡掉；换说法的重复仍然只能靠 prompt。
    """
    with connect() as c:
        existing = c.execute("SELECT COALESCE(MAX(idx), -1) FROM writing_sections WHERE plan_id=?",
                             (plan_id,)).fetchone()[0]
        have = {_section_key(r[0]) for r in
                c.execute("SELECT title FROM writing_sections WHERE plan_id=?", (plan_id,)).fetchall()}
        cap = min(MAX_SECTIONS_PER_ADD, max(0, MAX_PLAN_SECTIONS - len(have)))
        picked: list[str] = []
        for t in titles:
            if len(picked) >= cap:
                break
            t = _clean_section_title(t)
            k = _section_key(t)
            if not t or k in have:
                continue
            have.add(k)
            picked.append(t)
        titles = picked
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
             chunks_total: int | None = None, chunks_done: int | None = None,
             note_id: str | None = None) -> None:
    with connect() as c:
        c.execute(
            "UPDATE ingest_items SET status=?, facts=?, detail=?, updated_at=? WHERE id=?",
            (status, facts, detail[:500], _now(), item_id))
        if chunks_total is not None:
            c.execute("UPDATE ingest_items SET chunks_total=? WHERE id=?", (chunks_total, item_id))
        if chunks_done is not None:
            c.execute("UPDATE ingest_items SET chunks_done=? WHERE id=?", (chunks_done, item_id))
        if note_id is not None:
            c.execute("UPDATE ingest_items SET note_id=? WHERE id=?", (str(note_id)[:32], item_id))


# 没有历史数据时每块按这个估（GPT 实测 ~13s / 块）；token 按「固定提示 + 正文 / 1.5 + 输出」估
DEFAULT_CHUNK_MS = 13000
TOKENS_PER_CHUNK_FIXED = 1600


def bump_job_chunk(job_id: str, ms: int, chars: int) -> None:
    """一块抽完：累计耗时 / 字数 / 块数，预估时间和用量从这里算。"""
    with connect() as c:
        c.execute("UPDATE ingest_jobs SET chunk_ms=chunk_ms+?, chars_done=chars_done+?, chunks_done=chunks_done+?"
                  " WHERE id=?", (int(ms), int(chars), 1, job_id))


def set_job_chunks_total(job_id: str, n: int) -> None:
    with connect() as c:
        c.execute("UPDATE ingest_jobs SET chunks_total=? WHERE id=?", (int(n), job_id))


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
    total = sum(int(i.get("chunks_total") or 0) for i in items) or int(job.get("chunks_total") or 0)
    n = int(job.get("chunks_done") or 0)
    done = sum(int(i.get("chunks_done") or 0) for i in items) if items else n
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
                       final_scores: dict[str, int], weak_dimensions: list[str],
                       stopped: str = "", run_id: str = "",
                       tokens: int = 0, calls: int = 0) -> None:
    """记一次跑。

    **`run_id` 传的是 `harness_rounds.run_id` 那个 id**（`Ledger` 生成的），
    于是这三张表第一次有了同一个连接键：`harness_runs.id` = `harness_rounds.run_id`
    = `harness_edits.run_id`。在这之前 `harness_runs` 和 `harness_rounds`
    **没有任何 join 键**——批 23 量「单次跑花多少」只能拿时间窗口把
    `llm_usage` 贴回去，而那份重建在两次跑重叠时会把账算到隔壁。
    留空则照旧自己生成一个（没挂 `Ledger` 的模式走这条）。
    """
    with connect() as c:
        c.execute(
            "INSERT INTO harness_runs "
            "(id, key, status, rounds, final_scores, weak_dimensions, stopped, "
            "tokens, calls, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id or str(uuid.uuid4()), key, status, rounds,
             json.dumps(final_scores, ensure_ascii=False),
             json.dumps(weak_dimensions, ensure_ascii=False), stopped[:40],
             int(tokens), int(calls), _now()))
        # 一个 key（一篇笔记 / 一个分段）只留最近 50 次：策略只看最近几次，
        # 再往前的除了占地方没有用
        c.execute("DELETE FROM harness_runs WHERE key=? AND id NOT IN ("
                  "SELECT id FROM harness_runs WHERE key=? ORDER BY created_at DESC, rowid DESC LIMIT 50)",
                  (key, key))


def record_harness_round(key: str, run_id: str, round_: int, scores: dict[str, int],
                         status: str, weakest: str, content_len: int,
                         facts_new: int = 0, facts_total: int = 0,
                         tool_calls: int = 0, repeat_calls: int = 0,
                         cached_calls: int = 0, superseded: int = 0,
                         revisions_proposed: int = 0,
                         revisions_dropped: int = 0,
                         depth_dropped: int = 0,
                         claim_atoms: int = -1,
                         fired_checks: str = "",
                         abstained: str = "") -> None:
    """记一轮。**记账失败不能影响这一轮的产出**——这张表是给分析用的，
    不是承重的，所以调用方把它包在 try 里。"""
    with connect() as c:
        c.execute(
            "INSERT INTO harness_rounds (id,key,run_id,round,scores,status,weakest,"
            "content_len,facts_new,facts_total,tool_calls,repeat_calls,"
            "cached_calls,superseded,revisions_proposed,revisions_dropped,"
            "depth_dropped,claim_atoms,fired_checks,abstained,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), key, run_id, int(round_),
             json.dumps(scores, ensure_ascii=False), status, weakest,
             int(content_len), int(facts_new), int(facts_total),
             int(tool_calls), int(repeat_calls),
             int(cached_calls), int(superseded),
             int(revisions_proposed), int(revisions_dropped),
             int(depth_dropped), int(claim_atoms), str(fired_checks or ""),
             str(abstained or ""), _now()))
        # 跟 harness_runs 同一条修剪规矩：一个 key 只留最近 400 行
        # （50 次跑 × 8 轮），再往前的除了占地方没有用。
        c.execute("DELETE FROM harness_rounds WHERE key=? AND id NOT IN ("
                  "SELECT id FROM harness_rounds WHERE key=? "
                  "ORDER BY created_at DESC, rowid DESC LIMIT 400)", (key, key))


def rounds_of_run(run_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM harness_rounds WHERE run_id=? ORDER BY round",
                         (run_id,)).fetchall()
    return [dict(r) | {"scores": json.loads(r["scores"] or "{}")} for r in rows]


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
            "stopped": row["stopped"] if "stopped" in row.keys() else "",
        }
        for row in rows
    ]


def sweep_orphan_assets(assets_dir: Path, min_age_days: int = 7) -> dict:
    """资产库里没有任何笔记 / 历史版本 / 最近删除引用的图删掉。dev 库 10 张里 6 张（6.6MB）是探针拖图、
    删掉的笔记留下的，之前没有任何清理机制（第 417 轮）。7 天宽限：刚贴进来还没自动保存的图不能误删；
    引用按文件名 LIKE 扫三张表，笔记里的图片链接是 `/api/assets/<名字>`。"""
    if not assets_dir.is_dir():
        return {"removed": 0, "bytes": 0}
    now = datetime.now(timezone.utc).timestamp()
    removed = 0
    freed = 0
    with connect() as c:
        for entry in sorted(assets_dir.iterdir()):
            if not entry.is_file() or entry.name.startswith("."):
                continue
            if now - entry.stat().st_mtime < min_age_days * 86400:
                continue
            pat = f"%{entry.name}%"
            used = any(
                c.execute(f"SELECT 1 FROM {t} WHERE {col} LIKE ? LIMIT 1", (pat,)).fetchone()
                for t, col in (("notes", "content"), ("note_revisions", "content"), ("note_trash", "payload")))
            if used:
                continue
            try:
                size = entry.stat().st_size
                entry.unlink()
                removed += 1
                freed += size
            except OSError:
                pass
    return {"removed": removed, "bytes": freed}


def prune_job_payloads(jobs_dir: Path) -> int:
    """导入任务的 payload（清洗好的笔记列表落盘，给断点续跑用）跑完就没用了：
    done / error / cancelled 的、以及库里已经没有这个 job 的文件删掉，只留 interrupted 的。"""
    if not jobs_dir.is_dir():
        return 0
    with connect() as c:
        keep = {r[0] for r in c.execute("SELECT payload_path FROM ingest_jobs WHERE status IN ('interrupted','queued','running','cancelling') AND payload_path<>''")}
    n = 0
    for f in jobs_dir.glob("*.json"):
        if str(f) not in keep and f.name[:-5] not in {Path(k).name[:-5] for k in keep}:
            f.unlink(missing_ok=True)
            n += 1
    return n


def sweep_orphan_plans() -> int:
    """父节点已经不在的 active 计划标成 abandoned；非活跃计划里指着已删笔记的 section 行、
    既不在笔记也不在回收站的导回记录，一起清掉。启动时扫一遍（dev 库里攒了 261 行这样的 section）。"""
    with connect() as c:
        n = c.execute("UPDATE writing_plans SET status='abandoned' WHERE status='active'"
                      " AND parent_note_id NOT IN (SELECT id FROM notes)").rowcount
        n += c.execute("DELETE FROM writing_sections WHERE note_id<>'' AND note_id NOT IN (SELECT id FROM notes)"
                       " AND plan_id IN (SELECT id FROM writing_plans WHERE status<>'active')").rowcount
        n += c.execute("DELETE FROM note_remotes WHERE note_id NOT IN (SELECT id FROM notes)"
                       " AND note_id NOT IN (SELECT note_id FROM note_trash)").rowcount
        return n


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
            "SELECT slug, enabled, scopes, sandbox, source, idx, seeded_sha FROM skill_config "
            "WHERE user_id = ?", (user_id,)).fetchall()
    return {
        r["slug"]: {
            "enabled": bool(r["enabled"]),
            "scopes": [s for s in (r["scopes"] or "").split(",") if s],
            "sandbox": r["sandbox"],
            "source": r["source"],
            "idx": r["idx"],
            "seeded_sha": r["seeded_sha"],
        }
        for r in rows
    }


def set_skill_config(user_id: str, slug: str, *, enabled: bool | None = None,
                     scopes: list[str] | None = None, sandbox: str | None = None,
                     source: str | None = None, idx: int | None = None,
                     seeded_sha: str | None = None) -> None:
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
                              ("seeded_sha", seeded_sha),
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


SNAPSHOT_MAX_AGE_DAYS = 7
USAGE_KEEP_DAYS = 90        # 用量账本：设置页只看到 30 天，留 90 天够回看
JOB_KEEP_DAYS = 30          # 跑完的导入 / 入库任务：面板只列最近几个
PLAN_KEEP_DAYS = 30         # 作废 / 写完的写作计划：只有活跃的那个会被用到


def vacuum_if_bloated(min_free_mb: float = 1.0, min_ratio: float = 0.25) -> dict:
    """启动时把删掉的页还给文件系统。sqlite 删行不缩文件，只把页挂到 freelist 上再复用：
    dev 库表里的数据 1.6MB，文件 10.1MB，81% 是空页（第 415 轮实测，历次清理 / 删测试用户攒的）。
    备份是整文件拷，跟着一起胖。空页 ≥ min_free_mb（1MB）且占比 ≥ min_ratio 才 VACUUM——小库没必要，
    大库一次 VACUUM 要重写整个文件，只在真的胖了才做。"""
    with connect() as c:
        page_size = c.execute("PRAGMA page_size").fetchone()[0]
        pages = c.execute("PRAGMA page_count").fetchone()[0]
        free = c.execute("PRAGMA freelist_count").fetchone()[0]
    before_mb = pages * page_size / 1024 / 1024
    free_mb = free * page_size / 1024 / 1024
    if pages == 0 or free_mb < min_free_mb or free / pages < min_ratio:
        return {"vacuumed": False, "before_mb": round(before_mb, 1), "free_mb": round(free_mb, 1)}
    conn = sqlite3.connect(_db_path())
    try:
        conn.isolation_level = None          # VACUUM 不能在事务里
        conn.execute("VACUUM")
        after = conn.execute("PRAGMA page_count").fetchone()[0] * page_size / 1024 / 1024
    finally:
        conn.close()
    return {"vacuumed": True, "before_mb": round(before_mb, 1), "after_mb": round(after, 1), "free_mb": round(free_mb, 1)}


def sweep_old_rows(now: datetime | None = None) -> dict:
    """启动时清掉只增不减的流水：用量账本、跑完的入库任务（连同它的 items）、非活跃的写作计划
    （连同 sections）。都是没有界面再回看的历史（第 264 轮：dev 库 27 个任务 201 个 item、18 个旧计划、
    45 条用量，都没有过期机制）。笔记 / 事实 / 历史版本不在这里——那些是数据。"""
    now = now or datetime.now(timezone.utc)
    cut = lambda days: (now - timedelta(days=days)).isoformat()   # noqa: E731
    out = {}
    with connect() as c:
        out["usage"] = c.execute("DELETE FROM llm_usage WHERE created_at < ?", (cut(USAGE_KEEP_DAYS),)).rowcount
        old_jobs = [r["id"] for r in c.execute(
            "SELECT id FROM ingest_jobs WHERE status NOT IN ('queued','running') AND created_at < ?", (cut(JOB_KEEP_DAYS),))]
        if old_jobs:
            q = ",".join("?" * len(old_jobs))
            c.execute(f"DELETE FROM ingest_items WHERE job_id IN ({q})", old_jobs)
            c.execute(f"DELETE FROM ingest_jobs WHERE id IN ({q})", old_jobs)
        out["jobs"] = len(old_jobs)
        old_plans = [r["id"] for r in c.execute(
            "SELECT id FROM writing_plans WHERE status <> 'active' AND updated_at < ?", (cut(PLAN_KEEP_DAYS),))]
        if old_plans:
            q = ",".join("?" * len(old_plans))
            c.execute(f"DELETE FROM writing_sections WHERE plan_id IN ({q})", old_plans)
            c.execute(f"DELETE FROM writing_plans WHERE id IN ({q})", old_plans)
        out["plans"] = len(old_plans)
        c.commit()
    return out


def sweep_stale_snapshots(days: int = SNAPSHOT_MAX_AGE_DAYS) -> int:
    """启动时清掉所有用户超过 N 天没人来处置的轮末暂停。留着的话每次打开那篇都提示
    「上次写到第 N 轮停下来等你处置」，而恢复它等于把一周前的材料盖到已经改过的正文上
    （第 222 轮）。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with connect() as c:
        n = c.execute("DELETE FROM harness_snapshots WHERE created_at < ?", (cutoff,)).rowcount
        c.commit()
    return n


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
