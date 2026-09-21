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
 *  · `self` —— 只有 `onDone` 一条：它**自己**处理跨篇（切走了就只提示一句、
 *    正文由服务端保存），所以从来就不在那一刀的射程里。
 *
 * ── 为什么**不是**把 `blocked` 那一摞也放行 ──────────────────────────────
 * **判据宁可窄一点。** 那一摞里有两类，各有各的账，都不是这一批的正题：
 *  · **动正文那几条**（`onRevision` / `onInsertAt` / `onDelta` 的后半 / `onTextEnd` /
 *    `onScrub` / `onDedup` / `onRoundEnd`）——放行就是 P95 A0 记的那条
 *    「A 的内容写进了 B」当场长回来。
 *  · **弹 toast / 动当前这篇右栏那几条**（`onCost` / `onCrossRun` / `onWarning` /
 *    `onSkeleton`）——放行不会写坏正文，但**它们该不该在你已经切走之后弹**
 *    是另一条判据（弹出来的话用户看不出说的是哪一篇），这一批**不动**，
 *    逐条记在 `docs/edge-cases.md`。⚠️ `onSkeleton` 里那句 `persistSkeleton(s, b, noteId)`
 *    **确实是按 noteId 落库的**，切走就丢——**那是另一处误伤，照实记，这一批不治**
 *    （治它要把 `setSpine` / `setBeats` 那半边拆开，而它没有 P99 那样的实拍判据）。
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

  // ── 一点账都不记 ⇒ 照旧拦 ──────────────────────────────────────────────
  onRevision: { verdict: 'blocked', why: '动正文：`applyRevision` 之后 `setContent`——放行就是「A 的内容写进 B」' },
  onInsertAt: { verdict: 'blocked', why: '动正文 + 滚编辑器：`prepareInsert` / `EditorView.scrollIntoView`' },
  onTextEnd: { verdict: 'blocked', why: '动正文：整篇 `fixBoldPunct` 之后 `setContent`' },
  onRoundEnd: { verdict: 'blocked', why: '动正文（用服务端的对齐）+ `pushDiff` 往编辑器加一层改动' },
  onScrub: { verdict: 'blocked', why: '动正文：服务端删了一整句，本地同一句也删' },
  onDedup: { verdict: 'blocked', why: '动正文：剥掉重复的那一段 / 行' },
  onSkeleton: { verdict: 'blocked', why: '动当前这篇的右栏：`setSpine` / `setBeats` / `setSkeletonNotes`（里头那句 persistSkeleton 是另一处误伤，见抬头）' },
  onCost: { verdict: 'blocked', why: '只弹一句 toast：切走之后弹出来看不出说的是哪一篇，另一条判据' },
  onCrossRun: { verdict: 'blocked', why: '只弹一句 toast：同 onCost' },
  onWarning: { verdict: 'blocked', why: '只弹一句 toast：同 onCost' },

  // ── 自己处理跨篇 ──────────────────────────────────────────────────────
  onDone: { verdict: 'self', why: '它自己判跨篇：切走了就只提示一句「已保存在那篇里」，正文一个字不动' },
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
