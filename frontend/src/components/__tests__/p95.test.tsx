// @vitest-environment jsdom
/**
 * P95 A（第 817 轮）：**右栏摆的那叠轮次卡，得是这一篇的**——收 P93 问题 #1。
 *
 * ── P93 实拍到、量清了、判「这一批不改」的那个洞 ──────────────────────────
 *   > 在 A 篇跑完 2 轮续写后 ⌘K 新建一篇**空**笔记（`0 字`、正文空），
 *   > 右栏「计划」写着 **`计划 2`**，底下摆着 **A 篇那两轮的执行记录**，
 *   > 连「本轮写出的正文（72 字）」都在。
 *
 * 根因：`agentRounds` 是**一整个 App 一份**的 `useState`，只在 harness 开跑那一刻
 * 清一次，**没有任何一条「换篇就清」的路**。
 *
 * P93 同时写着**这条闸抓不到它**：
 *   > P93 A 那条通用闸抓不到它：那一格「有字」，只不过字是别人的。
 * ——**这份文件就是那条抓得到的闸。**
 *
 * ── 为什么不是一行 `useEffect(() => setAgentRounds([]), [current?.id])` ────
 * P17 给 `verifyResult` / `roundDiff` 各立过一条那样的 effect，形状是现成的。
 * 这一批**先读了那两条**，结论是**这一条不该跟它们一样**：
 *
 *   · `verifyResult` 是「**按 A 的选区**算出来的校验结果」——换篇之后它说的那一段
 *     根本不在屏幕上，**清掉之后没有任何东西该回来**；
 *   · `roundDiff` 是「给编辑器的**一条消息**」，层本身活在编辑器的 field 里，
 *     **消息发过就该作废**；
 *   · 轮次卡是**这一篇的一段历史**，且**只活在内存里**（不落库）。照抄那个形状 ⇒
 *     「跑着 harness 切走再切回，这一次跑的卡**永久丢**」。
 *
 * ⇒ 正经改法是 P93 自己写下的那个：**按 note id 存**（`util/roundsByNote.ts`）。
 *
 * ── 这份文件核什么（三块，**分工写清楚**）────────────────────────────────
 *  ① **源码侧**（`util/roundsWiring.ts` 从 `App.tsx` 现解）：屏幕上那份卡是
 *     `roundsFor(<表>, current?.id)` 取的、每一处写入都点名了写给哪一篇、
 *     `planTabContent` 和 `<AgentActivity>` 两处喂的是同一份、
 *     直接动那张表的地方正好 1 处。**回退成一个全 App 一份的 `useState` ⇒ 当场红。**
 *  ② **真挂一次**（真 `createRoot` + 真 `RightPane` + 真 `AgentActivity` +
 *     真 `planTabContent`）：表里只有 A 的两轮，
 *       · 现在开着 B（新建的空笔记）⇒ 「计划」那一格**没有角标**、
 *         底下**一个「第 N 轮」都没有**，摆的是 `PLAN_EMPTY_HINT`（那是 P91 A 接的那条路）；
 *       · **切回 A** ⇒ 角标 `2`、两张卡都在。**这一条就是那行 `useEffect` 的代价**：
 *         照那条路改的话，这一格在切回来之后是空的。
 *       · 虚拟页（`current === null`）⇒ 一张卡都读不到。
 *  ③ **那两条纯函数自己的例 / 反例**（`roundsFor` / `writeRoundsIn` /
 *     `isNoteIdVar` / `readRoundsWiring` 解不出来要抛）。
 *
 * ── 它答不了什么（**这一段别含糊过去**）──────────────────────────────────
 *  · **切走的那几秒里到达的事件丢不丢**：答不了，这一批也没改那件事
 *    （`App.tsx` 那个 `guarded` 包装在 HEAD 上就是那么拦的）。
 *  · **`App.tsx` 真跑起来长什么样**：第 ② 块挂的是**这份文件自己搭的** `PaneTab`
 *    （用的是真模块），跟 P93 那一条同一个射程。「App 真跑起来摆的就是这个」
 *    在**真壳上**量——`steps/rounds95.mjs`，走查表里那一行。
 *  · **那一格空的时候有没有字**：那是 **P93 A** 那 17 条在盯的，**别在这儿抄第二份**。
 *    这一条问的是另一件事：**那些字是不是这一篇的**。
 */
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import appSrc from '../../App.tsx?raw'
import AgentActivity, { type AgentRound } from '../AgentActivity'
import RightPane, { RIGHT_TAB_KEY, type PaneTab } from '../RightPane'
import { PLAN_EMPTY_HINT, planTabContent } from '../../util/planTab'
import { NO_ROUNDS, roundsFor, writeRoundsIn, type RoundsByNote } from '../../util/roundsByNote'
import { isNoteIdVar, readRoundsWiring, wiringComplaints } from '../../util/roundsWiring'

