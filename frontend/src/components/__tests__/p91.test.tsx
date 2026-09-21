// @vitest-environment jsdom
/**
 * P91 A（第 814 轮）：**「计划」页签那片纯空白** —— 先量、再改、再立闸。
 *
 * ── 开工量到的（改之前）────────────────────────────────────────────────────
 * 右栏 `App.tsx` 里 6 个页签，三个字段逐格量了一遍：
 *
 *     id          alwaysShown   hasContent                emptyHint
 *     memory      true          —                         —
 *     slides      true          —                         —
 *     changes     —             changesTabHasContent(…)   —
 *     plan        true          —                         —
 *     revisions   —             revisions.length > 0      '这篇还没有待处置的修订。'
 *     trace       —             !!trace                   —
 *
 * `RightPane` 摆 `emptyHint` 的那条路要**两件事同时成立**：
 * 页签留在条上（`alwaysShown || hasContent !== false`）**而且** `hasContent === false`。
 * ⇒ 够得着它的只有 `alwaysShown === true && hasContent === false` 这一种组合，
 * 而**上面那张表里一个都没有**：
 *
 *   · `memory` / `slides` / `plan` 有 `alwaysShown`，**从不设 `hasContent`**；
 *   · `changes` / `revisions` / `trace` 设了 `hasContent`，但**没有 `alwaysShown`**
 *     ——为 false 时整个页签先被 `shown` 滤掉了，内容区根本轮不到它。
 *
 * ⇒ **`emptyHint` 这条路开工时走得到的条数是 0。** `revisions` 上写着的那句
 * 「这篇还没有待处置的修订。」是**写了却够不着**的一句话（这一批不动它：
 * 要它能说话就得给 `revisions` 加 `alwaysShown`，那是另一个产品决定，判据宁可窄）。
 *
 * ── 那 6 个页签里，哪几个**真会留白** ────────────────────────────────────
 * 逐格走了一遍（`—` = 这一格不会留白，后面是它靠什么不留白）：
 *
 *   · `memory`    — `body` 自己兜底（`current ? … : <p>打开一篇笔记后…</p>`）
 *   · `slides`    — `SlidesPanel` 自己兜底（0 页时「这篇还不是幻灯片。…」）；
 *                    而且它只在 `isSlides(content)` 时才进数组
 *   · `changes`   — 没有 `alwaysShown`，空了整个页签不出现（P12：右栏页签只能减不能加）
 *   · `revisions` — 同上
 *   · `trace`     — 同上（`body` 那一支干脆是 `null`）
 *   · **`plan`    ← 会。** `alwaysShown` 留在条上，而 `body` 那四块
 *     （完成标准 / 目录 / 骨架 / 执行记录）在**虚拟页**上（`current === null`
 *     且没有 harness 在跑）**一块都画不出来** ⇒ `<div className="stack">` 里四个
 *     falsy ⇒ React 一个节点都不画 ⇒ **一片纯空白**。
 *
 * ⇒ **「该说话却没说话」的只有这一格：`plan` × 虚拟页。** 判据就窄在这一格上。
 * 另外三个「空了整个页签不出现」的**判成空得对**，这一批一个字不动。
 *
 * ── 还叠着一处「两把尺」（这才是最难读的那一半）────────────────────────
 * 角标那一行原来是 `agentRounds.length || (current ? beats.length : 0)`：
 * 虚拟页上 `agentRounds` **还是上一篇留下的**，于是页签上写着「计划 2」，
 * 底下一个字都没有（P89 实拍 `p89-b4-old-wipe-light.png`）。
 * **一个说有两件事的角标 + 一片什么都不说的空白**——用户没法判断是没内容、
 * 是坏了、还是自己少做了什么。改法照「改动」那一格 P43 #1 的老规矩：
 * **角标、出不出内容、空了说哪句话，从同一份判据里出**（`util/planTab.ts`）。
 *
 * ── 这份文件核什么 ────────────────────────────────────────────────────────
 *  ① `RightPane` 那条机制本身（真 `createRoot` 渲染，4 种组合各一条）：
 *     `emptyHint` 只在 `alwaysShown && hasContent === false` 时才说得出口。
 *     ⚠️ 其中一条**故意留着旧洞的形状**（`alwaysShown` + 不设 `hasContent` + 空 `body`
 *     ⇒ 纯空白）——它是这个机制的真实边界，不是缺陷，把它写下来是为了
 *     「下一格为什么必须设 `hasContent`」有个看得见的对照。
 *  ② `planTabContent` 这份判据本身（纯函数，虚拟页 / 跑着 / 开着笔记三档）。
 *  ③ **两头对齐**：`App.tsx` 那一格真的把它接在 `badge` 和 `hasContent` 上、
 *     真的挂了 `emptyHint`（`hasContent` 为 false 而角标还写着数 = 又变回两把尺）。
 *     只核源码 =「文件里有这个串」≠「这段代码还在跑」，所以 ① 那几条是真渲染。
 *
 * ── 它答不了什么 ──────────────────────────────────────────────────────────
 *  - **别的页签该不该说话**：一条都答不了。判据窄在 `plan` 这一格。
 *  - **那句话写得好不好**：答不了。它只管「有没有话说」和「角标跟正文对不对得上」。
 */
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import appSrc from '../../App.tsx?raw'
import RightPane, { RIGHT_TAB_KEY, type PaneTab } from '../RightPane'
import { PLAN_EMPTY_HINT, planTabContent } from '../../util/planTab'

