import React, { useEffect, useRef, useState } from 'react'
import * as api from '../api'
import type { Fact, Note } from '../api'
import { displayTitle } from '../util/displayTitle'
import { fmtDate } from '../util/time'
import { matchSnippet } from '../util/snippet'
import Highlight from './Highlight'

/** 没输入时的快捷命令：Trilium 的 jumpToNote 空态列最近笔记，我们再加几个
 * 常去的页——每一项走 window 事件，跟左栏按钮同一条路。 */
const COMMANDS: { label: string; icon: string; run: () => void }[] = [
  { label: '新建笔记', icon: 'bx-plus', run: () => window.dispatchEvent(new CustomEvent('new-note')) },
  { label: '知识库总览', icon: 'bx-data', run: () => window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb' })) },
  { label: '主题地图', icon: 'bx-network-chart', run: () => window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb:graph' })) },
  { label: '时间线', icon: 'bx-calendar', run: () => window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb:timeline' })) },
  { label: '导入', icon: 'bx-import', run: () => window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'app:import' })) },
  { label: '设置', icon: 'bx-cog', run: () => window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'app:settings' })) },
  { label: '定位到当前笔记（树上）', icon: 'bx-crosshair', run: () => window.dispatchEvent(new CustomEvent('tree-locate')) },
  { label: '折叠整棵树', icon: 'bx-collapse-vertical', run: () => window.dispatchEvent(new CustomEvent('tree-collapse')) },
  { label: '快捷键', icon: 'bx-command', run: () => window.dispatchEvent(new CustomEvent('show-shortcuts')) },
  { label: '导出全部笔记（Markdown zip）', icon: 'bx-export', run: () => window.dispatchEvent(new CustomEvent('export-all')) },
  // 导回住在导入页最底下（第 128 轮实拍：⌘K 搜「导」只有导入 / 导出，找不到导回）
  { label: '导回到 Obsidian / Notion / 飞书…', icon: 'bx-share',
    run: () => { window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'app:import' })); setTimeout(() => document.querySelector('.export-back')?.scrollIntoView({ block: 'start', behavior: 'smooth' }), 700) } },
]

/**
 * Cmd/Ctrl+K: one search box over both notes and the knowledge base, instead
 * of two separate search boxes in two separate panels. Picking a note opens
 * it; picking a fact inserts a citation at the cursor -- same citation
 * format @-mention completion and RelatedMemory already use, so all three
 * "find and cite a fact" paths in the app behave identically.
 */
