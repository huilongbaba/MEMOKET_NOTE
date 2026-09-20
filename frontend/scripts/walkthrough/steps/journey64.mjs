// P66 C 第 8 步：屏幕活动 —— 顺带把 **P62 ③「历史坏数据提示」在壳上摆出来**。
//
// P62 做了这条判据（`JourneyPage.overlongExcess`），但那一批**没起壳**，
// 所以它到今天一次都没在界面上出现过。这一趟：
//   · 今天那一页照走查表的老口径读一遍（段数 / 合计 / 图例 / 按钮 / 保留期）；
//   · 翻到造出来的那一天（`mkoverlong64.py`，两段各吞了 1 小时）→ **那句话该在**；
//   · **反例**：翻回一天正常的 → **那句话不许在**（一句永远都在的提示不是提示）。
//
// usage: journey64.mjs <偏长那天 yyyy-mm-dd> <正常那天 yyyy-mm-dd> <截图前缀>
import { openJourney, pageText, toTop, until, wait } from './lib52.mjs'

const SAY = '这个「合计」偏长'

async function stateLine(d) {
  const t = await pageText(d)
  return (t.match(/[^\n]*(合计|还没有记录|没在记录)[^\n]*/g) || []).slice(0, 3)
}

/** 直接翻到某一天（页面自己的翻页箭头一次只走一天，造出来那天在三天前）。 */
async function goDay(d, day) {
  await d.eval(`window.dispatchEvent(new CustomEvent('journey-day', { detail: ${JSON.stringify(day)} }))`)
  await wait(2500)
  return until(async () => ((await pageText(d)).includes(day) ? true : null), 20000, 800)
}

export default async function (d, [badDay, goodDay, shot]) {
  await until(async () => (await pageText(d)).length > 50, 30000)
  await wait(1200)
  await d.setTheme('light'); await wait(400)
  console.log('打开屏幕活动那一页:', await openJourney(d))
  await toTop(d)

  console.log('=== 今天那一页（走查表第 8 步的老口径）===')
  console.log('  状态行:', JSON.stringify(await stateLine(d)))
  const t0 = await pageText(d)
  for (const s of ['开始记录', '暂停 1 小时', '去这天的日记', '删掉这一天',
                   '这一页画的不是真的屏幕活动', SAY]) {
    console.log(`  含「${s}」:`, t0.includes(s))
  }
  // **天列表走后端那份，不走页面上的 <option>**：第一版写的是
  // `.journey-day-opt, option` —— 前端里**根本没有 .journey-day-opt 这个类**
  // （$S/selfcheck-selectors.mjs 当场点名了），`option` 于是退回去把「留多久」
  // 那两个下拉的选项读了回来，打出来是「1 周（7 天）/ 3 个月（90 天）…」。
  // **「选到东西 ≠ 选到那个东西」**。
  console.log('  天列表（后端 /api/journey/days）:', await d.eval(`(async () => {
    const u = localStorage.getItem('memoket.user') || 'terrence'
    const r = await fetch('/api/journey/days', { headers: { 'X-User-Id': u } })
    return JSON.stringify(await r.json())
  })()`))
  await d.shot(shot + '-today-light.png')

  console.log(`\n=== 翻到${badDay}（两段各吞了 1 小时）—— P62 ③ 那句话该在 ===`)
  const okBad = await goDay(d, badDay)
  console.log('  翻过去了吗（**「点过了」不等于「翻过了」**，判据是日期真的变了）:', okBad)
  const tb = await pageText(d)
  const line = (tb.match(new RegExp('[^\\n]*' + SAY + '[^\\n]*(\\n[^\\n]*)?')) || [])[0]
  console.log('  状态行:', JSON.stringify(await stateLine(d)))
  console.log('  「' + SAY + '」在吗（该 true）:', tb.includes(SAY))
  console.log('  那句话逐字:', JSON.stringify((line || '').replace(/\s+/g, ' ').trim()))
  await d.shot(shot + '-overlong-light.png')
  await d.setTheme('dark'); await wait(900)
  await d.shot(shot + '-overlong-dark.png')
  await d.setTheme('light'); await wait(500)

  console.log(`\n=== 反例：翻到${goodDay}（正常的一天）—— 那句话**不许**在 ===`)
  const okGood = await goDay(d, goodDay)
  console.log('  翻过去了吗:', okGood)
  const tg = await pageText(d)
  console.log('  状态行:', JSON.stringify(await stateLine(d)))
  console.log('  「' + SAY + '」在吗（**该 false**）:', tg.includes(SAY))
  await d.shot(shot + '-normal-light.png')

  // **两头都得会吵**（突变验要砍的就是它）：只打两行 true/false 的探针当不了闸。
  if (!tb.includes(SAY)) throw new Error(`${badDay} 那天该说「${SAY}」，没说 —— 逐段那条判据没开火`)
  if (tg.includes(SAY)) throw new Error(`${goodDay} 那天不该说「${SAY}」，却说了 —— 判错的提示比不提示更伤`)
}
