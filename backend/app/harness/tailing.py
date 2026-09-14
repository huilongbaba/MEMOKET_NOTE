"""撞 token 上限之后「把半句写完」那一步的两道护栏。

用户报的现场（第 569 轮）：一段中文正文的最后是

    ……这里需要补上的不是一组预设转化率，而是每一层的实际人数和流失原因。eriwa

句号之后凭空多了 `eriwa`。来路是续尾：主流 `finish_reason == "length"` 就再问模型一次
「接着最后那半句写完」，而原来的代码**不管模型回什么都往正文里拼**，还是边流边拼，
拼上去就撤不回来了。

两道护栏，都只用确定性判断，不再多花模型调用：

1. `needs_tail()` —— 撞上限 ≠ 切在句子中间。正文最后一个字符已经是句末标点 /
   闭合的代码块 / 表格行，就不该续：这时候模型没有「半句」可接，它只能自己找点
   东西写，`eriwa` 这种碎片正是这么来的。
2. `acceptable_tail()` —— 续回来的东西不像接上去的半句就丢掉。判据是语言：中文语境
   下的续尾一定带中文；纯 ASCII 又没有句末标点的碎片不是续写，是噪声。

丢弃时**整段都不 yield**，客户端的增量流里也不会有——不然轮末对齐会报「本地比服务端多几个字」。
"""
from __future__ import annotations

import re

# 句末 / 结构收尾：到这儿为止是完整的一句或一个块，没有半句要接
# 半角 `)` / `"` 不算收尾：代码里太常见（`print(1)`），而正文里的括号收尾是全角
_SENTENCE_TAIL = set("。！？!?…；;：:」』）】》”’")
_CJK = re.compile(r"[一-鿿぀-ヿ]")


def needs_tail(text: str) -> bool:
    """这段正文是不是真的停在半句上（值不值得再花一次续尾调用）。"""
    t = (text or "").rstrip()
    if not t:
        return False
    if t.count("```") % 2 == 1:                    # 代码块没闭合：一定要续，不然整段渲染坏掉
        return True
    if t.endswith("```") or t.endswith("~~~"):     # 代码块刚闭合
        return False
    last_line = t.rsplit("\n", 1)[-1].strip()
    if last_line.startswith("|") and last_line.endswith("|"):   # 表格整行写完了
        return False
    if last_line.startswith("#"):                  # 停在一个标题上，下一轮从正文写起
        return False
    return t[-1] not in _SENTENCE_TAIL


def acceptable_tail(text: str, tail: str) -> bool:
    """续回来的这段要不要拼上去。"""
    t = (tail or "").strip()
    if not t:
        return False
    # 正文尾部是中文语境（看最后 30 字），续尾却一个中日文字都没有、也没有句末标点：
    # 这不是「接着半句写完」，是模型自己找话说（实拍 `eriwa`）
    if _CJK.search((text or "")[-30:]) and not _CJK.search(t):
        if not any(ch in _SENTENCE_TAIL for ch in t):
            return False
    return True
