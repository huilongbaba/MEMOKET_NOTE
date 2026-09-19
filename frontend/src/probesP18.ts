/**
 * P18 探针（只在 `--probe=` 启动时跑，生产路径不进）：飞书 mermaid → 图，在真实 Chromium 里把这一篇的每段 mermaid
 * 渲成 PNG（`util/mermaidPng`），再走一遍导回前那一步（`exportMermaidRenders` → 真后端 `/api/export/renders`）。
 *
 *   p18:mermaidpng:<id>   打开这篇 → 问后端要 mermaid 源码 → 逐张渲 PNG → 日志记每张的键 / 字节数 / 后端收下几张；
 *                         PNG 的 data URL 按 2000 字一段打进日志（`p18 pngdata key=… i=…/…`），外面拼回来真发飞书用
 */
import * as api from './api'
import type { MermaidBlocks, Note } from './api'
import { exportMermaidRenders, renderMermaidPng, sizedSvg, svgSize, svgToPng, withExportInit } from './util/mermaidPng'
import { mermaidSvg } from './editor/mermaid'

type Ctx = Record<string, any> & { notes: Note[] }
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
const log = (s: string) => void api.clientLog('warn', s, '', 'probe')
const CHUNK = 2000

export async function runP18(probe: string, ctx: Ctx): Promise<boolean> {
  if (!probe.startsWith('p18:')) return false
  const [, kind, id] = probe.split(':')
  const n = ctx.notes.find((x) => x.id === id)
  if (!n) { log(`p18 note ${id} not found`); return true }
  if (ctx.harnessProbeDone.current) return true
  ctx.harnessProbeDone.current = true
  await wait(600)
  await ctx.switchTo(n)
  await wait(1500)
  if (kind !== 'mermaidpng') { log(`p18 unknown probe ${kind}`); return true }
  const res = await fetch('/api/export/mermaid', { method: 'POST', headers: { 'X-User-Id': api.getUser(), 'Content-Type': 'application/json' }, body: JSON.stringify({ note_ids: [id] }) })
  const blocks = (await res.json()) as MermaidBlocks
  log(`p18 mermaid blocks=${Object.keys(blocks).length} keys=${Object.keys(blocks).join(',')}`)
  for (const [key, code] of Object.entries(blocks)) {
    // 逐步诊断：哪一步给的 null（源码本身渲不渲得出 / 带 init 之后 / 尺寸 / canvas）
    const plain = await mermaidSvg(code).catch((e) => `ERR ${e}`)
    const withInit = await mermaidSvg(withExportInit(code)).catch((e) => `ERR ${e}`)
    const size = typeof withInit === 'string' && !withInit.startsWith('ERR') ? svgSize(withInit) : null
    log(`p18 svg key=${key} plain=${typeof plain === 'string' ? plain.length : plain} withInit=${typeof withInit === 'string' ? withInit.length : withInit} size=${JSON.stringify(size)} head=${typeof withInit === 'string' ? withInit.slice(0, 160).replace(/\s+/g, ' ') : ''}`)
    if (typeof withInit === 'string' && !withInit.startsWith('ERR')) {
      const png2 = await svgToPng(withInit).catch((e) => `ERR ${e}`)
      log(`p18 svgToPng key=${key} → ${typeof png2 === 'string' ? png2.slice(0, 30) + ' len=' + png2.length : png2}`)
      // 拆步：blob URL / data URL 两种装进 <img>，各自 onload / onerror；再画 canvas、toDataURL
      const sz = size ?? { w: 100, h: 100 }
      const fixed = sizedSvg(withInit, sz)
      log(`p18 svgdiag foreignObject=${fixed.includes('foreignObject')} nbsp=${fixed.includes('&nbsp;')} style=${fixed.includes('<style')} openTag=${fixed.slice(0, 200).replace(/\s+/g, ' ')}`)
      for (const [how, url] of [['blob', URL.createObjectURL(new Blob([fixed], { type: 'image/svg+xml;charset=utf-8' }))], ['data', 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(fixed)]] as const) {
        const r = await new Promise<string>((resolve) => {
          const img = new Image()
          img.onload = () => {
            try {
              const c = document.createElement('canvas'); c.width = Math.ceil(sz.w); c.height = Math.ceil(sz.h)
              const ctx = c.getContext('2d')!; ctx.drawImage(img, 0, 0)
              resolve(`onload ${img.naturalWidth}x${img.naturalHeight} toDataURL=${c.toDataURL('image/png').slice(0, 22)}`)
            } catch (e) { resolve(`onload but canvas threw: ${e}`) }
          }
          img.onerror = (e) => resolve(`onerror ${String(e)}`)
          img.src = url
        })
        log(`p18 img ${how}: ${r}`)
      }
    }
    const t0 = performance.now()
    const png = await renderMermaidPng(code)
    log(`p18 png key=${key} ok=${!!png} bytes=${png ? Math.round((png.length - 22) * 3 / 4) : 0} ms=${Math.round(performance.now() - t0)} code=${code.split('\n')[0]}`)
    if (!png) continue
    const parts = Math.ceil(png.length / CHUNK)
    for (let i = 0; i < parts; i++) log(`p18 pngdata key=${key} i=${i}/${parts} ${png.slice(i * CHUNK, (i + 1) * CHUNK)}`)
  }
  const stored = await exportMermaidRenders([id])
  log(`p18 renders stored=${stored}`)
  return true
}
