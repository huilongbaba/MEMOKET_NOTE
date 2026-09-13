"""字数：跟前端 `util/wordCount.ts` 同一条规则（第 547 轮）。

状态栏 / 信息面板用前端的 wordCount（去空白、markdown 记号、图片整条、链接地址、引用标记），
历史版本和最近删除的「N 字」原来是后端 `len(content)`——同一篇两个数（8330 vs 9613）。
这里照抄一遍，`scripts/check-wordcount-parity` 拿样本对拍。放在 database/ 而不是 util/：分层测试只允许 store 从 util 拿 config。
"""
from __future__ import annotations

import re

_CITE = re.compile(r"\[[A-Za-z][\w-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+\]")
_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$", re.M)
_LINE_MARK = re.compile(r"^\s*(#{1,6}|[-*>+]|\d+\.)\s+", re.M)
_INLINE_MARK = re.compile(r"[*_`|~]")
_WS = re.compile(r"\s+")


def word_count(content: str) -> int:
    s = content or ""
    s = _IMG.sub("", s)
    s = _LINK.sub(r"\1", s)
    s = _CITE.sub("", s)
    s = _TABLE_SEP.sub("", s)
    s = _LINE_MARK.sub("", s)
    s = _INLINE_MARK.sub("", s)
    s = _WS.sub("", s)
    return len(s)
