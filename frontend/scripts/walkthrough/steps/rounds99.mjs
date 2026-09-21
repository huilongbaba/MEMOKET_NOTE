// P99 B：**轮次卡到底丢的是什么**——三种情形各量一遍（**先量再判该不该落库**）。
//
// P95 / P97 连着两批留着同一句话：
//   > 切走那几秒的 harness 事件照旧丢、轮次卡**仍不落库**（只活在内存里）。
//
// 这一步**只读不判**（判在台账 §B）。它把用户真会撞上的三种情形拍成同一张表：
//   ① **跑着 harness 切走再切回**（`away`）：`guarded` 那层把切走那几秒的事件全扔了；
//   ② **关掉重开**（`away` 末尾那一次 reload，外加主走查第 ⑩ 步那趟真的重开）；
//   ③ **崩溃**（`crash-mark` + 外头 `kill -9` + `crash-read`）：连 `beforeunload` /
//      `flush-save` 那两条路都不跑——跟 ② 差的正是那两条路存的东西。
//
// ⚠️ **判据宁可窄**：每一档读回来的是同一个形状（`snap()`），**差别只在时机**。
//    读的几样：右栏条上那几格逐字 / 底下有几种「第 N 轮」/「本轮写出的正文」出现几次 /
//    编辑器里的字数 / **库里那一篇的字数**（`GET /api/notes/<id>`，带 `X-User-Id` 头）。
//    「库里 `harness_rounds` 有几行」**不在这儿读**——没有那条 API，
//    在外头拿 sqlite 直接数（**「编辑器里没有 ≠ 库里没有」**，两头都得摆出来）。
//
// ⚠️ **`编辑器字数` 这一格只能当参考，别拿它下判**（P99 B 实拍栽过一次）：
//    `docText()` 数的是 `.cm-content .cm-line`，而 CodeMirror **只渲染视口里那几行**。
//    同一篇 387 字的笔记，刚打开读回 **300**、⌘End 之后读回 **246**，
//    而单篇 API 一直是 387、打一个字之后 388（**库里那一截一直都在**）。
//    ⇒ 「编辑器比库里短」在长笔记上是**量具够不着**，不是产品丢了东西。
//    所以这儿**同时读状态栏那一格**（它来自 React 的 `content`，跟渲染无关），
//    判正文有没有丢**一律看库里那个数**。
//
//   node cdp.mjs <port> steps/rounds99.mjs <档> <截图名前缀> <note id> [标题头几个字] [切走停留毫秒]
//   档 = away | crash-mark | crash-read
import { clickExact } from './clickexact.mjs'
import { docText, pageText, until, wait } from './lib.mjs'
import { USER } from '../whoami.mjs'

