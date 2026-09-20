// P58 · 第九次全流程走查（空库新用户）：①②③⑧⑨⑪
import { clickExact } from './clickexact.mjs'
import { journeyFacts, openJourney, toTop, wait } from './lib52.mjs'
import { docText, pageText, until } from './lib.mjs'

const line = (t, re) => (t.match(re) || [])[0] || null

export default async function (d, [llmPort]) {
  await until(async () => (await pageText(d)).length > 50, 30000)
  await wait(1500)
  await d.setTheme('light'); await wait(500)

  console.log('=== ① 第一次打开 → 状态栏「还没配模型 · 去设置」（P19 #1 / P17 #1）===')
  const t0 = await pageText(d)
  for (const s of ['还没配模型', '去设置', 'LLM 不可达', '192.168', '10.0.', '172.16.']) {
    console.log(`  含「${s}」:`, t0.includes(s))
  }
  await d.shot('p70-bnew-1-open-light.png')

  const deep = await d.eval(`(() => {
    const all = Array.from(document.querySelectorAll('*')).filter((e) => (e.textContent||'').includes('还没配模型 · 去设置') && e.children.length <= 2)
    const el = all[all.length - 1]; if (!el) return null
    const b = el.getBoundingClientRect(); return { cx: b.x + b.width/2, cy: b.y + b.height/2 }
  })()`)
  if (!deep) { console.log('  没找到那一行，①后半没摆出来') } else {
    await d.clickAt(deep.cx, deep.cy); await wait(1500)
    const t1 = await pageText(d)
    console.log('  设置页顶上第一条:', line(t1, /[^\n]*还没配模型[^\n]*/))
    await d.shot('p70-bnew-1b-settings-light.png')
    const inputs = await d.eval(`Array.from(document.querySelectorAll('input, select, textarea')).map((e, i) => ({ i, type: e.type, ph: e.placeholder || '', val: String(e.value).slice(0,60) }))`)
    const addr = inputs.find((x) => /11434|地址|http/.test(x.ph) && x.type === 'text')
    console.log('  地址格:', JSON.stringify(addr))
    if (addr) {
      await d.click('input', { idx: addr.i })
      await d.key('a', ['meta'], { commands: ['selectAll'] })
      await d.insert('http://127.0.0.1:' + llmPort + '/v1')
      await wait(400)
      const btn = await d.findText('button', '测一下')
      if (btn) { await d.clickAt(btn.cx, btn.cy); await wait(3000) }
      const t2 = await pageText(d)
      console.log('  测一下结果:', line(t2, /连上了[^\n]{0,80}/))
      console.log('  含「模型名还没填」:', t2.includes('模型名还没填'))
      await d.shot('p70-bnew-1c-tested-light.png')
      await clickExact(d, '保存', 0, 4).catch((e) => console.log('  保存没点到:', e.message))
      await wait(2500)
      const t3 = await pageText(d)
      console.log('  保存之后「还没配模型」还在吗（该 false）:', t3.includes('还没配模型'))
      await d.shot('p70-bnew-1d-saved-light.png')
    }
  }

  console.log('=== ②③ 新建 → 标题 → 「计划」+ 打三段 → 空库图例 / 空托盘 ===')
  await d.key('Escape'); await wait(300)
  await d.key('k', ['meta']); await wait(1000)
  await d.insert('新建笔记'); await wait(900)
  await clickExact(d, '新建笔记', 0, 8).catch((e) => console.log('  新建没点到:', e.message))
  await wait(3000)
  // ───────── P66 B：P64 问题 #2「空库第一篇 d.noteId() 回 null，没核清楚是量具还是产品」─────────
  // 三头各读一次，**分得开才叫核清楚**：
  //   ① 量具默认那一格（`d.noteId()` 的默认 user 是 'terrence'）
  //   ② 这个窗口真正的身份那一格
  //   ③ 整个 localStorage 里所有 `memoket-note-active:*`（**「选不到 ≠ 没有」**）
  //   ④ 后端真有哪几篇（**「编辑器里没有 ≠ 库里没有」的镜像**）
  console.log('=== P66 B：空库第一篇的 active-note 那一格 ===')
  console.log('  ① d.noteId()（默认=本窗口身份，P70 B 改的）:', await d.noteId())
  console.log('  ② d.noteId(本窗口身份):', await d.noteId('p70-newbie'))
  console.log('  ③ api.getUser() =', await d.eval(`(new URLSearchParams(location.search).get('user') || localStorage.getItem('memoket.user'))`))
  console.log('  ④ localStorage 里所有 active 那一格:', JSON.stringify(await d.eval(`
    Object.fromEntries(Object.keys(localStorage).filter((k) => k.startsWith('memoket-note-active'))
      .map((k) => [k, localStorage.getItem(k)]))`)))
  console.log('  ⑤ 后端真有哪几篇:', JSON.stringify(await d.eval(`(async () => {
    const u = new URLSearchParams(location.search).get('user') || localStorage.getItem('memoket.user')
    const r = await fetch('/api/notes', { headers: { 'X-User-Id': u } })
    const j = await r.json()
    return (Array.isArray(j) ? j : (j.items || j.notes || [])).map((n) => n.id)
  })()`)))
  await d.focusEditor()
  await d.insert('# P58 走查（新用户 · 可删）'); await d.key('Enter'); await d.key('Enter')
  await d.insert('众筹页面那一版文案是 3 月 12 号上线的，当天点击 12700。'); await d.key('Enter'); await d.key('Enter')
  await wait(4000)
  console.log('  正文字数:', (await docText(d) ?? '').length)
  console.log('  右栏页签:', JSON.stringify(await d.texts('.pane-tab', 12)))
  const intent = await d.eval(`(() => {
    const el = document.querySelector('.doc-intent'); if (!el) return { found: false }
    return { found: true, vals: Array.from(el.querySelectorAll('input.doc-intent-input')).map((i) => i.value),
             prefill: !!el.querySelector('.doc-intent-src') }
  })()`)
  console.log('  意图行:', JSON.stringify(intent))
  await d.shot('p70-bnew-2-plan-light.png')
  await clickExact(d, '记忆', 0, 6).catch(() => {})
  await wait(2500)
  const pane = await d.eval(`(() => { const t = document.querySelectorAll('.pane-tab')[0]; return t ? t.parentElement.parentElement.innerText.slice(0, 2000) : null })()`)
  console.log('--- 右栏「记忆」（空库）---')
  console.log(pane)
  console.log('  P32 #3 空库图例收成一句:', (pane || '').includes('页边圆点和这份记忆是怎么来的'))
  console.log('  P35 #8 空托盘收成一句:', (pane || '').includes('摊上来的材料有什么用、怎么摊'))
  await d.shot('p70-bnew-3-memory-light.png')

  console.log('=== ⑧ 屏幕活动：知情选择五条（P21 #1 / P32 #4）===')
  await openJourney(d)
  await toTop(d)
  const t4 = await pageText(d)
  console.log('  知情屏在吗:', await d.count('.journey-consent'))
  console.log('--- 那一屏 ---')
  console.log(t4.slice(0, 1600))
  console.log('  「留多久」那一行（从后端读的数）:', line(t4, /描述留[^\n]*/))
  console.log('  两个钮:', JSON.stringify(await d.eval(`Array.from(document.querySelectorAll('.journey-consent button')).map((e) => (e.textContent||'').trim())`)))
  console.log('  facts:', JSON.stringify(await journeyFacts(d)))
  await d.shot('p70-bnew-4-consent-light.png')

  console.log('=== ⑨ ⌘K 全部去处 ===')
  await d.key('Escape'); await wait(300)
  await d.key('k', ['meta']); await wait(1200)
  const dests = await d.texts('[role="option"], [class*="palette"] [class*="item"], .palette-item', 60)
  console.log('  项数:', dests.length, JSON.stringify(dests))
  await d.insert('屏幕'); await wait(1200)
  console.log('  搜「屏幕」:', JSON.stringify(await d.texts('[role="option"], [class*="palette"] [class*="item"], .palette-item', 20)))
  await d.shot('p70-bnew-5-cmdk-light.png')
  await d.key('Escape'); await wait(600)

  console.log('=== ⑪ 深色 + 900px ===')
  await d.setTheme('dark'); await wait(1200)
  const bg = await d.eval(`getComputedStyle(document.body).backgroundColor`)
  const white = await d.eval(`(() => {
    let n = 0
    for (const e of document.querySelectorAll('*')) {
      const c = getComputedStyle(e).backgroundColor
      const m = c.match(/rgba?\\((\\d+), ?(\\d+), ?(\\d+)(?:, ?([\\d.]+))?\\)/)
      if (!m) continue
      const [r, g, b, a] = [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]]
      if (a > 0.9 && r > 235 && g > 235 && b > 235) { const q = e.getBoundingClientRect(); if (q.width > 40 && q.height > 20) n++ }
    }
    return n
  })()`)
  console.log('  深色 body:', bg, ' 近白大块:', white)
  await d.shot('p70-bnew-6-dark.png')
  await d.resize(900, 900); await wait(800)
  const over = await d.eval(`(() => { let n = 0; for (const e of document.querySelectorAll('*')) { const r = e.getBoundingClientRect(); if (r.width > 0 && r.right > innerWidth + 1) n++ } return n })()`)
  console.log('  900px 横向溢出:', over,
              ' 横向滚得动吗:', await d.eval(`document.documentElement.scrollWidth > document.documentElement.clientWidth + 1`))
  const fb = await d.eval(`(() => {
    const f = document.querySelector('.floating-buttons'); const e = document.querySelector('.cm-editor')
    if (!f || !e) return null
    return { fbBottom: Math.round(f.getBoundingClientRect().bottom), edTop: Math.round(e.getBoundingClientRect().top) }
  })()`)
  console.log('  fbBottom vs edTop（P41 #4）:', JSON.stringify(fb))
  await d.setTheme('light'); await wait(500)
  await d.shot('p70-bnew-7-900-light.png')
  await d.resize(0)
}
