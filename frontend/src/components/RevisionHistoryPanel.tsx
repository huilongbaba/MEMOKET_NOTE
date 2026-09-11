import { useEffect, useState } from 'react'
import * as api from '../api'
import { toast } from '../toast'
import MarkdownEditor from './MarkdownEditor'

const REASON: Record<string, string> = { auto: '自动', manual: '手动', before_restore: '恢复前' }

function when(iso: string) {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * ribbon「历史」：这篇笔记的历史版本（Trilium 的 Note Revisions）。保存时正文变了
 * 且离上一版超过十分钟就自动留一版；也可以手动「存一版」。点一版看内容，
 * 「恢复到这一版」之前后端会把现在的正文再存一版，所以恢复永远可逆。
 */
export default function RevisionHistoryPanel({ noteId, currentChars, onRestored }: {
  noteId: string
  currentChars: number
  onRestored: (n: api.Note) => void
}) {
  const [revs, setRevs] = useState<api.NoteRevision[] | null>(null)
  const [open, setOpen] = useState<(api.NoteRevision & { content: string }) | null>(null)
  const [busy, setBusy] = useState(false)

  const reload = () => api.listRevisions(noteId).then(setRevs).catch(() => setRevs([]))
  useEffect(() => { setOpen(null); void reload() }, [noteId])  // eslint-disable-line react-hooks/exhaustive-deps

  async function snapshot() {
    setBusy(true)
    try { await api.snapshotNote(noteId); await reload(); toast('已存一版') }
    catch (e) { toast('存版失败：' + e, 'error') }
    finally { setBusy(false) }
  }
  async function view(r: api.NoteRevision) {
    if (open?.id === r.id) { setOpen(null); return }
    try { setOpen(await api.getRevision(noteId, r.id)) } catch (e) { toast('读不到这一版：' + e, 'error') }
  }
  async function restore(r: api.NoteRevision) {
    setBusy(true)
    try {
      const n = await api.restoreRevision(noteId, r.id)
      onRestored(n); setOpen(null); await reload()
      toast('已恢复到 ' + when(r.created_at) + ' 的版本（恢复前的内容也留了一版）')
    } catch (e) { toast('恢复失败：' + e, 'error') }
    finally { setBusy(false) }
  }

  if (!revs) return <p className="muted" style={{ margin: 0 }}>…</p>
  return (
    <div className="stack" style={{ fontSize: 13, gap: 8 }}>
      <div className="row" style={{ gap: 8, alignItems: 'center' }}>
        <span className="muted" style={{ fontSize: 12 }}>
          {revs.length === 0 ? '还没有历史版本——正文改动后每隔十分钟自动留一版。' : `${revs.length} 个版本 · 当前 ${currentChars} 字`}
        </span>
        <span style={{ flex: 1 }} />
        <button className="chip" disabled={busy} onClick={snapshot}><i className="bx bx-bookmark-plus" /> 现在存一版</button>
      </div>
      {revs.length > 0 && (
        <div className="revision-list">
          {revs.map((r) => (
            <div key={r.id} className={'revision-row' + (open?.id === r.id ? ' open' : '')}>
              <a className="kb-link" onClick={() => void view(r)}>
                <i className={'bx ' + (open?.id === r.id ? 'bx-chevron-down' : 'bx-chevron-right')} />
                <span>{when(r.created_at)}</span>
                <span className="muted" style={{ fontSize: 11 }}>{REASON[r.reason] ?? r.reason} · {r.chars} 字
                  {r.chars !== currentChars && <> · {r.chars > currentChars ? '+' : ''}{r.chars - currentChars}</>}</span>
                <span style={{ flex: 1 }} />
                <button className="chip" disabled={busy} onClick={(e) => { e.stopPropagation(); void restore(r) }}><i className="bx bx-undo" /> 恢复到这一版</button>
              </a>
              {open?.id === r.id && (
                <div className="revision-body">
                  <MarkdownEditor content={open.content} readOnly />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
