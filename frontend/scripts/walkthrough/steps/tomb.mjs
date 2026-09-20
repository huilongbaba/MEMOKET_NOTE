// P58 · A2：**段被逐条删光、只剩墓碑的那一天**（P50 问题 #3）在壳上摆一次。
//
// 这个 udd 的今天：4 段全部走真的 `DELETE /segment` 删掉了（盘上 4 条墓碑，
// `segments.json` 还在）；昨天 2 段 + 一份日报；前天 `[]`。
// 修之前：`/days` 会把今天和前天都列出来，翻过去是「这一天没有记录」，
// 而「删掉这一天」置灰——**既看不到也删不掉**。
import { openJourney, pageText, toTop, wait } from './lib52.mjs'

const line = (t, re) => (t.match(re) || [])[0] || null

export default async function (d, [tag, today, y]) {
  await openJourney(d)
  await toTop(d)
  const t0 = await pageText(d)
  console.log('— 今天（段全删光，只剩 4 条墓碑）—')
  console.log('  标题:', line(t0, /\d{4}-\d{2}-\d{2} · 屏幕活动/))
  console.log('  那一句:', line(t0, /今天还没有记录[^\n]*|这一天没有记录[^\n]*/))
  console.log('  知情选择那一屏出现了吗（不该）:', await d.count('.journey-consent'))
  const days = await d.eval(`(async () => { const u = localStorage.getItem('memoket.user') || 'default'; const r = await fetch('/api/journey/days', { headers: { 'X-User-Id': u } }); return JSON.stringify(await r.json()) })()`)
  console.log('  后端 /days:', days, '← 今天（墓碑）和前天（[]）都该不在里面')
  const nav = await d.eval(`(() => {
    const g = (t) => { const b = document.querySelector('button[title=' + JSON.stringify(t) + ']'); return b ? b.disabled : null }
    return { prev: g('上一条记录'), next: g('下一条记录') }
  })()`)
  console.log('  翻页两个箭头（true = 置灰）:', JSON.stringify(nav))
  await d.shot(`p70-${tag}-1-tomb-today-light.png`)

  console.log('— 按「上一条记录」：该落在', y, '（不是跳过它）—')
  const box = await d.eval(`(() => { const b = document.querySelector('button[title="上一条记录"]'); if (!b || b.disabled) return null; b.scrollIntoView({block:'center'}); const r = b.getBoundingClientRect(); return { cx: r.x + r.width/2, cy: r.y + r.height/2 } })()`)
  if (!box) { console.log('  「上一条记录」是灰的，翻不动'); return }
  await d.clickAt(box.cx, box.cy)
  await wait(1600)
  await toTop(d)
  const t1 = await pageText(d)
  console.log('  落在:', line(t1, /\d{4}-\d{2}-\d{2} · 屏幕活动/))
  console.log('  段数那一行:', line(t1, /[这今]天 \d+ 段[^\n]*/))
  const nav2 = await d.eval(`(() => {
    const g = (t) => { const b = document.querySelector('button[title=' + JSON.stringify(t) + ']'); return b ? b.disabled : null }
    return { prev: g('上一条记录'), next: g('下一条记录') }
  })()`)
  console.log('  翻页两个箭头（true = 置灰）:', JSON.stringify(nav2), '← 只剩这一天有记录，两边都该到头')
  await d.shot(`p70-${tag}-2-tomb-prev-light.png`)
}
