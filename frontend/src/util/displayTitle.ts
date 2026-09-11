/**
 * 一篇笔记显示成什么名字。树、标签页、面包屑都用这一个——三处各算一遍就会
 * 出现「树上叫 A、标签上叫 未命名」。
 *
 * 旧界面建笔记时把标题填成了「未命名」，真实库里 18 篇有 15 篇是这个值。
 * 一列二十个「未命名」没法用，所以这种情况退回正文首行。
 *
 * **只在显示这一层做，不改库里的值**：把它当真标题写回去，就等于替用户
 * 给笔记起了名，而他可能只是还没想好。
 */
export const PLACEHOLDER = new Set(['', '未命名', 'Untitled', 'note'])
export const isPlaceholderTitle = (t: string) => PLACEHOLDER.has((t ?? '').trim())

export function displayTitle(n: { title?: string; preview?: string; content?: string }): string {
  const t = (n.title ?? '').trim()
  if (!PLACEHOLDER.has(t)) return t
  const firstLine = (n.preview ?? n.content ?? '')
    .split('\n')
    .map((l) => l.replace(/^#+\s*/, '').trim())
    .find((l) => l.length > 0)
  return firstLine ? firstLine.slice(0, 60) : '未命名'
}
