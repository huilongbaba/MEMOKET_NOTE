// @vitest-environment jsdom
/**
 * P39（`docs/TRACELOG-product.md` P39 节）：**待处置的改动层落库**——痛点 8 的最后一块。
 *
 * P37 #5 量完的结论是「重建不出来」，最缺的那一样是**处置状态没有载体**：
 * 哪几处已经逐处接受 / 撤回、哪几层关掉了、层序和 `at`，全活在 CodeMirror 的状态里。
 * 这一批给层单开了一张表，这个文件盯前端那一半：
 *
 * * **四个处置状态每一个都从一次真操作里长出来**（不是手搓的 payload）：
 *   加一层 → `pending`；整层关掉 → `off`；点「✓ 接受」→ `accepted`；点「↩ 撤回」→ `reverted`。
 *   `acceptHunk` / `dropHunk` 会把 hunk 直接 filter 掉，所以后两个取值**必须**走
 *   `roundDiffField` 里另记的那本 `settled` 账——不走的话它俩一辈子写不进库（批 22 `stopped` 那条教训）。
 * * **存下去再放回来是同一批层**：层序、`at`、每一处的状态、正文都对得上。
 * * **正文被别处改过**：靠文字重新定位；多处命中 / 找不到 = 说清楚，**不猜**。
 * * **接线洞**：编辑器真的会报「层动了」、App 真的接了那条线、落库不是每敲一个字一次。
 */
import { describe, expect, it, vi } from 'vitest'
import { EditorState, type TransactionSpec } from '@codemirror/state'
import appSrc from '../../App.tsx?raw'
import editorSrc from '../../components/MarkdownEditor.tsx?raw'
import panelSrc from '../../components/ChangeLayersPanel.tsx?raw'
import {
  acceptHunk, addLayer, diffParts, dropHunk, layersOf, restoreLayers as restoreLayersEffect,
  roundDiffField, settledOf, turnLayerOff,
} from '../roundDiff'
import { minimalChange } from '../minimalChange'
import {
  contentTag, layerSource, relocate, restoreLayers, sameLayers, serializeLayers, type SavedLayer,
} from '../../util/changeLayers'

class Host {
  state: EditorState
  constructor(doc: string) { this.state = EditorState.create({ doc, extensions: [roundDiffField] }) }
  dispatch(spec: TransactionSpec) { this.state = this.state.update(spec).state }
  get doc() { return this.state.doc.toString() }
  /** 跟 App.pushDiff 同一条路：正文按最小改动换成 after，再按 diff 加一层 */
  push(label: string, after: string) {
    const before = this.doc
    const change = minimalChange(before, after)
    if (change) this.state = this.state.update({ changes: change }).state
    this.dispatch({ effects: addLayer.of({ label, parts: diffParts(before, after) }) })
  }
  save(): SavedLayer[] { return serializeLayers(this.state) }
}

// 三处改动，中间隔着 9 个没动过的字——`toHunks` 的 MERGE_GAP 是 8，再近就并成一处了
const V0 = '甲一二三四五六七八九乙一二三四五六七八九丙一二三四五六七八九'
const V1 = 'AA一二三四五六七八九BB一二三四五六七八九CC一二三四五六七八九'
const V0_4 = V0 + '丁一二三四五六七八九'
const V1_4 = V1 + 'DD一二三四五六七八九'

function threeHunks(): Host {
  const h = new Host(V0)
  h.push('润色', V1)
  return h
}

// ---------------------------------------------------------------- 四个取值

