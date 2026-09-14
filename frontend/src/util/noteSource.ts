/**
 * 一篇笔记是哪来的：自己写的、从别处导进来的、还是机器生成的。
 *
 * 树上**只用一个图标**表示它，不写文字（docs/sidebar-ia-plan.md §3）：一行已经
 * 扛着展开箭头、图标、标题、撞名时间、事实角标、摄入角标、克隆角标、子节点数，
 * 再塞两段字树就变成表了。而图标那一列本来就在。
 *
 * 为什么值得占这一个字形：库里混着手写、飞书导入、写作计划自动生成的分段时，
 * **「这行是我写的还是机器来的」是唯一一个会改变你怎么读这行的信息**——它决定
 * 你信不信里面的话、该不该直接改它。
 */
const ICON: Record<string, string> = {
  obsidian: 'bx-shape-triangle',
  notion: 'bx-file',
  feishu: 'bx-paper-plane',
  apple: 'bx-notepad',
  evernote: 'bx-bookmark',
  import: 'bx-import',
  plan: 'bx-rocket',          // 写作计划生成的分段：跟无限续写同一个图标
  // 这两个是这一段新长出来的「机器来的」（第 651 轮补）。它们各自都有一个
  // `notes.icon`（幻灯片 bx-slideshow、屏幕活动回顾 bx-desktop）而 `iconOf` 里
  // 用户图标优先，所以图标上看不出差别——**但悬停要说得出它是哪来的**，
  // 那正是 `sourceLabel` 的活。
  slides: 'bx-slideshow',
  journey: 'bx-desktop',
}

const LABEL: Record<string, string> = {
  obsidian: 'Obsidian 导入', notion: 'Notion 导入', feishu: '飞书导入',
  apple: 'Apple 备忘录导入', evernote: 'Evernote 导入', import: '导入',
  plan: '无限续写生成的',
  slides: '这篇的幻灯片版（AI 生成，改笔记再重做）',
  journey: '屏幕活动回顾（AI 生成）',
}

/** 有来源就给它的图标，没有（自己写的）返回空串——由调用方用默认图标。 */
export function sourceIcon(source?: string): string {
  return ICON[(source ?? '').trim()] ?? ''
}

/** 悬停时说清楚这个图标是什么意思；自己写的不说（没必要解释「正常」）。 */
export function sourceLabel(source?: string): string {
  return LABEL[(source ?? '').trim()] ?? ''
}
