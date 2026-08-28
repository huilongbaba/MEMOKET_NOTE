import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  createTopic, factSources, memoryEntities, memoryFacts, memoryStats, memoryTimeline,
  memoryTopics, topicEntityLinks,
} from '../api'
import type {
  EntityNode, FactDetail, FactsFilter, MemoryStats, SourceLine, TimelineBucket, TopicEntityLink,
  TopicNode,
} from '../api'
import KnowledgeGraph from './KnowledgeGraph'

type Tab = 'overview' | 'topics' | 'timeline' | 'facts'

const PAGE_SIZE = 20

/** depth(root) = 0 -- "一级" in the UI means depth 0, "二级" depth <= 1, etc.
 * Same reachability-with-cycle-guard shape as closureFactCounts in
 * KnowledgeGraph, just walking parents instead of children. */
function topicDepths(topics: TopicNode[]): Map<string, number> {
  const byCode = new Map(topics.map((t) => [t.code, t]))
  const cache = new Map<string, number>()
  const visiting = new Set<string>()
  function depthOf(code: string): number {
    if (cache.has(code)) return cache.get(code)!
    if (visiting.has(code)) return 0
    visiting.add(code)
    const parents = (byCode.get(code)?.parents ?? []).filter((p) => byCode.has(p) && p !== code)
    const d = parents.length === 0 ? 0 : 1 + Math.max(...parents.map(depthOf))
    visiting.delete(code)
    cache.set(code, d)
    return d
  }
  const out = new Map<string, number>()
  for (const t of topics) out.set(t.code, depthOf(t.code))
  return out
}

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
  const [links, setLinks] = useState<TopicEntityLink[]>([])
  const [timeline, setTimeline] = useState<TimelineBucket[]>([])
  const [factsFilter, setFactsFilter] = useState<FactsFilter>({ limit: PAGE_SIZE, offset: 0 })
  const [facts, setFacts] = useState<FactDetail[]>([])
  const [factsTotal, setFactsTotal] = useState(0)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [sources, setSources] = useState<SourceLine[]>([])
  const [loading, setLoading] = useState(false)
  const [newTopicCode, setNewTopicCode] = useState('')
  const [newTopicParent, setNewTopicParent] = useState('')
  const [creatingTopic, setCreatingTopic] = useState(false)
  const [newTopicError, setNewTopicError] = useState('')
  const [maxLevel, setMaxLevel] = useState<number | null>(null)
  const [graphFullscreen, setGraphFullscreen] = useState(false)
  const [showEntities, setShowEntities] = useState(true)

  useEffect(() => { memoryStats().then(setStats).catch(() => {}) }, [])
  // 主题/实体/共现边同样是抽取时后台不断产出的，之前只在切进 tab 的时候拉
  // 一次（还带了 length===0 的门槛，切走再切回来都不会重新拉）——开着这个
  // tab 抽取新内容，图上永远不会长出新节点。改成跟事实表一样轮询。
  useEffect(() => {
    if (tab !== 'topics') return
    const fetchAll = () => {
      memoryTopics().then(setTopics).catch(() => {})
      memoryEntities().then(setEntities).catch(() => {})
      topicEntityLinks().then(setLinks).catch(() => {})
    }
    fetchAll()
    const timer = setInterval(fetchAll, 3000)
    return () => clearInterval(timer)
  }, [tab])

  useEffect(() => {
    if (tab !== 'timeline') return
    const fetchTimeline = () => memoryTimeline().then((r) => setTimeline(r.buckets)).catch(() => {})
    fetchTimeline()
    const timer = setInterval(fetchTimeline, 3000)
    return () => clearInterval(timer)
  }, [tab])

  // 事实是分块抽取的，入库任务跑在后台的时候新 fact 会不断往库里落——这里
  // 开着事实表就跟着轮询，边抽边多地刷出来，不用手动切一下筛选才能看到最新
  // 的。第一次拉带 loading 转圈，轮询这几次不带，不然每 3 秒闪一下。
  useEffect(() => {
    if (tab !== 'facts') return
    setLoading(true)
    memoryFacts(factsFilter)
      .then((r) => { setFacts(r.facts); setFactsTotal(r.total) })
      .finally(() => setLoading(false))

    const timer = setInterval(() => {
      memoryFacts(factsFilter).then((r) => { setFacts(r.facts); setFactsTotal(r.total) }).catch(() => {})
    }, 3000)
    return () => clearInterval(timer)
  }, [tab, factsFilter])

  // 主题多了以后图会很挤，按层级过滤只留一级/二级/三级根及其祖先链——不是
  // 简单按 depth 相等筛，那样会把中间层的连线也切断，看不出层级关系了。
  const depths = useMemo(() => topicDepths(topics), [topics])
  const visibleTopics = useMemo(
    () => (maxLevel === null ? topics : topics.filter((t) => (depths.get(t.code) ?? 0) < maxLevel)),
    [topics, depths, maxLevel],
  )
  const visibleTopicCodes = useMemo(() => new Set(visibleTopics.map((t) => t.code)), [visibleTopics])
  const levelFilteredLinks = useMemo(
    () => (maxLevel === null ? links : links.filter((l) => visibleTopicCodes.has(l.topic))),
    [links, visibleTopicCodes, maxLevel],
  )
  // 实体本身没有"层级"概念——过滤只影响跟主题层级挂钩的那部分：一个实体如果
  // 曾经跟任何主题共现过，就只在它共现的主题还可见时才继续显示；从来没跟
  // 任何主题共现过的实体（图上本来就是孤立节点）不受层级筛选影响。
  const entityCodesWithAnyTopicLink = useMemo(() => new Set(links.map((l) => l.entity)), [links])
  const levelFilteredEntities = useMemo(() => {
    if (maxLevel === null) return entities
    const stillLinkedCodes = new Set(levelFilteredLinks.map((l) => l.entity))
    return entities.filter((e) => !entityCodesWithAnyTopicLink.has(e.code) || stillLinkedCodes.has(e.code))
  }, [entities, levelFilteredLinks, entityCodesWithAnyTopicLink, maxLevel])
  const visibleEntities = useMemo(() => (showEntities ? levelFilteredEntities : []), [showEntities, levelFilteredEntities])
  const visibleLinks = useMemo(() => (showEntities ? levelFilteredLinks : []), [showEntities, levelFilteredLinks])

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

  async function submitNewTopic() {
    if (!newTopicCode.trim()) return
    setCreatingTopic(true)
    setNewTopicError('')
    try {
      const created = await createTopic(newTopicCode.trim(), newTopicParent)
      setTopics((prev) => [...prev, created])
      setNewTopicCode('')
      setNewTopicParent('')
    } catch (e) {
      setNewTopicError(String(e))
    } finally {
      setCreatingTopic(false)
    }
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
            <div className="row" style={{ marginBottom: 8, flexWrap: 'wrap' }}>
              <input
                placeholder="新主题名"
                value={newTopicCode}
                onChange={(e) => setNewTopicCode(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && submitNewTopic()}
                style={{ width: 160 }}
              />
              <select value={newTopicParent} onChange={(e) => setNewTopicParent(e.target.value)}>
                <option value="">（作为根主题）</option>
                {topics.map((t) => (
                  <option key={t.code} value={t.code}>{t.code}</option>
                ))}
              </select>
              <button onClick={submitNewTopic} disabled={!newTopicCode.trim() || creatingTopic}>
                {creatingTopic ? <span className="spinner" /> : '+ 新建主题'}
              </button>
              {newTopicError && <span className="muted" style={{ color: 'var(--del)' }}>{newTopicError}</span>}
            </div>

            <div className="row" style={{ marginBottom: 8, flexWrap: 'wrap', justifyContent: 'space-between' }}>
              <div className="row" style={{ flexWrap: 'wrap' }}>
                <span className="muted" style={{ fontSize: 12 }}>显示到：</span>
                <button className={maxLevel === null ? 'primary' : ''} onClick={() => setMaxLevel(null)}>全部</button>
                {Array.from({ length: Math.max(1, ...depths.values()) + 1 }, (_, i) => i + 1).map((lvl) => (
                  <button key={lvl} className={maxLevel === lvl ? 'primary' : ''} onClick={() => setMaxLevel(lvl)}>
                    {'一二三四五六七八九十'[lvl - 1] ?? lvl}级
                  </button>
                ))}
                <button className={showEntities ? '' : 'primary'} onClick={() => setShowEntities((v) => !v)}>
                  {showEntities ? '隐藏实体' : '不显示实体'}
                </button>
              </div>
              <button onClick={() => setGraphFullscreen(true)}>⛶ 全屏</button>
            </div>

            <KnowledgeGraph
              topics={visibleTopics}
              entities={visibleEntities}
              links={visibleLinks}
              onSelect={(kind, code) => (kind === 'topic' ? filterByTopic(code) : filterByEntity(code))}
            />

            {graphFullscreen && (
              <GraphFullscreenOverlay
                topics={visibleTopics}
                entities={visibleEntities}
                links={visibleLinks}
                onSelect={(kind, code) => {
                  setGraphFullscreen(false)
                  if (kind === 'topic') filterByTopic(code); else filterByEntity(code)
                }}
                onClose={() => setGraphFullscreen(false)}
              />
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
            {!loading && facts.length === 0 && (
              <p className="muted">
                {factsFilter.topic
                  ? `「${factsFilter.topic}」下面（含子主题）还没有事实——这是预置的分类，还没有内容归到这里。`
                  : factsFilter.entity
                    ? `「${factsFilter.entity}」还没有关联的事实。`
                    : '没有符合条件的事实。'}
              </p>
            )}

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

/** The graph's own modal is already full-screen, but its `.modal` wrapper
 * caps out at max-width:960px (styles.css) -- crowded once there are more
 * than a handful of nodes. This portals straight to document.body so the
 * canvas can actually use the full window instead of that 960px column, with
 * its own resize listener since it's the only thing that needs one. */
function GraphFullscreenOverlay(
  { topics, entities, links, onSelect, onClose }: {
    topics: TopicNode[]
    entities: EntityNode[]
    links: TopicEntityLink[]
    onSelect: (kind: 'topic' | 'entity', code: string) => void
    onClose: () => void
  },
) {
  const [size, setSize] = useState({ w: window.innerWidth - 40, h: window.innerHeight - 90 })

  useEffect(() => {
    const onResize = () => setSize({ w: window.innerWidth - 40, h: window.innerHeight - 90 })
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return createPortal(
    <div className="modal-backdrop" style={{ zIndex: 200 }}>
      <div style={{ padding: '10px 20px' }}>
        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
          <h2 style={{ margin: 0 }}>主题地图（全屏）</h2>
          <button onClick={onClose}>✕ 退出全屏</button>
        </div>
        <KnowledgeGraph
          topics={topics} entities={entities} links={links} onSelect={onSelect}
          width={size.w} height={size.h}
        />
      </div>
    </div>,
    document.body,
  )
}
