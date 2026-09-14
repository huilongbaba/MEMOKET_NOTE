/** 幻灯片 markdown → 一页一页。**跟后端 `checks/slides.split_pages` 同一条规则**，
 *  两边漂了的后果是「判据说 24 页、预览画出 26 页」。
 *
 *  `---` 分页，但**代码块里的 `---` 不算**——mermaid / yaml 块里横线很常见，
 *  切错一次整份就乱了（跟 `util/sectionEnd` 同一个坑）。开头的 front-matter
 *  不算一页。 */
export type Page = { title: string; body: string; at: number; cited: boolean }

const CITE = /\[[A-Za-z][A-Za-z0-9_-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+\]/

export function isSlides(md: string): boolean {
  return /^---\s*\n([\s\S]*?)\n---\s*(\n|$)/.test(md || '') && /\bslides:\s*true\b/.test(md || '')
}

export function slidePages(md: string): Page[] {
  const lines = (md || '').split('\n')
  let start = 0
  if (lines[0]?.trim() === '---') {
    const end = lines.findIndex((l, i) => i > 0 && l.trim() === '---')
    if (end > 0) start = end + 1
  }
  const pages: Page[] = []
  let buf: string[] = []
  let at = lines.slice(0, start).join('\n').length + (start ? 1 : 0)
  let bufAt = at
  let fenced = false
  const flush = () => {
    const raw = buf.join('\n').trim()
    if (raw) {
      const m = /^#{1,6}\s+(.*)$/m.exec(raw)
      pages.push({
        title: (m?.[1] ?? '').trim(),
        body: raw.replace(/^#{1,6}\s+.*$/m, '').trim(),
        at: bufAt,
        cited: CITE.test(raw),
      })
    }
    buf = []
  }
  for (let i = start; i < lines.length; i++) {
    const ln = lines[i]
    if (ln.trim().startsWith('```')) fenced = !fenced
    if (!fenced && ln.trim() === '---') { flush(); at += ln.length + 1; bufAt = at; continue }
    if (!buf.length) bufAt = at
    buf.push(ln)
    at += ln.length + 1
  }
  flush()
  return pages
}