/** 真挂一次，回 `.right-pane-body` 那个节点（**不是整页**：条上的页签名也是字）。 */
async function mount(tabs: PaneTab[], active?: string) {
  if (active) localStorage.setItem(RIGHT_TAB_KEY, active)
  const el = document.createElement('div')
  document.body.append(el)
  const root = createRoot(el)
  await act(async () => { root.render(<RightPane tabs={tabs} defaultTab={tabs[0]?.id ?? ''} />) })
  const body = el.querySelector('.right-pane-body')
  if (!body) throw new Error('右栏内容区整个没渲染出来——先看 RightPane 是不是抛了，而不是改判据')
  return { el, body: body as HTMLElement }
}

/** 条上现在摆着哪几个页签（逐字，连角标）。 */
const tabNames = (el: HTMLElement) =>
  [...el.querySelectorAll('.pane-tab')].map((b) => b.textContent ?? '')

beforeEach(() => { localStorage.clear() })
afterEach(() => { document.body.innerHTML = ''; localStorage.clear() })

describe('P91 A ①：`RightPane` 那条「别留白」的路，什么时候才走得到', () => {
  it('alwaysShown + hasContent:false → 说 `emptyHint`，body 一个字都不摆', async () => {
    const { el, body } = await mount([
      { id: 'plan', title: '计划', alwaysShown: true, hasContent: false,
        emptyHint: '这里空着，因为还没开着一篇笔记。', body: <div id="real">真正文</div> },
    ])
    expect(body.textContent).toBe('这里空着，因为还没开着一篇笔记。')
    // **「看到 ≠ 真在正文里」的反面**：那句话摆出来了，原来的 body 得真的没渲染
    expect(el.querySelector('#real')).toBe(null)
    expect(tabNames(el)).toEqual(['计划'])
  })

  it('alwaysShown + hasContent:false + 没写 emptyHint → 摆那句兜底的，仍然不留白', async () => {
    const { body } = await mount([
      { id: 'plan', title: '计划', alwaysShown: true, hasContent: false, body: <div>真正文</div> },
    ])
    expect(body.textContent).toBe('这篇还没有这一项的内容。')
  })

  it('⚠️ alwaysShown + **不设** hasContent + body 画不出东西 → **一片纯空白**（这就是 P89 照出来的那个洞的形状）', async () => {
    const { el, body } = await mount([
      // `<div className="stack">{[false, false, false, false]}</div>` 的等价形状：
      // 节点在、里面一个字都没有。这正是虚拟页上「计划」那一格改之前的样子。
      { id: 'plan', title: '计划', alwaysShown: true, body: <div className="stack">{[false, false, false, false]}</div> },
    ])
    expect(body.textContent).toBe('')          // ← 用户眼里：一片什么都不说的空白
    expect(tabNames(el)).toEqual(['计划'])      // ← 而页签还在条上，点得进来
  })

  it('没有 alwaysShown + hasContent:false → **整个页签先被滤掉**，`emptyHint` 根本轮不到（`revisions` 今天就是这一档）', async () => {
    const { el, body } = await mount([
      { id: 'memory', title: '记忆', alwaysShown: true, body: <div>记忆正文</div> },
      { id: 'revisions', title: '修订', hasContent: false,
        emptyHint: '这篇还没有待处置的修订。', body: <div>修订正文</div> },
    ])
    expect(tabNames(el)).toEqual(['记忆'])
    expect(body.textContent).toBe('记忆正文')
    // **两个方向**：那句话一个字都不该出现在页面上——它够不着
    expect(el.textContent).not.toContain('这篇还没有待处置的修订。')
  })
})

