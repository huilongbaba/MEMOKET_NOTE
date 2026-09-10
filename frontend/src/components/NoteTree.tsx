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
import { useEffect, useMemo, useRef, useState } from 'react'

import type { TreeRow } from '../api'
import { ROOT_ID, isFactId, isVirtualId } from '../api'
import { displayTitle } from '../util/displayTitle'

type Props = {
  rows: TreeRow[]
  activeNoteId: string | null
  onOpen: (noteId: string, mods?: { alt: boolean }) => void
  onToggle: (row: TreeRow) => void
  onContextMenu?: (row: TreeRow, at: { x: number; y: number }) => void
  /** 键盘：Delete 删除、F2 改名；hover 出现的「＋」建子笔记。只对真笔记生效。 */
  onDelete?: (row: TreeRow) => void
  onRename?: (row: TreeRow) => void
  onNewChild?: (row: TreeRow) => void
  /** 拖拽：把 drag 放到 target 的前面 / 后面 / 里面。只对真笔记生效。 */
  onDrop?: (drag: TreeRow, target: TreeRow, where: DropWhere) => void
}

export type DropWhere = 'before' | 'after' | 'over'


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
  rows, activeNoteId, onOpen, onToggle, onContextMenu, onDelete, onRename, onNewChild, onDrop,
}: Props) {
  const nodes = useMemo(() => flatten(rows), [rows])
  const rootRef = useRef<HTMLDivElement>(null)

  // 拖拽状态。drop 位置按行内 y 分三段：上 25% = 放前面、下 25% = 放后面、
  // 中间 = 放进去（note_tree.ts:615-623 的 moveBefore/After/ToParent）。
  const [drag, setDrag] = useState<Node | null>(null)
  const [drop, setDrop] = useState<{ id: string; where: DropWhere } | null>(null)
  const expandTimer = useRef<number | null>(null)
  const clearExpandTimer = () => { if (expandTimer.current) { window.clearTimeout(expandTimer.current); expandTimer.current = null } }

  // 键盘焦点落在哪一行（roving tabindex）。默认跟着当前笔记；用户用方向键
  // 挪开后各走各的——Trilium 也是「焦点」和「激活」两个概念。
  const [focusKey, setFocusKey] = useState<string | null>(null)
  const focused = nodes.find((n) => n.id === focusKey)
    ?? nodes.find((n) => n.note_id === activeNoteId) ?? nodes[0]

  // 切换笔记后把激活行滚进视口（note_tree.ts:393-397 的 scrollOfs 100）。
  // 克隆意味着同一篇在树上有多处，滚到**第一处**。
  useEffect(() => {
    const el = rootRef.current?.querySelector<HTMLElement>('.tree-node.active')
    el?.scrollIntoView({ block: 'nearest' })
  }, [activeNoteId])

  function onKeyDown(e: React.KeyboardEvent) {
    if (!focused || e.metaKey || e.ctrlKey || e.altKey) return
    const i = nodes.indexOf(focused)
    const go = (n: Node | undefined) => { if (n) { setFocusKey(n.id); e.preventDefault() } }
    switch (e.key) {
      case 'ArrowDown': go(nodes[i + 1]); break
      case 'ArrowUp': go(nodes[i - 1]); break
      case 'ArrowRight':
        e.preventDefault()
        if (focused.child_count > 0 && !focused.is_expanded) onToggle(focused)
        else go(nodes[i + 1]?.depth === focused.depth + 1 ? nodes[i + 1] : undefined)
        break
      case 'ArrowLeft':
        e.preventDefault()
        if (focused.child_count > 0 && focused.is_expanded) onToggle(focused)
        else go(nodes.slice(0, i).reverse().find((n) => n.depth === focused.depth - 1))
        break
      case 'Enter': case ' ': e.preventDefault(); onOpen(focused.note_id); break
      case 'Delete': case 'Backspace':
        if (onDelete && !isVirtualId(focused.note_id)) { e.preventDefault(); onDelete(focused) }
        break
      case 'F2':
        if (onRename && !isVirtualId(focused.note_id)) { e.preventDefault(); onRename(focused) }
        break
      case 'Home': go(nodes[0]); break
      case 'End': go(nodes[nodes.length - 1]); break
    }
  }

  // 焦点行随键盘移动时也要滚进视口
  useEffect(() => {
    if (!focusKey) return
    rootRef.current?.querySelector<HTMLElement>('.tree-node.focused')?.scrollIntoView({ block: 'nearest' })
  }, [focusKey])

  if (nodes.length === 0) {
    return <p className="muted" style={{ fontSize: 13, padding: '8px 4px' }}>
      还没有笔记。新建一篇开始。
    </p>
  }

  return (
    <div className="note-tree" role="tree" ref={rootRef} tabIndex={0} onKeyDown={onKeyDown}>
      {nodes.map((n) => {
        const active = n.note_id === activeNoteId
        const hasKids = n.child_count > 0
        const virtual = isVirtualId(n.note_id)
        return (
          <div
            key={n.id}
            role="treeitem"
            aria-expanded={hasKids ? n.is_expanded : undefined}
            aria-selected={active}
            className={'tree-node' + (active ? ' active' : '') + (focused?.id === n.id ? ' focused' : '')
              + (drag?.id === n.id ? ' dragging' : '') + (drop?.id === n.id ? ' drop-' + drop.where : '')}
            // 每级 10px、根再让 12px（theme-next/shell.css:716-723）
            style={{ paddingInlineStart: 12 + n.depth * 10 }}
            onClick={(e) => { setFocusKey(n.id); onOpen(n.note_id, { alt: e.altKey }) }}
            draggable={!!onDrop && !virtual}
            onDragStart={(e) => {
              setDrag(n); e.dataTransfer.effectAllowed = 'move'
              e.dataTransfer.setData('text/plain', n.note_id)
            }}
            onDragOver={(e) => {
              if (!drag || virtual || drag.id === n.id) return
              e.preventDefault()
              const r = e.currentTarget.getBoundingClientRect()
              const y = (e.clientY - r.top) / r.height
              const where: DropWhere = y < .25 ? 'before' : y > .75 ? 'after' : 'over'
              if (drop?.id !== n.id || drop.where !== where) {
                setDrop({ id: n.id, where })
                // 悬停 600ms 自动展开（fancytree dnd5 的 autoExpandMS）
                clearExpandTimer()
                if (where === 'over' && hasKids && !n.is_expanded)
                  expandTimer.current = window.setTimeout(() => onToggle(n), 600)
              }
            }}
            onDragLeave={() => { if (drop?.id === n.id) { setDrop(null); clearExpandTimer() } }}
            onDrop={(e) => {
              e.preventDefault()
              if (drag && drop && drop.id === n.id && drag.id !== n.id) onDrop?.(drag, n, drop.where)
              setDrag(null); setDrop(null); clearExpandTimer()
            }}
            onDragEnd={() => { setDrag(null); setDrop(null); clearExpandTimer() }}
            onContextMenu={(e) => {
              if (!onContextMenu) return
              e.preventDefault()
              setFocusKey(n.id)
              onContextMenu(n, { x: e.clientX, y: e.clientY })
            }}
            // 只在文字真被截断时才给 tooltip（note_tree.ts:329-353），
            // 否则每行都弹一个悬浮框很烦
            onMouseEnter={(e) => {
              const title = e.currentTarget.querySelector<HTMLElement>('.tree-title')
              if (title && title.scrollWidth > title.clientWidth) e.currentTarget.title = title.textContent ?? ''
              else e.currentTarget.removeAttribute('title')
            }}
          >
            <span
              className={'tree-expander' + (hasKids ? '' : ' leaf')}
              onClick={(e) => { e.stopPropagation(); if (hasKids) onToggle(n) }}
              aria-hidden={!hasKids}
            >
              {hasKids ? (n.is_expanded ? '▾' : '▸') : ''}
            </span>
            {/* 图标：真笔记 叶子 = 文档 / 有子节点 = 文件夹（notes.ts:140-143）；
                知识库虚拟节点 事实 ◆ / 分类 ▤。 */}
            <span className="tree-icon" aria-hidden>
              {virtual ? (isFactId(n.note_id) ? '◆' : '▤') : (hasKids ? '▣' : '▢')}
            </span>
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
            {hasKids && !virtual && <span className="tree-count">{n.child_count}</span>}
            {/* hover 才出现的「＋ 建子笔记」。建笔记是最高频动作，藏在右键里
                成本太高（note_tree.ts:1875-1941 的 add-note-button）。 */}
            {onNewChild && !virtual && (
              <button className="tree-item-button" title="新建子笔记"
                      onClick={(e) => { e.stopPropagation(); onNewChild(n) }}>＋</button>
            )}
          </div>
        )
      })}
    </div>
  )
}

export { flatten as flattenTreeForTest }
