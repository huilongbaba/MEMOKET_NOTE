// P58 问题 #8 单独复现：**翻到别的一天之后，「删掉这一天」的确认框该作废。**
//
// P58 那一趟没摆干净，因为它连点两下**同一个**箭头（「上一条记录」）：
// 站在最早那一天上，那个钮是 `disabled`，第二下什么都没发生——
// 于是「确认框还在」被读成产品问题，实际上**那一下压根没翻页**。
// 这一版的规矩：**翻页之前先把两个箭头的 `disabled` 打出来，只点亮着的那个，
// 并且用「日期真的变了」当翻页成功的判据**，不拿「点过了」当翻过了。
import { clickExact } from './clickexact.mjs'
import { openJourney, pageText, toTop, wait } from './lib52.mjs'

const day = (t) => ((t.match(/\d{4}-\d{2}-\d{2} · 屏幕活动/) || [])[0] || null)

async function navBtns(d) {
  return d.eval(`Array.from(document.querySelectorAll('button')).map((e) => ({
    t: (e.title || e.getAttribute('aria-label') || (e.textContent||'')).replace(/\\s+/g,' ').trim().slice(0, 12),
    dis: e.disabled
  })).filter((b) => /上一条记录|下一条记录/.test(b.t))`)
}

async function openConfirm(d) {
  await toTop(d)
  await clickExact(d, '删掉这一天', 0, 4).catch((e) => console.log('    没点到「删掉这一天」:', e.message))
  await wait(1000)
  return d.count('.journey-keep-confirm')
}

/** 只点**亮着的**那个箭头；回 { clicked, from, to } */
async function flip(d) {
  const from = day(await pageText(d))
  const btns = await navBtns(d)
  console.log('    两个箭头:', JSON.stringify(btns))
  const live = btns.find((b) => !b.dis)
  if (!live) return { clicked: null, from, to: from }
  await toTop(d)
  await clickExact(d, live.t, 0, 4).catch(async () => {
    const r = await d.eval(`(() => {
      const el = Array.from(document.querySelectorAll('button')).find((e) => !e.disabled &&
        (e.title || e.getAttribute('aria-label') || '').includes(${JSON.stringify(live.t)}))
      if (!el) return null
      el.scrollIntoView({ block: 'center' })
      const q = el.getBoundingClientRect()
      return { cx: q.x + q.width / 2, cy: q.y + q.height / 2 }
    })()`)
    if (r) await d.clickAt(r.cx, r.cy)
  })
  await wait(2000)
  await toTop(d)
  return { clicked: live.t, from, to: day(await pageText(d)) }
}

export default async function (d) {
  await d.setTheme('light'); await wait(400)
  await openJourney(d)
  await toTop(d)
  console.log('起点这一页:', day(await pageText(d)))

  for (let i = 1; i <= 2; i++) {
    console.log(`\n=== 第 ${i} 次：开确认框 → 翻天 → 确认框该没了 ===`)
    const n0 = await openConfirm(d)
    console.log('  开出来的确认框:', n0, '个')
    const f = await flip(d)
    console.log('  点的是:', JSON.stringify(f.clicked), ' 日期:', f.from, '→', f.to,
                ' **真翻了吗:**', f.from !== f.to)
    const n1 = await d.count('.journey-keep-confirm')
    console.log('  翻完之后确认框:', n1, '个（该 0）',
                f.from !== f.to ? (n1 === 0 ? '✔' : '✘ 没作废') : '（没翻成，这一格不算数）')
    await d.shot(`p70-b8-flipday-${i}-light.png`)
    if (f.from === f.to) break
  }
}
