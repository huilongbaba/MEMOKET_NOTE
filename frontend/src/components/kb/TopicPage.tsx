import { useEffect, useState } from 'react'

import { kbTopic, type KbTopicPage } from '../../api'
import { Chip, FactList, KbSection, MiniBars, Pager, type KbActions } from './KbBits'

export default function TopicPage({ code, actions }: { code: string; actions: KbActions }) {
  const [p, setP] = useState<KbTopicPage | null | undefined>(undefined)
  const [offset, setOffset] = useState(0)
  useEffect(() => { setOffset(0) }, [code])
  useEffect(() => {
    let alive = true
    kbTopic(code, 50, offset).then((d) => { if (alive) setP(d) }).catch(() => { if (alive) setP(null) })
    return () => { alive = false }
  }, [code, offset])
  if (p === undefined) return <p className="muted"><span className="spinner" /> 加载中…</p>
  if (p === null) return <p className="muted">没有这个主题：{code}</p>
  return (
    <div className="kb-page">
      <div className="kb-head">
        <div className="kb-crumbs muted">
          <a href="#" onClick={(e) => { e.preventDefault(); actions.onOpen('kb:topics') }}>主题</a>
          {p.parents.map((pp) => <span key={pp}> / <a href="#" onClick={(e) => { e.preventDefault(); actions.onOpen('kb:topic:' + pp) }}>{pp}</a></span>)}
        </div>
        <h2 className="kb-note-title"><i className="bx bx-hash muted" /> {p.code}</h2>
        <div className="muted" style={{ fontSize: 13 }}>
          {p.facts_total} 条事实{p.aliases.length ? ' · 别名：' + p.aliases.join('、') : ''}{p.status !== 'canonical' ? ' · ' + p.status : ''}
        </div>
      </div>
      {p.months.length > 1 && <KbSection title="按月"><MiniBars data={p.months} /></KbSection>}
      {p.children.length > 0 && (
        <KbSection title="子主题">
          <div className="chip-wrap">{p.children.map((c) => <Chip key={c.code} icon="bx-hash" count={c.facts} onClick={() => actions.onOpen('kb:topic:' + c.code)}>{c.code}</Chip>)}</div>
        </KbSection>
      )}
      {p.entities.length > 0 && (
        <KbSection title="常一起出现的实体">
          <div className="chip-wrap">{p.entities.map((e) => <Chip key={e.code} icon="bx-user" count={e.facts} onClick={() => actions.onOpen('kb:entity:' + e.code)}>{e.name}</Chip>)}</div>
        </KbSection>
      )}
      <KbSection title="事实" extra={<span className="muted" style={{ fontSize: 12 }}>含子主题 · 新的在前</span>}>
        <FactList facts={p.facts} actions={actions} />
        <Pager total={p.facts_total} limit={p.limit} offset={p.offset} onPage={setOffset} />
      </KbSection>
    </div>
  )
}
