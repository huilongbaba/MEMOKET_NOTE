/** Multi-note workspace tabs stay readable and scroll when the window is full. */
import { useEffect, useRef, useState } from 'react'
import { fmtShortcut } from '../util/keys'
import Icon from './Icon'

export type Tab = { id: string; noteId: string; title: string }

const MAX_W = 240
/** Keep enough room for a recognizable title; overflow has explicit scroll controls. */
const MIN_W = 128
const MARGIN_W = 5

export default function TabBar({
  tabs, activeId, onSelect, onClose, onNew, onContextMenu, onReorder, iconOf, onListTabs, busyIds, menuTabId,
}: {
  tabs: Tab[]
  activeId: string | null
  /** 某个标签的笔记图标（用户挑过的才有；Trilium 的标签也带 NoteIcon）。不进 Tab 模型——那个落 localStorage，图标改了会留旧值 */
  iconOf?: (noteId: string) => string | undefined
  onSelect: (id: string) => void
  onClose: (id: string) => void
  onNew: () => void
  onContextMenu?: (tab: Tab, at: { x: number; y: number }) => void
  /** 拖拽排序：把 id 挪到第 index 位 */
  onReorder?: (id: string, index: number) => void
  /** 装不下时多一个 ▾：列出所有标签（Chrome 的标签搜索 / VS Code 的「打开的编辑器」）。50 个标签靠 ◀ ▶ 一格格滚是找不到的 */
  onListTabs?: (at: { x: number; y: number }) => void
  /** harness 正在写的那几篇：标签顶上一道色条。切去别的标签时唯一能看出「还在跑、跑的是哪篇」的地方 */
  busyIds?: Set<string>
  /** 右键菜单开着时是哪个标签：高亮它（Trilium tab_row 右键时也这样） */
  menuTabId?: string | null
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [dragId, setDragId] = useState<string | null>(null)
  const [overIndex, setOverIndex] = useState<number | null>(null)

  // 标签多到放不下时按比例缩。宽度算在这儿而不是交给 flex，是因为要保证
  // 每个标签**至少**看得出是个标签（Trilium 的下限是 48px）。
  // 激活的标签滚进视野：十几个标签时 ⌘9 / 后退切到的那个可能在看不见的地方
  useEffect(() => {
    if (!activeId) return
    const el = ref.current?.querySelector('.note-tab.active') as HTMLElement | null
    el?.scrollIntoView({ inline: 'nearest', block: 'nearest' })
  }, [activeId, tabs.length])

  // 装不下时显形两个滚动按钮（Trilium tab_row.ts:19x：每次滚 ±210px）——只靠滚轮横滚
  // 没人发现得了，十几个标签时最右那个就一直藏着
  const [overflow, setOverflow] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const check = () => setOverflow(el.scrollWidth > el.clientWidth + 2)
    check()
    const ro = new ResizeObserver(check)
    ro.observe(el)
    return () => ro.disconnect()
  }, [tabs.length])

  useEffect(() => {
    const el = ref.current
    const parent = el?.parentElement
    if (!el || !parent) return
    const resize = () => {
      // Measure the actual controls; navigation and capture widths vary by platform/window.
      const siblings = [...parent.children].filter((child) => child !== el && !child.classList.contains('tab-row-filler'))
      const controls = siblings.reduce((sum, child) => sum + child.getBoundingClientRect().width, 0)
      const gap = parseFloat(getComputedStyle(parent).columnGap) || MARGIN_W
      const inset = parseFloat(getComputedStyle(parent).paddingLeft) + parseFloat(getComputedStyle(parent).paddingRight) || 0
      const avail = parent.clientWidth - controls - inset - 50 - gap * (parent.children.length - 1) - (tabs.length - 1) * MARGIN_W
      const width = Math.max(MIN_W, Math.min(Math.floor(avail / Math.max(1, tabs.length)), MAX_W))
      el.style.setProperty('--tab-w', `${width}px`)
      el.dataset.size = width < 160 ? 'narrow' : ''
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(parent)
    for (const child of parent.children) if (child !== el && !child.classList.contains('tab-row-filler')) observer.observe(child)
    return () => observer.disconnect()
  }, [tabs.length, overflow])

  return (
    <>
    {overflow && <button className="tab-scroll" title="往左看" onClick={() => { if (ref.current) ref.current.scrollBy({ left: -210, behavior: 'smooth' }) }}><Icon n="bx-chevron-left" /></button>}
    <div className="tab-strip" ref={ref} role="tablist"
         // 滚轮竖滚转横滚：strip 是横向的，用户的滚轮是竖向的（tab_row.ts:424-466）
         onWheel={(e) => { if (e.deltaY && ref.current) ref.current.scrollLeft += e.deltaY }}>
      {tabs.map((t, i) => (
        <div
          key={t.id}
          role="tab"
          tabIndex={t.id === activeId || (!tabs.some((tab) => tab.id === activeId) && i === 0) ? 0 : -1}
          aria-selected={t.id === activeId}
          className={'note-tab' + (t.id === activeId ? ' active' : '') + (busyIds?.has(t.noteId) ? ' busy' : '') + (menuTabId === t.id ? ' ctx-target' : '')
            + (dragId === t.id ? ' dragging' : '') + (overIndex === i && dragId !== t.id ? ' drop-before' : '')}
          title={`${t.title || '未命名'}${busyIds?.has(t.noteId) ? '（正在写）' : ''}${i < 9 ? `　${fmtShortcut('⌘' + (i + 1))}` : ''}`}
          onClick={() => onSelect(t.id)}
          onKeyDown={(event) => {
            if (event.target !== event.currentTarget) return
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault(); onSelect(t.id); return
            }
            const next = event.key === 'ArrowRight' ? (i + 1) % tabs.length
              : event.key === 'ArrowLeft' ? (i - 1 + tabs.length) % tabs.length
                : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1
            if (next < 0) return
            event.preventDefault(); event.stopPropagation()
            onSelect(tabs[next].id)
            ref.current?.querySelectorAll<HTMLElement>('[role="tab"]')[next]?.focus()
          }}
          // 同行内拖拽排序（Trilium 用 Draggabilly；HTML5 dnd 够用）
          draggable={!!onReorder}
          onDragStart={(e) => { setDragId(t.id); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', t.id) }}
          onDragOver={(e) => {
            if (!dragId) return
            e.preventDefault()
            const r = e.currentTarget.getBoundingClientRect()
            setOverIndex(e.clientX < r.left + r.width / 2 ? i : i + 1)
          }}
          onDrop={(e) => {
            e.preventDefault()
            if (dragId && overIndex !== null) onReorder?.(dragId, overIndex)
            setDragId(null); setOverIndex(null)
          }}
          onDragEnd={() => { setDragId(null); setOverIndex(null) }}
          // 中键关闭：浏览器里的通用习惯，Trilium 也有。没有它的话，关一堆
          // 标签要一个个瞄准那个小叉。
          onAuxClick={(e) => { if (e.button === 1) { e.preventDefault(); onClose(t.id) } }}
          onContextMenu={(e) => {
            if (!onContextMenu) return
            e.preventDefault()
            onContextMenu(t, { x: e.clientX, y: e.clientY })
          }}
        >
          {iconOf?.(t.noteId) && <Icon n={iconOf(t.noteId)!} className="note-tab-icon" />}
          <span className="note-tab-title">{t.title || '未命名'}</span>
          <button type="button" tabIndex={-1}
            className="note-tab-close"
            aria-label={`关闭 ${t.title || '未命名'}`}
            onClick={(e) => { e.stopPropagation(); onClose(t.id) }}
          >
            <Icon n="bx-x" />
          </button>
        </div>
      ))}
    </div>
    {overflow && <button className="tab-scroll" title="往右看" onClick={() => { if (ref.current) ref.current.scrollBy({ left: 210, behavior: 'smooth' }) }}><Icon n="bx-chevron-right" /></button>}
    {overflow && onListTabs && (
      <button className="tab-scroll tab-list" title={`列出全部 ${tabs.length} 个标签`}
              onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); onListTabs({ x: r.left, y: r.bottom + 2 }) }}>
        <Icon n="bx-chevron-down" />
      </button>
    )}
    <button className="note-new-tab" onClick={onNew} title={`新建笔记（${fmtShortcut('⌘T')}）`}><span><Icon n="bx-plus" /></span></button>
    {/* 标签行空白处双击开新标签（浏览器约定） */}
    <div className="tab-row-filler" onDoubleClick={onNew} />
    </>
  )
}
