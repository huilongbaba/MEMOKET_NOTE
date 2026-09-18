/**
 * P16 探针（只在 `--probe=` 启动时跑，生产路径不进）：agent-native 剩下两条，在真实 app 里对着真实笔记截图。
 *
 *   p16:rounds:<id>:burn      智能续写（假模型 harness 模式，三轮停）→「全部接受」（烧进正文）→ 右栏「改动」页签：
 *                             烧之后这次跑的每一轮还在不在列表里；日志记正文里第 1 / 2 / 3 轮写的句子各在不在
 *   p16:rounds:<id>:undo3     同上，再点第 3 轮的「只撤这一轮」→ 日志记撤前 / 撤后三轮句子各在不在（痛点 8：留一二轮、丢第三轮）
 *   p16:rounds:<id>:history   同上 burn，然后切到 ribbon「历史」看同一次跑的轮次折成一组
 *   p16:hover:<id>:<词>[:key][:insert]   打开这篇 → 把 <词> 滚进视口 → 按住 ⌥ 悬停在它上面（合成带 altKey 的 mousemove，≥400ms）
 *                             → 词边的来龙去脉卡；`key` = 走键盘那条路（光标停在词上，⌥↩）；`insert` = 词不在正文里，先打到文末
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
const button = (text: string, root: ParentNode = document) =>
  Array.from(root.querySelectorAll<HTMLElement>('button')).find((e) => (e.textContent ?? '').replace(/\s+/g, '') === text)
const has = (v: EditorView, s: string) => v.state.doc.toString().includes(s)
const roundsPresent = (v: EditorView) => [1, 2, 3].map((k) => `r${k}=${has(v, `第${k}轮假模型`) ? 'in' : 'OUT'}`).join(' ')

async function runThreeRounds(v: EditorView, out: string[]) {
  const base = v.state.doc.length
  const btn = button('智能续写')
  btn?.click()
  out.push(`clicked 智能续写 button=${!!btn} base len=${base}`)
  let rounds = 0
  for (let i = 0; i < 400; i++) {
    await wait(500)
    const running = Array.from(document.querySelectorAll<HTMLElement>('button')).some((e) => e.classList.contains('running') && (e.textContent ?? '').includes('停止'))
    const status = (document.querySelector('.fb-status-text')?.textContent ?? '')
    const m = status.match(/第 (\d+) 轮/); if (m) rounds = Math.max(rounds, Number(m[1]))
    if (i > 6 && !running) break
  }
  await wait(1500)
  out.push(`harness done: rounds seen=${rounds} len ${base}→${v.state.doc.length} ${roundsPresent(v)}`)
}

export async function runP16(probe: string, ctx: Ctx): Promise<boolean> {
  if (!probe.startsWith('p16:')) return false
  const [, kind, id, what, ...flags] = probe.split(':')
  const n = ctx.notes.find((x) => x.id === id)
  if (!n) { log(`p16 note ${id} not found`); return true }
  if (ctx.harnessProbeDone.current) return true
  ctx.harnessProbeDone.current = true
  await wait(600)
  await ctx.switchTo(n)
  await wait(1800)
  const v = view()
  if (!v) { log('p16: no editor'); return true }
  const out: string[] = []

  if (kind === 'rounds') {
    ctx.setPaneFocus({ id: 'plan', n: Date.now() })
    await wait(500)
    await runThreeRounds(v, out)
    const accept = button('全部接受')
    accept?.click()
    out.push(`clicked 全部接受 button=${!!accept}`)
    await wait(2500)                                                  // 自动保存 + 重查历史
    ctx.setPaneFocus({ id: 'changes', n: Date.now() })
    if (what === 'history') {
      // ribbon「历史」是编辑器顶上的面板，不是右栏页签：点那个按钮
      const h = Array.from(document.querySelectorAll<HTMLElement>('button')).find((e) => (e.textContent ?? '').replace(/\s+/g, '') === '历史')
      h?.click()
      out.push(`clicked ribbon 历史 button=${!!h}`)
    }
    await wait(1800)
    v.dispatch({ effects: EditorView.scrollIntoView(v.state.doc.length, { y: 'end' }) })
    const pane = document.querySelector('.right-pane-body')
    const cards = Array.from(pane?.querySelectorAll<HTMLElement>('.run-round') ?? []).map((e) => (e.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 80))
    out.push(`panel rounds listed=${cards.length}: ${JSON.stringify(cards)}`)
    out.push(`panel text=${JSON.stringify((pane?.textContent ?? '').replace(/\s+/g, ' ').slice(0, 300))}`)
    if (what === 'history') {
      const groups = Array.from(document.querySelectorAll<HTMLElement>('.revision-run')).map((e) => (e.querySelector('summary')?.textContent ?? '').replace(/\s+/g, ' ').trim())
      out.push(`history run groups=${groups.length}: ${JSON.stringify(groups)}`)
    }
    if (what === 'undo3') {
      out.push(`before undo: ${roundsPresent(v)}`)
      const third = Array.from(pane?.querySelectorAll<HTMLElement>('.run-round') ?? []).find((e) => /第 3 轮/.test(e.textContent ?? ''))
      const b = third ? button('只撤这一轮', third) : undefined
      b?.click()
      out.push(`clicked 只撤这一轮(第3轮) button=${!!b}`)
      await wait(2000)
      out.push(`after undo: ${roundsPresent(v)} len=${v.state.doc.length}`)
      out.push(`toasts=${JSON.stringify(Array.from(document.querySelectorAll('.toast')).map((e) => e.textContent?.trim().slice(0, 120)))}`)
      v.dispatch({ effects: EditorView.scrollIntoView(v.state.doc.length, { y: 'end' }) })
    }
    log(`p16 rounds ${what}\n` + out.join('\n'))
    return true
  }

  if (kind === 'hover') {
    const word = decodeURIComponent(what)
    if (flags.includes('insert') && !has(v, word)) {
      const end = v.state.doc.length
      v.dispatch({ changes: { from: end, insert: `\n\n${word}` }, userEvent: 'input.type' })
      await wait(600)
    }
    const at = v.state.doc.toString().indexOf(word)
    if (at < 0) { log(`p16 hover: 「${word}」not in doc`); return true }
    v.dispatch({ effects: EditorView.scrollIntoView(at, { y: 'center' }) })
    await wait(700)
    const c = v.coordsAtPos(at + 1)
    if (!c) { log('p16 hover: no coords'); return true }
    const x = (c.left + c.right) / 2 + 2
    const y = (c.top + c.bottom) / 2
    if (flags.includes('key')) {
      v.dispatch({ selection: { anchor: at + 1 } })
      v.focus()
      v.contentDOM.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', altKey: true, bubbles: true, cancelable: true }))
      out.push(`⌥↩ at 「${word}」`)
    } else {
      // 按住 ⌥ 停在词上：几次 mousemove（进入 + 停住），总时长跨过 400ms 的门槛
      for (let i = 0; i < 4; i++) {
        v.contentDOM.dispatchEvent(new MouseEvent('mousemove', { clientX: x + i, clientY: y, altKey: true, bubbles: true }))
        await wait(180)
      }
      out.push(`⌥ hover at 「${word}」(${Math.round(x)},${Math.round(y)})`)
    }
    await wait(1600)
    const card = document.querySelector<HTMLElement>('.trace-card')
    out.push(`card=${!!card} text=${JSON.stringify((card?.textContent ?? '').replace(/\s+/g, ' ').slice(0, 400))}`)
    if (card) {
      const r = card.getBoundingClientRect()
      const pane = document.querySelector('.note-pane')?.getBoundingClientRect()
      out.push(`card rect=${Math.round(r.left)},${Math.round(r.top)} ${Math.round(r.width)}x${Math.round(r.height)} pane.right=${Math.round(pane?.right ?? 0)} inside=${pane ? r.right <= pane.right + 1 : '?'}`)
      out.push(`focus in card=${card.contains(document.activeElement)}`)
    }
    log(`p16 hover\n` + out.join('\n'))
    return true
  }
  return true
}
