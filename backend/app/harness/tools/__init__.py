"""工具池。

``import app.tools`` 就会把所有内置工具注册进来——具体能力模块在下面
显式 import，加新一组工具时在这里加一行 import 即可。

分组约定（``Tool.group``）：
    memory   —— KITE 知识库的只读查询，零 LLM、亚毫秒，默认对写作 agent 开放
    data     —— 对当前笔记里的表格做确定性统计（画像/分组聚合/相关），零 LLM
    chart    —— 把数据拼成 markdown 表格或 mermaid 图，**语法由代码生成**，
                模型不写 mermaid，从根上消掉"图渲染不出来"这类错
    image    —— 文生图。单独一组是因为它要花钱、要等几十秒，不该在"画个柱状图"
                的场合被顺手调用
以后加 web browsing / 代码执行这类需要单独授权、或者有外部副作用的能力时，
给它们各自的 group，harness 通过 ``specs(groups=[...])`` 决定暴露哪些，
不需要改注册表本身。
"""

# 这四个是**为副作用而导入**的：每个模块顶层的 @register 装饰器在导入的
# 那一刻把工具填进注册表。名字本身没人用，所以标 noqa——静态检查会把
# 「导入了没用」当成重构没做干净的残留报出来，而这里恰恰不是。
from . import data_tools      # noqa: F401  注册 data 组
from . import memory_tools    # noqa: F401  注册 memory 组
from . import sandbox_tools   # noqa: F401  注册 skill_script 组
from . import skill_tools     # noqa: F401  注册 skill 组
from .registry import (
    Tool,
    ToolContext,
    ToolError,
    describe,
    dispatch,
    get,
    names,
    register,
    specs,
)

__all__ = [
    "Tool",
    "ToolContext",
    "ToolError",
    "describe",
    "dispatch",
    "get",
    "names",
    "register",
    "specs",
]
