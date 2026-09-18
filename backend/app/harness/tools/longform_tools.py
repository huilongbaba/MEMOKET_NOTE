"""长文专用的一个工具：**把这篇笔记的某一节原文读回来。**

这是计划 3.1（[CE] §7）的另一半。另一半在 `middleware/sections.py`：
续写 prompt 里的正文从「更早的部分折成摘要」换成了「小节索引 + 当前小节
逐字」。**索引是指针，不是替换**——而指针要成立，就得真的有一条路能把
指到的东西取回来。这条路就是这里。

## 为什么它值得单独占一个 group

`longform` 只挂在 `NOTE` / `SECTION` 两个模式上。六个 block 模式写的是
「插进笔记里的一块」，几百个字，根本没有小节可言——把这个工具摆到它们
面前，只是在每一次调用的工具表里多一条永远用不上的定义，而**工具定义
与顺序在官方的断缓存清单里**（[CE] §1）。判据宁可窄一点。

## 它**不是**知识库查询

三处边界，各有各的后果：

* 不进 `agent_loop.FACT_TOOLS`——它返回的是**用户自己已经写下的正文**，
  不是检索回来的材料。算进去的话，「连着两次没带回新事实就停」
  （计划 2.5）会被自己的正文喂饱，停机判据当场失效。
* 不进 `query_cache.CACHEABLE`——正文**每一轮都在变**（`Revise` 就地改写）。
  短路它等于让第 3 轮读到第 1 轮的那一节。这跟 `data` 组不能短路是同一条
  理由（`query_cache` 的模块文档写着）。
* 不进 `ToolTrace.as_facts()` 的白名单，所以读回来的正文不会被当成
  【知识库事实】喂给续写——实测过同一种错：只调了 `list_topics` 就收手，
  那份主题列表被原样当作事实喂进去，模型手里一条真事实都没有。
"""

from __future__ import annotations

from .registry import ToolContext, register

# 分节结果和「读过哪几节」都挂在 `ToolContext.scratch` 上（注册表那边明写
# 「调用方自己的暂存区，工具池不解释它」）。
#
# **两个键名定义在工具这一侧，不在 middleware 那一侧。** `test_layering` 钉着
# 一条边界：工具可以用 harness 的能力，但**不许认识运行时**（loop / state /
# modes / middleware / hooks / checks）——它跟驱动方之间只有 `scratch` 这一个
# dict，正是为了不用知道有没有 harness 在跑。第一版把键名 import 自
# `middleware/sections.py`，当场被那条测试拦下。反过来由 `middleware` 来取
# 就没有这个问题：middleware 本来就在 import tools（`runtime.py` 顶上就是）。
SCRATCH_SECTIONS = "harness_sections"      # [(标题, 这一节原文)]，由 middleware 发布
SCRATCH_READ = "harness_sections_read"     # 这次跑里读回过哪几节（节号，1 起）


@register(
    name="read_section",
    description=(
        "把当前这篇笔记的第 n 节原文完整读回来。"
        "续写提示里的【目录】给的只是每节一行的索引；要看某一节到底写了什么，"
        "就用那一行前面的节号调这个工具。"),
    params={"n": {"type": "integer",
                  "description": "节号，从 1 开始，就是目录里「第 N 节」的那个 N"}},
    required=["n"],
    group="longform",
    # 一轮最多读三节。再多就等于把全文搬回上下文，那正是这一整条改动要
    # 消掉的东西；而且真要通读全文的是打分和修订，它们本来就拿全文。
    max_calls_per_round=3,
)
def read_section(ctx: ToolContext, n: int) -> str:
    sections = ctx.scratch.get(SCRATCH_SECTIONS) or []
    if not sections:
        # block 模式、或者正文还没分出小节。**说清楚是「没有小节」而不是
        # 「读失败」**：模型看到一句含糊的错误会换个参数再试一遍，白花一次调用。
        return "（这次没有分小节的长文，用不上这个工具——要写什么直接写。）"
    try:
        idx = int(n)
    except (TypeError, ValueError):
        return f"（节号要是一个整数，收到的是 {n!r}。）"
    if not 1 <= idx <= len(sections):
        return (f"（这篇笔记一共 {len(sections)} 节，没有第 {idx} 节。"
                f"节号在目录里每一行的开头。）")
    title, text = sections[idx - 1]
    # 记下来，`middleware/sections.py` 会在**这一轮的续写 prompt** 里把这一节
    # 逐字带上。**不记的话这次读就白读了**：工具循环发生在检索规划那次调用里，
    # 而续写是另一次调用、messages 是新拼的，上一次的 tool 消息不在里面。
    # （`query_cache` 的模块文档里记着同一个形状的坑：跨轮短路必须返回全文，
    # 退化成一句提示会让那一轮凭空少掉一批材料。）
    read = ctx.scratch.setdefault(SCRATCH_READ, [])
    if idx not in read:
        read.append(idx)
    return f"【第 {idx} 节「{title or '开头那段'}」全文】\n{text}"
