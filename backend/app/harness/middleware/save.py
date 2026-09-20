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
    # `source="harness"`：这是机器写回去的，**不是一次用户编辑**。计划 9.1
    # 采的是「用户拿到 AI 写的东西之后改了什么」，把 harness 自己每轮的落盘
    # 算进去，采到的就全是「用户一个字没改」。
    store.update_note(st.ctx.user, st.ctx.note_id, st.ctx.note_title, st.content,
                      source="harness")
    # **库里现在装的是哪一份**（P45 #1）。`persist_if_changed` 读它；
    # 存的是字符串本身而不是长度 / 哈希——「长度没变但字变了」也得算变
    # （`no_foreign_script` 把 `मंत्री` 换成同样长的东西就是这一档）。
    st.bag["saved_content"] = st.content
    return True


def persist_if_changed(st: State) -> bool:
    """`st.content` 跟**上一次写进库的那一份**不再逐字相同时，再落一次。

    **为什么需要第二次落库**（P45 #1，P44 走查最重的那条）：`Save` 写库在
    `after_produce`，而 `Verdict.fix` 改正文在 `before_judge`——**改在写之后**。
    于是「这一轮吐了一整串 JSON」那条判据把 JSON 从 `st.content` 里摘掉了、
    `STEP_FINISHED` 交给前端的是干净的那份、面板上写着「已经从正文里撤掉了」，
    可 `notes.content` 里躺的还是 `after_produce` 那一刻的脏正文——**重开 app
    它就摆在正文里**。P44 实拍：编辑器 119 → 119，库里 119 → 166。

    这不是 `output_not_json` 一条的事，是**一个类**：`note` / `section` 两个
    会写库的模式上，带 `fix` 的判据一共 7 条（`chart_restates_list` /
    `charts_from_tools` / `citations_exist` / `no_echoed_text` /
    `no_foreign_script` / `no_junk_tail` / `output_not_json`），条条同样落在
    `before_judge` 里。**同一件事挡住一半等于没挡**，所以修的是落库那一下的
    时机，不是七条判据各打一个补丁。

    **只在真的不一样时才写**：`after_produce` 刚写过的那一份绝大多数轮次
    一个字都不会再变，无条件再 `UPDATE` 一次会让 `notes.updated_at` 每轮
    白动两次、`middleware/edits` 那边采的「用户改了没有」也跟着糊掉。
    """
    if str(st.bag.get("saved_content") or "") == st.content:
        return False
    return persist(st)


def writes_note(st: State) -> bool:
    """这次跑会不会把正文写进用户的笔记。

    **不是「有没有 Save 这个名字」，是「这次跑的产出会不会变成那篇笔记」。**
    `middleware/edits`（计划 9.1）要问的正是这个：block 模式的 `st.content`
    是一个块、不是整篇笔记，`hooks/block.commit` 也是空的——在那儿开一行
    「AI 交了什么」，`ai_chars` 数的是块、`revision_id` 指的是没被动过的整篇，
    **两边说的根本不是同一份东西**。

    两个条件都要：这个 Mode 挂了 `Save`（note / section），而且这次跑没有把它
    摘掉（`rails_off`）。后半条跟 `persist()` 问的是同一句——出口自己认 rails
    那条规矩（批 16）在这儿照旧成立，这个函数只是让**别的 middleware** 也能
    问到同一个答案，而不是各写一句 `if`。
    """
    return (any(getattr(m, "name", "") == "save" for m in st.mode.extra_mw)
            and "save" not in st.mode.rails_off)


class Save:
    name = "save"
    # **两下，不是一下**（P45 #1）：
    #   · `after_produce` —— 这一轮写出来的字先落一次。判分那一步要几十秒，
    #     用户在这中间关掉标签页，这一轮的字得还在（这个文件开头那段）。
    #   · `after_round`  —— 这一轮**定稿**之后再落一次。判据的 `fix` 在
    #     `before_judge` 里改 `st.content`，改在上面那一下之后；不补这一下，
    #     库里留下的永远是没修过的那份（P44 问题 #1 实拍）。
    #     它紧挨着 `loop.py` 那句 `Event.step_finished(st.round, st.content)`
    #     ——**前端按它对齐正文，库里就该是同一份**。
    hooks = ("after_produce", "after_round")
    after: tuple[str, ...] = ()

    async def after_produce(self, st: State) -> None:
        persist(st)

    async def after_round(self, st: State) -> None:
        persist_if_changed(st)
