// P97 B：**⑩ 那一档「重开之后正好开着带层那篇」，屏幕上到底有没有那句 toast。**
//
// ── P95 留下的原话 ────────────────────────────────────────────────────────
//     这一档**读不到**那句 toast，是量具够不着还是用户也看不到，**这一批没量**。
//
// **这是两件事**（P80 立的规矩：两边都要有证据）。所以这一份读三次，三个数都打出来：
//
//  ① **「⑩ 那个时刻」怎么读的**：逐字照 `reopen64.mjs` 开头那几行
//     （`until(pageText>50) + wait(2000) + setTheme + wait(400)`），读一次 toast。
//     这一格复现的是 P95 那个 `[]`。
//  ② **「从连上那一刻就盯着」**：连上 CDP 之后每 80ms 读一次，读满 `<ms>`。
//     ⚠️ **连上那一刻本身就晚了**：`go.sh` 等 page target（秒级）之后还 `sleep 5`。
//     这一格量的是「量具最早能到场的时间」，**不是**「屏幕上有没有过」。
//  ③ **「从渲染进程这一次启动的第 0 毫秒开始录」**：
//     `Page.addScriptToEvaluateOnNewDocument` 把录音机装在**页面脚本之前**，
//     再 `Page.reload()` 让 app 完整重走一遍启动。录的是 `.toaster > .toast`
//     这些**真 DOM 节点**的增删，每一条带 `performance.now()`。
//     头一次看见就**当场截一张图**，并且把它的 `getBoundingClientRect` +
//     `opacity` / `visibility` / `display` 一起读出来——
//     **「DOM 里有」≠「屏幕上看得见」**（「看到 ≠ 真在正文里」的同族）。
//
// 为什么 ③ 算数：产生那句 toast 的是 `App.tsx` 里 `useEffect(..., [current?.id])`
// 那一条——**渲染进程这一侧**的事（`current` 从 localStorage 里那篇恢复 →
// `api.listChangeLayers` → `+320ms` → `reopenedLayersNotice` → `toast()`）。
// 主进程重不重启它一个字都不看。`reload` 之后 localStorage 原样、开的还是同一篇，
// 这条 effect 走的是**逐句相同**的一条路。
// ⚠️ 照旧记着：**`reload` 不是「关掉重开」**。真·关掉重开那一趟是 ①②
// （壳是 `go.sh` 新起的），③ 补的是「它活着的那几百毫秒里屏幕上是什么」。
//
// usage: toast97.mjs <截图名前缀> [盯多少毫秒，默认 20000]
import { pageText, until, wait } from './lib.mjs'

/** 装在页面脚本之前的录音机：录 `.toaster > .toast` 的增删，带毫秒。 */
const RECORDER = `(() => {
  window.__p97 = { t0: Date.now(), rows: [], live: new Map() }
  const scan = () => {
    const now = Date.now() - window.__p97.t0
    const cur = new Set()
    for (const el of document.querySelectorAll('.toaster > .toast')) {
      const txt = (el.textContent || '').trim()
      if (!txt) continue
      cur.add(txt)
      if (!window.__p97.live.has(txt)) {
        const r = el.getBoundingClientRect()
        const cs = getComputedStyle(el)
        const row = { text: txt, 出现: now, 消失: null,
          屏幕上: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
                    opacity: cs.opacity, visibility: cs.visibility, display: cs.display } }
        window.__p97.rows.push(row)
        window.__p97.live.set(txt, row)
      }
    }
    for (const [txt, row] of window.__p97.live) {
      if (!cur.has(txt)) { row.消失 = now; window.__p97.live.delete(txt) }
    }
  }
  // ⚠️ **观察的是 \`document\`，不是 \`document.documentElement\`**：
  // 这段脚本跑在**页面脚本之前**，那一刻 \`documentElement\` 还是 null，
  // \`observe()\` 当场抛 \`parameter 1 is not of type 'Node'\` —— 实拍栽过一次，
  // 而症状是「录到 0 条」，跟「屏幕上真没有过」**长得一模一样**
  // （「选不到 ≠ 没有」的又一张脸）。所以下面那句 \`录音机装上了吗\` 是承重的。
  new MutationObserver(scan).observe(document, { childList: true, subtree: true, characterData: true })
  setInterval(scan, 40)
  window.__p97.armed = true
  scan()
})()`

const TOAST = '上次没处置完的'

