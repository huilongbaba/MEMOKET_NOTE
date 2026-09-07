"""入库：文档 / 语音 -> 知识库。

抽取事实要调 LLM（本地 30B 上约 13s/段），所以一律丢后台任务，接口立刻返回
job_id，前端轮询 /api/ingest/jobs/{id} 看进度。
"""

from __future__ import annotations

import asyncio
import json
import re
import hashlib
import uuid
from datetime import date as _date

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .. import asr, extract, store
from ..kite_memory import UserMemory
from ..schemas import IngestItemOut, IngestOut, IngestTextIn
from .deps import current_user

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

# 一次抽取喂给 LLM 的字符上限，太长会拖垮抽取质量和耗时
CHUNK_CHARS = 1200

# 一个批量任务最多接受多少文件，避免一次请求把后台任务队列堵成小时级
BATCH_MAX_FILES = 50


def _chunks(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """按段落切块，尽量不在句子中间断开。"""
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    out: list[str] = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 1 > size and buf:
            out.append(buf)
            buf = p
        else:
            buf = f"{buf}\n{p}" if buf else p
    if buf:
        out.append(buf)
    return out or ([text] if text.strip() else [])


def _markdown_sections(text: str) -> list[str]:
    """按标题行切段，让每个 chunk 尽量落在同一个标题层级下。"""
    sections: list[str] = []
    buf: list[str] = []
    for line in text.split("\n"):
        if re.match(r"^#{1,6}\s", line) and buf:
            sections.append("\n".join(buf).strip())
            buf = [line]
        else:
            buf.append(line)
    if buf:
        sections.append("\n".join(buf).strip())
    return [s for s in sections if s.strip()]


def _chunks_for(text: str, kind: str, size: int = CHUNK_CHARS) -> list[str]:
    if kind == "md":
        out: list[str] = []
        for section in _markdown_sections(text):
            out.extend(_chunks(section, size))
        return out or _chunks(text, size)
    return _chunks(text, size)


def _ingest_job(job_id: str, user_id: str, text: str, title: str, source: str,
                date: str = "", source_id: str = "") -> None:
    store.set_job(job_id, "running")
    try:
        mem = UserMemory(user_id)
        total = 0
        # 有稳定 source_id 就用它拼 session_id：KITE 拒绝重复的 session_id
        # 且不花 LLM 调用，于是重跑导入自动变成增量同步。没有就退回随机 id
        # （手工粘贴一段文字这种场景，本来也没有可稳定的标识）。
        stem = f"{source}-{source_id}" if source_id else f"{source}-{uuid.uuid4().hex[:8]}"
        when = date or _date.today().isoformat()
        for i, chunk in enumerate(_chunks(text)):
            total += mem.remember(
                [{"role": "user", "content": chunk}],
                session_id=f"{stem}-{i}",
                date=when,
                title=title,
            )
            # 每个 chunk 单独一次 LLM 调用（~13s），落一次库让前端轮询能看见
            # facts 数逐块往上涨，而不是等全部 chunk 跑完才一次性跳到最终值。
            store.set_job(job_id, "running", facts=total)
        store.set_job(job_id, "done", facts=total)
    except Exception as exc:  # 后台任务的异常必须落库，否则前端只看到永远 running
        store.set_job(job_id, "error", detail=f"{type(exc).__name__}: {exc}")


@router.post("/text", response_model=IngestOut)
def ingest_text(body: IngestTextIn, bg: BackgroundTasks,
                user: str = Depends(current_user)):
    if not body.content.strip():
        raise HTTPException(400, "content is empty")
    job_id = store.create_job(user)
    bg.add_task(_ingest_job, job_id, user, body.content, body.title, body.source,
                body.date, body.source_id)
    return IngestOut(job_id=job_id, status="queued")


@router.post("/audio", response_model=IngestOut)
async def ingest_audio(bg: BackgroundTasks,
                       file: UploadFile = File(...),
                       language: str = Form("auto"),
                       title: str = Form(""),
                       user: str = Depends(current_user)):
    """语音 -> Whisper 转写 -> 后台抽取入库。转写是同步的（RTF 50x+，很快）。"""
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty audio")
    try:
        text = await asr.transcribe(data, filename=file.filename or "audio.wav",
                                    language=language)
    except Exception as exc:
        raise HTTPException(502, f"transcription failed: {exc}") from exc
    if not text:
        return IngestOut(job_id="", status="done", facts=0,
                         detail="转写结果为空，可能是静音音频")

    job_id = store.create_job(user)
    bg.add_task(_ingest_job, job_id, user, text, title or (file.filename or ""),
                "audio")
    return IngestOut(job_id=job_id, status="queued", detail=text[:2000])


@router.post("/transcribe")
async def transcribe_only(file: UploadFile = File(...),
                          language: str = Form("auto")):
    """只转写不入库 —— 编辑器里「语音输入」直接把文字插到光标处。"""
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty audio")
    try:
        text = await asr.transcribe(data, filename=file.filename or "audio.wav",
                                    language=language)
    except Exception as exc:
        raise HTTPException(502, f"transcription failed: {exc}") from exc
    return {"text": text}


# ---------------------------------------------------------------- 批量导入
#
# item 状态机：queued -> extracting -> [transcribing](仅音频) -> chunking
#            -> remembering -> done | failed | cancelled
#
# 一个 job 内的文件顺序处理（不并发）：批量导入本质是小时级后台任务
# （13s/chunk，见 docs/PLAN.md），顺序执行让取消语义简单——「取消」就是
# 不再处理还没轮到的文件，已经在 remembering 的那个跑完即可。


def _extract_item_text(filename: str, kind: str, data: bytes, language: str) -> str:
    if kind == "audio":
        return asyncio.run(asr.transcribe(data, filename=filename, language=language))
    return extract.extract_text(data, filename)


def _batch_job(job_id: str, user_id: str, items: list[dict],
               payloads: dict[str, bytes], language: str) -> None:
    store.set_job(job_id, "running")
    mem = UserMemory(user_id)
    for item in items:
        item_id, filename, kind = item["id"], item["filename"], item["kind"]
        if store.is_cancel_requested(job_id):
            store.set_item(item_id, "cancelled")
            store.update_job_from_items(job_id)
            continue
        try:
            store.set_item(item_id, "transcribing" if kind == "audio" else "extracting")
            text = _extract_item_text(filename, kind, payloads[item_id], language)
            store.update_job_from_items(job_id)

            if not text or not text.strip():
                store.set_item(item_id, "done", facts=0, detail="内容为空")
                store.update_job_from_items(job_id)
                continue

            store.set_item(item_id, "chunking")
            store.update_job_from_items(job_id)
            chunks = _chunks_for(text, kind)
            file_date = _date.today().isoformat()

            store.set_item(item_id, "remembering")
            store.update_job_from_items(job_id)
            total = 0
            cancelled_mid_file = False
            content_key = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
            for i, chunk in enumerate(chunks):
                # 取消检查放在块与块之间，不是只在文件与文件之间——一个大文件
                # 可能切成几百上千个 chunk，每块又是一次独立的 LLM 调用（见
                # docs/kite-constraints.md 约束 9 提到的耗时），只在外层文件
                # 循环查取消标记的话，取消这一个大文件的任务实际上完全没用，
                # 只能等它自己把所有 chunk 跑完（真实碰到过：整本小说当文档传
                # 进来，切出几百个 chunk，点了取消却半小时都停不下来）。
                if store.is_cancel_requested(job_id):
                    cancelled_mid_file = True
                    break
                total += mem.remember(
                    [{"role": "user", "content": chunk}],
                    # 用**内容哈希**而不是 item_id：item_id 是每次任务新生成的，
                    # 同一个文件传两次会在知识库里存两份。内容哈希让"同样的文件
                    # 再传一次"自动被 KITE 跳过（不花 LLM 调用）。
                    session_id=f"file-{content_key}-{i}",
                    date=file_date,
                    title=filename,
                )
                # 同一个文件常常切成好几个 chunk，每个 chunk 一次独立的 LLM
                # 调用——每块跑完就落一次库，SSE 才能把 facts 数逐块往上涨
                # 推给前端，而不是等一整个文件的所有 chunk 都跑完才跳一次。
                store.set_item(item_id, "remembering", facts=total)
                store.update_job_from_items(job_id)
            if cancelled_mid_file:
                store.set_item(item_id, "cancelled", facts=total,
                              detail=f"已处理 {i}/{len(chunks)} 块后取消")
            else:
                store.set_item(item_id, "done", facts=total)
        except Exception as exc:  # noqa: BLE001 — 单个文件失败不能拖垮整批
            store.set_item(item_id, "failed", detail=f"{type(exc).__name__}: {exc}")
        store.update_job_from_items(job_id)


@router.post("/batch", response_model=IngestOut)
async def ingest_batch(bg: BackgroundTasks,
                       files: list[UploadFile] = File(...),
                       language: str = Form("auto"),
                       user: str = Depends(current_user)):
    """多文件批量入库：PDF / DOCX / TXT / MD / 音频混着传，每个文件独立处理，
    互不拖累。用 GET /jobs/{id}/events 订阅进度。"""
    if not files:
        raise HTTPException(400, "no files")
    if len(files) > BATCH_MAX_FILES:
        raise HTTPException(400, f"最多一次 {BATCH_MAX_FILES} 个文件")

    # 批量上传拿不到原始笔记的日期（HTTP 上传没有这个信息），只能退回今天。
    # **导入器不要走这条路**——用 POST /api/ingest/text 并带上 date，否则
    # 用户几年的笔记会被压成同一天。这条路留给「把手边几个文件拖进来」。
    specs: list[dict] = []
    raw: list[bytes] = []
    for f in files:
        try:
            kind = extract.kind_for(f.filename or "")
        except extract.UnsupportedFileType as exc:
            raise HTTPException(400, str(exc)) from exc
        data = await f.read()
        if not data:
            raise HTTPException(400, f"空文件：{f.filename}")
        specs.append({"filename": f.filename or "file", "kind": kind})
        raw.append(data)

    job_id, items = store.create_batch_job(user, specs)
    # create_batch_job 按 specs 顺序生成 item，用 idx 位置对齐回原始字节
    # （不能用文件名做 key —— 同批次可能有同名文件）
    keyed_payloads = {item["id"]: raw[item["idx"]] for item in items}
    bg.add_task(_batch_job, job_id, user, items, keyed_payloads, language)
    return IngestOut(job_id=job_id, status="queued",
                     items=[IngestItemOut(**it) for it in items])


@router.get("/jobs", response_model=list[IngestOut])
def list_jobs(user: str = Depends(current_user), limit: int = 20):
    jobs = store.list_jobs(user, limit)
    return [
        IngestOut(job_id=j["id"], status=j["status"], facts=j["facts"],
                  detail=j["detail"],
                  items=[IngestItemOut(**it) for it in store.get_items(j["id"])])
        for j in jobs
    ]


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, user: str = Depends(current_user)):
    job = store.get_job(job_id)
    if not job or job["user_id"] != user:
        raise HTTPException(404, "job not found")
    store.request_cancel(job_id)
    # **立刻把还没开工的 item 置为已取消**，不要等后台线程自己发现。
    #
    # 后台线程可能正阻塞在一次 LLM 调用或 KITE 的写锁里，几十秒都到不了下一个
    # 取消检查点——那期间界面上什么都不变，用户看到的就是「点了取消没反应」。
    # 已经开工的那一条只能等它自己收尾，但排队中的可以马上停，进度条立刻动起来。
    for it in store.get_items(job_id):
        if it["status"] == "queued":
            store.set_item(it["id"], "cancelled")
    store.update_job_from_items(job_id)
    return {"ok": True, "status": (store.get_job(job_id) or {}).get("status", "")}


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, user: str = Depends(current_user)):
    """SSE 进度流：轮询 DB 里的 job/items，状态一变就推一帧，job 到终态就结束。"""
    job = store.get_job(job_id)
    if not job or job["user_id"] != user:
        raise HTTPException(404, "job not found")

    async def gen():
        last = None
        while True:
            j = store.get_job(job_id)
            snap = {
                "job_id": j["id"], "status": j["status"], "facts": j["facts"],
                "detail": j["detail"], "items": store.get_items(job_id),
            }
            frame = json.dumps(snap, ensure_ascii=False, sort_keys=True)
            if frame != last:
                last = frame
                yield f"event: progress\ndata: {frame}\n\n"
            if j["status"] in ("done", "error", "cancelled"):
                yield "event: end\ndata: {}\n\n"
                return
            await asyncio.sleep(0.7)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.get("/jobs/{job_id}", response_model=IngestOut)
def job_status(job_id: str):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return IngestOut(job_id=job["id"], status=job["status"], facts=job["facts"],
                     detail=job["detail"], items=[
                         IngestItemOut(**it) for it in store.get_items(job_id)])
