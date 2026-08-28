import { useEffect, useMemo, useRef } from 'react'
import { drag as d3drag } from 'd3-drag'
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from 'd3-force'
import { select as d3select } from 'd3-selection'
import type { EntityNode, TopicEntityLink, TopicNode } from '../api'

/**
 * One force-directed graph for topics AND entities together.
 *
 * These used to be two disconnected sections -- a topic DAG above a plain
 * entity list -- and there was no way to see how they related, because in
 * KITE's data model there IS no direct schema link between a topic and an
 * entity: each fact carries its own `topics` and `entities` arrays
 * independently, so the only real relationship is which topics and entities
 * keep showing up on the same facts. This draws that: topic<->entity edges
 * here are co-occurrence, aggregated server-side (topic_entity_links()) --
 * not a stored relation, a derived one. Entity<->entity edges ARE a stored
 * relation (Entity.rels), drawn the same way. Three edge kinds share one
 * graph: topic hierarchy (solid, arrowed), entity relations (solid, arrowed,
 * a different color), topic<->entity co-occurrence (dashed, unarrowed --
 * it's symmetric, "shown up together", not a direction).
 *
 * Topics render as circles, entities as squares, so the two node kinds stay
 * visually distinguishable inside one shared layout.
 */

type NodeKind = 'topic' | 'entity'

type GraphNode = {
  id: string
  kind: NodeKind
  code: string
  label: string
  factCount: number
  status: string
  aliases: string[]
  x?: number; y?: number; fx?: number | null; fy?: number | null
}
type GraphLink = { source: string; target: string; kind: 'hierarchy' | 'relation' | 'cooccur' }
type SimLink = { source: string | GraphNode; target: string | GraphNode; kind: GraphLink['kind'] }

const DEFAULT_WIDTH = 900
const DEFAULT_HEIGHT = 560
const MIN_R = 16
const R_SCALE = 6
// Labels can be wider than their shape (up to 12 chars at 12px), so the
// boundary clamp needs more headroom than the shape radius alone or a long
// label peeks past the canvas edge even though its shape is fully inside.
const LABEL_MARGIN = 30

function radiusOf(factCount: number): number {
  return MIN_R + Math.sqrt(factCount) * R_SCALE
}

/** All descendants of `code` (itself included), via the parents links -- a
 * plain reachability set, not `vocab.downset()`'s bounded/candidate-aware
 * version, but close enough for sizing a few dozen topic nodes. */
function descendantsOf(code: string, childrenOf: Map<string, string[]>): Set<string> {
  const seen = new Set<string>([code])
  const stack = [code]
  while (stack.length) {
    const cur = stack.pop()!
    for (const child of childrenOf.get(cur) ?? []) {
      if (!seen.has(child)) { seen.add(child); stack.push(child) }
    }
  }
  return seen
}

/** Topics: own fact_count is an exact-code match, so a root with all its
 * facts tagged onto specific children reads as empty even though clicking it
 * shows every one of those facts (facts_page() filters by descendant
 * closure, same as here). Sizing by closure instead makes a node's apparent
 * weight match what clicking it actually reveals. Computed as a proper
 * reachability SET (not summed per-branch) so a multi-parent topic doesn't
 * get double-counted under a shared ancestor. */
function closureFactCounts(topics: TopicNode[]): Map<string, number> {
  const childrenOf = new Map<string, string[]>()
  for (const t of topics) {
    for (const p of t.parents) {
      if (!childrenOf.has(p)) childrenOf.set(p, [])
      childrenOf.get(p)!.push(t.code)
    }
  }
  const byCode = new Map(topics.map((t) => [t.code, t]))
  const out = new Map<string, number>()
  for (const t of topics) {
    let total = 0
    for (const code of descendantsOf(t.code, childrenOf)) total += byCode.get(code)?.fact_count ?? 0
    out.set(t.code, total)
  }
  return out
}

