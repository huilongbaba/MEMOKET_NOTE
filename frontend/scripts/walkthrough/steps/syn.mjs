// P58 · A1 + A4：假采集源那一趟。
//   ① 那条「不是真的屏幕活动」的横幅在不在（误报比漏报更糟，所以另一趟也要核它不在）
//   ② `synthetic` 档摆出来的形状：假的「连续 3 小时」、「没截图补不了」、空的一天
//   ③ **真按下「开始记录」**（一张屏都不拍）→ 段真的攒出来 → 暂停 → 到点自己醒
import { journeyFacts, openJourney, pageText, toTop, until, wait } from './lib52.mjs'

const line = (t, re) => (t.match(re) || [])[0] || null

export default async function (d, [tag]) {
  await openJourney(d)
  const t0 = await pageText(d)
  console.log('— ① 假采集源那条横幅 —')
  console.log('  「不是真的屏幕活动」:', t0.includes('这一页画的不是真的屏幕活动'))
  console.log('  那一句逐字:', line(t0, /这一页画的不是真的屏幕活动[^\n]*/))

  console.log('— ② synthetic 档摆出来的形状 —')
  const f0 = await journeyFacts(d)
  console.log('  今天:', JSON.stringify(f0))
  const rows = await d.texts('.journey-desc', 20)
  console.log('  今天每一行写的是:', JSON.stringify(rows))
  const days = await d.eval(`(async () => { const r = await fetch('/api/journey/days', { headers: { 'X-User-Id': localStorage.getItem('memoket.user') || 'default' } }); return JSON.stringify(await r.json()) })()`)
  console.log('  后端 /days（**空的那一天该不在里面**，P50 问题 #3 修完的样子）:', days)
  await d.shot(`p70-${tag}-1-fake-today-light.png`)

  // 翻到昨天：那一段假的「连续 3 小时」+ 日报卡
  await toTop(d)
  const prev = await d.eval(`(() => { const b = document.querySelector('button[title="上一条记录"]'); if (!b || b.disabled) return null; b.scrollIntoView({block:'center'}); const r = b.getBoundingClientRect(); return { cx: r.x + r.width/2, cy: r.y + r.height/2 } })()`)
  if (prev) { await d.clickAt(prev.cx, prev.cy); await wait(1500) }
  const t1 = await pageText(d)
  console.log('  翻到昨天，标题:', line(t1, /\d{4}-\d{2}-\d{2} · 屏幕活动/))
  console.log('  日报卡:', await d.count('.journey-report'), '张；那一行:',
              line(t1, /这一天的回顾[^\n]*/))
  console.log('  假的「连续 3 小时」那一段（时长 vs 采样数）:',
              JSON.stringify((await d.texts('.journey-row', 10)).slice(0, 4)))
  await d.shot(`p70-${tag}-2-fake-yesterday-light.png`)

  console.log('— ③ 真按下「开始记录」（一张屏都不拍）—')
  // **先翻回今天**：往日那一页的状态行是空的（P50 走查那条规矩：翻到往日时
  // 「记录中」是句废话），在昨天那一页上读「已暂停」永远读不到。
  await d.eval(`window.dispatchEvent(new CustomEvent('journey-day', { detail: '' }))`)
  await wait(1500)
  await toTop(d)
  console.log('  翻回今天了吗:', line(await pageText(d), /\d{4}-\d{2}-\d{2} · 屏幕活动/))
  const st0 = await d.eval(`window.memoketDesktop.journey.state()`)
  console.log('  按之前:', JSON.stringify(st0))
  await d.eval(`window.memoketDesktop.journey.start()`)
  await wait(2500)
  const st1 = await d.eval(`window.memoketDesktop.journey.state()`)
  console.log('  按之后:', JSON.stringify(st1))
  const grew = await until(async () => {
    const s = await d.eval(`window.memoketDesktop.journey.state()`)
    return s.today > 4 ? s.today : null
  }, 25000, 1000)
  console.log('  假采集源真的攒出段了吗（今天原来 4 段）:', grew)

  console.log('— ④ 暂停 1 小时 → 页面上那一句 —')
  await d.eval(`window.memoketDesktop.journey.pause(60)`)
  await wait(800)
  // 页面每 30 秒对一次状态，而且**窗口看不见就不轮询**（util/poll）。走查里窗口
  // 多半不在前台，所以别干等——踢一次 visibilitychange，它会立刻 refresh 一次。
  await d.eval(`document.dispatchEvent(new Event('visibilitychange'))`)
  await until(async () => (await pageText(d)).includes('已暂停'), 40000, 1000)
  const t2 = await pageText(d)
  console.log('  状态那一行:', line(t2, /[^\n]*已暂停[^\n]*/))
  console.log('  右上角那个钮:', JSON.stringify(await d.texts('button', 60)).includes('继续记录'))
  await d.shot(`p70-${tag}-3-paused-light.png`)

  console.log('— ⑤ 暂停到点自己醒（P20 #4）—')
  // 托盘只给「暂停 1 小时」；这里走同一条 IPC（`journey:pause`）给一个短的到点时间，
  // 判的是 `capture.ts` 那一段「到点自己醒」，跟按 60 分钟走的是同一行代码。
  await d.eval(`window.memoketDesktop.journey.pause(0.05)`)   // 3 秒后到点
  const st2 = await d.eval(`window.memoketDesktop.journey.state()`)
  console.log('  刚暂停:', JSON.stringify(st2))
  const woke = await until(async () => {
    const s = await d.eval(`window.memoketDesktop.journey.state()`)
    return s.state === 'running' ? s : null
  }, 45000, 1500)
  console.log('  到点自己醒了吗:', JSON.stringify(woke))

  console.log('— ⑥ 收摊：停掉记录（`on` 不许留在盘上）—')
  await d.eval(`window.memoketDesktop.journey.stop()`)
  await wait(1200)
  console.log('  停掉之后:', JSON.stringify(await d.eval(`window.memoketDesktop.journey.state()`)))
}
