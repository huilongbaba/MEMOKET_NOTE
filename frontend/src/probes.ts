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
import { writeDraft } from './util/draft'
import { layersOf, turnLayerOff } from './editor/roundDiff'
import * as api from './api'
import { SLASH_ITEMS } from './editor/slashMenu'
import type { SelectionAction } from './components/SelectionMenu'
import type { Note, TreeRow } from './api'

export type ProbeCtx = Record<string, any>

export function runProbe(probe: string, ctx: ProbeCtx): void {
  // 记忆范围存在 localStorage，上一次探针（digest:30:notes）切的会留给下一次——
  // 除非这次探针自己指定了范围，否则先复位到「全部记忆」（第 188 轮实拍右栏莫名「只看笔记」）
  const { notes, tree, switchTo, openVirtual, openInSplit, newNote, removeWithSubtree, remove, syncTab, openWritingPlan, formatNote, setSelectionMenu, setPaneFocus, setContent, setTreeMenu, setTabs, setTabMenu, setShowShortcuts, setReviewEachRound, setQuick, setNoteQuery, setFocusMode, editorViewRef, actionsRef, harnessProbeDone, moveNodeTo, setKbExpanded, loadKbChildren } = ctx as ProbeCtx & { notes: Note[]; tree: TreeRow[] }
  if (!harnessProbeDone.current && !/:(notes|meetings|imports)(:|$)/.test(probe) && api.memoryScope() !== 'all') api.setMemoryScope('all')
  if (probe === 'tabs' && notes.length >= 3) {
    // 连开三篇，看标签行铺开的样子
    void (async () => {
      for (const n of notes.slice(0, 3)) { await switchTo(n) }
    })()
    return
  }
  // 标签装不下时右边的 ▾：列出全部标签
  if (probe === 'tabs:list') {
    setTimeout(() => (document.querySelector('.tab-list') as HTMLElement | null)?.click(), 2500)
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
  if (probe?.startsWith('open:')) setTimeout(() => void openVirtual(probe.slice(5)), 900)
  // openend:<id> → 打开虚拟页并把正文滚到底（看页面尾部的小节 / 分页器）
  if (probe?.startsWith('openend:')) { setTimeout(() => void openVirtual(probe.slice(8)), 900); setTimeout(() => { const el = document.querySelector('.note-scroll'); if (el) el.scrollTop = el.scrollHeight }, 5000) }
  // note:<id>[:ribbon:<tab>] → 按 id 打开某篇真笔记（ribbon 标签由 App 的 defaultOpen 从 probe 串里读）
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
  // kbexpand:<id> → 把树上的某个知识库分类展开（看懒加载的那一层长什么样）
  if (probe?.startsWith('kbexpand:') && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    // `kbexpand:<id>:end` → 展开后把左栏滚到底（看 300 条之后的尾巴行）
    const toEnd = probe.endsWith(':end')
    const id = toEnd ? probe.slice(9, -4) : probe.slice(9)
    if (toEnd) setTimeout(() => { const el = document.querySelector('.left-pane-body'); if (el) el.scrollTop = el.scrollHeight }, 4500)
    // 父链也要展开（kb:entity:x 挂在 kb:entities 下，那层是懒加载的，也要取）
    const parent = ({ entity: 'kb:entities', topic: 'kb:topics', month: 'kb:timeline', unit: 'kb:recent', material: 'kb:recent', etype: 'kb:entities' } as Record<string, string>)[id.split(':')[1]]
    setTimeout(() => {
      setKbExpanded(new Set(['kb', ...(parent ? [parent] : []), id]))   // 只展开这一条链，别的收起
      if (parent) void loadKbChildren(parent)
      void loadKbChildren(id)
    }, 900)
    // 把那个节点滚到树的可视区顶部，不然截图里看不到展开的那一层
    setTimeout(() => {
      const NAMES = { 'kb:entities': '实体', 'kb:topics': '主题', 'kb:recent': '最近摄入', 'kb:timeline': '时间线' } as Record<string, string>
      const find = (label: string) => Array.from(document.querySelectorAll('.tree-node')).find((n) => new RegExp('^' + label + '\\s*\\d*$', 'i').test(n.textContent?.trim() ?? ''))
      // 会议 / 月份行的文字不是 id（「03-10 · 产品计划会…」）：找不到就滚到它的父分类
      const el = find(NAMES[id] ?? id.split(':').pop() ?? '') ?? (parent ? find(NAMES[parent] ?? parent) : undefined)
      el?.scrollIntoView({ block: 'start' })
    }, 2500)
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
  if (probe?.startsWith('tap:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(4))
    if (n) { harnessProbeDone.current = true; void (async () => {
      await switchTo(n)
      // 光标放到正文中段（第二个二级标题之前），看「从光标处续写」是不是插在那
      setTimeout(() => {
        const v = editorViewRef.current
        if (v) { const t = v.state.doc.toString(); const i = t.indexOf('\n## ', t.indexOf('\n## ') + 1); v.focus(); v.dispatch({ selection: { anchor: i > 0 ? i : Math.floor(t.length / 2) } }) }
      }, 1200)
      setTimeout(() => void actionsRef.current.runMagicTap(), 1500)
    })() }
  }
  // 写作流三件：`/` 菜单、`@` 引用补全、右栏各标签
  if ((probe === 'slash' || probe === 'mention' || probe === 'wikilink') && notes.length && !harnessProbeDone.current) {
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
          view.dispatch({ changes: { from: end + 2, insert: probe === 'slash' ? '/' : '@' }, selection: { anchor: end + 3 }, userEvent: 'input.type' })
          if (probe === 'mention') view.dispatch({ changes: { from: end + 3, insert: '样机' }, selection: { anchor: end + 5 }, userEvent: 'input.type' })
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
  if (probe === 'plan-panel' && tree.length) setTimeout(() => openWritingPlan(), 1200)
  // 写作计划面板上点「换个目标」，看放弃计划的确认框（要那个文件夹上有计划）
  // `:abandon-esc` 再按一次 Esc——只该关掉确认框，面板留着；`plan-panel:esc` 只开面板然后 Esc——面板该关掉
  if ((probe === 'plan-panel:abandon' || probe === 'plan-panel:abandon-esc' || probe === 'plan-panel:esc') && tree.length && !harnessProbeDone.current) {
    harnessProbeDone.current = true
    setTimeout(() => openWritingPlan(), 1200)
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
  if (probe?.startsWith('margin:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(7))
    if (n) { harnessProbeDone.current = true; void switchTo(n) }
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
    if (n) { harnessProbeDone.current = true; const t0 = performance.now(); void switchTo(n).then(() => requestAnimationFrame(() => void api.clientLog('warn', `big note ${n.content.length} 字 switchTo→paint ${Math.round(performance.now() - t0)} ms`, '', 'perf'))) }
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
  if (probe === 'picker' && tree.length) {
    // 「移动到…」的选择器
    setTimeout(() => void moveNodeTo(tree[0]), 600)
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
    const row = tree.find((r) => r.child_count > 0) ?? tree[0]
    setTreeMenu({ row, at: { x: 260, y: 180 } })
  }
}
