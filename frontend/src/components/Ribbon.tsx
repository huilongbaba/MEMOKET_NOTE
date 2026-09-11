/**
 * Ribbon —— 标题下面那条可折叠的标签带，放**这篇笔记的元数据**。
 *
 * 对标 Trilium 的 ribbon（基本属性、笔记路径、附件…）。我们往里放的第一件
 * 东西是**写作骨架**，理由在 docs/product-north-star.md 判据 3：
 *
 *   > 高度自动化 = 自主规划、自主执行、检查结果。
 *   > 所以**计划要看得见**。
 *
 * 骨架就是这次自动化的计划——它属于笔记的元数据区，跟正文一起被看见，而不是
 * 右栏某个要切过去才有的面板。把计划藏起来，用户就只能看到一个转圈的
 * 指示器，那等于什么都没说。
 *
 * 抄它的一个细节：**标签带不因为当前笔记没内容就消失**（Trilium 的
 * `alwaysShown`）。消失的话，在笔记之间切换时整条带子会自己变形，鼠标下面
 * 的东西会跑掉。
 */
import { useEffect, useState, type ReactNode } from 'react'

import ContextMenu, { type MenuAt, type MenuItem } from './ContextMenu'

export type RibbonTab = {
  id: string
  title: string
  icon?: string
  /** 有内容时给个角标，让用户不用点开就知道里面有东西 */
  badge?: string | number
  /** 换笔记时要不要自动展开。照 Trilium Ribbon.tsx:46-51：取第一个 activate
   *  为真的 tab 展开，都不满足才收起。写作骨架有内容时**必须**展开——判据 3
   *  说计划要看得见，一个折叠起来的计划跟转圈的指示器没区别。 */
  activate?: boolean
  body: ReactNode
}

export default function Ribbon({
  tabs, defaultOpen, noteKey, actions,
}: { tabs: RibbonTab[]; defaultOpen?: string; noteKey?: string; actions?: MenuItem[] }) {
  // 右端的三点菜单（Trilium NoteActions）：导出 / 复制 / 专注模式这些低频杂项
  // 收进来，不跟 magic tap / 智能续写抢同一行的注意力（判据 1 的反面）
  const [menuAt, setMenuAt] = useState<MenuAt | null>(null)
  // undefined = 收起。收起是默认：正文才是主角，元数据是需要时才展开的东西。
  const [open, setOpen] = useState<string | undefined>(defaultOpen)

  // 换笔记时按 activate 规则重算；同一篇里用户手动收起/展开的不动。
  const activateId = tabs.find((t) => t.activate)?.id
  useEffect(() => {
    setOpen(defaultOpen ?? activateId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noteKey, defaultOpen, activateId === undefined])

  if (tabs.length === 0) return null

  return (
    <div className="ribbon">
      <div className="ribbon-strip" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={open === t.id}
            className={'ribbon-tab' + (open === t.id ? ' active' : '')}
            onClick={() => setOpen(open === t.id ? undefined : t.id)}
          >
            {t.icon && <span className="ribbon-icon">{t.icon.startsWith('bx-') ? <i className={'bx ' + t.icon} /> : t.icon}</span>}
            <span>{t.title}</span>
            {t.badge !== undefined && t.badge !== 0 && (
              <span className="ribbon-badge">{t.badge}</span>
            )}
          </button>
        ))}
        {actions && actions.length > 0 && (
          <button className="ribbon-actions" title="更多操作" aria-haspopup="menu"
                  onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setMenuAt({ x: r.right - 200, y: r.bottom + 4 }) }}>
            ⋯
          </button>
        )}
        {menuAt && actions && <ContextMenu at={menuAt} items={actions} onClose={() => setMenuAt(null)} />}
      </div>
      {open && (
        <div className="ribbon-body" role="tabpanel">
          {tabs.find((t) => t.id === open)?.body}
        </div>
      )}
    </div>
  )
}
