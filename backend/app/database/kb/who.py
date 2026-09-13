"""说话人标签的归一化。同一个人在不同批次的转写里写成 `speaker a` / `speaker_a` /
`Speaker A`，首页「类型 · 说话人」里并排出现 speaker a 6185 和 speaker_a 1106（第 217 轮
实拍），事实表按说话人筛也只能筛到其中一种写法。比较和分组都按归一化后的键，显示用
最常见的那种原写法。"""

from __future__ import annotations

import re

_WS = re.compile(r"[\s_]+")


def norm_who(who: str) -> str:
    return _WS.sub(" ", (who or "").strip()).lower()
