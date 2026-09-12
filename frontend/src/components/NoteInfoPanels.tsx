/**
 * ribbon 里两个「语义上就该在 ribbon」的标签（Trilium 的 NoteInfoTab /
 * NotePathsTab）：
 * · 笔记信息：创建/修改时间、字数、跟知识库的连接
 * · 笔记路径：**克隆之后一篇笔记同时长在几处**，用户必须能看到「它还在哪儿」，
 *   不然改了一处不知道另外哪几处跟着变
 */
import { useEffect, useState } from 'react'

import { notePaths, noteRemotes, type Note, type NoteRemote, type TreeRow } from '../api'
import { displayTitle } from '../util/displayTitle'
import { fmtDate, fmtDateTime } from '../util/time'
import { readingMinutes, wordCount } from '../util/wordCount'

const SOURCE_LABEL: Record<string, string> = { obsidian: 'Obsidian', notion: 'Notion', apple: 'Apple 备忘录', evernote: 'Evernote', feishu: '飞书', import: '导入' }

export function NoteInfoPanel({ note, content, row }: { note: Note; content: string; row?: TreeRow }) {
  const words = wordCount(content)
  // 导回副本（docs/import-sync-plan.md §2）：这篇在哪些平台有副本、上次导回是什么时候
  const [remotes, setRemotes] = useState<NoteRemote[]>([])
  useEffect(() => {
    let alive = true
    const load = () => { noteRemotes(note.id).then((r) => { if (alive) setRemotes(r) }).catch(() => { /* 没有就没有 */ }) }
    load()
    window.addEventListener('note-remotes-changed', load)
    return () => { alive = false; window.removeEventListener('note-remotes-changed', load) }
  }, [note.id])
  return (
    <dl className="kv">
      <dt>创建</dt><dd>{fmtDateTime(note.created_at)}</dd>
      <dt>修改</dt><dd>{fmtDateTime(note.updated_at)}</dd>
      <dt>字数</dt><dd>{words} · 约 {readingMinutes(words)} 分钟阅读</dd>
      <dt>引用</dt><dd>{row?.cite_count ? `${row.cite_count} 条知识库记录` : '无'}</dd>
      <dt>摄入</dt><dd>{row?.ingested_at ? `已摄入（${fmtDate(row.ingested_at)}）` : '未摄入'}</dd>
      {note.source && <><dt>来源</dt><dd>{SOURCE_LABEL[note.source] ?? note.source}{note.imported_at ? ` · ${fmtDate(note.imported_at)} 导入` : ''}{note.imported_at && note.updated_at > note.imported_at ? ' · 本地改过' : ''}</dd></>}
      {remotes.length > 0 && <><dt>副本</dt><dd>{remotes.map((r) => `${SOURCE_LABEL[r.platform] ?? r.platform} · ${fmtDate(r.exported_at)} 导回${r.exported_at < note.updated_at ? '（之后改过）' : ''}`).join('；')}</dd></>}
      <dt>位置</dt><dd>{row?.branch_count && row.branch_count > 1 ? `${row.branch_count} 处（克隆）` : '1 处'}</dd>
      <dt>id</dt><dd><code style={{ fontSize: 11 }}>{note.id}</code></dd>
    </dl>
  )
}

export function NotePathsPanel({ noteId, rows, onOpen, onClone }: {
  noteId: string
  rows: TreeRow[]
  onOpen: (noteId: string) => void
  /** Trilium 的 note paths 组件在列表底下就带「克隆到新位置」 */
  onClone?: () => void
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
      {onClone && (
        <div>
          <button className="chip" onClick={onClone}><i className="bx bx-duplicate" /> 克隆到另一个位置…</button>
        </div>
      )}
    </div>
  )
}
