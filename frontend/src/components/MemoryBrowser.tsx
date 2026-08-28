import { useEffect, useState } from 'react'
import {
  factSources, memoryEntities, memoryFacts, memoryStats, memoryTimeline, memoryTopics,
} from '../api'
import type {
  EntityNode, FactDetail, FactsFilter, MemoryStats, SourceLine, TimelineBucket, TopicNode,
} from '../api'
import TopicDag from './TopicDag'

type Tab = 'overview' | 'topics' | 'timeline' | 'facts'

const PAGE_SIZE = 20

/**
 * 知识库可视化：概览 / 主题地图 / 时间线 / 事实表。
 * 证据回溯是重点——事实表展开一条就按需拉 /facts/{id}/sources，不在列表页
 * 就把每条的原文都查一遍。
 */
export default function MemoryBrowser({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>('overview')
  const [stats, setStats] = useState<MemoryStats | null>(null)
  const [topics, setTopics] = useState<TopicNode[]>([])
  const [entities, setEntities] = useState<EntityNode[]>([])
  const [timeline, setTimeline] = useState<TimelineBucket[]>([])
  const [factsFilter, setFactsFilter] = useState<FactsFilter>({ limit: PAGE_SIZE, offset: 0 })
  const [facts, setFacts] = useState<FactDetail[]>([])
  const [factsTotal, setFactsTotal] = useState(0)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [sources, setSources] = useState<SourceLine[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => { memoryStats().then(setStats).catch(() => {}) }, [])
  useEffect(() => {
    if (tab === 'topics' && topics.length === 0) memoryTopics().then(setTopics).catch(() => {})
    if (tab === 'topics' && entities.length === 0) memoryEntities().then(setEntities).catch(() => {})
    if (tab === 'timeline' && timeline.length === 0) memoryTimeline().then((r) => setTimeline(r.buckets)).catch(() => {})
  }, [tab])

  useEffect(() => {
    if (tab !== 'facts') return
    setLoading(true)
    memoryFacts(factsFilter)
      .then((r) => { setFacts(r.facts); setFactsTotal(r.total) })
      .finally(() => setLoading(false))
  }, [tab, factsFilter])

  function filterByTopic(code: string) {
    setFactsFilter({ topic: code, limit: PAGE_SIZE, offset: 0 })
    setTab('facts')
  }

  function filterByEntity(code: string) {
    setFactsFilter({ entity: code, limit: PAGE_SIZE, offset: 0 })
    setTab('facts')
  }

  async function toggleExpand(f: FactDetail) {
    if (expanded === f.id) { setExpanded(null); return }
    setExpanded(f.id)
    setSources(await factSources(f.id).catch(() => []))
  }

  const maxTimelineCount = Math.max(1, ...timeline.map((b) => Math.max(b.units, b.facts)))

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2 style={{ margin: 0 }}>知识库</h2>
          <button onClick={onClose}>✕ 关闭</button>
        </div>

        <div className="row" style={{ margin: '10px 0' }}>
          {(['overview', 'topics', 'timeline', 'facts'] as Tab[]).map((t) => (
            <button
              key={t}
              className={tab === t ? 'primary' : ''}
              onClick={() => setTab(t)}
            >
              {{ overview: '概览', topics: '主题地图', timeline: '时间线', facts: '事实表' }[t]}
            </button>
          ))}
        </div>

        {tab === 'overview' && stats && (
          <div className="card">
            <div className="row" style={{ gap: 20 }}>
              <div><strong>{stats.facts}</strong> <span className="muted">条事实</span></div>
              <div><strong>{stats.topics}</strong> <span className="muted">个主题</span></div>
              <div><strong>{stats.entities}</strong> <span className="muted">个实体</span></div>
              <div><strong>{stats.units}</strong> <span className="muted">个会话</span></div>
              <div><strong>{stats.lines}</strong> <span className="muted">条原文</span></div>
            </div>
            {stats.start_date && (
              <p className="muted" style={{ marginTop: 8 }}>
                记录跨度：{stats.start_date} ~ {stats.end_date}
              </p>
            )}
            {stats.speakers.length > 0 && (
              <p className="muted">说话人：{stats.speakers.join('、')}</p>
            )}
            <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>{stats.codebook}</p>
          </div>
        )}

        {tab === 'topics' && (
          <div>
            <TopicDag topics={topics} onSelect={filterByTopic} />

            {entities.length > 0 && (
              <>
                <h2>实体</h2>
                {entities.map((e) => (
                  <div className="card" key={e.code}>
                    <a className="link" onClick={() => filterByEntity(e.code)}>
                      {e.name || e.code}
                    </a>
                    {e.type && <span className="badge" style={{ marginLeft: 6 }}>{e.type}</span>}
                    {e.relations.length > 0 && (
                      <p className="muted" style={{ margin: '4px 0 0' }}>
                        {e.relations.map(([rel, other]) => `${rel} → ${other}`).join('；')}
                      </p>
                    )}
                  </div>
                ))}
              </>
            )}
          </div>
        )}

        {tab === 'timeline' && (
          <div>
            {timeline.length === 0 && <p className="muted">还没有记录。</p>}
            {timeline.map((b) => (
              <div key={b.date} className="row" style={{ marginBottom: 6 }}>
                <span className="muted" style={{ width: 90 }}>{b.date}</span>
                <div style={{ flex: 1, background: 'var(--panel)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{
                    width: `${(b.facts / maxTimelineCount) * 100}%`,
                    background: 'var(--accent)', height: 8,
                  }} />
                </div>
                <span className="muted" style={{ fontSize: 12 }}>
                  {b.units} 会话 · {b.facts} 事实
                </span>
              </div>
            ))}
          </div>
        )}

        {tab === 'facts' && (
          <div>
            <div className="row" style={{ marginBottom: 8, flexWrap: 'wrap' }}>
              <input
                placeholder="按 kind 过滤"
                value={factsFilter.kind ?? ''}
                onChange={(e) => setFactsFilter((f) => ({ ...f, kind: e.target.value, offset: 0 }))}
                style={{ width: 120 }}
              />
              <input
                placeholder="按 who 过滤"
                value={factsFilter.who ?? ''}
                onChange={(e) => setFactsFilter((f) => ({ ...f, who: e.target.value, offset: 0 }))}
                style={{ width: 120 }}
              />
              <select
                value={factsFilter.conf_min ?? ''}
                onChange={(e) => setFactsFilter((f) => ({ ...f, conf_min: e.target.value, offset: 0 }))}
              >
                <option value="">任意置信度</option>
                <option value="low">low 及以上</option>
                <option value="med">med 及以上</option>
                <option value="high">仅 high</option>
              </select>
              {(factsFilter.topic || factsFilter.entity) && (
                <span className="badge">
                  {factsFilter.topic ? `主题: ${factsFilter.topic}` : `实体: ${factsFilter.entity}`}
                  {' '}
                  <a className="link" onClick={() => setFactsFilter({ limit: PAGE_SIZE, offset: 0 })}>✕</a>
                </span>
              )}
            </div>

            {loading && <p className="muted"><span className="spinner" /> 加载中…</p>}
            {!loading && facts.length === 0 && <p className="muted">没有符合条件的事实。</p>}

            {facts.map((f) => (
              <div className="card" key={f.id}>
                <div onClick={() => toggleExpand(f)} style={{ cursor: 'pointer' }}>
                  {f.text}
                  <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>
                    {f.when} · {f.who} · {f.kind} · {f.conf}
                  </span>
                </div>
                {(f.topics.length > 0 || f.entities.length > 0) && (
                  <p className="muted" style={{ margin: '4px 0 0', fontSize: 12 }}>
                    {f.topics.map((t) => `#${t}`).join(' ')} {f.entities.map((e) => `@${e}`).join(' ')}
                  </p>
                )}
                {expanded === f.id && (
                  <div style={{ marginTop: 6, borderTop: '1px solid var(--line)', paddingTop: 6 }}>
                    {sources.length === 0
                      ? <p className="muted">没有找到原始出处。</p>
                      : sources.map((s) => (
                        <p key={s.id} className="muted" style={{ margin: '4px 0' }}>
                          出处（{s.date} · {s.who}）：{s.text}
                        </p>
                      ))}
                  </div>
                )}
              </div>
            ))}

            {factsTotal > PAGE_SIZE && (
              <div className="row" style={{ justifyContent: 'center', marginTop: 10 }}>
                <button
                  disabled={(factsFilter.offset ?? 0) === 0}
                  onClick={() => setFactsFilter((f) => ({ ...f, offset: Math.max(0, (f.offset ?? 0) - PAGE_SIZE) }))}
                >上一页</button>
                <span className="muted">
                  {(factsFilter.offset ?? 0) + 1}–{Math.min(factsTotal, (factsFilter.offset ?? 0) + PAGE_SIZE)} / {factsTotal}
                </span>
                <button
                  disabled={(factsFilter.offset ?? 0) + PAGE_SIZE >= factsTotal}
                  onClick={() => setFactsFilter((f) => ({ ...f, offset: (f.offset ?? 0) + PAGE_SIZE }))}
                >下一页</button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
