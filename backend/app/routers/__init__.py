"""和前端对接的一层，**薄壳**。

一条 harness 的 router 只做三件事：认模式、装 State、把事件序列化成 SSE。
真正的循环在 ``harness/``——三条 router 曾经各抄一遍循环（555 + 245 + 156
行），代价是「同一个能力一条有、另一条没有」出现了六次。现在：

    note_harness.py   98 行   骨架前置 · 打磨模式配置
    writing_plan.py  281 行   plan 级循环：选下一段 · 要不要加段 · 同步追踪笔记
    compose_block.py 186 行   认模式 · 图片转表格 · 智能排版
    harness.py               轮末暂停的恢复入口

其余是 CRUD 和资源：notes · folders · notes 的骨架 · profile · skills ·
settings · assets · ingest · import_sources · memory · kb。

``deps.py`` 是所有 router 共用的依赖（现在只有 ``current_user``）。
**router 之间不许互相 import**——一个 router 伸手去拿另一个的东西，说明
那个东西该往下沉一层（六次都是这样，六个都沉下去了，见
tests/test_layering.py）。
"""
