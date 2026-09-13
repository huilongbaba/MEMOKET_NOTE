"""个人偏好——独立于知识库的一份轻量 profile。

跟知识库的关键区别：知识库的 fact 是从文档/笔记里"抽"出来的，异步、经模型
取舍、走 LLM 排队（13s/chunk）。这里是用户自己直接说"我喜欢/我倾向于..."，
不用抽取，写完立刻生效。写作三件套（骨架/编辑/magic tap，见 routers/compose.py）
生成时会读取这份 profile，让输出贴合用户偏好——跟"检索知识库事实"是两路
并行的输入，不是同一个存储。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..database import store
from .schemas import ProfileEntry, ProfileEntryIn
from .deps import current_user

router = APIRouter(prefix="/api/profile", tags=["profile"])

# 一条偏好是一句话，不是一篇文章：每条都会原样拼进写作提示词，5000 字的一条能把提示词撑爆
# （第 242 轮实测接口照单全收）
MAX_CHARS = 400


@router.get("", response_model=list[ProfileEntry])
def list_profile(user: str = Depends(current_user)):
    return store.list_profile(user)


@router.post("", response_model=ProfileEntry)
def add_profile(body: ProfileEntryIn, user: str = Depends(current_user)):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "content is empty")
    if len(text) > MAX_CHARS:
        raise HTTPException(400, f"一条偏好最多 {MAX_CHARS} 字——太长的拆成几条，或者写进笔记再存入知识库")
    # 同一句话再加一次原样返回已有的那条：连点两下「添加」不该出现两条一模一样的
    for e in store.list_profile(user):
        if e["text"] == text:
            return e
    return store.add_profile_entry(user, text)


@router.delete("/{entry_id}")
def delete_profile(entry_id: str, user: str = Depends(current_user)):
    if not store.delete_profile_entry(user, entry_id):
        raise HTTPException(404, "entry not found")
    return {"ok": True}
