"""memoket_kite 的私有名字还在不在。

kite_memory.py 在 import 期就伸手拿 memoket_kite 的两个下划线名字，而
requirements.txt 里这个依赖是 ``git+https://github.com/memoket/memoket-kite``
——不带 tag、不带 sha，跟着上游 HEAD 走。上游哪天改个名字，症状是**服务
起不来**，报一个 ImportError，堆栈里看不出该找谁。

这个文件的全部作用就是把那一刻提前到 CI：一条命名清楚的红测试，说明是哪个
私有名字没了、当初为什么要借它。借用私有 API 本身是权衡过的（见
kite_memory.py 里 import 处的注释），这里只负责让权衡的代价可见。
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("module, name, why", [
    ("memoket_kite.pipeline.extract", "_consolidation_round_votes",
     "整合轮的投票解析；自己重写会让两边的解析规则各自漂移"),
    ("memoket_kite.storage", "_verify_loadable",
     "写回前校验能不能读回来；没有公开等价物"),
])
def test_the_private_names_we_borrow_still_exist(module, name, why):
    import importlib

    mod = importlib.import_module(module)
    assert hasattr(mod, name), (
        f"{module}.{name} 不在了。这是 memoket-kite 的私有 API，我们借它是因为"
        f"{why}。上游改了名就在这里对齐，或者推动上游把它转正——别删掉这条测试。")
