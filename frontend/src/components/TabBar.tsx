/**
 * 标签行 —— 对标 Trilium 的 tab_row。
 *
 * 尺寸取自它（tab_row.ts）：单个标签 100–240px，标签多了按 84 / 60 / 48
 * 三档缩，新建按钮 36px。这几个数字不是我猜的——标签缩到 48px 时只剩一个
 * 图标位，再窄就点不准了。
 *
 * **为什么这个产品需要多标签**：痛点 10「笔记散在飞书和 Notion，想把两边
 * 交起来写，得先想起两边叫什么名字」，以及写作时最常见的动作——对照着另
 * 一篇写。单篇编辑器逼着用户在脑子里存住另一篇的内容，那正是判据 2 要省
 * 下来的注意力。
 */
import { useEffect, useRef, useState } from 'react'
import { fmtShortcut } from '../util/keys'

export type Tab = { id: string; noteId: string; title: string }

const MAX_W = 240
/** Trilium 的三档：TAB_SIZE_SMALL 84 / SMALLER 60 / MINI 48。我们的下限取
 *  84——再窄的那两档它靠滚动按钮兜底，我们靠 strip 横向可滚兜底，效果一样。 */
const MIN_W = 84
const MARGIN_W = 5

export default function TabBar({
  tabs, activeId, onSelect, onClose, onNew, onContextMenu, onReorder,
}: {
  tabs: Tab[]
  activeId: string | null
  onSelect: (id: string) => void
  onClose: (id: string) => void
  onNew: () => void
  onContextMenu?: (tab: Tab, at: { x: number; y: number }) => void
  /** 拖拽排序：把 id 挪到第 index 位 */
  onReorder?: (id: string, index: number) => void
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
    if (!el) return
    // 可用宽度是 strip 的父容器（标签行）减去左右 spacer / filler / ＋；
    // 间隙照 tab_row.ts:536-538 扣掉 (n-1)*5。
    const parent = el.parentElement
    const avail = (parent?.clientWidth ?? el.clientWidth) - 36 - 50 - 72 - (tabs.length - 1) * MARGIN_W
    const each = Math.floor(avail / Math.max(1, tabs.length))
    const w = Math.max(MIN_W, Math.min(each, MAX_W))
    el.style.setProperty('--tab-w', `${w}px`)
    el.dataset.size = w <= 84 ? 'small' : ''
  }, [tabs.length])

  return (
    <>
    {overflow && <button className="tab-scroll" title="往左看" onClick={() => { if (ref.current) ref.current.scrollBy({ left: -210, behavior: 'smooth' }) }}><i className="bx bx-chevron-left" /></button>}
    <div className="tab-strip" ref={ref} role="tablist"
         // 滚轮竖滚转横滚：strip 是横向的，用户的滚轮是竖向的（tab_row.ts:424-466）
         onWheel={(e) => { if (e.deltaY && ref.current) ref.current.scrollLeft += e.deltaY }}>
      {tabs.map((t, i) => (
        <div
          key={t.id}
          role="tab"
          aria-selected={t.id === activeId}
          className={'note-tab' + (t.id === activeId ? ' active' : '')
            + (dragId === t.id ? ' dragging' : '') + (overIndex === i && dragId !== t.id ? ' drop-before' : '')}
          title={`${t.title || '未命名'}${i < 9 ? `　${fmtShortcut('⌘' + (i + 1))}` : ''}`}
          onClick={() => onSelect(t.id)}
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
          <span className="note-tab-title">{t.title || '未命名'}</span>
          <span
            className="note-tab-close"
            aria-label="关闭"
            onClick={(e) => { e.stopPropagation(); onClose(t.id) }}
          >
            ×
          </span>
        </div>
      ))}
    </div>
    {overflow && <button className="tab-scroll" title="往右看" onClick={() => { if (ref.current) ref.current.scrollBy({ left: 210, behavior: 'smooth' }) }}><i className="bx bx-chevron-right" /></button>}
    <button className="note-new-tab" onClick={onNew} title={`新建笔记（${fmtShortcut('⌘T')}）`}><span><i className="bx bx-plus" /></span></button>
    {/* 标签行空白处双击开新标签（浏览器约定） */}
    <div className="tab-row-filler" onDoubleClick={onNew} />
    </>
  )
}
