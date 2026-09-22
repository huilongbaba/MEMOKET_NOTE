// @vitest-environment jsdom
/**
 * P107：**A「点了名 ≠ 点对了名」**（收 P103 问题 #6 / P105 问题 #7）+ **B 那条横条上的日期是 UTC**（收 P105 问题 #6）。
 *
 * ── A ─────────────────────────────────────────────────────────────────────
 * P103 把切走之后那几句 toast 改成**点名是哪一篇**，而篇名读的是 handler 建起来那一刻的
 * `notes` 闭包（`onDone` 从来如此）。P105 第 ⑫ 步实拍：
 *   > 点的名里对得上这一趟标题记号「P105切走Sc7ghxj」的有 0 条；读成「另一篇笔记」的有 1 条
 * 这一批给 `notes` 加了 `notesRef`，三处点名（`awayToast` / `onDone` 切走那一支 / `notifyIfHidden`）
 * 一起换成读 `notesRef.current`——**同一个根因的同一把刀**，不是「一刀动多处」。
 *
 * ── B ─────────────────────────────────────────────────────────────────────
 * 库里 `harness_runs.created_at` 是 UTC（`store._now()`），`AgentActivity` 那条横条原来
 * 直接 `slice(0, 16)` 摆出来 ⇒ 用户看到的是 UTC：P105 实拍**本地 12:59** 跑的那一趟，
 * 卡上写着「那次跑：2026-09-22 04:58」；北京时间**早上 8 点之前**跑的，日期是**昨天的**
 * （P103 那趟就是，归一化因此读成 `<D-1>`）。`util/time.ts` 抬头逐字写着
 * 「一律转成本地时间再显示」，那一格是漏网的。**这是产品的洞，不是归一化的洞**：
 * 归一化按本地今天算是对的，产品摆出本地时间之后两边就对得上了。
 *
 * ── 这份文件**答不了**什么 ─────────────────────────────────────────────────
 *  · **真壳上那句 toast 点的名对不对**：答不了。那是走查第 ⑫ 步 `steps/switchaway105.mjs`
 *    判⑤ 升级版（P107）的事——它在真壳上现造一篇、打标题、不等落库就跑并切走。
 *  · **`App.tsx` 里那三处真的换成 ref 了没有**：形状那一半在 `scripts/check-harness-guard.mts`
 *    第 ⑥ / ⑧ 条（它读 `App.tsx` 原文、先摘注释）；这儿只核 ref 本身在不在。
 */
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AgentActivity, { type AgentRound } from '../AgentActivity'
import { fmtDateTime } from '../../util/time'
import { displayTitle } from '../../util/displayTitle'
import appSrc from '../../App.tsx?raw'

const round = (over: Partial<AgentRound> = {}): AgentRound => ({
  round: 1, cleanupOnly: false, revisions: 0, toolCalls: [], toolTruncated: false,
  scores: {}, status: '', weakest: null, policyReasons: [], policy: null,
  errors: [], dropped: [], ...over,
})