export default function KnowledgeGraph(
  { topics, entities, links, onSelect, width = DEFAULT_WIDTH, height = DEFAULT_HEIGHT }: {
    topics: TopicNode[]
    entities: EntityNode[]
    links: TopicEntityLink[]
    onSelect: (kind: NodeKind, code: string) => void
    width?: number
    height?: number
  },
) {
  const nodeEls = useRef(new Map<string, SVGGElement>())
  const linkEls = useRef(new Map<number, SVGLineElement>())
  const simulationRef = useRef<ReturnType<typeof forceSimulation<GraphNode>> | null>(null)

  const closureCounts = useMemo(() => closureFactCounts(topics), [topics])

  const topicIds = useMemo(() => new Set(topics.map((t) => `topic:${t.code}`)), [topics])
  const entityIds = useMemo(() => new Set(entities.map((e) => `entity:${e.code}`)), [entities])

  const nodesKey = topics.map((t) => t.code).join(',') + '|' + entities.map((e) => e.code).join(',')

  // Keep one mutable node/link array across renders -- d3-force writes x/y/vx/vy
  // onto these objects in place, so recreating them every render would throw
  // away the simulation's progress.
  const nodes = useMemo<GraphNode[]>(() => [
    ...topics.map((t): GraphNode => ({
      id: `topic:${t.code}`, kind: 'topic', code: t.code, label: t.code,
      factCount: closureCounts.get(t.code) ?? t.fact_count, status: t.status, aliases: t.aliases,
    })),
    ...entities.map((e): GraphNode => ({
      id: `entity:${e.code}`, kind: 'entity', code: e.code, label: e.name || e.code,
      factCount: e.fact_count, status: 'canonical', aliases: e.aliases,
    })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [nodesKey])

  // Polling (see MemoryBrowser) hands this component a brand-new `links`
  // array reference every few seconds even when the co-occurrence pairs
  // haven't actually changed -- keying the memo on the array reference would
  // rebuild (and the effect below would then restart the whole simulation)
  // on every single poll tick. Key on content instead.
  const linksKey = links.map((l) => `${l.topic}>${l.entity}`).join(',')

  const graphLinks = useMemo<GraphLink[]>(() => {
    const topicParent: GraphLink[] = topics.flatMap((t) =>
      t.parents.filter((p) => topicIds.has(`topic:${p}`))
        .map((p) => ({ source: `topic:${p}`, target: `topic:${t.code}`, kind: 'hierarchy' as const })))
    const entityRel: GraphLink[] = entities.flatMap((e) =>
      e.relations.filter(([, other]) => entityIds.has(`entity:${other}`))
        .map(([, other]) => ({ source: `entity:${e.code}`, target: `entity:${other}`, kind: 'relation' as const })))
    const cooccur: GraphLink[] = links
      .filter((l) => topicIds.has(`topic:${l.topic}`) && entityIds.has(`entity:${l.entity}`))
      .map((l) => ({ source: `topic:${l.topic}`, target: `entity:${l.entity}`, kind: 'cooccur' as const }))
    return [...topicParent, ...entityRel, ...cooccur]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodesKey, linksKey])

  useEffect(() => {
    if (nodes.length === 0) return

    const simulation = forceSimulation<GraphNode>(nodes)
      .force('link', forceLink<GraphNode, SimLink>(graphLinks as SimLink[]).id((d) => d.id)
        .distance((l) => (l.kind === 'cooccur' ? 70 : 90)))
      .force('charge', forceManyBody().strength(-260))
      .force('center', forceCenter(width / 2, height / 2))
      .force('collide', forceCollide<GraphNode>((d) => radiusOf(d.factCount) + 6))
    simulationRef.current = simulation

    simulation.on('tick', () => {
      for (const n of nodes) {
        // Charge repulsion between disjoint clusters has nothing pulling it
        // back once a cluster drifts near an edge -- clamp in place (not
        // just at render time) so the simulation's own state stays
        // consistent with what's drawn, instead of fighting a display-only
        // clamp every tick.
        const r = radiusOf(n.factCount) + LABEL_MARGIN
        if (n.x !== undefined) n.x = Math.max(r, Math.min(width - r, n.x))
        if (n.y !== undefined) n.y = Math.max(r, Math.min(height - r, n.y))
        const el = nodeEls.current.get(n.id)
        if (el && n.x !== undefined && n.y !== undefined) {
          el.setAttribute('transform', `translate(${n.x}, ${n.y})`)
        }
      }
      graphLinks.forEach((l, i) => {
        const el = linkEls.current.get(i)
        const source = l.source as unknown as GraphNode
        const target = l.target as unknown as GraphNode
        if (el && source.x !== undefined && target.x !== undefined) {
          el.setAttribute('x1', String(source.x))
          el.setAttribute('y1', String(source.y))
          el.setAttribute('x2', String(target.x))
          el.setAttribute('y2', String(target.y))
        }
      })
    })

    for (const n of nodes) {
      const el = nodeEls.current.get(n.id)
      if (!el) continue
      d3select(el).call(
        d3drag<SVGGElement, unknown>()
          .on('start', (event) => {
            if (!event.active) simulation.alphaTarget(0.3).restart()
            n.fx = n.x
            n.fy = n.y
          })
          .on('drag', (event) => {
            n.fx = event.x
            n.fy = event.y
          })
          .on('end', (event) => {
            if (!event.active) simulation.alphaTarget(0)
            n.fx = null
            n.fy = null
          }),
      )
    }

    return () => { simulation.stop() }
    // width/height as deps: entering/leaving fullscreen (or a window resize
    // while in it) changes the canvas size, and the simulation's center/
    // boundary-clamp forces close over whatever width/height they were built
    // with -- they need a fresh simulation to pick up the new dimensions.
  }, [nodes, graphLinks, width, height])

  // Polling (see MemoryBrowser) refreshes topics/entities every few seconds
  // while a background ingest is adding facts. When the *set* of nodes is
  // unchanged, `nodes` above stays the same array on purpose -- rebuilding
  // it would restart the simulation from scratch (every node re-explodes out
  // from the center, dragged positions lost) just because a fact_count went
  // up. Instead, patch the count directly onto the SAME node objects the
  // simulation is already tracking, and nudge it awake so collision spacing
  // catches up to the new radius -- existing layout stays put otherwise.
  useEffect(() => {
    let changed = false
    for (const n of nodes) {
      const next = n.kind === 'topic'
        ? closureCounts.get(n.code) ?? 0
        : entities.find((e) => e.code === n.code)?.fact_count ?? n.factCount
      if (next !== n.factCount) { n.factCount = next; changed = true }
    }
    if (changed) simulationRef.current?.alpha(0.3).restart()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, topics, entities])

  if (nodes.length === 0) return <p className="muted">还没有主题或实体——先入库一些内容。</p>

  return (
    <div style={{ overflow: 'auto', border: '1px solid var(--line)', borderRadius: 8 }}>
      <div className="row" style={{ padding: '8px 10px 0', fontSize: 12 }}>
        <span className="muted">
          <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
                         border: '1.5px solid var(--accent)', marginRight: 4, verticalAlign: -1 }} />
          主题
        </span>
        <span className="muted">
          <span style={{ display: 'inline-block', width: 10, height: 10,
                         border: '1.5px solid var(--ins)', marginRight: 4, verticalAlign: -1 }} />
          实体
        </span>
        <span className="muted">虚线 = 共同出现在同一条事实里</span>
      </div>
      <svg width={width} height={height} style={{ display: 'block' }}>
        <defs>
          <marker id="kg-arrow" viewBox="0 0 8 8" refX="7" refY="4"
                  markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 L8 4 L0 8 z" fill="var(--muted)" />
          </marker>
          <marker id="kg-arrow-rel" viewBox="0 0 8 8" refX="7" refY="4"
                  markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 L8 4 L0 8 z" fill="var(--ins)" />
          </marker>
        </defs>

        {graphLinks.map((l, i) => (
          <line
            key={i}
            ref={(el) => { if (el) linkEls.current.set(i, el); else linkEls.current.delete(i) }}
            stroke={l.kind === 'relation' ? 'var(--ins)' : 'var(--muted)'}
            strokeWidth={1.4}
            strokeDasharray={l.kind === 'cooccur' ? '3 3' : undefined}
            markerEnd={l.kind === 'cooccur' ? undefined : `url(#${l.kind === 'relation' ? 'kg-arrow-rel' : 'kg-arrow'})`}
          />
        ))}

        {nodes.map((n) => {
          const deprecated = n.status === 'deprecated'
          const candidate = n.status === 'candidate'
          const empty = n.factCount === 0
          const r = radiusOf(n.factCount)
          const label = n.label.length > 12 ? n.label.slice(0, 11) + '…' : n.label
          const color = n.kind === 'topic' ? 'var(--accent)' : 'var(--ins)'
          return (
            <g
              key={n.id}
              ref={(el) => { if (el) nodeEls.current.set(n.id, el); else nodeEls.current.delete(n.id) }}
              style={{ cursor: 'pointer' }}
              onClick={() => onSelect(n.kind, n.code)}
            >
              <title>
                {n.kind === 'topic' ? '主题' : '实体'}：{n.label} · {n.factCount} 条事实
                {n.aliases.length ? ` · 别名：${n.aliases.join('、')}` : ''}
                {n.kind === 'topic' ? ` · ${n.status}` : ''}
                {empty ? ' · 还没有内容' : ''}
              </title>
              {n.kind === 'topic' ? (
                <circle
                  r={r}
                  fill="var(--panel)"
                  opacity={empty ? 0.4 : (deprecated ? 0.55 : 1)}
                  stroke={deprecated ? 'var(--muted)' : color}
                  strokeDasharray={candidate ? '4 3' : undefined}
                />
              ) : (
                <rect
                  x={-r * 0.8} y={-r * 0.8} width={r * 1.6} height={r * 1.6} rx={4}
                  fill="var(--panel)"
                  opacity={empty ? 0.4 : 1}
                  stroke={color}
                />
              )}
              <text textAnchor="middle" dy={4} fontSize={12} fill="var(--fg)"
                    style={{ textDecoration: deprecated ? 'line-through' : 'none', pointerEvents: 'none' }}>
                {label}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
