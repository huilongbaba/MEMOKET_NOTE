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
import { useEffect, useRef } from 'react'

export type Tab = { id: string; noteId: string; title: string }

const MAX_W = 240
/** Trilium 的三档：TAB_SIZE_SMALL 84 / SMALLER 60 / MINI 48。我们的下限取
 *  84——再窄的那两档它靠滚动按钮兜底，我们靠 strip 横向可滚兜底，效果一样。 */
const MIN_W = 84
const MARGIN_W = 5

export default function TabBar({
  tabs, activeId, onSelect, onClose, onNew, onContextMenu,
}: {
  tabs: Tab[]
  activeId: string | null
  onSelect: (id: string) => void
  onClose: (id: string) => void
  onNew: () => void
  onContextMenu?: (tab: Tab, at: { x: number; y: number }) => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  // 标签多到放不下时按比例缩。宽度算在这儿而不是交给 flex，是因为要保证
  // 每个标签**至少**看得出是个标签（Trilium 的下限是 48px）。
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
    <div className="tab-strip" ref={ref} role="tablist"
         // 滚轮竖滚转横滚：strip 是横向的，用户的滚轮是竖向的（tab_row.ts:424-466）
         onWheel={(e) => { if (e.deltaY && ref.current) ref.current.scrollLeft += e.deltaY }}>
      {tabs.map((t, i) => (
        <div
          key={t.id}
          role="tab"
          aria-selected={t.id === activeId}
          className={'note-tab' + (t.id === activeId ? ' active' : '')}
          title={`${t.title || '未命名'}${i < 9 ? `　⌘${i + 1}` : ''}`}
          onClick={() => onSelect(t.id)}
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
    <button className="note-new-tab" onClick={onNew} title="新建笔记（⌘T）"><span>＋</span></button>
    <div className="tab-row-filler" />
    </>
  )
}
