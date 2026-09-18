/**
 * 探针：`?probe=xxx` 把界面驱动到某个状态，供截图核对。
 *
 * **为什么要这个**：右键菜单、弹层、分屏这些东西只有在交互之后才存在，而截图工具
 * 没法替我点——发合成点击要系统的「辅助访问」权限，那是得让仓库主人去系统设置里
 * 授权的东西，不该为了自测要求他改系统权限。
 *
 * 只认 URL 参数，不留任何常驻入口：正常使用时这段代码一次都不会执行。从 App.tsx
 * 搬出来是因为它长到了三百行——测试用的代码不该跟产品代码挤在一个文件里。
 * ctx 就是 App 里那些闭包（函数和 setState），探针要什么就从里面拿。
 */
import { EditorView } from '@codemirror/view'
import { toastAction } from './toast'
import { writeDraft } from './util/draft'
import { layersOf, turnLayerOff } from './editor/roundDiff'
import * as api from './api'
import { SLASH_ITEMS } from './editor/slashMenu'
import type { SelectionAction } from './components/SelectionMenu'
import type { Note, TreeRow } from './api'
import { runP10 } from './probesP10'

export type ProbeCtx = Record<string, any>

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
const ranOnce = new Set<string>()

export function runProbe(probe: string, ctx: ProbeCtx): void {
  /* 用 `;;` 串起来就是「先跑这个再跑那个」：`open:kb;;rect:.kb-search`。
     （`|` 已经被 `openclick:` 占了，别复用。）
     有了它，量一个**要先导航才存在**的元素不用再为每种组合新写一个探针。 */
  if (probe?.includes(';;')) { for (const one of probe.split(';;')) runProbe(one, ctx); return }
  // P10：编辑器基本功五条（快捷键 / 撤销 / 粘贴 / 输入法 / 长文性能），代码在 probesP10.ts
  if (probe?.startsWith('p10:')) { void runP10(probe, ctx as ProbeCtx & { notes: Note[] }); return }
  // 记忆范围存在 localStorage，上一次探针（digest:30:notes）切的会留给下一次——
  // 除非这次探针自己指定了范围，否则先复位到「全部记忆」（第 188 轮实拍右栏莫名「只看笔记」）
  const { notes, tree, switchTo, openVirtual, openInSplit, newNote, removeWithSubtree, remove, syncTab, formatNote, setSelectionMenu, setPaneFocus, setContent, setTreeMenu, setTabs, setTabMenu, setShowShortcuts, setReviewEachRound, setQuick, setNoteQuery, setFocusMode, editorViewRef, actionsRef, harnessProbeDone, moveNodeTo, setLoading, setNoteHarnessStatus } = ctx as ProbeCtx & { notes: Note[]; tree: TreeRow[] }
  if (!harnessProbeDone.current && !/:(notes|meetings|imports)(:|$)/.test(probe) && api.memoryScope() !== 'all') api.setMemoryScope('all')
  /* `rect:<CSS 选择器>`：把匹配到的元素的几何和几条关键计算样式打进
     `[client:info]` 日志。**这条不是为了截图，是为了量。**
     对着截图反推「这条边线到底是谁画的」会推错——第 702 轮我在知识库搜索框上
     推了四五轮才发现该直接问 DOM。选择器里的逗号要用 `~` 代替（URL 参数）。 */
  if (probe?.startsWith('rect:')) {
    const sel = decodeURIComponent(probe.slice(5)).replace(/~/g, ',')
    setTimeout(() => {
      const out: string[] = []
      document.querySelectorAll(sel).forEach((el, k) => {
        const r = el.getBoundingClientRect()
        const c = getComputedStyle(el)
        const keys = ['height', 'padding', 'border', 'borderRadius', 'background', 'backgroundColor', 'boxSizing', 'flex', 'width', 'overflow', 'position'] as const
        out.push(`[${k}] <${el.tagName.toLowerCase()}.${(el.className || '').toString().split(' ').join('.')}> `
          + `x=${r.x.toFixed(1)} y=${r.y.toFixed(1)} w=${r.width.toFixed(1)} h=${r.height.toFixed(1)} | `
          + keys.map((q) => `${q}=${(c as any)[q]}`).join(' ; '))
      })
      void api.clientLog('info', 'rect ' + sel + '\n' + (out.join('\n') || '（没匹配到）'))
    }, 4000)
  }
  if (probe === 'tabs' && notes.length >= 3) {
    // 连开三篇，看标签行铺开的样子
    void (async () => {
      for (const n of notes.slice(0, 3)) { await switchTo(n) }
    })()
    return
  }
  // 打开一条不存在的事实，点「收掉这个标签」：标签应该没了、切到旁边那个
  if (probe === 'badfact:close') {
    setTimeout(() => void openVirtual('kb:fact:terrence-9999-FFF', '事实 terrence-9999-FFF'), 800)
    setTimeout(() => { const b = Array.from(document.querySelectorAll('.kb-note .chip-action')).find((x) => x.textContent?.includes('收掉')) as HTMLElement | undefined; b?.click() }, 3000)
    setTimeout(() => void api.clientLog('warn', `badfact:close tabs=${Array.from(document.querySelectorAll('.note-tab-title'), (el) => el.textContent?.slice(0, 8)).filter((t) => t?.includes('9999')).length} status=${document.querySelector('.statusbar, .status-bar')?.textContent?.slice(0, 30) ?? '?'}`, '', 'probe'), 4000)
    return
  }
  // 应用菜单「标签 › …」走的那条事件：tabaction:<close|reopen|next|prev|list|close-others>
  if (probe?.startsWith('tabaction:')) {
    const a = probe.slice(10)
    setTimeout(() => window.dispatchEvent(new CustomEvent('tab-action', { detail: a })), 2500)
    setTimeout(() => void api.clientLog('warn', `tabaction:${a} active=${document.querySelector('.note-tab.active .note-tab-title')?.textContent?.slice(0, 8) ?? '?'} menu=${!!document.querySelector('.context-menu')}`, '', 'probe'), 3500)
    return
  }
  // 键盘走可点的 div：事实表第一条 .fact-text 聚焦后按 Enter，应该打开那条事实
  if (probe === 'factkeys' || probe === 'factkeys:focus') {
    setTimeout(() => void openVirtual('kb:facts', '事实表'), 800)
    // :focus → 只聚焦不按 Enter，看焦点环
    setTimeout(() => { const el = document.querySelector('.fact-text') as HTMLElement | null; el?.focus(); if (probe === 'factkeys') el?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })) }, 4000)
    setTimeout(() => void api.clientLog('warn', `factkeys active=${document.querySelector('.note-tab.active .note-tab-title')?.textContent?.slice(0, 12) ?? '?'}`, '', 'probe'), 5500)
    return
  }
  // 带动作的 toast（删除后的「撤销」那种）：看按钮长得像不像链接、Tab 能不能走到
  if (probe === 'toast:action') {
    setTimeout(() => toastAction('已删除「样例」（30 天内可在「最近删除」找回）', '撤销', () => {}), 1500)
    setTimeout(() => (document.querySelector('.toast button') as HTMLElement | null)?.focus(), 2200)
    return
  }
  // mermaid:<noteId> → 打开这篇，把第一个 ```mermaid 块滚进视野（CM6 只渲染视口附近的 widget），6.5 秒后报渲染状态
  if (probe?.startsWith('mermaid:')) {
    const id = probe.slice(8)
    setTimeout(() => { const n = notes.find((x) => x.id === id); if (n) void switchTo(n) }, 900)
    setTimeout(() => { const v = editorViewRef.current; if (!v) return; const at = v.state.doc.toString().indexOf('```mermaid'); if (at >= 0) v.dispatch({ effects: EditorView.scrollIntoView(at + 200, { y: 'center' }) }) }, 3000)
    setTimeout(() => { const ws = document.querySelectorAll('.cm-mermaid-widget'); void api.clientLog('warn', `mermaid widgets=${ws.length} svg=${Array.from(ws).filter((w) => w.querySelector('svg')).length} error=${document.querySelectorAll('.cm-mermaid-error').length}`, '', 'probe') }, 6500)
    return
  }
  // kbsearch:<q> → 知识库首页的搜索框打字，看命中词 / 结果（第 541 轮：命中词只在这里显示）
  if (probe?.startsWith('kbsearch:')) {
    const q = decodeURIComponent(probe.slice(9))
    setTimeout(() => void openVirtual('kb', '知识库'), 800)
    setTimeout(() => {
      const input = document.querySelector('.kb-page input, .kb-dashboard input, input[placeholder^="搜知识库"]') as HTMLInputElement | null
      if (!input) { void api.clientLog('warn', 'kbsearch: input not found', '', 'probe'); return }
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      setter?.call(input, q); input.dispatchEvent(new Event('input', { bubbles: true }))
    }, 3000)
    return
  }
  // 重启之后（探针 return-spot:reload 会 location.reload 一次）：上次看的那篇和位置还在不在
  if (probe === 'return-spot:reload' && notes.length >= 2) {
    let did = false
    try { did = sessionStorage.getItem('spot-reloaded') === '1' } catch { /* 无所谓 */ }
    if (did) {
      setTimeout(() => {
        const w = editorViewRef.current
        const scroller = document.querySelector('.note-scroll') as HTMLElement | null
        void api.clientLog('warn', `return-spot:reload 之后 光标 ${w?.state.selection.main.head ?? -1} · scrollTop ${Math.round(scroller?.scrollTop ?? -1)} · 文档 ${w?.state.doc.length ?? -1}`, '', 'probe')
      }, 3000)
      return
    }
    try { sessionStorage.setItem('spot-reloaded', '1') } catch { /* 无所谓 */ }
  }
  // 痛点 12：查完一篇旧笔记回来，光标和滚动位置还在不在原处
  if ((probe === 'return-spot' || probe === 'return-spot:kb' || probe === 'return-spot:reload') && notes.length >= 2) {
    const [a, b] = notes
    void (async () => {
      // 每一步都走 window 事件，不用 ctx 里那份闭包：ctx 是 runProbe 那一刻的快照，
      // 多步切换时里面的 current 早就过时了（第一版这么写，切回来编辑器还停在第二篇）
      const open = (id: string) => window.dispatchEvent(new CustomEvent('open-note', { detail: id }))
      open(a.id)
      await wait(1200)
      const v = editorViewRef.current
      if (!v) return
      const at = Math.floor(v.state.doc.length * 0.7)
      v.focus()
      v.dispatch({ selection: { anchor: at }, effects: EditorView.scrollIntoView(at, { y: 'center' }) })
      await wait(800)
      const scroller = () => document.querySelector('.note-scroll') as HTMLElement | null
      const leftScroll = Math.round(scroller()?.scrollTop ?? -1)
      // 走一趟知识库再回来（第 588 轮：openVirtual 那条路原来不记位置）
      if (probe === 'return-spot:kb') window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb' }))
      else if (probe === 'return-spot:reload') { await wait(300); location.reload(); return }
      else open(b.id)
      await wait(1500)
      open(a.id)
      await wait(1500)
      const w = editorViewRef.current
      if (!w) return
      void api.clientLog('warn',
        `return-spot 光标 期望 ${at} / 实际 ${w.state.selection.main.head} · scrollTop 走时 ${leftScroll} / 回来 ${Math.round(scroller()?.scrollTop ?? -1)} · 文档 ${w.state.doc.length}`,
        '', 'probe')
    })()
    return
  }
  // 标签装不下时右边的 ▾：列出全部标签
  if (probe === 'tabs:list' || probe === 'tabs:list:keys') {
    setTimeout(() => (document.querySelector('.tab-list') as HTMLElement | null)?.click(), 2500)
    // :keys → 按 40 下 ↓，高亮应该滚到列表下半截还看得见
    // 一个 tick 里连发 40 下没用：菜单的 keydown 闭包里 hi 还是同一个值，得隔开发
    if (probe.endsWith(':keys')) setTimeout(() => { let n = 0; const t = setInterval(() => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })); if (++n >= 40) clearInterval(t) }, 30) }, 3500)
    return
  }
  // 连开三篇，关掉中间那个，再 ⌘⇧T 找回来：应该回到原位（第 2 个），不是追加到最右
  if (probe === 'tabs:reopen' && notes.length >= 3) {
    void (async () => {
      for (const n of notes.slice(0, 3)) { await switchTo(n) }
      const titles = () => Array.from(document.querySelectorAll('.note-tab-title'), (el) => el.textContent?.slice(0, 6)).join(' | ')
      // 关的是第 2 个标签：中键（onAuxClick）不挑是不是当前标签、× 有没有渲染
      setTimeout(() => { void api.clientLog('warn', `tabs before: ${titles()}`, '', 'probe')
        document.querySelectorAll('.note-tab')[1]?.dispatchEvent(new MouseEvent('auxclick', { button: 1, bubbles: true })) }, 2500)
      setTimeout(() => { void api.clientLog('warn', `tabs closed: ${titles()}`, '', 'probe')
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'T', metaKey: true, shiftKey: true, bubbles: true })) }, 4000)
      setTimeout(() => void api.clientLog('warn', `tabs reopened: ${titles()}`, '', 'probe'), 5500)
    })()
    return
  }
  if (probe === 'kb-tab') {
    // 一条真、一条假（FFF 是合法十六进制，正则认得）——看「找不到」的红提示
    setContent((c: string) => c + '\n\n据 [terrence-1872-5F8] 所述，另见 [terrence-9999-FFF]。\n')
  }
  if (probe === 'kb-graph' || probe === 'kb-overview') {
    setTimeout(() => void openVirtual('kb:' + probe.slice(3)), 800)
  }
  if (probe === 'settings' || probe === 'settings:bottom') setTimeout(() => void openVirtual('app:settings', '设置'), 600)
  // settings:bottom → 滚到设置页底部（用量账本 / 出处行在最下面）
  if (probe === 'settings:bottom') setTimeout(() => { for (const el of Array.from(document.querySelectorAll<HTMLElement>('.note-scroll, .embedded-panel, main'))) el.scrollTo(0, 1e6) }, 3000)
  if (probe === 'skills') setTimeout(() => void openVirtual('app:skills'), 600)
  // 外观三选一走 preload → 主进程 nativeTheme；点完再截图看有没有真的变色
  if (probe === 'theme-dark' || probe === 'theme-system') {
    setTimeout(() => void openVirtual('app:settings', '设置'), 600)
    setTimeout(() => (document.querySelector(probe === 'theme-dark' ? '.chip .bx-moon' : '.chip .bx-desktop')?.parentElement as HTMLElement | null)?.click(), 3000)
  }
  if (probe === 'import') setTimeout(() => void openVirtual('app:import', '导入'), 600)
  if (probe === 'conflicts') setTimeout(() => void openVirtual('kb', '知识库'), 600)
  if (probe === 'trash') setTimeout(() => void openVirtual('app:trash', '最近删除'), 600)
  if (probe === 'today' && !harnessProbeDone.current) { harnessProbeDone.current = true; setTimeout(() => window.dispatchEvent(new CustomEvent('open-today')), 800) }   // 这个 hook 每次 notes 变都跑，不挡会连点四次
  // 导回区块在导入页最底下：打开后滚到它
  if (probe === 'exportback') setTimeout(() => { void openVirtual('app:import', '导入'); setTimeout(() => document.querySelector('.export-back')?.scrollIntoView({ block: 'end' }), 1500) }, 600)
  if (probe?.startsWith('open:')) {
    setTimeout(() => void openVirtual(probe.slice(5)), 900)
    // 页里有 mermaid 块的话报一下渲染状态：按需加载 mermaid 之后（第 518 轮）得确认真的画出来了
    setTimeout(() => { const ws = document.querySelectorAll('.cm-mermaid-widget'); if (ws.length) void api.clientLog('warn', `mermaid widgets=${ws.length} svg=${Array.from(ws).filter((w) => w.querySelector('svg')).length} error=${document.querySelectorAll('.cm-mermaid-error').length}`, '', 'probe') }, 6000)
  }
  /* openclick:<虚拟页 id>|<选择器> → 打开一页，再去点里面某个东西，并把点的结果报出来。
     写这个是因为**「点不动」这件事只有真点一下才验得了**：空库示例那两条假事实靠
     `inert` 挡交互，而 jsdom 根本没实现 inert（属性读出来是 undefined）——单测只能
     断言属性在，行为得在真 Chromium 里看（第 673 轮）。 */
  if (probe?.startsWith('openclick:')) {
    const [id, sel] = probe.slice(10).split('|')
    setTimeout(() => void openVirtual(id), 900)
    setTimeout(() => {
      const el = document.querySelector(sel) as HTMLElement | null
      const before = document.querySelector(".status-crumbs")?.textContent ?? ''
      el?.focus()
      const focused = document.activeElement === el
      el?.click()
      setTimeout(() => void api.clientLog('warn', `openclick ${sel} found=${!!el} focusable=${focused} crumbs「${before}」→「${document.querySelector(".status-crumbs")?.textContent ?? ''}」`, '', 'probe'), 600)
    }, 3500)
  }
  // openend:<id> → 打开虚拟页并把正文滚到底（看页面尾部的小节 / 分页器）
  if (probe?.startsWith('openend:')) { setTimeout(() => void openVirtual(probe.slice(8)), 900); setTimeout(() => { const el = document.querySelector('.note-scroll'); if (el) el.scrollTop = el.scrollHeight }, 5000) }
  // note:<id>[:ribbon:<tab>] → 按 id 打开某篇真笔记（ribbon 标签由 App 的 defaultOpen 从 probe 串里读）
  /* `running:<noteId>` —— 把界面摆成「智能续写跑到一半」，**不真的跑**。
     第 767 轮加的：用户说跑的过程中那条状态横条挡着正文，我把它挪进了浮动按钮那一排，
     而当时**没有任何探针能摆出这个状态**（`tap:` 那个是真跑，要花钱还会写进笔记库），
     于是只能靠「`.floating-buttons` 是 height:0，结构上挡不着」这种推理交差——
     这个仓反复证明过推理不算数。状态就两个 useState，摆出来不需要任何网络。
     状态文案照抄实拍那一条（用户截图里是「第 9 轮：修订 3 处，续写中…」），
     长度要够长，才量得出「换个地方接着挡」有没有发生。 */
  if (probe?.startsWith('running:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.split(':')[1]) ?? notes[0]
    harnessProbeDone.current = true
    void (async () => {
      await switchTo(n)
      setTimeout(() => { setLoading('note-harness'); setNoteHarnessStatus('第 9 轮：修订 3 处，续写中…') }, 1200)
    })()
    return
  }
  if (probe?.startsWith('note:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.split(':')[1])
    if (n) {
      harnessProbeDone.current = true; void switchTo(n)
      // `…:ribbon:<tab>:end` → 把 ribbon 体滚到底（看面板末尾的东西，比如引用页最后的局部图）
      if (probe.endsWith(':end')) setTimeout(() => { const el = document.querySelector('.ribbon-body'); if (el) el.scrollTop = el.scrollHeight }, 5500)
      // `…:ribbon:cites:strip` → 文末塞一条指向不存在事实的引用（探针不落库），5 秒后点「清掉这些引用」
      // `…:ribbon:links:unlink` → 文末塞一条链到不存在笔记的链接（不落库），6 秒后点「改成纯文本」
      if (probe.endsWith(':unlink')) {
        // 编辑器可能 2.5 秒时还没挂上（end: 探针也是这么重试的）：没插进去就再试一次
        const ins = () => { const v = editorViewRef.current; if (v && !v.state.doc.toString().includes('note://000000000000')) v.dispatch({ changes: { from: v.state.doc.length, insert: '\n\n另见 [早就删掉的那篇](note://000000000000)。' } }) }
        setTimeout(ins, 2500); setTimeout(ins, 4000)
        setTimeout(() => { for (const b of Array.from(document.querySelectorAll('button'))) if (b.textContent?.trim() === '改成纯文本') { b.click(); break } }, 7000)
      }
      if (probe.endsWith(':strip')) {
        setTimeout(() => { const v = editorViewRef.current; if (v) v.dispatch({ changes: { from: v.state.doc.length, insert: '\n\n这句的依据早没了 [terrence-9999-FF]。' } }) }, 2500)
        setTimeout(() => { for (const b of Array.from(document.querySelectorAll('button'))) if (b.textContent?.trim() === '清掉这些引用') { b.click(); break } }, 6000)
      }
    }
  }
  // kbexpand:<id> → 打开某个知识库分类的页面（看它名下那一层长什么样）。
  // 第 619 轮之前这条是「把树展开到它」——知识库不在树里之后，下钻本来就在
  // 那一页里，探针跟着改成直接开页。`:end` 保留：滚到页底看 300 条之后的尾巴行。
  if (probe?.startsWith('kbexpand:') && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    const toEnd = probe.endsWith(':end')
    const id = toEnd ? probe.slice(9, -4) : probe.slice(9)
    setTimeout(() => void openVirtual(id), 900)
    if (toEnd) setTimeout(() => { const el = document.querySelector('.kb-page'); if (el) el.scrollTop = el.scrollHeight }, 4500)
  }
  if (probe === 'graph-zoom') {
    setTimeout(() => void openVirtual('kb:graph'), 900)
    // 布局稳定后模拟用户滚轮放大三档，之后如果图又缩回去 / 跳走，就是有人在抢
    setTimeout(() => {
      const svg = document.querySelector('.local-graph svg, .kb-browser svg') as SVGSVGElement | null
      if (!svg) return
      const r = svg.getBoundingClientRect()
      for (let i = 0; i < 3; i++) svg.dispatchEvent(new WheelEvent('wheel', { deltaY: -300, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, bubbles: true, cancelable: true }))
    }, 12000)
  }
  // P1（第 768 轮点名那六条）的探针。三条都是**真实操作的重放**，不是摆出来的状态：
  //   custom-empty:<id>     选一段 → 右键「自定义提示…」→ 什么都不写按 Enter
  //   slashpick:<key>:<id>  打开笔记（可以是空白）→ 打 `/` → 点菜单里那一项
  //   margin:<id>:memory    页边圆点算完 + 光标放到第一个含数字的段落 + 右栏切到「记忆」看图例和关系卡
  //   tap:<id>:scope=<s>    先把记忆范围切到 s 再续写（看「自由续写」那行现在说不说原因）
  if (probe?.startsWith('custom-empty:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(13))
    if (n) { harnessProbeDone.current = true; void (async () => {
      await switchTo(n)
      await wait(1500)
      const v = editorViewRef.current; if (!v) return
      // 选第一段正文（不是标题、够长）
      const text = v.state.doc.toString()
      let from = 0
      for (const line of text.split('\n')) { if (line.trim().length >= 12 && !line.startsWith('#') && !line.startsWith('```')) break; from += line.length + 1 }
      const to = Math.min(text.length, (text.indexOf('\n', from) < 0 ? text.length : text.indexOf('\n', from)))
      v.focus(); v.dispatch({ selection: { anchor: from, head: to }, effects: EditorView.scrollIntoView(from, { y: 'center' }) })
      await wait(300)
      const c = v.coordsAtPos(from)
      setSelectionMenu({ x: (c?.left ?? 400) + 40, y: (c?.bottom ?? 300) + 4, text: text.slice(from, to) })
      await wait(500)
      await actionsRef.current.handleSelectionAction('custom')
      await wait(800)
      const input = document.querySelector('input[aria-label="给 AI 的指令"]') as HTMLInputElement | null
      input?.focus()
      input?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }))
    })() }
    return
  }
  //   slashpick:<key>:<id>:<文字>  多一段：选中之后往输入框里打这段文字再按 Enter（看真跑的运行块日志，比如「技能」那一行）
  if (probe?.startsWith('slashpick:') && notes.length && !harnessProbeDone.current) {
    const [, key, id, typed] = probe.split(':')
    const n = notes.find((x) => x.id === id)
    const item = SLASH_ITEMS.find((x) => x.key === key)
    if (n && item) { harnessProbeDone.current = true; void (async () => {
      await switchTo(n)
      await wait(1500)
      const v = editorViewRef.current; if (!v) return
      let end = v.state.doc.length
      v.focus()
      // 空行和 `/` 分两次：`slashTypedAt` 只认「这一次改动插入的正好是一个 /」
      if (end) { v.dispatch({ changes: { from: end, insert: '\n\n' }, selection: { anchor: end + 2 }, userEvent: 'input.type' }); end += 2 }
      v.dispatch({ changes: { from: end, insert: '/' }, selection: { anchor: end + 1 }, userEvent: 'input.type' })
      await wait(600)
      const row = Array.from(document.querySelectorAll<HTMLElement>('.slash-item'))
        .find((r) => r.querySelector('.slash-label')?.textContent === item.label)
      row?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
      if (!typed) return
      await wait(600)
      const input = document.querySelector('input[aria-label="给 AI 的指令"]') as HTMLInputElement | null
      if (!input) return
      // 受控输入框：走原生 setter + input 事件，React 才认
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(input, decodeURIComponent(typed))
      input.dispatchEvent(new Event('input', { bubbles: true }))
      await wait(200)
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }))
      // 运行块默认折叠；等它跑起来把日志展开，「技能 / 查 / 阶段」那几行才看得见
      await wait(3500)
      document.querySelector('.cm-run-head')?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
      // 运行块在文末（`/` 打在那儿），把它滚进视口
      const v2 = editorViewRef.current
      if (v2) v2.dispatch({ effects: EditorView.scrollIntoView(v2.state.doc.length, { y: 'end', yMargin: 40 }) })
    })() }
    return
  }
  if (probe?.startsWith('tap:') && notes.length && !harnessProbeDone.current) {
    const [, id, opt] = probe.split(':')
    const n = notes.find((x) => x.id === id)
    if (n) { harnessProbeDone.current = true; void (async () => {
      if (opt?.startsWith('scope=')) api.setMemoryScope(opt.slice(6) as api.MemoryScope)
      await switchTo(n)
      // 光标放到正文中段（第二个二级标题之前），看「从光标处续写」是不是插在那
      setTimeout(() => {
        const v = editorViewRef.current
        if (v) { const t = v.state.doc.toString(); const i = t.indexOf('\n## ', t.indexOf('\n## ') + 1); v.focus(); v.dispatch({ selection: { anchor: i > 0 ? i : Math.floor(t.length / 2) } }) }
      }, 1200)
      // 跑完把正文滚回顶部：「引用知识库 / 自由续写」那一行在编辑器上方，续写会把视口滚到插入处
      setTimeout(() => void actionsRef.current.runMagicTap().then(() => { const el = document.querySelector('.note-scroll'); if (el) el.scrollTop = 0 }), 1500)
    })() }
  }
  // ---- P3（临界条件表 docs/edge-cases.md）：四种可用 `;;` 拼接的步骤 + 两种场景。
  //   netdown[:<ms>]          把 fetch 换成「后端没起来」：/api/* 一律 TypeError('Failed to fetch')
  //                            （/api/client-log 放行——日志还要靠它写）；ms = 几毫秒之后再换，好让笔记先打开
  //   click:<ms>:<选择器>      等 ms 毫秒点一下。选择器可以写 text=<文字>：在 button / [role=menuitem] /
  //                            .palette-item / .chip 里找文字相等（去空白）的那个
  //   toasts:<ms>              等 ms 毫秒把 toast / 红字 / 运行块 / 忙态写进日志——「静默什么都不发生」靠它证
  //   type:<ms>:<文字>          等 ms 毫秒往编辑器文末插一段（不落库）
  //   selact:<id>:<动作>       选第一段正文 → 右键菜单 → 点那一项（verify / rewrite / polish / expand / trace / custom）
  //   audiopick:<id>[:bad]     打开笔记 → `/` 插入音频 → 选一个合成的小 wav（bad = 选一个 .txt 冒充音频）
  // 这几种步骤没有 harnessProbeDone 挡着，而 App 的探针 effect 在 notes / tree 变时会重跑——
  // 每一步只跑一次（实拍：click 步骤被重跑，toast 出现两遍）。
  if (/^(netdown|click:|toasts:|type:)/.test(probe ?? '')) {
    if (ranOnce.has(probe)) return
    ranOnce.add(probe)
  }
  if (probe?.startsWith('netdown')) {
    const ms = Number(probe.split(':')[1] ?? 0)
    setTimeout(() => {
      const real = window.fetch.bind(window)
      window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
        // 拼出来写：test_api_contract 会把源码里每个 `/api/…` 字面量当成「前端调的端点」
        if (url.startsWith('/' + 'api/') && !url.startsWith('/' + 'api/client-log')) return Promise.reject(new TypeError('Failed to fetch'))
        return real(input, init)
      }) as typeof fetch
      void api.clientLog('warn', 'netdown: /api/* 从现在起全部 Failed to fetch', '', 'probe')
    }, ms)
    return
  }
  if (probe?.startsWith('click:')) {
    const [, ms, ...rest] = probe.split(':')
    const sel = decodeURIComponent(rest.join(':'))
    setTimeout(() => {
      const el = probeFind(sel)
      void api.clientLog('warn', `click ${sel} found=${!!el} disabled=${String((el as HTMLButtonElement | null)?.disabled ?? '-')}`, '', 'probe')
      el?.click()
    }, Number(ms))
    return
  }
  if (probe?.startsWith('toasts:')) {
    setTimeout(() => {
      const texts = (q: string) => Array.from(document.querySelectorAll(q)).map((t) => (t.textContent ?? '').trim().slice(0, 160)).filter(Boolean)
      void api.clientLog('warn', `toasts=${JSON.stringify(texts('.toaster .toast'))} alerts=${JSON.stringify(texts('[role=alert]'))} runs=${JSON.stringify(texts('.cm-run-head'))} runlog=${JSON.stringify(texts('.cm-run-log'))} busy=${JSON.stringify(texts('.fb-busy, .fb-btn.running, .fb-btn[disabled], .palette .spinner'))} chars=${document.querySelector('.note-scroll .cm-content') ? EditorView.findFromDOM(document.querySelector('.note-scroll .cm-content') as HTMLElement)?.state.doc.length : '-'}`, '', 'probe')
    }, Number(probe.slice(7)))
    return
  }
  if (probe?.startsWith('type:')) {
    const [, ms, ...rest] = probe.split(':')
    setTimeout(() => {
      const el = document.querySelector('.note-scroll .cm-content')
      const v = el && EditorView.findFromDOM(el as HTMLElement)
      if (v) { const end = v.state.doc.length; v.dispatch({ changes: { from: end, insert: decodeURIComponent(rest.join(':')) }, selection: { anchor: end } }) }
    }, Number(ms))
    return
  }
  //   selact:new:<动作>        先新建一篇、写两段再选（给「无知识库」那一列：换个空库用户跑）
  //   mdpick[:netdown]         启动栏「导入」那张 Markdown 卡：选一个合成的 .md（netdown = 选之前先把后端「拔掉」）
  if (probe?.startsWith('mdpick') && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    void (async () => {
      await wait(500)
      if (probe.endsWith(':netdown')) runProbe('netdown', ctx)
      const file = new File([new TextEncoder().encode('# 导入测试\n\n这是一篇从 .md 导进来的笔记。')], 'imported.md', { type: 'text/markdown' })
      const dt = new DataTransfer(); dt.items.add(file)
      void api.clientLog('warn', 'mdpick start', '', 'probe')
      try { await actionsRef.current.importMarkdown(dt.files, 'root', false); void api.clientLog('warn', 'mdpick returned', '', 'probe') }
      catch (e) { void api.clientLog('warn', `mdpick threw ${String(e)}`, '', 'probe') }
    })()
    return
  }
  if (probe?.startsWith('selact:') && (notes.length || probe.startsWith('selact:new:')) && !harnessProbeDone.current) {
    const [, id, action] = probe.split(':')
    const n = id === 'new' ? ({} as Note) : notes.find((x) => x.id === id)
    if (n) { harnessProbeDone.current = true; void (async () => {
      if (id === 'new') {
        await newNote(); await wait(1200)
        const el = document.querySelector('.note-scroll .cm-content'); const v0 = el && EditorView.findFromDOM(el as HTMLElement)
        if (v0) v0.dispatch({ changes: { from: 0, insert: '# 空库上的一篇\n\n今天跟供应商确认了 PCBA 样品的交期，4 月 10 日拿到手板之后再定下一步的测试安排。\n\n第二段是关于预算的：这一批的成本比上一批高了 12%。\n' } })
      } else await switchTo(n)
      await wait(1500)
      const v = editorViewRef.current; if (!v) return
      const text = v.state.doc.toString()
      let from = 0
      for (const line of text.split('\n')) { if (line.trim().length >= 12 && !line.startsWith('#') && !line.startsWith('```')) break; from += line.length + 1 }
      const to = Math.min(text.length, (text.indexOf('\n', from) < 0 ? text.length : text.indexOf('\n', from)))
      v.focus(); v.dispatch({ selection: { anchor: from, head: to }, effects: EditorView.scrollIntoView(from, { y: 'center' }) })
      await wait(300)
      const c = v.coordsAtPos(from)
      setSelectionMenu({ x: (c?.left ?? 400) + 40, y: (c?.bottom ?? 300) + 4, text: text.slice(from, to) })
      await wait(500)
      void api.clientLog('warn', `selact ${action} start chars=${text.length}`, '', 'probe')
      await actionsRef.current.handleSelectionAction(action as SelectionAction)
      void api.clientLog('warn', `selact ${action} returned chars=${editorViewRef.current?.state.doc.length ?? '-'}`, '', 'probe')
    })() }
    return
  }
  if (probe?.startsWith('audiopick:') && notes.length && !harnessProbeDone.current) {
    const [, id, bad] = probe.split(':')
    const n = notes.find((x) => x.id === id)
    const item = SLASH_ITEMS.find((x) => x.key === 'audio')
    if (n && item) { harnessProbeDone.current = true; void (async () => {
      await switchTo(n)
      await wait(1500)
      const v = editorViewRef.current; if (!v) return
      const end = v.state.doc.length
      v.focus(); v.dispatch({ changes: { from: end, insert: '\n\n' }, selection: { anchor: end + 2 } })
      ctx.setSlash({ item, from: end + 2, to: end + 2, x: 300, y: 300 })
      await wait(300)
      // 0.2 秒的 8kHz 静音 wav：够小，真语音服务也认
      const wav = () => { const n = 1600; const b = new ArrayBuffer(44 + n); const d = new DataView(b); const w = (o: number, s: string) => { for (let i = 0; i < s.length; i++) d.setUint8(o + i, s.charCodeAt(i)) }
        w(0, 'RIFF'); d.setUint32(4, 36 + n, true); w(8, 'WAVE'); w(12, 'fmt '); d.setUint32(16, 16, true); d.setUint16(20, 1, true); d.setUint16(22, 1, true); d.setUint32(24, 8000, true); d.setUint32(28, 8000, true); d.setUint16(32, 1, true); d.setUint16(34, 8, true); w(36, 'data'); d.setUint32(40, n, true); return b }
      const file = bad ? new File([new TextEncoder().encode('这不是音频')], 'notes.txt', { type: 'text/plain' }) : new File([wav()], 'probe.wav', { type: 'audio/wav' })
      const dt = new DataTransfer(); dt.items.add(file)
      void api.clientLog('warn', `audiopick ${bad ? 'bad' : 'wav'} chars=${v.state.doc.length}`, '', 'probe')
      await actionsRef.current.onPickFile(dt.files)
      void api.clientLog('warn', `audiopick returned chars=${editorViewRef.current?.state.doc.length ?? '-'}`, '', 'probe')
      // 占位块在文末，CM 只渲染视口内的东西——滚到底，截图和 toasts 步骤才看得见它
      const v2 = editorViewRef.current
      if (v2) v2.dispatch({ effects: EditorView.scrollIntoView(v2.state.doc.length, { y: 'end', yMargin: 40 }) })
    })() }
    return
  }
  // 写作流三件：`/` 菜单、`@` 引用补全、右栏各标签
  // `slash:<词>` = 打完 `/` 再打一个过滤词，看筛选之后的菜单（第 705 轮加排版组时要看）
  if ((probe === 'slash' || probe?.startsWith('slash:') || probe === 'mention' || probe === 'wikilink') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => (x.content ?? '').length > 80)
    if (n) { harnessProbeDone.current = true; void (async () => {
      await switchTo(n)
      setTimeout(() => {
        const view = editorViewRef.current
        if (!view) return
        const end = view.state.doc.length
        view.focus()
        view.dispatch({ changes: { from: end, insert: '\n\n' }, selection: { anchor: end + 2 }, userEvent: 'input.type' })
        if (probe === 'wikilink') {
          view.dispatch({ changes: { from: end + 2, insert: '[[创业' }, selection: { anchor: end + 6 }, userEvent: 'input.type' })
        } else {
          view.dispatch({ changes: { from: end + 2, insert: probe.startsWith('slash') ? '/' : '@' }, selection: { anchor: end + 3 }, userEvent: 'input.type' })
          const q = probe === 'mention' ? '样机' : probe.startsWith('slash:') ? decodeURIComponent(probe.slice(6)) : ''
          if (q) view.dispatch({ changes: { from: end + 3, insert: q }, selection: { anchor: end + 3 + q.length }, userEvent: 'input.type' })
        }
        view.dispatch({ effects: EditorView.scrollIntoView(end + 3) })
        // mermaid / 表格预览晚一点才撑开高度，再滚一次
        setTimeout(() => editorViewRef.current?.dispatch({ effects: EditorView.scrollIntoView(editorViewRef.current.state.doc.length) }), 2500)
      }, 1500)
    })() }
  }
  if (probe?.startsWith('pane:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => (x.content ?? '').length > 80)
    if (n) { harnessProbeDone.current = true; void (async () => { await switchTo(n); setTimeout(() => setPaneFocus({ id: probe.slice(5), n: 1 }), 1200) })() }
  }
  if (probe?.startsWith('search:')) setTimeout(() => setNoteQuery(decodeURIComponent(probe.slice(7))), 900)
  // `export-one:<id>[:<where>[:<mode>]]` → 打开某篇 → 「⋯」→「导回到…」，验单篇导回那个入口（第 628 轮）。
  // P2-fix 加的两段：带 where（obsidian / notion / feishu）就切到那个去处；mode=bad 填一组错的凭证再点「写入」
  // （看失败提示长什么样），mode=badfolder 只把文件夹 token 填错（App ID / Secret 用桌面壳记着的那份），
  // mode=go 直接点「写入」（凭证由桌面壳记着的那份填好）——前后对比截图靠它。
  if (probe?.startsWith('export-one:') && notes.length && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    // 第四段：Obsidian 的 vault 路径（URL 编码），mode=go 时填进输入框——网页里没别的地方能拿到本机路径
    const [id, where, mode, extra] = probe.slice(11).split(':')
    const n = notes.find((x) => x.id === id) ?? notes[0]
    const setInput = (label: string, v: string) => {
      const el = document.querySelector(`.export-note input[aria-label="${label}"]`) as HTMLInputElement | null
      if (!el) { void api.clientLog('warn', `export-one: 没有输入框「${label}」`, '', 'probe'); return }
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(el, v)
      el.dispatchEvent(new Event('input', { bubbles: true }))
    }
    void (async () => {
      await switchTo(n)
      await wait(1200)
      const more = Array.from(document.querySelectorAll('.floating-buttons .fb-btn'))
        .find((x) => x.getAttribute('title') === '更多') as HTMLElement | undefined
      if (!more) { void api.clientLog('warn', 'export-one: 找不到「更多」', '', 'probe'); return }
      more.click()
      await wait(400)
      const item = Array.from(document.querySelectorAll('.context-menu button, .context-menu [role="menuitem"]'))
        .find((x) => (x.textContent ?? '').includes('导回到')) as HTMLElement | undefined
      if (!item) { void api.clientLog('warn', 'export-one: 「更多」里没有「导回到…」', '', 'probe'); return }
      item.click()
      await wait(900)
      if (where) {
        const label = { obsidian: 'Obsidian', notion: 'Notion', feishu: '飞书' }[where] ?? where
        const seg = Array.from(document.querySelectorAll('.export-note-seg button'))
          .find((x) => (x.textContent ?? '').trim().startsWith(label)) as HTMLElement | undefined
        seg?.click()
        await wait(400)
      }
      if (mode === 'bad' && where === 'notion') { setInput('Notion Integration token', 'ntn_bad'); setInput('Notion 父页面 id', 'deadbeefdeadbeefdeadbeefdeadbeef') }
      if (mode === 'bad' && where === 'feishu') { setInput('飞书 App ID', 'cli_wrong'); setInput('飞书 App Secret', 'wrong-secret'); setInput('飞书文件夹 token', 'fldcnNotARealToken') }
      if (mode === 'badfolder') setInput('飞书文件夹 token', 'fldcnNotARealToken')
      if (where === 'obsidian' && extra) setInput('Obsidian vault 文件夹路径', decodeURIComponent(extra))
      if (mode) {
        await wait(400)
        const go = document.querySelector('.export-note button.primary') as HTMLButtonElement | null
        if (!go || go.disabled) { void api.clientLog('warn', `export-one: 「写入」${go ? '是禁用的' : '不在'}`, '', 'probe'); return }
        go.click()
      }
    })()
  }
  // `reopen-right` → 点「展开右栏」那个小钮。验的是「明确的动作要赢过被动布局规则」：
  // 左栏拖宽之后右栏会被自动收掉，而按钮只改 rightOn（本来就是 true），点了等于没点
  // （用户实拍「右侧栏打不开了？」，第 625 轮）。
  if (probe === 'reopen-right') setTimeout(() => {
    const b = document.querySelector('.right-pane-reopen') as HTMLElement | null
    if (b) b.click()
    else void api.clientLog('warn', 'reopen-right: 右栏本来就开着 / 找不到那个钮', '', 'probe')
  }, 1200)
  // `recent` → 侧栏切到「按最近改动排」（第 622 轮）
  if (probe === 'recent') setTimeout(() => {
    const b = Array.from(document.querySelectorAll('.list-head .seg button'))
      .find((x) => (x.textContent ?? '').trim() === '最近') as HTMLElement | undefined
    if (b) b.click()
    else void api.clientLog('warn', 'recent: 侧栏没有「按最近」那个开关', '', 'probe')
  }, 1000)
  // `search-kb:<q>`：搜一个笔记里没有的词，再点「到知识库里搜」那条去处——
  // 验的是词有没有真的落进知识库的搜索框（第 616 轮）。
  if (probe?.startsWith('search-kb:')) {
    setTimeout(() => setNoteQuery(decodeURIComponent(probe.slice(10))), 900)
    setTimeout(() => {
      const link = Array.from(document.querySelectorAll('.left-pane-body a'))
        .find((a) => (a.textContent ?? '').includes('到知识库里搜')) as HTMLElement | undefined
      if (link) link.click()
      else void api.clientLog('warn', 'search-kb: 没找到「到知识库里搜」那条去处', '', 'probe')
    }, 2600)
  }
  if (probe === 'many-tabs' && notes.length >= 8 && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    void (async () => { for (const n of notes.slice(0, 10)) { syncTab(n); await switchTo(n) } })()
  }
  // 分段写作全程：没计划先生成一个，再对这棵子树跑
  if (probe?.startsWith('plan-run:') && tree.length && !harnessProbeDone.current) {
    const row = tree.find((r) => r.note_id === probe.slice(9))
    if (row) { harnessProbeDone.current = true; void (async () => {
      const got = await api.getWritingPlan(row.note_id)
      if (!got.plan) await api.startWritingPlan(row.note_id, '把创业一年的硬件、APP、市场三条线各写成一篇，每篇有据可依')
      setTimeout(() => void actionsRef.current.runHarness(row), 800)
    })() }
  }
  // 走真实路径：点标题行那个「无限续写」。左栏那个全局火箭第 621 轮砍掉了——
  // 同一个动作三个门，而它是错配最深的那个（工具栏没有上下文，这个动作需要上下文）。
  // 走真实路径：浮动按钮的「⋯」→「无限续写…」。第 625 轮起它不在标题行上常驻了。
  const clickPlanEntry = () => {
    const more = Array.from(document.querySelectorAll('.floating-buttons .fb-btn'))
      .find((x) => x.getAttribute('title') === '更多') as HTMLElement | undefined
    if (!more) { void api.clientLog('warn', 'plan-panel: 找不到「更多」按钮', '', 'probe'); return }
    more.click()
    setTimeout(() => {
      const item = Array.from(document.querySelectorAll('.context-menu button, .context-menu [role="menuitem"]'))
        .find((x) => (x.textContent ?? '').includes('无限续写')) as HTMLElement | undefined
      if (item) item.click()
      else void api.clientLog('warn', 'plan-panel: 「更多」里没有「无限续写」', '', 'probe')
    }, 400)
  }
  if (probe === 'plan-panel' && tree.length) setTimeout(clickPlanEntry, 1200)
  // 写作计划面板上点「换个目标」，看放弃计划的确认框（要那个文件夹上有计划）
  // `:abandon-esc` 再按一次 Esc——只该关掉确认框，面板留着；`plan-panel:esc` 只开面板然后 Esc——面板该关掉
  if ((probe === 'plan-panel:abandon' || probe === 'plan-panel:abandon-esc' || probe === 'plan-panel:esc') && tree.length && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    setTimeout(clickPlanEntry, 1200)
    const esc = () => {
      const target = document.activeElement ?? window
      const ev = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
      target.dispatchEvent(ev)
      setTimeout(() => void api.clientLog('warn', `esc → ${(target as HTMLElement).tagName ?? 'window'}.${(target as HTMLElement).className ?? ''} prevented=${ev.defaultPrevented} backdrops=${document.querySelectorAll('.palette-backdrop').length} active=${(document.activeElement as HTMLElement | null)?.textContent?.trim().slice(0, 12) ?? '?'}`, '', 'probe'), 300)
    }
    // 先 focus 再 click：真人鼠标点按钮会把焦点给它，程序 click() 不会——不 focus 的话「关掉后焦点回去」测的是面板容器
    if (probe !== 'plan-panel:esc') setTimeout(() => { for (const b of Array.from(document.querySelectorAll('button'))) if (b.textContent?.trim() === '换个目标') { b.focus(); b.click(); break } }, 5000)
    if (probe !== 'plan-panel:abandon') setTimeout(esc, 6500)
  }
  // 导入断点续跑：打开导入页，点「上次没跑完的导入」里的「继续」，看进度条 / 预估 / 用量
  if (probe === 'import-resume' && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    setTimeout(() => void openVirtual('app:import'), 600)
    setTimeout(() => {
      const btn = Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === '继续')
      if (btn) btn.click(); else void api.clientLog('warn', 'import-resume: no 继续 button', '', 'probe')
    }, 3000)
    // 进度卡在页面底部的「批量导入」一节，截图前滚到底
    for (const t of [2000, 4000, 11000, 30000]) setTimeout(() => { const sc = document.querySelector('.note-scroll'); if (sc) sc.scrollTop = sc.scrollHeight }, t)
  }
  // 边缘记忆：打开笔记，等页边圆点算出来
  // P9：`cursorline:<ms>:<行号>` 把光标放到第 N 行（右栏「记忆」按光标段查关系）
  if (probe?.startsWith('cursorline:')) {
    const [, ms, ln] = probe.split(':')
    setTimeout(() => {
      const v = editorViewRef.current; if (!v) return
      const line = v.state.doc.line(Math.min(Number(ln), v.state.doc.lines))
      v.focus(); v.dispatch({ selection: { anchor: line.from + 1 }, effects: EditorView.scrollIntoView(line.from, { y: 'center' }) })
      setPaneFocus({ id: 'memory', n: Date.now() })
    }, Number(ms))
    return
  }
  // P9：`mdown:<ms>:<选择器>` 发一次 mousedown（占位块的「停止」、`/` 菜单行这些只听 mousedown 的）
  if (probe?.startsWith('mdown:')) {
    const [, ms, ...rest] = probe.split(':')
    const sel = decodeURIComponent(rest.join(':'))
    setTimeout(() => {
      const el = document.querySelector(sel) as HTMLElement | null
      void api.clientLog('warn', `mdown ${sel} found=${!!el}`, '', 'probe')
      el?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
    }, Number(ms))
    return
  }
  // P9：`fill:<ms>:<选择器>:<文字>` 往任意输入框里填字（React 认的 input 事件）；`filefill:<ms>:<选择器>:<文件名>` 往 file 输入框里塞一个合成文件
  if (probe?.startsWith('fill:') || probe?.startsWith('filefill:')) {
    const isFile = probe.startsWith('filefill:')
    const [, ms, sel, ...rest] = probe.split(':')
    setTimeout(() => {
      const el = document.querySelector(decodeURIComponent(sel)) as HTMLInputElement | null
      void api.clientLog('warn', `${isFile ? 'filefill' : 'fill'} ${sel} found=${!!el}`, '', 'probe')
      if (!el) return
      if (isFile) {
        const name = decodeURIComponent(rest.join(':'))
        const dt = new DataTransfer(); dt.items.add(new File([new TextEncoder().encode('<?xml version="1.0"?><en-export></en-export>')], name, { type: 'application/octet-stream' }))
        el.files = dt.files
        el.dispatchEvent(new Event('change', { bubbles: true }))
      } else {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(el, decodeURIComponent(rest.join(':')))
        el.dispatchEvent(new Event('input', { bubbles: true }))
      }
    }, Number(ms))
    return
  }
  // P9：`mic` 把 getUserMedia 换成一条合成的静音音轨（不要麦克风权限），之后语音输入 / 录音钮就能走完整个流程
  if (probe === 'mic') {
    const ac = new AudioContext(); const dest = ac.createMediaStreamDestination()
    const osc = ac.createOscillator(); osc.connect(dest); osc.start()
    navigator.mediaDevices.getUserMedia = () => Promise.resolve(dest.stream)
    return
  }
  // P9：`imagepick:<id>` 打开笔记 → `/` 图片转表格 → 选一张合成的 png（看图模型慢 / 卡时占位块「停止」的行为）
  if (probe?.startsWith('imagepick:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(10))
    const item = SLASH_ITEMS.find((x) => x.key === 'table-image')
    if (n && item) { harnessProbeDone.current = true; void (async () => {
      await switchTo(n)
      await wait(1500)
      const v = editorViewRef.current; if (!v) return
      const end = v.state.doc.length
      v.focus(); v.dispatch({ changes: { from: end, insert: '\n\n' }, selection: { anchor: end + 2 } })
      ctx.setSlash({ item, from: end + 2, to: end + 2, x: 300, y: 300 })
      await wait(300)
      const cv = document.createElement('canvas'); cv.width = 64; cv.height = 32
      const g = cv.getContext('2d')!; g.fillStyle = '#fff'; g.fillRect(0, 0, 64, 32); g.fillStyle = '#000'; g.fillRect(8, 8, 48, 2)
      const blob: Blob = await new Promise((r) => cv.toBlob((b) => r(b!), 'image/png'))
      const dt = new DataTransfer(); dt.items.add(new File([blob], 'probe.png', { type: 'image/png' }))
      void api.clientLog('warn', `imagepick chars=${v.state.doc.length}`, '', 'probe')
      await actionsRef.current.onPickFile(dt.files)
      void api.clientLog('warn', `imagepick returned chars=${editorViewRef.current?.state.doc.length ?? '-'}`, '', 'probe')
      const v2 = editorViewRef.current
      if (v2) v2.dispatch({ effects: EditorView.scrollIntoView(v2.state.doc.length, { y: 'end', yMargin: 40 }) })
    })() }
    return
  }
  // P9：`tree-menu-leaf` 同 tree-menu，但挑一篇没有子节点的（「删除」不走确认框，直接乐观删）
  if (probe === 'tree-menu-leaf' && tree.length) {
    const row = tree.find((r) => r.child_count === 0 && r.parent_note_id === api.ROOT_ID && (r.title || '').length > 0) ?? tree.find((r) => r.child_count === 0) ?? tree[0]
    setTreeMenu({ row, at: { x: 260, y: 180 } })
    return
  }
  // P9：`title:<ms>:<文字>` 把标题输入框改成这段（走 React 认的 input 事件）——看「这篇要干什么」按标题预填
  if (probe?.startsWith('title:')) {
    const [, ms, ...rest] = probe.split(':')
    setTimeout(() => {
      const el = document.querySelector('.note-title') as HTMLInputElement | null
      if (!el) return
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      set?.call(el, decodeURIComponent(rest.join(':')))
      el.dispatchEvent(new Event('input', { bubbles: true }))
    }, Number(ms))
    return
  }
  // P9：`blank:margin:<文字>` 新建一篇、写进这段、光标停在段尾——看光标进了黄点 / 紫点的段时卡自己贴到行边上
  if (probe?.startsWith('blank:margin:') && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    setTimeout(() => void newNote(), 600)
    setTimeout(() => {
      const el = document.querySelector('.note-scroll .cm-content')
      const v = el && EditorView.findFromDOM(el as HTMLElement)
      if (!v) return
      const text = decodeURIComponent(probe.slice(13))
      v.focus()
      v.dispatch({ changes: { from: v.state.doc.length, insert: text }, selection: { anchor: v.state.doc.length + text.length } })
    }, 2500)
    return
  }
  if (probe?.startsWith('margin:') && notes.length && !harnessProbeDone.current) {
    const [, id, opt] = probe.split(':')
    const n = notes.find((x) => x.id === id)
    if (n) { harnessProbeDone.current = true; void (async () => {
      await switchTo(n)
      // P9：`margin:<id>:card[:<关系>]` 等页边圆点算出来，点第一个（或第一个该关系的）圆点——看贴在行边的关系卡
      if (opt === 'card') {
        const want = probe.split(':')[3]
        for (let i = 0; i < 60; i++) {
          await wait(500)
          const dot = document.querySelector(want ? `.cm-memory-gutter .mm-dot.mm-${want}` : '.cm-memory-gutter .mm-dot') as HTMLElement | null
          if (dot) { dot.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true })); void api.clientLog('warn', `margin card: clicked dot after ${(i + 1) * 0.5}s`, '', 'probe'); return }
        }
        void api.clientLog('warn', 'margin card: no dot in 30s', '', 'probe')
        return
      }
      if (opt !== 'memory') return
      await wait(1500)
      const v = editorViewRef.current; if (!v) return
      // 光标放到第一个含数字的段落（页边圆点判的正是这种段），右栏「记忆」就会查这段的关系
      const text = v.state.doc.toString()
      let at = 0
      for (const line of text.split('\n')) { if (/\d/.test(line) && !line.startsWith('#') && line.trim().length >= 8) break; at += line.length + 1 }
      v.focus(); v.dispatch({ selection: { anchor: Math.min(at + 2, text.length) }, effects: EditorView.scrollIntoView(at, { y: 'start', yMargin: 120 }) })
      setPaneFocus({ id: 'memory', n: Date.now() })
    })() }
  }
  // 改动分层：格式化一层 + 探针塞一行当第二层，看右栏「改动」的分层账本
  if (probe?.startsWith('layers:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(7))
    if (n) { harnessProbeDone.current = true; void switchTo(n).then(() => {
      setTimeout(() => formatNote(), 1200)
      setTimeout(() => {
        const v = editorViewRef.current; if (!v) return
        const before = v.state.doc.toString()
        // 插在第一行标题后面，不追加到文末：格式化的最后一处常贴着文末，追加的文字会按
        // 「末尾续写算这处一部分」并进那一层，关掉格式化就把它一起收了（第 151 轮实拍）
        const firstLineEnd = v.state.doc.line(1).to
        v.dispatch({ changes: { from: firstLineEnd, insert: '\n\n探针塞进来的一段：第二层提案。' } })
        const after = v.state.doc.toString()
        setContent(after)
        actionsRef.current.pushDiff('探针', before, after)
        setPaneFocus({ id: 'changes', n: 1 })
      }, 4000)                                   // 格式化大文要 2s 多；早了 setContent 会把探针那段冲掉
      // 第四步：把第一层（格式化）关掉——截图里应看到它的卡片变淡、正文回到格式化前
      setTimeout(() => {
        const v = editorViewRef.current; if (!v) return
        const first = layersOf(v)[0]
        if (first) turnLayerOff(v, first.id)
      }, 6000)
    }) }
  }
  // 记忆的关系：打开笔记，把光标放到含数字的最后一段上，看右栏「记忆」的关系卡
  if (probe?.startsWith('relations:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(10))
    if (n) { harnessProbeDone.current = true; void switchTo(n).then(() => setTimeout(() => {
      const v = editorViewRef.current; if (!v) return
      const text = v.state.doc.toString()
      const paras = text.split(/\n\s*\n/)
      let pos = text.length
      for (let i = paras.length - 1; i >= 0; i--) { if (/\d/.test(paras[i]) && !paras[i].startsWith('#')) { pos = text.indexOf(paras[i]) + 2; break } }
      v.dispatch({ selection: { anchor: Math.min(pos, text.length) }, effects: EditorView.scrollIntoView(pos, { y: 'center' }) })
      setPaneFocus({ id: 'memory', n: 1 })
    }, 1500)) }
  }
  // 笔记 ↔ 知识库：打开指定笔记的「引用」页（贡献的事实、过期标识、同步）
  if (probe?.startsWith('notekb:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(7))
    if (n) { harnessProbeDone.current = true; void switchTo(n) }
  }
  if (probe?.startsWith('ribbon:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => (x.content ?? '').length > 80)
    if (n) { harnessProbeDone.current = true; void switchTo(n) }
  }
  if (probe?.startsWith('big:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(4))
    if (n) { harnessProbeDone.current = true; const t0 = performance.now(); void switchTo(n).then(() => requestAnimationFrame(() => {
      void api.clientLog('warn', `big note ${n.content.length} 字 switchTo→paint ${Math.round(performance.now() - t0)} ms`, '', 'perf')
      // 打开之后再量三件用户真的会做的事：敲一个字、跳到文末、⌘F 找一个词（第 582 轮）
      setTimeout(() => {
        const v = editorViewRef.current; if (!v) return
        const len = v.state.doc.length
        const typeAt = Math.floor(len / 2)
        v.dispatch({ selection: { anchor: typeAt } })
        const t1 = performance.now()
        for (let k = 0; k < 20; k++) v.dispatch({ changes: { from: typeAt + k, insert: '字' }, userEvent: 'input.type' })
        const typed = performance.now() - t1
        const t2 = performance.now()
        v.dispatch({ effects: EditorView.scrollIntoView(len, { y: 'end' }) })
        requestAnimationFrame(() => {
          const jumped = performance.now() - t2
          void api.clientLog('warn', `big note 打 20 个字 ${Math.round(typed)} ms（每字 ${(typed / 20).toFixed(1)}）· 跳到文末 ${Math.round(jumped)} ms · 文档 ${len} 字`, '', 'perf')
        })
      }, 2500)
    })) }
  }

  if (probe?.startsWith('end:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(4))
    if (n) { harnessProbeDone.current = true; void switchTo(n).then(() => { for (const t of [3000, 6000, 8000]) setTimeout(() => { const v = editorViewRef.current; if (v) v.dispatch({ effects: EditorView.scrollIntoView(v.state.doc.length, { y: 'end' }) }) }, t); setTimeout(() => { const c = document.querySelector('.note-scroll'); if (c) c.scrollTop = c.scrollHeight }, 8500); setTimeout(() => document.querySelector('.cm-note-link')?.dispatchEvent(new MouseEvent('mouseenter')), 9000) }) }
  }
  // 删除：先分屏打开它，再从树上删，看树 / 标签 / 分屏有没有残留（5 秒后才真删）
  if (probe?.startsWith('delete:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(7))
    if (n) { harnessProbeDone.current = true; void (async () => {
      await switchTo(n)
      openInSplit(n.id)
      setTimeout(() => { const row = tree.find((r) => r.note_id === n.id); if (row) void removeWithSubtree(n, row); else remove(n) }, 1500)
    })() }
  }
  // 存入知识库：跑摄入任务，看树上的 ⇡ 和「最近摄入」有没有跟上
  if (probe?.startsWith('ingest:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(7))
    if (n) { harnessProbeDone.current = true; void (async () => { await switchTo(n); setTimeout(() => void actionsRef.current.ingestCurrentNote(), 1200) })() }
  }
  // `/` 块生成：在文末跑「用 AI 写」/「智能表格」等，看占位块 → 结果落下来
  if (probe?.startsWith('block:') && notes.length && !harnessProbeDone.current) {
    const [, key, noteId] = probe.split(':')
    const n = notes.find((x) => x.id === noteId)
    const item = SLASH_ITEMS.find((i) => i.key === key)
    if (n && item) { harnessProbeDone.current = true; void (async () => {
      await switchTo(n)
      setTimeout(() => {
        const v = editorViewRef.current
        if (!v) return
        const end = v.state.doc.length
        v.dispatch({ changes: { from: end, insert: '\n\n' }, selection: { anchor: end + 2 }, effects: EditorView.scrollIntoView(end + 2, { y: 'center' }) })
        void actionsRef.current.runBlock(item, end + 2, end + 2, key === 'prompt' ? '把上面几段总结成三条结论' : '')
      }, 1500)
    })() }
  }
  // 目录：打开右栏目录、把正文滚到中段，看当前所在的那一节有没有高亮
  if (probe?.startsWith('outline:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(8))
    if (n) { harnessProbeDone.current = true; void (async () => {
      await switchTo(n)
      setTimeout(() => setPaneFocus({ id: 'outline', n: 1 }), 800)
      setTimeout(() => { const sc = document.querySelector('.note-scroll'); if (sc) sc.scrollTop = sc.scrollHeight * 0.45 }, 2500)
    })() }
  }
  // 编辑器里按 ⌘[：应该回到上一篇，而不是缩进
  if (probe === 'keynav' && notes.length >= 2 && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    void (async () => {
      await switchTo(notes[1]); await switchTo(notes[0])
      setTimeout(() => {
        const v = editorViewRef.current; if (!v) return
        v.focus()
        v.contentDOM.dispatchEvent(new KeyboardEvent('keydown', { key: '[', code: 'BracketLeft', metaKey: true, bubbles: true, cancelable: true }))
      }, 1500)
    })()
  }
  // 编辑器里按 ⌘K：应该开搜索面板，而不是插一个链接
  if ((probe === 'keypalette' || probe === 'keypalette:esc') && notes.length && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    // `:esc` → 开了再 Esc 关掉，看焦点是不是回到编辑器
    if (probe === 'keypalette:esc') {
      setTimeout(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })), 3000)
      setTimeout(() => void api.clientLog('warn', `keypalette:esc palette=${document.querySelector('.palette-backdrop') ? 'open' : 'closed'} active=${(document.activeElement as HTMLElement | null)?.className.split(' ')[0] ?? '?'}`, '', 'probe'), 3500)
    }
    setTimeout(() => {
      const v = editorViewRef.current; if (!v) return
      v.focus(); v.dispatch({ selection: { anchor: Math.min(20, v.state.doc.length) } })
      v.contentDOM.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', code: 'KeyK', metaKey: true, bubbles: true, cancelable: true }))
    }, 1500)
  }
  if (probe === 'focus' && notes.length) setTimeout(() => setFocusMode(true), 1500)
  // 定期回顾：打开工具页后点「最近 N 天」
  if (probe?.startsWith('digest:') && !harnessProbeDone.current) {
    harnessProbeDone.current = true   // 存为笔记后 notes 变了，effect 会再跑一次——别再点一遍
    // digest:7:notes → 先把记忆范围切到「只看笔记」再回顾（第 184 轮）
    const seg = probe.slice(7).split(':')[1]
    if (seg === 'notes' || seg === 'meetings' || seg === 'imports') api.setMemoryScope(seg)
    else api.setMemoryScope('all')
    setTimeout(() => void openVirtual('kb:digest'), 600)
    setTimeout(() => { const days = probe.slice(7).split(':')[0]; const btn = Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === `最近 ${days} 天`); btn?.click() }, 2500)
    // digest:7:save → 结果出来后点「存为笔记」
    if (probe.endsWith(':save')) setTimeout(() => (Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.includes('存为笔记')) as HTMLElement | undefined)?.click(), 55000)
  }
  // 树的键盘导航：聚焦树，往下三格、回车打开
  if (probe === 'treekeys' && tree.length && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    setTimeout(() => {
      const t = document.querySelector('.note-tree') as HTMLElement | null
      if (!t) return
      t.focus()
      const key = (k: string) => t.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }))
      key('ArrowDown'); key('ArrowDown'); key('ArrowDown'); key('Enter')
    }, 1500)
  }
  // 没存上的草稿恢复：先往 localStorage 塞一份比库里新的草稿，再切走切回来
  if (probe?.startsWith('draft:') && notes.length >= 2 && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(6))
    if (n) { harnessProbeDone.current = true; void (async () => {
      const other = notes.find((x) => x.id !== n.id)!
      await switchTo(other)
      writeDraft(n.id, n.title, n.content + '\n\n（这一段是上次没存上的草稿）')
      setTimeout(() => void switchTo(n), 800)
      setTimeout(() => { const v = editorViewRef.current; if (v) v.dispatch({ effects: EditorView.scrollIntoView(v.state.doc.length, { y: 'end' }) }) }, 3500)
    })() }
  }
  // 拖一张图进编辑器：应该走资产库、正文里是 /api/assets/… 而不是 base64
  // 系统文件拖到树上：造一个 .md 文件用 DataTransfer 丢到指定标题的行上（没指定就丢到树空白处）
  if (probe?.startsWith('filedrop') && tree.length && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    setTimeout(() => {
      const title = probe.slice(9)
      const rowEl = title
        ? Array.from(document.querySelectorAll<HTMLElement>('.tree-node')).find((el) => el.textContent?.includes(title))
        : document.querySelector<HTMLElement>('.note-tree')
      if (!rowEl) { void api.clientLog('warn', 'filedrop: target not found ' + title, '', 'filedrop'); return }
      const dt = new DataTransfer()
      dt.items.add(new File(['# 拖进来的\n\n这篇是从系统拖进树的 .md。\n'], '拖进来的（可删）.md', { type: 'text/markdown' }))
      rowEl.dispatchEvent(new DragEvent('dragover', { dataTransfer: dt, bubbles: true, cancelable: true }))
      rowEl.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }))
    }, 1500)
  }
  if (probe === 'imgdrop' && notes.length && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    setTimeout(() => {
      const v = editorViewRef.current; if (!v) return
      const canvas = document.createElement('canvas'); canvas.width = 120; canvas.height = 60
      const ctx = canvas.getContext('2d')!; ctx.fillStyle = '#3b82f6'; ctx.fillRect(0, 0, 120, 60); ctx.fillStyle = '#fff'; ctx.font = '20px sans-serif'; ctx.fillText('probe', 20, 38)
      canvas.toBlob((blob) => {
        if (!blob) return
        const file = new File([blob], 'probe.png', { type: 'image/png' })
        const dt = new DataTransfer(); dt.items.add(file)
        const r = v.contentDOM.getBoundingClientRect()
        v.contentDOM.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, clientX: r.left + 40, clientY: r.top + 40, bubbles: true, cancelable: true }))
        setTimeout(() => void api.clientLog('warn', 'imgdrop doc has: ' + (/\]\(\/api\/assets\/[a-f0-9]+\.png\)/.test(v.state.doc.toString()) ? 'asset url' : (/data:image/.test(v.state.doc.toString()) ? 'DATA URI' : 'nothing')), '', 'imgdrop'), 2500)
      }, 'image/png')
    }, 1500)
  }
  // 格式化：滚到中段再 ⇧⌘F，视口不该被拽走
  if (probe?.startsWith('format:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(7))
    if (n) { harnessProbeDone.current = true; void (async () => {
      await switchTo(n)
      setTimeout(() => { const sc = document.querySelector('.note-scroll'); if (sc) sc.scrollTop = sc.scrollHeight * 0.4 }, 2000)
      setTimeout(() => formatNote(), 3000)
    })() }
  }
  // 历史：打开 ribbon 历史后展开第一版（看「与当前对比」）
  if (probe === 'history-open') setTimeout(() => (document.querySelector('.revision-row .kb-link') as HTMLElement | null)?.click(), 3000)
  // 树上拖拽：把 dragId 拖到 targetId 上（over → 成为它的子节点）。合成 DragEvent 走的是
  // 真实的 onDragStart/onDragOver/onDrop，dragover 之后要等一帧让 React 把落点状态渲染出来
  if (probe?.startsWith('dnd:') && tree.length && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    const [, dragId, targetId] = probe.split(':')
    setTimeout(() => {
      const rowOf = (id: string) => {
        const row = tree.find((r) => r.note_id === id)
        if (!row) return null
        const title = (row.title || '').trim()
        return Array.from(document.querySelectorAll('.tree-node')).find((el) => (el.textContent ?? '').includes(title)) as HTMLElement | undefined
      }
      const a = rowOf(dragId); const b = rowOf(targetId)
      if (!a || !b) { void api.clientLog('warn', `dnd probe: rows not found ${!!a} ${!!b}`, '', 'dnd'); return }
      const dt = new DataTransfer()
      a.dispatchEvent(new DragEvent('dragstart', { dataTransfer: dt, bubbles: true, cancelable: true }))
      const r = b.getBoundingClientRect()
      const mid = { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }
      b.dispatchEvent(new DragEvent('dragover', { dataTransfer: dt, bubbles: true, cancelable: true, ...mid }))
      setTimeout(() => {
        b.dispatchEvent(new DragEvent('dragover', { dataTransfer: dt, bubbles: true, cancelable: true, ...mid }))
        setTimeout(() => b.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true, ...mid })), 150)
      }, 150)
    }, 1500)
  }
  if (probe === 'shortcuts') setTimeout(() => setShowShortcuts(true), 900)
  if (probe === 'palette' || probe?.startsWith('palette:')) {
    setTimeout(() => window.dispatchEvent(new CustomEvent('open-command-palette')), 900)
    // palette:<q> → 往输入框里打字（走 React 认的 input 事件）
    const q = probe.includes(':') ? decodeURIComponent(probe.slice(8)) : ''
    // palette:keys → 不打字，往输入框按 12 下 ↓（最近编辑 6 + 命令若干），高亮要滚进视野
    if (q === 'keys') { setTimeout(() => { const input = document.querySelector('.palette input') as HTMLInputElement | null; let n = 0
      const t = setInterval(() => { input?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true })); if (++n >= 12) clearInterval(t) }, 30) }, 1800); return }
    if (q) setTimeout(() => {
      const input = document.querySelector('.palette input') as HTMLInputElement | null
      if (!input) return
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      setter?.call(input, q)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    }, 1600)
  }
  // 选区动作跑一遍：sel:verify / sel:trace / sel:polish / sel:rewrite / sel:expand
  if (probe?.startsWith('sel:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === '5f65df10cad6') ?? notes.find((x) => (x.content ?? '').length > 400)
    if (n) { harnessProbeDone.current = true; void (async () => {
      await switchTo(n)
      setTimeout(() => {
        const view = editorViewRef.current
        if (!view) return
        const t = view.state.doc.toString()
        const from = Math.max(0, t.indexOf('\n\n', 300) + 2)
        const to = Math.min(t.length, t.indexOf('\n\n', from + 50))
        view.dispatch({ selection: { anchor: from, head: to }, effects: EditorView.scrollIntoView(from, { y: 'center' }) })
        setSelectionMenu({ x: 700, y: 420, text: t.slice(from, to) })
        setTimeout(() => void actionsRef.current.handleSelectionAction(probe.slice(4) as SelectionAction), 400)
      }, 1500)
    })() }
  }
  // 编辑器内查找替换条（⌘F，CM 自带面板）——它的皮肤是 CM 默认的，跟 `/` 菜单一样要单独核对暗色
  if (probe === 'find' && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => (x.content ?? '').length > 80)
    if (n) { harnessProbeDone.current = true; void switchTo(n).then(() => setTimeout(() => {
      const view = editorViewRef.current
      if (!view) return
      void import('@codemirror/search').then((m) => { m.openSearchPanel(view); const inp = document.querySelector<HTMLInputElement>('.cm-search input[main-field]'); if (inp) { inp.value = '样机'; inp.dispatchEvent(new Event('change', { bubbles: true })); m.findNext(view) } })
    }, 1500)) }
  }
  if (probe === 'selection' && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => (x.content ?? '').length > 80)
    if (n) { harnessProbeDone.current = true; void (async () => {
      await switchTo(n)
      setTimeout(() => {
        const view = editorViewRef.current
        if (!view) return
        view.dispatch({ selection: { anchor: 10, head: 60 } })
        setSelectionMenu({ x: 700, y: 420, text: view.state.sliceDoc(10, 60) })
      }, 1500)
    })() }
  }
  // 打磨模式 / 逐轮我来定（轮末暂停等处置）
  if ((probe?.startsWith('polish:') || probe?.startsWith('review:')) && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(probe.indexOf(':') + 1))
    if (n) { harnessProbeDone.current = true; void (async () => {
      await switchTo(n)
      if (probe.startsWith('review:')) setReviewEachRound(true)
      setTimeout(() => void actionsRef.current.runNoteHarness(probe.startsWith('polish:') ? 'polish' : 'write'), 1500)
    })() }
  }
  if (probe?.startsWith('harness:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(8))
    if (n) { harnessProbeDone.current = true; void (async () => { await switchTo(n); setTimeout(() => void actionsRef.current.runNoteHarness('write'), 1500) })() }
  }
  // 只对截图用户跑：harness 在服务端改笔记，对真实用户跑一次就污染一篇（实拍踩过）。
  // 探针 effect 会因依赖变化跑两次，用 ref 挡住第二次。
  if (probe === 'harness' && notes.length && api.getUser().startsWith('shot-') && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    const n = notes.find((x) => (x.content ?? '').trim().length > 200) ?? notes[0]
    if (n) void (async () => { await switchTo(n); setTimeout(() => void actionsRef.current.runNoteHarness('write'), 1500) })()
  }
  // 用一个专门的截图用户跑，别污染真实库。要 harnessProbeDone 守着：runProbe 随 notes/tree 刷新
  // 会再进来，之前一轮建了三篇空「未命名」（实拍 demo 库攒了一堆）。
  if (probe === 'blank' && !harnessProbeDone.current) { harnessProbeDone.current = true; setTimeout(() => void newNote(), 600) }
  // 新建一篇空笔记并打开 ribbon 的某个标签（引用 / 链接 / 历史 / 路径 / 信息）：看全新一篇上这些标签的空状态
  if (probe?.startsWith('blank:ribbon:') && !harnessProbeDone.current) { harnessProbeDone.current = true; setTimeout(() => void newNote(), 600) }
  // 新建一篇然后往正文里写一段（不落库）：看右栏「记忆」在空库 / 有库时各说什么
  if (probe === 'blank:write' && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    setTimeout(() => void newNote(), 600)
    setTimeout(() => {
      const el = document.querySelector('.note-scroll .cm-content')
      const v = el && EditorView.findFromDOM(el as HTMLElement)
      if (v) v.dispatch({ changes: { from: v.state.doc.length, insert: '今天跟供应商确认了 PCBA 样品的交期，4 月 10 日拿到手板之后再定下一步的测试安排。' } })
    }, 2500)
  }
  // 空笔记上点续写：应该提示先写点东西，而不是让模型编
  if (probe === 'blank-tap' && !harnessProbeDone.current) { harnessProbeDone.current = true; setTimeout(() => void newNote(), 600); setTimeout(() => void actionsRef.current.runMagicTap(), 2500) }
  if (probe === 'split' && notes.length >= 2) setTimeout(() => openInSplit(notes[1].id), 800)
  // splitv:<id> → 把某个虚拟页（kb:facts?topic=work 这种）放进分屏
  if (probe?.startsWith('splitv:')) setTimeout(() => openInSplit(probe.slice(7)), 800)
  // ⌘K 命令「换个图标」→ 选择器该弹在标题行下
  if (probe === 'icon-cmd' && notes.length) setTimeout(() => window.dispatchEvent(new CustomEvent('open-icon-picker')), 1500)
  // 空库：新建一篇、点开选择器挑「rocket」——只有一个标签、够宽，标签上该有图标（真落库，用户跑完删）
  if (probe === 'blank:icon' && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    setTimeout(() => void newNote(), 600)
    setTimeout(() => (document.querySelector('.title-icon-btn') as HTMLButtonElement | null)?.click(), 2500)
    setTimeout(() => (document.querySelector('.icon-picker-cell[title="rocket"]') as HTMLButtonElement | null)?.click(), 3500)
  }
  // 选择器里用方向键走：右、右、下 → 从第 1 格走到第 11 格（task），把焦点所在格子的名字写进日志
  if (probe === 'icon-picker:keys' && notes.length && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    setTimeout(() => (document.querySelector('.title-icon-btn') as HTMLButtonElement | null)?.click(), 1500)
    setTimeout(() => { for (const k of ['ArrowRight', 'ArrowRight', 'ArrowDown']) document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true })) }, 3000)
    setTimeout(() => void api.clientLog('warn', `icon-picker:keys active=${(document.activeElement as HTMLElement | null)?.title ?? '?'}`, '', 'probe'), 3500)
  }
  // 选择器上按 Esc：焦点该回到标题行的图标钮
  if (probe === 'icon-picker:esc' && notes.length && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    setTimeout(() => (document.querySelector('.title-icon-btn') as HTMLButtonElement | null)?.click(), 1500)
    setTimeout(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })), 3000)
    setTimeout(() => void api.clientLog('warn', `icon-picker:esc picker=${document.querySelector('.icon-picker') ? 'open' : 'closed'} active=${(document.activeElement as HTMLElement | null)?.className ?? '?'}`, '', 'probe'), 3500)
  }
  // 标题行图标点开选择器
  if (probe === 'icon-picker' && notes.length) setTimeout(() => (document.querySelector('.title-icon-btn') as HTMLButtonElement | null)?.click(), 1500)
  // 点开选择器再挑「rocket」：标题行 / 树上的图标都该变（真落库，跑完用 setNoteIcon(id, '') 清回去）
  if (probe === 'icon-picker:pick' && notes.length && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    setTimeout(() => (document.querySelector('.title-icon-btn') as HTMLButtonElement | null)?.click(), 1500)
    setTimeout(() => (document.querySelector('.icon-picker-cell[title="rocket"]') as HTMLButtonElement | null)?.click(), 2500)
  }
  // 主栏正开着的那篇放进分屏：应该是只读 + 一行提示
  if (probe === 'split:same' && notes.length) setTimeout(() => openInSplit(notes[0].id), 800)
  // 分屏第二栏里写字：找到那一栏的 CM 视图，文末插一句，看正文变了 + 底下出「已保存」（探针模式不落库）
  if (probe === 'split:edit' && notes.length >= 2 && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    setTimeout(() => openInSplit(notes[1].id), 800)
    setTimeout(() => {
      const el = document.querySelector('.split-body .cm-content')
      const v = el && EditorView.findFromDOM(el as HTMLElement)
      if (!v) { void api.clientLog('warn', 'split:edit: no editor in split', '', 'probe'); return }
      v.dispatch({ changes: { from: v.state.doc.length, insert: '\n\n（这一句是在分屏里写的）' } })
    }, 3000)
    setTimeout(() => void api.clientLog('warn', `split:edit status=${JSON.stringify(document.querySelector('.split-save-status')?.textContent ?? null)} editors=${document.querySelectorAll('.split-body .cm-content').length}`, '', 'probe'), 5500)
  }
  if (probe === 'confirm' && tree.length) {
    const parent = tree.find((r) => r.child_count > 0)
    const n = parent && notes.find((x) => x.id === parent.note_id)
    if (parent && n) setTimeout(() => void removeWithSubtree(n, parent), 800)
  }
  if (probe === 'quick-view' && notes.length) {
    setTimeout(() => setQuick(notes[0]), 800)
  }
  if ((probe === 'picker' || probe === 'picker:keys') && tree.length) {
    // 「移动到…」的选择器；:keys → 往输入框按 25 下 ↓，高亮要滚进视野
    setTimeout(() => void moveNodeTo(tree[0]), 600)
    if (probe === 'picker:keys') setTimeout(() => { const input = document.querySelector('.palette input') as HTMLInputElement | null; let n = 0
      const t = setInterval(() => { input?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true })); if (++n >= 25) clearInterval(t) }, 30) }, 1800)
  }
  if (probe === 'tab-menu' && notes.length >= 2) {
    void (async () => {
      for (const n of notes.slice(0, 2)) { await switchTo(n) }
      setTimeout(() => setTabs((ts: any[]) => { setTabMenu({ tab: ts[0], at: { x: 160, y: 40 } }); return ts }), 800)
    })()
    return
  }
  if (probe === 'fact-peek') {
    // 往正文插一条真实的出处，再把鼠标事件打到它上面——CodeMirror 的
    // hoverTooltip 只认真实的 mousemove。
    setContent((c: string) => c + '\n\n据 [terrence-1872-5F8] 所述。\n')
    setTimeout(() => {
      // 取屏幕里能看见的那条：第一条常在折叠线下面，坐标打过去 CM 什么都不弹
      const all = Array.from(document.querySelectorAll('.cm-fact-cite'))
      const el = all[all.length - 1]
      if (!el) return
      el.scrollIntoView({ block: 'center' })
      setTimeout(() => {
        const r = el.getBoundingClientRect()
        const at = { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }
        el.dispatchEvent(new MouseEvent('mousemove', { ...at, bubbles: true }))
        document.querySelector('.cm-content')?.dispatchEvent(
          new MouseEvent('mousemove', { ...at, bubbles: true }))
      }, 500)
    }, 1200)
    return
  }
  if (probe === 'tree-menu' && tree.length) {
    // 挑一个**画在树上**的文件夹（顶层的）：折叠着的父节点下面的行没渲染，右键高亮看不出来（第 513 轮）
    const row = tree.find((r) => r.child_count > 0 && r.parent_note_id === api.ROOT_ID) ?? tree.find((r) => r.child_count > 0) ?? tree[0]
    setTreeMenu({ row, at: { x: 260, y: 180 } })
    setTimeout(() => void api.clientLog('warn', `tree-menu row=${row.title} ctx-target=${document.querySelectorAll('.tree-node.ctx-target').length} title=${(document.querySelector('.tree-node.ctx-target .tree-title') as HTMLElement | null)?.textContent ?? '-'}`, '', 'probe'), 1500)
  }
}

/** `click:` 用的查找：`text=<文字>` 在可点的元素里按文字找（去空白后相等），否则当 CSS 选择器。 */
function probeFind(sel: string): HTMLElement | null {
  if (!sel.startsWith('text=')) return document.querySelector(sel) as HTMLElement | null
  const want = sel.slice(5).replace(/\s+/g, '')
  return Array.from(document.querySelectorAll<HTMLElement>('button, [role=menuitem], .palette-item, .chip, a.link, .fb-btn'))
    .find((e) => (e.textContent ?? '').replace(/\s+/g, '') === want
      || (e.querySelector('.cm-label, .fb-label')?.textContent ?? '').replace(/\s+/g, '') === want) ?? null
}
