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
import { layersOf, turnLayerOff } from './editor/roundDiff'
import * as api from './api'
import { SLASH_ITEMS } from './editor/slashMenu'
import type { SelectionAction } from './components/SelectionMenu'
import type { Note, TreeRow } from './api'

export type ProbeCtx = Record<string, any>

export function runProbe(probe: string, ctx: ProbeCtx): void {
  const { notes, tree, switchTo, openVirtual, openInSplit, newNote, removeWithSubtree, remove, syncTab, openWritingPlan, formatNote, setSelectionMenu, setPaneFocus, setContent, setTreeMenu, setTabs, setTabMenu, setShowShortcuts, setReviewEachRound, setQuick, setNoteQuery, setFocusMode, editorViewRef, actionsRef, harnessProbeDone, moveNodeTo } = ctx as ProbeCtx & { notes: Note[]; tree: TreeRow[] }
  if (probe === 'tabs' && notes.length >= 3) {
    // 连开三篇，看标签行铺开的样子
    void (async () => {
      for (const n of notes.slice(0, 3)) { await switchTo(n) }
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
  if (probe === 'settings') setTimeout(() => void openVirtual('app:settings', '设置'), 600)
  if (probe === 'skills') setTimeout(() => void openVirtual('app:skills'), 600)
  // 外观三选一走 preload → 主进程 nativeTheme；点完再截图看有没有真的变色
  if (probe === 'theme-dark' || probe === 'theme-system') {
    setTimeout(() => void openVirtual('app:settings', '设置'), 600)
    setTimeout(() => (document.querySelector(probe === 'theme-dark' ? '.chip .bx-moon' : '.chip .bx-desktop')?.parentElement as HTMLElement | null)?.click(), 3000)
  }
  if (probe === 'import') setTimeout(() => void openVirtual('app:import', '导入'), 600)
  if (probe === 'conflicts') setTimeout(() => void openVirtual('kb', '知识库'), 600)
  if (probe === 'trash') setTimeout(() => void openVirtual('app:trash', '最近删除'), 600)
  // 导回区块在导入页最底下：打开后滚到它
  if (probe === 'exportback') setTimeout(() => { void openVirtual('app:import', '导入'); setTimeout(() => document.querySelector('.export-back')?.scrollIntoView({ block: 'end' }), 1500) }, 600)
  if (probe?.startsWith('open:')) setTimeout(() => void openVirtual(probe.slice(5)), 900)
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
    if (n) { harnessProbeDone.current = true; void switchTo(n).then(() => { for (const t of [3000, 6000, 8000]) setTimeout(() => { const v = editorViewRef.current; if (v) v.dispatch({ effects: EditorView.scrollIntoView(v.state.doc.length, { y: 'end' }) }) }, t); setTimeout(() => document.querySelector('.cm-note-link')?.dispatchEvent(new MouseEvent('mouseenter')), 9000) }) }
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
  if (probe === 'keypalette' && notes.length && !harnessProbeDone.current) {
    harnessProbeDone.current = true
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
      try { localStorage.setItem('memoket-note-draft:' + n.id, JSON.stringify({ title: n.title, content: n.content + '\n\n（这一段是上次没存上的草稿）', at: Date.now() })) } catch { /* 无所谓 */ }
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
  // 空笔记上点续写：应该提示先写点东西，而不是让模型编
  if (probe === 'blank-tap' && !harnessProbeDone.current) { harnessProbeDone.current = true; setTimeout(() => void newNote(), 600); setTimeout(() => void actionsRef.current.runMagicTap(), 2500) }
  if (probe === 'split' && notes.length >= 2) setTimeout(() => openInSplit(notes[1].id), 800)
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
