/**
 * ribbon 里两个「语义上就该在 ribbon」的标签（Trilium 的 NoteInfoTab /
 * NotePathsTab）：
 * · 笔记信息：创建/修改时间、字数、跟知识库的连接
 * · 笔记路径：**克隆之后一篇笔记同时长在几处**，用户必须能看到「它还在哪儿」，
 *   不然改了一处不知道另外哪几处跟着变
 */
import { useEffect, useState } from 'react'

import { notePaths, type Note, type TreeRow } from '../api'
import { displayTitle } from '../util/displayTitle'

export function NoteInfoPanel({ note, content, row }: { note: Note; content: string; row?: TreeRow }) {
  const words = content.replace(/\s+/g, '').length
  const fmt = (s: string) => (s ? s.replace('T', ' ').slice(0, 16) : '—')
  return (
    <dl className="kv">
      <dt>创建</dt><dd>{fmt(note.created_at)}</dd>
      <dt>修改</dt><dd>{fmt(note.updated_at)}</dd>
      <dt>字数</dt><dd>{words} · 约 {Math.max(1, Math.round(words / 400))} 分钟阅读</dd>
      <dt>引用</dt><dd>{row?.cite_count ? `${row.cite_count} 条知识库记录` : '无'}</dd>
      <dt>摄入</dt><dd>{row?.ingested_at ? `已摄入（${row.ingested_at.slice(0, 10)}）` : '未摄入'}</dd>
      <dt>位置</dt><dd>{row?.branch_count && row.branch_count > 1 ? `${row.branch_count} 处（克隆）` : '1 处'}</dd>
      <dt>id</dt><dd><code style={{ fontSize: 11 }}>{note.id}</code></dd>
    </dl>
  )
}

export function NotePathsPanel({ noteId, rows, onOpen }: {
  noteId: string
  rows: TreeRow[]
  onOpen: (noteId: string) => void
}) {
  const [paths, setPaths] = useState<string[][] | null>(null)
  useEffect(() => {
    let alive = true
    setPaths(null)
    notePaths(noteId).then((p) => { if (alive) setPaths(p) }).catch(() => { if (alive) setPaths([]) })
    return () => { alive = false }
  }, [noteId, rows])
  const name = (id: string) => {
    const r = rows.find((x) => x.note_id === id)
    return r ? displayTitle(r) : id
  }
  if (paths === null) return <p className="muted" style={{ margin: 0 }}>…</p>
  return (
    <div className="stack" style={{ fontSize: 13 }}>
      {paths.length > 1 && (
        <p className="muted" style={{ margin: 0, fontSize: 12 }}>
          这篇同时在 {paths.length} 个位置——它们是同一篇，改一处处处都变。
        </p>
      )}
      {paths.map((p, i) => (
        <div key={i} className="breadcrumb">
          <span className="muted">树根</span>
          {p.map((id, k) => (
            <span key={id}>
              <span className="muted"> / </span>
              {k === p.length - 1
                ? <b>{name(id)}</b>
                : <a href="#" onClick={(e) => { e.preventDefault(); onOpen(id) }}>{name(id)}</a>}
            </span>
          ))}
        </div>
      ))}
    </div>
  )
}