/** 这一刻的四样。**点进「计划」再读**——`<details>` 收着 / 页签没选中时 `innerText` 读不到（P60）。 */
async function snap(d, tag, shotPrefix, noteId) {
  const tabs = await d.eval(`Array.from(document.querySelectorAll('.pane-tab')).map((e) => {
    const r = e.getBoundingClientRect()
    return { t: (e.textContent||'').replace(/\\s+/g,' ').trim(), cx: r.x + r.width/2, cy: r.y + r.height/2 }
  })`)
  const plan = tabs.find((x) => x.t.startsWith('计划'))
  let rounds = []
  let wrote = 0
  let scored = 0
  if (plan) {
    await d.clickAt(plan.cx, plan.cy)
    await wait(700)
    await d.eval(`(() => { for (const e of document.querySelectorAll('.right-pane-body details')) e.open = true })()`)
    const body = await d.eval(`(document.querySelector('.right-pane-body')?.innerText ?? null)`)
    if (body === null) throw new Error('`.right-pane-body` 整个选不到——右栏没渲染出来（**选不到 ≠ 没有**，先去看 App.tsx）')
    const flat = body.replace(/\s+/g, ' ').trim()
    rounds = [...new Set(flat.match(/第 \d+ 轮/g) || [])]
    // **整份 body 上数**，不是头 120 字：卡上那几样明细只活在内存里，
    // 「切走那几秒丢的是什么」全看这两个数（P95 / P97 留的那半句）。
    // ⚠️ 这两个串**先去 AgentActivity.tsx 里核过在不在**：写一个产品里根本没有的串，
    //    这一格会**永远是 0**，读起来跟「真的丢了」一模一样（判据比产品窄的又一张脸）。
    wrote = flat.split('本轮写出的正文').length - 1
    scored = flat.split('修订 ').length - 1
  }
  const doc = (await docText(d)) ?? ''
  const status = await d.eval(`(document.querySelector('.status-bar')?.innerText ?? '').replace(/\\s+/g,' ').trim()`)
  // **库里那一篇**：`GET /api/notes/<id>`。**「编辑器里有 ≠ 库里有」**——这一条是承重的。
  const db = await d.eval(`(async () => {
    const u = ${USER}
    const r = await fetch('/api/notes/' + ${JSON.stringify(noteId)}, { headers: { 'X-User-Id': u } })
    if (!r.ok) return { status: r.status, len: null }
    const j = await r.json()
    return { status: r.status, len: (j.content ?? '').length }
  })()`)
  const out = {
    档: tag,
    条上几格: tabs.map((x) => x.t),
    几种轮次卡: rounds.length,
    轮次卡: rounds,
    本轮写出的正文出现几次: wrote,
    '「修订 N 处」出现几次': scored,
    '编辑器字数（只作参考·见抬头）': doc.length,
    状态栏: (status.match(/\d[\d,]*\s*字/) || [''])[0],
    库里字数: db.len,
    库里回的状态: db.status,
  }
  console.log(`  [${tag}]`, JSON.stringify(out))
  await d.shot(`${shotPrefix}-${tag}.png`)
  return out
}

/** 切到另一篇（⌘K 打开「屏幕活动」那种虚拟页不算换篇——得是真的另一篇）。 */
async function switchAway(d) {
  await d.key('Escape'); await wait(300)
  await d.eval(`window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'app:journey' }))`)
  await wait(1500)
  return d.eval(`(document.querySelector('.note-tab.active')?.textContent ?? '').trim()`)
}

