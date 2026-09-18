/** P13 的探针（只在 `--probe=` 启动时跑，生产路径不进）。
 *
 *   p13:undo-tap:<id>   「续写」（假模型 slowstream：四片各隔 900ms）跑完之后 ⌘Z：按几次才回到开跑前，
 *                       有没有吃掉用户自己的字；⇧⌘Z 回来。P10 量的是「封之后 48/48」，P13 #5 把封那一步删了，
 *                       续写跟智能续写走同一套 `aiSyncSpec`——这条量的是删了之后还是 1 次。
 *   p13:check:<id>      智能续写（假模型 harness 模式：每轮写一段带出处 + 一段没出处）：跑完把执行面板里
 *                       「你定的完成标准」那几行打进日志；截图靠 --shot-delay。
 *   p13:keys:<id>       ⌘E / ⇧⌘X：打一句、选中、合成 keydown 打进 CM，记正文。
 */
import { EditorView } from '@codemirror/view'
import * as api from './api'
import type { Note } from './api'

type Ctx = Record<string, any> & { notes: Note[] }
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
const log = (s: string) => void api.clientLog('warn', s, '', 'probe')

function view(): EditorView | null {
  const el = document.querySelector('.note-scroll .cm-content')
  return el ? EditorView.findFromDOM(el as HTMLElement) : null
}
function key(v: EditorView, k: string, mods: { meta?: boolean; shift?: boolean } = {}, code?: number) {
  const ev = new KeyboardEvent('keydown', { key: k, keyCode: code, metaKey: !!mods.meta, shiftKey: !!mods.shift, bubbles: true, cancelable: true } as KeyboardEventInit)
  v.contentDOM.dispatchEvent(ev)
}
function typeText(v: EditorView, s: string) {
  const { from, to } = v.state.selection.main
  v.dispatch({ changes: { from, to, insert: s }, selection: { anchor: from + s.length }, userEvent: 'input.type' })
}
const tail = (v: EditorView, n = 70) => JSON.stringify(v.state.doc.sliceString(Math.max(0, v.state.doc.length - n)))
const button = (text: string) => Array.from(document.querySelectorAll<HTMLElement>('button, .fb-btn')).find((e) => (e.textContent ?? '').replace(/\s+/g, '') === text)

