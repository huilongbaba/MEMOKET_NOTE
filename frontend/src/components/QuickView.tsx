/**
 * 快速查看——不离开当前笔记看另一篇（Trilium 的 PopupEditor）。
 *
 * 判据 2 的直接落地：「为了看一条旧记录而离开当前页面 = 失败」。右栏的
 * 相关记忆解决了「浮现」，但点进去读全文以前只能开新标签、切走。这里是
 * 一个浮层：读完关掉，正文和光标都还在原地。
 */
import { useEffect } from 'react'

import type { Note } from '../api'
import { displayTitle } from '../util/displayTitle'
import MarkdownEditor from './MarkdownEditor'
import { fmtDate } from '../util/time'

export default function QuickView({ note, onClose, onOpen }: {
  note: Note
  onClose: () => void
  onOpen: (n: Note) => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal quick-view" onMouseDown={(e) => e.stopPropagation()}>
        <div className="row" style={{ alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <b style={{ flex: 1, fontSize: 16 }}>{displayTitle(note)}</b>
          <span className="muted" style={{ fontSize: 12 }}>{fmtDate(note.updated_at)}</span>
          <button onClick={() => { onClose(); onOpen(note) }}>在标签里打开</button>
          <button className="icon-btn" title="关闭（Esc）" onClick={onClose}>×</button>
        </div>
        <div className="quick-view-body">
          <MarkdownEditor content={note.content} readOnly />
        </div>
      </div>
    </div>
  )
}
