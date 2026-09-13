"""说话人标签的归一化。同一个人在不同批次的转写里写成 `speaker a` / `speaker_a` /
`Speaker A`，首页「类型 · 说话人」里并排出现 speaker a 6185 和 speaker_a 1106（第 217 轮
实拍），事实表按说话人筛也只能筛到其中一种写法。比较和分组都按归一化后的键，显示用
最常见的那种原写法。"""

from __future__ import annotations

import re

_WS = re.compile(r"[\s_]+")


def norm_who(who: str) -> str:
    return _WS.sub(" ", (who or "").strip()).lower()


# 录音转写的说话人标签（Speaker A / speaker_c / 说话人 1…）：抽取会把它们当实体。
# 跟前端 util/kbNoise.ts 的 SPEAKER_TAG 同一条正则，两边都要认得出。
# 字母标签必须带分隔（Speaker A / speaker_c），不然「speakers」「speaker phone」也算（第 460 轮前端测试抓的）；
# 数字标签可以贴着（Speaker1 / 说话人2）
_SPEAKER_TAG = re.compile(r"^(speaker(?:[\s_-][a-z]|[\s_-]?\d{1,2})|说话人(?:\s?[a-z]|\s?\d{1,2})|发言人(?:\s?[a-z]|\s?\d{1,2}))$", re.I)


def is_speaker_tag(name: str) -> bool:
    return bool(_SPEAKER_TAG.match((name or "").strip()))
