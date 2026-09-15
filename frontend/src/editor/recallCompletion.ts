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
 * Citations are inserted as plain text (`原文 [fact-id]`), not a custom
 * widget/reference token: the document must stay a single plain string for
 * the anchor-based revision system, so there's no round-trip-safe way to
 * embed a "live" reference object without breaking that contract. The
 * `[fact-id]` tail is what the backend's `store.cited_fact_ids` and the
 * editor's `factCite` plugin both recognise -- 三条「找到并引用」的路径
 * （@ 补全 / 相关记忆 / ⌘K）插的必须是同一种东西，否则只有一条会算成引用。
 */
export async function recallSource(context: CompletionContext): Promise<CompletionResult | null> {
  const match = context.matchBefore(/@[一-鿿\w][一-鿿\w ]{0,40}$/)
  if (!match) return null
  const query = match.text.slice(1).trim()
  if (!query) return null

  let facts: api.Fact[]
  let kbEmpty = false
  try {
    const res = await api.recall(query, 8)
    facts = res.facts
    kbEmpty = !!res.kb_empty
  } catch {
    return null
  }
  if (context.aborted) return null
  if (facts.length === 0) {
    // **「库是空的」跟「这一次没查到」得说成两件事。** 前者换多少个说法都是空，
    // 该说的是「去导入」；后者才值得换个词再试。第 677 轮实拍：一个还没导过
    // 任何东西的新用户按 `@样机`，看到的是「知识库里没找到跟"样机"相关的记录」
    // ——听起来像是这个词不对。（写作闭环里的同一个坑在第 676 轮修过。）
    return {
      from: match.from,
      to: match.to,
      options: [{
        label: kbEmpty
          ? '知识库还是空的——先导入会议记录或笔记，这里才有东西可引'
          : `知识库里没找到跟"${query}"相关的记录`,
        apply: () => {},
      }],
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
        const citation = `${f.text} [${f.id}]`
        view.dispatch({
          changes: { from, to, insert: citation },
          selection: { anchor: from + citation.length },
        })
      },
    })),
  }
}
