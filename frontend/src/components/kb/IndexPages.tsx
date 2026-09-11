/** 三个分类页：主题 / 实体 / 最近摄入。数据就是树上那些行——不再请求一次。 */
import { useMemo, useState } from 'react'

import type { TreeRow } from '../../api'
import { Chip, KbSection, type KbActions } from './KbBits'

export function TopicsIndex({ rows, actions }: { rows: TreeRow[]; actions: KbActions }) {
  const roots = rows.filter((r) => r.parent_note_id === 'kb:topics').sort((a, b) => b.fact_count - a.fact_count)
  const kids = (code: string) => rows.filter((r) => r.parent_note_id === 'kb:topic:' + code).sort((a, b) => b.fact_count - a.fact_count)
  return (
    <div className="kb-page">
      <div className="kb-head">
        <h2 className="kb-note-title"><i className="bx bx-hash muted" /> 主题</h2>
        <div className="muted" style={{ fontSize: 13 }}>{roots.length} 个一级主题。计数含子主题。</div>
      </div>
      <div className="topic-grid">
        {roots.map((t) => (
          <div key={t.id} className="topic-card">
            <a href="#" className="topic-card-title" onClick={(e) => { e.preventDefault(); actions.onOpen(t.note_id) }}>
              <i className="bx bx-hash muted" /> {t.title}<span className="muted" style={{ marginInlineStart: 'auto', fontSize: 12 }}>{t.fact_count}</span>
            </a>
            <div className="chip-wrap">
              {kids(t.title).slice(0, 8).map((k) => <Chip key={k.id} count={k.fact_count} onClick={() => actions.onOpen(k.note_id)}>{k.title}</Chip>)}
              {kids(t.title).length > 8 && <span className="muted" style={{ fontSize: 12 }}>…还有 {kids(t.title).length - 8} 个</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function EntitiesIndex({ rows, actions }: { rows: TreeRow[]; actions: KbActions }) {
  const [q, setQ] = useState('')
  const all = useMemo(() => rows.filter((r) => r.note_id.startsWith('kb:entity:')).sort((a, b) => b.fact_count - a.fact_count), [rows])
  const list = q ? all.filter((r) => (r.title + ' ' + r.preview).toLowerCase().includes(q.toLowerCase())) : all.slice(0, 200)
  return (
    <div className="kb-page">
      <div className="kb-head">
        <h2 className="kb-note-title"><i className="bx bx-group muted" /> 实体</h2>
        <div className="muted" style={{ fontSize: 13 }}>{all.length} 个。按事实数排序{!q && all.length > 200 ? '，先给前 200 个——搜一下能找到其余的' : ''}。</div>
      </div>
      <div className="kb-search">
        <i className="bx bx-search" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜实体名或别名…" />
      </div>
      <div className="chip-wrap">
        {list.map((e) => <Chip key={e.id} icon="bx-user" count={e.fact_count} onClick={() => actions.onOpen(e.note_id)} title={e.preview || undefined}>{e.title}</Chip>)}
      </div>
    </div>
  )
}

export function RecentIndex({ rows, actions }: { rows: TreeRow[]; actions: KbActions }) {
  const units = rows.filter((r) => r.parent_note_id === 'kb:recent').sort((a, b) => a.position - b.position)
  return (
    <div className="kb-page">
      <div className="kb-head">
        <h2 className="kb-note-title"><i className="bx bx-time-five muted" /> 最近摄入</h2>
        <div className="muted" style={{ fontSize: 13 }}>最近 {units.length} 场会议。点开看这场会抽出来的事实。</div>
      </div>
      <KbSection title="会议">
        <div className="stack" style={{ gap: 4 }}>
          {units.map((u) => (
            <a key={u.id} href="#" className="kb-link" onClick={(e) => { e.preventDefault(); actions.onOpen(u.note_id) }}>
              <i className="bx bx-conversation muted" /> {u.title}
              <span className="muted" style={{ marginInlineStart: 'auto' }}>{u.fact_count} 条</span>
            </a>
          ))}
        </div>
      </KbSection>
    </div>
  )
}
