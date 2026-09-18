/**
 * P12 探针：C2 agent-native 再落地两条（`docs/agent-native-editor.md` §3.1「完成标准可检查」+ §3.5「目录 = 计划」），
 * 在真实 app 里对着真实笔记截图。跟 `probes.ts` 一样只认 URL 参数；状态打进 `[client:warn]` 日志，截图是佐证。
 *
 *   p12:tab:<id>:<tabId>   打开这篇，右栏切到某个页签（outline / plan…）——前后对比用同一条
 *   p12:tick:<id>          打开这篇 → 切到「计划」→ 把完成标准里第一个「要你判」的勾打上（看它落库、角标变）
 *   p12:jump:<id>:<n>      打开这篇 → 切到「计划」→ 点目录里第 n 节（0 起），看光标跳过去、当前节高亮
 */
import * as api from './api'
import type { Note } from './api'

type Ctx = Record<string, any> & { notes: Note[] }
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
const log = (s: string) => void api.clientLog('warn', s, '', 'probe')

export async function runP12(probe: string, ctx: Ctx): Promise<boolean> {
  if (!probe.startsWith('p12:')) return false
  const [, what, id, arg] = probe.split(':')
  const n = ctx.notes.find((x) => x.id === id)
  if (!n) { log(`p12 note ${id} not found`); return true }
  if (ctx.harnessProbeDone.current) return true
  ctx.harnessProbeDone.current = true
  await wait(600)
  await ctx.switchTo(n)
  await wait(900)
  const tab = what === 'tab' ? (arg || 'plan') : 'plan'
  ctx.setPaneFocus({ id: tab, n: Date.now() })
  await wait(900)
  const pane = document.querySelector('.right-pane-body')
  log(`p12 ${what} tab=${tab} pane-text=${JSON.stringify((pane?.textContent ?? '').slice(0, 400))}`)
  if (what === 'tick') {
    const box = document.querySelector<HTMLInputElement>('.plan-check input[type=checkbox]')
    log(`p12 tick found=${!!box} checked-before=${box?.checked}`)
    box?.click()
    await wait(1200)
    const chip = document.querySelector('.doc-intent-check')
    log(`p12 tick checked-after=${box?.checked} chip=${JSON.stringify(chip?.textContent ?? '')}`)
  }
  if (what === 'jump') {
    const items = document.querySelectorAll<HTMLElement>('.outline-item')
    const k = Number(arg || 0)
    log(`p12 jump items=${items.length} k=${k} text=${JSON.stringify(items[k]?.textContent ?? '')}`)
    items[k]?.click()
    await wait(800)
    const active = document.querySelector('.outline-item.active')
    log(`p12 jump active=${JSON.stringify(active?.textContent ?? '')}`)
  }
  return true
}
