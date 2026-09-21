// P103 B：**三条 toast 切走之后该不该弹**——弹出来的那句话**说的是哪一篇**。
//
// P101 B 逐字留下来的那半句：
//   > `onCost` / `onCrossRun` / `onWarning` —— 只弹一句 toast。**这一批不动**：
//   > 它们该不该在你已经切走之后弹是**另一条判据**（弹出来看不出说的是哪一篇），
//   > 没有实拍撑着，**判据宁可窄**。
//
// 这一步给的就是那份实拍。**它只读不判**（判在台账 §B）。
//
// ── 拿 `onCost` 当那三条的实拍 ────────────────────────────────────────────
// 三条里**只有 `onCost` 造得出来**：`MEMOKET_RUN_TOKEN_CAP=1` 一设，
// 第一轮末尾 `middleware/cost.py` 就发一条（`over_cap` 在轮末判）。
//   · `onCrossRun` 要「这一篇上一次跑的 final_scores 比这次好」，摆不出来；
//   · `onWarning` 要一条 middleware 真抛异常。
// 它们走的是**同一段代码**（切走那一支各自一句 `awayToast(...)` / 一句 `return`），
// 形状那一半由 `scripts/check-harness-guard.mts` 的第 ⑥ 条核（每条 `self`
// 的跨篇分支里都点了名）。**这一步答的是「屏幕上真的长这样吗」那一半。**
//
// ── 读的那一样 ────────────────────────────────────────────────────────────
// 切走之后**一直盯着 `.toaster > .toast`**，每条第一次出现在第几毫秒、逐字是什么。
// ⚠️ toast 活几秒就没（P97 实拍：某一句在屏幕上活了 3501 毫秒），
//    **隔几秒读一次会整条漏掉**——所以这儿是 400 毫秒一轮地攒，攒的是**并集**。
//
//   node cdp.mjs <port> steps/toast103.mjs <档: stay|away> <截图名前缀> [盯多久毫秒]
import { clickExact } from './clickexact.mjs'
import { until, wait } from './lib.mjs'

const SEED = [
  'P103 toast 实拍：这一段只是给 harness 一点东西可写。',
  '众筹页面那一版文案是 3 月 12 号上线的，当天点击 12700，退款率 1.8%。',
  '预热名单回收了 860 份，按渠道排了一遍：自然搜索 41%、朋友转发 33%、广告 26%。',
]

/** 切到另一个去处（跟 `steps/skel103.mjs` / `steps/rounds99.mjs` 同一份做法）。 */
async function switchAway(d, t0) {
  await d.key('Escape'); await wait(150)
  await d.eval(`window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'app:journey' }))`)
  const gone = await until(async () => {
    const st = await d.eval(`(() => ({
      tab: (document.querySelector('.note-tab.active')?.textContent ?? '').trim(),
      cm: !!document.querySelector('.cm-content'),
    }))()`)
    return (st.tab.startsWith('屏幕活动') && !st.cm) ? Math.round(Date.now() - t0) : null
  }, 8000, 100)
  return gone
}

export default async function (d, [phase, shotPrefixRaw, budgetRaw]) {
  const prefix = shotPrefixRaw || 'p103-toast'
  const budget = Number(budgetRaw || 90000)
  if (phase !== 'stay' && phase !== 'away') throw new Error('没给档（stay | away）——**跳过就是跳过**')

  await d.setTheme('light'); await wait(400)
  await until(async () => await d.exists('.cm-content'), 30000)
  await wait(1200)

  console.log('=== 现造一篇（**这一趟自己造的**）===')
  await d.key('Escape'); await wait(300)
  await d.key('k', ['meta']); await wait(1000)
  await d.insert('新建笔记'); await wait(1000)
  await clickExact(d, '新建笔记', 0, 8)
  await wait(2500)
  const noteId = await d.noteId()
  const nonce = 'T' + Date.now().toString(36).slice(-6)
  const titleHead = `P103toast${nonce}`
  console.log('  新建出来的 note id:', noteId, ' 标题记号:', titleHead)
  if (!noteId) throw new Error('新建之后读不到 note id——**别往下跑**')
  await d.focusEditor()
  await d.insert(`# ${titleHead}（${phase}，可删）`); await d.key('Enter'); await d.key('Enter')
  for (const s of SEED) { await d.insert(s); await d.key('Enter'); await d.key('Enter'); await wait(200) }
  await wait(1200)

  console.log('=== 点「智能续写」（这一趟 MEMOKET_RUN_TOKEN_CAP=1，第一轮末尾必发 cost）===')
  const t0 = Date.now()
  await clickExact(d, '智能续写', 0, 10)

  if (phase === 'away') {
    const gone = await switchAway(d, t0)
    console.log('  第几毫秒真的切走了:', gone)
    if (gone === null) throw new Error('dispatch 完 8 秒 `current` 还在那一篇上——没真的切走，这一趟作废')
  }

  // **400 毫秒一轮地攒并集**（toast 活几秒就没，隔几秒读一次会整条漏掉）。
  const seen = new Map()
  const tEnd = Date.now() + budget
  let shots = 0
  while (Date.now() < tEnd) {
    const now = await d.toasts()
    for (const t of now) {
      if (!seen.has(t)) {
        seen.set(t, Math.round(Date.now() - t0))
        console.log(`  [第 ${seen.get(t)} 毫秒] toast: ${JSON.stringify(t)}`)
        if (shots < 4) { await d.shot(`${prefix}-toast${++shots}.png`); }
      }
    }
    await wait(400)
  }

  const list = [...seen.entries()].sort((a, b) => a[1] - b[1])
  console.log('=== 这一趟攒到的 toast（并集，按第一次出现排）===')
  console.log('  ', JSON.stringify({
    档: phase,
    盯了几秒: Math.round(budget / 1000),
    几条: list.length,
    逐条: list.map(([t, ms]) => ({ 毫秒: ms, 字: t })),
    带篇名的几条: list.filter(([t]) => t.includes(titleHead)).length,
  }))
  await d.shot(`${prefix}-收尾.png`)
}
