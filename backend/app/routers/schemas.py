"""请求/响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- 笔记

class NoteIn(BaseModel):
    title: str = ""
    content: str = ""


class Note(BaseModel):
    id: str
    user_id: str
    title: str
    content: str
    pinned: bool = False
    # 写作骨架跟着笔记走。之前只活在前端内存里，换一篇/刷新/无限续写自动
    # 跟随切页，骨架就没了——而 harness 每轮都要拿它当主线依据。
    spine: str = ""
    beats: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ComposeBlockIn(BaseModel):
    """`/` 唤起的块生成。cursor 是光标在正文里的字符位置——只取它前后一段
    当上下文，不是整篇（整篇会让模型去接全文的尾巴，而不是补这个位置）。"""

    note_id: str = ""
    title: str = ""
    content: str = ""
    cursor: int = 0
    mode: str = "prompt"
    prompt: str = ""
    # 用户选中的那段。给了就是「对这段做点什么」（右键 → 自定义提示），
    # 没给就是「在光标这里插一块」（`/` 唤起）。同一套 harness，差的是作用域。
    selection: str = ""


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
    pinned: bool = False
    updated_at: str
    child_count: int = 0
    # 这篇笔记一共有几条 branch。>1 就是克隆，树上要标出来——用户得知道
    # 改这一处会让别处跟着变。
    branch_count: int = 1


class NoteCreateIn(BaseModel):
    title: str = ""
    content: str = ""
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


class BranchExpandIn(BaseModel):
    note_id: str
    parent_note_id: str
    expanded: bool


# ---------------------------------------------------------------- 无限续写计划

class WritingPlanStartIn(BaseModel):
    parent_note_id: str
    goal: str = ""


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
    max_rounds: int = 20
    # 每轮写完停下来等用户逐条接受/拒绝。**是用户的选择，不是功能的属性**
    # ——同一个人在重要文档上想要、在草稿上不想要。
    review_each_round: bool = False


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
    provider: str  # "local" | "gpt"
    gpt_api_key: str | None = None  # 不传就保留原值，见 store.set_provider_config
    gpt_model: str | None = None
    gpt_base_url: str | None = None


class ProviderConfigOut(BaseModel):
    provider: str
    gpt_model: str
    gpt_base_url: str
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


class SourceLineOut(BaseModel):
    id: str
    unit: str
    date: str = ""
    who: str = ""
    text: str


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
    unit: str = ""


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


class RecallOut(BaseModel):
    facts: list[FactOut]
    took_ms: float
    terms: list[str] = Field(default_factory=list)


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


# job 的合法状态。"cancelling" = 收到取消但后台还没停干净（可能卡在一次 LLM
# 调用或 KITE 写锁里），界面要如实说「正在停止」而不是「处理中」。
JOB_STATUSES = ("queued", "running", "cancelling", "done", "error", "cancelled")


class IngestOut(BaseModel):
    job_id: str
    # 同 IngestItemOut.status：**出参用 str 不用 Literal**。一个不在枚举里的
    # 状态会让整个接口 500，界面卡在「处理中」、点取消没反应——这个坑今晚踩了
    # 两次（item 一次、job 一次），所以两处都改成写入侧白名单 + 测试来管。
    status: str
    facts: int = 0
    detail: str = ""
    items: list[IngestItemOut] = Field(default_factory=list)


# ---------------------------------------------------------------- 写作

class SkeletonIn(BaseModel):
    """线 1：为当前写作内容生成主线骨架。"""
    content: str
    title: str = ""


class SkeletonOut(BaseModel):
    """spine：一句话，这篇东西真正在处理的核心张力/问题——不是主题。
    beats：3-6 条结构性/修辞性功能（"建立处境""引入转折"），不是内容摘要。
    见 prompts.py 的 SKELETON_SYSTEM。"""
    spine: str = ""
    beats: list[str] = Field(default_factory=list)
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


class MagicTapIn(BaseModel):
    content: str
    spine: str = ""
    beats: list[str] = Field(default_factory=list)
    max_tokens: int = 1200


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


class ExpandIn(BaseModel):
    content: str
    selection: str


class VerifyIn(BaseModel):
    content: str
    selection: str


class VerifyFinding(BaseModel):
    verdict: Literal["矛盾", "支持", "无法判断"]
    reason: str
    fact_id: str = ""
    fact_text: str = ""
    sources: list[str] = Field(default_factory=list)


class VerifyOut(BaseModel):
    findings: list[VerifyFinding]
    took_ms: float


class DigestIn(BaseModel):
    """按日期范围（或最近 N 天）生成阶段回顾。不给 date_from/date_to 时按 days 算。"""
    days: int = 7
    date_from: str = ""
    date_to: str = ""


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
