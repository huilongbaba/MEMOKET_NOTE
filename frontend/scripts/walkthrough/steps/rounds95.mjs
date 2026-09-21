// P95 A：**右栏摆的那叠轮次卡，是不是这一篇的**——在真打好的壳上拍前后对比。
//
// P93 在这儿实拍到一处产品缺陷（它自己的问题 #1）：
//   > 在 A 篇跑完 2 轮续写后 ⌘K 新建一篇**空**笔记（`0 字`、正文空），
//   > 右栏「计划」写着 **`计划 2`**，底下摆着 **A 篇那两轮的执行记录**，
//   > 连「本轮写出的正文（72 字）」都在。
//
// P93 同时写着**它那条「不许留白」的通用闸抓不到这个**：那一格「有字」，
// 只不过字是别人的。⇒ 这一步就是「抓得到」的那一半里**在壳上**的那一块。
//
// 三档，一档一读（**它只读不判**，判在走查表和 `components/__tests__/p95.test.tsx`）：
//   ① A 篇跑完 2 轮：「计划」该有角标、底下该有「第 N 轮」；
//   ② ⌘K 新建一篇**空**笔记 B：「计划」**不该有数字**、底下**不该有任何「第 N 轮」**
//      ——**这一档就是 P93 那张截图**；
//   ③ **切回 A**：卡该原样还在。**这一档是那行 `useEffect(…, [current?.id])` 的代价**
//      ——照那条路改的话，这儿会是空的（P93 判「不改」正是因为这个）。
//
//   node cdp.mjs <port> steps/rounds95.mjs <截图名前缀> <A 篇的 note id> [A 篇标题头几个字]
import { clickExact } from './clickexact.mjs'
import { docText, pageText, until, wait } from './lib.mjs'

/** 「计划」那一格这一刻的样子：页签上逐字、底下 `.right-pane-body` 逐字。
 *  **点进去再读**——`<details>` 收着 / 页签没选中时 `innerText` 读不到里面的字
 *  （P60 那一课）。 */
async function readPlan(d, tag, shotPrefix) {
  const tabs = await d.eval(`Array.from(document.querySelectorAll('.pane-tab')).map((e, i) => {
    const r = e.getBoundingClientRect()
    return { i, t: (e.textContent||'').replace(/\\s+/g,' ').trim(), cx: r.x + r.width/2, cy: r.y + r.height/2 }
  })`)
  console.log(`  [${tag}] 条上几格:`, JSON.stringify(tabs.map((x) => x.t)))
  const plan = tabs.find((x) => x.t.startsWith('计划'))
  if (!plan) throw new Error('「计划」那一格不在条上——**选不到 ≠ 没有**，先去读 App.tsx 的 tabs')
  await d.clickAt(plan.cx, plan.cy)
  await wait(800)
  const opened = await d.eval(`(() => { let n = 0
    for (const e of document.querySelectorAll('.right-pane-body details')) { if (!e.open) { e.open = true; n++ } }
    return n })()`)
  const body = await d.eval(`(document.querySelector('.right-pane-body')?.innerText ?? null)`)
  if (body === null) throw new Error('`.right-pane-body` 整个选不到——右栏没渲染出来')
  const flat = body.replace(/\s+/g, ' ').trim()
  // 「第 N 轮」是 `AgentActivity` 里那张卡的抬头（`第 ${r.round} 轮`）——拿它当靶子，
  // **不拿「Agent 运行」那个表头**：表头在不在跟卡在不在是两件事。
  const rounds = [...new Set((flat.match(/第 \d+ 轮/g) || []))]
  console.log(`  [${tag}] 「计划」页签逐字: ${JSON.stringify(plan.t)}`
    + `  角标里有数字吗: ${/\d/.test(plan.t)}  （摊开了 ${opened} 个折叠块）`)
  console.log(`  [${tag}] 底下有几种「第 N 轮」: ${rounds.length}`, JSON.stringify(rounds))
  console.log(`  [${tag}] 「本轮写出的正文」出现几次:`, flat.split('本轮写出的正文').length - 1)
  console.log(`  [${tag}] 底下头 200 字:`, JSON.stringify(flat.slice(0, 200)))
  await d.shot(`${shotPrefix}-${tag}-计划.png`)
  return { tab: plan.t, rounds, body: flat }
}

export default async function (d, [shotPrefix, noteId, titleHead]) {
  const prefix = shotPrefix || 'p95-rounds'
  if (!noteId) throw new Error('没给 A 篇的 note id——**跳过就是跳过**，不拿别的顶')
  await d.setTheme('light'); await wait(400)

  console.log('=== ① A 篇跑一趟智能续写 ===')
  await d.openNoteById(noteId, titleHead ?? '')
  await wait(2000)
  const nowId = await d.noteId()
  console.log('  开着的是:', nowId, '（该是', noteId, '）')
  const before = await docText(d)
  console.log('  跑之前 正文字数:', (before ?? '').length)
  await clickExact(d, '智能续写', 0, 10)
  await wait(2000)
  const t0 = Date.now()
  const done = await until(async () => (/· \d+ 轮 ·/.test(await pageText(d)) ? true : null), 300000, 2000)
  console.log(`  收工那行等到了吗: ${done === true}（等了 ${Math.round((Date.now() - t0) / 1000)} 秒；`
    + 'null = 干等超时，不是「跑完了」）')
  await wait(4000)
  const after = await docText(d)
  console.log('  跑完 正文字数:', (after ?? '').length)
  console.log('  收工那一行:', JSON.stringify((await pageText(d)).match(/[^\n]*· \d+ 轮 ·[^\n]*/g) || []))
  const a1 = await readPlan(d, 'A跑完', prefix)

  console.log('=== ② ⌘K 新建一篇**空**笔记（P93 实拍「计划 2」那一屏）===')
  await d.key('Escape'); await wait(300)
  await d.key('k', ['meta']); await wait(1000)
  await d.insert('新建笔记'); await wait(900)
  await clickExact(d, '新建笔记', 0, 8)
  await wait(3000)
  const bId = await d.noteId()
  console.log('  新建出来的 note id:', bId, '（**跟 A 不是同一篇**:', bId !== nowId, '）')
  console.log('  正文（该是空的）:', JSON.stringify(await d.cmText()))
  const b = await readPlan(d, '新建空笔记', prefix)

  console.log('=== ③ 切回 A（**那行 useEffect 的代价在这一档上**）===')
  await d.openNoteById(noteId, titleHead ?? '')
  await wait(2500)
  console.log('  开着的是:', await d.noteId())
  const a2 = await readPlan(d, 'A切回来', prefix)

  console.log('=== 三档并排 ===')
  console.log('  ', JSON.stringify({
    A跑完: { 页签: a1.tab, 几种轮次卡: a1.rounds.length },
    新建空笔记: { 页签: b.tab, 几种轮次卡: b.rounds.length, 页签里有数字吗: /\d/.test(b.tab) },
    A切回来: { 页签: a2.tab, 几种轮次卡: a2.rounds.length },
  }))
}
