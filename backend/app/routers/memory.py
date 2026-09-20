"""记忆检索与调试。检索路径零 LLM 调用，亚毫秒返回。"""

import re
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..database import store
from ..database.kb import pages
from ..database.kb import relations as kb_relations
from ..database.kb import search
from memoket_kite.errors import ProviderError

from ..database.kite.kite_memory import ProviderFailed, UserMemory
from ..harness import prompts
from ..util import llm
from .schemas import AskIn, AskOut, CitingNoteOut, FactPeekOut, TraceIn, EntityOut, FactDetailOut, FactOut, FactsPageOut, RecallIn, RecallOut, SourceLineOut, StatsOut, TimelineBucket, TimelineOut, TopicCreateIn, TopicEntityLink, TopicOut
from .deps import current_user

# 关系卡上那句话的长度上限——代码判出来的本来就短，模型改写的那版没准绳
RELATION_SAY_MAX = 120

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
    # `evidence=True`：这条路是**拿给用户看的那一列**（右栏「记忆」/ ⌘K / 知识库搜索框），
    # 每一条都得说得出「为什么给我看这条」——说不出就别送上去（P32 #1）。
    # 喂给 `kb/relations.detect` 的那两条路（下面 `/relations`、`/relations/batch`）**故意不开**，
    # 理由写在 `UserMemory.recall` 的文档串里（开了会掉一个从 P22 就在的绿点）。
    rows, terms, took = mem.recall(body.query, limit=body.limit, scope=body.scope,
                                   evidence=True)
    # 空着的时候说清楚为什么（P4 #6）：是这段没有可查的词，还是有词但没有一条记录同时命中两个——
    # 右栏据此写「这段没有可查的关键词」，而不是「暂时没有找到相关内容」一句话糊过去。
    why = ""
    if not rows:
        try:
            why = "no_terms" if not search._terms(mem, search.clean_query(body.query)) else "weak"
        except Exception:      # noqa: BLE001 — 解释是附赠的
            why = ""
    try:
        ev = mem.recall_evidence(body.query, rows) if rows else []
    except Exception:          # noqa: BLE001 — 解释是附赠的，别让它挡住召回本身
        ev = []
    return RecallOut(facts=rows_to_facts(mem, rows), took_ms=round(took, 3),
                     # 给人看的是整词，不是「小时预」「号上众」这种切碎的 n-gram（P4 #6）
                     terms=search.display_terms(terms, body.query), kb_empty=mem.is_empty(),
                     evidence=ev, why_empty=why)


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
    mem = UserMemory(user)
    rows, total = mem.facts_page(
        kind=kind, who=who, topic=topic, entity=entity, conf_min=conf_min,
        limit=limit, offset=offset)
    pages.annotate(mem, rows)
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
    store_, vocab = mem._index()
    from ..database.kb import entities as entities_mod
    groups = entities_mod.for_store(store_, vocab)
    return FactPeekOut(
        id=fact_id, text=fact.get("text", ""), when=fact.get("when", ""),
        kind=fact.get("kind", ""),
        topics=list(fact.get("topics") or []), entities=list(fact.get("entities") or []),
        entity_names=[groups.name(c) for c in fact.get("entities") or []],
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


class _RelationsIn(TraceIn):
    confirm: bool = True
    scope: str = "all"


def _has_facts(mem: UserMemory) -> bool:
    """知识库是空的就不判关系：空库时每一段带数字的都会是「缺依据」，满页灰点全是噪音
    （第 131 轮实拍 412 篇零事实的用户）。"""
    try:
        return mem.stats()["facts"] > 0
    except Exception:      # noqa: BLE001 — 索引读不出来就当没有
        return False


def _live(mem: UserMemory, rows: list[dict]) -> list[dict]:
    """被取代 / 合并掉的记录不参与关系判断——「合并结果记住，下次不再问」。"""
    gone = mem.fact_attrs("superseded_by")
    return [r for r in rows if r["id"] not in gone]


@router.post("/relations")
async def relations(body: _RelationsIn, user: str = Depends(current_user)) -> dict:
    """一段正文跟知识库是什么关系：冲突 / 延续 / 印证 / 缺依据（docs/agent-native-editor.md
    §3.3.1）。候选是代码判的（毫秒级、零 LLM）；只有冲突候选才让模型确认一遍、写一句人话。"""
    passage = body.passage.strip()
    if not passage:
        return {"relations": [], "took_ms": 0.0}
    t0 = time.perf_counter()
    mem = UserMemory(user)
    if not _has_facts(mem):
        return {"relations": [], "took_ms": round((time.perf_counter() - t0) * 1000, 1)}
    rows, _terms, _took = mem.recall(passage, limit=8, scope=body.scope)
    rows = _live(mem, rows)
    cands = kb_relations.detect(passage, rows, common=mem.common_term())
    by_id = {r["id"]: r for r in rows}
    if body.confirm and any(c["relation"] == "conflict" for c in cands):
        try:
            verdict = await llm.complete_json(
                [{"role": "system", "content": prompts.RELATIONS_SYSTEM},
                 {"role": "user", "content": prompts.relations_user(passage, cands, by_id)}],
                max_tokens=600, temperature=0.1)
            if isinstance(verdict, list):
                keep = {}
                for v in verdict:
                    if isinstance(v, dict) and isinstance(v.get("index"), int):
                        keep[v["index"]] = v
                # 模型改写的那句话直接显示在右栏关系卡上：封顶 120 字，别把卡片撑成一屏（第 577 轮）
                cands = [dict(c, say=" ".join(str(keep[i].get("say") or c["say"]).split())[:RELATION_SAY_MAX])
                         for i, c in enumerate(cands)
                         if i not in keep or keep[i].get("keep", True)]
        except Exception:      # noqa: BLE001 — 模型不在就用代码判的那句
            pass
    facts = rows_to_facts(mem, rows)
    fmap = {f.id: f for f in facts}
    return {
        "relations": [dict(c, facts=[fmap[i].model_dump() for i in c.get("fact_ids", []) if i in fmap]) for c in cands],
        "took_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


class _RelationsBatchIn(BaseModel):
    passages: list[str]
    scope: str = "all"


@router.post("/relations/batch")
def relations_batch(body: _RelationsBatchIn, user: str = Depends(current_user)) -> dict:
    """页边圆点用：一批段落各自跟知识库是什么关系，只要代码判的候选（零 LLM，每段几毫秒），
    每段只回最要紧的一条。最多 80 段。"""
    mem = UserMemory(user)
    t0 = time.perf_counter()
    if not _has_facts(mem):
        return {"marks": [None] * len(body.passages[:80]), "took_ms": 0.0}
    # 一批段落共用同一个判据对象（里头那份 df 是按词 memo 的，80 段之间大量重复）
    common = mem.common_term()
    out = []
    for p in body.passages[:80]:
        p = (p or "").strip()
        if len(p) < 8 or not any(ch.isdigit() for ch in p):
            out.append(None)
            continue
        rows, _terms, _took = mem.recall(p, limit=8, scope=body.scope)
        cands = kb_relations.detect(p, _live(mem, rows), common=common)
        # 一段只画一个点，画最要紧的——`detect()` 收尾已经按 冲突 > 延续 > 缺依据 >
        # 叠加 > 合并 > 印证 排好，`cands[0]` 就是它（P1-1d 核过，有闸钉着这个顺序）。
        # `kinds` 是这段一共判出几种关系，悬停时告诉用户「点开还有别的」。
        top = cands[0] if cands else None
        if not top:
            out.append(None)
            continue
        # P9（§3.3 边缘记忆）：圆点旁边的卡要能直接说「上次记的是 6/3」——把那几条事实（id / 原话 / 日期）
        # 一起带回去，前端不用再为每个点发一次 /relations。rows 已经在手里，零额外查询。
        by_id = {r["id"]: r for r in rows}
        facts = [f.model_dump() for f in rows_to_facts(mem, [by_id[i] for i in top["fact_ids"] if i in by_id])]
        # `why`（P25 #4）：「缺依据」分 `no_record`（库里连沾边的都没有）/ `no_value`
        # （沾边但那条记录没带这段的量）两档，前端据此决定页边画不画点——理由在
        # `kb/relations.detect()` 收尾那段注释里。别的关系没有这一栏。
        out.append({"relation": top["relation"], "say": top["say"], "fact_ids": top["fact_ids"],
                    "kinds": len({c["relation"] for c in cands}), "facts": facts,
                    **({"why": top["why"]} if top.get("why") else {})})
    return {"marks": out, "took_ms": round((time.perf_counter() - t0) * 1000, 1)}


_NO_INFO = re.compile(r"^\s*(no|not enough|insufficient)\s+information\b.*$", re.I | re.S)


# 「一条都没召回」那句话要说之前，先用**词法召回**核一遍——用跟「校验」一样的 limit
# （`compose.verify` 那条 `mem.recall(..., limit=6)`）。两块面板报的数出自同一把尺子，
# 才不会再出现 P40 那一屏：一边说「知识库里有 6 条」，一边说「没有跟这段沾边的记录」。
TRACE_RECALL_LIMIT = 6


def _no_info_to_chinese(text: str, has_facts: bool = True, recalled: int | None = None) -> str:
    """KITE 的拒答是英文一句「No information」（第 156 轮实拍：右栏「脉络」顶着一行英文，下面却列着
    10 条召回的记录）。换成中文、并说清楚下面那几条是什么；一条都没召回就别说「下面几条」。

    **「KITE 那条检索没回东西」≠「知识库里没有」**（P41 #1 / P40 问题 #1）。
    P40 实拍：同一屏上「校验」对同一段话说「知识库里有 6 条相关记录」，而这里说
    「知识库里没有跟这段沾边的记录。」——**两块面板互相打架，前一句是假的**。
    根因：`has_facts` 数的是 **KITE 自己那条 planning 检索**回了几条，
    而这句话说的是「知识库里有没有」。跟 P9 #26 / P37 #2 是同一个形状，只是换了一块面板。

    所以照 `VerifyOut` 那条思路**多带一格**：`recalled` = 同一段话的**词法召回**回了几条
    （`None` = 这一趟没量，退回原来那句，老调用方对得上）。三档：

    * `has_facts` —— KITE 串出了东西，原样那句。
    * `recalled` 有数 —— **说自己的话**：这一步没串出时间线，但库里有 N 条沾边的。
    * `recalled == 0` —— 真的一条都没有。原来那句话**在这一档才是对的**。
    """
    if _NO_INFO.match(text or ""):
        if has_facts:
            return "知识库里的记录串不出这件事的来龙去脉——下面是最相关的几条，可能只是沾边。"
        if recalled:
            return (f"按这段话没能串出一条时间线——知识库里有 {recalled} 条沾边的记录，"
                    f"只是这一步没能把它们排成先后。")
        return "知识库里没有跟这段沾边的记录。"
    return text


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
    mem = UserMemory(user)
    if not _has_facts(mem):
        # 空库：KITE 的 ask() 照样会花一次规划调用（实拍 12 秒）然后答「No information」
        return AskOut(answer="知识库还是空的——先导入一些记录，或者把写好的笔记「存入知识库」。",
                      facts=[], recalled=0,
                      took_ms=round((time.perf_counter() - t0) * 1000, 1))
    try:
        text, facts = mem.ask(question, limit=body.limit)
    except ProviderError as exc:
        # **「答得不合形状」≠「没应答」**（P37 #3 / P35 #4）。
        #
        # KITE 的 `providers/llm.llm_json` 在模型答的里面找不到 JSON 时抛
        # `ProviderError("no JSON in llm output: …")`。这条原来**没人接**，500 原样透出去，
        # 前端 `friendlyError` 把 5xx 一律翻成「后端处理出错（多半是模型没应答）——看一眼
        # 设置里的 LLM 供应商」并挂一个「打开设置」。P35 实拍：模型明明答了（200 + 一段字），
        # 供应商也是通的，而界面把人指去改模型地址 / key ——**指错地方比不说更糟**
        # （P26 那条「探针把好的说成坏的」同一形状；P3 那条「后端没起来 ≠ 模型连不上」升一层）。
        #
        # 判据**故意窄**：只认 `no JSON in llm output` 这一句。别的 ProviderError
        # （连不上 / 超时 / 401）本来就是「模型侧出了事」，照旧透出去，
        # 「打开设置」对它们是对的出口。
        if "no JSON" not in str(exc):
            raise
        # 502 + **一句中文**：`friendlyError` 见到状态码后面是中文就原样给，
        # 而这句话不以「模型连不上 / 后端处理出错 / 模型服务」开头，
        # `isLlmUnreachable` 因此是 false ——**不带「打开设置」**。
        raise HTTPException(
            502, "模型答的不是这个动作要的格式（不是没应答，供应商是通的）"
                 "——换个模型，或者再试一次") from exc
    except ProviderFailed as exc:
        # P9：模型出错要说出错，不能翻成「知识库里没有沾边的记录」（那是 KITE 回退出来的假答案）
        raise HTTPException(502, f"来龙去脉没查成：{exc}（{store.get_active_llm_config()['base_url']}）——去设置里看一眼 LLM 供应商") from exc
    # **KITE 一条都没串出来的时候，先去问一遍词法召回**（P41 #1）：零模型、几毫秒，
    # 而它正是「校验」和右栏「记忆」用的那条路。串出东西的那一档不量——那时候
    # 没有第二块面板可以打架，多花的每一次查询都是白花的。
    recalled = None if facts else len(mem.recall(passage, limit=TRACE_RECALL_LIMIT)[0])
    text = _no_info_to_chinese(text, bool(facts), recalled)
    return AskOut(
        answer=text,
        facts=[FactOut(id=f["id"], text=f["text"], when=f["date"],
                       kind=f["kind"], sources=f["sources"]) for f in facts],
        recalled=recalled,
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
