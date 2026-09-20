// @vitest-environment jsdom
/**
 * P43（`docs/TRACELOG-product.md` P43 节）：P42 走查那 8 条里的前端几条。
 *
 * · **#1** toast 说「上次没处置完的 1 层改动还在右栏「改动」里」，而**整页搜不到这两个字**。
 *   两头各错一半：那句话数的是「放回来的层」（一处活的都不剩的也算），
 *   而页签只看 `pendingDiff`（还**不算只差空白的那几处**）。
 *   这一批把两头**收进两个纯函数**，并且钉住它们之间那条不变式：
 *   **弹了 toast ⇒ 页签一定在**。
 *   顺带回答了「逐处处置完算不算烧」：**不算**——烧（「全部接受」）是把层落进正文、
 *   清库、交给「烧过的跑」接手；逐处处置完那几下是 `settled` 那本账，
 *   面板上是一行灰字「已处置：N 处接受、M 处撤回」，那正是 P39 面板
 *   「你逐处按下去的接受 / 撤回也留着」那句承诺的兑现物。清掉 = 让那句话变成空头支票。
 *
 * · **#2** 意图预填只认 `input.note-title`，不认正文 H1。一篇笔记**只有一个名字**
 *   （`displayTitle`），预填得认这一个。重推的代价先量过（见 `App.tsx` 那段注释）；
 *   依赖挂的是**算出来的名字**而不是 `content`，名字没变一次都不跑。
 */
import { describe, expect, it } from 'vitest'
import { EditorState, type TransactionSpec } from '@codemirror/state'
import appSrc from '../../App.tsx?raw'
import {
  acceptHunk, addLayer, diffParts, layersOf, restoreLayers as restoreLayersEffect,
  roundDiffField, settledOf,
} from '../roundDiff'
import { minimalChange } from '../minimalChange'
import {
  changesTabHasContent, reopenedLayersNotice, restoreLayers, serializeLayers,
  type Restored, type SavedLayer,
} from '../../util/changeLayers'
import { displayTitle } from '../../util/displayTitle'
import { resolveIntent, type DocIntent } from '../../util/docIntent'

class Host {
  state: EditorState
  constructor(doc: string) { this.state = EditorState.create({ doc, extensions: [roundDiffField] }) }
  dispatch(spec: TransactionSpec) { this.state = this.state.update(spec).state }
  get doc() { return this.state.doc.toString() }
  push(label: string, after: string) {
    const before = this.doc
    const change = minimalChange(before, after)
    if (change) this.state = this.state.update({ changes: change }).state
    this.dispatch({ effects: addLayer.of({ label, parts: diffParts(before, after) }) })
  }
  save(): SavedLayer[] { return serializeLayers(this.state) }
}

const V0 = '甲一二三四五六七八九乙一二三四五六七八九'
const V1 = 'AA一二三四五六七八九BB一二三四五六七八九'

/** 把库里回来的那几行真的塞进一个新编辑器——跟 App 那条 effect 同一条路。 */
function reopen(saved: SavedLayer[], doc: string): { host: Host; r: Restored } {
  const host = new Host(doc)
  const r = restoreLayers(saved, doc)
  host.dispatch({ effects: restoreLayersEffect.of({ layers: r.layers, hunks: r.hunks, settled: r.settled }) })
  return { host, r }
}

const EMPTY: Restored = { layers: [], hunks: [], settled: [], conflicts: [], stuck: [] }
const R = (over: Partial<Restored>): Restored => ({ ...EMPTY, ...over })
const LIVE = (key: string) => ({ key, from: 0, to: 2, del: '甲' })
const DONE = (key: string) => ({ key, state: 'accepted' as const, del: '甲', ins: 'AA' })

// ------------------------------------------------------------------ #1 那句 toast

