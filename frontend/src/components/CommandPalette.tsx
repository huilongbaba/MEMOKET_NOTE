import { useEffect, useRef, useState } from 'react'
import * as api from '../api'
import type { Fact, Note } from '../api'

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
  const [facts, setFacts] = useState<Fact[]>([])
  const [activeIndex, setActiveIndex] = useState(0)
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
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    if (!open) return
    setQ('')
    setNotes([])
    setFacts([])
    setActiveIndex(0)
    const t = setTimeout(() => inputRef.current?.focus(), 0)
    return () => clearTimeout(t)
  }, [open])

  useEffect(() => {
    if (!open || !q.trim()) { setNotes([]); setFacts([]); return }
    const t = setTimeout(() => {
      api.listNotes(q).then(setNotes).catch(() => {})
      api.recall(q, 6).then((r) => setFacts(r.facts)).catch(() => {})
    }, 200)
    return () => clearTimeout(t)
  }, [q, open])

  if (!open) return null

  const items = [
    ...notes.map((n) => ({ kind: 'note' as const, note: n })),
    ...facts.map((f) => ({ kind: 'fact' as const, fact: f })),
  ]

  function choose(i: number) {
    const item = items[i]
    if (!item) return
    if (item.kind === 'note') {
      onOpenNote(item.note)
    } else {
      onInsertFact(`${item.fact.text} [${item.fact.id}]`)
    }
    setOpen(false)
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
          {q.trim() && items.length === 0 && <p className="muted" style={{ padding: 8 }}>没有匹配结果</p>}
          {notes.length > 0 && <p className="muted palette-group">笔记</p>}
          {notes.map((n, i) => (
            <div
              key={n.id}
              className={'palette-item' + (i === activeIndex ? ' active' : '')}
              onClick={() => choose(i)}
            >
              📝 {n.title || '未命名'}
            </div>
          ))}
          {facts.length > 0 && <p className="muted palette-group">知识库（点击插入引用）</p>}
          {facts.map((f, i) => (
            <div
              key={f.id}
              className={'palette-item' + (notes.length + i === activeIndex ? ' active' : '')}
              onClick={() => choose(notes.length + i)}
            >
              💡 {f.text.slice(0, 60)}{f.when && <span className="muted"> · {f.when}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
