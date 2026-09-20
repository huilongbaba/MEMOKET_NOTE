// P50 走查共用的量具。
//
// **「选不到 ≠ 没有」**（P17/P31/P35/P47 各栽过）：选不到先把候选都列出来，再换选择器。
// P47 的 `whoami.mjs` 就栽在这上面——它拿 `fetch('/api/tree?user=terrence')` 量身份，
// 而后端认的是 **`X-User-Id` 头**（`routers/deps.current_user`），查询串它压根不看。
// 于是不管窗口里开着谁，那条日志一律报 `[]`。这一版一律带头。

import { USER, USER_SOFT } from '../whoami.mjs'
export const wait = (ms) => new Promise((r) => setTimeout(r, ms))

/** 等到 fn() 为真（或超时）。**别用固定 sleep**。 */
export async function until(fn, ms = 20000, step = 250) {
  const t0 = Date.now()
  for (;;) {
    const v = await fn()
    if (v) return v
    if (Date.now() - t0 > ms) return null
    await wait(step)
  }
}

export async function pageText(d) {
  return d.eval(`document.body.innerText.replace(/\\n{3,}/g, '\\n\\n')`)
}

export async function toasts(d) {
  // P62 ①：通配会把外层容器 `.toaster` 一起选中（那个串里含 `toast`），
  // 一条读回来是两条一模一样的字。走公共那份精确选择器。
  return d.toasts()
}

/** 这个窗口现在是谁（前端自己记的那份身份，跟它发出去的头是同一个来源）。 */
export async function whoami(d) {
  return d.eval(`(() => {
    const u = ${USER_SOFT} || '(默认)'
    return u
  })()`)
}

/** 拿窗口自己的身份问后端（**带 X-User-Id 头**）。 */
export async function api(d, path) {
  return d.eval(`(async () => {
    const u = ${USER}
    const r = await fetch(${JSON.stringify(path)}, { headers: { 'X-User-Id': u } })
    const t = await r.text()
    return r.status + ' ' + t.slice(0, 400)
  })()`)
}

/** 打开屏幕活动那一页（启动栏那个去处）。`open-virtual` 是 App 自己的事件。
 *
 *  **每次进来都先滚回页顶**：这一页有两屏多，上一个步骤滚到「留多久」那块之后，
 *  页头那两个翻页箭头的 bbox 是**负的 y**（`cy: -1488`，实拍），
 *  拿它去点就是点在窗口外面——一声不响地什么都没发生，看起来像「翻页坏了」。 */
export async function openJourney(d) {
  await d.eval(`window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'app:journey' }))`)
  await wait(1800)
  const ok = await until(async () => (await pageText(d)).includes('屏幕活动'), 15000)
  await toTop(d)
  return ok
}

/** 滚回页顶（这一页的滚动容器不是 window，是 `.kb-page` 的某个祖先）。 */
export async function toTop(d) {
  await d.eval(`(() => {
    const p = document.querySelector('.kb-page')
    let e = p
    while (e) { if (e.scrollHeight > e.clientHeight + 4) { e.scrollTop = 0 } e = e.parentElement }
    window.scrollTo(0, 0)
    return true
  })()`)
  await wait(400)
}

/** 页面上所有按钮（文字 + 禁没禁用 + 位置），点之前先列一遍。 */
export async function buttons(d) {
  return d.eval(`Array.from(document.querySelectorAll('button')).map((e, i) => {
    const r = e.getBoundingClientRect()
    return { i, t: (e.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 24),
             title: e.title || e.getAttribute('aria-label') || '',
             dis: e.disabled, cls: (e.className || '').toString().slice(0, 40),
             x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width) }
  })`)
}

/** 按**准确文字**点一个钮：先 scrollIntoView、再**重读 bbox**，最后真鼠标点下去。
 *  （滚过之后 bbox 就变了，拿滚之前那份去点会点到别的东西上。） */
export async function clickBtn(d, text, { exact = true, idx = 0 } = {}) {
  const r = await d.eval(`(() => {
    const all = Array.from(document.querySelectorAll('button')).filter((e) => {
      const t = (e.textContent || '').replace(/\\s+/g, ' ').trim()
      return ${exact} ? t === ${JSON.stringify(text)} : t.includes(${JSON.stringify(text)})
    })
    const el = all[${idx}]
    if (!el) return { n: all.length, found: false,
      all: Array.from(document.querySelectorAll('button')).map((e) => (e.textContent||'').replace(/\\s+/g,' ').trim()).slice(0, 60) }
    el.scrollIntoView({ block: 'center' })
    return { n: all.length, found: true, dis: el.disabled }
  })()`)
  if (!r.found) throw new Error(`clickBtn 找不到「${text}」；页面上的钮：${JSON.stringify(r.all)}`)
  await wait(400)                                   // 滚动落定，再重读 bbox
  const box = await d.eval(`(() => {
    const all = Array.from(document.querySelectorAll('button')).filter((e) => {
      const t = (e.textContent || '').replace(/\\s+/g, ' ').trim()
      return ${exact} ? t === ${JSON.stringify(text)} : t.includes(${JSON.stringify(text)})
    })
    const el = all[${idx}]; if (!el) return null
    const r = el.getBoundingClientRect()
    return { cx: r.x + r.width / 2, cy: r.y + r.height / 2, dis: el.disabled, t: (el.textContent||'').trim().slice(0,24) }
  })()`)
  if (!box) throw new Error(`clickBtn 重读 bbox 时「${text}」没了`)
  await d.clickAt(box.cx, box.cy)
  return box
}

/** 这一页上读得出来的「事实」——走查表每一格都拿它对。 */
export async function journeyFacts(d) {
  return d.eval(`(() => {
    const t = document.body.innerText
    const q = (s) => document.querySelectorAll(s).length
    return {
      title: (t.match(/\\d{4}-\\d{2}-\\d{2} · 屏幕活动/) || [])[0] || null,
      stateLine: (t.match(/^[^\\n]*(记录中|没在记录|已暂停)[^\\n]*$/m) || [])[0] || null,
      countLine: (t.match(/[今这]天 \\d+ 段，合计[^\\n]*/) || [])[0] || null,
      band: q('.journey-band > span'),
      gaps: q('.journey-gap'),
      legend: q('.journey-legend .badge'),
      runs: q('.journey-run'),
      rows: q('.journey-row'),
      thumbs: q('img.journey-thumb'),
      consent: q('.journey-consent'),
      facts: q('.journey-facts dt'),
      keepPanel: q('.journey-keep') + q('[class*="journey-keep"]'),
      confirmDay: q('.journey-keep-confirm'),
      confirmSeg: q('.journey-row-confirm'),
      spanHint: q('.journey-span-hint'),
      reportCard: q('.journey-report'),
      reportNotes: q('.journey-report-notes li'),
      describeBtn: (t.match(/描述这 \\d+ 段/) || [])[0] || null,
      writeBtn: (t.match(/写这一天的回顾（\\d+ 段）/) || [])[0] || null,
    }
  })()`)
}
