import { useEffect, useState } from 'react'

import { kbEntity, type KbEntityPage } from '../../api'
import { Chip, FactList, KbSection, MiniBars, Pager, type KbActions } from './KbBits'

export default function EntityPage({ code, actions }: { code: string; actions: KbActions }) {
  const [p, setP] = useState<KbEntityPage | null | undefined>(undefined)
  const [offset, setOffset] = useState(0)
  useEffect(() => { setOffset(0) }, [code])
  useEffect(() => {
    let alive = true
    kbEntity(code, 50, offset).then((d) => { if (alive) setP(d) }).catch(() => { if (alive) setP(null) })
    return () => { alive = false }
  }, [code, offset])
  if (p === undefined) return <p className="muted"><span className="spinner" /> 加载中…</p>
  if (p === null) return <p className="muted">没有这个实体：{code}</p>
  return (
    <div className="kb-page">
      <div className="kb-head">
        <div className="kb-crumbs muted"><a href="#" onClick={(e) => { e.preventDefault(); actions.onOpen('kb:entities') }}>实体</a></div>
        <h2 className="kb-note-title"><i className="bx bx-user muted" /> {p.name}</h2>
        <div className="muted" style={{ fontSize: 13 }}>
          {p.facts_total} 条事实{p.type ? ' · ' + p.type : ''}{p.aliases.length ? ' · 别名：' + p.aliases.join('、') : ''}
        </div>
      </div>
      {p.relations.length > 0 && (
        <KbSection title="关系">
          <div className="chip-wrap">
            {p.relations.map((r, i) => (
              <Chip key={i} icon="bx-right-arrow-alt" onClick={() => actions.onOpen('kb:entity:' + r.target)}>{r.rel} → {r.target_name}</Chip>
            ))}
          </div>
        </KbSection>
      )}
      {p.months.length > 1 && <KbSection title="按月"><MiniBars data={p.months} /></KbSection>}
      {p.topics.length > 0 && (
        <KbSection title="相关主题">
          <div className="chip-wrap">{p.topics.map((t) => <Chip key={t.code} icon="bx-hash" count={t.facts} onClick={() => actions.onOpen('kb:topic:' + t.code)}>{t.code}</Chip>)}</div>
        </KbSection>
      )}
      <KbSection title="事实">
        <FactList facts={p.facts} actions={actions} />
        <Pager total={p.facts_total} limit={p.limit} offset={p.offset} onPage={setOffset} />
      </KbSection>
    </div>
  )
}
