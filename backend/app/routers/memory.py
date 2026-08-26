"""记忆检索与调试。检索路径零 LLM 调用，亚毫秒返回。"""

import time

from fastapi import APIRouter, Depends

from ..kite_memory import UserMemory
from ..schemas import AskIn, AskOut, FactOut, RecallIn, RecallOut
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


@router.get("/stats")
def stats(user: str = Depends(current_user)):
    return UserMemory(user).stats()


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
