import { useEffect, useState } from 'react'
import * as api from '../api'
import { displayTitle } from '../util/displayTitle'
import { fmtDate } from '../util/time'

/** ribbon「链接」：这篇链出去的笔记 + 链进来的笔记。`[[` 打字即可插链接。 */
export default function NoteLinksPanel({ noteId, content, onOpen }: {
  noteId: string
  content: string
  onOpen: (noteId: string) => void
}) {
  const [links, setLinks] = useState<api.NoteLinks | null>(null)
  // 正文里链接的数量变了才重查——每个字都查一次没必要
  const outgoingKey = (content.match(/\]\(note:\/\/[0-9a-f]{12}\)/g) ?? []).join(',')
  useEffect(() => {
    let alive = true
    api.noteLinks(noteId).then((r) => { if (alive) setLinks(r) }).catch(() => { if (alive) setLinks({ outgoing: [], backlinks: [] }) })
    return () => { alive = false }
  }, [noteId, outgoingKey])
  if (!links) return <p className="muted" style={{ margin: 0 }}>…</p>
  const list = (rows: api.CitingNote[], empty: string) => rows.length === 0
    ? <p className="muted" style={{ margin: 0, fontSize: 12 }}>{empty}</p>
    : rows.map((n) => (
      <a key={n.id} className="kb-link" onClick={() => onOpen(n.id)}>
        <i className="bx bx-note" /> <span className="ellipsis">{displayTitle(n)}</span>
        <span className="muted" style={{ marginInlineStart: 'auto', fontSize: 11 }}>{fmtDate(n.updated_at)}</span>
      </a>
    ))
  return (
    <div className="row" style={{ gap: 24, alignItems: 'flex-start', fontSize: 13 }}>
      <section style={{ flex: 1, minWidth: 0 }}>
        <p className="muted palette-group" style={{ marginInline: 0 }}>链到的笔记 {links.outgoing.length > 0 && `· ${links.outgoing.length}`}</p>
        {list(links.outgoing, '正文里打 [[ 搜标题即可链接另一篇。')}
      </section>
      <section style={{ flex: 1, minWidth: 0 }}>
        <p className="muted palette-group" style={{ marginInline: 0 }}>链到这篇的 {links.backlinks.length > 0 && `· ${links.backlinks.length}`}</p>
        {list(links.backlinks, '还没有别的笔记链到这篇。')}
      </section>
    </div>
  )
}
