"""入库：文档 / 语音 -> 知识库。

抽取事实要调 LLM（本地 30B 上约 13s/段），所以一律丢后台任务，接口立刻返回
job_id，前端轮询 /api/ingest/jobs/{id} 看进度。
"""

from __future__ import annotations

import uuid
from datetime import date as _date

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from .. import asr, store
from ..kite_memory import UserMemory
from ..schemas import IngestOut, IngestTextIn
from .deps import current_user

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

# 一次抽取喂给 LLM 的字符上限，太长会拖垮抽取质量和耗时
CHUNK_CHARS = 1200


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


def _ingest_job(job_id: str, user_id: str, text: str, title: str, source: str) -> None:
    store.set_job(job_id, "running")
    try:
        mem = UserMemory(user_id)
        total = 0
        for i, chunk in enumerate(_chunks(text)):
            total += mem.remember(
                [{"role": "user", "content": chunk}],
                session_id=f"{source}-{uuid.uuid4().hex[:8]}-{i}",
                date=_date.today().isoformat(),
                title=title,
            )
        store.set_job(job_id, "done", facts=total)
    except Exception as exc:  # 后台任务的异常必须落库，否则前端只看到永远 running
        store.set_job(job_id, "error", detail=f"{type(exc).__name__}: {exc}")


@router.post("/text", response_model=IngestOut)
def ingest_text(body: IngestTextIn, bg: BackgroundTasks,
                user: str = Depends(current_user)):
    if not body.content.strip():
        raise HTTPException(400, "content is empty")
    job_id = store.create_job(user)
    bg.add_task(_ingest_job, job_id, user, body.content, body.title, body.source)
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


@router.get("/jobs/{job_id}", response_model=IngestOut)
def job_status(job_id: str):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return IngestOut(job_id=job["id"], status=job["status"],
                     facts=job["facts"], detail=job["detail"])
