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
import { useState, type ReactNode } from 'react'

export type RibbonTab = {
  id: string
  title: string
  icon?: string
  /** 有内容时给个角标，让用户不用点开就知道里面有东西 */
  badge?: string | number
  body: ReactNode
}

export default function Ribbon({
  tabs, defaultOpen,
}: { tabs: RibbonTab[]; defaultOpen?: string }) {
  // undefined = 收起。收起是默认：正文才是主角，元数据是需要时才展开的东西。
  const [open, setOpen] = useState<string | undefined>(defaultOpen)

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
            {t.icon && <span className="ribbon-icon">{t.icon}</span>}
            <span>{t.title}</span>
            {t.badge !== undefined && t.badge !== 0 && (
              <span className="ribbon-badge">{t.badge}</span>
            )}
          </button>
        ))}
      </div>
      {open && (
        <div className="ribbon-body" role="tabpanel">
          {tabs.find((t) => t.id === open)?.body}
        </div>
      )}
    </div>
  )
}
