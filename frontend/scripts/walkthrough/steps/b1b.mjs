// P58 · b1 那一趟量错了三格，换选择器重量一遍（**「选不到 ≠ 没有」**，这是第八个形状）：
//   · 页边圆点的类是 `.mm-*`（`check-margin-dots.mts` 里那几个），不是 `margin-dot`
//   · 「预填」角标在 `.doc-intent-src` 上，意图三格是 `input.doc-intent-input` 的 **value**
//     ——右栏 `innerText` 里根本读不到（P47 的 `p47intent.mjs` 已经栽过一次）
//   · 右键菜单项是 `.palette-item`；而且右键得点在**选区的 bbox** 上（P47 `ctxmenu.mjs`）
import { clickExact } from './clickexact.mjs'
import { selectLineAndRightClick } from './ctxmenu52.mjs'
import { docText, pageText, wait } from './lib.mjs'

export default async function (d, [noteId]) {
  await d.setTheme('light'); await wait(400)
  await d.openNoteById(noteId, 'P58 走查')
  await wait(2500)
  console.log('开着的是:', await d.noteId())
  const doc = await docText(d)
  console.log('正文字数:', (doc ?? '').length)

  console.log('=== ② 意图三格 + 「预填」角标（P43 #2 / P44 问题 #4 的回归）===')
  const intent = await d.eval(`(() => {
    const el = document.querySelector('.doc-intent')
    if (!el) return { found: false }
    const vals = Array.from(el.querySelectorAll('input.doc-intent-input')).map((i) => [i.getAttribute('aria-label'), i.value])
    const title = Array.from(document.querySelectorAll('input')).find((e) => String(e.className).includes('note-title'))
    return { found: true, vals, prefill: !!el.querySelector('.doc-intent-src'),
             titleBox: title ? title.value : null }
  })()`)
  console.log('  意图行:', JSON.stringify(intent))
  await d.shot('p70-b1b-old-intent-light.png')

  console.log('=== ③ 页边圆点两档（.mm-*）===')
  // P62：这两个档原来写的是 `.mm-continues` / `.mm-adds` —— **前端里没有这两个类**，
  // 真名是 `.mm-continuation` / `.mm-accumulation`（`api.ts:839` 那六个 kind）。
  // 于是 P52 / P58 / P60 三批台账上那句「圆点 8 个（冲突 2 / 印证 1 / 缺依据 2 / 合并 1）」
  // ——**四档只加得到 6**，另外 2 颗正是掉进这两个空档里的。**选不到 ≠ 没有。**
  // 现在走 `d.dots()`（六档齐 + 落槽内计数，图例那几颗单独列）。
  const dots = await d.dots()
  console.log('  圆点:', JSON.stringify(dots))

  console.log('=== ⑤ 右键六项（点在选区 bbox 上）===')
  const lines = await d.eval(`Array.from(document.querySelectorAll('.cm-content .cm-line')).map((l, i) => [i, (l.textContent||'').slice(0, 20)])`)
  const idx = (lines.find(([, t]) => t.includes('预热名单')) || [])[0]
  console.log('  「预热名单」在第', idx, '行')
  const { sel } = await selectLineAndRightClick(d, idx)
  console.log('  选中:', JSON.stringify(sel))
  const items = await d.texts('.palette-item, [class*="palette"] [class*="item"]', 20)
  console.log('  右键菜单:', items.length, '项', JSON.stringify(items))
  await d.shot('p70-b1b-old-ctx-light.png')
  await d.key('Escape'); await wait(500)
  console.log('  Esc 之后还剩:', (await d.texts('.palette-item, [class*="palette"] [class*="item"]', 20)).length)
  const doc2 = await docText(d)
  console.log('  正文一个字没动吗:', doc2 === doc)
  void clickExact; void pageText
}
