"""Persist after every round, not just at the end.

A run takes minutes. If the user closes the tab at round 6, the five rounds
already written have to survive. ``commit`` in the loop's ``finally`` is a
second line of defence for that, but per-round saving is what makes a
half-finished run useful rather than merely recoverable.

Not in BASE: block generation has nothing to persist -- the block goes
straight to the editor.

**这个文件里的 `persist()` 是 harness 全仓唯一一处写用户笔记的地方**，
而这条规矩是 2026-09-18（批 16）拿两篇真实笔记换来的，见下面那段注释。
"""

from __future__ import annotations

from ...database import store
from ..state import State


def persist(st: State) -> bool:
    """把正文落库。**harness 里写用户笔记只许走这一处。**

    **为什么非要收成一个函数**（批 16 的事故，这已经是第三次写坏真实笔记）：

    跑批脚本一直靠 `rails_off=("save",)` 来保证「这次跑不碰用户的笔记」——
    `loop.run` 按 `name` 把 middleware 过滤掉，看起来严丝合缝。台账批 14 的
    复盘甚至写着「`rails_off=("save",)` 本身是好的」，然后去猜是不是有人直接
    打了 HTTP 路由。

    **不是。** `middleware/revise.py` 自己也在调 `store.update_note`
    （修订应用成功、或者清掉元话语之后要落一次，免得跑到一半断了修订白做），
    而 `rails_off` 只摘掉了 `Save` 这一个。批 16 的真跑脚本拿**真实 note_id**
    装 `ToolContext`，12 次跑下来把 `309f19202309` 从 30588 字写成 4085 字、
    `06647b9c2031` 从 2762 写成 2937，标题双双被改成「批16对照」。
    （批 15 没出事纯属侥幸：它的种子用的不是真实 note_id，
    `UPDATE … WHERE id=?` 一行都没匹配上。）

    所以这里做两件事，缺一不可：
      1. **写库只有一个出口**，`Revise` 反过来调它——两处各写一份，
         下一个「摘掉写库」的开关又会只盖住其中一处；
      2. **出口自己认 `rails_off`**，而不是指望调用方记得把每一个会写库的
         middleware 都列进去。判据要守的是「这次跑不许碰笔记」这个**性质**，
         不是「save 这个名字有没有出现在列表里」这个**写法**。
    """
    if "save" in st.mode.rails_off:
        return False
    if not st.content.strip():
        return False
    store.update_note(st.ctx.user, st.ctx.note_id, st.ctx.note_title, st.content)
    return True


class Save:
    name = "save"
    hooks = ("after_produce",)
    after: tuple[str, ...] = ()

    async def after_produce(self, st: State) -> None:
        persist(st)