describe('P43 #1 重开那句 toast：说什么、说不说', () => {
  it('**一层全处置完之后重开：一个字都不说**（P42 实拍那一档）', () => {
    expect(reopenedLayersNotice(R({ settled: [DONE('L1')] }))).toBeNull()
  })

  it('真有活改动放回来才说，数的是层不是处', () => {
    const n = reopenedLayersNotice(R({ hunks: [LIVE('L1'), LIVE('L1')] }))
    expect(n?.kind).toBe('info')
    expect(n?.text).toBe('上次没处置完的 1 层改动还在右栏「改动」里')
  })

  it('一层还活着 + 一层全处置完 → 说 1 层，不是 2 层', () => {
    const n = reopenedLayersNotice(R({ hunks: [LIVE('L1')], settled: [DONE('L2')] }))
    expect(n?.text).toContain('1 层')
  })

  it('冲突那一档照旧要说（那时「改动」页签一定在，指的地方是真的）', () => {
    const n = reopenedLayersNotice(R({
      hunks: [LIVE('L1')], conflicts: ['润色：「甲」'], stuck: [{ id: 'L2', label: '润色', why: ['「甲」'] }],
    }))
    expect(n?.kind).toBe('error')
    expect(n?.text).toContain('重新打开了 1 层')
    expect(n?.text).toContain('右栏「改动」里可以重新算或者丢掉')
  })

  it('冲突、而且一层活的都没放回来：**不许说「重新打开了 0 层」**', () => {
    const n = reopenedLayersNotice(R({
      conflicts: ['润色：「甲」'], stuck: [{ id: 'L1', label: '润色', why: ['「甲」'] }],
    }))
    expect(n?.kind).toBe('error')
    expect(n?.text).not.toContain('0 层')
    expect(n?.text.startsWith('1 处因为正文改过')).toBe(true)
  })
})

describe('P43 #1 「改动」页签什么时候出现', () => {
  it('**只剩处置完的层也算有内容**——面板上那行「已处置…」得有地方看（P42 问题 #1 的另一半）', () => {
    expect(changesTabHasContent({ layers: 0, settled: 1, runs: 0, stuck: 0 })).toBe(true)
  })

  it('四样都是 0 才不出现', () => {
    expect(changesTabHasContent({ layers: 0, settled: 0, runs: 0, stuck: 0 })).toBe(false)
    for (const k of ['layers', 'settled', 'runs', 'stuck'] as const) {
      expect(changesTabHasContent({ layers: 0, settled: 0, runs: 0, stuck: 0, [k]: 1 })).toBe(true)
    }
  })
})

describe('P43 #1 不变式：**弹了 toast，页签就一定在**', () => {
  // 这条不变式才是 P42 那个缺陷的形状——两头各自判、判据不一样。
  // 遍历的这几种局面覆盖了「有活层 / 只有处置完的层 / 有冲突 / 什么都没有」。
  const cases: Restored[] = [
    EMPTY,
    R({ hunks: [LIVE('L1')] }),
    R({ settled: [DONE('L1')] }),
    R({ hunks: [LIVE('L1')], settled: [DONE('L1')] }),
    R({ hunks: [LIVE('L1')], settled: [DONE('L2')] }),
    R({ hunks: [LIVE('L1')], conflicts: ['x'], stuck: [{ id: 'L2', label: '润色', why: ['x'] }] }),
    R({ conflicts: ['x'], stuck: [{ id: 'L1', label: '润色', why: ['x'] }] }),
    R({ settled: [DONE('L1')], conflicts: ['x'], stuck: [{ id: 'L2', label: '润色', why: ['x'] }] }),
  ]
  for (const [i, r] of cases.entries()) {
    it(`第 ${i + 1} 种局面`, () => {
      const tab = changesTabHasContent({
        layers: new Set(r.hunks.map((h) => h.key)).size,
        settled: new Set(r.settled.map((s) => s.key)).size,
        runs: 0,
        stuck: r.stuck.length,
      })
      if (reopenedLayersNotice(r)) expect(tab).toBe(true)
    })
  }
})

