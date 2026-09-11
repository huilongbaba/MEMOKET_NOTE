"""前端把自己的错误报上来，打进后端 stdout——也就是 Electron 的日志。

打包版没有 DevTools：渲染进程一抛未捕获异常，React 把整棵树卸掉，用户看到的
是一片白，日志里什么都没有（实拍：「挂了」，后端还在正常写库）。有了这条，
白屏的原因至少会出现在日志里，界面上也由 ErrorBoundary 把错误摆出来。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .deps import current_user

router = APIRouter(prefix="/api/client-log", tags=["client-log"])
log = logging.getLogger("client")


class ClientLogIn(BaseModel):
    level: str = "error"
    message: str
    stack: str = ""
    where: str = ""


@router.post("")
def client_log(body: ClientLogIn, user: str = Depends(current_user)) -> dict:
    text = f"[client:{body.level}] user={user} {body.where} {body.message}"
    if body.stack:
        text += "\n" + body.stack[:4000]
    print(text, flush=True)
    log.error(text) if body.level == "error" else log.warning(text)
    return {"ok": True}
