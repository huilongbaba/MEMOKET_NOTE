/** P11 的探针（只在 `--probe=` 启动时跑，生产路径不进）。
 *
 *   p11:undo-harness:<id>   智能续写（假模型 `harness` 模式：每轮四片续写各隔 900ms，第 2 轮起一条 replace +
 *                           一条 delete 修订）跑完之后 ⌘Z：按几次才回到开跑前的正文、有没有吃掉用户自己的字；
 *                           再 ⇧⌘Z 逐轮回来。每一步把正文长度 / 尾巴打进 `[client:warn]` 日志。
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

export async function runP11(probe: string, ctx: Ctx): Promise<boolean> {
  if (!probe.startsWith('p11:')) return false
  const [, what, id] = probe.split(':')
  const n = ctx.notes.find((x) => x.id === id)
  if (!n) { log(`p11 note ${id} not found`); return true }
  if (ctx.harnessProbeDone.current) return true
  ctx.harnessProbeDone.current = true
  await wait(600)
  await ctx.switchTo(n)
  await wait(1800)
  const v = view()
  if (!v) { log('p11: no editor'); return true }
  v.focus()
  if (what !== 'undo-harness') { log(`p11: unknown probe ${what}`); return true }

  const out: string[] = []
  const len = () => v.state.doc.length
  // 用户自己先打几个字（记历史）——⌘Z 撤完 AI 的那几轮之后，下一次才该轮到它
  v.dispatch({ selection: { anchor: len() } })
  typeText(v, '\n\n用户自己打的一句。')
  await wait(800)
  const base = len()
  const baseText = v.state.doc.toString()
  out.push(`base len=${base} tail=${tail(v)}`)

  const btn = Array.from(document.querySelectorAll<HTMLElement>('button')).find((e) => (e.textContent ?? '').replace(/\s+/g, '') === '智能续写')
  btn?.click()
  out.push(`clicked 智能续写 button=${!!btn}`)
  // 等它跑完：主钮从「停止」变回「智能续写」（最多 150s）
  let rounds = 0
  for (let i = 0; i < 300; i++) {
    await wait(500)
    const running = Array.from(document.querySelectorAll<HTMLElement>('button')).some((e) => e.classList.contains('running') && (e.textContent ?? '').includes('停止'))
    const status = (document.querySelector('.fb-status-text')?.textContent ?? '')
    const m = status.match(/第 (\d+) 轮/); if (m) rounds = Math.max(rounds, Number(m[1]))
    if (i > 6 && !running) break
  }
  await wait(1500)
  const after = len()
  out.push(`harness done: rounds seen=${rounds} len ${base}→${after} (+${after - base}) tail=${tail(v)}`)
  const cards = document.querySelectorAll('.agent-round, .agent-activity .round, [class*=agent-round]').length
  out.push(`agent panel rounds=${cards}`)

  // ⌘Z 一次一次按，直到回到 base（最多 12 次）；记每一次撤掉了多少
  const steps: string[] = []
  let presses = 0
  let ateUser = false
  for (let i = 0; i < 12; i++) {
    const before = len()
    key(v, 'z', { meta: true }, 90); await wait(250)
    presses++
    steps.push(`#${presses}: ${before}→${len()} (${before - len() >= 0 ? '-' : '+'}${Math.abs(before - len())})`)
    if (v.state.doc.toString() === baseText) break
    if (len() < base) { ateUser = true; break }
  }
  out.push(`⌘Z presses to get back to base: ${presses}${v.state.doc.toString() === baseText ? ' (exact)' : ' (NOT back)'}${ateUser ? ' — ATE USER TEXT' : ''}`)
  out.push('steps: ' + steps.join(' | '))
  // 再按一次：应该撤掉用户自己那句（证明上面没多撤）
  const b2 = len()
  key(v, 'z', { meta: true }, 90); await wait(250)
  out.push(`one more ⌘Z: ${b2}→${len()} tail=${tail(v, 30)}`)
  // ⇧⌘Z 回来
  let redos = 0
  for (let i = 0; i < 14; i++) { const b = len(); key(v, 'z', { meta: true, shift: true }, 90); await wait(200); redos++; if (len() === b) break }
  out.push(`⇧⌘Z ×${redos} → len=${len()} (harness-end was ${after})`)
  log('p11 undo-harness\n' + out.join('\n'))
  return true
}
