// P58 走查 ⑧ 的一格：**P56 的 `emptyday` 档第一次在壳上摆**。
//
// P56 自己写着「验到后端那一层为止，没在打包壳上摆过就不冒充摆过」——
// 它改的是 `journey_fixture.py`：原来只造今天 `[]`，整个库一天记录都没有，
// 前端按 `state === 'off' && known.length === 0` 退回**知情选择屏**；
// 改成造两天（昨天一段 + 今天 `[]`）之后，该走到正常那一页再落到
// 「今天还没有记录」那一屏。这里就核这一件事，外加「删掉这一天」那个钮的状态。
import { journeyFacts, openJourney, pageText, toTop, wait } from './lib52.mjs'
import { USER } from '../whoami.mjs'

export default async function (d, [shotName]) {
  await d.setTheme('light'); await wait(600)
  await openJourney(d)
  await toTop(d)
  const t = await pageText(d)

  console.log('  知情选择屏还在吗（该 0 —— 在的话就是 P56 改之前那个局面）:', await d.count('.journey-consent'))
  console.log('  「今天还没有记录」那一句:',
              JSON.stringify((t.match(/[^\n]*今天还没有记录[^\n]*/) || [])[0]))
  console.log('  「现在没在记录」那半句:', t.includes('现在没在记录'))
  console.log('  「点右上角「开始记录」才会开始攒」:', t.includes('才会开始攒'))
  console.log('  facts:', JSON.stringify(await journeyFacts(d)))

  const days = await d.eval(`(async () => {
    const u = ${USER}
    const r = await fetch('/api/journey/days', { headers: { 'X-User-Id': u } })
    return JSON.stringify(await r.json())
  })()`)
  console.log('  后端 days()（该非空 —— 这正是 P56 改的那一格）:', days)

  const btns = await d.eval(`Array.from(document.querySelectorAll('button')).map((e) => ({
    t: (e.textContent||'').replace(/\\s+/g,' ').trim().slice(0, 18), dis: e.disabled }))
    .filter((b) => b.t)`)
  console.log('  这一页上的钮:', JSON.stringify(btns))
  const del = btns.find((b) => b.t.includes('删掉这一天'))
  console.log('  「删掉这一天」:', JSON.stringify(del), '（空的一天该置灰，P31 #3）')
  await d.shot(shotName)

  console.log('=== 翻到昨天（有记录的那一天）===')
  const prev = await d.eval(`(() => {
    const all = Array.from(document.querySelectorAll('button')).filter((e) => {
      const l = (e.getAttribute('aria-label') || e.title || e.textContent || '')
      return /前一天|上一天|‹|←/.test(l)
    })
    const el = all[0]; if (!el) return null
    el.scrollIntoView({ block: 'center' })
    const r = el.getBoundingClientRect()
    return { cx: r.x + r.width/2, cy: r.y + r.height/2, label: el.getAttribute('aria-label') || el.title || (el.textContent||'').trim() }
  })()`)
  console.log('  前一天那个钮:', JSON.stringify(prev))
  if (prev && prev.cy > 0) {
    await d.clickAt(prev.cx, prev.cy); await wait(2500)
    const t2 = await pageText(d)
    console.log('  翻过去之后标题:', JSON.stringify((t2.match(/\d{4}-\d{2}-\d{2} · 屏幕活动/) || [])[0]))
    console.log('  段数那一行:', JSON.stringify((t2.match(/[今这]天 \d+ 段[^\n]*/) || [])[0]))
    console.log('  facts:', JSON.stringify(await journeyFacts(d)))
  }
}
