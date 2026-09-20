/** 轮次卡片上那些「攒起来」的东西。
 *
 * **为什么是一个单独的纯函数，而不是 App.tsx 里的一行**（批 24 / 计划 12.1）：
 * 原来那一行写的是 `{ ...last, checkHit: d }`——**后到的把先到的盖掉**。
 * 一轮里可以先后到达好几条 `check_hit`：连着卡满被放行的那几条（后端照发，
 * 见 `middleware/checks.STUCK_ROUNDS`）+ 最后真正短路的那一条。于是
 * 「判据命中了，界面上看不见」，跟「建了判据不等于用了判据」是同一个形状。
 *
 * 写在 App.tsx 里的 setState 回调**没有任何测试够得着**：把它改回覆盖式，
 * 全套前端闸照绿（实测）。抽成纯函数才钉得住。
 */

/** 一条代码判据命中。`check` 是**判据自己的名字**——`dimension` 答不了
 * 「哪条判据命中了」，因为五条判据同时落在 `factual_grounding` 上。 */
export type CheckHit = {
  round?: number
  check?: string
  /** 这一轮跑到第几条（分母 `checksTotal` 在 round_summary 里） */
  ran?: number
  dimension: string
  note: string
  stuck_rounds?: number
  /** `true` = 这条不是「这一轮命中」，是**收工通知**：同一条判据连响够了轮数，
   * 整个跑**停下来交最好的一轮**（后端 `middleware/checks.after_run`）。
   * 跟 `stuck_rounds` 那条「放行、照常打分」的正好相反，面板上要说两句不同的话
   * ——原来两条共用「这一轮不再拦，照常打分」，而这一条明明已经停了（P35 走查 #7）。 */
  stopped?: boolean
  /** `true` = 这条判据**只是提个醒**：它报了，但这一轮**照常花模型调用打了分**
   * （后端 `middleware/checks.py` 的 advisory 那一支 / `types.Verdict.advisory`，P58 A）。 */
  advisory?: boolean
  /** 连着几轮一次真打分都没有，于是这一轮**放行**（报了但不短路）。
   * 后端 `middleware/checks.JUDGE_FLOOR`，带的是那个连续轮数。 */
  judge_floor?: number
}

/** 这条命中该用哪一句话说。**四档互斥**，面板三句话 + 一句收工通知。
 *
 * **为什么单独抽出来**（P58 走查 #1）：AgentActivity 里原来只分两档
 * （`h.stuck_rounds ? 卡死 : 短路`），于是 `judge_floor` 放行的那一条
 * 落进了「短路」那一句，界面上写着「这一轮没再花模型调用去打分」——
 * **而那一轮恰恰是为了打分才放行的**，字面是反的。跟 P35 走查 #7
 * （停机通知写着「照常打分」）是同一个形状的洞，只是在另一支上。
 * 一个 JSX 里的三元判不出来也测不着，所以是个纯函数 + 自己的闸。
 */
export type CheckHitKind = 'stopped' | 'stuck' | 'released' | 'shortCircuit'

export function checkHitKind(h: CheckHit): CheckHitKind {
  if (h.stopped) return 'stopped'                       // 收工通知，整个跑停了
  if (h.stuck_rounds) return 'stuck'                    // 连着卡满 → 放行
  if (h.advisory || h.judge_floor) return 'released'    // 提醒 / 饿死放行 → 放行
  return 'shortCircuit'                                 // 真短路：这一轮没打分
}

/** 把一条命中记到这一轮上，**不丢掉先到的那些**。 */
export function withCheckHit<T extends { checkHits?: CheckHit[] }>(
  round: T, hit: CheckHit,
): T {
  return { ...round, checkHits: [...(round.checkHits ?? []), hit] }
}
