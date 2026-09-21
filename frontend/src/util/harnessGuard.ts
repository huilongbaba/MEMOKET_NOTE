/** 切走之后 harness 的每个事件**拦谁、放谁**（P101 B，收 P99 B 判④）。
 *
 * ── 那一刀长什么样、为什么是误伤 ──────────────────────────────────────────
 * `App.tsx` 在 P95 之前给 `noteHarnessHandlers` 统一包了一层：
 *
 *     if (k !== 'onDone' && currentRef.current?.id !== noteId) return
 *
 * 立它的理由是真的（探针实拍两次）：`onDone` 的正文对齐和骨架**把 A 的内容写进了 B**。
 * 但它是**一刀切**的——而 `writeRounds` / `patchRound` 这两条**本来就按 noteId 写**
 * （P95 A 把轮次卡改成按 note id 存的那一刀），它们根本碰不到「现在显示的那篇」。
 * 拦住它们不是安全，是**误伤**。
 *
 * **判据现成，P99 在真壳上实拍过**（`22-old-rounds99-away.txt`）：
 * 同一篇、同一个探针，**跑着切走 20 秒再切回 ⇒ 卡上「本轮写出的正文」2 → 1**
 * （切走那一轮那一整块没了），**不切走的对照是 2**。丢的正是 `onDelta` 那一句
 * `writeRounds(noteId, … streamed …)`。
 *
 * ── 这份表判的那件事，一句话 ──────────────────────────────────────────────
 * **「这条 handler 的活儿里有没有『按 noteId 记账』那一份」**，两档：
 *
 *  · `rounds` —— 有。**放行**（它自己再挡动正文那一半：记账那几句**排在
 *    `if (currentRef.current?.id !== noteId) return` 前面**，其余照旧排在后面）。
 *  · `blocked` —— 一点账都不记，整条都是**动正文 / 动编辑器 / 动当前这篇的右栏 /
 *    弹一句 toast**。**照旧拦**——它们正是那一刀本来要拦的东西。
 *  · `self` —— **自己判跨篇**：切走了不是闭嘴，是说一句**点了名**的话
 *    （「「<篇名>」：…」），正文一个字不动。P101 只有 `onDone` 一条，
 *    P103 B 判完之后是三条（加 `onCost` / `onCrossRun`）。

 * ── P103 这一批动的两处（收 P101 B 留的两条）────────────────────────────
 *  · **A（`onSkeleton`）**：从 `blocked` 挪到 `rounds`。**实拍先行**
 *    （`steps/skel103.mjs`，真壳，`LLM_MODE=adv` + 每发慢 7 秒）：
 *    **不切走 → 库里 `spine` 第 8 秒变非 0（17 字 / 3 条）；点完 262 毫秒切走 →
 *    盯了 60 秒一直是 0，跑完 0，关掉重开还是 0。**
 *    而全仓只有 `PUT /api/notes/<id>/skeleton` 一条路能把跑里现生成的骨架写进笔记
 *    （`store.set_skeleton` 唯一调用点），发它的只有前端 `persistSkeleton`
 *    ⇒ 拦住 = **那一次生成的骨架永久没了**。
 *    **拆法**：`persistSkeleton(s, b, noteId)` 提到 guard 前面（它按 noteId 落库），
 *    `setSpine` / `setBeats` / `setSkeletonNotes` / `setNoteHarnessStatus` 照旧排在 guard 后面
 *    （**那半边是「现在显示的这篇」的右栏，放行就是把 A 的骨架摆进 B**）。
 *    ⇒ **`persistSkeleton` 该放行、`setSpine`/`setBeats` 该照拦，两件事两个判。**
 *  · **B（三条 toast）**：`onCost` / `onCrossRun` 挪到 `self`（切走照弹、**点名**），
 *    `onWarning` **照拦不动**——逐条的理由写在各自的 `why` 和 `App.tsx` 里。
 *
 * ── 为什么**不是**把 `blocked` 那一摞也放行 ──────────────────────────────
 * **判据宁可窄一点。** 那一摞里有两类，各有各的账，都不是这一批的正题：
 *  · **动正文那几条**（`onRevision` / `onInsertAt` / `onDelta` 的后半 / `onTextEnd` /
 *    `onScrub` / `onDedup` / `onRoundEnd`）——放行就是 P95 A0 记的那条
 *    「A 的内容写进了 B」当场长回来。
 *  · **弹 toast 那一条**（`onWarning`）——放行不会写坏正文，但切走之后弹出来
 *    用户看不出说的是哪一篇，而且它**一轮可以来好几条**。P103 B 逐条判完之后
 *    只剩它还在这一摞里，理由写在它自己的 `why` 上。
 *
 * ── 它答不了什么 ────────────────────────────────────────────────────────
 *  · **卡上那几样明细该不该落库**：一条都答不了（P99 判③判的「不落库」）。
 *    切走之后**这一趟**的明细留得住了，**关掉重开**照旧只剩骨架——那是 P101 A 那条路。
 *  · **`App.tsx` 里那几句真的照这张表排了没有**：这份模块自己答不了，
 *    闸在 `frontend/scripts/check-harness-guard.mts`（它去读 `App.tsx` 的原文）。
 */

/** 一条 handler 在那一刀底下的处境。 */
export type GuardVerdict = 'rounds' | 'blocked' | 'self'

