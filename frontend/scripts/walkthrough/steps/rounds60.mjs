// P60 走查 ⑥：轮次卡片那一段 —— **把 `details` 全摊开再读**。
//
// 上一趟（`rounds58.mjs`）拿「含『Agent 运行』的最后一个容器」的 `innerText`，
// 读回来只有表头一行「Agent 运行」：卡片在 `<details>` 里，收着的时候
// `innerText` **读不到里面的字**。「选不到 ≠ 没有」的第 N 个形状：
// 这一次不是选择器错，是**读法**错。
import { docText, pageText, until, wait } from './lib.mjs'
import { clickExact } from './clickexact.mjs'
import { USER } from '../whoami.mjs'

export default async function (d, [noteId, shotName]) {
  await d.setTheme('light'); await wait(400)
  await d.openNoteById(noteId, 'P58 走查')
  await wait(2000)
  const before = await docText(d)
  console.log('开着的是:', await d.noteId(), ' 跑之前 编辑器:', (before ?? '').length)

  await clickExact(d, '智能续写', 0, 10)
  await wait(2000)
  await until(async () => (/· \d+ 轮 ·/.test(await pageText(d)) ? true : null), 300000, 2000)
  await wait(4000)
  const after = await docText(d)
  console.log('跑完 编辑器:', (after ?? '').length, '（+', (after ?? '').length - (before ?? '').length, '）')

  // 把所有 details 摊开（含 Agent 面板里的每一张卡）
  const opened = await d.eval(`(() => {
    let n = 0
    for (const e of document.querySelectorAll('details')) { if (!e.open) { e.open = true; n++ } }
    return n
  })()`)
  console.log('摊开了', opened, '个折叠块')
  await wait(800)

  const agent = await d.eval(`(() => {
    const all = Array.from(document.querySelectorAll('div, section, aside'))
      .filter((e) => (e.textContent || '').includes('Agent 运行'))
    const el = all[all.length - 1]
    return el ? el.innerText : null
  })()`)
  console.log('--- Agent 运行（整段，details 已摊开）---')
  console.log(agent)

  const t = await pageText(d)
  const a = (agent || '') + '\n' + t
  const n = (s) => a.split(s).length - 1
  console.log('--- 收工那一行 ---', JSON.stringify((t.match(/[^\n]*· \d+ 轮 ·[^\n]*/g) || []).slice(0, 3)))
  console.log('判定（P58 #1 那三句，四档互斥）：')
  for (const s of ['当提醒看', '照常打分', '这一轮没再花模型调用去打分', '这一轮没打分',
                   '不再拦、照常打分', '判词就是下面']) {
    console.log(`  「${s}」:`, n(s), '次')
  }
  console.log('  空括号「（）」:', n('（）'), '次（该 0）')
  console.log('  正文里还有「做爰片」吗（该 false）:', (after || '').includes('做爰片'))
  console.log('  正文里还有「terrence-8F6」吗（该 false）:', (after || '').includes('terrence-8F6'))
  console.log('  库:', await d.eval(`(async () => {
    const u = ${USER}
    const r = await fetch('/api/notes/${noteId}', { headers: { 'X-User-Id': u } })
    const j = await r.json()
    return JSON.stringify({ len: (j.content||'').length, json: /\\{"scores"|\\{"spine"/.test(j.content||'') })
  })()`))
  await d.shot(shotName)
}
