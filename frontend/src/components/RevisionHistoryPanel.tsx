import { useEffect, useState } from 'react'
import { friendlyError } from '../util/friendlyError'
import * as api from '../api'
import { toast } from '../toast'
import MarkdownEditor from './MarkdownEditor'
import { diffParts } from '../editor/roundDiff'

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
export default function RevisionHistoryPanel({ noteId, currentChars, currentContent = '', onRestored }: {
  noteId: string
  currentChars: number
  /** 现在的正文：展开一版时默认给「与当前对比」（删了什么、加了什么），而不是只看旧版全文 */
  currentContent?: string
  onRestored: (n: api.Note) => void
}) {
  const [mode, setMode] = useState<'diff' | 'raw'>('diff')
  const [revs, setRevs] = useState<api.NoteRevision[] | null>(null)
  const [open, setOpen] = useState<(api.NoteRevision & { content: string }) | null>(null)
  const [busy, setBusy] = useState(false)

  const reload = () => api.listRevisions(noteId).then(setRevs).catch(() => setRevs([]))
  useEffect(() => { setOpen(null); void reload() }, [noteId])  // eslint-disable-line react-hooks/exhaustive-deps

  async function snapshot() {
    setBusy(true)
    try { await api.snapshotNote(noteId); await reload(); toast('已存一版') }
    catch (e) { toast('存版失败：' + friendlyError(e), 'error') }
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
    } catch (e) { toast('恢复失败：' + friendlyError(e), 'error') }
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
                  <div className="row" style={{ gap: 6, marginBottom: 6 }}>
                    <button className={'chip' + (mode === 'diff' ? ' active' : '')} onClick={() => setMode('diff')}>与当前对比</button>
                    <button className={'chip' + (mode === 'raw' ? ' active' : '')} onClick={() => setMode('raw')}>这一版全文</button>
                  </div>
                  {mode === 'raw'
                    ? <MarkdownEditor content={open.content} readOnly />
                    : <RevisionDiff from={open.content} to={currentContent} />}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


/** 旧版 → 当前 的词级 diff：红的是那一版有、现在没了的；绿的是现在新加的。
 *  同一套 diffParts（大文档先按行再逐词），跟编辑器里的轮次高亮是同一种语义。 */
function RevisionDiff({ from, to }: { from: string; to: string }) {
  const parts = diffParts(from, to)
  const changed = parts.filter((p) => p.type !== 'keep')
  if (changed.length === 0) return <p className="muted" style={{ margin: 0, fontSize: 12 }}>跟现在的正文一模一样（只差空白）。</p>
  // 没变的长段折起来（只留改动前后各 120 字的上下文）：改动往往在几千字的中间，
  // 全文摊开时第一屏看到的全是没变的（实拍）
  const CTX = 120
  return (
    <div className="revision-diff">
      {parts.map((p, i) => {
        if (p.type !== 'keep') return <span key={i} className={p.type === 'ins' ? 'rd-ins' : 'rd-del'}>{p.text}</span>
        if (p.text.length <= CTX * 2 + 40) return <span key={i}>{p.text}</span>
        const head = i === 0 ? '' : p.text.slice(0, CTX)
        const tail = i === parts.length - 1 ? '' : p.text.slice(-CTX)
        const hidden = p.text.length - head.length - tail.length
        return <span key={i}>{head}<span className="rd-skip">… 中间 {hidden} 字没变 …</span>{tail}</span>
      })}
    </div>
  )
}
