/** 粘贴 HTML → Markdown（P10 C3-3）。
 *
 *  从网页 / 飞书 / Notion / Word 复制一段再粘进来，CM6 默认只取剪贴板的 `text/plain`：
 *  标题、粗体、链接、列表**全部丢掉**（实拍 `p10-paste-before`：`<h2>季度目标</h2>…<ul>` 粘进来是
 *  五行光秃秃的字）。Notion / Obsidian / Typora 都会把 HTML 转成自己的格式，这是一个 markdown
 *  编辑器的基本功。
 *
 *  **什么时候不转**：
 *    · 剪贴板没有 `text/html`（终端、纯文本编辑器）——交给 CM 和 lang-markdown（URL 盖在选区上变链接）
 *    · HTML 里没有任何语义标签（VS Code 那种一堆带 style 的 `<span>`）——转出来跟 plain 一样，用 plain 保住原始空白
 *    · 转出来跟 `text/plain` 只差空白——同上
 *  正文永远是一个字符串（anchor 兼容），这里只是决定插进去的是哪一段字。 */
import { EditorView } from '@codemirror/view'

/** 有这些标签才算「带格式」，值得转。 */
const RICH = 'h1,h2,h3,h4,h5,h6,ul,ol,a[href],strong,b,em,i,blockquote,table,img,pre,code,hr,s,del,strike,input[type=checkbox]'

const BLOCK = new Set(['P', 'DIV', 'SECTION', 'ARTICLE', 'HEADER', 'FOOTER', 'MAIN', 'ASIDE', 'NAV', 'FIGURE', 'FIGCAPTION', 'DL', 'DT', 'DD', 'ADDRESS', 'DETAILS', 'SUMMARY'])
const SKIP = new Set(['SCRIPT', 'STYLE', 'HEAD', 'META', 'LINK', 'TITLE', 'TEMPLATE', 'NOSCRIPT', 'BUTTON', 'SELECT', 'TEXTAREA'])

function parse(html: string): HTMLElement {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  return doc.body
}

/** Google Docs 会把整段包在 `<b style="font-weight:normal">` 里；Word 的 `<span style="font-weight:bold">` 才是真粗 */
function isBold(el: Element): boolean {
  const fw = (el as HTMLElement).style?.fontWeight ?? ''
  if (el.tagName === 'STRONG' || el.tagName === 'B') return !/^(normal|[1-4]00)$/.test(fw)
  return /^(bold|bolder|[6-9]00)$/.test(fw)
}
function isItalic(el: Element): boolean {
  if (el.tagName === 'EM' || el.tagName === 'I') return true
  return /italic|oblique/.test((el as HTMLElement).style?.fontStyle ?? '')
}

function esc(s: string): string { return s.replace(/\|/g, '\\|') }
function collapse(s: string): string { return s.replace(/[ \t\r\n ]+/g, ' ') }

