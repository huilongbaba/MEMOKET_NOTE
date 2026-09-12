import { useEffect, useState } from 'react'

import { kbUnit, type KbUnitPage } from '../../api'
import { Chip, FactList, KbSection, Pager, type KbActions, MissingPage } from './KbBits'

/** 一场会议（KITE 的 unit）：这场会抽出来的事实。 */
export default function UnitPage({ id, actions }: { id: string; actions: KbActions }) {
  const [p, setP] = useState<KbUnitPage | null | undefined>(undefined)
  const [offset, setOffset] = useState(0)
  useEffect(() => { setOffset(0) }, [id])
  useEffect(() => {
    let alive = true
    kbUnit(id, 50, offset).then((d) => {
      if (!alive) return
      setP(d)
      // 标签一开始只知道 id（note-674aa9a1b4b7-0 这种裸 id 挂在标签栏上，第 142 轮实拍）：页面拿到标题后改过去
      window.dispatchEvent(new CustomEvent('virtual-title', { detail: { id: 'kb:unit:' + id, title: d.title || '会议记录' } }))
    }).catch(() => { if (alive) setP(null) })
    return () => { alive = false }
  }, [id, offset])
  if (p === undefined) return <p className="muted"><span className="spinner" /> 加载中…</p>
  if (p === null) return <MissingPage what="会议" id={id} actions={actions} back="kb:recent" backLabel="回最近摄入" />
  return (
    <div className="kb-page">
      <div className="kb-head">
        <div className="kb-crumbs muted"><a href="#" onClick={(e) => { e.preventDefault(); actions.onOpen('kb:recent') }}>最近摄入</a></div>
        <h2 className="kb-note-title"><i className="bx bx-conversation muted" /> {p.title || p.id}</h2>
        <div className="muted" style={{ fontSize: 13 }}>{p.date} · {p.facts_total} 条事实{p.speakers.length ? ' · ' + p.speakers.join('、') : ''}</div>
      </div>
      {(p.topics.length > 0 || p.entities.length > 0) && (
        <KbSection title="这场会在说什么">
          <div className="chip-wrap">
            {p.topics.map((t) => <Chip key={t.code} icon="bx-hash" count={t.facts} onClick={() => actions.onOpen('kb:topic:' + t.code)}>{t.code}</Chip>)}
            {p.entities.map((e) => <Chip key={e.code} icon="bx-user" count={e.facts} onClick={() => actions.onOpen('kb:entity:' + e.code)}>{e.name}</Chip>)}
          </div>
        </KbSection>
      )}
      <KbSection title="事实">
        <FactList facts={p.facts} actions={actions} showTopics />
        <Pager total={p.facts_total} limit={p.limit} offset={p.offset} onPage={setOffset} />
      </KbSection>
    </div>
  )
}
