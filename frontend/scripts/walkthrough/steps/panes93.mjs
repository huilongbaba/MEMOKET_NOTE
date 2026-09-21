// P93 A：**右栏每个页签「空的时候屏幕上是什么」，在真壳上逐格拍一遍。**
//
// 为什么要在壳上跑，而不是只读源码 / 只跑 jsdom：
//   · 「文件里有这个串」≠「这段代码还在跑」——`p93.test.tsx` 那一侧挂的是**我自己搭的**
//     `PaneTab`，它证得了「`RightPane` 摆得出话」，证不了「App 真跑起来的时候摆的就是这个」。
//   · jsdom 那一侧挂不动要网络的组件（`TrayPanel` / `RelatedMemory`），
//     所以「开着一篇**空**笔记时`记忆`那一格是什么」只有壳上量得到。
//
// 它**不判**，只**读**：每一格点进去、把 `.right-pane-body` 的 `innerText` 原样打出来，
// 顺带标一句「这一格是不是一个字都没有」。判在走查表和 `p93.test.tsx` 那一侧。
//
//   node cdp.mjs <port> steps/panes93.mjs <截图名前缀> [要打开的 note id] [它的标题头几个字]
//
// 三档走一遍：① 虚拟页（屏幕活动，`current === null`）；② 现建一篇空笔记；
// ③ 给了 note id 的话再开那一篇（走查里给的是**幻灯片**那一篇——
//    `slides` 这一格只在 `isSlides(content)` 时才进数组，别的档上它压根不在条上）。
import { clickExact } from './clickexact.mjs'
import { openJourney, wait } from './lib52.mjs'

/** 把右栏这一刻的样子读出来：条上几格、逐格点进去屏幕上是什么。 */
async function readPanes(d, tag, shotPrefix) {
  const names = await d.mustTexts('.pane-tab', 12, { why: '右栏页签条（`.pane-tab`）' })
  console.log(`  [${tag}] 条上 ${names.length} 格:`, JSON.stringify(names))
  const out = []
  for (let i = 0; i < names.length; i++) {
    // **每一格都重新按序号点**：点完右栏会重渲染，缓存下来的 bbox 就不作数了
    const r = await d.rect('.pane-tab', i)
    if (!r) throw new Error(`第 ${i} 格的 bbox 读不到——**选不到 ≠ 没有**`)
    await d.clickAt(r.cx, r.cy)
    await wait(600)
    const body = await d.eval(`(document.querySelector('.right-pane-body')?.innerText ?? null)`)
    if (body === null) throw new Error('`.right-pane-body` 整个选不到——右栏没渲染出来')
    const shown = body.replace(/\s+/g, ' ').trim()
    out.push({ 页签: names[i].replace(/\s+/g, ' ').trim(), 有字: shown.length > 0, 屏幕上: shown.slice(0, 160) })
    console.log(`    · ${names[i].replace(/\s+/g, ' ').trim()}`, shown.length > 0 ? '→ 有字：' : '→ **一片留白**', JSON.stringify(shown.slice(0, 160)))
    await d.shot(`${shotPrefix}-${tag}-${names[i].replace(/[^一-龥a-zA-Z]/g, '') || i}.png`)
  }
  const blank = out.filter((x) => !x.有字).map((x) => x.页签)
  console.log(`  [${tag}] 留白的格子（该 0 个）:`, JSON.stringify(blank))
  return out
}

export default async function (d, args) {
  const prefix = args[0] || 'p93-panes'
  await d.setTheme('light'); await wait(400)

  console.log('=== ① 虚拟页（屏幕活动）：`current === null` ===')
  await openJourney(d)
  await wait(1200)
  console.log('  这会儿开着的那一篇（该是 null / 上一篇但不在正文里）:', await d.noteId())
  await readPanes(d, 'virtual', prefix)

  console.log('=== ② 现建一篇空笔记：`current` 有了，但里头什么都没有 ===')
  await d.key('Escape'); await wait(300)
  await d.key('k', ['meta']); await wait(1000)
  await d.insert('新建笔记'); await wait(900)
  await clickExact(d, '新建笔记', 0, 8)
  await wait(3000)
  console.log('  新建出来的 note id:', await d.noteId())
  console.log('  正文（该是空的）:', JSON.stringify(await d.cmText()))
  await readPanes(d, 'emptynote', prefix)

  if (args[1]) {
    console.log('=== ③ 开一篇**幻灯片**：`slides` 这一格只有这时候才在条上 ===')
    await d.openNoteById(args[1], args[2] ?? '')
    await wait(1500)
    console.log('  开着的是:', await d.noteId())
    await readPanes(d, 'slides', prefix)
  } else {
    console.log('=== ③ 没给 note id，这一档跳过（**跳过就是跳过**，不拿别的顶）===')
  }
}