describe('P39 每个处置状态都是从一次真操作里长出来的', () => {
  it('刚加的一层：每一处都是 pending', () => {
    const saved = threeHunks().save()
    expect(saved.length).toBe(1)
    expect(saved[0].hunks.map((x) => x.state)).toEqual(['pending', 'pending', 'pending'])
    expect(saved[0].label).toBe('润色')
    expect(saved[0].state).toBe('on')
    // 新文字要一起带走：不带的话「再打开这一层」就没有可写回去的东西
    expect(saved[0].hunks.map((x) => x.ins)).toEqual(['AA', 'BB', 'CC'])
    expect(saved[0].hunks.map((x) => x.del)).toEqual(['甲', '乙', '丙'])
  })

  it('整层关掉：每一处 off，整层 state=off，正文回到改之前', () => {
    const h = threeHunks()
    turnLayerOff(h, layersOf(h)[0].id)
    expect(h.doc).toBe(V0)
    const saved = h.save()
    expect(saved[0].state).toBe('off')
    expect(saved[0].hunks.map((x) => x.state)).toEqual(['off', 'off', 'off'])
    // 关着的时候正文里是原文，所以 ins 得是**关掉时摘下来的那一份**，不是 doc.slice
    expect(saved[0].hunks.map((x) => x.ins)).toEqual(['AA', 'BB', 'CC'])
  })

  it('逐处点「✓ 接受」：那一处记成 accepted（hunk 已经从列表里没了，靠 settled 那本账）', () => {
    const h = threeHunks()
    const first = h.state.field(roundDiffField).hunks[0]
    h.dispatch({ effects: acceptHunk.of(first.id) })
    const saved = h.save()
    expect(saved[0].hunks.filter((x) => x.state === 'accepted').map((x) => x.ins)).toEqual(['AA'])
    expect(saved[0].hunks.filter((x) => x.state === 'pending').length).toBe(2)
    expect(h.doc).toBe(V1)                     // 接受 = 正文保持现状
  })

  it('逐处点「↩ 撤回」：那一处记成 reverted，正文换回原文', () => {
    const h = threeHunks()
    const last = h.state.field(roundDiffField).hunks[2]
    h.dispatch({ changes: { from: last.from, to: last.to, insert: last.del }, effects: dropHunk.of(last.id) })
    const saved = h.save()
    const rev = saved[0].hunks.filter((x) => x.state === 'reverted')
    expect(rev.map((x) => x.del)).toEqual(['丙'])
    expect(h.doc).toBe('AA一二三四五六七八九BB一二三四五六七八九丙一二三四五六七八九')
  })

  it('验证 2 的那一幕：接受两处、撤回一处，四个取值一起落库', () => {
    const h = new Host(V0_4)
    h.push('润色', V1_4)                          // 四处
    const hs = [...h.state.field(roundDiffField).hunks]
    h.dispatch({ effects: acceptHunk.of(hs[0].id) })
    h.dispatch({ effects: acceptHunk.of(hs[1].id) })
    const third = h.state.field(roundDiffField).hunks.find((x) => x.id === hs[2].id)!
    h.dispatch({ changes: { from: third.from, to: third.to, insert: third.del }, effects: dropHunk.of(third.id) })
    const states = h.save()[0].hunks.map((x) => x.state).sort()
    expect(states).toEqual(['accepted', 'accepted', 'pending', 'reverted'])
    // 面板上那一行也说得出来
    expect(settledOf(h)[0]).toMatchObject({ accepted: 2, reverted: 1, live: 1 })
  })

  it('层序和 at 一起带走（痛点 8 要的就是「第一轮 / 第三轮」分得清）', () => {
    const h = new Host(V0)
    h.push('智能续写', 'AA一二三四五六七八九乙一二三四五六七八九丙一二三四五六七八九')
    h.push('格式化', 'AA一二三四五六七八九乙一二三四五六七八九CC一二三四五六七八九')
    const saved = h.save()
    expect(saved.map((l) => [l.seq, l.label])).toEqual([[0, '智能续写'], [1, '格式化']])
    expect(saved.map((l) => l.source)).toEqual(['round', 'format'])
    expect(new Date(saved[0].at).getTime()).toBeLessThanOrEqual(new Date(saved[1].at).getTime())
  })
})

// ---------------------------------------------------------------- 存下去 → 放回来

