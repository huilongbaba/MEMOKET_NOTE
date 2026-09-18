/**
 * ⌥ 悬停 = 来龙去脉贴在词边（P16，agent-native-editor §3.3「⌥ 悬停任何词就是来龙去脉，结果贴在词边上」；
 * 场景 B；痛点 11 / 12；判据 2）。
 *
 * 按住 ⌥ 把鼠标停在一个词上 ≥ 400ms → `onOpen(词, 词的矩形, 'hover')`，上层画卡（`components/TraceCard`，零模型）。
 * 键盘同一条路：光标停在词上按 ⌥↩ → `onOpen(词, …, 'key')`（a11y 闸：悬停能做的键盘也要能做）。
 * 选中了一段、鼠标在选区里 → 用选区当「词」。
 *
 * 词怎么切：中文靠 `Intl.Segmenter` 分词（「众筹页面定在3月12号上线」→ 众筹 / 页面 / 定 / 在 / …），
 * 英文 / 数字按词；标点 / 空白上没有词。没有分词器（老运行时）退化成「连续的字母数字」。
 */
import { EditorView, keymap } from '@codemirror/view'

export type AltHoverRange = { from: number; to: number; focus?: number }
export type AltHoverOpen = (phrase: string, anchor: DOMRect | null, reason: 'hover' | 'key', range: AltHoverRange) => void

export const HOVER_MS = 400
export const MAX_PHRASE = 24
/** 分词器不认识的词（「众筹」不在 ICU 的中文词典里，切成 众 | 筹）：把相邻的单字段连成一串交给知识库去认，最多这么多字 */
export const MAX_RUN = 6
/** `focus` = 鼠标停的那个字在 text 里的偏移：只在「单字连成串」时给，知识库据此挑出真正的词（`util/traceCard.pickTerm`） */
export type Phrase = { from: number; to: number; text: string; focus?: number }

let seg: Intl.Segmenter | null | undefined
function segmenter(): Intl.Segmenter | null {
  if (seg === undefined) {
    try { seg = new Intl.Segmenter('zh-Hans', { granularity: 'word' }) } catch { seg = null }
  }
  return seg
}

const isCjk = (s: string) => /^[一-鿿]$/.test(s)

/** 一行文本里第 col 个字符落在哪个词上（纯函数，可测）。标点 / 空白上返回 null；词长封顶 MAX_PHRASE。
 *
 *  分词器切出来是**单个汉字**时（词典里没有这个词：实测「众筹」→ 众 | 筹，「服从」「外部」「节点」都对），
 *  把左右相邻的单字段连成一串（遇到多字词 / 非汉字 / 标点就停，封顶 MAX_RUN），带上 focus 交给知识库去认整词。 */
export function phraseAt(line: string, col: number): Phrase | null {
  if (col < 0 || col >= line.length) return null
  const s = segmenter()
  if (s) {
    const parts = [...s.segment(line)]
    const k = parts.findIndex((p) => col >= p.index && col < p.index + p.segment.length)
    if (k < 0 || !parts[k].isWordLike) return null
    const hit = parts[k]
    if (!isCjk(hit.segment)) {
      const text = hit.segment.slice(0, MAX_PHRASE)
      return { from: hit.index, to: hit.index + text.length, text }
    }
    const single = (p: Intl.SegmentData | undefined) => !!p && !!p.isWordLike && isCjk(p.segment)
    let a = k
    let b = k
    while (b + 1 < parts.length && single(parts[b + 1]) && b - a + 1 < MAX_RUN) b++
    while (a > 0 && single(parts[a - 1]) && b - a + 1 < MAX_RUN) a--
    const from = parts[a].index
    const to = parts[b].index + parts[b].segment.length
    return { from, to, text: line.slice(from, to), focus: col - from }
  }
  const re = /[\p{L}\p{N}_]+/gu
  let m: RegExpExecArray | null
  while ((m = re.exec(line))) {
    if (col >= m.index && col < m.index + m[0].length) {
      const text = m[0].slice(0, MAX_PHRASE)
      return { from: m.index, to: m.index + text.length, text }
    }
  }
  return null
}

/** 文档位置 pos 上的词：选区里就是选区（一行以内、≤ 80 字），否则按分词；停在词尾（光标在词后面）也算这个词。 */
export function phraseAtPos(view: EditorView, pos: number): Phrase | null {
  const sel = view.state.selection.main
  if (!sel.empty && pos >= sel.from && pos <= sel.to) {
    const text = view.state.doc.sliceString(sel.from, sel.to).trim()
    if (text && text.length <= 80 && !text.includes('\n')) return { from: sel.from, to: sel.to, text }
  }
  const line = view.state.doc.lineAt(pos)
  const col = pos - line.from
  const p = phraseAt(line.text, col) ?? (col > 0 ? phraseAt(line.text, col - 1) : null)
  return p && { from: line.from + p.from, to: line.from + p.to, text: p.text, focus: p.focus }
}

function anchorOf(view: EditorView, p: Phrase): DOMRect | null {
  const a = view.coordsAtPos(p.from)
  if (!a) return null
  const b = view.coordsAtPos(p.to, -1)
  const right = b && Math.abs(b.top - a.top) < 2 ? b.right : a.right
  return new DOMRect(a.left, a.top, Math.max(1, right - a.left), a.bottom - a.top)
}

export function altHover(onOpen: AltHoverOpen) {
  let timer: ReturnType<typeof setTimeout> | null = null
  let pending: Phrase | null = null
  const cancel = () => { if (timer) { clearTimeout(timer); timer = null } pending = null }
  const open = (view: EditorView, p: Phrase, reason: 'hover' | 'key') =>
    onOpen(p.text, anchorOf(view, p), reason, { from: p.from, to: p.to, focus: p.focus })

  const handlers = EditorView.domEventHandlers({
    mousemove(e, view) {
      if (!e.altKey) { cancel(); return false }
      const pos = view.posAtCoords({ x: e.clientX, y: e.clientY })
      const p = pos == null ? null : phraseAtPos(view, pos)
      if (!p) { cancel(); return false }
      if (pending && pending.from === p.from && pending.to === p.to) return false   // 还停在同一个词上：让计时器走完
      cancel()
      pending = p
      timer = setTimeout(() => {
        timer = null
        if (pending) { open(view, pending, 'hover'); pending = null }
      }, HOVER_MS)
      return false
    },
    mouseleave() { cancel(); return false },
    keyup(e) { if (e.key === 'Alt') cancel(); return false },
  })
  // ⌥↩：光标所在的词。排在 defaultKeymap 前面（MarkdownEditor 里挂在早的位置）
  const keys = keymap.of([{ key: 'Alt-Enter', run: (view) => {
    const p = phraseAtPos(view, view.state.selection.main.head)
    if (!p) return false
    open(view, p, 'key')
    return true
  } }])
  return [handlers, keys]
}
