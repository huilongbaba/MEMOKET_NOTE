"""编辑器功能里既不是 agent、也不是知识库的那部分。

    outline.py      markdown 大纲：层级、下一个空的小节、结构有没有被压平
    restructure.py  智能排版：模型只说「第几行改成什么结构」，搬运在这儿
    textshape.py    文本形状的零碎判断
    vision.py       图片转表格：把一张图问给多模态模型
    profile.py      用户的写作偏好

前三个只依赖标准库，给个字符串就能测（见 tests/test_layering.py 的
纯度断言）。``vision`` 要调模型，但它服务的是一个编辑器功能，不是 agent
的一环——这个区分是实扫「谁在用」得出的，按感觉分过一次就分错了。
"""
