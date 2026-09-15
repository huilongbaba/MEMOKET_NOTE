"""让模型确认一遍冲突候选，再放进收件箱。

**为什么这一步值得多花一次模型调用**（第 678 轮）：原来收件箱这条路是纯代码、
不确认的，而右栏那张**只是给你看**的关系卡反倒会让模型确认一遍
（`routers/memory.py` 的 `body.confirm`）。**把关把反了**——收件箱那张卡上摆着
「新的取代旧的」，点一下就把一条正确的事实作废掉。

实拍（新用户导入两篇真会议记录）：收件箱里两条**都是误报**。纯词面重合看不出
「竞品 Plaud 的定价是 159 美元」跟「我们的定价是 199 美元」说的不是一件事——
这正是模型一眼能判的。

代价可以忽略：在 20406 条的真库上抽 2500 条量过，冲突候选一共只触发 4 次
（0.16%），一次全库导入也就几十次调用。

住在 `harness/` 而不是 `routers/`：它要用 `prompts` 和 `util.llm`，而路由之间
不许互相 import（`test_layering` 拦下了第一版）。知识库那一层把它当参数收下
（`kb/inbox.scan_session(confirm=…)`），不注入就是原来的纯代码行为——
**层次的方向是「上面知道下面」，所以这件事只能由上面递进去。**
"""

from __future__ import annotations

import asyncio
import concurrent.futures as _f

from . import prompts
from ..util import llm

# 模型改写的那句话直接显示在卡片上：封顶，别把卡撑成一屏（跟右栏那条同一个数）
SAY_MAX = 160


def _run(coro):
    """后台摄入任务是同步的；有没有在跑的事件循环都要能等到结果
    （跟 `harness/tools/registry._await` 同一套做法）。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with _f.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


def confirm_conflicts(passage: str, cands: list[dict], by_id: dict[str, dict]) -> list[dict]:
    """逐条问「这是同一件事的同一个量吗」。

    **模型不在就原样放行**——宁可多报一条让用户自己判，也不要因为模型不可用
    就悄悄吞掉一条真冲突。
    """
    if not cands:
        return cands
    try:
        verdict = _run(llm.complete_json(
            [{"role": "system", "content": prompts.RELATIONS_SYSTEM},
             {"role": "user", "content": prompts.relations_user(passage, cands, by_id)}],
            max_tokens=600, temperature=0.1))
    except Exception as exc:      # noqa: BLE001
        print(f"[inbox] 冲突确认跳过（模型不可用）: {type(exc).__name__}: {exc}")
        return cands
    if not isinstance(verdict, list):
        return cands
    keep = {v["index"]: v for v in verdict
            if isinstance(v, dict) and isinstance(v.get("index"), int)}
    out = []
    for i, c in enumerate(cands):
        v = keep.get(i)
        if v is not None and not v.get("keep", True):
            continue
        # 模型改写的那句更准——它看得见两边的主语（「竞品的价」还是「我们的价」）
        out.append(dict(c, say=" ".join(str((v or {}).get("say") or c["say"]).split())[:SAY_MAX]))
    return out
