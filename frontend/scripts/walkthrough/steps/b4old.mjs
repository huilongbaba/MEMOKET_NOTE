// P58 · 第九次全流程走查（老用户）第四趟：把上一趟量错 / 挑错素材的两格补上
//   · 一键全删那个钮叫「全部删掉」，不叫「删掉全部屏幕活动」（**「选不到 ≠ 没有」**）
//   · P44 问题 #5 的反面：上一趟挑的那篇**自己就有一层**，换一篇**真的没有层**的
import { clickExact } from './clickexact.mjs'
import { clickBtn, openJourney, pageText, toTop, toasts, wait } from './lib52.mjs'

export default async function (d) {
  await d.setTheme('light'); await wait(400)

  console.log('=== P44 问题 #5 的反面：新建一篇（一层都没有）===')
  await d.key('Escape'); await wait(300)
  await d.key('k', ['meta']); await wait(1000)
  await d.insert('新建笔记'); await wait(900)
  await clickExact(d, '新建笔记', 0, 8)
  await wait(3000)
  const fresh = await d.noteId()
  console.log('  新建出来的:', fresh)
  console.log('  右栏页签（不许有「改动」）:', JSON.stringify(await d.texts('.pane-tab', 12)))
  console.log('  toast（该一条都没有）:', JSON.stringify(await toasts(d)))
  console.log('  库里的层:', await d.eval(`(async () => {
    const u = localStorage.getItem('memoket.user') || 'terrence'
    const r = await fetch('/api/notes/' + ${JSON.stringify(fresh)} + '/change-layers', { headers: { 'X-User-Id': u } })
    return JSON.stringify(await r.json())
  })()`))
  await d.shot('p70-b4-old-nolayer-light.png')

  console.log('=== 一键全删（两段式，P21 #3）===')
  await openJourney(d)
  await toTop(d)
  const btns = await d.eval(`Array.from(document.querySelectorAll('button')).map((e) => (e.textContent||'').replace(/\\s+/g,' ').trim()).filter((s) => /删/.test(s))`)
  console.log('  这一页上带「删」的钮:', JSON.stringify(btns))
  // **这个钮在页底**（保留期面板最下面）。`clickExact` 不滚动，拿到的 bbox 在视口外
  // ——点下去一声不响，读起来像「这个钮坏了」。P50 量具坑 #3 的第二个形状。
  console.log('  点之前 bbox:', JSON.stringify(await clickBtn(d, '全部删掉')))
  await wait(1300)
  const t = await pageText(d)
  console.log('  摊开那段:', JSON.stringify((t.match(/删掉全部屏幕活动[\s\S]{0,300}/) || [])[0]))
  console.log('  两个钮:', JSON.stringify(await d.eval(`Array.from(document.querySelectorAll('button')).map((e) => (e.textContent||'').replace(/\\s+/g,' ').trim()).filter((s) => /确认删掉|先不删/.test(s))`)))
  await d.shot('p70-b4-old-wipe-light.png')
  const days0 = await d.eval(`(async () => { const u = localStorage.getItem('memoket.user') || 'terrence'; const r = await fetch('/api/journey/days', { headers: { 'X-User-Id': u } }); return JSON.stringify(await r.json()) })()`)
  await clickBtn(d, '先不删')
  await wait(1500)
  const days1 = await d.eval(`(async () => { const u = localStorage.getItem('memoket.user') || 'terrence'; const r = await fetch('/api/journey/days', { headers: { 'X-User-Id': u } }); return JSON.stringify(await r.json()) })()`)
  console.log('  「先不删」之后天列表原封不动吗:', days0 === days1, days0, '→', days1)
  console.log('  确认框还在吗（该 0）:', await d.count('.journey-keep-confirm'))
}
