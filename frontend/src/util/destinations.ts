/**
 * 启动栏上的**去处**（destination）——左栏那一竖排里「打开某一页」的那几个。
 *
 * **为什么要有这么一份东西**（第 779 轮 / P21）：屏幕活动在启动栏、欢迎页、
 * 菜单栏托盘、「文件」菜单四个地方都有入口，唯独 **⌘K 里没有**——而
 * `docs/daily-journey-plan.md` §8.4 明写「⌘K 加『今天的屏幕活动』」。
 * 靠 ⌘K 导航的人因此找不到这个功能。顺手查出来「写作 Skill」也一样不在。
 *
 * **不是漏了一行，是这两处各写各的。** 所以这一版把去处收成一份，
 * 启动栏和 ⌘K **都从这里生成**：加一个新去处 = 改这一个文件，
 * 两处同时有；漏不掉，也不需要谁去记得同步。
 * `scripts/check-destinations.mts` 守的正是「两边都还在从这儿生成」——
 * 闸门盯的是**来源**，不是两份清单字面上一不一样（那种闸门加个入口要改两处，
 * 跟当初漏掉屏幕活动是同一类失败）。
 *
 * 启动栏上还有三个按钮不在这儿：新建笔记 / 今天的日记 / 全局搜索。
 * 它们是**动作**不是去处（各自有自己的 handler，⌘K 里也各自有一项，
 * 「全局搜索」就是 ⌘K 自己）。闸门只管去处这一类。
 */

export type Destination = {
  /** 虚拟页 id，`open-virtual` 事件的 detail */
  id: string
  /** 页签标题，也是启动栏按钮的可读名字 */
  name: string
  icon: string
  /** 启动栏按钮的 title（可以比名字长，说清楚这一页是干什么的） */
  hint: string
  /** ⌘K 里显示的名字。留空就用 `name`——**⌘K 是搜出来的，名字里要带人会打的词**
   *  （「今天」「屏幕」都该找得到屏幕活动）。 */
  palette?: string
  /** 在启动栏的哪一段：`top` = 分隔线上面，`foot` = 下面（设置 / Skill 这种
   *  「特殊笔记」），`palette` = **不在启动栏上，只在 ⌘K 里**（最近删除）。
   *  反过来的那一半没有：**⌘K 里没有的去处不许有**，那正是这份清单的由来。 */
  where: 'top' | 'foot' | 'palette'
}

export const DESTINATIONS: Destination[] = [
  { id: 'kb', name: '知识库', icon: 'bx-data', where: 'top',
    hint: '知识库：搜索事实、查看主题地图和定期回顾' },
  { id: 'app:import', name: '导入', icon: 'bx-import', where: 'top',
    hint: '导入：.md 文件 / Obsidian / Evernote / Notion / Apple Notes / 批量文件' },
  { id: 'app:journey', name: '屏幕活动', icon: 'bx-desktop', where: 'top',
    hint: '屏幕活动：今天都在做什么', palette: '今天的屏幕活动' },
  { id: 'app:skills', name: '写作 Skill', icon: 'bx-extension', hint: '写作 Skill', where: 'foot' },
  { id: 'app:settings', name: '设置', icon: 'bx-cog', hint: '设置：LLM 供应商', where: 'foot' },
  { id: 'app:trash', name: '最近删除', icon: 'bx-trash', where: 'palette',
    hint: '最近删除（30 天内可找回）', palette: '最近删除（30 天内可找回）' },
]

/** ⌘K 里那一条的名字。 */
export const paletteLabel = (d: Destination): string => d.palette ?? d.name
