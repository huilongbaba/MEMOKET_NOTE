// P58 · 第九次全流程走查（老用户）第三趟：⑩（后半，关掉重开）+ ⑧（屏幕活动整页）
import { clickExact } from './clickexact.mjs'
import { clickBtn, journeyFacts, openJourney, toTop, toasts, until, wait } from './lib52.mjs'
import { pageText } from './lib.mjs'

const line = (t, re) => (t.match(re) || [])[0] || null

async function nav(d) {
  return d.eval(`(() => {
    const g = (t) => { const b = document.querySelector('button[title=' + JSON.stringify(t) + ']'); return b ? b.disabled : null }
    return { prev: g('上一条记录'), next: g('下一条记录') }
  })()`)
}
async function clickTitle(d, title) {
  const box = await d.eval(`(() => {
    const b = document.querySelector('button[title=' + ${JSON.stringify(JSON.stringify(title))} + ']')
    if (!b || b.disabled) return null
    b.scrollIntoView({ block: 'center' })
    return true
  })()`)
  if (!box) return false
  await wait(350)
  const p = await d.eval(`(() => {
    const b = document.querySelector('button[title=' + ${JSON.stringify(JSON.stringify(title))} + ']')
    const r = b.getBoundingClientRect(); return { cx: r.x + r.width / 2, cy: r.y + r.height / 2 }
  })()`)
  await d.clickAt(p.cx, p.cy)
  await wait(1600)
  return true
}

