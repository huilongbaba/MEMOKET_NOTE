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
}

/** 把一条命中记到这一轮上，**不丢掉先到的那些**。 */
export function withCheckHit<T extends { checkHits?: CheckHit[] }>(
  round: T, hit: CheckHit,
): T {
  return { ...round, checkHits: [...(round.checkHits ?? []), hit] }
}
