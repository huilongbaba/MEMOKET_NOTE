/** 外部把整篇正文塞进来时，算出最小的一处改动。
 *
 * 之前是「整篇替换 + 光标挪到文末」：流式续写每来一片就整篇换一遍，光标和视口
 * 一起被拽到文末——往中间插（从光标处续写、定向续写）根本没法看；轮次高亮、
 * 折叠这些按位置映射的装饰也跟着全量重算。这里取公共前缀 / 后缀，只 dispatch
 * 中间那一段，选区由 CodeMirror 自己映射。 */
export function minimalChange(oldText: string, newText: string): { from: number; to: number; insert: string } | null {
  if (oldText === newText) return null
  const minLen = Math.min(oldText.length, newText.length)
  let start = 0
  while (start < minLen && oldText.charCodeAt(start) === newText.charCodeAt(start)) start++
  let endOld = oldText.length
  let endNew = newText.length
  while (endOld > start && endNew > start && oldText.charCodeAt(endOld - 1) === newText.charCodeAt(endNew - 1)) { endOld--; endNew-- }
  // 别把代理对从中间切开（emoji 等四字节字符）
  if (start > 0 && start < minLen && (oldText.charCodeAt(start - 1) & 0xfc00) === 0xd800) start--
  return { from: start, to: endOld, insert: newText.slice(start, endNew) }
}
