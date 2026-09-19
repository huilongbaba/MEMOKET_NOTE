/**
 * P19 探针（只在 `--probe=` 启动时跑，生产路径不进）：**「只撤第 N 轮」在真 app 里拍一次**。
 *
 *   p19:undoround:<id>:<n>   智能续写（假模型，三轮停）→ 右栏「改动」→ 第 n 轮的「只撤这一轮」
 *                            → 日志记撤前 / 撤后每一轮写的句子各在不在、toast 说了什么
 *
 * P16 的探针只撤第 3 轮（最后一轮，没人动过它）；P18 把「后一轮改过它的句子」那种情况做了
 * 逐轮映射（`editor/undoRound.paragraphDiff` / `mapPos`），但**只在单测里验过，真 app 里没拍**
 * （P18「下一步」原话）。这条探针补的就是那一张：撤第 1 轮，而第 2 轮改过第 1 轮写的那一句。
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

/** 每一轮在正文里留下的痕迹：原句 / 被第 2 轮改过的那句 / 第二段推论。 */
function marks(v: EditorView): string {
  return [1, 2, 3].map((k) => {
    const first = has(v, `第${k}轮假模型写的第一句`)
    const edited = k === 1 && has(v, '第1轮假模型改过的第一句')
    const second = has(v, `第${k}轮假模型另写的一段推论`)
    return `r${k}=${first ? '原句在' : edited ? '改过的在' : second ? '只剩第二段' : 'OUT'}${second ? '+推论' : ''}`
  }).join(' ')
}

export async function runP19(probe: string, ctx: Ctx): Promise<boolean> {
  if (!probe.startsWith('p19:')) return false
  const [, kind, id, nRaw] = probe.split(':')
  if (kind !== 'undoround') return true
  const n = Number(nRaw || 1)
  const note = ctx.notes.find((x) => x.id === id)
  if (!note) { log(`p19 note ${id} not found`); return true }
  if (ctx.harnessProbeDone.current) return true
  ctx.harnessProbeDone.current = true
  await wait(600)
  await ctx.switchTo(note)
  await wait(1800)
  const v = view()
  if (!v) { log('p19: no editor'); return true }
  const out: string[] = []

  ctx.setPaneFocus({ id: 'plan', n: Date.now() })
  await wait(500)
  const base = v.state.doc.length
  const start = v.state.doc.toString()
  button('智能续写')?.click()
  out.push(`开跑 len=${base}`)
  let rounds = 0
  for (let i = 0; i < 400; i++) {
    await wait(500)
    const running = Array.from(document.querySelectorAll<HTMLElement>('button')).some((e) => e.classList.contains('running') && (e.textContent ?? '').includes('停止'))
    const m = (document.querySelector('.fb-status-text')?.textContent ?? '').match(/第 (\d+) 轮/)
    if (m) rounds = Math.max(rounds, Number(m[1]))
    if (i > 6 && !running) break
  }
  await wait(1800)
  out.push(`跑完 rounds=${rounds} len ${base}→${v.state.doc.length}`)
  out.push(`撤之前: ${marks(v)}`)
  // **这一张的前提**：第 2 轮真的改过第 1 轮写的那句（改过的在 = 映射有活可干）
  out.push(`第 2 轮改过第 1 轮那句吗: ${has(v, '第1轮假模型改过的第一句')}`)
  out.push(`撤之前正文尾部: ${JSON.stringify(v.state.doc.toString().slice(-420))}`)

  ctx.setPaneFocus({ id: 'changes', n: Date.now() })
  await wait(1800)
  const pane = document.querySelector('.right-pane-body')
  const cards = Array.from(pane?.querySelectorAll<HTMLElement>('.run-round') ?? [])
  out.push(`轮次卡 ${cards.length} 张: ${JSON.stringify(cards.map((e) => (e.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 40)))}`)
  const card = cards.find((e) => new RegExp(`第 ${n} 轮`).test(e.textContent ?? ''))
  const b = card ? button('只撤这一轮', card) : undefined
  out.push(`点「只撤这一轮」(第 ${n} 轮) button=${!!b}`)
  b?.click()
  await wait(2500)
  out.push(`撤之后: ${marks(v)} len=${v.state.doc.length}`)
  out.push(`撤之后正文尾部: ${JSON.stringify(v.state.doc.toString().slice(-420))}`)
  out.push(`toast: ${JSON.stringify(Array.from(document.querySelectorAll('.toast')).map((e) => e.textContent?.trim().slice(0, 160)))}`)
  out.push(`开跑前那段还在吗: ${v.state.doc.toString().includes(start.trim().slice(0, 20))}`)
  log('p19 undoround\n' + out.join('\n'))
  return true
}
