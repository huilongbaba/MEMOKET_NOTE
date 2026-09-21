// P101 A：**关掉重开那一屏，右栏有几张轮次卡**——改前 / 改后同一个探针跑两趟。
//
// P99 在真壳上量到、也判好了形状的那件事：
//   > `harness_rounds` **早就逐轮记着骨架**，实测那一篇 **6 runs / 12 rounds**，
//   > 界面重开之后 **0 张卡**——**前端一行都没读，也没有那条 API。**
//   > **判**：不新开表；补的是「读回来那条路」；**缺的明细在卡上照实标**。
//
// 这一步**只读不判**（判在台账 §A）。它把同一屏读四样，**两头都摆出来**：
//   ① **屏幕上**：右栏条上那几格逐字 / 底下有几种「第 N 轮」/
//      「这张卡是从库里读回来的骨架」出现几次 /「库里没有」出现几次 /
//      「本轮写出的正文」出现几次；
//   ② **库里**：直接 `fetch` 那条只读 API（`GET /api/notes/<id>/rounds`）——
//      **「编辑器里没有 ≠ 库里没有」**。改前那一趟这条 API 照样通
//      （后端件是同一个，换的只有 `Resources/web`），所以它读回来的
//      「库里有几轮」在两趟里是**同一个数**，而屏幕上那个数不是。
//      **这正是「改前 0 张卡」那句话的证据**：不是库里没有，是没人读。
//
// ⚠️ **`docText()` 只数得到视口里渲染的那几行**（P99 实拍：库 387 的笔记读回 300）。
//    所以正文那一格**同时读状态栏**，判正文有没有丢一律看单篇 API 那个数。
//
// ⚠️ **别把「几种轮次卡」读成「后端跑了几轮」**：前者是右栏摆出来的，
//    后者在 `harness_rounds` 里，这一步两个都打出来，**分开记**。
//
//   node cdp.mjs <port> steps/rounds101.mjs <截图名前缀> <note id> [标题头几个字]
import { docText, pageText, wait } from './lib.mjs'
import { USER } from '../whoami.mjs'

/** 这一刻的那几样。**点进「计划」再读**——`<details>` 收着 / 页签没选中时 `innerText` 读不到（P60）。 */
async function snap(d, tag, shotPrefix, noteId) {
  const tabs = await d.eval(`Array.from(document.querySelectorAll('.pane-tab')).map((e) => {
    const r = e.getBoundingClientRect()
    return { t: (e.textContent||'').replace(/\\s+/g,' ').trim(), cx: r.x + r.width/2, cy: r.y + r.height/2 }
  })`)
  const plan = tabs.find((x) => x.t.startsWith('计划'))
  let rounds = []
  let restored = 0
  let missingLine = 0
  let wrote = 0
  let facts = 0
  if (plan) {
    await d.clickAt(plan.cx, plan.cy)
    await wait(800)
    await d.eval(`(() => { for (const e of document.querySelectorAll('.right-pane-body details')) e.open = true })()`)
    const body = await d.eval(`(document.querySelector('.right-pane-body')?.innerText ?? null)`)
    if (body === null) throw new Error('`.right-pane-body` 整个选不到——右栏没渲染出来（**选不到 ≠ 没有**，先去看 App.tsx）')
    const flat = body.replace(/\s+/g, ' ').trim()
    rounds = [...new Set(flat.match(/第 \d+ 轮/g) || [])]
    // ⚠️ 这四个串**先去 `AgentActivity.tsx` 里核过在不在**：写一个产品里根本没有的串，
    //    这几格会**永远是 0**，读起来跟「真的没有」一模一样（判据比产品窄的又一张脸）。
    restored = flat.split('这张卡是从库里读回来的骨架').length - 1
    missingLine = flat.split('库里没有').length - 1
    facts = flat.split('库里存着的').length - 1
    // ⚠️ **数的是 `本轮写出的正文（` 那个左括号**，不是光那五个字：
    //    「库里没有：**本轮写出的正文**、工具调用逐条…」那一行里也有这五个字，
    //    光数字面串会把**「照实标出它没有」**数成**「它有」**——正好反了。
    //    真正那一块的抬头是 `本轮写出的正文（{n} 字）`（`AgentActivity.tsx`），
    //    左括号是它独有的。**第一趟就是这么读错的，照实记。**
    wrote = flat.split('本轮写出的正文（').length - 1
  }
  const doc = (await docText(d)) ?? ''
  const status = await d.eval(`(document.querySelector('.status-bar')?.innerText ?? '').replace(/\\s+/g,' ').trim()`)
  // **库里那一篇 + 库里那几轮**：两条只读 API。**「屏幕上没有 ≠ 库里没有」**。
  const db = await d.eval(`(async () => {
    const u = ${USER}
    const id = ${JSON.stringify(noteId)}
    const a = await fetch('/api/notes/' + id, { headers: { 'X-User-Id': u } })
    const note = a.ok ? await a.json() : null
    const b = await fetch('/api/notes/' + id + '/rounds', { headers: { 'X-User-Id': u } })
    const r = b.ok ? await b.json() : null
    return {
      noteStatus: a.status, len: note ? (note.content ?? '').length : null,
      apiHttp: b.status,
      // **这条 API 在改前那一趟也通**（后端件同一个）——所以下面这三个数
      // 在两趟里该是一样的，而屏幕上那个数不是。
      apiRounds: r ? (r.rounds ?? []).length : null,
      apiReason: r ? r.reason : null,
      apiRunsTotal: r ? r.runsTotal : null,
      apiRoundsTotal: r ? r.roundsTotal : null,
      apiMissing: r ? (r.missing ?? []).length : null,
    }
  })()`)
  const out = {
    档: tag,
    条上几格: tabs.map((x) => x.t),
    '屏幕上·几种轮次卡': rounds.length,
    '屏幕上·轮次卡': rounds,
    '屏幕上·读回来的骨架那条横条出现几次': restored,
    '屏幕上·「库里没有」出现几次': missingLine,
    '屏幕上·「库里存着的」出现几次': facts,
    '屏幕上·「本轮写出的正文（」那一块出现几次': wrote,
    '库里·那一次跑几轮': db.apiRounds,
    '库里·reason': db.apiReason,
    '库里·一共几次跑': db.apiRunsTotal,
    '库里·一共几行轮次': db.apiRoundsTotal,
    '库里·缺的明细几样': db.apiMissing,
    'rounds API 回的状态': db.apiHttp,
    '编辑器字数（只作参考·见抬头）': doc.length,
    状态栏: (status.match(/\d[\d,]*\s*字/) || [''])[0],
    库里字数: db.len,
  }
  console.log(`  [${tag}]`, JSON.stringify(out))
  await d.shot(`${shotPrefix}-${tag}.png`)
  return out
}

