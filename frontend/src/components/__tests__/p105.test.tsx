// @vitest-environment jsdom
/**
 * P105 C：**轮次卡上那一格「这一轮少了什么」**（收 P103 问题 #7）。
 *
 * ── P103 逐字留下来的那一条 ───────────────────────────────────────────────
 *   > `onWarning` 被拦掉之后，**「这一轮少了哪个能力」在界面上就没有第二个出处了**
 *   > （轮次卡上没有这一格）。要接就得先给轮次卡加一格「这一轮少了什么」——**那是另一刀**。
 *
 * 这一批就是那一刀。**它切成了两半，两半各判各的**：
 *  · **记**：`onWarning` 从 `blocked` 挪到 `rounds`，`writeRounds(noteId, … warnings …)`
 *    排在自己那句 guard **前面** ⇒ 切走了这一格照样记（这是**这一篇这一轮**的账）。
 *  · **弹**：那句红字 toast 照旧排在 guard **后面** ⇒ 切走之后**一个字都不弹**。
 *    P103 B ③ 判的「照拦」说的就是这半边，这一批**一个字没动**。
 *
 * ── 这份文件**答不了**什么（别含糊过去）──────────────────────────────────
 *  · **`App.tsx` 里那几句真的这么排了没有**：答不了，那在
 *    `scripts/check-harness-guard.mts`（它读 `App.tsx` 的原文；第 ⑦ 条是这一批加的）。
 *  · **真壳上那一格用户真看得见吗**：答不了。那是走查 `steps/warn105.mjs` 的事
 *    （真壳：骨架存着半句 ⇒ 每一轮一条 warning，跑着切走再切回，卡上那一格还在）。
 *  · **关掉重开还在不在**：**不在**——这一格不落库，`store.ROUND_SKELETON_MISSING`
 *    里逐字写着「本轮少了哪个能力」，读回来的那张卡会照实标出来。
 */
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import AgentActivity, { type AgentRound, type RoundWarning, warningLine, warningsHead }
  from '../AgentActivity'
import { HARNESS_GUARD, guardBlocks, guardedKeys } from '../../util/harnessGuard'

const W = (over: Partial<RoundWarning> = {}): RoundWarning => ({
  middleware: '骨架', hook: 'skeleton',
  error: '这篇存着的骨架第 2 条是半句（被旧版 60 字上限切过，句子没写完）', ...over,
})

const round = (over: Partial<AgentRound> = {}): AgentRound => ({
  round: 1, cleanupOnly: false, revisions: 0, toolCalls: [], toolTruncated: false,
  scores: {}, status: '', weakest: null, policyReasons: [], policy: null,
  errors: [], dropped: [], ...over,
})

describe('C① 那张表：`onWarning` 记账那一半放行了', () => {
  it('它归 `rounds`', () => {
    expect(HARNESS_GUARD.onWarning.verdict).toBe('rounds')
    expect(guardBlocks('onWarning')).toBe(false)
  })
  it('它的「为什么」里点了那个调用的名字 + **点明那句 toast 照旧不弹**', () => {
    expect(HARNESS_GUARD.onWarning.why).toContain('writeRounds(noteId')
    expect(HARNESS_GUARD.onWarning.why).toContain('guard 后面')
    expect(HARNESS_GUARD.onWarning.why).toContain('不弹')
  })
  it('`self` 那一档**没跟着涨**（切走了会说话的还是那三条）', () => {
    expect(guardedKeys('self')).toEqual(['onCost', 'onCrossRun', 'onDone'])
  })
  it('动正文那几条照旧拦（这一刀没蹭到别人）', () => {
    for (const k of ['onRevision', 'onInsertAt', 'onTextEnd', 'onRoundEnd', 'onScrub', 'onDedup']) {
      expect(guardBlocks(k), k).toBe(true)
    }
  })
  it('22 条一条不少地归着档', () => {
    expect(Object.keys(HARNESS_GUARD)).toHaveLength(22)
  })
})

describe('C② 那两句话：**一处定义**（卡上那一格和那句 toast 读的是同一份）', () => {
  it('`warningLine` 逐字：点了哪一步 + 后端的原话', () => {
    expect(warningLine(W())).toBe(
      '「骨架」这一步出错了，本轮少了这个能力：'
      + '这篇存着的骨架第 2 条是半句（被旧版 60 字上限切过，句子没写完）')
  })
  it('抬头把**几条**真数出来（一轮能来好几条，写死「一个」会把第二条藏起来）', () => {
    expect(warningsHead([W(), W({ middleware: '成本' })]))
      .toBe('本轮少了 2 个能力（骨架、成本），这一轮是在少了这一步的证据上跑完的')
  })
  it('同一步来两条 ⇒ 抬头里那一步只报一次，**条数还是 2**', () => {
    expect(warningsHead([W(), W({ hook: 'before_run' })]))
      .toBe('本轮少了 2 个能力（骨架），这一轮是在少了这一步的证据上跑完的')
  })
})

describe('C③ 真挂一次 `AgentActivity`：那一格用户看得见', () => {
  let host: HTMLDivElement
  beforeEach(() => { host = document.createElement('div'); document.body.appendChild(host) })
  afterEach(() => { host.remove() })

  const render = (rounds: AgentRound[]) => {
    const root = createRoot(host)
    act(() => { root.render(<AgentActivity rounds={rounds} status="" running={false} />) })
    const t = host.textContent ?? ''
    const details = host.querySelectorAll('details').length
    act(() => { root.unmount() })
    return { t, details }
  }

  it('有 warning ⇒ 抬头 + 那一条原话都在屏幕上', () => {
    const { t } = render([round({ warnings: [W()] })])
    expect(t).toContain('本轮少了 1 个能力（骨架）')
    expect(t).toContain('这篇存着的骨架第 2 条是半句')
  })
  it('**一轮两条 ⇒ 两条都摆出来**（后到的不许把先到的盖掉）', () => {
    const { t } = render([round({ warnings: [W(), W({ middleware: '成本', error: '这次跑有 1 笔用量没记上' })] })])
    expect(t).toContain('本轮少了 2 个能力（骨架、成本）')
    expect(t).toContain('这次跑有 1 笔用量没记上')
  })
  it('**没折叠**（`<details>` 收着的时候读不到里头的字，收起来的出处等于没有出处）', () => {
    const { t, details } = render([round({ warnings: [W()] })])
    expect(details).toBe(0)
    expect(t).toContain('本轮少了')
  })
  it('一条都没有 ⇒ 屏幕上**一个字都没有**（不留空壳）', () => {
    const { t } = render([round()])
    expect(t).not.toContain('本轮少了')
  })
  // ⚠️ **数的是抬头那一句**（`本轮少了 <数> 个能力`），不是「本轮少了」这四个字：
  //    那四个字在**抬头**和**那一条原话**（`warningLine`：「…本轮少了这个能力：…」）
  //    里**各出现一次**，一张卡就是 2。第一版正是数的那四个字，当场红
  //    ——**「同一个字面量可能有第二份」**，这个仓咬过九次，这是第十次。
  it('两轮各记各的（不是一整个 App 一份）', () => {
    const { t } = render([round({ round: 1, warnings: [W()] }), round({ round: 2 })])
    expect((t.match(/本轮少了 \d+ 个能力/g) ?? []).length).toBe(1)
    expect((t.match(/本轮少了/g) ?? []).length).toBe(2)   // 抬头 1 + 那一条原话 1
  })
})
