import type { CompletionContext, CompletionResult } from '@codemirror/autocomplete'
import * as api from '../api'
import { displayTitle } from '../util/displayTitle'
import { fmtDate } from '../util/time'

/**
 * `[[` + 几个字 → 搜笔记标题，选中插成 `[标题](note://<id>)`。
 *
 * 用标准 markdown 链接而不是 `[[wiki]]`：正文导出到别处仍是合法链接，
 * 后端 `store.note_links_in` 与反链查询认的也是 `note://<id>`。
 * Trilium 的内部链接（`~` / 链接对话框）对应的就是这条路。
 */
/** 同名笔记只靠日期分不开（实拍三篇「创业一年回顾」并排）：重名的补一截正文首句。 */
export function disambiguate(hits: { title?: string; content?: string; preview?: string; first_body?: string; updated_at: string }[]): string[] {
  const names = hits.map(displayTitle)
  const dup = new Set(names.filter((t, i) => names.indexOf(t) !== i))
  return hits.map((n, i) => {
    const date = fmtDate(n.updated_at)
    if (!dup.has(names[i])) return date
    if (n.first_body) return `${date} · ${n.first_body.slice(0, 28)}${n.first_body.length > 28 ? '…' : ''}`   // 服务端算好的第一行正文
    // 小标题（「时间线与里程碑」）几篇都一样，分不开——优先取正文行，标题行只兜底
    // 只有 preview（前 80 字）时最后一行可能被截在半截（「## 时间线」剩个「#」）：整行去掉
    const src = n.content ?? n.preview ?? ''
    const lines = src.split('\n')
    if (n.content == null && lines.length > 1) lines.pop()
    const clean = (l: string) => l.replace(/^\s*(#{1,6}|[-*>]|\d+\.)\s+/, '').replace(/[*_`\[\]#]/g, '').trim()
    const pick = (ls: string[]) => ls.map(clean).filter((l) => l.length > 1 && l !== names[i])
    const body = pick(lines.filter((l) => !/^\s*#{1,6}\s/.test(l)))
    const heads = pick(lines.filter((l) => /^\s*#{1,6}\s/.test(l)))
    const first = body.find((l) => l.length > 6) ?? body[0] ?? heads[0] ?? ''
    return first ? `${date} · ${first.slice(0, 28)}${first.length > 28 ? '…' : ''}` : date
  })
}

export async function noteLinkSource(context: CompletionContext): Promise<CompletionResult | null> {
  const match = context.matchBefore(/\[\[([^\]\n]{0,40})$/)
  if (!match) return null
  const query = match.text.slice(2).trim()
  let notes: api.NoteBrief[]
  try { notes = (await api.listNotesBrief(query)).notes } catch { return null }
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
  const details = disambiguate(hits)
  return {
    from: match.from,
    to: match.to,
    filter: false,
    options: hits.map((n, i) => ({
      label: displayTitle(n),
      detail: details[i],
      apply: (view, _c, from, to) => {
        const text = `[${displayTitle(n)}](note://${n.id})`
        view.dispatch({ changes: { from, to, insert: text }, selection: { anchor: from + text.length } })
      },
    })),
  }
}
