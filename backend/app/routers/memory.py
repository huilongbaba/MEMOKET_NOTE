"""记忆检索与调试。检索路径零 LLM 调用，亚毫秒返回。"""

import time

from fastapi import APIRouter, Depends, HTTPException

from ..database import store
from ..database.kite.kite_memory import UserMemory
from .schemas import AskIn, AskOut, CitingNoteOut, FactPeekOut, TraceIn, EntityOut, FactDetailOut, FactOut, FactsPageOut, RecallIn, RecallOut, SourceLineOut, StatsOut, TimelineBucket, TimelineOut, TopicCreateIn, TopicEntityLink, TopicOut
from .deps import current_user

router = APIRouter(prefix="/api/memory", tags=["memory"])


def rows_to_facts(mem: UserMemory, rows: list[dict]) -> list[FactOut]:
    out = []
    for r in rows:
        out.append(FactOut(
            id=r.get("id", ""),
            text=r.get("text", ""),
            when=r.get("date", ""),
            kind=r.get("kind", ""),
            sources=mem.source_lines(r),
        ))
    return out


@router.post("/recall", response_model=RecallOut)
def recall(body: RecallIn, user: str = Depends(current_user)):
    mem = UserMemory(user)
    rows, terms, took = mem.recall(body.query, limit=body.limit)
    return RecallOut(facts=rows_to_facts(mem, rows), took_ms=round(took, 3),
                     terms=terms)


@router.get("/stats", response_model=StatsOut)
def stats(user: str = Depends(current_user)):
    return UserMemory(user).stats()


# ---------------------------------------------------------------- 可视化（结构化浏览）

@router.get("/topics", response_model=list[TopicOut])
def topics(user: str = Depends(current_user)):
    """topic 树。parents 构成层级，前端自己拼——不同 topic 可能有多个 parent。"""
    return UserMemory(user).topics()


@router.post("/topics", response_model=TopicOut)
def create_topic(body: TopicCreateIn, user: str = Depends(current_user)):
    """手动新建主题——主题地图里"新建主题"用，直接落 canonical。"""
    try:
        return UserMemory(user).add_topic(body.code, parent=body.parent, aliases=body.aliases)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/entities", response_model=list[EntityOut])
def entities(user: str = Depends(current_user)):
    """实体列表，前端按 type 分组展示。"""
    return UserMemory(user).entities()


@router.get("/topic-entity-links", response_model=list[TopicEntityLink])
def topic_entity_links(user: str = Depends(current_user)):
    """topic 和 entity 没有直接 schema 关联，只在同一条 fact 上共现——这里把
    共现次数聚合成边，主题地图用它把两类节点连起来。"""
    return UserMemory(user).topic_entity_links()


@router.get("/facts", response_model=FactsPageOut)
def facts(kind: str = "", who: str = "", topic: str = "", entity: str = "",
          conf_min: str = "", limit: int = 20, offset: int = 0,
          user: str = Depends(current_user)):
    """事实表：分页 + 过滤。topic 过滤含子主题闭包，跟 /recall 语义一致。"""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    rows, total = UserMemory(user).facts_page(
        kind=kind, who=who, topic=topic, entity=entity, conf_min=conf_min,
        limit=limit, offset=offset)
    return FactsPageOut(facts=[FactDetailOut(**r) for r in rows], total=total,
                        limit=limit, offset=offset)


PEEK_SOURCE_CHARS = 220
"""浮层里每条原话最多显示多少字。见 fact_peek 里的注释。"""


def _clip(s: str) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= PEEK_SOURCE_CHARS else s[:PEEK_SOURCE_CHARS] + "…"


@router.get("/facts/{fact_id}", response_model=FactPeekOut)
def fact_peek(fact_id: str, user: str = Depends(current_user)):
    """一条事实 + 它的原话。**行内出处浮层**用这个。

    判据 2（docs/product-north-star.md）：为了看一条旧记录而离开当前页面
    就是失败。正文里的 `[terrence-1872-5F8]` 悬停就能看到原文和出处行——
    代价是「移开鼠标」，而不是跳走再回来时丢掉的那条思路。

    也直接对着痛点 13：汇总零散笔记时「有些事实好像也不对」。事实旁边就是
    它的原话，对不对当场看得见，不用相信模型。

    **找不到要明确 404**，不能回一个空壳：一条指向不存在事实的引用是个真
    问题（模型编的、或者知识库重建过），静默当成没事等于把它藏起来。
    """
    mem = UserMemory(user)
    fact = mem.fact_by_id(fact_id)
    if not fact:
        raise HTTPException(404, f"没有这条记录：{fact_id}")
    return FactPeekOut(
        id=fact_id, text=fact.get("text", ""), when=fact.get("when", ""),
        kind=fact.get("kind", ""),
        # **每条原话截断。** 实拍发现一条会议记录原文能有几千字，浮层直接
        # 占了半屏、把正文盖住——那反而违背了判据 2（不打断当前这一页）。
        # 浮层是「扫一眼确认对不对」，不是阅读器；要看全文走知识库那一栏。
        sources=[_clip(s["text"] if isinstance(s, dict) else str(s))
                 for s in mem.fact_sources(fact_id)][:3],
    )


