// P66：P64 问题 #6 的复核。**只做「一键全删」那一格**，别的不碰。
//
// P64 把根因记成「文案不对」（钮叫「全部删掉」，`b3old` 找的是「删掉全部屏幕活动」）。
// P66 先把文案改对了跑一趟 —— **还是读回 `undefined`**。
// 真根因是**两条**：文案 + **那个钮在页底，`clickExact` 不滚动**，
// 拿到的 bbox 在视口外，点下去一声不响。这一趟走 `clickBtn`（先 `scrollIntoView`）复核。
import { clickBtn, openJourney, pageText, toTop, wait } from './lib52.mjs'
import { clickExact } from './clickexact.mjs'
import { USER } from '../whoami.mjs'

export default async function (d) {
  await d.setTheme('light'); await wait(400)
  await openJourney(d)
  await toTop(d)
  const btns = await d.eval(`Array.from(document.querySelectorAll('button')).map((e) => (e.textContent||'').replace(/\\s+/g,' ').trim()).filter((s) => /删/.test(s))`)
  console.log('  这一页上带「删」的钮:', JSON.stringify(btns))
  console.log('  点之前 bbox:', JSON.stringify(await clickBtn(d, '全部删掉')))
  await wait(1300)
  const t = await pageText(d)
  console.log('  摊开那段:', JSON.stringify((t.match(/删掉全部屏幕活动[\s\S]{0,300}/) || [])[0]))
  console.log('  两个钮:', JSON.stringify(await d.eval(`Array.from(document.querySelectorAll('button')).map((e) => (e.textContent||'').replace(/\\s+/g,' ').trim()).filter((s) => /确认删掉|先不删/.test(s))`)))
  await d.shot('p70-b3b-old-wipe-light.png')
  const days0 = await d.eval(`(async () => { const u = ${USER}; const r = await fetch('/api/journey/days', { headers: { 'X-User-Id': u } }); return JSON.stringify(await r.json()) })()`)
  await clickExact(d, '先不删', 0, 4).catch((e) => console.log('  没点到「先不删」:', e.message))
  await wait(1000)
  const days1 = await d.eval(`(async () => { const u = ${USER}; const r = await fetch('/api/journey/days', { headers: { 'X-User-Id': u } }); return JSON.stringify(await r.json()) })()`)
  console.log('  「先不删」之后天列表原封不动吗:', days0 === days1, days0, '→', days1)
  console.log('  确认框还在吗（该 0）:', await d.count('.journey-keep-confirm'))
}
