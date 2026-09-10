/**
 * 笔记树 —— 照 Trilium 的树。
 *
 * 几条它的做法，都是有理由的、不是装饰：
 *
 * · **文件夹不是一种东西**。有子节点的笔记就画成可展开的，没有就是叶子。
 *   所以「新建文件夹」这个动作不存在——建一篇笔记，往里面放东西，它自然
 *   就成了文件夹。
 * · **克隆要看得出来**。同一篇笔记可以长在树的好几个位置，改一处处处都变。
 *   不标出来的话用户会以为那是两篇，改了一处发现另一处也变了，像见了鬼。
 * · **展开状态存在服务端**。刷新一次就全收起来的树，几十个节点之后没法用。
 * · **行高 2.4em、圆角 5px**（取自 Trilium 的 tree.css）：这个高度是给鼠标
 *   拖拽留的余量，压到 1.6em 之后拖放的命中率会明显变差。
 */
import { useMemo } from 'react'

import type { TreeRow } from '../api'
import { ROOT_ID, isFactId, isVirtualId } from '../api'
import { displayTitle } from '../util/displayTitle'

type Props = {
  rows: TreeRow[]
  activeNoteId: string | null
  onOpen: (noteId: string) => void
  onToggle: (row: TreeRow) => void
  onContextMenu?: (row: TreeRow, at: { x: number; y: number }) => void
}

type Node = TreeRow & { depth: number }



/** 把扁平的 branch 列表按父子关系铺平成「要画的行」，只铺开展开着的。 */
function flatten(rows: TreeRow[]): Node[] {
  const byParent = new Map<string, TreeRow[]>()
  for (const r of rows) {
    const list = byParent.get(r.parent_note_id)
    if (list) list.push(r)
    else byParent.set(r.parent_note_id, [r])
  }
  for (const list of byParent.values()) {
    list.sort((a, b) => a.position - b.position || a.title.localeCompare(b.title))
  }

  const out: Node[] = []
  // 迭代而不是递归：树的深度由用户决定，而且**万一数据里成了环**（后端有
  // 防线，但前端不该假设它没漏），递归是直接爆栈，迭代加一个 seen 集合
  // 最多画重复，界面还活着。
  const seen = new Set<string>()
  const walk = (parent: string, depth: number) => {
    for (const row of byParent.get(parent) ?? []) {
      const key = `${row.note_id}@${row.parent_note_id}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ ...row, depth })
      if (row.is_expanded && row.child_count > 0) walk(row.note_id, depth + 1)
    }
  }
  walk(ROOT_ID, 0)
  return out
}

export default function NoteTree({
  rows, activeNoteId, onOpen, onToggle, onContextMenu,
}: Props) {
  const nodes = useMemo(() => flatten(rows), [rows])

  if (nodes.length === 0) {
    return <p className="muted" style={{ fontSize: 13, padding: '8px 4px' }}>
      还没有笔记。新建一篇开始。
    </p>
  }

  return (
    <div className="note-tree" role="tree">
      {nodes.map((n) => {
        const active = n.note_id === activeNoteId
        const hasKids = n.child_count > 0
        return (
          <div
            key={n.id}
            role="treeitem"
            aria-expanded={hasKids ? n.is_expanded : undefined}
            aria-selected={active}
            className={'tree-node' + (active ? ' active' : '')}
            style={{ paddingInlineStart: 4 + n.depth * 16 }}
            onClick={() => onOpen(n.note_id)}
            onContextMenu={(e) => {
              if (!onContextMenu) return
              e.preventDefault()
              onContextMenu(n, { x: e.clientX, y: e.clientY })
            }}
          >
            <span
              className={'tree-expander' + (hasKids ? '' : ' leaf')}
              onClick={(e) => { e.stopPropagation(); if (hasKids) onToggle(n) }}
              aria-hidden={!hasKids}
            >
              {hasKids ? (n.is_expanded ? '▾' : '▸') : ''}
            </span>
            {/* 知识库那棵虚拟子树的节点带图标：事实 ◆、分类 ▤。真笔记不带——
                Trilium 的树也是只给特殊类型的笔记配图标。 */}
            {isVirtualId(n.note_id) && (
              <span className="tree-icon" aria-hidden>{isFactId(n.note_id) ? '◆' : '▤'}</span>
            )}
            <span className="tree-title">{displayTitle(n)}</span>
            {n.fact_count > 0 && !isFactId(n.note_id) && (
              <span className="tree-badge" title={`${n.fact_count} 条事实`}>{n.fact_count}</span>
            )}
            {/* 跟知识库的连接，树上直接看得见（docs/kb-fusion-design.md）。
                一眼分出「有据可依的」和「还只是草稿的」。 */}
            {n.ingested_at && (
              <span className="tree-badge ingested"
                    title={`已摄入知识库（${n.ingested_at.slice(0, 10)}）`}>⇡</span>
            )}
            {n.cite_count > 0 && (
              <span className="tree-badge cited"
                    title={`引用了 ${n.cite_count} 条知识库记录`}>◆{n.cite_count}</span>
            )}
            {n.branch_count > 1 && (
              // 克隆标记。用户得知道改这一处会让别处跟着变。
              <span className="tree-badge" title={`这篇笔记同时在 ${n.branch_count} 个位置`}>
                ⧉
              </span>
            )}
            {hasKids && !isVirtualId(n.note_id) && <span className="tree-count">{n.child_count}</span>}
          </div>
        )
      })}
    </div>
  )
}

export { flatten as flattenTreeForTest }
