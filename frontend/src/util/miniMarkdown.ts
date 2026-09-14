/** 日报那一小块 markdown 的解析。**不是通用 markdown 渲染器，也不想是。**
 *
 * 为什么不复用 `MarkdownEditor readOnly`：那是 CM6 的**源码视图**，`##` 和
 * `**` 会原样显示出来，标题按编辑器的字号排——一屏只装得下半份日报，而这一页
 * 的规矩是「报告在上、证据在下」，报告把证据顶到屏幕外就等于没有证据。
 * 「阶段回顾」那个面板用它是因为那儿只有一份内容、可以随便占地方。
 * **复用逻辑不复用排版**（第 630 轮那条教训）。
 *
 * 认的东西刚好是日报会产出的那几样（提示词里规定死的）：`## 小标题`、
 * `- 列表项`、`**粗**`、`` `代码` ``、普通段落。别的一律当纯文本——
 * 宁可少认一种写法，也不要在一份回顾里冒出半截没渲染的标记。
 *
 * 后来加了**代码围栏**：幻灯片会带 ```mermaid 图，而不认围栏的话整块会被压成
 * 一行带反引号的乱码（第 650 轮导出 PDF 实拍，第 7 页就是那样）。围栏里的内容
 * 原样留着、连换行一起——那正是「不认的东西当纯文本」这条规矩本来的意思。
 */

export type Inline = { t: 'text' | 'b' | 'code'; s: string }
export type Block =
  | { kind: 'h'; parts: Inline[] }
  | { kind: 'p'; parts: Inline[] }
  | { kind: 'ul'; items: Inline[][] }
  /** 代码围栏。`lang` 是围栏后面那个词（mermaid / python / 空）。 */
  | { kind: 'pre'; lang: string; text: string }

const INLINE = /\*\*([^*]+)\*\*|`([^`]+)`/g

export function parseInline(line: string): Inline[] {
  const out: Inline[] = []
  let last = 0
  for (const m of line.matchAll(INLINE)) {
    if (m.index! > last) out.push({ t: 'text', s: line.slice(last, m.index) })
    out.push(m[1] !== undefined ? { t: 'b', s: m[1] } : { t: 'code', s: m[2] })
    last = m.index! + m[0].length
  }
  if (last < line.length) out.push({ t: 'text', s: line.slice(last) })
  return out.length ? out : [{ t: 'text', s: line }]
}

export function parseMini(md: string): Block[] {
  const out: Block[] = []
  let para: string[] = []
  const flush = () => { if (para.length) { out.push({ kind: 'p', parts: parseInline(para.join('')) }); para = [] } }

  const lines = (md || '').split('\n')
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i]
    const fence = /^\s*```(.*)$/.exec(raw)
    if (fence) {
      flush()
      const lang = fence[1].trim().split(/\s+/)[0] ?? ''
      const buf: string[] = []
      for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) buf.push(lines[i])
      out.push({ kind: 'pre', lang, text: buf.join('\n') })
      continue
    }
    const line = raw.trimEnd()
    if (!line.trim()) { flush(); continue }
    const h = /^#{1,6}\s+(.*)$/.exec(line)
    if (h) { flush(); out.push({ kind: 'h', parts: parseInline(h[1]) }); continue }
    const li = /^\s*[-*]\s+(.*)$/.exec(line)
    if (li) {
      flush()
      const prev = out[out.length - 1]
      if (prev?.kind === 'ul') prev.items.push(parseInline(li[1]))
      else out.push({ kind: 'ul', items: [parseInline(li[1])] })
      continue
    }
    // 段落里的软换行拼成一行：日报里没有「按 Enter 排版」这回事
    para.push(para.length ? (/[一-鿿]$/.test(para[para.length - 1]) ? '' : ' ') + line : line)
  }
  flush()
  return out
}
