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
    created_at: str
    updated_at: str


# ---------------------------------------------------------------- 记忆

class FactOut(BaseModel):
    id: str
    text: str
    when: str = ""
    kind: str = ""
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


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


class IngestItemOut(BaseModel):
    """批量任务里单个文件的进度。单文件任务（/text /audio）不产生 item，恒为空列表。"""
    id: str
    idx: int
    filename: str
    kind: str
    status: Literal["queued", "extracting", "transcribing", "chunking",
                    "remembering", "done", "failed", "cancelled"]
    facts: int = 0
    detail: str = ""


class IngestOut(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "error", "cancelled"]
    facts: int = 0
    detail: str = ""
    items: list[IngestItemOut] = Field(default_factory=list)


# ---------------------------------------------------------------- 写作

class SkeletonIn(BaseModel):
    """线 1：为当前写作内容生成主线骨架。"""
    content: str
    title: str = ""


class SkeletonOut(BaseModel):
    skeleton: list[str]
    took_ms: float


class EditIn(BaseModel):
    """线 2：骨架 + 已写内容 + 知识库 -> 修订建议。"""
    content: str
    skeleton: list[str] = Field(default_factory=list)


class Revision(BaseModel):
    """一条 track-changes 修订。前端据此渲染可接受/拒绝的标记。"""
    id: str
    op: Literal["insert", "delete", "replace"]
    anchor: str = ""          # 原文中被定位的片段（delete/replace 用）
    text: str = ""            # 新内容（insert/replace 用）
    reason: str = ""
    sources: list[str] = Field(default_factory=list)


class EditOut(BaseModel):
    revisions: list[Revision]
    took_ms: float


class MagicTapIn(BaseModel):
    content: str
    skeleton: list[str] = Field(default_factory=list)
    max_tokens: int = 1200


class AskIn(BaseModel):
    """显式提问知识库。走 KITE 原生 planning，慢但支持时序推理。"""
    question: str
    limit: int = 10


class AskOut(BaseModel):
    answer: str
    facts: list[FactOut] = Field(default_factory=list)
    took_ms: float
