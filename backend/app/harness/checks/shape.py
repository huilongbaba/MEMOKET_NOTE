"""这一轮**产出的形状**对不对——不对就不落进正文（P37 #1 / P35 #2）。

## 这条修的是什么

P35 实拍（`p35-B-harness-streamjson-light`）：智能续写「写」这一步吐了一整串
`{"text": …, "reason": …}`，**两段整串落进正文、还跟着进了目录**，117 → 211 字，
**一句话都不说**。P37 在后端把它复现成一次零调用的真跑：53 → 169 字，
两段 JSON 原样待在正文里，而当轮唯一响过的判据是 `no_echoed_text`
（它说的是「这两段重复了」——**指错了地方**，那是 JSON 撞 JSON 的副作用）。

## 为什么闸装在这里，而不是前端

P35 已经量过前端那条路：流式增量走 `App.tsx onDelta → streamJoin.insertStreamed`，
**逐 token 落地**。在那儿拦拦不住（拿到第一个 `{` 时不知道整段是什么），
落完再撤又会跟 `undoRound` 打架。正确的位置是判据层：走已有的
⚑ / 自动重试 / 「这一轮不再拦」那一套，`STEP_FINISHED` 带着**服务端的权威正文**
回去，前端 `onRoundEnd` 本来就按它对齐——**不用改前端一行**。

## 判据宁可窄（跟 P32 `blockShape.ts` 逐字同一条）

只认「**整段能 `json.loads` 成对象 / 数组**」这一档：

* 只看开头那个 `{` 会把「{产品名} 的定价还没定，先看 {留存}」这种正常句子拦下来；
* 块生成那三条（该是表格 / 该有围栏 / 该有图片）**一条都不搬**——长文续写写的是
  一段人话，形状本来就只有这一种，拿「该是表格」去卡它会把「帮我改成一张表」判死。

**误伤比漏报贵**：用户眼睁睁看着跑完几十秒然后被拦下，比漏掉一次贵得多。

## 撤正文那一刀也是窄的

`fix` 只摘掉**这次跑新写出来的**、本身是整串 JSON 的自然段
（开跑前正文里就有的段落一个字不动——用户自己笔记里贴了一个 ```json 围栏，
不许被这条判据吃掉）。
"""

from __future__ import annotations

import json
import re

from ..state import State
from ..types import Verdict
from .pick import pick_dimension

# 段落之间的分隔：一个空行及以上。
_PARA_SPLIT = re.compile(r"\n{2,}")
_FENCE_HEAD = re.compile(r"^```[A-Za-z0-9_-]*\s*\n")


def _unfence(text: str) -> str:
    """剥掉整段外面的代码围栏（模型爱把产出裹一层 ```），**只用来判形状**，不改落进正文的字。

    跟 `frontend/src/editor/blockShape.unfence` 是同一条，逐行对着写的。
    """
    s = (text or "").strip()
    if not s.startswith("```"):
        return s
    m = _FENCE_HEAD.match(s)
    if not m:
        return s
    inner = s[m.end():]
    j = inner.rfind("```")
    return (inner if j < 0 else inner[:j]).strip()


def looks_like_json(text: str) -> bool:
    """整段是不是一个 JSON 对象 / 数组。**要真能 parse**。

    `frontend/src/editor/blockShape.looksLikeJson` 的 Python 孪生——两边逐字同一条判据，
    `tests/test_p37.py` 里有一条闸拿同一组样本对着钉。
    """
    s = _unfence(text)
    if not ((s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]"))):
        return False
    try:
        v = json.loads(s)
    except (ValueError, TypeError):
        return False
    return isinstance(v, (dict, list))


def json_paragraphs(content: str, before: str = "") -> list[str]:
    """`content` 里**本身就是一整串 JSON** 的自然段，`before` 里已经有的那些除外。

    `before` = 开跑时的正文（`bag["content_at_start"]`）。不给的话就什么都不排除
    ——那只用在单测里，真跑一定给得出来。
    """
    old = {p.strip() for p in _PARA_SPLIT.split(before or "") if p.strip()}
    out = []
    for para in _PARA_SPLIT.split(content or ""):
        p = para.strip()
        if p and p not in old and looks_like_json(p):
            out.append(p)
    return out


def drop_json_paragraphs(content: str, before: str = "") -> str:
    """把那几段摘掉，顺手把留下的空行压平。纯函数——`Verdict.fix` 的契约。"""
    bad = set(json_paragraphs(content, before))
    if not bad:
        return content
    keep = [p for p in _PARA_SPLIT.split(content or "") if p.strip() not in bad]
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(keep).strip())


def output_not_json(st: State) -> Verdict | None:
    """这一轮**整段**答的是一串 JSON，不是能写进正文的内容。

    量程是 `st.fresh`（**这一轮流出来的字**），不是整篇正文：用整篇去判的话，
    用户自己笔记里贴的一段 JSON 会让这条判据每一轮都响，而模型一个字都改不动它
    ——那正是第 601 轮 `no_placeholder` 那次死锁的形状。

    命中之后三件事一起发生（`middleware/checks.py` 那一段的既有机制，不新开路）：

      1. `fix` 把那几段从正文里摘掉 → **这一轮的产出不落正文**；
      2. `fix_done` 说「我管的那件事修好了」→ 正文留下摘完的那版，
         判据**照旧命中**（`st.fresh` 没变，它本来就是「这一轮答错了形状」这件事），
         于是短路打分 + 发 ⚑ 事件；
      3. 命中的 `message` 进 `Evaluation` → `State.steer` → 下一轮写作提示里的
         「上一轮的问题，这一轮要解决」——**下一轮被要求重写**。
    """
    fresh = (st.fresh or "").strip()
    if not fresh or not looks_like_json(fresh):
        return None
    before = str(st.bag.get("content_at_start") or "")
    return Verdict(
        # 跟 `no_foreign_script` / `no_junk_tail` 逐字同一条理由：形状是**机械缺陷**，
        # block 模式打「贴不贴上下文」（`fits_context`），长文两个模式没有这一维
        # 就落 `checks.pick.MECHANICS` 兜底桶（`coherence` 不许当垃圾桶，见 `pick.py`）。
        # 它带 `fix`、正文一定摘得掉，所以这一维实际上永远到不了打分器 / `Repair`。
        pick_dimension(st, "fits_context"),
        "这一轮整段答的是一串 JSON，不是能写进正文的内容——已经从正文里撤掉了。"
        "这一轮重写：直接输出 markdown 正文，不要输出 JSON、不要键值对、不要把整个响应"
        "再塞进一个字段里。",
        fix=lambda text: drop_json_paragraphs(text, before),
        # 「我管的那件事」= 正文里不再有这一轮那几段 JSON。修好了正文就留下，
        # 判据仍按「这一轮答错了形状」再报一次（两件事，各说各的——P23 #1 / P26 #3）。
        fix_done=lambda text: not json_paragraphs(text, before),
        fix_note="把这一轮那段整串 JSON 从正文里撤掉了（它没有落进正文）",
    )