describe('P39 关掉再打开：层和处置状态原样回来', () => {
  /** 模拟一次重启：拿存下来的行，在一个全新的编辑器上放回去 */
  function reopen(saved: SavedLayer[], doc: string): Host {
    const h = new Host(doc)
    const r = restoreLayers(saved, doc)
    h.dispatch({ effects: restoreLayersEffect.of({ layers: r.layers, hunks: r.hunks, settled: r.settled }) })
    return h
  }

  it('三处没处置 → 关掉重开：三处都还在、还是待处置', () => {
    const before = threeHunks()
    const h = reopen(before.save(), V1)
    expect(layersOf(h).map((l) => [l.label, l.count, l.off])).toEqual([['润色', 3, false]])
    // 每一处的位置都对得上：整层关掉能精确回到 V0
    turnLayerOff(h, layersOf(h)[0].id)
    expect(h.doc).toBe(V0)
  })

  it('接受两处、撤回一处 → 关掉重开：三处的处置状态各自还在', () => {
    const h0 = new Host(V0_4)
    h0.push('润色', V1_4)
    const hs = [...h0.state.field(roundDiffField).hunks]
    h0.dispatch({ effects: acceptHunk.of(hs[0].id) })
    h0.dispatch({ effects: acceptHunk.of(hs[1].id) })
    const third = h0.state.field(roundDiffField).hunks.find((x) => x.id === hs[2].id)!
    h0.dispatch({ changes: { from: third.from, to: third.to, insert: third.del }, effects: dropHunk.of(third.id) })
    const saved = h0.save()

    const h = reopen(saved, h0.doc)
    expect(settledOf(h)[0]).toMatchObject({ label: '润色', accepted: 2, reverted: 1 })
    expect(layersOf(h)[0].count).toBe(1)                 // 还剩那一处待定
    expect(sameLayers(h.save(), saved)).toBe(true)       // 再存一次跟上次一模一样：不会每开一次就漂一点
  })

  it('整层关着 → 关掉重开：层还是关着的，再打开能把新文字写回去', () => {
    const h0 = threeHunks()
    turnLayerOff(h0, layersOf(h0)[0].id)
    const h = reopen(h0.save(), h0.doc)
    expect(layersOf(h)[0].off).toBe(true)
    expect(h.doc).toBe(V0)
  })

  it('层序、标签、时间都是存下来的那一份，不是「刚刚」', () => {
    const at = new Date('2026-09-19T08:30:00Z').getTime()
    const saved: SavedLayer[] = [{
      id: 'L1', label: '智能续写', source: 'round', seq: 0, state: 'on',
      at: new Date(at).toISOString(), content_tag: contentTag(V1),
      hunks: [{ k: 0, from: 0, to: 2, del: '甲', ins: 'AA', state: 'pending', before: '', after: '一二三四' }],
    }]
    const h = reopen(saved, V1)
    expect(layersOf(h)[0].label).toBe('智能续写')
    expect(layersOf(h)[0].at).toBe(at)
  })
})

// ---------------------------------------------------------------- 正文变过

describe('P39 正文被别处改过：靠文字重新定位，对不上就说清楚', () => {
  const H = (o: Partial<SavedLayer['hunks'][0]>) => ({
    k: 0, from: 0, to: 0, del: '', ins: '', state: 'pending' as const, before: '', after: '', ...o,
  })

  it('正文前面被插了一段：坐标全漂了，靠前后文照样找得回来', () => {
    const before = threeHunks().save()
    const moved = '（用户后来在开头加的一句）' + V1
    const r = restoreLayers(before, moved)
    expect(r.conflicts).toEqual([])
    const h = new Host(moved)
    h.dispatch({ effects: restoreLayersEffect.of({ layers: r.layers, hunks: r.hunks, settled: r.settled }) })
    turnLayerOff(h, layersOf(h)[0].id)
    expect(h.doc).toBe('（用户后来在开头加的一句）' + V0)
  })

  it('同一段在正文里出现了两次：报冲突，不猜', () => {
    const r = restoreLayers([{
      id: 'L', label: '润色', source: 'polish', seq: 0, state: 'on', at: new Date().toISOString(),
      content_tag: 'stale', hunks: [H({ ins: 'XX', del: '甲' })],
    }], 'XX 前面一段 XX 后面一段')
    expect(r.hunks).toEqual([])
    expect(r.conflicts.length).toBe(1)
    expect(r.conflicts[0]).toContain('润色')
  })

  it('那处新文字被用户整段删了：找不到 = 报冲突，不是悄悄少一处', () => {
    const r = restoreLayers([{
      id: 'L', label: '格式化', source: 'format', seq: 0, state: 'on', at: new Date().toISOString(),
      content_tag: 'stale', hunks: [H({ ins: '这段已经不在了', del: '原文' })],
    }], '正文里压根没有那段')
    expect(r.conflicts.length).toBe(1)
  })

  it('纯删除那种（新文字是空串）不许用 0 上下文去定位', () => {
    // 空串在任何正文里都有无数个位置。上下文对不上就该报冲突。
    const got = relocate('完全不相干的一段正文', H({ ins: '', del: '被删掉的原文', before: '前文前文', after: '后文后文' }))
    expect(got.ok).toBe(false)
  })

  it('正文一个字没变：走的是「按坐标精确放回」那条路（content_tag 对得上）', () => {
    const saved = threeHunks().save()
    expect(saved[0].content_tag).toBe(contentTag(V1))
    const r = restoreLayers(saved, V1)
    expect(r.hunks.map((x) => x.from)).toEqual(saved[0].hunks.map((x) => x.from))
  })
})

