"""共享依赖。原型阶段用请求头传用户身份，不做认证。"""

from fastapi import Header


def current_user(x_user_id: str = Header(default="default")) -> str:
    """多用户隔离：每个 user_id 对应一个独立的 KITE codebook。

    生产环境这里换成真实的鉴权（JWT / session），返回值语义不变。
    """
    return (x_user_id or "default").strip() or "default"