@router.get("/facts/{fact_id}/citing", response_model=list[CitingNoteOut])
def citing_notes(fact_id: str, user: str = Depends(current_user)):
    """**哪些笔记引用了这条事实。** 反查——整个「笔记 × 知识库」融合的关键。

    回答的是一个真问题：这条事实还活着吗、改了它会影响谁。没有反查，知识库
    就是个只进不出的仓库。对标 Trilium 右栏的 Backlinks。

    设计见 `docs/kb-fusion-design.md`。
    """
    return store.notes_citing(user, fact_id)


@router.get("/facts/{fact_id}/sources", response_model=list[SourceLineOut])
def fact_sources(fact_id: str, user: str = Depends(current_user)):
    """证据回溯：fact -> 原始对话行。事实表展开一条时按需调用。"""
    return UserMemory(user).fact_sources(fact_id)


@router.get("/timeline", response_model=TimelineOut)
def timeline(user: str = Depends(current_user)):
    """按日期聚合的 session 数 / fact 数，体现入库节奏。"""
    return TimelineOut(buckets=[TimelineBucket(**b) for b in UserMemory(user).timeline()])


@router.post("/trace", response_model=AskOut)
def trace(body: TraceIn, user: str = Depends(current_user)):
    """**来龙去脉**：给一段正文，回它涉及的事情按时间怎么演进的。

    这是 `ask` 那条能力的**封装**，也是它现在唯一的对外入口。判据 1
    （docs/product-north-star.md）：

      > 所有「AI 协助」的功能封装成一个按钮，按钮能完成用户预期的功能执行，
      > 无需再反复和 AI 交互。
      > **界面上出现聊天输入框，就是我们没把意图封装好。**

    所以问题**由这里拼**，用户一个字都不写——他只是选中了一段，然后点了
    「来龙去脉」。

    对应的是痛点 13：把零散笔记汇总时「AI 根本捋不清楚时间线」。KITE 的
    planning 恰好擅长时序，之前却藏在一个要用户自己想怎么问的输入框后面。
    """
    passage = body.passage.strip()
    if not passage:
        raise HTTPException(400, "没有选中内容")
    # 太长的选区对时序检索没有帮助，反而会把主语淹掉——取前后各一段。
    head = passage[:400]
    question = (f"围绕下面这段内容涉及的事情，按时间顺序说明它是怎么演进的，"
                f"每条都要带上日期：\n\n{head}")
    t0 = time.perf_counter()
    text, facts = UserMemory(user).ask(question, limit=body.limit)
    return AskOut(
        answer=text,
        facts=[FactOut(id=f["id"], text=f["text"], when=f["date"],
                       kind=f["kind"], sources=f["sources"]) for f in facts],
        took_ms=round((time.perf_counter() - t0) * 1000, 1),
    )


@router.post("/ask", response_model=AskOut, include_in_schema=False)
def ask(body: AskIn, user: str = Depends(current_user)):
    """自由提问。**不再有对外的入口**——留着是因为 /trace 和以后别的封装
    动作都建在它上面，而它自己那个「用户自己想怎么问」的交互正是判据 1 要
    消灭的东西（见 /trace 的注释）。

    同步 def —— FastAPI 会丢到线程池，不阻塞事件循环。

    注意这个接口很慢（本地模型上约 40-50s），前端要给明确的等待反馈。
    写作路径请用 /recall，那条是零 LLM 的。
    """
    t0 = time.perf_counter()
    text, facts = UserMemory(user).ask(body.question, limit=body.limit)
    return AskOut(
        answer=text,
        facts=[FactOut(id=f["id"], text=f["text"], when=f["date"],
                       kind=f["kind"], sources=f["sources"]) for f in facts],
        took_ms=round((time.perf_counter() - t0) * 1000, 1),
    )