export default async function (d, [shotPrefix, noteId, titleHead]) {
  const prefix = shotPrefix || 'p101-rounds'
  if (!noteId) throw new Error('没给 note id——**不拿上一趟那篇顶上去**（P80 问题 #7 那条坑）')
  await d.setTheme('light'); await wait(400)
  await d.openNoteById(noteId, titleHead ?? '')
  await wait(2500)
  console.log('  开着的是:', await d.noteId(), '（该是', noteId, '）')

  // ① 刚打开这一屏（= 用户「关掉重开」之后看到的那一屏，壳是这一趟新起的）
  const open = await snap(d, '重开这一屏', prefix, noteId)

  // ② 切到另一篇再切回来：读回来那一叠**不许在切走切回之后变样**
  console.log('=== 切到虚拟页再切回来 ===')
  await d.key('Escape'); await wait(300)
  await d.eval(`window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'app:journey' }))`)
  await wait(1800)
  console.log('  切到了:', JSON.stringify(await d.eval(`(document.querySelector('.note-tab.active')?.textContent ?? '').trim()`)))
  await d.openNoteById(noteId, titleHead ?? '')
  await wait(2500)
  const back = await snap(d, '切回来', prefix, noteId)

  // ③ 那条横条上逐字写着什么（**「缺的明细照实标」那句话的原文**）
  const txt = await pageText(d)
  const line = (txt.match(/[^\n]*从库里读回来的骨架[^\n]*/g) || [])
  console.log('  横条那一行逐字:', JSON.stringify(line.slice(0, 2)))
  const miss = (txt.match(/[^\n]*库里没有[^\n]*/g) || [])
  console.log('  「库里没有」那一行逐字:', JSON.stringify(miss.slice(0, 1)))

  console.log('=== 两档并排 ===')
  console.log('  ', JSON.stringify({
    重开这一屏: { 屏幕上的卡: open['屏幕上·几种轮次卡'], 横条: open['屏幕上·读回来的骨架那条横条出现几次'], 库里那次跑: open['库里·那一次跑几轮'], 库里共几行: open['库里·一共几行轮次'] },
    切回来: { 屏幕上的卡: back['屏幕上·几种轮次卡'], 横条: back['屏幕上·读回来的骨架那条横条出现几次'], 库里那次跑: back['库里·那一次跑几轮'], 库里共几行: back['库里·一共几行轮次'] },
  }))
  console.log('  ⚠️ **「屏幕上的卡」和「库里那次跑」是两把尺**：'
    + '改之前库里那个数照样在（那条 API 在改前那一趟也通），屏幕上那个数是 0——'
    + '**不是库里没有，是没人读**。')
}
