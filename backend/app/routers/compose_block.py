"""`/` 唤起的块生成：智能插图 / 智能表格 / 数据可视化 / 智能数据分析 / 按提示词编辑。

**走跟写作 harness 同一套闭环**，不是一次性问模型要一段文本：

    ① 规划：带着工具问模型「要看什么数据、画什么图」——模型可以调
       list_tables / describe_table / aggregate_table / correlate_columns
       （数字由代码算）和 render_chart / render_table（mermaid 语法由代码拼）
    ② 生成：把工具查到的东西喂回去，流式写出要插入的那一块
    ③ 打分：harness.checks.rubric.evaluate() 按这个模式该守的原则打分
    ④ 不达标就带着诊断再来一轮（最多 MAX_ROUNDS 轮）

**为什么数字和图表语法都不让模型出**：让它自己算均值会编，让它自己写
mermaid 会出语法错（用户碰到过"mermaid 语法错误，自动修复也没成功"，那种
错会在笔记里留下一块渲染不出来的死代码）。模型负责判断「该算什么、该画
什么」，这才是它擅长的部分。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from ..harness import tools
from ..util import llm
from ..editor import vision
from ..editor import restructure, textshape
from ..harness import loop, modes
from ..harness.events import legacy_frames
from ..harness.hooks.block import BlockHooks
from ..harness.state import State
from ..editor.profile import entries as _profile
from ..schemas import ComposeBlockIn
from .deps import current_user

router = APIRouter(prefix="/api/compose", tags=["compose"])

def _context_block(content: str, cursor: int, span: int = 900) -> tuple[str, str]:
    """光标前后各截一段。**不是整篇**——整篇塞进去，模型会去接全文的尾巴，
    而不是补这个位置该有的东西；而且每一轮都带全文很快就把上下文撑爆。"""
    cur = max(0, min(cursor, len(content)))
    return content[max(0, cur - span):cur], content[cur:cur + span // 2]


@router.post("/block")
async def compose_block(body: ComposeBlockIn, request: Request,
                        user: str = Depends(current_user)):
    """SSE。事件：phase / tool-calls / delta / evaluate / round-end / done / error

    这个端点本身已经不含循环了——轮次、材料累积、查重、打分、确定性检查、
    取最好的一轮、停机判断全在 ``harness.loop`` 里，三个 harness 共用一份。
    这里只剩三件事：**认模式、装 State、把事件翻成前端现在听的那套名字**。
    """
    mode = modes.BLOCK.get(body.mode)
    if not mode:
        raise HTTPException(
            400, f"不认识的模式 {body.mode!r}，可用：{'、'.join(modes.BLOCK)}")

    async def gen():
        before, after = _context_block(body.content, body.cursor)
        st = State(
            mode=mode,
            ctx=tools.ToolContext(user=user, note_id=body.note_id,
                                  note_title=body.title,
                                  content=body.content, cursor=body.cursor),
            request=request,
            before=before,
            after=after,
        )
        hooks = BlockHooks(prompt=body.prompt, selection=body.selection,
                           profile=_profile(user), title=body.title)
        # 恢复时靠这些重建 hooks（见 routers/harness.py 的 _hooks_for）
        st.bag.update(prompt=body.prompt, selection=body.selection,
                      profile=_profile(user))
        async for event in loop.run(st, hooks):
            for frame in legacy_frames(event):
                yield frame

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- 图片转表格

_TABLE_PROMPT = (
    "看这张图。\n"
    "如果图里有表格（或者任何行列对齐、可以整理成表的数据，比如票据、报表、"
    "统计截图），把它**完整**转成 markdown 表格：第一行是表头，之后每行一条记录，"
    "只输出表格本身，不要任何说明文字。\n"
    "格子里看不清的内容写「?」，**不要猜**。\n"
    "如果图里没有表格也没有可以整理成表的数据，只回四个字：没有表格。"
)


@router.post("/table-from-image")
async def table_from_image(file: UploadFile = File(...),
                           user: str = Depends(current_user)) -> dict:
    """一张图 → markdown 表格。看图走**本地**那台带视觉的模型（见 app/vision.py）。

    识别不出表格时明确返回 ``detected=False``，让前端如实说「没有检测到表格」
    ——比硬编一张空表塞进用户笔记要好得多。
    """
    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > 16 * 1024 * 1024:
        raise HTTPException(400, "图太大了（上限 16MB）")
    mime = (file.content_type or "image/png").split(";")[0].strip()
    if not mime.startswith("image/"):
        raise HTTPException(400, f"这不是图片（{mime}）")
    try:
        out = await vision.ask_image(_TABLE_PROMPT, data, mime)
    except vision.VisionError as exc:
        raise HTTPException(502, str(exc)) from exc

    text = (out or "").strip()
    # 模型有时会用代码块包起来，剥掉再判断
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    rows = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    detected = len(rows) >= 2 and any(set(ln) <= set("|-: ") for ln in rows[1:2])
    if not detected:
        return {"detected": False, "table": "", "raw": text[:300]}
    return {"detected": True, "table": "\n".join(rows), "raw": ""}


# ---------------------------------------------------------------- 智能排版

_RESTRUCTURE_SYSTEM = """你在帮用户整理一篇笔记的**结构**。