export type GuardEntry = {
  verdict: GuardVerdict
  /** 为什么归这一档。**不许空**，闸要求至少 8 个字——「同上」那种盖过去的写法 P89 被拦过。 */
  why: string
}

/** 22 条 handler 逐条。**键必须跟 `App.tsx` 里 `const h: api.NoteHarnessHandlers = {…}`
 *  真定义出来的那些一个不多一个不少**（闸核集合相等，不是「表里有的都在」
 *  ——那是**「测试数据比判据窄」**的那张脸）。 */
export const HARNESS_GUARD: Record<string, GuardEntry> = {
  // ── 有按 noteId 记账那一份 ⇒ 放行（记账排在自己那句 guard 前面）──────────
  onRoundStart: { verdict: 'rounds', why: '`patchRound(noteId, d.round, …)` 建这一轮的卡；动正文那半截排在自己那句 guard 后面' },
  onDelta: { verdict: 'rounds', why: '`writeRounds(noteId, … streamed …)` 就是 P99 实拍丢掉的那一块（2 → 1）' },
  onEvaluate: { verdict: 'rounds', why: '`writeRounds(noteId, …)` 写这一轮的分数 / 最弱维度；`setBeatCoverage` 那半截排在 guard 后面' },
  onPhase: { verdict: 'rounds', why: '整条只有 `patchRound(noteId, d.round, { phase, phaseLabel })` 一句' },
  onPhaseDelta: { verdict: 'rounds', why: '整条只有 `writeRounds(noteId, …)` 一句（阶段实时输出）' },
  onToolCalls: { verdict: 'rounds', why: '`patchRound(noteId, …)` 记这一轮查了几次；状态行那句排在 guard 后面' },
  onPolicy: { verdict: 'rounds', why: '整条只有 `patchRound(noteId, …)` 一句（策略调整理由）' },
  onDropped: { verdict: 'rounds', why: '整条只有 `writeRounds(noteId, …)` 一句（防线丢掉的修订）' },
  onSkills: { verdict: 'rounds', why: '整条只有 `patchRound(noteId, …)` 一句（这次跑带了哪几条技能）' },
  onCheckHit: { verdict: 'rounds', why: '`writeRounds(noteId, …)` 攒判据命中；`stuckCheckRef` 是这次跑的账，`onDone` 要读' },
  onError: { verdict: 'rounds', why: '`writeRounds(noteId, … errors …)` 记这一轮的报错；toast / 状态行排在 guard 后面' },

  onSkeleton: { verdict: 'rounds', why: '`persistSkeleton(s, b, noteId)` 按 noteId 落库（P103 A 实拍：切走 60 秒库里 spine 一直是 0，跑完 / 重开还是 0）；`setSpine` / `setBeats` 那半边排在自己那句 guard 后面，照旧拦' },

  // ── 一点账都不记 ⇒ 照旧拦 ──────────────────────────────────────────────
  onRevision: { verdict: 'blocked', why: '动正文：`applyRevision` 之后 `setContent`——放行就是「A 的内容写进 B」' },
  onInsertAt: { verdict: 'blocked', why: '动正文 + 滚编辑器：`prepareInsert` / `EditorView.scrollIntoView`' },
  onTextEnd: { verdict: 'blocked', why: '动正文：整篇 `fixBoldPunct` 之后 `setContent`' },
  onRoundEnd: { verdict: 'blocked', why: '动正文（用服务端的对齐）+ `pushDiff` 往编辑器加一层改动' },
  onScrub: { verdict: 'blocked', why: '动正文：服务端删了一整句，本地同一句也删' },
  onDedup: { verdict: 'blocked', why: '动正文：剥掉重复的那一段 / 行' },
  onWarning: { verdict: 'blocked', why: '只弹一句 toast，而且一轮能来好几条（每个 middleware 每个钩子抛一次就一条）；跑还在继续，切走之后用户一件事都做不了 ⇒ 是噪声不是通知' },

  // ── 自己处理跨篇：切走了不闭嘴，说一句**点了名**的话 ──────────────────
  onDone: { verdict: 'self', why: '它自己判跨篇：切走了就只提示一句「「X」的…已保存在那篇里」，正文一个字不动' },
  onCost: { verdict: 'self', why: '它是**停机的理由**，而 onDone 切走那一支只说「已结束」、理由那半句丢了；花掉的 token 是用户的钱，切走了也该点名说一句' },
  onCrossRun: { verdict: 'self', why: '它给的下一步动作落在「历史版本」那一栏，而那是**按篇**的；不点名等于把人送去翻错的那一篇 ⇒ 要么点名要么别弹' },
}

/** 切走之后这一条**不许跑**吗。`App.tsx` 那个包装只问这一句。
 *
 *  表里没有的键 ⇒ **拦**（保守那一侧）。**不是静默放行**：新加一条 handler 忘了
 *  归档时，拦住它最多是「那一格不更新」，放行它可能是「A 的内容写进 B」。
 *  而「忘了归档」本身有闸当场红（集合相等那一条）。 */
export function guardBlocks(k: string): boolean {
  return (HARNESS_GUARD[k]?.verdict ?? 'blocked') === 'blocked'
}

/** 归在某一档的那几条（闸和台账都要逐条点名）。 */
export function guardedKeys(v: GuardVerdict): string[] {
  return Object.keys(HARNESS_GUARD).filter((k) => HARNESS_GUARD[k].verdict === v).sort()
}