const A = 'aaaaaaaaaaaa'
const B = 'bbbbbbbbbbbb'

/** 一张最省的轮次卡。**卡上那个「第 N 轮」是屏幕上真会出现的字**
 *  （`AgentActivity` 里 `第 ${r.round} 轮`），第 ② 块就是拿它当靶子。 */
const round = (n: number): AgentRound => ({
  round: n, cleanupOnly: false, revisions: 0, toolCalls: [], toolTruncated: false,
  scores: {}, status: '', weakest: null, policyReasons: [], policy: null, errors: [], dropped: [],
})

/** A 篇跑完 2 轮之后那张表。**只有 A 有卡，B 一张都没有**——P93 实拍的那一刻。 */
const AFTER_TWO_ROUNDS: RoundsByNote = writeRoundsIn({}, A, () => [round(1), round(2)])

/** `App.tsx` 里「计划」那一格的三样（`badge` / `hasContent` / `emptyHint`）逐字照搭，
 *  `body` 摆的是真 `AgentActivity`。**三样都从真模块出**，不在这儿另抄一份判据。 */
function planTab(m: RoundsByNote, noteId: string | null): PaneTab {
  const rounds = roundsFor(m, noteId)
  const t = planTabContent({ hasNote: !!noteId, running: false, rounds: rounds.length, beats: 0 })
  return {
    id: 'plan', title: '计划', alwaysShown: true,
    badge: t.badge || undefined,
    hasContent: t.has,
    emptyHint: PLAN_EMPTY_HINT,
    body: <AgentActivity rounds={rounds} status="" running={false} />,
  }
}

let host: HTMLDivElement
let root: ReturnType<typeof createRoot>

