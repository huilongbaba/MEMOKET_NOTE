"""采集用户的编辑：这个回路唯一可能的 ground truth（计划 9.1 / [MECH] §5 / [IND] §8⑥）。

## 为什么

[MECH] §5 的判断是：**整个回路没有 ground truth**。没有任何证据表明「五个
维度全 2 分」等于「用户愿意留下这篇笔记」，而 Goodhart 已经发生过一次，
代码里自己记着（`middleware/best_of.py` 开头）：

    round 2 produced two clean charts, round 3 added a single-value bar
    **to satisfy the scorer**, round 3 was delivered.

**唯一真实的信号，是用户拿到结果之后对它做了什么。** [IND] §8⑥ 给了现成的
名字和方法：PRELUDE（NeurIPS 2024，*Aligning LLM Agents by Learning Latent
Preference from User Edits*）、coactive learning——后者的假设弱到只要求
**「编辑后的文本比提出的文本更好」**，我们这儿天然成立，采集成本接近零。

## 怎么采

跑完落一份正文（`note_revisions` 里一行，`reason='harness'`、`run_id` 指回
这次跑），同时在 `harness_edits` 里开一行；用户**下一次真的改了正文再保存**
时，`store.update_note` 带 `source="user"` 把那一行关掉，记下他留下了多少字。

`note_revisions` 这张表一直在，但**跟哪一次跑无关**——所以它到今天为止用不
了。加的是那一列 `run_id` 和那张只存指针与几个数的 `harness_edits`。

## 三条边界

1. **只采集，不调参。** 样本不够时按它调参比不调更糟：判据本来就会随产出
   漂移（[IND] §8③ 的 criteria drift），拿 n=3 的编辑信号去动 25 个维度里的
   任何一个，是把噪声当方向。这张表现在**没有任何一处写回路**——
   `tests/test_harness_edits.py` 有一条闸钉着这件事。
2. **这是用户的数据。** 存的是指针和四个整数，不是第二份笔记副本（跟账本
   那条「只存 id + 一行，全文永远回 kite 取」同一个道理）。AI 那一份正文
   走的是**已经存在的**版本机制，用户那一份就是 `notes.content` 本身。
3. **绝对不碰 `notes`。** 这一批只加表、加列、加行。落库那一处认
   `rails_off`（见下），所以跑批脚本的 `rails_off=("save",)` 自动也挡住它。

## 只在「产出会变成那篇笔记」的跑上采

判据是 `middleware/save.writes_note(st)`，两档一起挡：

* **`rails_off=("save",)`** —— 批 16 的教训是「出口自己认 rails，而不是指望
  调用方记得把每一个会写库的 middleware 都列进去」。这里守的是同一个性质：
  **这次跑不许碰这篇笔记**，那就也不许往它的历史里塞一版——否则跑批脚本会往
  `note_revisions`（`db_guard` 的指纹盯着的两张表之一）里写行。
* **这个模式的产出根本不是「这篇笔记」** —— 六个 block 模式的 `st.content`
  是一个块，`hooks/block.commit` 是空的。在那儿开一行「AI 交了什么」，
  `ai_chars` 数的是块、`revision_id` 指的是**没被动过的整篇**，两边说的不是
  同一份东西；而一份指错对象的 ground truth 比没有更糟。
"""

from __future__ import annotations

from ...database import store
from ..state import State
from .save import writes_note


class Edits:
    name = "edits"
    hooks = ("after_run",)
    # 用 `harness_runs.id` 当指针，所以得等 `History` 把那一行写进去。
    after: tuple[str, ...] = ("history",)

    async def after_run(self, st: State) -> None:
        from .history import records_this_run

        if not writes_note(st):
            # 两档一起挡（`middleware/save.writes_note` 是那一份实现）：
            # ① 这次跑不许碰这篇笔记（`rails_off`），历史也不行；
            # ② 这个模式的产出根本不是「这篇笔记」——block 的 `st.content`
            #    是一个块，在那儿开一行「AI 交了什么」，`ai_chars` 数的是块、
            #    `revision_id` 指的是没被动过的整篇，两边不是同一份东西。
            return
        if not records_this_run(st):
            return              # 没进 `harness_runs` 的跑，指针会指向空气
        if not st.ctx.note_id or not (st.content or "").strip():
            return
        run_id = str(st.bag.get("run_id") or "")
        if not run_id:
            return              # 没挂 `Ledger` 的模式：没有 run_id 就没有关联
        try:
            rev = store.snapshot_note(st.ctx.user, st.ctx.note_id,
                                      store.REVISION_REASON_HARNESS, run_id=run_id)
            if not rev:
                return
            store.open_harness_edit(
                st.ctx.user, st.ctx.note_id,
                run_id=run_id, key=f"{st.mode.key}:{st.ctx.note_id}",
                revision_id=rev["id"],
                # 开跑时正文有多长——用来分开「这次跑写的」和「本来就有的」。
                # `loop.py` 每次跑都存这一份（批 21 为 `no_audit_voice` 的
                # 量程加的），这里是它的第二个读者。
                base_chars=len(str(st.bag.get("content_at_start") or "")),
                ai_chars=len(st.content or ""))
        except Exception:                                   # noqa: BLE001
            pass        # 采集不承重：写不进去也不能影响这次跑交出去的正文