export default async function (d, [phase, shotPrefix, noteId, titleHead, awayMsRaw]) {
  const prefix = shotPrefix || 'p99-rounds'
  const awayMs = Number(awayMsRaw || 12000)
  if (!phase) throw new Error('没给档（away | crash-mark | crash-read）——**跳过就是跳过**')
  if (!noteId) throw new Error('没给 note id——**不拿上一趟那篇顶上去**（P80 问题 #7 那条坑）')
  await d.setTheme('light'); await wait(400)
  await d.openNoteById(noteId, titleHead ?? '')
  await wait(2000)
  console.log('  开着的是:', await d.noteId(), '（该是', noteId, '）')

  if (phase === 'crash-read') {
    console.log('=== ③ 崩溃之后重开：还剩什么 ===')
    await snap(d, '崩溃重开', prefix, noteId)
    const txt = await pageText(d)
    console.log('  正文里还有那个记号吗:', txt.includes('P99崩溃记号'))
    return
  }

  const base = await snap(d, '跑之前', prefix, noteId)

  console.log('=== 点「智能续写」 ===')
  await clickExact(d, '智能续写', 0, 10)
  const t0 = Date.now()
  const first = await until(async () => (/第 1 轮/.test(await pageText(d)) ? true : null), 120000, 1000)
  console.log(`  第一张卡等到了吗: ${first === true}（等了 ${Math.round((Date.now() - t0) / 1000)} 秒；`
    + 'null = 干等超时，**不是「跑完了」**）')
  const running = await snap(d, '跑着-第一张卡', prefix, noteId)

  if (phase === 'crash-mark') {
    console.log('=== ② 崩溃：等它跑完，再往正文里打一个记号，**立刻**交给外头 kill -9 ===')
    const done = await until(async () => (/· \d+ 轮 ·/.test(await pageText(d)) ? true : null), 300000, 2000)
    console.log(`  收工那行等到了吗: ${done === true}（等了 ${Math.round((Date.now() - t0) / 1000)} 秒）`)
    await wait(3000)
    const fin = await snap(d, '跑完', prefix, noteId)
    console.log('  收工那一行:', JSON.stringify((await pageText(d)).match(/[^\n]*· \d+ 轮 ·[^\n]*/g) || []))
    await d.focusEditor()
    await d.key('End', ['meta'])
    await d.insert('\nP99崩溃记号')
    await wait(200)
    const after = ((await docText(d)) ?? '')
    console.log('  打完记号 编辑器字数:', after.length, '（比跑完多', after.length - fin['编辑器字数（只作参考·见抬头）'], '）')
    console.log('  打完记号 正文里有记号吗:', after.includes('P99崩溃记号'))
    await d.shot(`${prefix}-崩溃前.png`)
    console.log('  → **这一刻交给外头 kill -9**（`beforeunload` / `flush-save` 一条都不跑）')
    return
  }

  console.log(`=== ① 跑着切走 ${awayMs} 毫秒再切回来 ===`)
  const tabName = await switchAway(d)
  console.log('  切到了:', JSON.stringify(tabName))
  await wait(awayMs)
  await d.openNoteById(noteId, titleHead ?? '')
  await wait(2500)
  const back = await snap(d, '切回来', prefix, noteId)
  console.log('  切走前 / 切回来 各几种轮次卡:', running.几种轮次卡, '→', back.几种轮次卡)

  const done = await until(async () => (/· \d+ 轮 ·/.test(await pageText(d)) ? true : null), 300000, 2000)
  console.log(`  收工那行等到了吗: ${done === true}（等了 ${Math.round((Date.now() - t0) / 1000)} 秒）`)
  await wait(4000)
  const fin = await snap(d, '跑完', prefix, noteId)
  const line = (await pageText(d)).match(/[^\n]*· \d+ 轮 ·[^\n]*/g) || []
  console.log('  收工那一行:', JSON.stringify(line))
  console.log('  ⚠️ 收工那行里的「N 轮」数的是**留下来的**那几张卡（`roundsByNoteRef`），'
    + '不是后端真跑了几轮 —— 后端那个数在外头从 `harness_rounds` 数')

  console.log('=== ② 关掉重开（renderer reload：内存里那份从此不存在）===')
  await d.eval('location.reload()')
  await wait(9000)
  const up = await until(async () => (await d.exists('.cm-content')) || null, 60000, 1000)
  console.log('  重开之后编辑器起来了吗:', up === true)
  await wait(2000)
  const nowId = await d.noteId()
  console.log('  重开之后开着的是:', nowId, '（该还是', noteId, '）')
  if (nowId !== noteId) await d.openNoteById(noteId, titleHead ?? '')
  await wait(2000)
  const re = await snap(d, '重开之后', prefix, noteId)

  console.log('=== 四档并排 ===')
  console.log('  ', JSON.stringify({
    跑之前: { 卡: base.几种轮次卡, 写出的正文: base.本轮写出的正文出现几次, 修订处: base['「修订 N 处」出现几次'], 状态栏: base.状态栏, 库里: base.库里字数 },
    跑着: { 卡: running.几种轮次卡, 写出的正文: running.本轮写出的正文出现几次, 修订处: running['「修订 N 处」出现几次'], 状态栏: running.状态栏, 库里: running.库里字数 },
    切回来: { 卡: back.几种轮次卡, 写出的正文: back.本轮写出的正文出现几次, 修订处: back['「修订 N 处」出现几次'], 状态栏: back.状态栏, 库里: back.库里字数 },
    跑完: { 卡: fin.几种轮次卡, 写出的正文: fin.本轮写出的正文出现几次, 修订处: fin['「修订 N 处」出现几次'], 状态栏: fin.状态栏, 库里: fin.库里字数 },
    重开之后: { 卡: re.几种轮次卡, 写出的正文: re.本轮写出的正文出现几次, 修订处: re['「修订 N 处」出现几次'], 状态栏: re.状态栏, 库里: re.库里字数 },
  }))
}
