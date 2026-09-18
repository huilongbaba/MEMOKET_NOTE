/**
 * P10 探针：C3「编辑器基本功」五条各一个用例，在真实 app 里量（`docs/product-readiness-plan.md` §2 C3）。
 * 跟 `probes.ts` 一样只认 URL 参数；量出来的东西全部打进 `[client:warn]` 日志，截图只是佐证。
 *
 *   p10:keys:<id>    快捷键逐条：合成 keydown 打进 CM（CM 的 keymap 认 `key` / 修饰键），每步记正文和光标
 *   p10:undo:<id>    撤销粒度：一句话逐字打进去 → ⌘Z 撤掉多少；点「续写」（假模型）→ ⌘Z 撤掉什么
 *   p10:paste:<id>   粘贴：HTML / 多段纯文本 / markdown / URL（有选区、无选区）/ 图片，各变成什么
 *   p10:ime:<id>     中文输入法：模拟 IME 的 DOM 变更（compositionstart → 直接改文本节点 → compositionend），
 *                    组字期间 `/` 菜单、Enter、圆点重算会不会打断
 *   p10:perf:<id>    长文：逐字打 40 个字，量 dispatch 同步耗时 + 到下一帧的时间 + longtask；圆点从停手到画出来多久
 */
import { EditorView } from '@codemirror/view'
import { slashField } from './editor/slashMenu'
import * as api from './api'
import type { Note } from './api'

type Ctx = Record<string, any> & { notes: Note[] }
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
const log = (s: string) => void api.clientLog('warn', s, '', 'probe')

function view(): EditorView | null {
  const el = document.querySelector('.note-scroll .cm-content')
  return el ? EditorView.findFromDOM(el as HTMLElement) : null
}
/** 合成一个 keydown 打到编辑器上（会冒泡到 window，App 级的 ⌘K / ⌘S / ⌘/ 也收得到）。 */
function key(v: EditorView, k: string, mods: { meta?: boolean; shift?: boolean; alt?: boolean } = {}, code?: number) {
  const ev = new KeyboardEvent('keydown', { key: k, keyCode: code, metaKey: !!mods.meta, shiftKey: !!mods.shift, altKey: !!mods.alt, bubbles: true, cancelable: true } as KeyboardEventInit)
  v.contentDOM.dispatchEvent(ev)
  return ev.defaultPrevented
}
function typeText(v: EditorView, s: string) {
  const { from, to } = v.state.selection.main
  v.dispatch({ changes: { from, to, insert: s }, selection: { anchor: from + s.length }, userEvent: 'input.type' })
}
function line(v: EditorView) { const l = v.state.doc.lineAt(v.state.selection.main.head); return JSON.stringify(l.text) }
function tail(v: EditorView, n = 160) { return JSON.stringify(v.state.doc.sliceString(Math.max(0, v.state.doc.length - n))) }