describe('P43 #1 逐处处置完 ≠ 烧：层留在库里，面板上是一行灰字', () => {
  it('唯一那一处点了「✓ 接受」→ 存下去 → 重开：层还在、面板有得画、toast 不说话', () => {
    const h = new Host(V0)
    h.push('润色', V1)
    const hunks = h.state.field(roundDiffField).hunks
    for (const x of [...hunks]) h.dispatch({ effects: acceptHunk.of(x.id) })
    expect(h.state.field(roundDiffField).hunks).toHaveLength(0)

    const saved = h.save()
    expect(saved).toHaveLength(1)                                   // **没有从库里消失**
    expect(saved[0].hunks.every((x) => x.state === 'accepted')).toBe(true)

    const { host, r } = reopen(saved, h.doc)
    expect(layersOf(host)).toHaveLength(0)                          // 没有带按钮的卡片（按了也没用）
    expect(settledOf(host)).toHaveLength(1)                         // 有那一行「已处置 …」
    expect(reopenedLayersNotice(r)).toBeNull()                      // 所以一个字都不说
    expect(changesTabHasContent({
      layers: layersOf(host).length, settled: settledOf(host).length, runs: 0, stuck: 0,
    })).toBe(true)                                                  // 但页签在，那行灰字看得到
  })

  it('还有一处没处置：toast 说 1 层，页签也在', () => {
    const h = new Host(V0)
    h.push('润色', V1)
    h.dispatch({ effects: acceptHunk.of(h.state.field(roundDiffField).hunks[0].id) })
    const { host, r } = reopen(h.save(), h.doc)
    expect(reopenedLayersNotice(r)?.text).toContain('1 层')
    expect(layersOf(host).length).toBeGreaterThan(0)
  })
})

describe('P43 #1 接线洞', () => {
  it('App 那句 toast 真的走 `reopenedLayersNotice`，不再自己数一遍', () => {
    expect(appSrc).toContain('const notice = reopenedLayersNotice(r)')
    expect(appSrc).toContain('if (notice) toast(notice.text, notice.kind)')
    // 原来那一行（把 settled 也数进层数）不许再出现
    expect(appSrc).not.toContain('...r.settled.map((x) => x.key)')
  })

  it('「改动」页签的出现条件真的走 `changesTabHasContent`，而且把处置完的层算进去了', () => {
    // 锚点要唯一：`id: 'changes'` 在改动条那句「按层处置」的链接里也有一个
    const at = appSrc.indexOf("{ id: 'changes', title: '改动'")
    expect(at).toBeGreaterThan(0)
    const block = appSrc.slice(at, at + 700)
    expect(block).toContain('hasContent: changesTabHasContent({')
    expect(block).toContain('settled: editorViewRef.current ? settledOf(editorViewRef.current).length : 0')
    expect(block).not.toMatch(/hasContent:\s*pendingDiff > 0/)
  })
})

// ------------------------------------------------------------------ #5 两块卡各报各的户口

describe('P43 #5 「脉络」也要写清自己在说哪一段', () => {
  // P42 问题 #6 那一屏：跑完「来龙去脉」之后右栏上面同时挂着「校验结果」和「脉络」，
  // 而两块常常说的是**不同的两段**（实拍：校验说第 2 行、脉络说第 6 行）。
  // P41 给「校验」那块写了户口，这块没写——一块报一块不报，只解决了一半。
  it('两块卡用的是**同一个** `verifyScopeLine`，不是各写一句', () => {
    // P46 #4 在同一行上多导了一个 `passageLine`（跳回正文那一段的判据），
    // **钉的东西没变**：`verifyScopeLine` 是从 `VerifyPanel` 那一份拿的，不是 App 自己又写一句。
    expect(appSrc).toContain("import VerifyPanel, { passageLine, verifyScopeLine } from './components/VerifyPanel'")
    const at = appSrc.indexOf("id: 'trace', title: '脉络'")
    expect(at).toBeGreaterThan(0)
    const block = appSrc.slice(at, at + 1200)
    // **守门的那一行也要钉**（突变验 #12 第一版就是砍空在这儿）：只钉里面那次调用的话，
    // 把 `{!!verifyScopeLine(...) && (` 换成 `{false && (` 这一刀照样绿。
    expect(block).toContain("{!!verifyScopeLine(trace.passage ?? '', !!trace.passage && !content.includes(trace.passage)) && (")
    expect(block).toContain("{verifyScopeLine(trace.passage ?? '', !!trace.passage && !content.includes(trace.passage))}")
  })

  it('「那一段还在不在正文里」照旧按**现在的正文**判（代码判得准的才说）', () => {
    const at = appSrc.indexOf("id: 'trace', title: '脉络'")
    expect(appSrc.slice(at, at + 1200)).toContain('!!trace.passage && !content.includes(trace.passage)')
  })

  it('接线洞：跑「来龙去脉」时真的把那一段存了下来', () => {
    expect(appSrc).toContain('at: new Date().toISOString(), passage: text })')
  })
})

