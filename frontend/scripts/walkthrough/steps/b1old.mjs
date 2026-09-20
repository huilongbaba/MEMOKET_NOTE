// P58 · 第九次全流程走查（老用户 terrence）第一趟：①③④⑤⑨⑪
//   ① 开到上次那篇 + 右栏
//   ③ 打三段正文（含日期 / 数字）→ 圆点两档 + 右栏「记忆」
//   ④ `/` 菜单全项 + Esc（P49 ③ 判成不是缺陷，收尾把那个 `/` 删掉并逐字核回）
//   ⑤ 右键六项
//   ⑨ ⌘K 全部去处
//   ⑪ 深色 + 900px
import { clickExact } from './clickexact.mjs'
import { docText, pageText, statusWords, until, wait } from './lib.mjs'

const SEED = [
  'P58 走查：这一批在改屏幕活动那条线上的三处。',
  '众筹页面那一版文案是 3 月 12 号上线的，当天点击 12700。',
  '预热名单回收了 860 份，转化率按渠道排了一遍。',
]

async function rightPane(d) {
  return d.eval(`(() => { const t = document.querySelectorAll('.pane-tab')[0]; return t ? t.parentElement.parentElement.innerText.slice(0, 3000) : null })()`)
}
async function tabs(d) { return d.texts('.pane-tab', 12) }