export default function CommandPalette({ onOpenNote, onInsertFact }: {
  onOpenNote: (n: Note) => void
  onInsertFact: (text: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [notes, setNotes] = useState<Note[]>([])
  const [notesTotal, setNotesTotal] = useState(0)
  const [facts, setFacts] = useState<Fact[]>([])
  const [activeIndex, setActiveIndex] = useState(0)
  const [recent, setRecent] = useState<Note[]>([])
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      // ⌘K 是我们的；⌘J 是 Trilium 的 jumpToNote——给个别名，两边的肌肉记忆都认
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && (e.key.toLowerCase() === 'k' || e.key.toLowerCase() === 'j')) {
        e.preventDefault()
        setOpen((v) => !v)
      } else if (e.key === 'Escape') {
        setOpen(false)
      }
    }
    // 左栏放大镜按钮 / 探针走这条事件——它曾经只有发送方没有接收方，
    // 按钮点了没反应（r3 截图实拍）。
    function onOpenEvent() { setOpen(true) }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('open-command-palette', onOpenEvent)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('open-command-palette', onOpenEvent)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    setQ('')
    setNotes([])
    setFacts([])
    setActiveIndex(0)
    const t = setTimeout(() => inputRef.current?.focus(), 0)
    api.listNotes('').then((ns) => setRecent(
      [...ns].sort((a, b) => (b.updated_at > a.updated_at ? 1 : -1)).slice(0, 6),
    )).catch(() => {})
    return () => clearTimeout(t)
  }, [open])

  useEffect(() => {
    if (!open || !q.trim()) { setNotes([]); setNotesTotal(0); setFacts([]); return }
    const t = setTimeout(() => {
      // 标题命中的排前面，正文命中的排后面、最多给 8 条——「设」这种字几乎每篇正文
      // 都有，全列出来跟没搜一样
      api.listNotes(q).then((list) => {
        const needle = q.trim().toLowerCase()
        const byTitle = list.filter((n) => displayTitle(n).toLowerCase().includes(needle))
        const byBody = list.filter((n) => !byTitle.includes(n))
        setNotes([...byTitle, ...byBody].slice(0, 8))
        setNotesTotal(list.length)
      }).catch(() => {})
      api.recall(q, 6).then((r) => setFacts(r.facts)).catch(() => {})
    }, 200)
    return () => clearTimeout(t)
  }, [q, open])

  if (!open) return null

  const typing = !!q.trim()
  const cmdHits = typing ? COMMANDS.filter((c) => c.label.includes(q.trim())) : COMMANDS
  const items = typing
    ? [
      ...cmdHits.map((c) => ({ kind: 'cmd' as const, cmd: c })),
      ...notes.map((n) => ({ kind: 'note' as const, note: n })),
      ...facts.map((f) => ({ kind: 'fact' as const, fact: f })),
    ]
    : [
      ...recent.map((n) => ({ kind: 'note' as const, note: n })),
      ...COMMANDS.map((c) => ({ kind: 'cmd' as const, cmd: c })),
    ]

  function choose(i: number) {
    const item = items[i]
    if (!item) return
    if (item.kind === 'note') onOpenNote(item.note)
    else if (item.kind === 'cmd') item.cmd.run()
    else onInsertFact(`${item.fact.text} [${item.fact.id}]`)
    setOpen(false)
  }

  let idx = 0
  function row(key: string, label: React.ReactNode, icon: string) {
    const i = idx++
    return (
      <div key={key} className={'palette-item' + (i === activeIndex ? ' active' : '')} onClick={() => choose(i)}>
        <i className={'bx ' + icon} /> {label}
      </div>
    )
  }

  return (
    <div className="palette-backdrop" onClick={() => setOpen(false)}>
      <div className="palette" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => { setQ(e.target.value); setActiveIndex(0) }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setActiveIndex((i) => Math.min(i + 1, items.length - 1)) }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setActiveIndex((i) => Math.max(i - 1, 0)) }
            else if (e.key === 'Enter') { e.preventDefault(); choose(activeIndex) }
          }}
          placeholder="搜索笔记或知识库…（Esc 关闭）"
        />
        <div className="palette-results">
          {typing && items.length === 0 && <p className="muted" style={{ padding: 8 }}>没有匹配结果</p>}
          {!typing && recent.length > 0 && <p className="muted palette-group">最近编辑</p>}
          {!typing && recent.map((n) => row(n.id, <span className="palette-line"><span className="palette-main">{displayTitle(n)}</span>
            <span className="muted palette-when">{fmtDate(n.updated_at)}</span></span>, 'bx-note'))}
          {typing && cmdHits.length > 0 && <p className="muted palette-group">命令</p>}
          {typing && cmdHits.map((c) => row('c' + c.label, c.label, c.icon))}
          {notes.length > 0 && <p className="muted palette-group">笔记</p>}
          {typing && notes.map((n) => {
            // 标题里没命中的（靠正文命中进来的）给一截命中片段——实拍搜「创业」，
            // 「harness 测试」混在一排「创业一年回顾」里，看不出为什么在这。
            const title = displayTitle(n)
            const s = title.toLowerCase().includes(q.trim().toLowerCase()) ? null : matchSnippet(n.content, q, 18)
            return row(n.id, <span className="palette-line"><span className="palette-main"><Highlight text={title} q={q} />
              {s && <span className="muted palette-snip">{s.before}<mark>{s.hit}</mark>{s.after}</span>}</span>
              <span className="muted palette-when">{fmtDate(n.updated_at)}</span></span>, 'bx-note')
          })}
          {/* 412 篇「会议纪要」搜「会议」只列 8 条，得说清后面还有多少（实拍大库用户） */}
          {typing && notesTotal > notes.length && <p className="muted palette-group" style={{ marginTop: 2 }}>还有 {notesTotal - notes.length} 篇没列出——多打几个字缩小范围</p>}
          {facts.length > 0 && <p className="muted palette-group">知识库（点击插入引用）</p>}
          {/* 日期单独一格不被截：之前拼在正文后面，长一点的事实日期先被省略号吃掉，
              一列里有的有日期有的没有。 */}
          {typing && facts.map((f) => row(f.id, <span className="palette-line"><span className="palette-main"><Highlight text={f.text} q={q} /></span>
            {f.when && <span className="muted palette-when">{f.when}</span>}</span>, 'bx-bulb'))}
          {!typing && <p className="muted palette-group">前往</p>}
          {!typing && COMMANDS.map((c) => row('c' + c.label, c.label, c.icon))}
        </div>
      </div>
    </div>
  )
}
