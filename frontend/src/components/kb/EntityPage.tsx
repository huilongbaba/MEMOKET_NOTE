import { useEffect, useState } from 'react'

import { kbEntity, type KbEntityPage } from '../../api'
import { Chip, FactList, KbSection, MiniBars, Pager, type KbActions, MissingPage } from './KbBits'
import LocalGraph from './LocalGraph'

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
  if (p === null) return <MissingPage what="实体" id={code} actions={actions} back="kb:entities" backLabel="回实体列表" />
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
      {(p.topics.length > 0 || p.relations.length > 0) && (
        <KbSection title="周围有什么" extra={<span className="muted" style={{ fontSize: 12 }}>点节点进它的页面</span>}>
          <LocalGraph actions={actions}
            topics={p.topics.map((t) => ({ code: t.code, parents: [], status: 'canonical', aliases: [], fact_count: t.facts }))}
            entities={[
              { code: p.code, name: p.name, type: p.type, aliases: p.aliases, relations: p.relations.map((r) => [r.rel, r.target] as [string, string]), fact_count: p.facts_total },
              ...p.relations.map((r) => ({ code: r.target, name: r.target_name, type: '', aliases: [], relations: [], fact_count: 0 })),
            ]}
            links={p.topics.map((t) => ({ topic: t.code, entity: p.code, weight: t.facts }))} />
        </KbSection>
      )}
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