export async function runP13(probe: string, ctx: Ctx): Promise<boolean> {
  if (!probe.startsWith('p13:')) return false
  const [, what, id] = probe.split(':')
  const n = ctx.notes.find((x) => x.id === id)
  if (!n) { log(`p13 note ${id} not found`); return true }
  if (ctx.harnessProbeDone.current) return true
  ctx.harnessProbeDone.current = true
  await wait(600)
  await ctx.switchTo(n)
  await wait(1800)
  const v = view()
  if (!v) { log('p13: no editor'); return true }
  v.focus()
  const out: string[] = []
  const len = () => v.state.doc.length

  if (what === 'undo-tap') {
    v.dispatch({ selection: { anchor: len() } })
    typeText(v, '\n\n用户自己打的一句。')
    await wait(800)
    const base = len()
    const baseText = v.state.doc.toString()
    out.push(`base len=${base} tail=${tail(v)}`)
    const btn = button('续写')
    btn?.click()
    out.push(`clicked 续写 button=${!!btn}`)
    for (let i = 0; i < 80; i++) { await wait(500); if (i > 4 && len() > base && !document.querySelector('.fb-btn.running, .fb-busy')) break }
    await wait(1500)
    const after = len()
    out.push(`tap done: len ${base}→${after} (+${after - base}) tail=${tail(v)}`)
    const steps: string[] = []
    let presses = 0
    let ateUser = false
    for (let i = 0; i < 6; i++) {
      const before = len()
      key(v, 'z', { meta: true }, 90); await wait(250)
      presses++
      steps.push(`#${presses}: ${before}→${len()}`)
      if (v.state.doc.toString() === baseText) break
      if (len() < base) { ateUser = true; break }
    }
    out.push(`⌘Z presses to get back to base: ${presses}${v.state.doc.toString() === baseText ? ' (exact)' : ' (NOT back)'}${ateUser ? ' — ATE USER TEXT' : ''}`)
    out.push('steps: ' + steps.join(' | '))
    const b2 = len()
    key(v, 'z', { meta: true }, 90); await wait(250)
    out.push(`one more ⌘Z: ${b2}→${len()} tail=${tail(v, 30)}`)
    let redos = 0
    for (let i = 0; i < 6; i++) { const b = len(); key(v, 'z', { meta: true, shift: true }, 90); await wait(200); redos++; if (len() === b) break }
    out.push(`⇧⌘Z ×${redos} → len=${len()} (tap-end was ${after})`)
    log('p13 undo-tap\n' + out.join('\n'))
    return true
  }

  if (what === 'check') {
    ctx.setPaneFocus({ id: 'plan', n: Date.now() })
    await wait(600)
    const base = len()
    const btn = button('智能续写')
    btn?.click()
    out.push(`clicked 智能续写 button=${!!btn} base len=${base}`)
    let rounds = 0
    for (let i = 0; i < 300; i++) {
      await wait(500)
      const running = Array.from(document.querySelectorAll<HTMLElement>('button')).some((e) => e.classList.contains('running') && (e.textContent ?? '').includes('停止'))
      const status = (document.querySelector('.fb-status-text')?.textContent ?? '')
      const m = status.match(/第 (\d+) 轮/); if (m) rounds = Math.max(rounds, Number(m[1]))
      if (i > 6 && !running) break
    }
    await wait(1200)
    out.push(`harness done: rounds seen=${rounds} len ${base}→${len()}`)
    const pane = document.querySelector('.right-pane-body')
    // 执行面板在「计划」页签底部：把第一条命中滚进视口，截图才看得见
    Array.from(pane?.querySelectorAll('p') ?? []).find((e) => /你定的完成标准/.test(e.textContent ?? ''))?.scrollIntoView({ block: 'start' })
    const lines = (pane?.textContent ?? '').split(/(?<=。)/).filter((l) => /你定的完成标准|代码判据/.test(l))
    out.push(`check_hit lines (${lines.length}):\n` + lines.map((l) => '  ' + l.trim().slice(0, 220)).join('\n'))
    out.push(`status=${JSON.stringify(document.querySelector('.fb-status-text')?.textContent ?? '')}`)
    log('p13 check\n' + out.join('\n'))
    return true
  }

  if (what === 'keys') {
    v.dispatch({ selection: { anchor: len() } })
    typeText(v, '\n\n代码片段')
    const a = len() - 4
    v.dispatch({ selection: { anchor: a, head: len() } })
    key(v, 'e', { meta: true }, 69); await wait(200)
    out.push(`⌘E on 「代码片段」 → tail=${tail(v, 12)}`)
    key(v, 'e', { meta: true }, 69); await wait(200)
    out.push(`⌘E again → tail=${tail(v, 12)}`)
    v.dispatch({ selection: { anchor: a, head: len() } })
    key(v, 'x', { meta: true, shift: true }, 88); await wait(200)
    out.push(`⇧⌘X → tail=${tail(v, 12)}`)
    key(v, 'x', { meta: true, shift: true }, 88); await wait(200)
    out.push(`⇧⌘X again → tail=${tail(v, 12)}`)
    v.dispatch({ selection: { anchor: a, head: len() } })
    key(v, 'x', { meta: true, shift: true }, 88); await wait(200)
    ctx.setShowShortcuts(true)
    await wait(400)
    const row = Array.from(document.querySelectorAll('kbd, td, span, div')).find((e) => /⌘E/.test(e.textContent ?? '') && (e.textContent ?? '').length < 40)
    out.push(`shortcuts panel row: ${JSON.stringify(row?.parentElement?.textContent?.slice(0, 80) ?? '')}`)
    log('p13 keys\n' + out.join('\n'))
    return true
  }
  log(`p13: unknown probe ${what}`)
  return true
}
