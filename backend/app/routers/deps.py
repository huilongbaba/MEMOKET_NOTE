"""共享依赖：谁在请求、以及流式响应怎么开。

这里放的是**每个 router 都要用、又不属于任何一个 router** 的东西。
分层测试把这个文件和 schemas.py 一起豁免了 router 不许互相 import 的
规则，正是因为它们不是 router。
"""

from collections.abc import AsyncIterator

import re

from fastapi import Header, HTTPException
from fastapi.responses import StreamingResponse


def sse_response(gen: AsyncIterator[str]) -> StreamingResponse:
    """开一条 SSE 流。

    这三行原本在六个 router 里各抄了一遍。抄六遍的东西迟早漂：
    ``X-Accel-Buffering: no`` 是关掉 nginx 缓冲的，漏在哪一个上面，那条
    流在部署环境里就会攒够几 KB 才吐一次——本地一切正常，线上「一动不动
    然后突然全出来」。
    """
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


_USER_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")   # HTTP 头只能是 ASCII，中文名本来就发不出来


def current_user(x_user_id: str = Header(default="default")) -> str:
    """多用户隔离：每个 user_id 对应一个独立的 KITE codebook。

    生产环境这里换成真实的鉴权（JWT / session），返回值语义不变。
    user_id 直接拼进 `data/<user>/` 的路径，所以只认字母数字 `_ . -`（跟桌面壳 identity.json 同一条
    正则）——`../x` 这种别让它走到文件系统（第 159 轮巡检）。
    """
    uid = (x_user_id or "default").strip() or "default"
    if not _USER_ID.match(uid) or uid in (".", ".."):
        raise HTTPException(400, "user id 只能是字母、数字、_ . -，最长 64")
    return uid
