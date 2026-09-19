"""请求/响应模型。"""

from __future__ import annotations

from typing import Literal

import re

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------- 笔记

# 标题是一行字：树、标签页、面包屑都按一行画。接口曾照收带换行的和一万字的标题（第 244 轮实测）。
TITLE_MAX = 200


def _one_line_title(v: str) -> str:
    return " ".join((v or "").split())[:TITLE_MAX]


class NoteIn(BaseModel):
    title: str = ""
    content: str = ""

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return _one_line_title(v)


class NoteIntent(BaseModel):
    """文档意图（P9，agent-native-editor §3.1）：这篇要干什么。三个字段各一行；
    source = prefill（代码按标题预填的）/ user（用户改过一个字就是校准）/ 空。"""
    goal: str = ""
    reader: str = ""
    done: str = ""
    source: Literal["", "prefill", "user"] = ""
    # P12（§3.1「完成标准可检查」）：「完成标准」里用户勾过的条目原文——代码判不了的才要人勾
    checked: list[str] = []


class NoteIntentIn(NoteIntent):
    pass


class TrayItemIn(BaseModel):
    """材料托盘的一条（P14，agent-native-editor §3.4）。kind：note = 另一篇笔记（ref_id 是它的 id）/
    fact = 知识库里一条事实（ref_id 是 fact id）/ import = 导入进来的一段 / selection = 从别处摘的一段。
    excerpt 是进 prompt 的那段（后端封顶 `store.TRAY_EXCERPT_MAX`）。"""
    id: str = ""
    kind: Literal["note", "fact", "import", "selection"]
    ref_id: str = ""
    title: str = ""
    excerpt: str = ""


class TrayItem(TrayItemIn):
    position: int = 0
    added_at: str = ""


class TrayIn(BaseModel):
    """整份托盘（顺序 = 数组顺序）。加一条 / 删一条 / 拖序都是 PUT 整份——托盘最多 24 条，整份比补丁简单。"""
    items: list[TrayItemIn] = Field(default_factory=list)


class TrayOut(BaseModel):
    items: list[TrayItem] = Field(default_factory=list)


class TrayClipIn(BaseModel):
    """网页剪藏进托盘（P15 #3）：一个网址。抓正文变成一条 `import` 材料追加到托盘末尾。"""
    url: str


class Note(BaseModel):
    # 摄入过没有（空 = 没有）。前端拿它判「改过没同步」、决定要不要自动同步。
    ingested_at: str = ""
    # 从哪导来的（obsidian / notion / apple / evernote / feishu…）、源侧稳定 id、上次导入时间
    source: str = ""
    source_id: str = ""
    imported_at: str = ""

    id: str
    user_id: str
    title: str
    content: str
    pinned: bool = False
    # 笔记图标（boxicons 类名，空 = 默认）
    icon: str = ""
    # 写作骨架跟着笔记走。之前只活在前端内存里，换一篇/刷新/无限续写自动
    # 跟随切页，骨架就没了——而 harness 每轮都要拿它当主线依据。
    spine: str = ""
    beats: list[str] = Field(default_factory=list)
    # 文档意图跟着笔记走（P9）。库里没有就是四个空串。
    intent: NoteIntent = Field(default_factory=NoteIntent)
    created_at: str
    updated_at: str