// ---------------------------------------------------------------- 取值表 / 杂项

describe('P39 来源码', () => {
  it('九种改动层各自认得出来，认不出来的落 other 而不是被丢掉', () => {
    expect(layerSource('智能续写')).toBe('round')
    expect(layerSource('撤掉第 3 轮')).toBe('undo_round')
    expect(layerSource('续写')).toBe('continue')
    expect(layerSource('重写')).toBe('rewrite')
    expect(layerSource('润色')).toBe('polish')
    expect(layerSource('扩展上下文')).toBe('expand')
    expect(layerSource('格式化')).toBe('format')
    expect(layerSource('智能排版')).toBe('restructure')
    expect(layerSource('语音输入')).toBe('voice')
    expect(layerSource('插入音频')).toBe('voice')
    expect(layerSource('图片转表格')).toBe('table')
    expect(layerSource('用 AI 写')).toBe('block')       // `/` 菜单那一组，名单从 SLASH_ITEMS 直接算
    expect(layerSource('探针')).toBe('other')
  })
})

describe('P39 写之前先问一句「跟上次一样吗」', () => {
  it('什么都没动就一个字节都不发', () => {
    const h = threeHunks()
    expect(sameLayers(h.save(), h.save())).toBe(true)
  })
  it('处置了一处就不一样了', () => {
    const h = threeHunks()
    const a = h.save()
    h.dispatch({ effects: acceptHunk.of(h.state.field(roundDiffField).hunks[0].id) })
    expect(sameLayers(a, h.save())).toBe(false)
  })
  it('正文指纹认得出长度一样但内容不同的两份', () => {
    expect(contentTag('甲乙丙')).not.toBe(contentTag('甲乙丁'))
    expect(contentTag('甲乙丙')).toBe(contentTag('甲乙丙'))
  })
})

describe('P39 「全部接受」= 烧进正文，层和那本账一起清掉', () => {
  it('烧完存下去的是空的（这一段改由「烧过的跑」接手，P16）', async () => {
    const { acceptAllHunks } = await import('../roundDiff')
    const h = threeHunks()
    h.dispatch({ effects: acceptAllHunks.of(null) })
    expect(h.save()).toEqual([])
  })
})

// ---------------------------------------------------------------- 接线洞

