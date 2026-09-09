"""纯函数层：只依赖标准库，给个字符串就能测。

这一层的定义不是「小工具」，是**一条可验证的性质**：不碰网络、不碰数据库、
不调模型，所以每一条判断都能用一个构造出来的字符串单测。判据里凡是代码
判得了的都在这儿——``blockcheck`` 认假图、``grounding_check`` 认审计腔和
没出处的数字、``outline`` 认大纲层级、``tabular`` 算数字、``blocks`` 拼
mermaid。

`tests/test_layering.py` 有一条断言盯着这条性质：这里任何一个文件长出
标准库以外的依赖，测试会红。之前这九个文件平铺在 ``app/`` 顶层，那条断言
靠一张手写名单认它们；现在名单就是这个目录。

    blockcheck.py       假图 · 手写 mermaid · 图表缺口
    grounding_check.py  占位符 · 审计腔 · 事实用没用上
    outline.py          markdown 大纲：层级、下一个空节、结构有没有被压平
    restructure.py      智能排版：模型只说「第几行改成什么结构」，搬运在这儿
    textshape.py        文本形状的零碎判断
    tabular.py          从 markdown 表格里算数字（均值、分组、相关）
    blocks.py           拼 mermaid 语法——**模型不许自己写**
    runtime_policy.py   把这一轮的观测算成下一轮的运行参数
    replan.py           骨架重规划的收敛保护（该不该改、改完合不合法）
"""
