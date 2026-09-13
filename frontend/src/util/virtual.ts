/** 虚拟页（知识库 / 设置这些不是笔记的标签页）的几条纯规则。从 App.tsx 挪出来（第 466 轮）：
 *  App.tsx 三千多行，这些不碰状态的函数放这儿才测得到。 */

export const VIRTUAL_LABELS: Record<string, string> = {
  'app:settings': '设置', 'app:skills': '写作 Skill', 'app:import': '导入', 'app:trash': '最近删除',
  kb: '知识库', 'kb:graph': '主题地图', 'kb:digest': '定期回顾', 'kb:timeline': '时间线',
  'kb:topics': '主题', 'kb:entities': '实体', 'kb:recent': '最近摄入',
}

/** 认识的知识库虚拟 id 形状（`kb:facts?topic=x` 也算——重启时带查询串的事实表标签不能被当成不认识的收掉） */
export const KNOWN_KB_RE = /^kb:(topic|entity|unit|material|fact|facts|etype)(:|\?|$)/

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
  // 第一行常常就是标题本身（「# 会议纪要 10」）——搜索卡上再印一遍没意义，
  // 跳过跟标题一样的那行，取下一行
  // 先 trim 再剥记号：整篇缩进的笔记（「    ## 时间线」，第 362 轮实拍）不然会露出「## 」；
  // `#` 后面没空格的也剥（后端 _first_body_line 是 strip 后 \s*，两边一致）
  const clean = (l: string) => l.trim().replace(/^#{1,6}\s*/, '').replace(/^[-*>]\s+/, '').trim()
  const lines = content.split('\n').map(clean).filter((l) => l)
  const skipNorm = skip.trim().replace(/\s+/g, '')
  return lines.find((l) => l.replace(/\s+/g, '') !== skipNorm) ?? lines[0] ?? ''
}