describe('A① `notes` 有了 ref（跟 `currentRef` 同一个形状、同一个理由）', () => {
  it('`notesRef` 是 `useRef<Note[]>(notes)` + `useEffect` 跟着 `notes` 走', () => {
    expect(appSrc).toMatch(/const notesRef = useRef<Note\[\]>\(notes\)/)
    expect(appSrc).toMatch(/useEffect\(\(\) => \{ notesRef\.current = notes \}, \[notes\]\)/)
  })
  it('点名那三处都走 `noteName`（**三处**：awayToast / onDone 切走那一支 / notifyIfHidden）', () => {
    const from = appSrc.indexOf('function noteHarnessHandlers(')
    const to = appSrc.indexOf('const guarded: api.NoteHarnessHandlers = {}', from)
    const region = appSrc.slice(from, to)
    expect((region.match(/\$\{noteName\(/g) ?? []).length).toBe(3)
  })
  it('`noteName` = 读 `notesRef.current` + 走 `displayTitle`（**两半缺一不可**，P107 真壳实拍）', () => {
    expect(appSrc).toMatch(/const n = notesRef\.current\.find\(\(x\) => x\.id === noteId\)\s*return n \? displayTitle\(n\) : fallback/)
  })
  it('handler 那一摞里旧的两种形状**一处都不剩**（`iconOf` 那种每次渲染现建的回调不算）', () => {
    const from = appSrc.indexOf('function noteHarnessHandlers(')
    const to = appSrc.indexOf('const guarded: api.NoteHarnessHandlers = {}', from)
    expect(from).toBeGreaterThan(0)
    expect(to).toBeGreaterThan(from)
    const region = appSrc.slice(from, to)
    expect(region).not.toMatch(/\bnotes\.find\(\(x\) => x\.id === noteId\)/)
    expect(region).not.toMatch(/\.find\(\(x\) => x\.id === noteId\)\?\.title/)
  })
})

describe('A② 第二半的实例：标题框空着、名字在正文 `# …` 里', () => {
  // P107 真壳实拍那一篇：库里 `title` 是 `''`，`content` 以 `# P107切走Scbba88（可删）` 开头。
  const n = { title: '', content: '# P107切走Scbba88（可删）\n\nP107 走查第 ⑫ 步：跑着切走再切回' }
  it('直接读 `.title` ⇒ 空串 ⇒ 落到「另一篇笔记」（只加 ref 那一版就是这样）', () => {
    expect(n.title || '另一篇笔记').toBe('另一篇笔记')
  })
  it('`displayTitle` ⇒ 用户在标签页上看到的那个名字', () => {
    expect(displayTitle(n)).toBe('P107切走Scbba88（可删）')
  })
})

describe('B `fmtDateTime` 转本地：跨过 UTC 0 点那一档日期要跟着变', () => {
  // ⚠️ 判据钉在**固定时区**上（Asia/Shanghai = UTC+8，没有夏令时），不钉「这台机器的时区」：
  //    钉后者的话这条测试在别的机器上红的理由跟对错无关。`vi.stubEnv('TZ', …)` 写的是
  //    `process.env.TZ`，Node 里改了就生效（v13+），jsdom 环境下 `Date` 还是 Node 的。
  beforeEach(() => { vi.stubEnv('TZ', 'Asia/Shanghai') })
  afterEach(() => { vi.unstubAllEnvs() })

  it('UTC 19:00 ⇒ 本地**第二天** 03:00（P103 那趟读成「昨天」的正是这一档）', () => {
    expect(fmtDateTime('2026-09-21T19:00:00+00:00')).toBe('2026-09-22 03:00')
  })
  it('P105 实拍那条：UTC 04:58 ⇒ 本地 12:58（跟那一趟的钟点对上了）', () => {
    expect(fmtDateTime('2026-09-22T04:58:12+00:00')).toBe('2026-09-22 12:58')
  })
  it('语料那篇：UTC 10:03 ⇒ 本地 18:03（走查 `28-old-rounds101-corpus` 那一行从此写 18:03）', () => {
    expect(fmtDateTime('2026-09-18T10:03:31+00:00')).toBe('2026-09-18 18:03')
  })
})

describe('B 真挂一次 `AgentActivity`：横条上摆的是本地时间', () => {
  let host: HTMLDivElement
  beforeEach(() => {
    vi.stubEnv('TZ', 'Asia/Shanghai')
    host = document.createElement('div'); document.body.appendChild(host)
  })
  afterEach(() => { host.remove(); vi.unstubAllEnvs() })

  const render = (rounds: AgentRound[]) => {
    const root = createRoot(host)
    act(() => { root.render(<AgentActivity rounds={rounds} status="" running={false} />) })
    const t = host.textContent ?? ''
    act(() => { root.unmount() })
    return t
  }
  const restored = (at: string) => round({
    restored: { at, missing: ['本轮写出的正文'], facts: '', firedChecks: [] },
  })

  it('跨 UTC 0 点：库里 `2026-09-21T19:00:00+00:00` ⇒ 卡上「那次跑：2026-09-22 03:00」', () => {
    const t = render([restored('2026-09-21T19:00:00+00:00')])
    expect(t).toContain('那次跑：2026-09-22 03:00')
    expect(t).not.toContain('2026-09-21 19:00')       // 原来 `slice(0, 16)` 摆的就是这个
  })
  it('反例（改前的形状）：直接 `slice(0, 16)` 出来的是 UTC，跟卡上摆的**不是同一串**', () => {
    const at = '2026-09-21T19:00:00+00:00'
    const t = render([restored(at)])
    expect(at.slice(0, 16).replace('T', ' ')).toBe('2026-09-21 19:00')
    expect(t).not.toContain(at.slice(0, 16).replace('T', ' '))
  })
  it('`at` 是空串 ⇒ 那半句括号整个不摆（不写「那次跑：—」）', () => {
    const t = render([restored('')])
    expect(t).toContain('这张卡是从库里读回来的骨架')
    expect(t).not.toContain('那次跑')
  })
})