export default async function (d) {
  await d.setTheme('light'); await wait(500)
  console.log('=== ① 开到上次那篇 ===')
  await until(async () => await d.exists('.cm-content'), 30000)
  await wait(1500)
  console.log('  note id:', await d.noteId())
  console.log('  正文字数:', (await docText(d) ?? '').length, ' 状态栏:', await statusWords(d))
  console.log('  右栏页签:', JSON.stringify(await tabs(d)))
  const t0 = await pageText(d)
  for (const s of ['还没配模型', 'LLM 不可达', '记忆', '计划']) console.log(`  含「${s}」:`, t0.includes(s))
  await d.shot('p70-b1-old-open-light.png')

  console.log('=== ② 新建 → 打标题 → 右栏「计划」 ===')
  await d.key('Escape'); await wait(300)
  await d.key('k', ['meta']); await wait(1000)
  await d.insert('新建笔记'); await wait(1000)
  await clickExact(d, '新建笔记', 0, 8)
  await wait(2500)
  const fresh = await d.noteId()
  console.log('  新建出来的 note id:', fresh)
  await d.focusEditor()
  await d.insert('# P58 走查（可删）'); await d.key('Enter'); await d.key('Enter')
  await wait(3500)
  console.log('  右栏页签:', JSON.stringify(await tabs(d)))
  const titleBox = await d.eval(`(() => { const e = document.querySelector('input.note-title, .note-title input, input[placeholder*="标题"]'); return e ? { value: e.value } : null })()`)
  console.log('  标题框:', JSON.stringify(titleBox))
  await clickExact(d, '计划', 0, 4).catch(() => {})
  await wait(2500)
  const plan = await rightPane(d)
  console.log('--- 右栏「计划」---')
  console.log((plan || '').slice(0, 1200))
  console.log('  「预填」角标:', (plan || '').includes('预填'))
  await d.shot('p70-b1-old-plan-light.png')

  console.log('=== ③ 打三段正文 → 圆点 + 右栏「记忆」 ===')
  await d.focusEditor()
  await d.key('End', ['meta'])
  await d.key('Enter'); await d.key('Enter')
  const before = (await docText(d) ?? '').length
  for (const s of SEED) { await d.insert(s); await d.key('Enter'); await d.key('Enter'); await wait(250) }
  await wait(3000)
  const after = (await docText(d) ?? '').length
  console.log('  正文 ', before, '→', after)
  // P62：原来这里是 `.cm-margin-dot, [class*="margin-dot"]` —— **整个前端里没有这两个类**，
  // 真类是 `.mm-dot` / `.mm-<relation>`（`editor/marginMemory.ts:128`）。
  // 于是 P58 / P60 两批这一格一律报「圆点 0」，读起来像「关系判据坏了」。
  // **选不到 ≠ 没有。** 现在走 `d.dots()`（落槽内计数，图例那几颗单独列），选不到会吵。
  console.log('  页边圆点:', JSON.stringify(await d.dots()))
  // 光标落到「众筹页面…3 月 12 号」那一段
  const lines = await d.eval(`Array.from(document.querySelectorAll('.cm-content .cm-line')).map((l, i) => [i, (l.textContent||'').slice(0, 24)])`)
  const idx = (lines.find(([, t]) => t.includes('众筹页面')) || [])[0]
  console.log('  「众筹页面」那一行是第', idx, '行')
  if (idx != null) {
    const r = await d.eval(`(() => { const l = document.querySelectorAll('.cm-content .cm-line')[${idx}]; const b = l.getBoundingClientRect(); return { x: b.x + 20, y: b.y + b.height/2 } })()`)
    await d.clickAt(r.x, r.y); await wait(3000)
  }
  await clickExact(d, '记忆', 0, 6).catch(() => {})
  await wait(3000)
  const mem = await rightPane(d)
  console.log('--- 右栏「记忆」---')
  console.log(mem)
  console.log('  命中行:', JSON.stringify((mem || '').match(/命中[：:][^\n]{0,120}/g)))
  await d.shot('p70-b1-old-memory-light.png')

  console.log('=== ④ `/` 菜单 + Esc ===')
  const doc0 = await docText(d)
  await d.focusEditor(); await d.key('End', ['meta'])
  await d.key('Enter'); await d.key('Enter')
  await d.key('/'); await wait(1200)
  const items = await d.texts('.slash-item, [class*="slash"] [class*="item"], [role="option"]', 30)
  console.log('  `/` 菜单项数:', items.length)
  console.log('  项:', JSON.stringify(items))
  await d.shot('p70-b1-old-slash-light.png')
  await d.key('Escape'); await wait(600)
  console.log('  Esc 之后还剩几项:', (await d.texts('.slash-item, [class*="slash"] [class*="item"], [role="option"]', 30)).length)
  const tail = (await docText(d) ?? '').slice(-3)
  console.log('  正文末尾（P49 ③：`/` 留着是对的）:', JSON.stringify(tail))
  // 收尾：把刚才那一下退干净，并**逐字核回打 `/` 之前那一份**（P49 ③ 立的规矩）
  for (let i = 0; i < 3; i++) { await d.key('Backspace'); await wait(120) }
  await wait(600)
  const doc1 = await docText(d)
  console.log('  收尾之后逐字回到打 `/` 之前了吗:', doc1 === doc0,
              doc1 === doc0 ? '' : JSON.stringify([doc0.slice(-12), doc1.slice(-12)]))

  console.log('=== ⑤ 右键六项 ===')
  const sel = await d.eval(`(() => {
    const l = Array.from(document.querySelectorAll('.cm-content .cm-line')).find((e) => (e.textContent||'').includes('预热名单'))
    if (!l) return null
    const b = l.getBoundingClientRect()
    return { x: b.x + 30, y: b.y + b.height / 2, x2: b.x + Math.min(b.width - 10, 160) }
  })()`)
  if (sel) {
    await d.clickAt(sel.x, sel.y)
    await d.mouse('mousePressed', sel.x, sel.y, { button: 'left', clickCount: 1 })
    await d.mouse('mouseMoved', sel.x2, sel.y, { button: 'left', buttons: 1 })
    await d.mouse('mouseReleased', sel.x2, sel.y, { button: 'left', clickCount: 1 })
    await wait(400)
    await d.clickAt(sel.x2 - 20, sel.y, { button: 'right' })
    await wait(1200)
    // P62：原来这里是 `.context-menu …` —— 那个类只活在 `probes*.ts` 的老探针里，
    // 编辑器右键菜单的条目真类是 `.palette-item`（`styles.css:473`）。同上：报的 `[]` 是假的。
    const menu = await d.menuItems(20)
    console.log('  右键菜单:', JSON.stringify(menu))
    const selText = await d.eval(`String(window.getSelection())`)
    console.log('  选区还在吗:', JSON.stringify(selText.slice(0, 30)))
    await d.shot('p70-b1-old-ctx-light.png')
    await d.key('Escape'); await wait(500)
  } else { console.log('  找不到那一行，右键这一格没摆出来') }

  console.log('=== ⑨ ⌘K 全部去处 ===')
  await d.key('Escape'); await wait(300)
  await d.key('k', ['meta']); await wait(1200)
  const dests = await d.texts('[role="option"], [class*="palette"] [class*="item"], .palette-item', 60)
  console.log('  项数:', dests.length)
  console.log('  项:', JSON.stringify(dests))
  await d.shot('p70-b1-old-cmdk-light.png')
  await d.insert('屏幕'); await wait(1200)
  const screen = await d.texts('[role="option"], [class*="palette"] [class*="item"], .palette-item', 40)
  console.log('  搜「屏幕」:', screen.length, JSON.stringify(screen))
  await d.key('Escape'); await wait(600)
  console.log('  Esc 关得掉吗:', (await d.texts('[role="option"], [class*="palette"] [class*="item"], .palette-item', 5)).length === 0)

  console.log('=== ⑪ 深色 + 900px ===')
  await d.setTheme('dark'); await wait(1200)
  const bg = await d.eval(`getComputedStyle(document.body).backgroundColor`)
  const white = await d.eval(`(() => {
    let n = 0
    for (const e of document.querySelectorAll('*')) {
      const c = getComputedStyle(e).backgroundColor
      const m = c.match(/rgba?\\((\\d+), ?(\\d+), ?(\\d+)(?:, ?([\\d.]+))?\\)/)
      if (!m) continue
      const [r, g, b, a] = [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]]
      if (a > 0.9 && r > 235 && g > 235 && b > 235) {
        const q = e.getBoundingClientRect()
        if (q.width > 40 && q.height > 20) n++
      }
    }
    return n
  })()`)
  console.log('  深色 body 背景:', bg, ' 近白的大块:', white)
  await d.shot('p70-b1-old-dark.png')
  await d.resize(900, 900); await wait(800)
  const over = await d.eval(`(() => {
    let n = 0
    for (const e of document.querySelectorAll('*')) { const r = e.getBoundingClientRect(); if (r.width > 0 && r.right > innerWidth + 1) n++ }
    return n
  })()`)
  const scrollable = await d.eval(`document.documentElement.scrollWidth > document.documentElement.clientWidth + 1`)
  console.log('  900px 横向溢出:', over, ' 页面横向滚得动吗:', scrollable)
  await d.setTheme('light'); await wait(600)
  await d.shot('p70-b1-old-900-light.png')
  await d.resize(0)
  // P62：`lib.mjs` 的 `toasts()` 用的是 `[class*="toast"]`，**把外层容器 `.toaster` 也选进来了**
  // ——一条读成两条，P58 / P60 两批都记成了「同一条 toast 连出两遍」。走 `d.toasts()`（精确 + 容器只许一个）。
  console.log('  toast 一摞:', JSON.stringify(await d.toasts()))
}
