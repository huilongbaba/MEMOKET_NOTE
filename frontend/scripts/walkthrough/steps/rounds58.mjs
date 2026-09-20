// P58 走查 ⑥ 的正主：**把每一张轮次卡片的整段文字打出来**。
//
// 上一趟量错在两处，都是「选不到 ≠ 没有」的老形状：
//   · `right` 拿的是 `.pane-body`，而轮次卡片在**另一个**面板里 → 判据那几行一律读成 []；
//   · 收工那一行在卡片头上，不在 `pageText` 的开头。
// 这一版直接找含「Agent 运行」的那个容器，整段 innerText 打出来，再逐条对。
import { docText, pageText, until, wait } from './lib.mjs'
import { clickExact } from './clickexact.mjs'

export default async function (d, [noteId, shotName]) {
  await d.setTheme('light'); await wait(400)
  await d.openNoteById(noteId, 'P58 走查')
  await wait(2000)
  console.log('开着的是:', await d.noteId())
  const before = await docText(d)
  console.log('跑之前 编辑器:', (before ?? '').length)

  await clickExact(d, '智能续写', 0, 10)
  await wait(2000)
  await until(async () => (/· \d+ 轮 ·/.test(await pageText(d)) ? true : null), 300000, 2000)
  await wait(4000)

  const after = await docText(d)
  console.log('跑完 编辑器:', (after ?? '').length, '（+', (after ?? '').length - (before ?? '').length, '）')

  const agent = await d.eval(`(() => {
    const all = Array.from(document.querySelectorAll('div, section, aside'))
      .filter((e) => (e.textContent || '').includes('Agent 运行'))
    const el = all[all.length - 1]
    return el ? el.innerText : null
  })()`)
  console.log('--- Agent 运行（整段）---')
  console.log(agent)
  console.log('--- 收工那一行 ---')
  const t = await pageText(d)
  console.log(JSON.stringify((t.match(/[^\n]*· \d+ 轮 ·[^\n]*/g) || []).slice(0, 3)))

  const a = agent || ''
  const n = (s) => a.split(s).length - 1
  console.log('判定：')
  console.log('  「当提醒看」（advisory 那一句）:', n('当提醒看'), '次')
  console.log('  「照常打分」:', n('照常打分'), '次')
  console.log('  「这一轮没再花模型调用去打分」:', n('这一轮没再花模型调用去打分'), '次')
  console.log('  「这一轮没打分」（P33 折叠那句）:', n('这一轮没打分'), '次')
  console.log('  空括号「（）」:', n('（）'), '次（该 0）')
  console.log('  正文里还有「做爰片」吗（该 false）:', (after || '').includes('做爰片'))
  console.log('  正文里还有「terrence-8F6」吗:', (after || '').includes('terrence-8F6'))
  // 读库（P45 #1 / P44 问题 #1 的回归）：库里那份得跟编辑器逐字一样，而且不是 JSON
  console.log('  库:', await d.eval(`(async () => {
    const u = localStorage.getItem('memoket.user') || 'terrence'
    const r = await fetch('/api/notes/${noteId}', { headers: { 'X-User-Id': u } })
    const j = await r.json()
    return JSON.stringify({ len: (j.content||'').length, json: /\\{"scores"|\\{"spine"/.test(j.content||'') })
  })()`))
  await d.shot(shotName)
}
