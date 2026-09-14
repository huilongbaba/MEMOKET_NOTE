import { parseMini, type Block, type Inline } from './miniMarkdown'
import { slidePages } from './slidePages'

/** 幻灯片 markdown → 一份能直接打印成 PDF 的 HTML。
 *
 * **零新依赖**：Electron 主进程本来就能 `printToPDF`，所以「导出 PDF」这件事
 * 需要的全部东西就是一份排好版的 HTML。不引 Marp（600KB+）、不引 python-pptx。
 *
 * 一页一个 `<section>`，16:9，`page-break-after: always`——打印出来一页就是一页。
 * 样式跟应用同源（同一套灰度和字号），**不做主题选择器**：选主题是 PPT 软件的活。
 */

const esc = (s: string) => s.replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string))

const ink = (parts: Inline[]) => parts.map((p) =>
  p.t === 'b' ? `<b>${esc(p.s)}</b>` : p.t === 'code' ? `<code>${esc(p.s)}</code>` : esc(p.s)).join('')

function blockHtml(b: Block, svgs: Map<string, string>): string {
  if (b.kind === 'h') return `<h2>${ink(b.parts)}</h2>`
  if (b.kind === 'ul') return `<ul>${b.items.map((it) => `<li>${ink(it)}</li>`).join('')}</ul>`
  if (b.kind === 'pre') {
    // **图要是图**：打印那一步在离屏窗口里跑且关掉了 JS，所以 SVG 必须在调用方
    // 先渲好传进来（`svgs`）。渲不出来（或者调用方没渲）就老老实实印源码——
    // 那也比压成一行带反引号的乱码强（第 650 轮实拍第 7 页就是那样）。
    const svg = svgs.get(b.text.trim())
    if (svg) return `<figure class="diagram">${svg}</figure>`
    return `<pre>${esc(b.text)}</pre>`
  }
  return `<p>${ink(b.parts)}</p>`
}

/** `svgs`：mermaid 源码 → 渲好的 SVG。调用方先渲（`editor/mermaid.mermaidSvg`），
 *  因为打印那一步的窗口是关着 JS 的。 */
export function slidesToHtml(title: string, md: string, svgs = new Map<string, string>()): string {
  const pages = slidePages(md)
  const body = pages.map((p, i) => {
    // 每页的标题已经被 slidePages 摘出来了，正文里就别再出现一次
    const blocks = parseMini(p.body).filter((b) => b.kind !== 'h').map((b) => blockHtml(b, svgs)).join('\n')
    return `<section${i === 0 ? ' class="cover"' : ''}>
  <h1>${esc(p.title)}</h1>
  ${blocks}
  <footer>${i + 1} / ${pages.length}</footer>
</section>`
  }).join('\n')

  return `<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>${esc(title)}</title><style>
  @page { size: 1280px 720px; margin: 0; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 16px/1.6 -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; color: #1a1a19; }
  section { position: relative; width: 1280px; height: 720px; padding: 72px 88px 64px;
            page-break-after: always; break-after: page; background: #fff; overflow: hidden; }
  section:last-child { page-break-after: auto; break-after: auto; }
  h1 { margin: 0 0 28px; font-size: 40px; line-height: 1.25; font-weight: 700; }
  section.cover { display: flex; flex-direction: column; justify-content: center; }
  section.cover h1 { font-size: 56px; }
  p { margin: 0 0 14px; font-size: 22px; }
  ul { margin: 0; padding-inline-start: 28px; }
  li { margin: 0 0 12px; font-size: 22px; line-height: 1.5; }
  code { font-family: ui-monospace, Menlo, monospace; font-size: 18px;
         background: #f1f1ef; border-radius: 4px; padding: 1px 5px; }
  /* 引用编号排小一号、发灰：它是**凭据**，不是正文的一部分——但必须看得见，
     不然这份 PDF 跟通用工具做出来的就没区别了 */
  li code, p code { color: #6b6b66; }
  pre { margin: 0 0 14px; font-family: ui-monospace, Menlo, monospace; font-size: 15px;
        line-height: 1.5; white-space: pre-wrap; background: #f7f7f5; border-radius: 6px; padding: 12px 14px; }
  figure.diagram { margin: 0; display: flex; justify-content: center; align-items: center; height: 480px; }
  figure.diagram svg { max-width: 100%; max-height: 100%; }
  footer { position: absolute; inset-inline-end: 88px; inset-block-end: 40px;
           font-size: 14px; color: #9a9a94; }
</style></head><body>
${body}
</body></html>`
}
