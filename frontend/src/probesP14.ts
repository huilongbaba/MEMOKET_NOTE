/**
 * P14 探针：材料托盘（`docs/agent-native-editor.md` §3.4），在真实 app 里对着真实笔记截图。
 * 跟 `probes.ts` 一样只认 URL 参数；状态打进 `[client:warn]` 日志，截图是佐证。
 *
 *   p14:tray:<id>:empty                 打开这篇 → 右栏「记忆」→ 托盘空着（先把托盘清空）
 *   p14:tray:<id>:three:<n1>,<n2>,<fid> 打开这篇 → 通过「放进托盘」同一条路（`tray-add` 事件）放两篇笔记 + 一条事实 → 看托盘三项
 *   p14:tray:<id>:slash:<n1>,<n2>,<fid> 同上放三项 → 在文末打 `/托盘` → 看「从托盘写」那一项
 *   p14:tray:<id>:linkmenu:<n1>         正文末尾插一枚 `[[` 链接 → 右键它 → 看「摊到这篇桌上」菜单
 */
import { EditorView } from '@codemirror/view'
import * as api from './api'
import type { Note } from './api'
import { noteExcerpt } from './util/tray'

type Ctx = Record<string, any> & { notes: Note[] }
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
const log = (s: string) => void api.clientLog('warn', s, '', 'probe')

async function fill(ctx: Ctx, refs: string[]) {
  // 走的是用户那条路：`tray-add` 事件 → TrayPanel 收、落库。不直接 PUT，让「放进托盘」这条线也被截图覆盖
  for (const ref of refs) {
    if (/^[0-9a-f]{12}$/.test(ref)) {
      const n = ctx.notes.find((x: Note) => x.id === ref) ?? await api.getNote(ref).catch(() => null)
      window.dispatchEvent(new CustomEvent('tray-add', { detail: { kind: 'note', ref_id: ref, title: n?.title || '未命名', excerpt: noteExcerpt(n?.content ?? '') } }))
    } else {
      const f = await api.factPeek(ref).catch(() => null)
      window.dispatchEvent(new CustomEvent('tray-add', { detail: { kind: 'fact', ref_id: ref, title: f?.when ?? '', excerpt: f?.text ?? ref } }))
    }
    await wait(700)
  }
}

export async function runP14(probe: string, ctx: Ctx): Promise<boolean> {
  if (!probe.startsWith('p14:')) return false
  const [, , id, what, arg] = probe.split(':')
  const n = ctx.notes.find((x) => x.id === id)
  if (!n) { log(`p14 note ${id} not found`); return true }
  if (ctx.harnessProbeDone.current) return true
  ctx.harnessProbeDone.current = true
  await api.putTray(id, []).catch(() => {})                       // 每次从空托盘开始，截图可复现
  await wait(400)
  await ctx.switchTo(n)
  await wait(900)
  ctx.setPaneFocus({ id: 'memory', n: Date.now() })
  await wait(600)
  const refs = (arg || '').split(',').filter(Boolean)
  if (what === 'three' || what === 'slash') {
    await fill(ctx, refs)
    await wait(900)
  }
  const panel = document.querySelector('.tray-panel')
  log(`p14 ${what} count=${panel?.getAttribute('data-count')} items=${JSON.stringify(Array.from(document.querySelectorAll('.tray-item .tray-title')).map((e) => e.textContent))}`)
  if (what === 'slash') {
    const v = ctx.editorViewRef.current
    if (!v) return true
    let end = v.state.doc.length
    v.focus()
    if (end) { v.dispatch({ changes: { from: end, insert: '\n\n' }, selection: { anchor: end + 2 }, userEvent: 'input.type' }); end += 2 }
    v.dispatch({ changes: { from: end, insert: '/' }, selection: { anchor: end + 1 }, userEvent: 'input.type' })
    await wait(300)
    for (const ch of '托盘') v.dispatch({ changes: { from: v.state.selection.main.head, insert: ch }, selection: { anchor: v.state.selection.main.head + 1 }, userEvent: 'input.type' })
    // 菜单锚在文末：把文末滚进视口，不然截图里看不到（实拍第一版菜单在折叠线下面）
    v.dispatch({ effects: EditorView.scrollIntoView(v.state.doc.length, { y: 'end' }) })
    await wait(600)
    log(`p14 slash items=${JSON.stringify(Array.from(document.querySelectorAll('.slash-item .slash-label')).map((e) => e.textContent))}`)
  }
  if (what === 'linkmenu') {
    const v = ctx.editorViewRef.current
    const target = ctx.notes.find((x: Note) => x.id === refs[0])
    if (!v || !target) return true
    const end = v.state.doc.length
    v.dispatch({ changes: { from: end, insert: `\n\n参考 [${target.title || '未命名'}](note://${target.id})\n\n` }, selection: { anchor: 0 } })
    await wait(600)
    const chip = document.querySelector<HTMLElement>('.cm-note-link')
    log(`p14 linkmenu chip=${!!chip} text=${JSON.stringify(chip?.textContent ?? '')}`)
    const r = chip?.getBoundingClientRect()
    chip?.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: (r?.left ?? 300) + 8, clientY: (r?.bottom ?? 300) }))
    await wait(500)
    log(`p14 linkmenu menu=${JSON.stringify(Array.from(document.querySelectorAll('.context-menu [role=menuitem], .context-menu button')).map((e) => e.textContent?.trim()).slice(0, 4))}`)
  }
  return true
}
