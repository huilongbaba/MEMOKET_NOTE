/**
 * 右栏 —— 只有标签（照 Trilium）。「记忆」是默认标签。
 *
 * **为什么相关记忆常驻，而不是也做成一个标签**（这是我们跟 Trilium 的一处
 * 有意分歧，理由在 docs/product-north-star.md 判据 2）：
 *
 *   > 写报告时想查一篇旧笔记，找了半天读完回来，忘了这一点是为了支撑什么。
 *
 * 点一下标签虽然没离开页面，但它是一次**主动的检索动作**——用户得先想起
 * 「我该查一下」。而边写边浮现的召回是**被动的**：它在你需要之前就在那儿。
 * 这两件事对注意力的成本不一样，而这个产品的定义就是「保持注意力」。
 *
 * 下面的标签区照抄 Trilium 的两个做法：
 * · `alwaysShown`：没内容也留在条上，否则笔记间切换时标签条自己变形，
 *   鼠标下的东西会跑掉
 * · 有内容的标签给角标，不用点开就知道里面有东西
 *
 * **明确不抄它的 SidebarChat。** 那是个聊天框，正是判据 1 要消灭的东西。
 * 我们的「运行」放的是 harness 每一轮做了什么、判了什么——执行记录，不是对话。
 */
import { useEffect, useState, type ReactNode } from 'react'

export type PaneTab = {
  id: string
  title: string
  icon?: string          // Boxicons 类名
  badge?: string | number
  /** 没内容也留在标签条上。见上面注释里说的「条自己变形」。 */
  alwaysShown?: boolean
  hasContent?: boolean
  /** hasContent 为 false 时内容区说一句为什么是空的，别留白。 */
  emptyHint?: string
  body: ReactNode
}

export default function RightPane({
  tabs, defaultTab, onCollapse, focusTab,
}: { tabs: PaneTab[]; defaultTab: string; onCollapse?: () => void
     /** 外部要求切到某个标签（harness 跑起来切「计划」）。变一次切一次。 */
     focusTab?: { id: string; n: number } }) {
  const shown = tabs.filter((t) => t.alwaysShown || t.hasContent !== false)
  const [active, setActive] = useState(defaultTab)
  useEffect(() => { if (focusTab) setActive(focusTab.id) }, [focusTab])
  const current = shown.find((t) => t.id === active) ?? shown[0]

  return (
    <>
      <div className="right-pane-tabs" role="tablist">
        {shown.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={current?.id === t.id}
            className={'pane-tab' + (current?.id === t.id ? ' active' : '')}
            onClick={() => setActive(t.id)}
          >
            {t.icon && <i className={'bx ' + t.icon} />}
            {t.title}
            {t.badge !== undefined && t.badge !== 0 && (
              <span className="pane-tab-badge">{t.badge}</span>
            )}
          </button>
        ))}
        {/* 右端动作区：任何宽度下都完整可点（RightPanelContainer.css:110-145） */}
        {onCollapse && (
          <span className="right-pane-actions">
            <button className="icon-btn" title="收起右栏（⌘⇧\\）" onClick={onCollapse}><i className="bx bx-chevrons-right" /></button>
          </span>
        )}
      </div>
      <div className="right-pane-body" role="tabpanel">
        {current?.hasContent === false
          ? <p className="muted" style={{ fontSize: 12 }}>{current.emptyHint ?? '这篇还没有这一项的内容。'}</p>
          : current?.body}
      </div>
    </>
  )
}
