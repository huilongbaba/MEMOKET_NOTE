/** 知识库首页：搜索在第一屏，然后是数字、近 12 个月、主题 Top、实体 Top、最近摄入。 */
import { useEffect, useState } from 'react'

import { kbDashboard, recall, type Fact, type FactDetail, type KbDashboard as Data } from '../../api'
import { Chip, FactList, KbSection, MiniBars, StatTile, type KbActions } from './KbBits'

const toDetail = (f: Fact): FactDetail => ({ id: f.id, text: f.text, when: f.when, kind: f.kind, who: '', conf: '', topics: [], entities: [], unit: '' })

export default function KbDashboard({ actions }: { actions: KbActions }) {
  const [data, setData] = useState<Data | null>(null)
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<{ facts: FactDetail[]; took: number; terms: string[] } | null>(null)
  const [searching, setSearching] = useState(false)

  useEffect(() => { kbDashboard().then(setData).catch(() => setData(null)) }, [])

  // 即搜即显：零 LLM 的符号检索，毫秒级
  useEffect(() => {
    if (!q.trim()) { setHits(null); return }
    setSearching(true)
    const t = setTimeout(() => {
      recall(q, 20).then((r) => setHits({ facts: r.facts.map(toDetail), took: r.took_ms, terms: r.terms }))
        .catch(() => setHits({ facts: [], took: 0, terms: [] })).finally(() => setSearching(false))
    }, 250)
    return () => clearTimeout(t)
  }, [q])

  return (
    <div className="kb-page">
      <div className="kb-search">
        <i className="bx bx-search" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜知识库：人、事、数字、日期…"
               autoFocus onKeyDown={(e) => { if (e.key === 'Escape') setQ('') }} />
        {searching && <span className="spinner" />}
        {q && <button className="icon-btn" onClick={() => setQ('')}><i className="bx bx-x" /></button>}
      </div>

      {hits ? (
        <KbSection title={`${hits.facts.length} 条结果`}
                   extra={<span className="muted" style={{ fontSize: 12 }}>{hits.took} ms{hits.terms.length ? ' · 命中词：' + hits.terms.slice(0, 6).join('、') : ''}</span>}>
          <FactList facts={hits.facts} actions={actions} />
          {hits.facts.length === 0 && <p className="muted" style={{ fontSize: 12 }}>换个说法，或者到「事实表」按主题 / 实体筛。</p>}
        </KbSection>
      ) : !data ? (
        <p className="muted"><span className="spinner" /> 加载中…</p>
      ) : (
        <>
          <div className="stat-row">
            <StatTile value={data.stats.facts.toLocaleString()} label="条事实" />
            <StatTile value={data.stats.topics} label="个主题" />
            <StatTile value={data.stats.entities.toLocaleString()} label="个实体" />
            <StatTile value={data.stats.units.toLocaleString()} label="场会议" />
            <StatTile value={<span style={{ fontSize: 15 }}>{data.stats.start_date ? `${data.stats.start_date.slice(0, 7)} → ${data.stats.end_date.slice(0, 7)}` : '—'}</span>} label="跨度（按事实里的日期）" />
          </div>

          <KbSection title="近 12 个月（按事实里的日期，计划里的未来日期也算）" extra={<a href="#" className="muted" style={{ fontSize: 12 }} onClick={(e) => { e.preventDefault(); actions.onOpen('kb:timeline') }}>全部时间线 →</a>}>
            <MiniBars data={data.months} />
          </KbSection>

          <div className="kb-two-col">
            <KbSection title="主题" extra={<a href="#" className="muted" style={{ fontSize: 12 }} onClick={(e) => { e.preventDefault(); actions.onOpen('kb:topics') }}>全部 →</a>}>
              <div className="chip-wrap">
                {data.top_topics.map((t) => (
                  <Chip key={t.code} icon="bx-hash" count={t.facts} onClick={() => actions.onOpen('kb:topic:' + t.code)}
                        title={t.children ? `${t.children} 个子主题` : undefined}>{t.code}</Chip>
                ))}
              </div>
            </KbSection>
            <KbSection title="实体" extra={<a href="#" className="muted" style={{ fontSize: 12 }} onClick={(e) => { e.preventDefault(); actions.onOpen('kb:entities') }}>全部 →</a>}>
              <div className="chip-wrap">
                {data.top_entities.map((t) => (
                  <Chip key={t.code} icon="bx-user" count={t.facts} onClick={() => actions.onOpen('kb:entity:' + t.code)}>{t.name}</Chip>
                ))}
              </div>
            </KbSection>
          </div>

          <div className="kb-two-col">
            <KbSection title="最近摄入" extra={<a href="#" className="muted" style={{ fontSize: 12 }} onClick={(e) => { e.preventDefault(); actions.onOpen('kb:recent') }}>全部 →</a>}>
              <div className="stack" style={{ gap: 4 }}>
                {data.recent_units.map((u) => (
                  <a key={u.id} href="#" className="kb-link" onClick={(e) => { e.preventDefault(); actions.onOpen('kb:unit:' + u.id) }}>
                    <i className="bx bx-conversation muted" /> <span className="muted">{u.date}</span> {u.title || u.id}
                    <span className="muted" style={{ marginInlineStart: 'auto' }}>{u.facts} 条</span>
                  </a>
                ))}
              </div>
            </KbSection>
            <KbSection title="类型 · 说话人">
              <div className="chip-wrap">
                {data.kinds.map((k) => <Chip key={k.kind} count={k.facts} onClick={() => actions.onOpen('kb:facts?kind=' + k.kind)}>{k.kind}</Chip>)}
              </div>
              <div className="chip-wrap" style={{ marginTop: 6 }}>
                {data.speakers.map((s) => <Chip key={s.who} icon="bx-user-voice" count={s.facts} onClick={() => actions.onOpen('kb:facts?who=' + s.who)}>{s.who}</Chip>)}
              </div>
            </KbSection>
          </div>

          <div className="chip-wrap" style={{ marginTop: 4 }}>
            <Chip icon="bx-table" onClick={() => actions.onOpen('kb:facts')}>事实表</Chip>
            <Chip icon="bx-network-chart" onClick={() => actions.onOpen('kb:graph')}>主题地图</Chip>
            <Chip icon="bx-history" onClick={() => actions.onOpen('kb:digest')}>定期回顾</Chip>
          </div>
        </>
      )}
    </div>
  )
}
