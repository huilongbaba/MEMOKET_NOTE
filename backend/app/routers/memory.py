"""记忆检索与调试。检索路径零 LLM 调用，亚毫秒返回。"""

import time

from fastapi import APIRouter, Depends, HTTPException

from ..database.kite.kite_memory import UserMemory
from .schemas import AskIn, AskOut, EntityOut, FactDetailOut, FactOut, FactsPageOut, RecallIn, RecallOut, SourceLineOut, StatsOut, TimelineBucket, TimelineOut, TopicCreateIn, TopicEntityLink, TopicOut
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


@router.get("/facts/{fact_id}/sources", response_model=list[SourceLineOut])
def fact_sources(fact_id: str, user: str = Depends(current_user)):
    """证据回溯：fact -> 原始对话行。事实表展开一条时按需调用。"""
    return UserMemory(user).fact_sources(fact_id)


@router.get("/timeline", response_model=TimelineOut)
def timeline(user: str = Depends(current_user)):
    """按日期聚合的 session 数 / fact 数，体现入库节奏。"""
    return TimelineOut(buckets=[TimelineBucket(**b) for b in UserMemory(user).timeline()])


@router.post("/ask", response_model=AskOut)
def ask(body: AskIn, user: str = Depends(current_user)):
    """显式提问。同步 def —— FastAPI 会丢到线程池，不阻塞事件循环。

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