export default async function (d, args) {
  const prefix = args[0] || 'p97-toast'
  const budget = Number(args[1] || 20000)

  // ── ① 「⑩ 那个时刻」的读法（逐字照 reopen64.mjs 开头）─────────────────
  const t0 = Date.now()
  await until(async () => (await pageText(d)).length > 50, 30000)
  console.log(`=== ① 「⑩ 那个时刻」的读法（照 reopen64.mjs：until(pageText>50) + wait(2000) + setTheme + wait(400)）===`)
  console.log(`  pageText>50 等了 ${Date.now() - t0} 毫秒`)
  await wait(2000)
  await d.setTheme('light'); await wait(400)
  console.log('  壳刚起来，现在开着:', await d.noteId())
  console.log('  右栏页签:', JSON.stringify(await d.texts('.pane-tab', 12)))
  console.log('  这一刻的 toast:', JSON.stringify(await d.toasts()))
  console.log(`  （从这一步连上算起 ${Date.now() - t0} 毫秒）`)
  await d.shot(`${prefix}-1-at10.png`)

  // ── ② 从连上那一刻起盯着 ────────────────────────────────────────────────
  console.log(`=== ② 从连上那一刻起每 80ms 读一次，读满 ${budget} 毫秒 ===`)
  const seen = []
  const t1 = Date.now()
  while (Date.now() - t1 < budget) {
    const ts = await d.toasts()
    if (ts.length) seen.push({ 毫秒: Date.now() - t1, toast: ts })
    await wait(80)
  }
  console.log('  这段时间里读到过的 toast:', JSON.stringify(seen))
  console.log('  ⚠️ 读不到**不等于**屏幕上没有过：`go.sh` 等 page target 之后还 sleep 5，'
    + '量具最早能到场的时候，app 早就启动完了')

  // ── ③ 从渲染进程第 0 毫秒开始录 ─────────────────────────────────────────
  console.log('=== ③ 把录音机装在页面脚本之前，再 reload 让 app 完整重走一遍启动 ===')
  await d.c.send('Page.addScriptToEvaluateOnNewDocument', { source: RECORDER })
  await d.c.send('Page.reload', { ignoreCache: false })
  await wait(300)

  let shot = false
  let firstAt = -1
  const t2 = Date.now()
  while (Date.now() - t2 < budget) {
    const live = await d.eval(`(() => {
      const els = Array.from(document.querySelectorAll('.toaster > .toast'))
      return els.map((e) => (e.textContent || '').trim()).filter(Boolean)
    })()`)
    if (live.length && !shot) {
      firstAt = Date.now() - t2
      console.log(`  第一次看见（reload 之后 ${firstAt} 毫秒）:`, JSON.stringify(live))
      // **当场截图**：这是「用户看得见」唯一的物证
      await d.shot(`${prefix}-3-onscreen.png`)
      shot = true
    }
    if (shot && !live.length) break
    await wait(60)
  }
  if (!shot) console.log(`  盯了 ${budget} 毫秒，`.concat('`.toaster > .toast` 一次都没出现'))
  // 让那个 40ms 的 `setInterval` 再扫一遍，把「消失」那一格也记上
  await wait(300)

  const rec = await d.eval(`(() => {
    const r = window.__p97
    if (!r) return null
    return { rows: r.rows, armed: !!r.armed, 录了多久: Date.now() - r.t0 }
  })()`)
  if (!rec) throw new Error('录音机没装上——`window.__p97` 读不到；'
    + '**读不到 ≠ 没发生**，这一趟的 ③ 不算数，得重跑')
  // **「装上了」和「录到 0 条」得分开**：录音机自己炸了的话也是 0 条，
  // 而那跟「屏幕上真没有过」在日志上一模一样（实拍栽过一次：`observe(documentElement)`）。
  console.log('  录音机装上了吗:', rec.armed)
  if (!rec.armed) throw new Error('录音机装上了一半就抛了（`__p97.armed` 不是 true）——'
    + '**「录到 0 条」这时候一个字都不算数**，去看 renderer console 那几行')
  console.log('  录到的 toast（带毫秒 + 那一刻它在屏幕上的位置 / 样式）:', JSON.stringify(rec.rows))
  console.log('  录了', rec.录了多久, '毫秒')

  const hit = rec.rows.filter((r) => r.text.includes(TOAST))
  console.log(`  含「${TOAST}」的:`, JSON.stringify(hit))
  for (const h of hit) {
    const live = h.消失 === null ? '（还没消失就读完了）' : `${h.消失 - h.出现} 毫秒`
    console.log(`    · 在屏幕上活了 ${live}；`
      + `出现在第 ${h.出现} 毫秒；框 ${h.屏幕上.w}×${h.屏幕上.h} @ (${h.屏幕上.x},${h.屏幕上.y})；`
      + `opacity=${h.屏幕上.opacity} visibility=${h.屏幕上.visibility} display=${h.屏幕上.display}`)
  }
  console.log('  判：', hit.length
    ? '**用户看得见**——它真的出现在屏幕上过；⑩ 那一格读不到是**量具够不着**（它到场的时候已经过去了）'
    : '**这一趟一次都没录到**——这一档得当缺陷查（别记成「量具够不着」）')

  // 顺手把 P43 那条不变式再核一次（弹了 toast ⇒ 「改动」页签在）
  const tabs = await d.texts('.pane-tab', 12)
  console.log('  reload 之后的右栏页签:', JSON.stringify(tabs))
  console.log('  P43 不变式（弹了 toast ⇒ 页签在）:',
    hit.length ? (tabs.some((x) => x.includes('改动')) ? '成立' : '**破了**') : '没弹 toast，不适用')
  console.log('  开着的是:', await d.noteId())
  await d.shot(`${prefix}-4-after.png`)
}
