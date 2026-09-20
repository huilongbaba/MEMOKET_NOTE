// P58 · 新用户那一趟的收尾两格：
//   ① 上一趟**漏了一步**：P47 的原话是「填假端点 → …→ **点 chip** →「保存」→ 红条和状态栏那句同时消失」。
//      上一趟没点模型名那个 chip 就按了保存，于是 toast 逐字
//      「保存了，但模型还没配全——填上地址和模型名，AI 功能才用得了」、红条留着
//      ——**那是对的行为，不是缺陷**。这一趟把那一步补上。
//   ② 900px 下溢出的那一个是 `.note-tab`「屏幕活动×」。量清楚它的 × 到底够不够得着。
import { clickBtn, toTop, wait } from './lib52.mjs'
import { pageText } from './lib.mjs'
import { USER } from '../whoami.mjs'

const line = (t, re) => (t.match(re) || [])[0] || null

export default async function (d, [llmPort]) {
  await wait(2500)
  await d.setTheme('light'); await wait(500)

  const deep = await d.eval(`(() => {
    const all = Array.from(document.querySelectorAll('*')).filter((e) => (e.textContent||'').includes('还没配模型 · 去设置') && e.children.length <= 2)
    const el = all[all.length - 1]; if (!el) return null
    const b = el.getBoundingClientRect(); return { cx: b.x + b.width/2, cy: b.y + b.height/2 }
  })()`)
  if (!deep) { console.log('  状态栏那一行已经没了？'); } else { await d.clickAt(deep.cx, deep.cy); await wait(1800) }
  await toTop(d)

  const inputs = await d.eval(`Array.from(document.querySelectorAll('input, select, textarea')).map((e, i) => ({ i, type: e.type, ph: e.placeholder || '', val: String(e.value).slice(0,60) }))`)
  const addr = inputs.find((x) => /11434|地址|http/.test(x.ph) && x.type === 'text')
  await d.click('input', { idx: addr.i })
  await d.key('a', ['meta'], { commands: ['selectAll'] })
  await d.insert('http://127.0.0.1:' + llmPort + '/v1')
  await wait(400)
  const test = await d.findText('button', '测一下')
  await d.clickAt(test.cx, test.cy); await wait(3000)
  console.log('  测一下:', line(await pageText(d), /连上了[^\n]{0,80}/))

  // 「先用第一个「fake-p52」」那个 chip
  const chips = await d.eval(`Array.from(document.querySelectorAll('button.chip, .chip')).map((e, i) => {
    const r = e.getBoundingClientRect()
    return { i, t: (e.textContent||'').replace(/\\s+/g,' ').trim().slice(0, 24), y: Math.round(r.y) }
  }).filter((c) => /fake/.test(c.t))`)
  console.log('  模型名 chip:', JSON.stringify(chips))
  if (chips.length) {
    await clickBtn(d, chips[0].t, { exact: false })
    await wait(1200)
    const mv = await d.eval(`Array.from(document.querySelectorAll('input')).map((e) => String(e.value)).filter((v) => /fake/.test(v))`)
    console.log('  点完之后哪个格里写着模型名:', JSON.stringify(mv))
  }
  await clickBtn(d, '保存')
  await wait(3500)
  const t = await pageText(d)
  console.log('  保存之后「还没配模型」还在吗（该 false）:', t.includes('还没配模型'))
  console.log('  红条还在吗:', t.includes('还没配模型，AI 功能全都用不了'))
  console.log('  toast:', JSON.stringify(await d.toasts()))
  console.log('  库里:', await d.eval(`(async () => {
    const u = ${USER}
    const r = await fetch('/api/settings/provider', { headers: { 'X-User-Id': u } })
    const j = await r.json()
    return JSON.stringify({ provider: j.provider, local_base_url: j.local_base_url, local_model: j.local_model })
  })()`))
  await d.shot('p70-bnew3-1-saved-light.png')

  console.log('=== ② 900px：标签条那 4px ===')
  await d.resize(900, 900); await wait(1000)
  const tabs = await d.eval(`(() => {
    const out = []
    for (const e of document.querySelectorAll('.note-tab')) {
      const r = e.getBoundingClientRect()
      const x = e.querySelector('button, .note-tab-close, [class*="close"]')
      const xr = x ? x.getBoundingClientRect() : null
      out.push({ text: (e.textContent||'').replace(/\\s+/g,' ').trim().slice(0, 16),
                 left: Math.round(r.left), right: Math.round(r.right),
                 xRight: xr ? Math.round(xr.right) : null, xLeft: xr ? Math.round(xr.left) : null })
    }
    const strip = document.querySelector('.note-tabs, [class*="note-tab"]')?.parentElement
    return { innerWidth, tabs: out,
             stripScroll: strip ? { sw: strip.scrollWidth, cw: strip.clientWidth, overflowX: getComputedStyle(strip).overflowX } : null }
  })()`)
  console.log('  ', JSON.stringify(tabs))
  await d.shot('p70-bnew3-2-tabs900-light.png')
  await d.resize(0)
}
