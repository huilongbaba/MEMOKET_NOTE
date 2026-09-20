// P58 · A3：**「删不掉要吵」在壳上摆一次**（P21 立的规矩，P50「留给下一批」③）。
//
// P50 试的是「把 `/api/journey*` 的 fetch 拦掉」，那样 `day` 是 null → `segs` 空 →
// 「删掉这一天」本来就置灰，这条路根本走不到确认框。
// 这一趟换个摆法：**把昨天那个目录 chmod 500**——读得进来（页面照常画、钮照常亮），
// 删的时候 `rm_tree` 一条都删不掉，后端 500，页面上那句红字才摆得出来。
import { openJourney, pageText, toTop, toasts, until, wait } from './lib52.mjs'

const line = (t, re) => (t.match(re) || [])[0] || null

async function clickTitle(d, title) {
  const r = await d.eval(`(() => {
    const b = document.querySelector('button[title=${JSON.stringify(title)}]')
    if (!b) return { found: false }
    if (b.disabled) return { found: true, dis: true }
    b.scrollIntoView({ block: 'center' })
    return { found: true, dis: false }
  })()`)
  if (!r.found) throw new Error(`找不到 title=${title} 的钮`)
  if (r.dis) return { dis: true }
  await wait(350)
  const box = await d.eval(`(() => { const b = document.querySelector('button[title=${JSON.stringify(title)}]'); const r = b.getBoundingClientRect(); return { cx: r.x + r.width/2, cy: r.y + r.height/2 } })()`)
  await d.clickAt(box.cx, box.cy)
  await wait(1200)
  return { dis: false }
}

async function clickExact(d, text) {
  const r = await d.eval(`(() => {
    const all = Array.from(document.querySelectorAll('button')).filter((e) => (e.textContent || '').replace(/\\s+/g, ' ').trim() === ${JSON.stringify(text)})
    if (!all.length) return { found: false, all: Array.from(document.querySelectorAll('button')).map((e) => (e.textContent||'').replace(/\\s+/g,' ').trim()).slice(0, 60) }
    all[0].scrollIntoView({ block: 'center' })
    return { found: true, dis: all[0].disabled }
  })()`)
  if (!r.found) throw new Error(`找不到「${text}」；页面上的钮：${JSON.stringify(r.all)}`)
  await wait(350)
  const box = await d.eval(`(() => { const el = Array.from(document.querySelectorAll('button')).filter((e) => (e.textContent || '').replace(/\\s+/g, ' ').trim() === ${JSON.stringify(text)})[0]; const r = el.getBoundingClientRect(); return { cx: r.x + r.width/2, cy: r.y + r.height/2, dis: el.disabled } })()`)
  await d.clickAt(box.cx, box.cy)
  await wait(1500)
  return box
}

export default async function (d, [tag, day]) {
  await openJourney(d)
  await toTop(d)
  console.log('翻到昨天（那一天的目录是 chmod 500 的）')
  await clickTitle(d, '上一条记录')
  await toTop(d)
  const t0 = await pageText(d)
  console.log('  标题:', line(t0, /\d{4}-\d{2}-\d{2} · 屏幕活动/), '（该是', day, '）')
  console.log('  段数那一行:', line(t0, /[这今]天 \d+ 段[^\n]*/))
  const delBtn = await d.eval(`(() => { const b = Array.from(document.querySelectorAll('button')).find((e) => (e.textContent||'').includes('删掉这一天')); return b ? { dis: b.disabled, t: b.textContent.trim() } : null })()`)
  console.log('  「删掉这一天」:', JSON.stringify(delBtn), '← 目录读得进来，所以它是亮的')

  await clickExact(d, '删掉这一天')
  await toTop(d)
  const t1 = await pageText(d)
  console.log('  确认框在吗:', await d.count('.journey-keep-confirm'))
  console.log('  确认框里逐条:', JSON.stringify(await d.texts('.journey-keep-confirm li', 10)))
  await d.shot(`p70-${tag}-1-ro-confirm-light.png`)

  console.log('按下「确认删掉这一天」——后端删不掉，该吵')
  await clickExact(d, '确认删掉这一天')
  const said = await until(async () => {
    const ts = await toasts(d)
    return ts.length ? ts : null
  }, 20000, 500)
  console.log('  toast:', JSON.stringify(said))
  // —— P56 ④ 那条新拼法，在**壳上**量一遍（P56 只量到后端拼串那一层）——
  const body = (said || []).join('\n')
  const lines = body.split('\n').filter((x) => x.trim())
  const abs = lines.filter((x) => /\/(private\/)?tmp\/|\/Users\//.test(x))
  console.log('  ——P56 ④ 量一遍——')
  console.log('   总字符:', body.length, ' 行数:', lines.length,
              ' 最长一行:', Math.max(0, ...lines.map((x) => x.length)))
  console.log('   正文行里出现绝对路径的行数（P56 收完该 0）:', abs.length,
              JSON.stringify(abs.slice(0, 3)))
  console.log('   抬头那一行:', JSON.stringify(lines[0]))
  console.log('   其余各行:', JSON.stringify(lines.slice(1, 9)))
  await d.shot(`p70-${tag}-2-ro-toast-light.png`)
  const t2 = await pageText(d)
  console.log('  这一天还在吗（标题）:', line(t2, /\d{4}-\d{2}-\d{2} · 屏幕活动/))
  console.log('  段数那一行:', line(t2, /[这今]天 \d+ 段[^\n]*/))
  console.log('  后端直接问一次:', (await d.eval(`(async () => {
    const u = localStorage.getItem('memoket.user') || 'default'
    const r = await fetch('/api/journey/day?date=${day}', { headers: { 'X-User-Id': u } })
    const j = await r.json(); return r.status + ' segments=' + j.segments.length
  })()`)))
}
