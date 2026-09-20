// P58 · 新用户那一趟两格要重量：
//   ① 「保存」之后红条没消失 —— **先分清「没点上 / 点错了」和「真没保存」**
//      （`provider_config` 收工时 0 行 = 那一下压根没落库）。这一版把设置页上
//      所有钮列出来再点，点完直接问后端要 `provider_config`。
//   ② 900px 下有 1 个元素横向溢出 —— 把它是谁打出来（P47 是 0 个）
import { clickBtn, toTop, wait } from './lib52.mjs'
import { pageText } from './lib.mjs'

const line = (t, re) => (t.match(re) || [])[0] || null

export default async function (d, [llmPort]) {
  await wait(2500)
  await d.setTheme('light'); await wait(500)

  console.log('=== ① 设置页 → 填地址 → 测一下 → 保存 → **问库** ===')
  const deep = await d.eval(`(() => {
    const all = Array.from(document.querySelectorAll('*')).filter((e) => (e.textContent||'').includes('还没配模型 · 去设置') && e.children.length <= 2)
    const el = all[all.length - 1]; if (!el) return null
    const b = el.getBoundingClientRect(); return { cx: b.x + b.width/2, cy: b.y + b.height/2 }
  })()`)
  if (!deep) return console.log('  找不到状态栏那一行')
  await d.clickAt(deep.cx, deep.cy); await wait(1800)
  await toTop(d)

  const btns = await d.eval(`Array.from(document.querySelectorAll('button')).map((e, i) => {
    const r = e.getBoundingClientRect()
    return { i, t: (e.textContent||'').replace(/\\s+/g,' ').trim().slice(0, 20), dis: e.disabled,
             cls: String(e.className).slice(0, 40), x: Math.round(r.x), y: Math.round(r.y) }
  })`)
  console.log('  设置页上的钮:')
  for (const b of btns) console.log('   ', JSON.stringify(b))

  const inputs = await d.eval(`Array.from(document.querySelectorAll('input, select, textarea')).map((e, i) => ({ i, type: e.type, ph: e.placeholder || '', val: String(e.value).slice(0,60) }))`)
  const addr = inputs.find((x) => /11434|地址|http/.test(x.ph) && x.type === 'text')
  console.log('  地址格:', JSON.stringify(addr))
  await d.click('input', { idx: addr.i })
  await d.key('a', ['meta'], { commands: ['selectAll'] })
  await d.insert('http://127.0.0.1:' + llmPort + '/v1')
  await wait(400)
  const test = await d.findText('button', '测一下')
  await d.clickAt(test.cx, test.cy); await wait(3000)
  console.log('  测一下:', line(await pageText(d), /连上了[^\n]{0,80}/))

  // 「保存」可能不止一个：把每一个都打出来，再挑**离地址格最近的那个**
  const saves = await d.eval(`Array.from(document.querySelectorAll('button')).map((e, i) => {
    const r = e.getBoundingClientRect()
    return { i, t: (e.textContent||'').replace(/\\s+/g,' ').trim(), dis: e.disabled, y: Math.round(r.y), cls: String(e.className).slice(0, 30) }
  }).filter((b) => /保存/.test(b.t))`)
  console.log('  带「保存」的钮:', JSON.stringify(saves))
  const box = await clickBtn(d, saves[0].t)
  console.log('  点的是:', JSON.stringify(box))
  await wait(3000)
  const t = await pageText(d)
  console.log('  保存之后「还没配模型」还在吗:', t.includes('还没配模型'))
  console.log('  toast:', JSON.stringify(await d.toasts()))
  console.log('  后端 /api/provider（库里真落了吗）:', await d.eval(`(async () => {
    const u = localStorage.getItem('memoket.user') || 'default'
    for (const p of ['/api/provider', '/api/settings/provider', '/api/provider-config']) {
      const r = await fetch(p, { headers: { 'X-User-Id': u } })
      if (r.ok) return p + ' → ' + (await r.text()).slice(0, 300)
    }
    return '(三个路径都不是)'
  })()`))
  await d.shot('p70-bnew2-1-saved-light.png')

  console.log('=== ② 900px 下那一个溢出的是谁 ===')
  await d.resize(900, 900); await wait(1000)
  const over = await d.eval(`(() => {
    const out = []
    for (const e of document.querySelectorAll('*')) {
      const r = e.getBoundingClientRect()
      if (r.width > 0 && r.right > innerWidth + 1) {
        out.push({ tag: e.tagName, cls: String(e.className).slice(0, 60),
                   right: Math.round(r.right), w: Math.round(r.width), h: Math.round(r.height),
                   text: (e.textContent||'').replace(/\\s+/g,' ').trim().slice(0, 40) })
      }
    }
    return { innerWidth, n: out.length, out: out.slice(0, 8) }
  })()`)
  console.log('  ', JSON.stringify(over))
  console.log('  页面横向滚得动吗:', await d.eval(`document.documentElement.scrollWidth > document.documentElement.clientWidth + 1`))
  await d.shot('p70-bnew2-2-900-light.png')
  await d.resize(0)
}
