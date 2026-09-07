import type { CompletionContext, CompletionResult } from '@codemirror/autocomplete'
import * as api from '../api'

/**
 * Type "@" + a few characters to search the knowledge base and insert a
 * citation inline -- this is the "manual, verifiable" counterpart to the
 * automatic grounding in magic-tap/edit. Competitive research kept surfacing
 * "AI can't find something that's clearly in my notes" as the #1 AI
 * complaint across Notion/Copilot/etc.; giving the user an explicit,
 * always-available search-and-cite action means they're never stuck hoping
 * the automatic path picks up a fact -- they can just go get it.
 *
 * Citations are inserted as plain text (`[事实：... · 日期]`), not a custom
 * widget/reference token: the document must stay a single plain string for
 * the anchor-based revision system, so there's no round-trip-safe way to
 * embed a "live" reference object without breaking that contract.
 */
export async function recallSource(context: CompletionContext): Promise<CompletionResult | null> {
  const match = context.matchBefore(/@[一-鿿\w][一-鿿\w ]{0,40}$/)
  if (!match) return null
  const query = match.text.slice(1).trim()
  if (!query) return null

  let facts: api.Fact[]
  try {
    const res = await api.recall(query, 8)
    facts = res.facts
  } catch {
    return null
  }
  if (context.aborted) return null
  if (facts.length === 0) {
    return {
      from: match.from,
      to: match.to,
      options: [{ label: `知识库里没找到跟"${query}"相关的记录`, apply: () => {} }],
      filter: false,
    }
  }

  return {
    from: match.from,
    to: match.to,
    filter: false,
    options: facts.map((f) => ({
      label: f.text.length > 44 ? f.text.slice(0, 44) + '…' : f.text,
      detail: f.when || undefined,
      info: () => {
        const div = document.createElement('div')
        div.style.maxWidth = '340px'
        div.style.whiteSpace = 'pre-wrap'
        div.style.fontSize = '13px'
        div.textContent = f.sources.length ? `${f.text}\n\n原文：\n${f.sources.join('\n')}` : f.text
        return div
      },
      apply: (view, _completion, from, to) => {
        const citation = `[事实：${f.text}${f.when ? ' · ' + f.when : ''}]`
        view.dispatch({
          changes: { from, to, insert: citation },
          selection: { anchor: from + citation.length },
        })
      },
    })),
  }
}
