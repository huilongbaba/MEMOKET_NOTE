/**
 * P15 探针：导入 / 录音 / 剪藏默认进托盘 + 托盘项标题回退（`docs/TRACELOG-product.md` P15 节），在真实 app 里截图。
 * 跟 `probes.ts` 一样只认 URL 参数；状态打进 `[client:warn]` 日志，截图是佐证。
 *
 *   p15:tray:<id>:tools                 打开这篇 → 右栏「记忆」→ 托盘格：「默认进托盘」开关 + 剪藏输入框（空托盘）
 *   p15:tray:<id>:clip:<url>            同上，把 <url>（`~` 代替 `:`）贴进剪藏框、点「剪藏」→ 看托盘里那条 import 项
 *   p15:tray:<id>:untitled:<n2>         放一篇标题是「未命名」的笔记进托盘 → 托盘里显示的是正文首行（不是「未命名」）
 *   p15:tray:<id>:recmenu               点录音钮 → 看菜单第一项是「录音 → 进托盘」
 *   p15:tray:<id>:md                    把两个 .md 文件当导入（`importMarkdown` 同一条路）→ 落成的两篇进这篇的托盘
 */
import * as api from './api'
import type { Note } from './api'
import { noteExcerpt } from './util/tray'

type Ctx = Record<string, any> & { notes: Note[] }
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
const log = (s: string) => void api.clientLog('warn', s, '', 'probe')
const titles = () => JSON.stringify(Array.from(document.querySelectorAll('.tray-item .tray-title')).map((e) => e.textContent))
const kinds = () => JSON.stringify(Array.from(document.querySelectorAll('.tray-item .tray-kind')).map((e) => e.textContent?.trim()))

export async function runP15(probe: string, ctx: Ctx): Promise<boolean> {
  if (!probe.startsWith('p15:')) return false
  const [, , id, what, arg] = probe.split(':')
  const n = ctx.notes.find((x) => x.id === id)
  if (!n) { log(`p15 note ${id} not found`); return true }
  if (ctx.harnessProbeDone.current) return true
  ctx.harnessProbeDone.current = true
  await api.putTray(id, []).catch(() => {})                       // 每次从空托盘开始，截图可复现
  try { localStorage.setItem('memoket.tray.default', '1') } catch { /* 无所谓 */ }
  await wait(400)
  await ctx.switchTo(n)
  await wait(900)
  ctx.setPaneFocus({ id: 'memory', n: Date.now() })
  await wait(600)
  const box = document.querySelector<HTMLInputElement>('.tray-default input')
  log(`p15 ${what} toggle=${box ? box.checked : 'missing'} clipbox=${!!document.querySelector('.tray-clip-url')} count=${document.querySelector('.tray-panel')?.getAttribute('data-count')}`)

  if (what === 'clip') {
    const url = (arg || '').replace(/~/g, ':')
    const input = document.querySelector<HTMLInputElement>('.tray-clip-url')
    if (!input) { log('p15 clip: no input'); return true }
    // 走用户那条路：往 React 受控输入里打字（用原生 setter 触发 onChange），再提交表单
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
    setter?.call(input, url)
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await wait(200)
    document.querySelector<HTMLButtonElement>('.tray-clip-go')?.click()
    for (let i = 0; i < 40; i++) { await wait(250); if (document.querySelector('.tray-panel')?.getAttribute('data-count') !== '0') break }
    await wait(500)
    log(`p15 clip count=${document.querySelector('.tray-panel')?.getAttribute('data-count')} kinds=${kinds()} titles=${titles()} excerpt=${JSON.stringify(document.querySelector('.tray-excerpt')?.textContent?.slice(0, 80) ?? '')}`)
    return true
  }
  if (what === 'untitled') {
    const target = ctx.notes.find((x: Note) => x.id === arg) ?? await api.getNote(arg).catch(() => null)
    if (!target) { log(`p15 untitled: ${arg} not found`); return true }
    window.dispatchEvent(new CustomEvent('tray-add', { detail: { kind: 'note', ref_id: arg, title: target.title || '未命名', excerpt: noteExcerpt(target.content ?? '') } }))
    await wait(900)
    log(`p15 untitled stored_title=${JSON.stringify(target.title)} shown=${titles()}`)
    return true
  }
  if (what === 'recmenu') {
    const btn = Array.from(document.querySelectorAll<HTMLElement>('.fb-btn')).find((e) => (e.getAttribute('title') ?? '').startsWith('录音'))
    btn?.click()
    await wait(500)
    log(`p15 recmenu button=${!!btn} items=${JSON.stringify(Array.from(document.querySelectorAll('.context-menu [role=menuitem]')).map((e) => e.textContent?.trim().slice(0, 40)))}`)
    return true
  }
  if (what === 'md') {
    const files = [
      new File(['# 供应商会议\n\n4 月 10 日拿到手板，PCBA 15 套。'], '供应商会议.md', { type: 'text/markdown' }),
      new File(['# 众筹页面\n\n3 月 10 日上众筹，页面要放自己的 UI。'], '众筹页面.md', { type: 'text/markdown' }),
    ]
    const dt = new DataTransfer()
    for (const f of files) dt.items.add(f)
    await ctx.importMarkdown(dt.files, api.ROOT_ID, false)
    await wait(1200)
    // importMarkdown 结束会打开导入的那篇；切回来看托盘
    await ctx.switchTo(n)
    await wait(1200)
    ctx.setPaneFocus({ id: 'memory', n: Date.now() })
    await wait(600)
    log(`p15 md count=${document.querySelector('.tray-panel')?.getAttribute('data-count')} kinds=${kinds()} titles=${titles()}`)
    return true
  }
  return true
}
