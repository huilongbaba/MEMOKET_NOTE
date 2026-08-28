"""个人偏好——独立于知识库的一份轻量 profile。

跟知识库的关键区别：知识库的 fact 是从文档/笔记里"抽"出来的，异步、经模型
取舍、走 LLM 排队（13s/chunk）。这里是用户自己直接说"我喜欢/我倾向于..."，
不用抽取，写完立刻生效。写作三件套（骨架/编辑/magic tap，见 routers/compose.py）
生成时会读取这份 profile，让输出贴合用户偏好——跟"检索知识库事实"是两路
并行的输入，不是同一个存储。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import store
from ..schemas import ProfileEntry, ProfileEntryIn
from .deps import current_user

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("", response_model=list[ProfileEntry])
def list_profile(user: str = Depends(current_user)):
    return store.list_profile(user)


@router.post("", response_model=ProfileEntry)
def add_profile(body: ProfileEntryIn, user: str = Depends(current_user)):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "content is empty")
    return store.add_profile_entry(user, text)


@router.delete("/{entry_id}")
def delete_profile(entry_id: str, user: str = Depends(current_user)):
    if not store.delete_profile_entry(user, entry_id):
        raise HTTPException(404, "entry not found")
    return {"ok": True}
