/** 冲突收件箱（docs/agent-native-editor.md §3.3.1）：摄入时检出的「新事实 vs 旧事实」，
 *  用户点一下「新的取代旧的」/「旧的算数」/「两条都留」，不是静默入库。 */
import { useEffect, useState } from 'react'

import { kbConflicts, resolveConflict, type KbConflict } from '../../api'
import { toast } from '../../toast'
import { KbSection, type KbActions } from './KbBits'

export default function ConflictInbox({ actions, onCount }: { actions: KbActions; onCount?: (n: number) => void }) {
  const [rows, setRows] = useState<KbConflict[] | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const load = () => kbConflicts().then((r) => { setRows(r.conflicts); onCount?.(r.open) }).catch(() => setRows([]))
  useEffect(() => { void load() }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  async function act(c: KbConflict, action: 'new_wins' | 'old_wins' | 'keep_both') {
    setBusy(c.id)
    try {
      await resolveConflict(c.id, action)
      toast(action === 'new_wins' ? '新的取代旧的' : action === 'old_wins' ? '旧的算数，新的标成被取代' : '两条都留着')
      await load()
    } catch (e) { toast(String(e), 'error') }
    finally { setBusy(null) }
  }
  if (!rows || rows.length === 0) return null
  const Side = ({ f, label }: { f: KbConflict['new']; label: string }) => (
    <div>
      <div className="muted" style={{ fontSize: 11 }}>{label} · {f.when || '—'}{f.note_id ? <> · <a href="#" onClick={(e) => { e.preventDefault(); actions.onOpenNote(f.note_id) }}>来自笔记</a></> : null}</div>
      <div style={{ cursor: 'pointer' }} onClick={() => actions.onOpen('kb:fact:' + f.id)} title="打开这条">{f.text}</div>
    </div>
  )
  return (
    <KbSection title={`待处理冲突 · ${rows.length}`} extra={<span className="muted" style={{ fontSize: 12 }}>摄入时新记录跟旧记录撞上的，点一下定谁算数</span>}>
      <div className="stack conflict-inbox" style={{ gap: 6 }}>
        {rows.slice(0, 20).map((c) => (
          <div key={c.id} className="card" style={{ padding: '8px 10px' }}>
            <div style={{ fontSize: 13 }}><i className="bx bx-error" style={{ color: 'var(--warn)' }} /> {c.say}</div>
            <div className="cf-side">
              <Side f={c.old} label="旧记录" />
              <Side f={c.new} label="新记录" />
            </div>
            <div className="row" style={{ gap: 4, marginTop: 6 }}>
              <button style={{ fontSize: 12, padding: '2px 8px' }} disabled={busy === c.id} onClick={() => void act(c, 'new_wins')}>新的取代旧的</button>
              <button style={{ fontSize: 12, padding: '2px 8px' }} disabled={busy === c.id} onClick={() => void act(c, 'old_wins')}>旧的算数</button>
              <button style={{ fontSize: 12, padding: '2px 8px' }} disabled={busy === c.id} onClick={() => void act(c, 'keep_both')}>两条都留</button>
            </div>
          </div>
        ))}
      </div>
    </KbSection>
  )
}
