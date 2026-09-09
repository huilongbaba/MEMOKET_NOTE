"""一条 check 该打翻哪一维。

单独成文件，不是放在 ``checks/__init__.py`` 里——放那儿会绕成一个环：
包的 ``__init__`` 要 import 三个 check 模块来再导出，而三个 check 模块
都要 ``from . import pick_dimension``。它能跑只是因为函数定义**恰好**写在
那几行 import 之前；谁把 import 挪到文件顶部（每个 linter 都会这么建议）
就当场 ImportError。

一个只在「行的顺序」上成立的结构，迟早会被一次无害的整理弄坏。
"""

from __future__ import annotations

from ..state import State


def pick_dimension(st: State, *candidates: str) -> str:
    """这条 check 该打翻哪一维——**按当前 Mode 实际有的那些维度挑**。

    以前是写死的，而一条 check 被多个 Mode 共用：``no_fake_charts`` 写死打
    ``has_charts``，在数据可视化模式下对（那个模式的维度就叫这个），在智能
    插图模式下就打了一个**这个模式根本没有的维度**——它那一维叫
    ``chart_validity``。24 个「check × mode」组合里有 8 个是这样。

    后果不大但很别扭：Evaluation 里会出现一个模型从来不会打的维度名，
    喂回下一轮的诊断也顶着一个模型没见过的标签。

    两个维度名不是命名不统一——``has_charts`` 判的是「图有没有信息量」，
    ``chart_validity`` 判的是「图是不是工具产出的」，是不同的轴。所以修法
    不是统一命名，是让 check 在候选里挑这个 Mode 认识的那个。

    一个都没匹配上就退回第一个候选（不炸），而 ``test_harness_modes`` 里
    有一条断言保证这种情况在配置阶段就被发现。
    """
    have = {d.name for d in st.mode.dims}
    return next((c for c in candidates if c in have), candidates[0])
