/** 最近删除：删掉的笔记 30 天内能找回（Trilium 的删除也是可撤销的）。5 秒撤销窗口过了之后，
 *  这里是唯一的后悔药。恢复 = id 不变、放回原位（父节点没了就挂到树根）、历史版本一起回来。 */
import { useEffect, useState } from 'react'

import { listTrash, purgeTrash, restoreTrash, type TrashItem } from '../api'
import { toast } from '../toast'
import { fmtDateTime } from '../util/time'

export default function TrashPanel({ onRestored }: { onRestored: (id: string) => void }) {
  const [items, setItems] = useState<TrashItem[] | null>(null)
  const [busy, setBusy] = useState('')
  const load = () => listTrash().then(setItems).catch(() => setItems([]))
  useEffect(() => { void load() }, [])

  async function restore(it: TrashItem) {
    setBusy(it.note_id)
    try {
      await restoreTrash(it.note_id)
      toast(`「${it.title || '未命名'}」已恢复`)
      window.dispatchEvent(new CustomEvent('notes-changed'))
      await load()
      onRestored(it.note_id)
    } catch (e) { toast('恢复失败：' + String(e), 'error') }
    finally { setBusy('') }
  }
  async function purge(it: TrashItem) {
    setBusy(it.note_id)
    try { await purgeTrash(it.note_id); await load() }
    catch (e) { toast(String(e), 'error') }
    finally { setBusy('') }
  }

  if (items === null) return <p className="muted"><span className="spinner" /> 加载中…</p>
  return (
    <div className="stack" style={{ gap: 8 }}>
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>删掉的笔记在这里留 30 天。恢复会放回原来的位置（上级也删了的话放到最外层），历史版本一起回来；「彻底删除」之后就真的没了。</p>
      {items.length === 0 && <p className="muted" style={{ fontSize: 13 }}>最近 30 天没有删过笔记。</p>}
      {items.map((it) => (
        <div key={it.note_id} className="card row" style={{ alignItems: 'center', gap: 10, padding: '8px 10px' }}>
          <i className="bx bx-trash muted" />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.title || '未命名'}</div>
            <div className="muted" style={{ fontSize: 11 }}>{fmtDateTime(it.deleted_at)} 删除 · {it.chars} 字</div>
          </div>
          <button style={{ fontSize: 12, padding: '2px 10px' }} disabled={busy === it.note_id} onClick={() => void restore(it)}>恢复</button>
          <button style={{ fontSize: 12, padding: '2px 10px' }} disabled={busy === it.note_id} title="真的删掉，不能再找回" onClick={() => void purge(it)}>彻底删除</button>
        </div>
      ))}
    </div>
  )
}
