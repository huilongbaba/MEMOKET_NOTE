/** 搜索卡上的那行摘要：有命中就给命中处前后各一截，没有就给 null（调用方
 * 退回第一行）。实拍搜「创业」，六张卡的摘要全是各自第一行，没一张能看出
 * 命中在哪——标题不含关键词的那张（harness 测试）尤其莫名其妙。Trilium 的
 * 快速搜索是把命中片段带高亮显示的。 */
export type Snippet = { before: string; hit: string; after: string }

/** `before` 单独给：侧栏卡片一行 nowrap 只装得下十几个字，前面留 28 字命中就被省略号吃掉，
 *  卡片上只见「…“调整方案”或“停止推进”。矩阵不能只保留…」看不到 EVT 在哪（第 226 轮实拍）。 */
export function matchSnippet(content: string, query: string, span = 28, before = span): Snippet | null {
  const q = query.trim()
  if (!q) return null
  // 标题井号 / 列表符号在一行摘要里只是噪声（实拍「# 创业一年回顾 ## 时间线…」）
  const text = content.replace(/^\s*(#{1,6}|[-*>]|\d+\.)\s+/gm, '').replace(/\s+/g, ' ')
  const i = text.toLowerCase().indexOf(q.toLowerCase())
  if (i < 0) return null
  const start = Math.max(0, i - before)
  const end = Math.min(text.length, i + q.length + span)
  return {
    before: (start > 0 ? '…' : '') + text.slice(start, i),
    hit: text.slice(i, i + q.length),
    after: text.slice(i + q.length, end) + (end < text.length ? '…' : ''),
  }
}
