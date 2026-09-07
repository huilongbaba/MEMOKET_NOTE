"""工具池：一个进程内注册表，把「agent 能调用的能力」和「谁去实现它」分开。

设计目标是**加一个工具的成本 = 写一个带装饰器的函数**，不用改 harness、
不用改 llm.py、不用改任何调度代码：

    @register(
        name="search_memory",
        description="按关键词检索用户的个人知识库",
        params={"query": {"type": "string", "description": "检索词"}},
        required=["query"],
    )
    def search_memory(ctx: ToolContext, query: str) -> str:
        ...

注册表只管三件事：把工具渲染成 OpenAI tools 数组、按名字派发、把结果规整
成字符串。它不认识 KITE、不认识笔记、不做任何 I/O——具体能力都在
``memory_tools.py`` 这类模块里，import 时自行注册。

**为什么工具返回字符串而不是结构化对象**：工具结果最终要作为 role=tool
的消息塞回对话里给模型读，模型读的是文本。让每个工具自己决定怎么把结果
渲染得便于模型理解（哪些字段重要、怎么排版），比在这里统一 json.dumps
更贴合各自的语义——json.dumps 出来的中文还会变成 \\uXXXX，白白浪费 token。

**权限/分组**：每个工具带一个 ``group``。harness 按 group 挑要暴露哪些
工具，以后加 web browsing、代码执行这类需要单独授权的能力时，直接给它们
新的 group，不用改这里的机制。
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolContext:
    """派发时传给工具的运行上下文。工具需要什么就从这里取，不要自己去
    读全局状态——这样单测里构造一个 ToolContext 就能测任何工具。"""

    user: str
    note_id: str = ""
    note_title: str = ""
    # 当前笔记的正文和光标位置。data 组的工具要读它们才能找到表格、才能按
    # 「就近原则」选表。**必须挂在 ctx 上而不是模块级全局**：同一篇笔记可以
    # 有好几个 `/` 同时在跑（前端就是这么设计的），全局字典按 note_id 存的话
    # 后开始的那个会把先开始的光标覆盖掉，先跑的那个就分析到别处的表去了。
    content: str = ""
    cursor: int = 0


@dataclass
class Tool:
    name: str
    description: str
    params: dict[str, dict]
    required: list[str]
    handler: Callable[..., Any]
    group: str = "memory"
    # 单轮里同一个工具最多被调用几次。模型会一次并行发好几个查询（实测
    # 本地模型对一个问题一口气发了三个 recall），大多是同义改写，全放行
    # 只是浪费时间——超过就截断，保留前几个。
    max_calls_per_round: int = 3

    def spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.params,
                    "required": self.required,
                },
            },
        }


_REGISTRY: dict[str, Tool] = {}


def register(*, name: str, description: str, params: dict[str, dict],
             required: list[str] | None = None, group: str = "memory",
             max_calls_per_round: int = 3) -> Callable:
    def deco(fn: Callable) -> Callable:
        if name in _REGISTRY:
            raise ValueError(f"工具名重复注册: {name}")
        _REGISTRY[name] = Tool(
            name=name, description=description, params=params,
            required=list(required or []), handler=fn, group=group,
            max_calls_per_round=max_calls_per_round,
        )
        return fn
    return deco


def get(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def names(groups: list[str] | None = None) -> list[str]:
    if groups is None:
        return sorted(_REGISTRY)
    allowed = set(groups)
    return sorted(n for n, t in _REGISTRY.items() if t.group in allowed)


def specs(groups: list[str] | None = None) -> list[dict]:
    """渲染成 OpenAI ``tools`` 数组。groups 为 None 时给全部。"""
    return [_REGISTRY[n].spec() for n in names(groups)]


class ToolError(Exception):
    """工具执行失败。派发方会把它转成给模型看的错误文本，不往上抛——
    一个工具查不到东西不该让整轮 harness 炸掉。"""


def _await(coro, name: str) -> str:
    """在同步的 dispatch 里等一个异步工具跑完。

    dispatch 被 harness 从 async 上下文里调用（agent_loop 是 async 的），
    这时当前线程已经有一个正在跑的事件循环，不能 asyncio.run。丢到另一个
    线程里跑一个自己的循环，是这里唯一安全的做法。
    """
    import asyncio
    import concurrent.futures as _f

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        result = asyncio.run(coro)                      # 没有在跑的循环，直接跑
    else:
        with _f.ThreadPoolExecutor(max_workers=1) as ex:
            result = ex.submit(asyncio.run, coro).result()
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


def dispatch(name: str, arguments: str | dict, ctx: ToolContext) -> str:
    """执行一次工具调用，返回给模型读的文本。

    任何失败都转成文本返回，不抛异常：模型看到「这个工具没查到/参数不对」
    是可以自己纠正的信息，而抛出去只会让整轮 harness 中断。
    """
    tool = _REGISTRY.get(name)
    if tool is None:
        return f"（没有名为 {name} 的工具。可用的工具：{'、'.join(names())}）"

    if isinstance(arguments, str):
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return f"（{name} 的参数不是合法 JSON，收到的是：{arguments[:200]}）"
    else:
        args = dict(arguments or {})

    if not isinstance(args, dict):
        return f"（{name} 的参数必须是一个对象，收到的是 {type(args).__name__}）"

    missing = [k for k in tool.required if k not in args or args[k] in ("", None)]
    if missing:
        return f"（{name} 缺少必填参数：{'、'.join(missing)}）"

    # 只传函数签名里真有的参数——模型偶尔会多塞字段，直接 **args 会 TypeError
    sig = inspect.signature(tool.handler)
    accepted = {k: v for k, v in args.items() if k in sig.parameters}
    try:
        result = tool.handler(ctx, **accepted)
        if inspect.isawaitable(result):
            # 异步工具（比如文生图要等几十秒的网络调用）。**必须在这里 await**：
            # 不 await 的话返回的是一个协程对象，json.dumps 出来是
            # "<coroutine object ...>"，模型收到一句没有意义的字符串却毫无
            # 报错——这种"能跑但结果是垃圾"最难查。
            return _await(result, name)
    except ToolError as exc:
        return f"（{name} 执行失败：{exc}）"
    except Exception as exc:  # noqa: BLE001 - 工具失败绝不能让 harness 中断
        return f"（{name} 执行出错：{type(exc).__name__}: {exc}）"
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


def describe(groups: list[str] | None = None) -> str:
    """给 system prompt 用的工具清单文本（一行一个）。模型光看 tools 数组
    有时不够——把「什么时候该用哪个」写进 system prompt 更可靠。"""
    lines = []
    for n in names(groups):
        t = _REGISTRY[n]
        lines.append(f"- {t.name}：{t.description}")
    return "\n".join(lines)


# 单测用：让每个测试从干净的注册表开始，不受 import 顺序影响
def _reset_for_tests() -> None:
    _REGISTRY.clear()


def _snapshot() -> dict[str, Tool]:
    return dict(_REGISTRY)


def _restore(snapshot: dict[str, Tool]) -> None:
    _REGISTRY.clear()
    _REGISTRY.update(snapshot)