class NoteIconIn(BaseModel):
    """boxicons 的类名（bx-rocket 这种）或空串。只认这一种形状：图标名会原样进 className。"""
    icon: str = ""

    @field_validator("icon")
    @classmethod
    def _shape(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not re.fullmatch(r"bxs?-[a-z0-9-]{1,40}", v):
            raise ValueError("图标名只能是 boxicons 的类名，如 bx-rocket")
        return v


class ComposeBlockIn(BaseModel):
    """`/` 唤起的块生成。cursor 是光标在正文里的字符位置——只取它前后一段
    当上下文，不是整篇（整篇会让模型去接全文的尾巴，而不是补这个位置）。"""

    note_id: str = ""
    title: str = ""
    content: str = ""
    cursor: int = 0
    mode: str = "prompt"
    prompt: str = ""
    scope: str = "all"      # 记忆范围
    # 用户选中的那段。给了就是「对这段做点什么」（右键 → 自定义提示），
    # 没给就是「在光标这里插一块」（`/` 唤起）。同一套 harness，差的是作用域。
    selection: str = ""
    # 文档意图那句（P9）。智能排版用；`/block` 走 harness loop 那条线 P11 接上了（`hooks/block._system`）
    intent: str = ""
    # `/` 菜单「从托盘写」（P14）：只用托盘里摊开的材料写这一块。托盘空着就 400——不花模型调用。
    from_tray: bool = False


class SkeletonSaveIn(BaseModel):
    spine: str = ""
    beats: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- 笔记树
#
# 照 Trilium：树的边是 branch，不是笔记上的一个 parent 字段。一个笔记有多条
# branch 就是「克隆」——同时长在树的多个位置。所以下面这些操作的主语都是
# **branch**（哪个笔记、在哪个父节点下），不是笔记。

class TreeRow(BaseModel):
    """树上的一个节点 = 一条 branch + 那篇笔记的显示信息。"""
    id: str                  # branch id
    note_id: str
    parent_note_id: str      # 'root' 表示挂在树根
    position: int
    is_expanded: bool = False
    title: str
    # 正文开头。标题为空或还是「未命名」这种占位符时，树上拿它当显示名。
    preview: str = ""
    # 跟知识库的连接，树上直接看得见（见 docs/kb-fusion-design.md）：
    # 引用了几条事实、什么时候被摄入的。一眼看出哪些笔记「有据可依」、
    # 哪些还只是草稿。
    cite_count: int = 0
    ingested_at: str = ""
    pinned: bool = False
    icon: str = ""
    # 这篇是哪来的：obsidian / notion / feishu / apple / plan（写作计划生成的分段），
    # 空 = 自己写的。树上按它挑默认图标。`created_at` 不在这儿——见
    # docs/sidebar-ia-plan.md §3。
    source: str = ""
    updated_at: str
    child_count: int = 0
    # 这篇笔记一共有几条 branch。>1 就是克隆，树上要标出来——用户得知道
    # 改这一处会让别处跟着变。
    branch_count: int = 1
    # 只有知识库虚拟子树的节点用：这个主题/实体/月份名下有几条事实（主题含
    # 子主题闭包）。真笔记恒为 0。
    fact_count: int = 0


class Snippet(BaseModel):
    before: str
    hit: str
    after: str


class NoteBrief(BaseModel):
    """⌘K / `[[` 补全用的轻量行：不带全文。"""
    id: str
    title: str
    updated_at: str
    pinned: bool = False
    icon: str = ""           # 笔记图标（boxicons 类名，空 = 默认）
    preview: str = ""
    has_body: bool = True
    first_body: str = ""      # 第一行非标题正文，同名笔记靠它分辨
    snippet: Snippet | None = None


class NoteBriefPage(BaseModel):
    notes: list[NoteBrief]
    total: int


class NoteCreateIn(BaseModel):
    title: str = ""
    content: str = ""

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return _one_line_title(v)
    # 建在哪个父节点下。笔记总是创建在树上的某个位置，没有「先建了再说」
    # 这个中间态——不挂的话它存在于库里但用户看不见。
    parent_note_id: str = "root"


class BranchAttachIn(BaseModel):
    """把一篇已有的笔记挂到另一个位置 = 克隆。"""
    note_id: str
    parent_note_id: str = "root"


class BranchMoveIn(BaseModel):
    note_id: str
    from_parent_id: str
    to_parent_id: str
    position: int | None = None


class BranchReorderIn(BaseModel):
    parent_note_id: str
    order: list[str]


class BranchExpandIn(BaseModel):
    note_id: str
    parent_note_id: str
    expanded: bool


# ---------------------------------------------------------------- 无限续写计划

class WritingPlanStartIn(BaseModel):
    parent_note_id: str
    goal: str = ""
    scope: str = "all"      # 记忆范围（database/kb/scope.py）


class WritingSection(BaseModel):
    id: str
    plan_id: str
    idx: int
    title: str
    status: Literal["pending", "in_progress", "done"] = "pending"
    note_id: str = ""
    summary: str = ""
    created_at: str


class WritingPlan(BaseModel):
    id: str
    user_id: str
    parent_note_id: str
    goal: str
    status: Literal["active", "done", "abandoned"] = "active"
    doc_note_id: str = ""
    created_at: str
    updated_at: str


class WritingPlanOut(BaseModel):
    plan: WritingPlan | None = None
    sections: list[WritingSection] = Field(default_factory=list)


class WritingPlanRunIn(BaseModel):
    parent_note_id: str
    scope: str = "all"      # 记忆范围：每节取材料只看这一档


# ---------------------------------------------------------------- 单篇笔记 harness

class NoteHarnessRunIn(BaseModel):
    """``mode`` 决定这次跑的是哪种闭环：

    ``write``（默认）—— 修订 + 续写交替，写到结构节拍被实质覆盖为止。
    ``polish`` —— **只修不写**：反复修订 + 打分，直到"已写内容自身"这几个
    维度都达标。这条是补上"生成修订建议"那个功能一直缺的东西——它原来是
    一次性调用：点一下给最多 6 条建议就结束，没有打分、没有轮次、**没有
    任何东西告诉你改到这就够了**，你可以一直点它一直给。
    """

    note_id: str
    content: str
    mode: Literal["write", "polish"] = "write"
    spine: str = ""
    beats: list[str] = Field(default_factory=list)
    # **不传就用模式默认**（`modes.NOTE.max_rounds` = 8）。P6 问题 4：这里原来
    # 默认 20、前端 `api.ts` 也硬传 20，两处一起把模式上那个 8 盖掉——P5 实拍
    # `e78306202d78` 跑了 15 轮 385 秒 421k token。轮数是模式的属性，不是每个
    # 请求的参数；显式传只给脚本 / 测试用，仍受 `MAX_ROUNDS_CAP` 封顶。
    max_rounds: int | None = None
    # 文档意图那句（P11）：前端带过来的是标题下那一行**此刻**的值（落库有 800ms 延迟）；
    # 不带就用库里 `notes.intent` 那份。
    intent: str = ""
    # 每轮写完停下来等用户逐条接受/拒绝。**是用户的选择，不是功能的属性**
    # ——同一个人在重要文档上想要、在草稿上不想要。
    review_each_round: bool = False
    scope: str = "all"      # 记忆范围（database/kb/scope.py），取材料时只看这一档


class HarnessResumeIn(BaseModel):
    """用户处置完之后带回来的东西。

    ``content`` 是**编辑器里逐条接受/拒绝之后的正文**——用户的决定发生在
    编辑器里，让后端拿一串 hunk id 再合并一遍等于同一个合并写两份实现，
    而用户真正看到的是浏览器里那一份。
    """

    content: str = ""
    # 用户看完决定不再往下写了：存盘收尾，不再跑一轮。
    stop: bool = False


# ---------------------------------------------------------------- Skill 系统

class SkillIn(BaseModel):
    name: str
    # 目录名，也是 SKILL.md 里的 ``name``——规格只允许小写字母/数字/连字符。
    # 前端可以不传，后端从 name 生成；中文名生成不出合法 slug 时退到稳定哈希，
    # 可读的名字放 body 的一级标题（规格给它留的位置就是那里）。
    slug: str = ""
    description: str = ""
    scopes: list[str] = Field(default_factory=list)
    content: str
    enabled: bool = True


class Skill(BaseModel):
    """一个 skill 目录的对外形状。

    ``id`` 就是 slug（目录名）——skill 不再是数据库行，没有独立主键。
    前端一直按 ``id`` 寻址，所以这个字段留着，只是含义从「随机 id」变成
    「目录名」。
    """

    id: str
    slug: str
    name: str
    description: str
    scopes: list[str]
    content: str
    enabled: bool
    idx: int
    builtin: bool
    source: str = "user"
    sandbox: str = "none"


class SkillScope(BaseModel):
    value: str
    label: str


class SkillReorderIn(BaseModel):
    ordered_ids: list[str]


class SkillGenerateIn(BaseModel):
    goal: str
    scope_hint: str = ""


# ---------------------------------------------------------------- 个人偏好

class ProfileEntryIn(BaseModel):
    text: str


class ProfileEntry(BaseModel):
    id: str
    user_id: str
    text: str
    created_at: str


# ---------------------------------------------------------------- LLM 供应商配置

class ProviderConfigIn(BaseModel):
    provider: str  # "local" | "gpt"（gpt = 任何 OpenAI 兼容端点，界面叫「OpenAI 兼容」）
    gpt_api_key: str | None = None  # 不传就保留原值，见 store.set_provider_config
    gpt_model: str | None = None
    gpt_base_url: str | None = None
    asr_base_url: str | None = None  # 空串 = 清掉、退回 .env 默认
    auto_sync_notes: bool | None = None
    # 「本地模型」那一档（P19 #1）：不传 = 保留；空串 = 清掉、退回 .env / 出厂默认
    local_base_url: str | None = None
    local_model: str | None = None
    local_api_key: str | None = None
    # 看图：不传 = 保留；空串 = 清掉 → 跟着写作模型走
    vision_base_url: str | None = None
    vision_model: str | None = None
    vision_api_key: str | None = None


class ProviderTestIn(BaseModel):
    """「测一下」（P19 #1）：真发一次请求，结果当场显示。`api_key` 不传 = 用 `saved_key_of` 那一档已存的 key。"""
    kind: str                      # "llm" | "vision" | "asr"
    base_url: str
    model: str = ""
    api_key: str | None = None
    saved_key_of: str = ""         # "local" | "gpt" | "vision"


class ProviderTestOut(BaseModel):
    ok: bool
    message: str
    models: list[str] = Field(default_factory=list)
    model_found: bool | None = None   # /models 列表里有没有填的那个模型；列表拿不到 = None
    elapsed_ms: int = 0


class ProviderConfigOut(BaseModel):
    provider: str
    gpt_model: str
    gpt_base_url: str
    asr_base_url: str        # 用户填的（空 = 没填，在用默认）
    asr_default_url: str     # .env 默认，界面当 placeholder
    auto_sync_notes: bool = False
    # 看图那台（屏幕活动的描述走它，跟写作用的 LLM 是两回事）。**只读**：它是
    # 部署配置，跟 `asr_default_url` 一样。摆出来是因为知情选择那一屏上写着
    # 「截图发到哪」——**说得出口的承诺必须看得见**，否则就是一句安慰。
    vision_base_url: str = ""
    vision_model: str = ""
    vision_api_key_set: bool = False
    # 看图这一栏是不是「跟着写作模型走」（设置页没填、.env 也没覆盖）
    vision_follows_llm: bool = True
    # 看图实际生效的那台（跟着走时 = 写作模型那台），界面只读展示
    vision_active_url: str = ""
    vision_active_model: str = ""
    # 「本地模型」那一档（P19 #1）
    local_base_url: str = ""        # 用户填的（空 = 在用默认）
    local_model: str = ""
    local_api_key_set: bool = False
    local_default_url: str = ""     # .env / 出厂默认，界面当 placeholder
    local_default_model: str = ""
    # 有没有配过模型（llm_configured）：没配过时状态栏说「还没配模型」而不是报地址
    configured: bool = False
    configured_source: str = "default"
    # 当前实际生效的写作模型（不带 key）
    active_url: str = ""
    active_model: str = ""
    # 不把真实 key 传回前端——只告诉它"存了没"和"末尾几位"，用来在界面上
    # 显示"已设置 sk-...ab12"这种确认状态，不需要也不该把完整 key 露出来
    gpt_api_key_set: bool
    gpt_api_key_preview: str


# ---------------------------------------------------------------- 记忆

class FactOut(BaseModel):
    id: str
    text: str
    when: str = ""
    kind: str = ""
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class TopicOut(BaseModel):
    code: str
    parents: list[str] = Field(default_factory=list)
    status: str = "candidate"
    aliases: list[str] = Field(default_factory=list)
    fact_count: int = 0


class TopicCreateIn(BaseModel):
    code: str
    parent: str = ""
    aliases: list[str] = Field(default_factory=list)


class EntityOut(BaseModel):
    code: str
    name: str = ""
    type: str = ""
    aliases: list[str] = Field(default_factory=list)
    relations: list[tuple[str, str]] = Field(default_factory=list)
    fact_count: int = 0


class TopicEntityLink(BaseModel):
    topic: str
    entity: str
    weight: int


class NoteGraphOut(BaseModel):
    """这篇笔记周围有什么：正文引用的 + 它贡献的事实，各自挂在哪些主题 / 实体上（局部图用）。"""
    facts: int = 0
    topics: list[TopicOut] = Field(default_factory=list)
    entities: list[EntityOut] = Field(default_factory=list)
    links: list[TopicEntityLink] = Field(default_factory=list)


class SourceLineOut(BaseModel):
    id: str
    unit: str
    date: str = ""
    who: str = ""
    text: str


class CitingNoteOut(BaseModel):
    """引用了某条事实的笔记。右栏「反向链接」用。"""
    id: str
    title: str
    updated_at: str
    preview: str = ""      # 标题是「未命名」时前端拿正文首行当显示名
    icon: str = ""         # 笔记图标（boxicons 类名，空 = 默认）


class RevisionOut(BaseModel):
    """一版的摘要（列表用，不带正文）。"""
    id: str
    note_id: str
    title: str
    reason: str            # auto / manual / before_restore / harness / round / run_end
    created_at: str
    chars: int
    # 哪一次跑、哪一轮（P16 改动的分层历史）：`round` 行 = 那一轮烧进正文之前；收尾一行 = 最后一轮之后
    # （正常跑完是 `harness`，P18 #2 起带 round_no；暂停 / 没进 harness_runs 的跑是 `run_end`）。
    # 空 / 0 = 跟跑无关的版本。
    run_id: str = ""
    round_no: int = 0


class RevisionFullOut(RevisionOut):
    content: str


class NoteLinksOut(BaseModel):
    """笔记之间的链接：`[标题](note://<id>)`。outgoing 是这篇链出去的，backlinks 是链进来的。"""
    outgoing: list[CitingNoteOut]
    backlinks: list[CitingNoteOut]
    # 正文里链到的、已经不在的笔记 id（删了 / 从别的库导来的）：面板要列出来，能一键改成纯文本
    dangling: list[str] = Field(default_factory=list)


class FactPeekOut(BaseModel):
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    entity_names: list[str] = Field(default_factory=list)   # 实体显示名，跟 entities 一一对应（chip 上显示 Facebook 不是 facebook）
    """行内出处浮层要的东西：一条事实 + 它的原话。

    `sources` 最多三条——浮层是**扫一眼**用的，不是阅读器；要看全部走
    知识库那一栏。
    """
    id: str
    text: str
    when: str = ""
    kind: str = ""
    sources: list[str] = Field(default_factory=list)


class FactDetailOut(BaseModel):
    """事实表用的行——比 FactOut 多 who/conf/unit，少 sources（另走
    /facts/{id}/sources 按需拉，列表页不用为每行都查一遍原文）。"""
    id: str
    text: str
    when: str = ""
    kind: str = ""
    who: str = ""
    conf: str = ""
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    entity_names: list[str] = Field(default_factory=list)   # 实体显示名，跟 entities 一一对应（chip 上显示 Facebook 不是 facebook）
    unit: str = ""
    superseded_by: str = ""
    merged: bool = False


class FactsPageOut(BaseModel):
    facts: list[FactDetailOut]
    total: int
    limit: int
    offset: int


class TimelineBucket(BaseModel):
    date: str
    units: int = 0
    facts: int = 0


class TimelineOut(BaseModel):
    buckets: list[TimelineBucket]


class StatsOut(BaseModel):
    facts: int
    topics: int
    entities: int
    units: int = 0
    lines: int = 0
    speakers: list[str] = Field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
    codebook: str


class RecallIn(BaseModel):
    query: str
    limit: int = 8
    scope: str = "all"      # 记忆范围：all / notes / meetings / imports（database/kb/scope.py）


class RecallOut(BaseModel):
    facts: list[FactOut]
    took_ms: float
    terms: list[str] = Field(default_factory=list)
    # 知识库一条事实都没有。**「没查到」和「库是空的」得分得开**：前者该劝人
    # 换个说法再试，后者该劝人去导入。第 676 轮在写作闭环里修过一次，第 677 轮
    # 实拍发现 `@` 引用这条路上同样在说「知识库里没找到跟"样机"相关的记录」
    # ——那句话对一个还没导过任何东西的人是误导。
    kb_empty: bool = False
    # 空结果的原因（P7）：no_terms = 查询里没有可查的内容词；weak = 有词，但没有一条记录同时命中
    # 两个不同的词（长查询不硬凑）；"" = 有结果或说不清。
    why_empty: str = ""


class IngestTextIn(BaseModel):
    content: str
    title: str = ""
    source: str = "doc"
    # 原始内容的日期（YYYY-MM-DD）。**批量导入必须带上**——不带的话所有内容
    # 都会被记成导入当天，用户几年的笔记被压成同一天，时间线彻底失真。而事实
    # 的日期正是写作时判断 factual_grounding 的依据（见 harness-architecture
    # 第 9 节「事实的时间信息从未进过 prompt」那条根因）。
    date: str = ""
    # 源侧的稳定标识（Notion page_id、Obsidian 相对路径、ENEX GUID…）。
    # KITE 会拒绝重复的 session_id 且不花 LLM 调用，所以给了稳定 id 之后
    # **重跑导入自动变成增量同步**；不给就退回随机 id，同一批内容导两次会在
    # 知识库里存两份，第二份还要重新花一遍抽取的钱。
    source_id: str = ""
    # 同步：先删这篇上次摄入的 session 再重抽（只对 source="note" 有意义）
    replace: bool = False


# item 的合法状态。给前端做标签映射用，也是写入侧的白名单（见
# tests/test_importers.py::test_every_item_status_written_is_allowed_by_the_schema）。
ITEM_STATUSES = ("queued", "extracting", "transcribing", "chunking",
                 "remembering", "done", "failed", "cancelled")


class IngestItemOut(BaseModel):
    """批量任务里单个文件的进度。单文件任务（/text /audio）不产生 item，恒为空列表。"""
    id: str
    idx: int
    filename: str
    kind: str
    # 出参用 str 而不是 Literal。**Literal 在这里是个陷阱**：写进 DB 的状态
    # 只要有一个不在枚举里，`GET /api/ingest/jobs` 就整个 500——一行历史坏
    # 数据能让进度面板永远打不开，用户看到的是「处理中…」卡死、点取消没反应。
    # 该管的是**写入**那一侧：tests/test_importers.py 会扫所有 set_item 调用，
    # 保证写进去的状态都在 ITEM_STATUSES 里。
    status: str
    facts: int = 0
    detail: str = ""
    chunks_total: int = 0
    chunks_done: int = 0
    # 这一条落成了哪篇笔记（空 = 没建笔记：只进知识库、或那条失败了）。P15 #3 导入默认进托盘靠它。
    note_id: str = ""


# job 的合法状态。"cancelling" = 收到取消但后台还没停干净（可能卡在一次 LLM
# 调用或 KITE 写锁里），界面要如实说「正在停止」而不是「处理中」。
JOB_STATUSES = ("queued", "running", "cancelling", "done", "error", "cancelled", "interrupted")


class IngestOut(BaseModel):
    job_id: str
    # 同 IngestItemOut.status：**出参用 str 不用 Literal**。一个不在枚举里的
    # 状态会让整个接口 500，界面卡在「处理中」、点取消没反应——这个坑今晚踩了
    # 两次（item 一次、job 一次），所以两处都改成写入侧白名单 + 测试来管。
    status: str
    facts: int = 0
    detail: str = ""
    items: list[IngestItemOut] = Field(default_factory=list)
    # 进度 / 预估 / 用量（store.job_progress）：块数、还要多久、跑了多久、估计花了多少 token、
    # 当前在做哪个文件；resumable = 服务重启中断了但 payload 还在，能继续
    chunks_total: int = 0
    chunks_done: int = 0
    eta_s: int = 0
    elapsed_s: int = 0
    tokens_est: int = 0
    current: str = ""
    resumable: bool = False
    # 开始前的预估（_queue 给）：这一批一共多少块、大概多久、多少 token
    estimate: dict = Field(default_factory=dict)


# ---------------------------------------------------------------- 写作

class SkeletonIn(BaseModel):
    """线 1：为当前写作内容生成主线骨架。"""
    content: str
    title: str = ""
    # 文档意图那句（`editor/intent.as_text`），拼进 system 第一段；空 = 不加（P9）
    intent: str = ""


class SkeletonOut(BaseModel):
    """spine：一句话，这篇东西真正在处理的核心张力/问题——不是主题。
    beats：3-6 条结构性/修辞性功能（"建立处境""引入转折"），不是内容摘要。
    见 prompts.py 的 SKELETON_SYSTEM。"""
    spine: str = ""
    beats: list[str] = Field(default_factory=list)
    # 确定性体检的结果（计划 4.3，`harness/checks/skeleton.py`）。**不拦着返回**，
    # 跟骨架一起显示——骨架是一次成型的产物，重不重新生成由用户定。
    notes: list[str] = Field(default_factory=list)
    took_ms: float


class Revision(BaseModel):
    """一条 track-changes 修订。前端据此渲染可接受/拒绝的标记。

    insert 在 anchor **之后**插入；insert_before 在 anchor **之前**插入——
    后者是给"扩展上下文"用的（往选中片段前面补内容），没有它 insert 的
    "只能加在锚点后面"这个约束就没法表达"往前补"。"""
    id: str
    op: Literal["insert", "delete", "replace", "insert_before"]
    anchor: str = ""          # 原文中被定位的片段（delete/replace/insert_before 用）
    # 被定位片段的**结尾**标记。给了就表示要动的是 anchor 开头到 anchor_end
    # 结尾这一整段，anchor 本身只需要是个短的起始标记。
    #
    # 为什么加这个：原来 anchor 必须是"要被替换的完整原文"，一段两百字的
    # 段落就得原样回显两百字，replace 时改后的 text 还要再输出一遍——同一段
    # 内容进出各一次。输出 token 直接换算成时间，这是纯浪费。
    anchor_end: str = ""
    text: str = ""            # 新内容（insert/replace/insert_before 用）
    reason: str = ""
    sources: list[str] = Field(default_factory=list)


class EditOut(BaseModel):
    """一批 track-changes 修订建议。

    右键「重写 / 润色 / 扩展上下文」共用这一个形状，跟前端的接受/拒绝 UI
    是一套——三个入口做的事不同，但产出都是「几条可以逐条挑的修订」。
    """

    revisions: list[Revision]
    took_ms: float
    # 一条建议都没有时给个原因（比如「撞长度上限 JSON 切了半截」），前端原样提示；
    # 空 = 模型真的没给建议。
    note: str = ""


class MagicTapIn(BaseModel):
    content: str
    spine: str = ""
    beats: list[str] = Field(default_factory=list)
    max_tokens: int = 1200
    # 光标后面已有的正文。有它时「续写」是在中间插一段：接着 content 写、能衔接到
    # following、不重复 following 里已有的。空 = 追加到文末（原来的语义）。
    following: str = ""
    # 标题：正文还很短时它是模型唯一知道的方向（智能续写走 ctx.note_title，续写这条路之前没带）
    title: str = ""
    scope: str = "all"      # 记忆范围（同 RecallIn.scope）
    intent: str = ""       # 文档意图那句（P9）
    # 这篇的 id（P14）：给了就把它的材料托盘取出来摆在材料最前面；空 = 没有托盘（老调用方照旧）
    note_id: str = ""


# ---------------------------------------------------------------- 选中文本操作
#
# 右键选中文本触发的三个动作，都是"给定选区 + 上下文 -> 具体修订建议"，跟
# 线2的修订走同一套 Revision 模型和前端接受/拒绝 UI，不用另起一套展示层。

class RewriteIn(BaseModel):
    content: str
    selection: str
    intent: Literal["rewrite", "polish"] = "rewrite"
    spine: str = ""
    beats: list[str] = Field(default_factory=list)
    doc_intent: str = ""   # 文档意图那句（P9；这里 `intent` 已经被「重写 / 润色」占了）


class ExpandIn(BaseModel):
    content: str
    selection: str
    scope: str = "all"      # 记忆范围（database/kb/scope.py）
    intent: str = ""       # 文档意图那句（P9）
    note_id: str = ""      # 这篇的 id（P14）：托盘里的材料先摆


class VerifyIn(BaseModel):
    content: str
    selection: str
    scope: str = "all"      # 记忆范围：词法召回只看这一档；正文里显式引用的事实不受限
    intent: str = ""       # 文档意图那句（P9）：校验按「完成标准」核
    note_id: str = ""      # 这篇的 id（P14）：托盘里的材料先摆、当证据


class VerifyFinding(BaseModel):
    verdict: Literal["矛盾", "支持", "无法判断"]
    reason: str
    fact_id: str = ""
    fact_text: str = ""
    sources: list[str] = Field(default_factory=list)


class VerifyOut(BaseModel):
    findings: list[VerifyFinding]
    took_ms: float


class SlidesIn(BaseModel):
    """这篇 → 幻灯片。`style`：`points` 要点版 / `talk` 讲稿版——
    两种用途对页面密度的要求正好相反，所以分开而不是加个开关。"""

    note_id: str = ""
    content: str
    title: str = ""
    style: Literal["points", "talk"] = "points"
    max_tokens: int = 3000


class DigestIn(BaseModel):
    """按日期范围（或最近 N 天）生成阶段回顾。不给 date_from/date_to 时按 days 算。"""
    days: int = 7
    date_from: str = ""
    date_to: str = ""
    scope: str = "all"      # 记忆范围（database/kb/scope.py）


class DigestOut(BaseModel):
    summary: str
    fact_count: int
    date_from: str
    date_to: str
    took_ms: float


class TraceIn(BaseModel):
    """「来龙去脉」的入参：**只有一段正文，没有问题**。

    问题由后端拼——判据 1：用户点按钮，不写 prompt。
    """
    passage: str
    limit: int = 10


class AskIn(BaseModel):
    """显式提问知识库。走 KITE 原生 planning，慢但支持时序推理。"""
    question: str
    limit: int = 10


class AskOut(BaseModel):
    answer: str
    facts: list[FactOut] = Field(default_factory=list)
    took_ms: float


# ---------------------------------------------------------------- 屏幕活动
#
# 段落本身落在壳那边（`<userData>/journey/<日期>/segments.json`），这里只是
# 把它交给界面的形状。**截图不走接口出去**：`has_frame` 只说有没有，要看图
# 走 `/api/journey/frame`——图片默认不留、留也只在本机（daily-journey-plan §1）。

class JourneySegment(BaseModel):
    # 这一段在当天文件里的下标。**删一段要按它来**——数组里已删的位置是留着的
    # （抠掉会让后面每一段的下标都挪一位，点第 5 段删掉的其实是第 6 段）。
    i: int = 0
    start: str = ""
    end: str = ""
    app: str = ""
    title: str = ""
    desc: str = ""
    n: int = 0
    has_frame: bool = False
    # 有没有那张 256px 的缩略图（大图在描述做完之后就删了，§1 ③）。
    has_thumb: bool = False


class JourneyDayOut(BaseModel):
    date: str
    segments: list[JourneySegment] = Field(default_factory=list)
    minutes: int = 0
    # 已经写过的日报（`<那天>/report.json`）。没写过就是空串——**不自动生成**：
    # 一次模型调用，得用户说要。
    report: str = ""
    # 那份日报是按几段、什么时候写的。**日报是快照，这一天还在长**：
    # 不带这两个数，用户下午看到的还是上午那份，却没有任何迹象说明它过期了。
    report_segments: int = 0
    report_at: str = ""
    # 那份日报的确定性体检结果（`harness/checks/journey.py`，计划 8.2）。
    # **判了不拦**——跟日报一起落进 `report.json`，刷新之后还在。
    report_notes: list[str] = Field(default_factory=list)


class JourneyReportOut(BaseModel):
    date: str
    report: str = ""
    segments: int = 0
    report_at: str = ""
    # 见 `JourneyDayOut.report_notes`。
    notes: list[str] = Field(default_factory=list)
    took_ms: float = 0.0


class JourneySpanOut(BaseModel):
    date_from: str
    date_to: str
    days: int = 0
    """这段时间里没有日报的那几天——写进笔记正文，读的人得知道它按哪些天写的。"""
    missing: list[str] = Field(default_factory=list)
    note_id: str = ""
    title: str = ""
    took_ms: float = 0.0


class JourneyDenyIn(BaseModel):
    apps: list[str] = Field(default_factory=list)
    words: list[str] = Field(default_factory=list)


class JourneyDenyOut(BaseModel):
    apps: list[str] = Field(default_factory=list)
    words: list[str] = Field(default_factory=list)
    # 内置那份**拆不掉**，只读给界面显示
    builtin_apps: list[str] = Field(default_factory=list)
    builtin_words: list[str] = Field(default_factory=list)


class JourneyRunOut(BaseModel):
    date: str
    described: int = 0
    ingested: int = 0
    skipped: int = 0
    left: int = 0
    removed_facts: int = 0