beforeEach(() => {
  try { localStorage.setItem(RIGHT_TAB_KEY, 'plan') } catch { /* 私密窗口 */ }
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

/** 挂一次，把「计划」那一格屏幕上的样子读回来。 */
function mountPlan(m: RoundsByNote, noteId: string | null) {
  act(() => root.render(<RightPane tabs={[planTab(m, noteId)]} defaultTab="plan" />))
  const tab = host.querySelector('.pane-tab')
  const body = host.querySelector('.right-pane-body')
  if (!tab) throw new Error('页签条上一格都没有——**选不到 ≠ 没有**，先去读 RightPane')
  if (!body) throw new Error('`.right-pane-body` 整个选不到——右栏没渲染出来')
  return { tabText: (tab.textContent ?? '').trim(), bodyText: (body.textContent ?? '').trim() }
}

describe('P95 ① 源码侧：`App.tsx` 里轮次卡是按 note id 接的', () => {
  const w = readRoundsWiring(appSrc)

  it('五问一条都不抱怨', () => {
    expect(wiringComplaints(w)).toEqual([])
  })

  it('屏幕上那份是 `roundsFor(<表>, current?.id)` 取的，不是一个全 App 一份的 useState', () => {
    expect(w.globalState).toBe(null)
    expect(w.readName).toBe('agentRounds')
    expect(w.keyExpr).toBe('current?.id')
  })

  it('每一处写入都点名了写给哪一篇（一处都不许是「写给现在显示的那篇」）', () => {
    expect(w.writes.length).toBeGreaterThan(0)
    for (const x of w.writes) expect([x.fn, x.firstArg, isNoteIdVar(x.firstArg)]).toEqual([x.fn, x.firstArg, true])
    // 直接动那张表的只有 `writeRounds` 自己那一处
    expect(w.rawSetters).toBe(1)
  })

  it('角标 / 正文 / 底下那叠卡，三处喂的是同一份', () => {
    expect(w.planRounds).toEqual(['agentRounds.length', 'agentRounds.length'])
    expect(w.activityRounds).toBe('agentRounds')
  })

  it('**反例**：回退成一个全 App 一份的 useState ⇒ 当场红，且点名', () => {
    const fake = appSrc.replace(
      'const agentRounds = roundsFor(roundsByNote, current?.id)',
      'const [agentRounds, setAgentRounds] = useState<AgentRound[]>([])')
    expect(fake).not.toBe(appSrc)   // 锚点唯一，替换真的落地了
    const bad = wiringComplaints(readRoundsWiring(fake))
    expect(bad.join('\n')).toMatch(/轮次卡又变回全 App 一份了/)
    expect(bad.join('\n')).toMatch(/agentRounds/)
  })

  it('**反例**：按哪一篇取那一格写死成一个 id ⇒ 红', () => {
    const fake = appSrc.replace('roundsFor(roundsByNote, current?.id)', "roundsFor(roundsByNote, 'note-1')")
    expect(fake).not.toBe(appSrc)
    expect(wiringComplaints(readRoundsWiring(fake)).join('\n')).toMatch(/里头没有 `current`/)
  })

  it('**反例**：底下那叠卡绕过「按 note id 取」⇒ 红', () => {
    const fake = appSrc.replace('rounds={agentRounds}', 'rounds={allRounds}')
    expect(fake).not.toBe(appSrc)
    expect(wiringComplaints(readRoundsWiring(fake)).join('\n')).toMatch(/摆的不是 `agentRounds`/)
  })

  it('**反例**：有人绕过 `writeRounds` 直接动那张表 ⇒ 红', () => {
    const fake = appSrc.replace('const [roundsByNote, setRoundsByNote] = useState<RoundsByNote>({})',
      'const [roundsByNote, setRoundsByNote] = useState<RoundsByNote>({})\n  const wipe = () => setRoundsByNote({})')
    expect(fake).not.toBe(appSrc)
    expect(wiringComplaints(readRoundsWiring(fake)).join('\n')).toMatch(/该正好 1 处/)
  })

  it('**解不出来就抛**，不是静默回一张空表', () => {
    expect(() => readRoundsWiring('const x = 1')).toThrow(/轮次卡整个换写法了/)
  })
})

describe('P95 ② 真挂一次：那一格摆的是这一篇的', () => {
  it('A 跑完 2 轮 → 新建的空笔记 B 上：**没有角标、一张卡都没有**', () => {
    const { tabText, bodyText } = mountPlan(AFTER_TWO_ROUNDS, B)
    // P93 实拍的是「计划 2」——角标里那个 2 是 A 的
    expect(tabText).toBe('计划')
    expect(tabText).not.toMatch(/\d/)
    expect(bodyText).not.toMatch(/第 \d+ 轮/)
    // ⚠️ **这一档不断言 `PLAN_EMPTY_HINT`，那是对的**：B 是一篇真笔记，
    // `planTabContent({hasNote:true,…}).has` 为真 ⇒ `RightPane` 不摆 `emptyHint`，
    // 屏幕上填进去的是「完成标准 / 目录 / 骨架」那三块——**那三块这份文件没挂**
    // （这里只挂 `AgentActivity`，靶子就是那叠卡）。「那一格空了有没有字」是
    // **P93 A** 那 17 条的地盘，别在这儿抄第二份。
    expect(planTabContent({ hasNote: true, running: false, rounds: 0, beats: 0 }).has).toBe(true)
  })

  it('**切回 A**：两张卡还在、角标是 2（那行 `useEffect` 的代价正在这一条上）', () => {
    const { tabText, bodyText } = mountPlan(AFTER_TWO_ROUNDS, A)
    expect(tabText).toBe('计划2')
    expect(bodyText).toMatch(/第 1 轮/)
    expect(bodyText).toMatch(/第 2 轮/)
  })

  it('虚拟页（`current === null`）：一张卡都读不到', () => {
    const { tabText, bodyText } = mountPlan(AFTER_TWO_ROUNDS, null)
    expect(tabText).toBe('计划')
    expect(bodyText).not.toMatch(/第 \d+ 轮/)
    expect(bodyText).toContain(PLAN_EMPTY_HINT)
  })
})

describe('P95 ③ 那两条纯函数自己的例 / 反例', () => {
  it('`roundsFor`：这一篇有就给这一篇的，别的一律空', () => {
    expect(roundsFor(AFTER_TWO_ROUNDS, A).map((r) => r.round)).toEqual([1, 2])
    expect(roundsFor(AFTER_TWO_ROUNDS, B)).toEqual([])
    expect(roundsFor(AFTER_TWO_ROUNDS, null)).toEqual([])
    expect(roundsFor(AFTER_TWO_ROUNDS, undefined)).toEqual([])
    expect(roundsFor(AFTER_TWO_ROUNDS, '')).toEqual([])
  })

  it('`roundsFor` 取不到时给的是**同一份**空数组（别每次现造一个新引用）', () => {
    expect(roundsFor({}, B)).toBe(NO_ROUNDS)
    expect(roundsFor({}, null)).toBe(NO_ROUNDS)
  })

  it('`writeRoundsIn`：写 B 不碰 A', () => {
    const m2 = writeRoundsIn(AFTER_TWO_ROUNDS, B, (rs) => [...rs, round(1)])
    expect(roundsFor(m2, B).map((r) => r.round)).toEqual([1])
    expect(roundsFor(m2, A).map((r) => r.round)).toEqual([1, 2])
    // 原来那张表一个字没动（**新对象，不是就地改**）
    expect(roundsFor(AFTER_TWO_ROUNDS, B)).toEqual([])
  })

  it('`writeRoundsIn`：`fn` 原样返回 ⇒ 整张表原样返回（不白重渲染一次）', () => {
    expect(writeRoundsIn(AFTER_TWO_ROUNDS, A, (rs) => rs)).toBe(AFTER_TWO_ROUNDS)
    expect(writeRoundsIn(AFTER_TWO_ROUNDS, B, (rs) => rs)).toBe(AFTER_TWO_ROUNDS)
  })

  it('`writeRoundsIn`：开跑那一刻清的是**那一篇**，别的篇不动', () => {
    const m2 = writeRoundsIn(AFTER_TWO_ROUNDS, A, () => [])
    expect(roundsFor(m2, A)).toEqual([])
    const m3 = writeRoundsIn(m2, B, () => [round(1)])
    expect(roundsFor(m3, A)).toEqual([])
    expect(roundsFor(m3, B).map((r) => r.round)).toEqual([1])
  })

  it('`isNoteIdVar`：例 / 反例各一组', () => {
    expect(['noteId', 'id', 'runNoteId'].map(isNoteIdVar)).toEqual([true, true, true])
    expect(["'note-1'", 'current?.id', 'current', 'currentRef.current?.id', '`${x}`'].map(isNoteIdVar))
      .toEqual([false, false, false, false, false])
  })
})
