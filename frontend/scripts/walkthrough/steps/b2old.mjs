// P58 · 第九次全流程走查（老用户）第二趟：⑥⑦⑩（前半）
//   ⑥ 智能续写 → 轮次卡片 → **读库**（P45 #1 / P44 问题 #1 的回归）
//   ⑦ 导回到 Obsidian（浅走）
//   ⑩ 改动层：润色生一层 → 右栏「改动」页签 → 库里真有那一行（关掉重开在下一趟）
import { clickExact } from './clickexact.mjs'
import { selectLineAndRightClick } from './ctxmenu52.mjs'
import { docText, pageText, toasts, until, wait } from './lib.mjs'

async function dbContent(d, id) {
  return d.eval(`(async () => {
    const u = localStorage.getItem('memoket.user') || 'terrence'
    const r = await fetch('/api/notes/${id}', { headers: { 'X-User-Id': u } })
    const j = await r.json()
    return { len: (j.content || '').length, json: /\\{"text":|"reason": "假模型"/.test(j.content || '') }
  })()`)
}
async function layers(d, id) {
  return d.eval(`(async () => {
    const u = localStorage.getItem('memoket.user') || 'terrence'
    const r = await fetch('/api/notes/${id}/change-layers', { headers: { 'X-User-Id': u } })
    return JSON.stringify(await r.json()).slice(0, 400)
  })()`)
}

export default async function (d, [noteId]) {
  await d.setTheme('light'); await wait(400)
  await d.openNoteById(noteId, 'P58 走查')
  await wait(2000)
  console.log('开着的是:', await d.noteId())

  console.log('=== ⑥ 智能续写 → 轮次卡片 → 读库 ===')
  const before = await docText(d)
  console.log('  跑之前：编辑器', before.length, ' 库', JSON.stringify(await dbContent(d, noteId)))
  await clickExact(d, '智能续写', 0, 10)
  await wait(2000)
  // **判「跑完了」不能用「完成」两个字**：这一页上本来就有「完成标准」，
  // 第一轮还没开始就命中 —— 上一趟「+0 字 / 1 轮」的读数有一半是这么来的。
  // 认收工那一行自己的措辞（`· N 轮 ·`），它只在 RUN_FINISHED 之后才出现。
  await until(async () => {
    const t = await pageText(d)
    return /· \d+ 轮 ·/.test(t) ? t : null
  }, 300000, 2000)
  await wait(3000)
  // **P66：读之前先把 `<details>` 摊开**。P62 把这条收进了 `cdp.mjs`（`d.expandDetails()`）
  // 和 `rounds60.mjs`，**这一份没跟上** —— 于是这一格在 P58 / P60 / P62 三批里
  // 照旧读回 `[]`（「⚑ 判据那几行」「收工那行」全是空的）。
  // 那不是「这几句没了」，是**没摊开**：收着的 `<details>` 里的字 `innerText` 读不到。
  console.log('  摊开了', await d.expandDetails(), '个折叠块')
  await wait(600)
  const after = await docText(d)
  const right = await d.eval(`(() => { const el = document.querySelector('.pane-body, [class*="pane"] [class*="body"]'); return el ? el.innerText : document.body.innerText })()`)
  const n = (s) => right.split(s).length - 1
  console.log('  跑完：编辑器', after.length, '（+', after.length - before.length, '）')
  console.log('  库:', JSON.stringify(await dbContent(d, noteId)), '← len 该跟编辑器一样、json 该是 false')
  console.log('  「照它改的」', n('照它改的'), '次；「判词就是下面」', n('判词就是下面'), '次；空括号「（）」', n('（）'), '次（该 0）')
  const t = await pageText(d)
  console.log('  「这一次不再往下写了」:', t.includes('这一次不再往下写了'), ' 「照常打分」:', t.includes('照常打分'))
  console.log('  收工那行:', JSON.stringify((t.match(/[^\n]*(正文没有改动|落进正文|收工)[^\n]*/g) || []).slice(0, 3)))
  console.log('  ⚑ 判据那几行:', JSON.stringify((right.match(/[^\n]*(代码判据|判据)[^\n]*/g) || []).slice(0, 8)))
  console.log('  「照常打分」出现:', n('照常打分'), '次；「没再花模型调用去打分」出现:', n('没再花模型调用去打分'), '次')
  console.log('  「当提醒看」出现:', n('当提醒看'), '次')
  console.log('  垃圾尾巴那条:', JSON.stringify((right.match(/[^\n]*硬贴了一句[^\n]*/) || [])[0]))
  console.log('  残骸编号那条:', JSON.stringify((right.match(/[^\n]*查不到[^\n]*/) || [])[0]))
  console.log('  正文里还有「做爰片」吗（该 false）:', (after || '').includes('做爰片'))
  console.log('  正文里还有「[terrence-8F6]」吗（该 false）:', (after || '').includes('terrence-8F6'))
  await d.shot('p70-b2d-old-rounds-light.png')

  console.log('=== ⑩ 改动层：润色生一层 ===')
  const lines = await d.eval(`Array.from(document.querySelectorAll('.cm-content .cm-line')).map((l, i) => [i, (l.textContent||'').slice(0, 18)])`)
  const idx = (lines.find(([, s]) => s.includes('预热名单')) || lines.find(([i]) => i === 4) || [4])[0]
  console.log('  在第', idx, '行上右键「润色」')
  const doc0 = await docText(d)
  await selectLineAndRightClick(d, idx)
  await clickExact(d, '润色', 0, 10)
  await until(async () => (await docText(d)) !== doc0, 120000, 800)
  await wait(3000)
  const t2 = await pageText(d)
  console.log('  改动条:', JSON.stringify((t2.match(/[^\n]*改了 \d+ 处[^\n]*/) || [])[0]))
  console.log('  右栏页签:', JSON.stringify(await d.texts('.pane-tab', 12)))
  console.log('  库里的层:', await layers(d, noteId))
  await d.shot('p70-b2d-old-layer-light.png')

  console.log('=== ⑦ 导回到 Obsidian ===')
  await d.key('Escape'); await wait(300)
  await d.key('k', ['meta']); await wait(1000)
  await d.insert('导回'); await wait(1000)
  await clickExact(d, '导回到 Obsidian / Notion / 飞书…', 0, 10).catch((e) => console.log('  ⌘K 里没点到:', e.message))
  await wait(2500)
  const t3 = await pageText(d)
  console.log('  面板在吗:', t3.includes('Obsidian'))
  for (const s of ['vault', '树的层级变成文件夹', '克隆写成 .link.txt', '_assets/']) {
    console.log(`  逐字「${s}」:`, t3.includes(s))
  }
  console.log('  「导回 N 篇」:', JSON.stringify((t3.match(/导回 \d+ 篇/) || [])[0]))
  await d.shot('p70-b2d-old-export-light.png')
  console.log('  toast:', JSON.stringify(await toasts(d)))
}