/** 行内内容：返回一行（不含换行；`<br>` 变 `\n`）。 */
function inline(node: Node, pre = false): string {
  if (node.nodeType === Node.TEXT_NODE) return pre ? (node.textContent ?? '') : collapse(node.textContent ?? '')
  if (node.nodeType !== Node.ELEMENT_NODE) return ''
  const el = node as Element
  if (SKIP.has(el.tagName)) return ''
  const kids = () => Array.from(el.childNodes).map((c) => inline(c, pre)).join('')
  switch (el.tagName) {
    case 'BR': return '\n'
    case 'IMG': { const src = el.getAttribute('src') ?? ''; if (!src) return ''; return `![${collapse(el.getAttribute('alt') ?? '')}](${src})` }
    case 'A': {
      const href = el.getAttribute('href') ?? ''
      const text = kids().trim()
      if (!href || /^(javascript|#)/.test(href)) return text
      if (!text || text === href) return href
      return `[${text}](${href})`
    }
    case 'CODE': { const t = kids(); return t.trim() ? '`' + t.replace(/`/g, '`') + '`' : '' }
    case 'S': case 'DEL': case 'STRIKE': { const t = kids(); return t.trim() ? `~~${t.trim()}~~` : t }
    case 'INPUT': return ''
    default: {
      let t = kids()
      if (!t.trim()) return t
      // 粗 / 斜：标记贴在字上，两边的空白挪到外面（`** 粗 **` 不是粗体）
      const wrap = (m: string) => { const lead = /^\s*/.exec(t)![0]; const trail = /\s*$/.exec(t)![0]; t = `${lead}${m}${t.trim()}${m}${trail}` }
      if (isBold(el)) wrap('**')
      if (isItalic(el)) wrap('*')
      return t
    }
  }
}

function blocks(node: Node, out: string[], ctx: { indent: string; quote: boolean }) {
  if (node.nodeType === Node.TEXT_NODE) { const t = collapse(node.textContent ?? '').trim(); if (t) out.push(t); return }
  if (node.nodeType !== Node.ELEMENT_NODE) return
  const el = node as Element
  if (SKIP.has(el.tagName)) return
  const tag = el.tagName
  const m = /^H([1-6])$/.exec(tag)
  if (m) { const t = inline(el).trim(); if (t) out.push('#'.repeat(Number(m[1])) + ' ' + t.replace(/\n/g, ' ')); return }
  if (tag === 'HR') { out.push('---'); return }
  if (tag === 'PRE') {
    const code = el.querySelector('code')
    const lang = /language-(\w+)/.exec(code?.className ?? '')?.[1] ?? ''
    out.push('```' + lang + '\n' + (el.textContent ?? '').replace(/\n$/, '') + '\n```')
    return
  }
  if (tag === 'BLOCKQUOTE') {
    const inner: string[] = []
    for (const c of Array.from(el.childNodes)) blocks(c, inner, ctx)
    out.push(inner.join('\n\n').split('\n').map((l) => '> ' + l).join('\n'))
    return
  }
  if (tag === 'UL' || tag === 'OL') {
    const items: string[] = []
    let n = Number(el.getAttribute('start') ?? 1) || 1
    for (const li of Array.from(el.children)) {
      if (li.tagName !== 'LI') continue
      const marker = tag === 'OL' ? `${n++}. ` : '- '
      const box = li.querySelector(':scope > input[type=checkbox], :scope > p > input[type=checkbox], :scope > label > input[type=checkbox]') as HTMLInputElement | null
      const task = box ? (box.checked ? '[x] ' : '[ ] ') : ''
      // 一项里的行内文字 + 嵌套列表分开处理
      const own: string[] = []
      const nested: string[] = []
      for (const c of Array.from(li.childNodes)) {
        if (c.nodeType === Node.ELEMENT_NODE && ((c as Element).tagName === 'UL' || (c as Element).tagName === 'OL')) {
          blocks(c, nested, { indent: ctx.indent + '  ', quote: ctx.quote })
        } else if (c.nodeType === Node.ELEMENT_NODE && BLOCK.has((c as Element).tagName)) {
          const t = inline(c).trim(); if (t) own.push(t)
        } else { own.push(inline(c)) }
      }
      const text = own.join('').replace(/\n+/g, ' ').replace(/\s+/g, ' ').trim()
      let line = ctx.indent + marker + task + text
      if (nested.length) line += '\n' + nested.join('\n')          // 子列表自己带着 indent（上面递归时给的）
      items.push(line)
    }
    out.push(items.join('\n'))
    return
  }
  if (tag === 'TABLE') {
    const rows = Array.from(el.querySelectorAll('tr')).map((tr) => Array.from(tr.children).map((c) => esc(inline(c).replace(/\n/g, ' ').trim())))
    if (!rows.length) return
    const cols = Math.max(...rows.map((r) => r.length))
    const pad = (r: string[]) => { while (r.length < cols) r.push(''); return r }
    const line = (r: string[]) => '| ' + pad(r).join(' | ') + ' |'
    out.push([line(rows[0]), '|' + ' --- |'.repeat(cols), ...rows.slice(1).map(line)].join('\n'))
    return
  }
  if (tag === 'LI') { const t = inline(el).trim(); if (t) out.push('- ' + t); return }
  // 块容器：里面要么全是行内（凑成一段），要么有子块（递归）
  const kids = Array.from(el.childNodes)
  const hasBlockChild = kids.some((c) => c.nodeType === Node.ELEMENT_NODE && (BLOCK.has((c as Element).tagName) || /^(H[1-6]|UL|OL|PRE|BLOCKQUOTE|TABLE|HR|LI)$/.test((c as Element).tagName)))
  if (!hasBlockChild) { const t = inline(el).trim(); if (t) out.push(t); return }
  let run: Node[] = []
  const flush = () => { if (run.length) { const t = run.map((c) => inline(c)).join('').trim(); if (t) out.push(t); run = [] } }
  for (const c of kids) {
    if (c.nodeType === Node.ELEMENT_NODE && (BLOCK.has((c as Element).tagName) || /^(H[1-6]|UL|OL|PRE|BLOCKQUOTE|TABLE|HR|LI)$/.test((c as Element).tagName))) { flush(); blocks(c, out, ctx) }
    else run.push(c)
  }
  flush()
}

/** HTML → Markdown。块之间空一行；行内粗 / 斜 / 代码 / 链接 / 删除线；列表带嵌套和任务框；表格转 GFM。 */
export function htmlToMarkdown(html: string): string {
  const body = parse(html)
  const out: string[] = []
  blocks(body, out, { indent: '', quote: false })
  return out.join('\n\n').replace(/[ \t]+$/gm, '').replace(/\n{3,}/g, '\n\n').trim()
}

/** 这份 HTML 值不值得转：有语义标签、而且转出来跟 plain 不只是空白之差。 */
export function shouldConvertHtml(html: string, plain: string): boolean {
  if (!html) return false
  const body = parse(html)
  if (!body.querySelector(RICH)) return false
  const md = htmlToMarkdown(html)
  if (!md) return false
  const norm = (s: string) => s.replace(/\s+/g, '')
  return norm(md) !== norm(plain)
}

/** 粘贴：有带格式的 HTML 就转成 markdown 插进去；其余交给 CM（图片走 imagePaste，它排在前面）。 */
export const htmlPaste = EditorView.domEventHandlers({
  paste(event, view) {
    const cd = event.clipboardData
    if (!cd) return false
    if (Array.from(cd.items ?? []).some((i) => i.type.startsWith('image/'))) return false
    const html = cd.getData('text/html')
    const plain = cd.getData('text/plain')
    if (!shouldConvertHtml(html, plain)) return false
    const md = htmlToMarkdown(html)
    event.preventDefault()
    const { from, to } = view.state.selection.main
    // 粘在一行中间：块级内容前后各留一个空行，别跟这一行的字黏在一起
    const line = view.state.doc.lineAt(from)
    const multi = md.includes('\n') || /^(#|- |\d+\. |> |```|\|)/.test(md)
    const before = multi && line.text.slice(0, from - line.from).trim() ? '\n\n' : ''
    const after = multi && line.text.slice(to - line.from).trim() ? '\n\n' : ''
    const insert = before + md + after
    view.dispatch({ changes: { from, to, insert }, selection: { anchor: from + insert.length }, userEvent: 'input.paste', scrollIntoView: true })
    return true
  },
})