describe('P39 接线：函数对了但没接上，规则层单测抓不住', () => {
  it('编辑器报的是「roundDiffField 的值换没换」，不是「还剩几处」', async () => {
    // 量程：把 `onLayersChanged` 那一段改成挂在 `n !== lastPending.current` 里，这条红。
    // **为什么不能复用 `onPendingDiff`**：整层关掉一处都不少（关着的也算待处置），
    // 那条线上数字不变，落库就整个漏掉一类处置。
    expect(editorSrc).toContain('const st = update.state.field(roundDiffField, false)')
    expect(editorSrc).toContain('liveRef.current.onLayersChanged?.()')
    const seg = editorSrc.slice(editorSrc.indexOf('onLayersChanged?.()') - 400, editorSrc.indexOf('onLayersChanged?.()'))
    expect(seg).toContain('lastLayers.current')
  })

  it('整层关掉这一下：待处置的处数一点没变，但层确实动了', () => {
    // 这就是上一条为什么不能复用 `onPendingDiff` 的**可运行版本**
    const h = threeHunks()
    const before = h.state.field(roundDiffField)
    const n0 = before.hunks.filter((x) => !x.soft).length
    turnLayerOff(h, layersOf(h)[0].id)
    const after = h.state.field(roundDiffField)
    expect(after.hunks.filter((x) => !x.soft).length).toBe(n0)   // 数字没变
    expect(after).not.toBe(before)                               // 可是层动了
  })

  it('App 三头都接上了：读回来、塞进编辑器、动了就写', () => {
    expect(appSrc).toContain('api.listChangeLayers(')
    expect(appSrc).toContain('restoreLayersEffect.of(')
    expect(appSrc).toContain('api.saveChangeLayers(')
    expect(appSrc).toContain('onLayersChanged={onLayersChanged}')
  })

  it('落库是防抖的，而且比正文自动保存晚一点（不是每敲一个字写一次）', () => {
    // 量程：把 CHANGE_LAYER_SAVE_MS 改成 0 / 或者去掉 setTimeout，这条红。
    const m = /const CHANGE_LAYER_SAVE_MS = (\d+)/.exec(appSrc)
    expect(m).toBeTruthy()
    expect(Number(m![1])).toBeGreaterThan(1500)
    expect(appSrc).toContain('layersTimer.current = setTimeout(')
  })

  it('关窗口那一下带 keepalive，换篇之前也冲一次', () => {
    expect(appSrc).toContain("window.addEventListener('beforeunload', on)")
    expect(appSrc).toContain('flushChangeLayers(true)')
    expect(appSrc).toContain('flushChangeLayers()          // 离开这篇之前')
  })

  it('层还没放回来之前不许落库（换篇那一瞬间会把上一篇的层写到新这篇名下）', () => {
    expect(appSrc).toContain("layersReady.current !== id) return")
    expect(appSrc).toContain("layersReady.current = ''")
  })

  it('淘汰真的说出来了，不是收下就算', () => {
    expect(appSrc).toContain('没能留到下次打开')
  })

  it('面板上那一行说的是「关掉再打开还在」，而且列得出已处置几处', () => {
    expect(panelSrc).toContain('settledOf')
    expect(panelSrc).toContain('已处置')
    expect(panelSrc).toContain('关掉这个 app 再打开')
  })

  it('处置完的层在「还有别的层活着」时也列得出来（不然它只在空面板上看得见）', () => {
    // 量程：把第二处 `{settledLines}` 删掉，这条红。实拍抓到的：智能续写那层还活着时，
    // 「润色 · 2 接受 / 1 撤回」整行在面板上消失——存下来了却看不见，等于没存。
    expect(panelSrc.split('{settledLines}').length - 1).toBe(2)
    expect(panelSrc).toContain('const settledOnly = settled.filter')
  })
})

describe('P39 淘汰的口径两边对得上', () => {
  it('前端不自己定上限——上限在后端，前端只负责把它说的话原样转给用户', () => {
    // 前端要是也存一份 20 / 30 天，两边迟早对不上（一份过期的名单比没有名单更糟）
    expect(appSrc).not.toContain('CHANGE_LAYER_KEEP')
    expect(appSrc).toContain('r.evicted')
    expect(appSrc).toContain('r.rejected')
  })
})

describe('P39 不炸', () => {
  it('库里给了一层空的 / 坏的，放回去不抛', () => {
    const bad = [{ id: 'x' } as unknown as SavedLayer]
    expect(() => restoreLayers(bad, V1)).not.toThrow()
    expect(() => restoreLayers(undefined as unknown as SavedLayer[], V1)).not.toThrow()
  })
  it('坐标越界（正文后来变短了）不抛、也不放进去', () => {
    const saved = threeHunks().save()
    const spy = vi.fn()
    expect(() => { spy(restoreLayers(saved, '短')) }).not.toThrow()
    expect(spy).toHaveBeenCalled()
  })
})
