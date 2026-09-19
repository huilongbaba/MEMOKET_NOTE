/**
 * 导回飞书之前把正文里的 mermaid 渲成 PNG（P18 #4，`docs/TRACELOG-product.md` P18 节）。
 *
 * 飞书 docx 没有 mermaid 这个语言（P2-fix 只能落成纯文本代码块）。图不由后端画：**不用外部服务**（kroki 之类
 * 一律不许），后端是 PyInstaller 打的包、塞不进一个 Chromium；而这里本来就在用 mermaid 渲编辑器里的图——
 * 于是导回前先问后端「这批笔记里有哪几段 mermaid」（按源码哈希），在这边渲成 SVG → `<canvas>` → PNG，按同一个
 * 哈希交回去（`POST /api/export/renders`），后端走 P2-fix 已做的图片三步上传。
 *
 * 三条边界：
 *   · 渲染走跟编辑器同一条路（`editor/mermaid.mermaidSvg`，含 autoFix 与缓存），只多一个 `%%{init}%%`：
 *     导出永远用浅色主题（对面是白纸）；SVG 装进 `<img>` 走 data: URL（blob: 会让 canvas 被判污染，见 `svgDataUrl`）；
 *   · 任何一步失败都**不拦导回**：渲不出的那张后端退化成代码块 + 一行说明；
 *   · 这里没有 UI：`useExportBack.toFeishu` 在发导回请求之前调一次。
 */
import { getUser, type MermaidBlocks, type RendersOut } from '../api'
import { mermaidSvg } from '../editor/mermaid'

/** 导出用的 init 指令：浅色主题 + 纯 SVG 标签。已经带 init 的源码不再套一层。 */
export const EXPORT_INIT = '%%{init: {"theme":"default","flowchart":{"htmlLabels":false}}}%%\n'
/** 2× 缩放：飞书 / Notion 里图按原尺寸显示，1× 的文字发糊 */
export const EXPORT_SCALE = 2

export function withExportInit(code: string): string {
  return /^\s*%%\{\s*init/.test(code) ? code : EXPORT_INIT + code
}

/** mermaid 的 SVG 宽高：它给的 `width="100%"` 量不出来，要读 viewBox（没有再退回 width/height 属性）。 */
export function svgSize(svg: string): { w: number; h: number } | null {
  const vb = svg.match(/viewBox="\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)\s*"/)
  if (vb) {
    const w = Number(vb[1]); const h = Number(vb[2])
    if (w > 0 && h > 0) return { w, h }
  }
  const w = Number(svg.match(/\swidth="([\d.]+)(?:px)?"/)?.[1])
  const h = Number(svg.match(/\sheight="([\d.]+)(?:px)?"/)?.[1])
  return w > 0 && h > 0 ? { w, h } : null
}

/** 给 `<svg>` 明确的像素宽高（去掉 `width="100%"` 那种），`<img>` 才量得出尺寸。 */
export function sizedSvg(svg: string, size: { w: number; h: number }): string {
  return svg.replace(/<svg\b([^>]*)>/, (_m, attrs: string) => {
    const rest = attrs.replace(/\s(?:width|height)="[^"]*"/g, '')
    return `<svg${rest} width="${size.w}" height="${size.h}">`
  })
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('svg 画不出来'))
    img.src = url
  })
}

/** SVG 字符串 → `<img>` 能装的 URL。**用 data: 不用 blob:**——真 Chromium（桌面壳）实拍：mermaid 的 SVG 里标签是
 *  `<foreignObject>`（init 指令关 htmlLabels 没关掉），blob: URL 装进 `<img>` 画上 canvas 之后 `toDataURL` 抛
 *  「Tainted canvases may not be exported」；同一份 SVG 走 data: URL 画出来 1449×94、导得出 PNG。 */
export function svgDataUrl(svg: string): string {
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
}

/** SVG 字符串 → PNG data URL（白底、`scale` 倍）。没有 canvas（测试环境）/ 画不出来给 null。 */
export async function svgToPng(svg: string, scale = EXPORT_SCALE): Promise<string | null> {
  const size = svgSize(svg)
  if (!size || typeof document === 'undefined') return null
  const url = svgDataUrl(sizedSvg(svg, size))
  try {
    const img = await loadImage(url)
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.ceil(size.w * scale))
    canvas.height = Math.max(1, Math.ceil(size.h * scale))
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    const out = canvas.toDataURL('image/png')
    return out.startsWith('data:image/png') ? out : null
  } catch {
    return null
  }
}

/** 一段 mermaid 源码 → PNG data URL；语法错 / 渲不出给 null（后端那边退化成代码块）。 */
export async function renderMermaidPng(code: string): Promise<string | null> {
  try {
    const svg = await mermaidSvg(withExportInit(code))
    return svg ? await svgToPng(svg) : null
  } catch {
    return null
  }
}

export type Renderer = (code: string) => Promise<string | null>

/** 后端给的 {哈希: 源码} → {哈希: PNG}；渲不出的不带。逐张渲（mermaid 的 render 不能并发同 id）。 */
export async function collectMermaidRenders(blocks: MermaidBlocks, render: Renderer = renderMermaidPng): Promise<Record<string, string>> {
  const out: Record<string, string> = {}
  for (const [key, code] of Object.entries(blocks)) {
    const png = await render(code)
    if (png) out[key] = png
  }
  return out
}

async function postJson<T>(path: string, body: unknown, fetcher: typeof fetch): Promise<T> {
  const res = await fetcher(path, { method: 'POST', headers: { 'X-User-Id': getUser(), 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!res.ok) throw new Error(`${res.status}`)
  return res.json() as Promise<T>
}

/**
 * 导回飞书前的那一步：问后端要 mermaid 源码 → 渲 → 交回去。回交上去了几张；**任何失败都回 0、不抛**——
 * 图渲不出不该拦住整篇导回（后端会退化成代码块 + 一行说明）。
 */
export async function exportMermaidRenders(noteIds: string[], render: Renderer = renderMermaidPng, fetcher: typeof fetch = fetch): Promise<number> {
  try {
    const blocks = await postJson<MermaidBlocks>('/api/export/mermaid', { note_ids: noteIds }, fetcher)
    if (!Object.keys(blocks).length) return 0
    const renders = await collectMermaidRenders(blocks, render)
    if (!Object.keys(renders).length) return 0
    const r = await postJson<RendersOut>('/api/export/renders', { renders }, fetcher)
    return r.stored
  } catch {
    return 0
  }
}
