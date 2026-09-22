/** P103：`onSkeleton` 那处误伤（A）+ 三条 toast 切走之后该不该弹（B）。
 *
 * ── 这份测的是**那张表的判**，不是「真的留住了没有」────────────────────────
 * 「切走之后骨架到底落没落库」只有真壳上跑一趟才答得了，那份实拍在
 * `frontend/scripts/walkthrough/steps/skel103.mjs`（P103 走查日志
 * `31-skel103-*` / `32-skel103-*`）：**不切走 → 库里 `spine` 第 8 秒变非 0；
 * 点完 262 毫秒切走 → 盯了 60 秒一直是 0、跑完 0、关掉重开还是 0。**
 * 而「`App.tsx` 里那几句真的照这张表排了没有」在 `scripts/check-harness-guard.mts`
 * （它读 `App.tsx` 的原文）。这份只核**表本身**。
 *
 * ⚠️ 判词**不照抄要治的洞**：下面每一条写的是**改完之后该成立的那件事**，
 *    不是「onSkeleton 被拦住了」。
 */
import { describe, expect, it } from 'vitest'

import { HARNESS_GUARD, guardBlocks, guardedKeys } from '../../util/harnessGuard'

describe('A `onSkeleton`：落库那一半放行，摆右栏那一半照拦', () => {
  it('它归 `rounds`（有按 noteId 落库的那一份）', () => {
    expect(HARNESS_GUARD.onSkeleton.verdict).toBe('rounds')
  })
  it('`guardBlocks` 不再拦它 —— 切走之后 `persistSkeleton(s, b, noteId)` 照样跑', () => {
    expect(guardBlocks('onSkeleton')).toBe(false)
  })
  it('它的「为什么」里点了那个调用的名字（不是一句「动右栏的」）', () => {
    expect(HARNESS_GUARD.onSkeleton.why).toContain('persistSkeleton')
  })
})

describe('B 三条 toast：**逐条判**，答案不一样', () => {
  it('`onCost` 归 `self`：切走之后照弹，但自己点名', () => {
    expect(HARNESS_GUARD.onCost.verdict).toBe('self')
    expect(guardBlocks('onCost')).toBe(false)
  })
  it('`onCrossRun` 归 `self`：它给的下一步落在按篇的「历史版本」上，不点名会送错篇', () => {
    expect(HARNESS_GUARD.onCrossRun.verdict).toBe('self')
    expect(guardBlocks('onCrossRun')).toBe(false)
  })
  // ⚠️ **P105 C 动了这一条，但只动了半边**：`onWarning` 挪进了 `rounds`
  //（`writeRounds(noteId, … warnings …)` 记这一轮少了哪个能力，切走照记），
  // 而 **P103 判的那半边——「那句红字 toast 切走之后不弹」——一个字没动**：
  // 那句 toast 照旧排在自己那句 guard 后面。
  // 源码那一头由 `scripts/check-harness-guard.mts` 第 ⑦ 条钉着
  //（`rounds` 那一档里每一处 `toast(` 的下标都大于 guard 的下标）。
  // **这儿不把判词改成「照旧拦」**：那句话现在是假的，而一条假的判词比没有更糟。
  it('`onWarning` 那句红字 toast **切走之后照旧不弹**（P105 C 只挪了记账那一半）', () => {
    expect(HARNESS_GUARD.onWarning.verdict).toBe('rounds')
    expect(HARNESS_GUARD.onWarning.why).toContain('guard 后面')
    expect(HARNESS_GUARD.onWarning.why).toContain('不弹')
  })
  it('三条的「为什么」**各写各的**（不是一句「同 onCost」盖过去）', () => {
    const whys = ['onCost', 'onCrossRun', 'onWarning'].map((k) => HARNESS_GUARD[k].why)
    expect(new Set(whys).size).toBe(3)
    for (const w of whys) expect(w).not.toContain('同 onCost')
  })
  it('`self` 那一档现在是三条，**逐条点名**（不钉「正好几条」那种会变的数）', () => {
    expect(guardedKeys('self')).toEqual(['onCost', 'onCrossRun', 'onDone'])
  })
})

describe('没被这一刀带走的（回归）', () => {
  it('动正文那六条**照旧拦**（放行就是「A 的内容写进 B」当场长回来）', () => {
    for (const k of ['onRevision', 'onInsertAt', 'onTextEnd', 'onRoundEnd', 'onScrub', 'onDedup']) {
      expect(guardBlocks(k), k).toBe(true)
    }
  })
  it('P99 实拍那条（`onDelta`）还放行着', () => {
    expect(guardBlocks('onDelta')).toBe(false)
  })
  it('22 条一条不少地归着档', () => {
    expect(Object.keys(HARNESS_GUARD)).toHaveLength(22)
  })
  it('表里没有的键 ⇒ **拦**（保守那一侧，不是静默放行）', () => {
    expect(guardBlocks('onSomethingP103NobodyFiled')).toBe(true)
  })
})
