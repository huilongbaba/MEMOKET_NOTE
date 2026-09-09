"""共享依赖：谁在请求、以及流式响应怎么开。

这里放的是**每个 router 都要用、又不属于任何一个 router** 的东西。
分层测试把这个文件和 schemas.py 一起豁免了 router 不许互相 import 的
规则，正是因为它们不是 router。
"""

from collections.abc import AsyncIterator

from fastapi import Header
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


def current_user(x_user_id: str = Header(default="default")) -> str:
    """多用户隔离：每个 user_id 对应一个独立的 KITE codebook。

    生产环境这里换成真实的鉴权（JWT / session），返回值语义不变。
    """
    return (x_user_id or "default").strip() or "default"