判断哪一行应该是标题、哪几行应该是列表、哪一行是引用——这是规则算不出来的
语义判断，正是要你做的事。

**你不输出任何正文。** 只输出一组操作，告诉系统「第几行改成什么结构」，
原文由系统按行搬运。

输出一个 JSON 数组，每项是下面之一：
  {"op":"heading","line":3,"level":2}       第 3 行提升为二级标题
  {"op":"list","line":5,"indent":0}         第 5 行改成列表项（indent 是嵌套层级）
  {"op":"ordered","line":5}                 改成有序列表项（编号系统会重排）
  {"op":"quote","line":9}                   改成引用
  {"op":"paragraph","line":9}               降级成普通段落
  {"op":"split","line":12}                  第 12 行里塞着（1）（2）（3）这样的显式序号，
                                            拆成列表（拆点由系统按序号找，你只说拆哪行）
  {"op":"insert_heading","before":1,"level":2,"text":"众筹节奏"}
                                            在第 1 行前插一个新标题

规矩：
· 不需要改的行**不要出现在操作里**。没什么可改就输出 []。
· **一行里塞着三个以上「（1）（2）（3）」这类并列条目时，用 split 把它拆开**
  ——这是长文档里最值得改的地方，一大段话读不出并列关系。
· insert_heading 是唯一能新增文字的地方，标题要短（40 字以内）、
  必须概括它下面那段真实写了什么，不许写成一句新观点。
· 标记为「代码块内」「代码块边界」的行、以及表格行，一律不要动。
· 只输出 JSON 数组本身，不要任何解释。"""


@router.post("/restructure")
async def restructure_note(body: ComposeBlockIn, user: str = Depends(current_user)) -> dict:
    """智能排版：模型只决定结构，原文由代码搬运。

    跟一键格式化（前端 editor/format.ts，纯规则）是互补的两件事：
    规则那套只能把**已经标好**的结构规范化，判断「这行应该是标题」是语义判断。

    **模型一个字的原文都不输出**（见 app/restructure.py），所以"排版顺手改了
    内容"在结构上就不可能发生。最后仍然跑一次 content_drift 断言兜底——
    真出现漂移说明操作层有 bug，那要修代码，不是靠提示词。
    """
    src = body.content or ""
    if not src.strip():
        raise HTTPException(400, "正文是空的")
    try:
        text = await llm.complete(
            [{"role": "system", "content": _RESTRUCTURE_SYSTEM},
             {"role": "user", "content": restructure.numbered(src)}],
            max_tokens=1500, temperature=0.1)
    except Exception as exc:                       # noqa: BLE001
        raise HTTPException(502, f"排版调用失败：{exc}") from exc

    ops = llm.extract_json(text)
    if not isinstance(ops, list):
        return {"changed": False, "content": src, "ops": 0, "skipped": [],
                "detail": "模型没有给出有效的操作列表"}
    out, skipped = restructure.apply_ops(src, ops)
    drift = textshape.content_drift(src, out)
    if drift:
        # 到这一步还漂移 = 操作层有 bug（模型只给了操作，正文是代码搬的）。
        # 宁可什么都不改，也不能把用户的内容改掉。
        return {"changed": False, "content": src, "ops": 0,
                "skipped": skipped + ["内容发生了变化，已放弃这次排版"],
                "detail": drift[:200]}
    return {"changed": out != src, "content": out, "ops": len(ops),
            "skipped": skipped, "detail": ""}