// ------------------------------------------------------------------ #2 意图预填

describe('P43 #2 意图预填认的是界面上那个名字，不是标题框那一格', () => {
  const H1 = '# 周报 9-20\n\n这周把众筹页面的文案定稿了。'
  const prefill: DocIntent = { goal: '', reader: '', done: '', source: 'prefill', checked: [] }

  it('标题框空着、正文第一行是 H1：名字就是 H1（树 / 标签页 / 状态栏用的也是它）', () => {
    expect(displayTitle({ title: '', content: H1 })).toBe('周报 9-20')
  })

  it('**修之前**：拿标题框那一格去推 → 一个字都推不出来（P42 实拍的空意图行）', () => {
    const before = resolveIntent(prefill, '')
    expect(before.goal).toBe('')
    expect(before.source).toBe('')
  })

  it('**修之后**：拿那个名字去推 → 周报那条规则当场命中，角标是「预填」', () => {
    const after = resolveIntent(prefill, displayTitle({ title: '', content: H1 }))
    expect(after.source).toBe('prefill')
    expect(after.goal).toContain('周报 9-20')
    expect(after.reader).toBe('老板 / 团队')
    expect(after.done).toContain('每条进展有日期')
  })

  it('标题框里有字就照旧只认它——正文里另有一个 H1 也不抢（`displayTitle` 的老规矩）', () => {
    expect(displayTitle({ title: '真标题', content: H1 })).toBe('真标题')
  })

  it('**重推的次数**：正文改的不是首行，名字一个字没变 → 那个 effect 的依赖不变、一次都不跑', () => {
    const a = displayTitle({ title: '', content: H1 })
    const b = displayTitle({ title: '', content: H1 + '\n\n又写了一段，跟标题没关系。' })
    expect(a).toBe(b)
  })

  it('用户改过一个字的（source=user）永远不被覆盖（P31 #1 那条闸没动）', () => {
    const mine: DocIntent = { goal: '我自己写的', reader: '', done: '', source: 'user', checked: [] }
    expect(resolveIntent(mine, '周报 9-20').goal).toBe('我自己写的')
  })

  it('接线洞：App 真的按 `displayTitle({ title, content })` 算名字，effect 依赖的是它', () => {
    expect(appSrc).toContain('const shownTitle = useMemo(() => displayTitle({ title, content }), [title, content])')
    // P46 #5 在名字和 effect 之间多插了一层防抖（`settledTitle`），**这一条守的性质没变**：
    // 依赖的还是「**算出来的名字**」那条链，不是 `content`。防抖本身在 `p46.test.ts` 里钉。
    expect(appSrc).toContain('setIntent((i) => (i.source === \'user\' ? i : resolveIntent(i, settledTitle)))')
    expect(appSrc).toContain('}, [settledTitle, current?.id])')
    expect(appSrc).toContain('setSettledTitle(shownTitle), INTENT_PREFILL_IDLE_MS')
    // **依赖不许直接挂 `content`**：那才是「每敲一个字重推一次」
    expect(appSrc).not.toContain('}, [title, content, current?.id])')
  })
})