describe('P91 A ②：`planTabContent` —— 角标和「有没有东西」同一份判据', () => {
  it('虚拟页、没在跑：没东西、角标 0（上一篇留下的 rounds / beats 一个都不算）', () => {
    expect(planTabContent({ hasNote: false, running: false, rounds: 2, beats: 5 }))
      .toEqual({ has: false, badge: 0 })
  })

  it('虚拟页、**正在跑**：执行记录那一块画得出来 ⇒ 有东西，角标就是这一次的轮数', () => {
    expect(planTabContent({ hasNote: false, running: true, rounds: 2, beats: 5 }))
      .toEqual({ has: true, badge: 2 })
  })

  it('开着一篇笔记：永远有东西（至少一行「目录」），角标照旧轮数优先、没轮数用骨架拍数', () => {
    expect(planTabContent({ hasNote: true, running: false, rounds: 0, beats: 5 }))
      .toEqual({ has: true, badge: 5 })
    expect(planTabContent({ hasNote: true, running: false, rounds: 3, beats: 5 }))
      .toEqual({ has: true, badge: 3 })
    // 空笔记（没骨架也没跑过）：有东西（那行「目录」），但**不摆角标**
    expect(planTabContent({ hasNote: true, running: false, rounds: 0, beats: 0 }))
      .toEqual({ has: true, badge: 0 })
  })

  it('开着笔记时**跟原来那一行逐格相同**——这一刀只改虚拟页那一档', () => {
    // 原来那一行：`agentRounds.length || (current ? beats.length : 0)`
    const old = (rounds: number, beats: number, hasNote: boolean) => rounds || (hasNote ? beats : 0)
    for (const rounds of [0, 1, 7]) {
      for (const beats of [0, 2, 5]) {
        expect(planTabContent({ hasNote: true, running: false, rounds, beats }).badge)
          .toBe(old(rounds, beats, true))
      }
    }
    // 而虚拟页那一档**就是变了**：原来 2，现在 0（这一刀的全部分量）
    expect(old(2, 5, false)).toBe(2)
    expect(planTabContent({ hasNote: false, running: false, rounds: 2, beats: 5 }).badge).toBe(0)
  })

  it('那句话逐字（跟「记忆」那一格同一个句式）', () => {
    expect(PLAN_EMPTY_HINT).toBe('打开一篇笔记后，这里会摆出它的完成标准、目录、写作骨架和每一轮执行。')
  })
})

describe('P91 A ③：`App.tsx` 那一格真的接上了（源码两头对齐）', () => {
  /** 右栏 `tabs={[…]}` 那一整块里 `plan` 那一格的源码。 */
  const planBlock = (): string => {
    const src = appSrc
    const from = src.indexOf('tabs={[', src.indexOf('<RightPane'))
    const to = src.indexOf('] as PaneTab[]}', from)
    expect(from).toBeGreaterThan(0)
    expect(to).toBeGreaterThan(from)
    const block = src.slice(from, to)
    const at = block.indexOf("{ id: 'plan'")
    expect(at).toBeGreaterThan(0)
    const next = block.indexOf("{ id: 'revisions'", at)
    expect(next).toBeGreaterThan(at)
    return block.slice(at, next)
  }

  it('`badge` 和 `hasContent` 都从 `planTabContent` 出（两处都接，只接一处 = 又变回两把尺）', () => {
    const b = planBlock()
    expect(b).toMatch(/badge:\s*planTabContent\(/)
    expect(b).toMatch(/hasContent:\s*planTabContent\(/)
    // 原来那一行**不许留着**：留着就有两份判据，而两份判据迟早会飘开
    expect(b).not.toMatch(/badge:\s*agentRounds\.length\s*\|\|/)
  })

  it('`emptyHint` 挂的是 `PLAN_EMPTY_HINT`（不是就地写一句，不然它跟测试会各说各的）', () => {
    expect(planBlock()).toMatch(/emptyHint:\s*PLAN_EMPTY_HINT/)
  })

  it('`alwaysShown` 还在——去掉它这一格就退回「整个页签消失」，那是另一件事', () => {
    expect(planBlock()).toMatch(/alwaysShown:\s*true/)
  })

  it('喂进去的那两个数逐字照抄正文那两个条件（`!!current` / `note-harness` + `harness?.running`）', () => {
    const b = planBlock()
    // **只读那两个调用自己的实参**，不读整格——整格里 `body` 那一段自己也提 `pausedRun`
    // （它管的是四块的**排序**，不是画不画），拿整格去判就是拿两把尺当一把用。
    const calls = [...b.matchAll(/planTabContent\((\{[\s\S]*?\})\)/g)].map((m) => m[1])
    expect(calls).toHaveLength(2)
    for (const args of calls) {
      expect(args).toContain('hasNote: !!current')
      expect(args).toContain("running: loading === 'note-harness' || !!harness?.running")
      expect(args).toContain('rounds: agentRounds.length')
      expect(args).toContain('beats: beats.length')
      // **不含 `pausedRun`**：正文那一行的执行记录块也不看它（判据宁可窄）
      expect(args).not.toContain('pausedRun')
    }
    // 两处喂的是**同一份实参**，否则角标和「有没有东西」还是两把尺
    expect(calls[0].replace(/\s+/g, ' ')).toBe(calls[1].replace(/\s+/g, ' '))
  })
})
