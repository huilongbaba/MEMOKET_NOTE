/** 虚拟页（知识库 / 设置这些不是笔记的标签页）的几条纯规则。从 App.tsx 挪出来（第 466 轮）：
 *  App.tsx 三千多行，这些不碰状态的函数放这儿才测得到。 */

export const VIRTUAL_LABELS: Record<string, string> = {
  'app:settings': '设置', 'app:skills': '写作 Skill', 'app:import': '导入', 'app:trash': '最近删除', 'app:journey': '屏幕活动',
  kb: '知识库', 'kb:graph': '主题地图', 'kb:digest': '定期回顾', 'kb:timeline': '时间线',
  'kb:topics': '主题', 'kb:entities': '实体', 'kb:recent': '最近摄入',
  'kb:merges': '可能是同一个',
}

/** 认识的知识库虚拟 id 形状（`kb:facts?topic=x` 也算——重启时带查询串的事实表标签不能被当成不认识的收掉） */
export const KNOWN_KB_RE = /^kb:(topic|entity|unit|material|fact|facts|etype)(:|\?|$)/

/** 知识库是一块工作区，不是一组彼此独立的笔记标签。 */
export function isKbVirtual(id: string): boolean {
  return id === 'kb' || id.startsWith('kb:')
}

export type VirtualTabLike = { id: string; noteId: string; title: string }

/**
 * 打开普通虚拟页时沿用原来的「一页一个标签」。知识库内部导航则始终复用同一个
 * 标签，并顺手收掉旧版本留在 localStorage 里的多个知识库标签。
 */
export function syncVirtualTab<T extends VirtualTabLike>(
  tabs: T[], next: T, activeTabId: string | null,
): T[] {
  if (!isKbVirtual(next.noteId)) {
    const found = tabs.find((t) => t.noteId === next.noteId)
    if (!found) return [...tabs, next]
    return found.title === next.title
      ? tabs
      : tabs.map((t) => (t.id === found.id ? { ...t, title: next.title } : t))
  }

  const kbTabs = tabs.filter((t) => isKbVirtual(t.noteId))
  const keep = kbTabs.find((t) => t.id === activeTabId) ?? kbTabs[0]
  if (!keep) return [...tabs, next]
  return tabs.flatMap((t) => {
    if (t.id === keep.id) return [{ ...t, noteId: next.noteId, title: next.title }]
    return isKbVirtual(t.noteId) ? [] : [t]
  })
}

/** 这个虚拟 id 认不认识：固定页、知识库各种节点、app:* 特殊页 */
export function isKnownVirtual(id: string): boolean {
  return !!VIRTUAL_LABELS[id] || KNOWN_KB_RE.test(id) || id.startsWith('app:')
}

/** 带筛选的事实表叫什么：「事实表 · work」（查询串的值拼上）。标签 / 分屏头 / 面包屑三处用同一个，
 *  不然从树上尾巴行「还有 N 条 · 去事实表看」进来的页面会顶着那句入口的话当名字。 */
export function factsLabel(id: string): string | undefined {
  if (!id.startsWith('kb:facts')) return undefined
  return '事实表' + (id.includes('?') ? ' · ' + Array.from(new URLSearchParams(id.split('?')[1]).values()).filter(Boolean).join(' · ') : '')
}

/** First non-empty line of a note's content, syntax markers stripped, for
 * the sidebar preview -- strip rather than render so it stays plain text
 * in a one-line ellipsis instead of showing raw "## " or "- " noise. */
export function previewLine(content: string, skip = ''): string {
  // 照抄后端 store._first_body_line（第 544 轮对齐，scripts/check-preview-parity 拿样本对拍）：
  // 跳过跟显示名一样的那一行（占位标题的笔记显示名就是正文第一行）；代码围栏 / 图片行不算；
  // 剥列表符 / 井号 / 强调记号；一个字的行不算；优先正文行，一行正文都没有才退回第一个小标题；60 字。
  // 之前前端只是「第一行不等于标题的」，`# 小标题` 和 `![图](…)` 都会被当预览印出来，
  // ⌘K 笔记组（服务端 first_body）和标签组（本地算）同名消歧给的还不是同一截。
  const lines = (content || '').split('\n').slice(0, 60).map((l) => l.trim())
  const clean = (t: string) => t.replace(/^([-*>+]|\d+\.|#{1,6})\s*/, '').replace(/[*_`[\]]/g, '').trim()
  let shown = (skip || '').trim()
  if (shown === '' || shown === '未命名' || shown === 'Untitled' || shown === 'note') shown = clean(lines.find((l) => l) ?? '')
  const body: string[] = []; const heads: string[] = []
  let fenced = false
  for (const l of lines) {
    if (l.startsWith('```')) { fenced = !fenced; continue }   // 围栏里的是代码不是正文
    if (fenced || !l || l.startsWith('![')) continue
    const c = clean(l)
    if (c.length <= 1 || c.toLowerCase() === shown.toLowerCase()) continue
    ;(l.startsWith('#') ? heads : body).push(c)
  }
  return (body[0] ?? heads[0] ?? '').slice(0, 60)
}

/** 懒加载的虚拟节点在树上挂在哪个分类下（面包屑拼父链用） */
export function virtualParentOf(id: string): string | undefined {
  if (id === 'kb:merges') return 'kb:entities'     // 合并收件箱挂在实体下面，面包屑才回得去
  return ({ entity: 'kb:entities', etype: 'kb:entities', topic: 'kb:topics', month: 'kb:timeline', unit: 'kb:recent', material: 'kb:recent' } as Record<string, string>)[id.split(':')[1]]
}
