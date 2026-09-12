import { useEffect, useMemo, useRef, useState } from 'react'
import { useIngestActive } from '../util/ingestActive'
import {
  createTopic, factSources, listClusters, memoryEntities, memoryFacts, memoryStats,
  memoryTimeline, memoryTopics, topicEntityLinks,
} from '../api'
import type {
  EntityNode, FactDetail, FactsFilter, MemoryStats, SourceLine, TimelineBucket, TopicCluster,
  TopicEntityLink, TopicNode,
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
export default function MemoryBrowser({ onClose, embedded = false, initialTab = 'overview' }: {
  onClose?: () => void
  /** 内嵌进中栏（知识库虚拟节点打开时），不要弹层外壳、不要关闭按钮 */
  embedded?: boolean
  initialTab?: Tab
}) {
  const [tab, setTab] = useState<Tab>(initialTab)
  // 只在摄入任务跑着的时候轮询（util/ingestActive.ts）——之前三个 3 秒定时器常开
  const live = useIngestActive()
  const [showCreate, setShowCreate] = useState(false)
  // 内嵌进中栏时图随容器宽——写死 900 在窄栏里会横向溢出、在宽屏上又留一大块白
  const graphHost = useRef<HTMLDivElement>(null)
  const [graphW, setGraphW] = useState(900)
  useEffect(() => {
    const el = graphHost.current
    if (!el || !embedded) return
    const ro = new ResizeObserver(() => setGraphW(Math.max(320, Math.floor(el.clientWidth))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [embedded, tab])
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
  // 主题地图默认就要用满窗口——.modal 960px 的宽度封顶在节点一多的时候完全
  // 不够看，之前靠一个"全屏"按钮补，但那是要求用户先看一遍挤成一团的图再
  // 手动展开；这次改成默认状态本身就取消宽度封顶（见下面渲染部分）。
  const [graphSize, setGraphSize] = useState({ w: window.innerWidth - 80, h: window.innerHeight - 200 })
  useEffect(() => {
    function onResize() { setGraphSize({ w: window.innerWidth - 80, h: window.innerHeight - 200 }) }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  const [showEntities, setShowEntities] = useState(true)

  // 主题地图默认看**簇**，不是全部主题。196 个节点不是一张图，实测的代价是
  // 没人看得出自己知识库的形状。点开一个簇再看它里面的主题（见 kb-architecture
  // 6.4「聚合视图作为默认，全量图作为下钻」）。
  const [clusters, setClusters] = useState<TopicCluster[]>([])
  const [drilled, setDrilled] = useState<string | null>(null)
  useEffect(() => { listClusters().then((r) => setClusters(r.clusters)).catch(() => {}) }, [])

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
    if (!live) return
    const timer = setInterval(fetchAll, 3000)
    return () => clearInterval(timer)
  }, [tab, live])

  useEffect(() => {
    if (tab !== 'timeline') return
    const fetchTimeline = () => memoryTimeline().then((r) => setTimeline(r.buckets)).catch(() => {})
    fetchTimeline()
    if (!live) return
    const timer = setInterval(fetchTimeline, 3000)
    return () => clearInterval(timer)
  }, [tab, live])

  // 事实是分块抽取的，入库任务跑在后台的时候新 fact 会不断往库里落——这里
  // 开着事实表就跟着轮询，边抽边多地刷出来，不用手动切一下筛选才能看到最新
  // 的。第一次拉带 loading 转圈，轮询这几次不带，不然每 3 秒闪一下。
  useEffect(() => {
    if (tab !== 'facts') return
    setLoading(true)
    memoryFacts(factsFilter)
      .then((r) => { setFacts(r.facts); setFactsTotal(r.total) })
      .finally(() => setLoading(false))

    if (!live) return
    const timer = setInterval(() => {
      memoryFacts(factsFilter).then((r) => { setFacts(r.facts); setFactsTotal(r.total) }).catch(() => {})
    }, 3000)
    return () => clearInterval(timer)
  }, [tab, factsFilter, live])

  // 大语料下抽取会把 ASR 噪声碎片（单/双字母缩写、纯数字、0 引用的孤儿实体）
  // 一起当实体提出来——实测 terrence 语料到 1864 个实体时，95% type 为空，
  // 里面混了不少"bb"/"bba"/"100美元"这类噪声。抽取本身的锅（模型在脏转写文本
  // 上的已知短板，跟 kite-constraints.md #10/#11 是同一类问题），这里只做
  // 展示层兜底：默认过滤掉零引用和过短的噪声节点，可关掉看全量。
  const [hideNoiseEntities, setHideNoiseEntities] = useState(true)
  const cleanEntities = useMemo(() => {
    if (!hideNoiseEntities) return entities
    return entities.filter((e) => e.fact_count > 0
      && e.code.replace(/[^a-zA-Z0-9一-龥]/g, '').length > 1)
  }, [entities, hideNoiseEntities])
  const cleanEntityCodes = useMemo(() => new Set(cleanEntities.map((e) => e.code)), [cleanEntities])
  const cleanLinks = useMemo(
    () => (hideNoiseEntities ? links.filter((l) => cleanEntityCodes.has(l.entity)) : links),
    [links, cleanEntityCodes, hideNoiseEntities],
  )

  // 主题多了以后图会很挤，按层级过滤只留一级/二级/三级根及其祖先链——不是
  // 简单按 depth 相等筛，那样会把中间层的连线也切断，看不出层级关系了。
  const depths = useMemo(() => topicDepths(topics), [topics])
  const visibleTopics = useMemo(
    () => (maxLevel === null ? topics : topics.filter((t) => (depths.get(t.code) ?? 0) < maxLevel)),
    [topics, depths, maxLevel],
  )
  const visibleTopicCodes = useMemo(() => new Set(visibleTopics.map((t) => t.code)), [visibleTopics])
  const levelFilteredLinks = useMemo(
    () => (maxLevel === null ? cleanLinks : cleanLinks.filter((l) => visibleTopicCodes.has(l.topic))),
    [cleanLinks, visibleTopicCodes, maxLevel],
  )
  // 实体本身没有"层级"概念——过滤只影响跟主题层级挂钩的那部分：一个实体如果
  // 曾经跟任何主题共现过，就只在它共现的主题还可见时才继续显示；从来没跟
  // 任何主题共现过的实体（图上本来就是孤立节点）不受层级筛选影响。
  const entityCodesWithAnyTopicLink = useMemo(() => new Set(cleanLinks.map((l) => l.entity)), [cleanLinks])
  const levelFilteredEntities = useMemo(() => {
    if (maxLevel === null) return cleanEntities
    const stillLinkedCodes = new Set(levelFilteredLinks.map((l) => l.entity))
    return cleanEntities.filter((e) => !entityCodesWithAnyTopicLink.has(e.code) || stillLinkedCodes.has(e.code))
  }, [cleanEntities, levelFilteredLinks, entityCodesWithAnyTopicLink, maxLevel])
  const visibleEntities = useMemo(() => (showEntities ? levelFilteredEntities : []), [showEntities, levelFilteredEntities])
  const visibleLinks = useMemo(() => (showEntities ? levelFilteredLinks : []), [showEntities, levelFilteredLinks])

  // 主题地图会随语料量涨到几百上千个节点（见调研：Capacities 用"每个节点的
  // 局部图"缓解这个问题，我们暂时用最简单的按名字搜索代替——按层级过滤是
  // 控制"看多深"，这里是直接"找到那一个"。
  const [nodeQuery, setNodeQuery] = useState('')
  // 簇视图：把每个簇画成一个节点。KnowledgeGraph 一个字都不用改——一个簇
  // 就是一个没有父节点的主题，`fact_count` 是它里面所有事实。
  // 簇之间的边：两个簇共享的实体越多越相关。每个簇取最强的两个邻居，画成虚线
  // ——没有边的簇视图只是一堆散点，看不出「什么跟什么挨着」（实拍反馈）。
  const clusterEdges = useMemo<{ a: string; b: string }[]>(() => {
    const topicCluster = new Map<string, string>()
    for (const c of clusters) for (const tp of c.topics) topicCluster.set(tp, c.key)
    const entClusters = new Map<string, Map<string, number>>()
    for (const l of links) {
      const ck = topicCluster.get(l.topic)
      if (!ck) continue
      const m = entClusters.get(l.entity) ?? new Map<string, number>()
      m.set(ck, (m.get(ck) ?? 0) + l.weight)
      entClusters.set(l.entity, m)
    }
    const pair = new Map<string, number>()
    for (const m of entClusters.values()) {
      const ks = [...m.keys()]
      for (let i = 0; i < ks.length; i++) for (let j = i + 1; j < ks.length; j++) {
        const k = ks[i] < ks[j] ? ks[i] + '\u0000' + ks[j] : ks[j] + '\u0000' + ks[i]
        pair.set(k, (pair.get(k) ?? 0) + Math.min(m.get(ks[i])!, m.get(ks[j])!))
      }
    }
    const best = new Map<string, { key: string; w: number }[]>()
    for (const [k, w] of pair) {
      const [a, b] = k.split('\u0000')
      best.set(a, [...(best.get(a) ?? []), { key: b, w }])
      best.set(b, [...(best.get(b) ?? []), { key: a, w }])
    }
    const out = new Set<string>()
    for (const [a, list] of best) for (const n of list.sort((x, y) => y.w - x.w).slice(0, 2)) out.add(a < n.key ? a + '\u0000' + n.key : n.key + '\u0000' + a)
    return [...out].map((k) => { const [a, b] = k.split('\u0000'); return { a, b } })
  }, [clusters, links])
  const clusterNodes = useMemo<TopicNode[]>(() => clusters.map((c) => ({
    code: c.key, parents: [], status: c.merged ? 'candidate' : 'canonical',
    aliases: c.topics, fact_count: c.facts,
  })), [clusters])

  // 下钻：只看这一簇里的主题。
  const scopedTopics = useMemo(() => {
    if (!drilled) return visibleTopics
    const inside = new Set(clusters.find((c) => c.key === drilled)?.topics ?? [])
    return visibleTopics.filter((t) => inside.has(t.code))
  }, [visibleTopics, drilled, clusters])

  const searchedTopics = useMemo(() => {
    const q = nodeQuery.trim().toLowerCase()
    if (!q) return scopedTopics
    return scopedTopics.filter((t) =>
      t.code.toLowerCase().includes(q) || t.aliases.some((a) => a.toLowerCase().includes(q)))
  }, [scopedTopics, nodeQuery])
  const searchedEntities = useMemo(() => {
    const q = nodeQuery.trim().toLowerCase()
    if (!q) return visibleEntities
    return visibleEntities.filter((e) =>
      e.name.toLowerCase().includes(q) || e.code.toLowerCase().includes(q)
      || e.aliases.some((a) => a.toLowerCase().includes(q)))
  }, [visibleEntities, nodeQuery])
  const drilledEntityCodes = useMemo(() => {
    if (!drilled) return null
    const topicCodes = new Set(scopedTopics.map((t) => t.code))
    return new Set(visibleLinks.filter((l) => topicCodes.has(l.topic)).map((l) => l.entity))
  }, [drilled, scopedTopics, visibleLinks])
  const searchedLinks = useMemo(() => {
    const topicCodes = new Set(searchedTopics.map((t) => t.code))
    const entityCodes = new Set(searchedEntities.map((e) => e.code))
    if (!nodeQuery.trim() && !drilled) return visibleLinks
    return visibleLinks.filter((l) => topicCodes.has(l.topic) && entityCodes.has(l.entity))
  }, [visibleLinks, nodeQuery, drilled, searchedTopics, searchedEntities])

  // 簇视图下不画实体：一个簇跟一个实体共现说明不了什么，簇本来就是好几个
  // 主题合起来的，几乎每个簇都会碰上每个常见实体。
  const graphTopics = drilled === null && clusters.length ? clusterNodes : searchedTopics
  const graphEntities = drilled === null && clusters.length
    ? []
    : (drilledEntityCodes ? searchedEntities.filter((e) => drilledEntityCodes.has(e.code)) : searchedEntities)
  const graphLinks = drilled === null && clusters.length ? [] : searchedLinks

  // 内嵌在中栏时，点一个主题/实体 = 打开它的页面（树上的节点），不是切到
  // 这个组件自己那个已经藏起来的「事实表」tab。
  function filterByTopic(code: string) {
    if (embedded) { window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb:topic:' + code })); return }
    setFactsFilter({ topic: code, limit: PAGE_SIZE, offset: 0 })
    setTab('facts')
  }

  function filterByEntity(code: string) {
    if (embedded) { window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb:entity:' + code })); return }
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
    if (embedded || !onClose) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, embedded])

  // **不要把外壳写成 render 里定义的组件**：每次 render 都是新的组件类型，
  // 整棵子树（含力导向图）每 3 秒轮询一次就重挂一次——图自己跳、放大了缩回去、
  // 拖过的节点归位，全是这一个原因（client-log 抓到每 1.5s 一次 new simulation）。
  const body = (
    <>
        {!embedded && (
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <h2 style={{ margin: 0 }}>知识库</h2>
            <button onClick={onClose}>✕ 关闭</button>
          </div>
        )}

        {!embedded && <div className="row" style={{ margin: '10px 0' }}>
          {(['overview', 'topics', 'timeline', 'facts'] as Tab[]).map((t) => (
            <button
              key={t}
              className={tab === t ? 'primary' : ''}
              onClick={() => setTab(t)}
            >
              {{ overview: '概览', topics: '主题地图', timeline: '时间线', facts: '事实表' }[t]}
            </button>
          ))}
        </div>}

        {/* overview 是默认 tab，stats 请求没回来之前是 null——之前这里直接
           `stats &&` 短路，打开面板的第一瞬间内容区彻底空白，没有任何
           加载提示（跟 [11] 修的 RelatedMemory 是同一类问题：默认/首屏
           状态被短路成完全空白）。 */}
        {tab === 'overview' && !stats && <p className="muted"><span className="spinner" /> 加载中…</p>}
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
          <div className="stack">
            {showCreate && <div className="filter-row">
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
            </div>}

            {/* 工具栏：一行面包屑（全部簇 › 某簇），一行筛选。簇视图下层级筛选没意义，藏掉 */}
            {clusters.length > 0 && (
              <div className="filter-row" style={{ gap: 6 }}>
                <button className={'chip' + (drilled === null ? ' active' : '')} onClick={() => setDrilled(null)}>
                  <i className="bx bx-network-chart" />全部簇 <span className="chip-count">{clusters.length}</span>
                </button>
                {drilled !== null && (
                  <>
                    <i className="bx bx-chevron-right muted" />
                    <span className="chip active"><i className="bx bx-hash" />{clusters.find((c) => c.key === drilled)?.label ?? drilled}</span>
                    <span className="muted" style={{ fontSize: 12 }}>
                      {scopedTopics.length} 个主题 · {clusters.find((c) => c.key === drilled)?.facts ?? 0} 条事实
                    </span>
                  </>
                )}
                {drilled === null && (
                  <span className="muted" style={{ fontSize: 12 }}>
                    点一个簇进去看它的主题和实体。簇 = 老在同一场会议里一起出现的主题；虚线 = 两个簇共享的实体多。
                  </span>
                )}
              </div>
            )}

            <div className="filter-row">
              <div className="quick-search" style={{ minWidth: 200 }}>
                <i className="bx bx-search" />
                <input placeholder="找节点…" value={nodeQuery} onChange={(e) => setNodeQuery(e.target.value)} />
                {nodeQuery && <button className="icon-btn" onClick={() => setNodeQuery('')}><i className="bx bx-x" /></button>}
              </div>
              {(drilled !== null || clusters.length === 0) && (
                <>
                  <span className="muted" style={{ fontSize: 12 }}>层级</span>
                  <button className={'chip' + (maxLevel === null ? ' active' : '')} onClick={() => setMaxLevel(null)}>全部</button>
                  {Array.from({ length: Math.max(1, ...depths.values()) + 1 }, (_, i) => i + 1).map((lvl) => (
                    <button key={lvl} className={'chip' + (maxLevel === lvl ? ' active' : '')} onClick={() => setMaxLevel(lvl)}>
                      {'一二三四五六七八九十'[lvl - 1] ?? lvl}级
                    </button>
                  ))}
                  <button className={'chip' + (showEntities ? ' active' : '')} onClick={() => setShowEntities((v) => !v)} title="画不画实体节点">
                    <i className="bx bx-user" />实体
                  </button>
                  <button className={'chip' + (hideNoiseEntities ? ' active' : '')} onClick={() => setHideNoiseEntities((v) => !v)}
                          title="过滤零引用 / 过短的噪声实体（转写抽取常见的缩写碎片）">
                    <i className="bx bx-filter-alt" />滤噪声
                  </button>
                </>
              )}
              <button className="chip" onClick={() => setShowCreate((v) => !v)} title="手工加一个主题" style={{ marginInlineStart: 'auto' }}><i className="bx bx-plus" />新建主题</button>
            </div>

            <div ref={graphHost} />
            <KnowledgeGraph
              topics={graphTopics}
              entities={graphEntities}
              links={graphLinks}
              topicLinks={drilled === null && clusters.length ? clusterEdges : []}
              onSelect={(kind, code) => {
                if (kind !== 'topic') return filterByEntity(code)
                // 簇视图下点一个节点 = 下钻到它里面；已经在簇里了才是"看事实"
                if (drilled === null && clusters.some((c) => c.key === code)) {
                  setDrilled(code)
                  setNodeQuery('')
                  return
                }
                filterByTopic(code)
              }}
              width={embedded ? graphW : graphSize.w}
              height={embedded ? Math.max(520, Math.round(graphW * 0.72)) : graphSize.h}
            />
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
      </>
  )
  return embedded
    ? <div className="kb-browser">{body}</div>
    : <div className="modal-backdrop"><div className="modal" style={tab === 'topics' ? { maxWidth: 'calc(100vw - 48px)' } : undefined}>{body}</div></div>
}