export default async function (d, [noteId, plainId]) {
  await d.setTheme('light'); await wait(400)

  console.log('=== ⑩ 关掉重开：上一趟生出来的改动层还在吗（P39 / P43 / P44 问题 #5）===')
  await d.openNoteById(noteId, 'P58 走查')
  await wait(2500)
  console.log('  开着的是:', await d.noteId())
  console.log('  右栏页签:', JSON.stringify(await d.texts('.pane-tab', 12)))
  console.log('  toast（该一条都没有）:', JSON.stringify(await toasts(d)))
  const lay = await d.eval(`(async () => {
    const u = localStorage.getItem('memoket.user') || 'terrence'
    const r = await fetch('/api/notes/${noteId}/change-layers', { headers: { 'X-User-Id': u } })
    const j = await r.json(); return (j.layers || []).map((l) => l.label + ':' + l.hunks.length + '处/' + l.state).join(' | ')
  })()`)
  console.log('  库里的层:', lay)
  await d.shot('p70-b3-old-reopen-light.png')

  if (plainId) {
    console.log('  换一篇没有层的笔记（P44 问题 #5：不许冒出「改动」页签，也不许有 toast）')
    await d.openNoteById(plainId, '')
      .catch((e) => console.log('   没开到:', e.message))
    await wait(2000)
    console.log('   开着的是:', await d.noteId())
    console.log('   右栏页签:', JSON.stringify(await d.texts('.pane-tab', 12)))
    console.log('   toast:', JSON.stringify(await toasts(d)))
  }

  console.log('=== ⑧ 屏幕活动整页 ===')
  await openJourney(d)
  await toTop(d)
  const f = await journeyFacts(d)
  console.log('  今天:', JSON.stringify(f))
  const t0 = await pageText(d)
  console.log('  状态行:', line(t0, /[^\n]*(记录中|没在记录|已暂停)[^\n]*/))
  console.log('  假采集源那一句（这一份没挂，该没有）:', t0.includes('不是真的屏幕活动'))
  console.log('  翻页箭头:', JSON.stringify(await nav(d)))
  await d.shot('p70-b3-old-journey-light.png')

  console.log('— 保留期面板 —')
  const keep = await d.eval(`(() => { const e = document.querySelector('.journey-keep, [class*="journey-keep"]'); return e ? e.innerText.slice(0, 700) : null })()`)
  console.log(keep)

  console.log('— 一键全删（第一下摊开，先不删）—')
  // P64 问题 #6 / P66 改掉：**钮叫「全部删掉」**（`JourneyRetentionPanel.tsx:155`），
  // 「删掉全部屏幕活动？这一下会删掉：」是**摊开之后**那段话的标题（同文件 :139）。
  // 原来这儿拿标题去点钮，于是**一下都没点着**，而 `.catch()` 把它咽了——
  // 台账上那一格是靠 `b4old` 补的。**同一格有两份互相矛盾的读数时，得写明取的是哪一份。**
  //
  // **P66 实测：根因不止文案一条。** 光把文字改对，这一格还是读回 `undefined`——
  // 那个钮在保留期面板**最底下**，`clickExact` 不滚动，拿到的 bbox 在视口外，
  // 点下去一声不响（`b4old` 顶上逐字记着这条，`clickBtn` 会先 `scrollIntoView`）。
  // **「点过了 ≠ 翻过了」的同族：「点到坐标了 ≠ 点到那个钮了」。**
  console.log('  点之前 bbox:', JSON.stringify(await clickBtn(d, '全部删掉')))
  await wait(1300)
  const t1 = await pageText(d)
  console.log('  摊开那段:', JSON.stringify((t1.match(/删掉全部屏幕活动[\s\S]{0,300}/) || [])[0]))
  await d.shot('p70-b3-old-wipe-light.png')
  await clickExact(d, '先不删', 0, 4).catch(() => {})
  await wait(800)
  await toTop(d)

  console.log('— 翻天 + 「删掉这一天」确认框（P23 #5）—')
  await clickTitle(d, '上一条记录')
  await toTop(d)
  const t2 = await pageText(d)
  console.log('  翻到:', line(t2, /\d{4}-\d{2}-\d{2} · 屏幕活动/), line(t2, /这天 \d+ 段[^\n]*/))
  await clickExact(d, '删掉这一天', 0, 4).catch((e) => console.log('  没点到:', e.message))
  await wait(1000)
  console.log('  确认框:', await d.count('.journey-keep-confirm'))
  console.log('  逐条:', JSON.stringify(await d.texts('.journey-keep-confirm li', 10)))
  console.log('  那句话:', (await pageText(d)).includes('删完就真的没有了，没有回收站'))
  await d.shot('p70-b3-old-delday-light.png')
  console.log('— 翻到别的一天，确认作废 —')
  await toTop(d)
  await clickTitle(d, '上一条记录')
  await toTop(d)
  console.log('  确认框还在吗（该 0）:', await d.count('.journey-keep-confirm'))
  const t3 = await pageText(d)
  console.log('  现在这一页:', line(t3, /\d{4}-\d{2}-\d{2} · 屏幕活动/), ' 翻页:', JSON.stringify(await nav(d)))

  console.log('— 「去这天的日记」（P23 #6）—')
  const before = await d.eval(`(async () => { const u = localStorage.getItem('memoket.user') || 'terrence'; const r = await fetch('/api/tree', { headers: { 'X-User-Id': u } }); return JSON.stringify(await r.json()).length })()`)
  await clickExact(d, '去这天的日记', 0, 4).catch((e) => console.log('  没点到:', e.message))
  await wait(3000)
  const crumb = await d.texts('.crumbs, [class*="crumb"]', 4)
  console.log('  面包屑:', JSON.stringify(crumb))
  const after = await d.eval(`(async () => { const u = localStorage.getItem('memoket.user') || 'terrence'; const r = await fetch('/api/tree', { headers: { 'X-User-Id': u } }); return JSON.stringify(await r.json()).length })()`)
  console.log('  树大小:', before, '→', after)
  await d.shot('p70-b3-old-journal-light.png')

  console.log('— 深色（屏幕活动这一页）—')
  await openJourney(d)
  await toTop(d)
  await d.setTheme('dark'); await wait(1200)
  const white = await d.eval(`(() => {
    let n = 0
    for (const e of document.querySelectorAll('*')) {
      const c = getComputedStyle(e).backgroundColor
      const m = c.match(/rgba?\\((\\d+), ?(\\d+), ?(\\d+)(?:, ?([\\d.]+))?\\)/)
      if (!m) continue
      const [r, g, b, a] = [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]]
      if (a > 0.9 && r > 235 && g > 235 && b > 235) { const q = e.getBoundingClientRect(); if (q.width > 40 && q.height > 20) n++ }
    }
    return n
  })()`)
  console.log('  深色下近白的大块:', white)
  await d.shot('p70-b3-old-journey-dark.png')
  await d.setTheme('light'); await wait(600)
  void until
}
