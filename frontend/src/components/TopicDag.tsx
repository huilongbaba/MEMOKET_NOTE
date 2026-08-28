import type { TopicNode } from '../api'

/**
 * Topics form a DAG, not a tree -- a topic can have multiple parents (see
 * KITE core/vocab.py: `parents: set`). The earlier version only drew roots
 * plus one level of children, so multi-parent nodes and deeper levels were
 * invisible. This lays out nodes by topological depth instead:
 * depth(t) = 1 + max(depth(parent)), nodes at the same depth sorted by code,
 * parent -> child edges drawn as curves, and a node can have multiple
 * incoming edges.
 */

const NODE_W = 132
const NODE_H = 34
const COL_GAP = 20
const ROW_GAP = 56
const PAD = 20

type Pos = { x: number; y: number }

function layoutDag(topics: TopicNode[]): { positions: Record<string, Pos>; width: number; height: number } {
  const byCode = new Map(topics.map((t) => [t.code, t]))
  const depthCache = new Map<string, number>()
  const visiting = new Set<string>()

  function depthOf(code: string): number {
    if (depthCache.has(code)) return depthCache.get(code)!
    if (visiting.has(code)) return 0 // 循环保护——DAG 理论上无环，数据异常时别死循环
    visiting.add(code)
    const parents = (byCode.get(code)?.parents ?? []).filter((p) => byCode.has(p) && p !== code)
    const d = parents.length === 0 ? 0 : 1 + Math.max(...parents.map(depthOf))
    visiting.delete(code)
    depthCache.set(code, d)
    return d
  }

  const rows = new Map<number, string[]>()
  for (const t of topics) {
    const d = depthOf(t.code)
    if (!rows.has(d)) rows.set(d, [])
    rows.get(d)!.push(t.code)
  }
  for (const codes of rows.values()) codes.sort()

  const maxCols = Math.max(1, ...[...rows.values()].map((r) => r.length))
  const width = maxCols * (NODE_W + COL_GAP) - COL_GAP + PAD * 2
  const height = rows.size * (NODE_H + ROW_GAP) - ROW_GAP + PAD * 2

  const positions: Record<string, Pos> = {}
  for (const [depth, codes] of rows) {
    const rowWidth = codes.length * (NODE_W + COL_GAP) - COL_GAP
    const startX = PAD + (width - PAD * 2 - rowWidth) / 2
    codes.forEach((code, i) => {
      positions[code] = { x: startX + i * (NODE_W + COL_GAP), y: PAD + depth * (NODE_H + ROW_GAP) }
    })
  }
  return { positions, width, height }
}

export default function TopicDag({ topics, onSelect }: { topics: TopicNode[]; onSelect: (code: string) => void }) {
  if (topics.length === 0) return <p className="muted">还没有主题——先入库一些内容。</p>

  const { positions, width, height } = layoutDag(topics)
  const edges: { from: string; to: string }[] = []
  for (const t of topics) {
    for (const p of t.parents) {
      if (positions[p]) edges.push({ from: p, to: t.code })
    }
  }

  return (
    <div style={{ overflowX: 'auto', border: '1px solid var(--line)', borderRadius: 8 }}>
      <svg width={width} height={height} style={{ display: 'block' }}>
        <defs>
          <marker id="dag-arrow" viewBox="0 0 8 8" refX="7" refY="4"
                  markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 L8 4 L0 8 z" fill="var(--muted)" />
          </marker>
        </defs>

        {edges.map((e, i) => {
          const a = positions[e.from]
          const b = positions[e.to]
          const x1 = a.x + NODE_W / 2, y1 = a.y + NODE_H
          const x2 = b.x + NODE_W / 2, y2 = b.y
          const midY = (y1 + y2) / 2
          return (
            <path
              key={i}
              d={`M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`}
              fill="none"
              stroke="var(--muted)"
              strokeWidth={1.4}
              markerEnd="url(#dag-arrow)"
            />
          )
        })}

        {topics.map((t) => {
          const pos = positions[t.code]
          if (!pos) return null
          const deprecated = t.status === 'deprecated'
          const candidate = t.status === 'candidate'
          const label = t.code.length > 15 ? t.code.slice(0, 14) + '…' : t.code
          return (
            <g key={t.code} transform={`translate(${pos.x}, ${pos.y})`}
               style={{ cursor: 'pointer' }} onClick={() => onSelect(t.code)}>
              <title>
                {t.code}{t.aliases.length ? ` · 别名：${t.aliases.join('、')}` : ''} · {t.status}
              </title>
              <rect
                width={NODE_W} height={NODE_H} rx={6}
                fill="var(--panel)"
                stroke={deprecated ? 'var(--muted)' : 'var(--accent)'}
                strokeDasharray={candidate ? '4 3' : undefined}
                opacity={deprecated ? 0.55 : 1}
              />
              <text x={NODE_W / 2} y={NODE_H / 2 + 4} textAnchor="middle" fontSize={12}
                    fill="var(--fg)"
                    style={{ textDecoration: deprecated ? 'line-through' : 'none' }}>
                {label}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