export async function runP10(probe: string, ctx: Ctx): Promise<boolean> {
  if (!probe.startsWith('p10:')) return false
  const [, what, id, ...rest] = probe.split(':')
  const n = ctx.notes.find((x) => x.id === id)
  if (!n) { log(`p10 note ${id} not found`); return true }
  if (ctx.harnessProbeDone.current) return true
  ctx.harnessProbeDone.current = true
  // perf：圆点那几批请求什么时候发、多久回——包住 fetch，**在打开笔记之前**装好（打开那一刻就会算一轮）
  const calls: { at: number; ms: number }[] = []
  if (what === 'perf') {
    const rawFetch = window.fetch.bind(window)
    window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      const rec = { at: performance.now(), ms: -1 }
      if (url.includes('relations/batch')) calls.push(rec)
      const res = await rawFetch(input, init)
      rec.ms = performance.now() - rec.at
      return res
    }) as typeof window.fetch
  }
  const tOpen = performance.now()
  await wait(600)
  await ctx.switchTo(n)
  await wait(1800)
  const v = view()
  if (!v) { log('p10: no editor'); return true }
  v.focus()

  if (what === 'keys' && rest[0] === 'f') {
    // 只按一次 ⌘F，看正文有没有被动到（第一版全套探针里 ⌘F 之后 len=0、title=''）
    const out: string[] = []
    const snap = (label: string) => out.push(`${label}: len=${v.state.doc.length} title=${JSON.stringify((document.querySelector('.note-title') as HTMLInputElement | null)?.value)} tabs=${document.querySelectorAll('.note-tab').length} search=${!!document.querySelector('.cm-search')} active=${document.activeElement?.className?.toString().slice(0, 24)} live=${view() === v}`)
    snap('before')
    const prevented = key(v, 'f', { meta: true }, 70)
    snap(`0ms prevented=${prevented}`)
    await wait(200); snap('200ms')
    await wait(600); snap('800ms')
    log('p10 keys-f\n' + out.join('\n'))
    return true
  }
  if (what === 'keys') {
    const end = () => v.state.doc.length
    const out: string[] = []
    const say = (label: string, extra = '') => out.push(`${label} → line=${line(v)} sel=${v.state.selection.main.from}-${v.state.selection.main.to} len=${v.state.doc.length} focus=${document.activeElement?.className?.toString().slice(0, 30)} title=${(document.querySelector('.note-title') as HTMLInputElement | null)?.value?.slice(0, 8)} ${extra}`)
    // 文末另起一段，所有动作都在这段上做
    v.dispatch({ changes: { from: end(), insert: '\n\n' }, selection: { anchor: end() + 2 } })
    typeText(v, '加粗测试')
    v.dispatch({ selection: { anchor: end() - 4, head: end() } })
    key(v, 'b', { meta: true }, 66); say('⌘B')
    key(v, 'b', { meta: true }, 66); say('⌘B again')
    key(v, 'i', { meta: true }, 73); say('⌘I')
    key(v, 'i', { meta: true }, 73); say('⌘I again')
    key(v, 'k', { meta: true, shift: true }, 75); say('⇧⌘K')
    key(v, 'k', { meta: true }, 75); await wait(300); say('⌘K', `palette=${!!document.querySelector('.palette, .cmd-palette, [class*=palette]')}`)
    document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true, cancelable: true } as KeyboardEventInit)); await wait(300)
    say('Esc closes palette', `palette=${!!document.querySelector('.palette')}`)
    // 列表：Tab / ⇧Tab / Enter 续项 / 空项 Enter 退出
    v.dispatch({ changes: { from: end(), insert: '\n\n- 项目一' }, selection: { anchor: end() + 6 } })
    v.dispatch({ selection: { anchor: end() } })
    key(v, 'Enter', {}, 13); say('Enter after "- 项目一"')
    typeText(v, '项目二')
    key(v, 'Tab', {}, 9); say('Tab on "- 项目二"')
    key(v, 'Tab', { shift: true }, 9); say('⇧Tab')
    key(v, 'Enter', {}, 13); say('Enter after 项目二')
    key(v, 'Enter', {}, 13); say('Enter on empty item')
    v.dispatch({ changes: { from: end(), insert: '1. 第一' }, selection: { anchor: end() + 5 } })
    key(v, 'Enter', {}, 13); say('Enter after "1. 第一"')
    v.dispatch({ changes: { from: end(), insert: '\n\n- [ ] 待办' }, selection: { anchor: end() + 10 } })
    key(v, 'Enter', {}, 13); say('Enter after "- [ ] 待办"')
    key(v, 'Enter', {}, 13); say('Enter on empty task')
    // 标题 / 列表键
    v.dispatch({ changes: { from: end(), insert: '\n' }, selection: { anchor: end() + 1 } })
    typeText(v, '标题行')
    key(v, '1', { meta: true, alt: true }, 49); say('⌥⌘1')
    key(v, '8', { meta: true, shift: true }, 56); say('⇧⌘8')
    key(v, '8', { meta: true, shift: true }, 56); say('⇧⌘8 again')
    // ⌘↑ / ⌘↓
    key(v, 'ArrowUp', { meta: true }, 38); say('⌘↑')
    key(v, 'ArrowDown', { meta: true }, 40); say('⌘↓')
    // ⌘F / ⌘/ / ⌘S / ⇧⌘Z
    key(v, 'f', { meta: true }, 70); await wait(200); say('⌘F', `search=${!!document.querySelector('.cm-search')}`)
    key(v, 'Escape', {}, 27); await wait(100)
    key(v, '/', { meta: true }, 191); await wait(300); say('⌘/', `shortcuts=${!!Array.from(document.querySelectorAll('h2, h3, .dialog-title, [role=dialog]')).find((e) => e.textContent?.includes('快捷键'))}`)
    key(v, 'Escape', {}, 27); await wait(200)
    const before = end()
    key(v, 'z', { meta: true }, 90); say('⌘Z', `len ${before}→${end()}`)
    key(v, 'z', { meta: true, shift: true }, 90); say('⇧⌘Z', `len→${end()}`)
    key(v, 'd', { meta: true, shift: true }, 68); await wait(200); say('⇧⌘D (should be journal)', `title=${(document.querySelector('.note-title') as HTMLInputElement | null)?.value ?? '?'}`)
    log('p10 keys\n' + out.join('\n'))
    return true
  }

  if (what === 'undo') {
    const end = () => v.state.doc.length
    const out: string[] = []
    v.dispatch({ changes: { from: end(), insert: '\n\n' }, selection: { anchor: end() + 2 } })
    const base = end()
    // (a) 逐字打一句话（每字 60ms，像真打字），停 800ms 后 ⌘Z
    for (const ch of '这是一句连续打出来的话，中间没有停顿。') { typeText(v, ch); await wait(60) }
    await wait(800)
    key(v, 'z', { meta: true }, 90)
    out.push(`(a) typed 19 chars, ⌘Z removed ${base + 19 - end()} chars (doc ${base + 19}→${end()})`)
    key(v, 'z', { meta: true, shift: true }, 90)
    // (a2) 中间停顿 700ms 再打：⌘Z 只撤后半句
    for (const ch of '前半句') { typeText(v, ch); await wait(60) }
    await wait(700)
    for (const ch of '，后半句。') { typeText(v, ch); await wait(60) }
    await wait(800)
    const b2 = end()
    key(v, 'z', { meta: true }, 90)
    out.push(`(a2) pause 700ms mid-sentence: ⌘Z removed ${b2 - end()} chars (后半句 = 5)`)
    // (b) 续写（假模型流式；slowstream 模式四片各隔 900ms）→ 跑完 ⌘Z
    const tap = async (label: string) => {
      const b3 = end()
      v.dispatch({ selection: { anchor: end() } })
      const btn = Array.from(document.querySelectorAll<HTMLElement>('button, .fb-btn')).find((e) => (e.textContent ?? '').replace(/\s+/g, '') === '续写')
      btn?.click()
      for (let i = 0; i < 60; i++) { await wait(500); if (end() > b3 && !document.querySelector('.fb-btn.running, .fb-busy')) break }
      await wait(1500)
      out.push(`${label} 续写 button=${!!btn} inserted ${end() - b3} chars; diff-bar=${!!Array.from(document.querySelectorAll('span')).find((e) => /改了 \d+ 处/.test(e.textContent ?? ''))}`)
      return end() - b3
    }
    const ins1 = await tap('(b)')
    let b4 = end()
    key(v, 'z', { meta: true }, 90); await wait(200)
    out.push(`(b) ⌘Z after 续写 removed ${b4 - end()} of ${ins1} chars; tail=${tail(v, 60)}`)
    key(v, 'z', { meta: true }, 90); await wait(200)
    out.push(`(b) second ⌘Z removed ${b4 - end()} of ${ins1} so far`)
    key(v, 'z', { meta: true }, 90); await wait(200)
    out.push(`(b) third ⌘Z removed ${b4 - end()} of ${ins1} so far (more than ${ins1} = ate user text)`)
    while (end() < b4) { key(v, 'z', { meta: true, shift: true }, 90); await wait(100) }
    out.push(`(b) ⇧⌘Z back to ${end()} (=${b4})`)
    // (c) 「全部接受」之后再 ⌘Z：接受了的还能撤吗
    const ins2 = await tap('(c)')
    const acc = Array.from(document.querySelectorAll<HTMLElement>('button')).find((e) => e.textContent?.trim() === '全部接受')
    acc?.click(); await wait(400)
    b4 = end()
    key(v, 'z', { meta: true }, 90); await wait(200)
    out.push(`(c) 全部接受 button=${!!acc}; ⌘Z after accept removed ${b4 - end()} of ${ins2} chars`)
    log('p10 undo\n' + out.join('\n'))
    return true
  }

  if (what === 'paste') {
    const out: string[] = []
    const end = () => v.state.doc.length
    const paste = (data: Record<string, string>, files: File[] = []) => {
      const dt = new DataTransfer()
      for (const [t, s] of Object.entries(data)) dt.setData(t, s)
      for (const f of files) dt.items.add(f)
      const ev = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })
      v.contentDOM.dispatchEvent(ev)
    }
    const fresh = () => { v.dispatch({ changes: { from: end(), insert: '\n\n' }, selection: { anchor: end() + 2 } }); return end() }
    let b = fresh()
    paste({ 'text/html': '<meta charset="utf-8"><h2>季度目标</h2><p>这是 <strong>粗体</strong> 和 <em>斜体</em>，还有 <a href="https://example.com/x">一个链接</a>。</p><ul><li>第一条</li><li>第二条</li></ul><p>结尾一段</p>', 'text/plain': '季度目标\n这是 粗体 和 斜体，还有 一个链接。\n第一条\n第二条\n结尾一段' })
    await wait(300); out.push(`html → ${JSON.stringify(v.state.doc.sliceString(b))}`)
    b = fresh()
    paste({ 'text/plain': '第一段。\n\n第二段。\n第二段第二行。' })
    await wait(300); out.push(`plain multi-para → ${JSON.stringify(v.state.doc.sliceString(b))}`)
    b = fresh()
    paste({ 'text/plain': '# 标题\n\n- 列表 **粗**\n\n[链](https://a.b)' })
    await wait(300); out.push(`markdown → ${JSON.stringify(v.state.doc.sliceString(b))}`)
    b = fresh()
    paste({ 'text/plain': 'https://example.com/page?a=1' })
    await wait(300); out.push(`url no selection → ${JSON.stringify(v.state.doc.sliceString(b))}`)
    b = fresh()
    typeText(v, '官网'); v.dispatch({ selection: { anchor: b, head: b + 2 } })
    paste({ 'text/plain': 'https://example.com/' })
    await wait(300); out.push(`url over selection「官网」 → ${JSON.stringify(v.state.doc.sliceString(b))}`)
    // VS Code 那种：text/html 是一堆 span 的代码，plain 才是要的
    b = fresh()
    paste({ 'text/html': '<meta charset="utf-8"><div style="color:silver;font-family:Menlo"><span style="color:steelblue">const</span> <span>x</span> = 1</div>', 'text/plain': 'const x = 1' })
    await wait(300); out.push(`code-editor html → ${JSON.stringify(v.state.doc.sliceString(b))}`)
    b = fresh()
    const c = document.createElement('canvas'); c.width = 4; c.height = 4
    const blob: Blob | null = await new Promise((r) => c.toBlob(r, 'image/png'))
    if (blob) paste({}, [new File([blob], 'shot.png', { type: 'image/png' })])
    await wait(2500); out.push(`image → ${JSON.stringify(v.state.doc.sliceString(b, Math.min(end(), b + 120)))} (len ${end() - b})`)
    log('p10 paste\n' + out.join('\n'))
    return true
  }

  if (what === 'ime') {
    const out: string[] = []
    const end = () => v.state.doc.length
    const hold = Number(rest[0] ?? 0)
    v.dispatch({ changes: { from: end(), insert: '\n\n' }, selection: { anchor: end() + 2 } })
    const b = end()
    typeText(v, '/')
    await wait(200)
    out.push(`after "/": slash-menu=${!!document.querySelector('.slash-menu')}`)
    // 模拟 IME：compositionstart → 直接往 CM 的文本节点里写拼音（这就是输入法做的事）→ compositionupdate
    const dom = v.contentDOM
    const range = document.getSelection()?.getRangeAt(0)
    let node = range?.startContainer as Node | null
    if (node && node.nodeType !== Node.TEXT_NODE) { node = node.childNodes[Math.max(0, (range?.startOffset ?? 1) - 1)] ?? node }
    out.push(`caret node=${node?.nodeType === Node.TEXT_NODE ? 'text:' + JSON.stringify((node as Text).data) : node?.nodeName}`)
    dom.dispatchEvent(new CompositionEvent('compositionstart', { data: '', bubbles: true }))
    const tn = node?.nodeType === Node.TEXT_NODE ? (node as Text) : null
    if (tn) {
      const base = tn.data
      for (const p of ['b', 'bi', 'bia', 'biao']) {
        tn.data = base + p
        document.getSelection()?.collapse(tn, tn.data.length)     // 输入法会把光标放到组字串末尾
        dom.dispatchEvent(new CompositionEvent('compositionupdate', { data: p, bubbles: true }))
        await wait(80)
      }
    } else {
      // 光标在空行上（没有文本节点）：直接插一个
      const t = document.createTextNode('biao'); range?.insertNode(t)
      dom.dispatchEvent(new CompositionEvent('compositionupdate', { data: 'biao', bubbles: true }))
      await wait(80)
    }
    await wait(150)
    out.push(`composing=${v.composing} doc tail=${tail(v, 12)} head=${v.state.selection.main.head}/${end()} slash-field=${JSON.stringify(v.state.field(slashField))} slash-menu=${!!document.querySelector('.slash-menu')} query-items=${document.querySelectorAll('.slash-item').length}`)
    // 组字中按 Enter：输入法的 Enter 是「上屏」，不该被 `/` 菜单当成确认
    const prevented = key(v, 'Enter', {}, 13)
    await wait(150)
    out.push(`Enter during composition: prevented=${prevented} doc tail=${tail(v, 12)} slash-menu=${!!document.querySelector('.slash-menu')} doc-len-delta=${end() - b}`)
    if (hold) {
      // 组字挂着不动 hold ms：这期间圆点重算（1.5s）、右栏关系查询（0.9s）都会跑——看会不会把组字打断
      await wait(hold)
      out.push(`after holding ${hold}ms: composing=${v.composing} dots=${document.querySelectorAll('.mm-dot').length} tail=${tail(v, 12)}`)
    }
    // 上屏：输入法把 "biao" 换成 "表格" 然后 compositionend
    const sel = document.getSelection()
    const node2 = sel?.anchorNode
    if (node2 && node2.nodeType === Node.TEXT_NODE) {
      (node2 as Text).data = (node2 as Text).data.replace(/biao$/, '表格')
      document.getSelection()?.collapse(node2, (node2 as Text).data.length)
    }
    dom.dispatchEvent(new CompositionEvent('compositionend', { data: '表格', bubbles: true }))
    await wait(300)
    out.push(`after commit: composing=${v.composing} doc tail=${tail(v, 12)} slash-field=${JSON.stringify(v.state.field(slashField))} slash-menu=${!!document.querySelector('.slash-menu')} items=${Array.from(document.querySelectorAll('.slash-label')).map((e) => e.textContent).join('|')}`)
    // 再来一遍 `[[` 补全：组字中不该弹，上屏后要弹
    v.dispatch({ changes: { from: end(), insert: '\n' }, selection: { anchor: end() + 1 } })
    typeText(v, '[[')
    await wait(400)
    out.push(`after "[[": tooltip=${!!document.querySelector('.cm-tooltip-autocomplete')} options=${document.querySelectorAll('.cm-tooltip-autocomplete li').length}`)
    log('p10 ime\n' + out.join('\n'))
    return true
  }

  if (what === 'perf') {
    const out: string[] = []
    const doc = v.state.doc
    out.push(`doc ${doc.length} chars / ${doc.lines} lines; window ${window.innerWidth}x${window.innerHeight}`)
    const dots = () => document.querySelectorAll('.cm-memory-gutter .mm-dot').length
    const batchStat = (since: number) => { const c = calls.filter((x) => x.at >= since); const done = c.filter((x) => x.ms >= 0); return `batch calls=${c.length} (in-flight ${c.length - done.length}) first-sent=+${c.length ? ((c[0].at - since) / 1000).toFixed(1) : '-'}s last-done=+${done.length ? ((Math.max(...done.map((x) => x.at + x.ms)) - since) / 1000).toFixed(1) : '-'}s sizes=${c.map((x) => x.ms.toFixed(0)).join('/')}ms`
    }
    /** 从 since 起，等第一个点画出来 + 请求都回来（最多 maxMs） */
    const settle = async (since: number, maxMs: number) => {
      let firstDot = -1
      for (let i = 0; i < maxMs / 250; i++) {
        await wait(250)
        if (firstDot < 0 && dots() > 0) firstDot = performance.now() - since
        const c = calls.filter((x) => x.at >= since)
        if (firstDot >= 0 && c.length && c.every((x) => x.ms >= 0) && performance.now() - since > 2500) break
      }
      return `first dot +${firstDot < 0 ? 'never' : (firstDot / 1000).toFixed(1) + 's'} · ${batchStat(since)}`
    }
    // ① 打开这篇 → 圆点（首次，全量）
    out.push(`open → ${await settle(tOpen, 45000)}`)
    // ② 光标放到正文中段，逐字打 40 个字（每字 40ms 间隔，像真打字），量输入延迟
    const at = Math.floor(doc.length * 0.5)
    const l = doc.lineAt(at)
    v.dispatch({ selection: { anchor: l.to }, effects: EditorView.scrollIntoView(l.to, { y: 'center' }) })
    await wait(800)
    let longSum = 0; let longN = 0; let longMax = 0
    const po = new PerformanceObserver((list) => { for (const e of list.getEntries()) { longSum += e.duration; longN++; longMax = Math.max(longMax, e.duration) } })
    try { po.observe({ entryTypes: ['longtask'] }) } catch { out.push('no longtask observer') }
    const sync: number[] = []; const frame: number[] = []
    const text = '这一句是探针逐字打进去量延迟用的，一共四十个字左右，打完再看圆点重算要多久才画出来啦。'
    const t0 = performance.now()
    for (const ch of text.slice(0, 40)) {
      const a = performance.now()
      typeText(v, ch)
      const b = performance.now()
      await new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())))
      const c = performance.now()
      sync.push(b - a); frame.push(c - a)
      await wait(40)
    }
    const typedMs = performance.now() - t0
    po.disconnect()
    const stat = (xs: number[]) => { const s = [...xs].sort((x, y) => x - y); return `p50=${s[Math.floor(s.length / 2)].toFixed(1)} p90=${s[Math.floor(s.length * 0.9)].toFixed(1)} max=${s[s.length - 1].toFixed(1)}` }
    out.push(`40 keystrokes in ${typedMs.toFixed(0)}ms: dispatch-sync ${stat(sync)} · to-2nd-frame ${stat(frame)} · longtasks n=${longN} sum=${longSum.toFixed(0)} max=${longMax.toFixed(0)}`)
    // ③ 停手 → 圆点重算（改了一段）
    const tStop = performance.now()
    out.push(`after 40 keystrokes (one paragraph changed) → ${await settle(tStop, 45000)}`)
    // ④ 再打 1 个字 → 圆点重算
    const t2 = performance.now()
    typeText(v, '。')
    out.push(`after 1 more keystroke → ${await settle(t2, 45000)}`)
    // 滚动：从顶滚到底分 20 步，量每步到下一帧
    const scroller = document.querySelector('.note-scroll') as HTMLElement | null
    if (scroller) {
      const fr: number[] = []
      scroller.scrollTop = 0; await wait(300)
      for (let i = 1; i <= 20; i++) {
        const a = performance.now()
        scroller.scrollTop = (scroller.scrollHeight - scroller.clientHeight) * i / 20
        await new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())))
        fr.push(performance.now() - a)
        await wait(30)
      }
      out.push(`scroll 20 steps to-2nd-frame ${stat(fr)}`)
    }
    log('p10 perf\n' + out.join('\n'))
    return true
  }
  log(`p10: unknown ${what}`)
  return true
}
