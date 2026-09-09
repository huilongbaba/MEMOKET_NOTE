"""前端调的每一个 /api 路径，后端都得真的有。

这条测试是在一轮大重构之后补的：schemas 换了目录、prompts 拆了包、路由
文件搬过位置——后端自己的测试全绿，但**没有任何东西**在看前端还能不能
对得上。契约漂了的症状是线上 404，而不是红测试。

只查路径存不存在，不查请求体和返回值：那两样归 schemas 和 FastAPI 自己
的校验管，在这里重复一遍只会变成两份要同步的真相。
"""

from __future__ import annotations

import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"

pytestmark = pytest.mark.skipif(not FRONTEND.is_dir(),
                                reason="没有前端源码目录")


def _normalise(url: str) -> str:
    """``/api/notes/${id}`` 和 ``/api/notes/{note_id}`` 是同一条路径。"""
    return re.sub(r"\{[^}]*\}", "{}", re.sub(r"\$\{[^}]*\}", "{}", url)).rstrip("/")


def _frontend_calls() -> set[str]:
    text = "\n".join(p.read_text(encoding="utf-8")
                     for p in FRONTEND.rglob("*.ts*"))
    return {m.group(1) for m in
            re.finditer(r"""[`"']((?:/api)/[\w/${}.:-]*)[`"']""", text)}


def _backend_paths() -> set[str]:
    # 走 OpenAPI 表，不走 app.routes：这个版本的 FastAPI 把 include_router
    # 进来的路由包在 _IncludedRouter 里，直接遍历 app.routes 只看得到
    # /docs 那四条。第一版就是这么写的，报出「51 个端点不存在」——那是
    # 检查器坏了，不是代码坏了。
    from app.main import app

    return set(app.openapi()["paths"])


def test_前端调的每个端点后端都有():
    calls = _frontend_calls()
    assert len(calls) > 30, f"只从前端扒出 {len(calls)} 个调用——正则怕是不认了"

    have = {_normalise(p) for p in _backend_paths()}
    missing = sorted(u for u in calls if _normalise(u) not in have)
    assert not missing, "前端在调后端没有的端点：\n  " + "\n  ".join(missing)


def test_后端发的每个CUSTOM事件前端都接得住():
    """CUSTOM 事件的名字是前后端之间的第二份契约，比路径那份更容易漏。

    实际漏过两个：``check_hit``（代码判据当场判这一轮不合格，触发很频繁）
    和 ``warning``（某条 middleware 抛异常了）。两个都在生产路径上真的会
    发，前端一个分支都没有，全被 else 掉了——`loop.py` 里明明写着「失败
    不能是静默的，要变成一个 CUSTOM 警告事件」，那句话在端到端层面并不
    成立，因为没有任何东西显示它。

    路径漂了会 404，还看得见；事件名漂了什么都不会发生。
    """
    import re

    from app.harness import events

    emitted = {v for k, v in vars(events).items()
               if k.startswith("CUSTOM_") and isinstance(v, str)}
    assert len(emitted) >= 8, f"没认出 CUSTOM 名字，只找到 {sorted(emitted)}"

    api_ts = (FRONTEND / "api.ts").read_text(encoding="utf-8")
    handled = set(re.findall(r"payload\.name === '([\w_]+)'", api_ts))
    missing = sorted(emitted - handled)
    assert not missing, ("后端会发、前端没有分支接的 CUSTOM 事件："
                         f"{missing}——发出去直接被丢掉，不会有任何症状")


# 后端会发、前端**故意**不接的标准事件。每一条都要有理由——默认掉进 else
# 和「想清楚了不接」看起来一模一样，区别只在有没有写下来。
_DELIBERATELY_IGNORED = {
    "RUN_STARTED": "前端自己发起的请求，它早就知道跑起来了",
    "TEXT_MESSAGE_START": "正文按轮累积、轮次由 STEP_STARTED 划分，消息边界是冗余的",
    "TEXT_MESSAGE_END": "同上",
}


def test_后端发的每种标准事件前端要么接要么写明不接():
    """AG-UI 那 11 个标准事件名，也是一份契约。

    这一条跟 CUSTOM 那条的区别：CUSTOM 漏一个是 bug（那两个漏掉的确实
    是），标准事件里有几个前端**本来就不需要**。所以判据不是「全都要接」，
    是「要么接，要么在上面那张表里写明为什么不接」。
    """
    import re

    from app.harness import events

    api_ts = (FRONTEND / "api.ts").read_text(encoding="utf-8")
    handled = set(re.findall(r"event === '([A-Z_]+)'", api_ts))

    backend_src = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (FRONTEND.parents[1] / "backend" / "app").rglob("*.py"))
    emitted = {e.value for e in events.EventType
               if re.search(rf"EventType\.{e.name}\b", backend_src)}
    assert len(emitted) >= 10, f"没认出后端在发哪些事件：{sorted(emitted)}"

    unaccounted = sorted(emitted - handled - set(_DELIBERATELY_IGNORED))
    assert not unaccounted, (
        f"这些事件后端会发，前端既没接也没写明为什么不接：{unaccounted}")

    stale = sorted(set(_DELIBERATELY_IGNORED) & handled)
    assert not stale, f"这些已经接上了，从「故意不接」名单里删掉：{stale}"
