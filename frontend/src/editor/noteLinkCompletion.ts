import type { CompletionContext, CompletionResult } from '@codemirror/autocomplete'
import * as api from '../api'
import { displayTitle } from '../util/displayTitle'

/**
 * `[[` + 几个字 → 搜笔记标题，选中插成 `[标题](note://<id>)`。
 *
 * 用标准 markdown 链接而不是 `[[wiki]]`：正文导出到别处仍是合法链接，
 * 后端 `store.note_links_in` 与反链查询认的也是 `note://<id>`。
 * Trilium 的内部链接（`~` / 链接对话框）对应的就是这条路。
 */
export async function noteLinkSource(context: CompletionContext): Promise<CompletionResult | null> {
  const match = context.matchBefore(/\[\[([^\]\n]{0,40})$/)
  if (!match) return null
  const query = match.text.slice(2).trim()
  let notes: api.Note[]
  try { notes = await api.listNotes(query) } catch { return null }
  if (context.aborted) return null
  // 只按标题（或无标题时的正文首行）匹配，别把正文命中也混进来——链接的是「一篇」
  const q = query.toLowerCase()
  const hits = notes
    .filter((n) => !q || displayTitle(n).toLowerCase().includes(q))
    .slice(0, 8)
  if (hits.length === 0) {
    return { from: match.from, to: match.to, filter: false,
             options: [{ label: query ? `没有叫"${query}"的笔记` : '输入几个字搜笔记标题', apply: () => {} }] }
  }
  return {
    from: match.from,
    to: match.to,
    filter: false,
    options: hits.map((n) => ({
      label: displayTitle(n),
      detail: n.updated_at.slice(0, 10),
      apply: (view, _c, from, to) => {
        const text = `[${displayTitle(n)}](note://${n.id})`
        view.dispatch({ changes: { from, to, insert: text }, selection: { anchor: from + text.length } })
      },
    })),
  }
}
