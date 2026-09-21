// P103 A：**`onSkeleton` 那处误伤到底伤了什么**——跑着切走，自动生成的骨架落没落库。
//
// P101 B 逐字留下来的那半句：
//   > `onSkeleton` —— 这一条里藏着另一处误伤，照实记、这一批不治：
//   > `persistSkeleton(s, b, noteId)` **确实是按 noteId 落库的**，切走就丢；
//   > 但它跟 `setSpine` / `setBeats` / `setSkeletonNotes` 缠在一条里，拆开要有自己的判据，
//   > 而 P99 没给它实拍。
//
// 这一步就是那份实拍。**它只读不判**（判在台账 §A）。
//
// ── 为什么「落没落库」这件事只有这条路答得了 ──────────────────────────────
// 后端**没有**任何一条路会把跑里现生成的骨架写进笔记：`store.set_skeleton` 全仓
// 只有一个调用点，在 `routers/notes.py` 的 `PUT /api/notes/<id>/skeleton` 上，
// 而那条 HTTP 只有前端 `persistSkeleton` 会发（`api.saveSkeleton`）。
// ⇒ **前端那一句被拦住 = 这一次生成的骨架永久没了**（下次打开要重新打一次模型，
//    而重新生成出来的是**另一份**骨架）。
//
// ── 两档，差别只在「切不切走」 ────────────────────────────────────────────
//   · `stay` —— 点完「智能续写」**原地不动**。对照组。
//   · `away` —— 点完**立刻**切到别的去处，停 N 毫秒再切回来。
//     ⚠️ 「立刻」是这一步的承重件：`onSkeleton` 是整条跑**最上游**那一发，
//        慢一步它就已经到了，那时候量到的是「没切走」（量具够不着 ≠ 产品没毛病）。
//        所以这一趟的假模型要**每一发慢几秒**（`LLM_DELAY_MS`），
//        而且这一步点完按钮**不等任何东西**就切走。
//
// ── 量具那两处够不着，都是实拍出来的，别删 ────────────────────────────────
//  1. **`--mode ok` 的假模型压根不回骨架 JSON**（`walkthrough_fakellm.py` 的
//     `is_skeleton` 只在 adv / floor / ship / shapes 那几档有分支），于是 `spine`
//     恒为空、`stay` 和 `away` **两档都读 0**。第一趟就是这么读回来的——
//     那是量具够不着，不是产品没毛病。**这一步必须跑 `LLM_MODE=adv`。**
//  2. **前端自己还有一条后台骨架**（`App.tsx` 的 `runSkeleton(true)`：停顿 8 秒 +
//     内容变了 20 字就自动生成并落库）。它跟 harness 那一发**落的是同一份文本**，
//     光看 `spine` 的字分不开谁写的。
//  3. ⚠️ **光把库里那份清掉没有用**（第二版就是这么写的，实拍 `stay` / `away`
//     **两档都在第 1 秒就落了库**）：`api.runNoteHarness(noteId, content, spine, beats, …)`
//     **把前端内存里那份 spine/beats 一起发给后端**，后端 `NoteHooks(spine=…, beats=…)`
//     拿到非空就**不再生成**，`onSkeleton` 一发就到（**没有那 7 秒**），
//     切走再快也赶不上。**「我把库清了」≠「这一次跑会现生成一份」。**
//     ⇒ 这一步改成**打完字 8 秒之内就点「智能续写」**（后台那条还没到点），
//     内存里那份是空的 ⇒ 后端真的现生成 ⇒ 那一发要等假模型慢的那几秒。
//     判据只认**「点完之后盯库，`spine` 第几秒变非 0」**那一格。
//     `跑完` / `重开之后` 两格**会被后台那条重新填上**，照实记、**不拿它下判**。
//
// ── 读的几样（**两头都读**）────────────────────────────────────────────────
//   · **库里那一篇**：`GET /api/notes/<id>` 的 `spine` / `beats`（带 `X-User-Id` 头）。
//     **「编辑器里有 ≠ 库里有」**——这一格是承重的，判就判它。
//   · **屏幕上**：右栏「计划」那一格里那句主线在不在。
//   两个数分开摆：它们可以不一样（内存里有、库里没有，正是这处误伤的形状）。
//
//   node cdp.mjs <port> steps/skel103.mjs <档: stay|away> <截图名前缀> [切走停留毫秒]
import { clickExact } from './clickexact.mjs'
import { docText, pageText, until, wait } from './lib.mjs'
import { USER } from '../whoami.mjs'

const SEED = [
  'P103 走查：这一批在治 onSkeleton 那处误伤，顺带判三条 toast 切走之后该不该弹。',
  '众筹页面那一版文案是 3 月 12 号上线的，当天点击 12700，退款率 1.8%。',
  '预热名单回收了 860 份，按渠道排了一遍：自然搜索 41%、朋友转发 33%、广告 26%。',
  '下一步要把「谁来付钱」这条线单独拆出来，别跟「谁会用」混在一张表里。',
]

/** 库里那一篇的骨架（**判就判这一格**）。 */
async function dbSkeleton(d, noteId) {
  return d.eval(`(async () => {
    const r = await fetch('/api/notes/' + ${JSON.stringify(noteId)}, { headers: { 'X-User-Id': ${USER} } })
    if (!r.ok) return { status: r.status, spine: null, beats: null }
    const j = await r.json()
    return { status: r.status, spine: (j.spine ?? ''), beats: (j.beats ?? []) }
  })()`)
}

/** 屏幕上右栏「计划」那一格里写着什么（**跟库里那格分开记**）。 */
async function paneSkeleton(d, paneWait = 800) {
  const tabs = await d.eval(`Array.from(document.querySelectorAll('.pane-tab')).map((e) => {
    const r = e.getBoundingClientRect()
    return { t: (e.textContent||'').replace(/\\s+/g,' ').trim(), cx: r.x + r.width/2, cy: r.y + r.height/2 }
  })`)
  const plan = tabs.find((x) => x.t.startsWith('计划'))
  if (!plan) return { 页签: tabs.map((x) => x.t), 正文: null }
  await d.clickAt(plan.cx, plan.cy)
  await wait(paneWait)
  const body = await d.eval(`(document.querySelector('.right-pane-body')?.innerText ?? null)`)
  if (body === null) throw new Error('`.right-pane-body` 整个选不到——右栏没渲染出来（**选不到 ≠ 没有**，先去看 App.tsx）')
  return { 页签: tabs.map((x) => x.t), 正文: body.replace(/\s+/g, ' ').trim() }
}

async function snap(d, tag, shotPrefix, noteId, { shot = true, paneWait = 800 } = {}) {
  const db = await dbSkeleton(d, noteId)
  const pane = await paneSkeleton(d, paneWait)
  const out = {
    档: tag,
    '库里 spine 几个字': db.spine === null ? null : db.spine.length,
    '库里 beats 几条': db.beats === null ? null : db.beats.length,
    '库里 spine 头 40 字': db.spine === null ? null : db.spine.slice(0, 40),
    '库里回的状态': db.status,
    '右栏「计划」头 160 字': (pane.正文 ?? '').slice(0, 160),
    '右栏页签': pane.页签,
    '编辑器字数（只作参考）': ((await docText(d)) ?? '').length,
  }
  console.log(`  [${tag}]`, JSON.stringify(out))
  if (shot) await d.shot(`${shotPrefix}-${tag}.png`)
  return out
}

/** 切到另一个去处（⌘K 打开「屏幕活动」那种虚拟页——跟 `steps/rounds99.mjs` 同一份做法）。 */
async function switchAway(d, t0) {
  await d.key('Escape'); await wait(150)
  await d.eval(`window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'app:journey' }))`)
  // ⚠️ **「我 dispatch 了」≠「current 真的换了」**：那一刀问的是 `currentRef.current?.id`，
  //    `openVirtual` 里先 `await save()` 才 `setCurrent(null)`。**盯到它真的换了为止**，
  //    并且把「第几毫秒换的」打出来——切走得比 `onSkeleton` 早，这个数是承重的。
  //
  // ⚠️ **别拿 `d.noteId()` 当「现在开着哪一篇」**（第一版就是这么栽的）：它读的是
  //    `localStorage['memoket-note-active:<user>']`，那是**上次打开的那一篇**，
  //    开虚拟页不会清它 —— 于是这一格永远非空，看起来像「没切走」。
  //    真正对得上 `current === null` 的是：**活动标签换成了那个虚拟页** +
  //    **编辑器整个不在了**（`openVirtual` 把 `current` 置空，编辑器就不渲染）。
  const gone = await until(async () => {
    const st = await d.eval(`(() => ({
      tab: (document.querySelector('.note-tab.active')?.textContent ?? '').trim(),
      cm: !!document.querySelector('.cm-content'),
    }))()`)
    return (st.tab.startsWith('屏幕活动') && !st.cm) ? Math.round(Date.now() - t0) : null
  }, 8000, 100)
  const st = await d.eval(`(() => ({
    tab: (document.querySelector('.note-tab.active')?.textContent ?? '').trim(),
    cm: !!document.querySelector('.cm-content'),
  }))()`)
  return { 第几毫秒真的切走了: gone, 活动标签: st.tab, 编辑器还在吗: st.cm }
}

export default async function (d, [phase, shotPrefixRaw, awayMsRaw]) {
  const prefix = shotPrefixRaw || 'p103-skel'
  const awayMs = Number(awayMsRaw || 25000)
  if (phase !== 'stay' && phase !== 'away') throw new Error('没给档（stay | away）——**跳过就是跳过**')

  await d.setTheme('light'); await wait(400)
  await until(async () => await d.exists('.cm-content'), 30000)
  await wait(1200)

  console.log('=== 现造一篇（**这一趟自己造的**，不拿上一趟那篇顶上去）===')
  await d.key('Escape'); await wait(300)
  await d.key('k', ['meta']); await wait(1000)
  await d.insert('新建笔记'); await wait(1000)
  await clickExact(d, '新建笔记', 0, 8)
  await wait(2500)
  const noteId = await d.noteId()
  console.log('  新建出来的 note id:', noteId)
  if (!noteId) throw new Error('新建之后读不到 note id——**别往下跑**')
  // **标题带一个这一趟独有的记号**：走查会在同一份 udd 上跑好几趟，
  // 标题一样的话 `openNoteById` 会在一堆同名候选里逐个点，点不中就 FAIL
  // （实拍过一次：6 个候选全是上几趟留下的「P103 骨架实拍」）。
  const nonce = 'N' + Date.now().toString(36).slice(-6)
  const titleHead = `P103骨架${nonce}`
  await d.focusEditor()
  await d.insert(`# ${titleHead}（${phase}，可删）`); await d.key('Enter'); await d.key('Enter')
  for (const s of SEED) { await d.insert(s); await d.key('Enter'); await d.key('Enter'); await wait(200) }
  // ⚠️ **这里不许多等**：后台那条骨架是「停顿 8 秒」就跑，等够了它就把 spine 填上了，
  //    这一趟量到的就成了「本来就有」（见抬头第 3 条）。
  await wait(1200)

  // **这一段有预算**：打完最后一个字到点「智能续写」之间越短越好（后台那条是
  // `SKELETON_IDLE_MS = 8000`）。所以**点之前只读库**（一发 fetch，百来毫秒），
  // 右栏那一格留到点完之后再读——**读一眼右栏要点页签 + 等渲染 + 截图，
  // 那几秒正好够后台那条起跑**（实拍栽过一次：读完右栏写着「写作骨架 停止」，
  // 后台那条已经在飞了）。
  const tType = Date.now()
  const base0 = await dbSkeleton(d, noteId)
  console.log('  [打完字·还没点·只读库]', JSON.stringify({ spine: base0.spine.length, beats: base0.beats.length }))
  if (base0.spine.length !== 0 || base0.beats.length !== 0) {
    // **这一步的前提**：这一篇没有骨架，跑起来才会现生成一份。
    // 有的话这一趟量到的是「本来就有」，跟切不切走无关——**那不是读数，是废掉的一趟**。
    throw new Error(`还没点就有骨架了（spine ${base0.spine.length} 字 / beats ${base0.beats.length} 条）——前提不成立，这一趟作废`)
  }
  const base = { '库里 spine 几个字': base0.spine.length, '库里 beats 几条': base0.beats.length }

  console.log(`=== 点「智能续写」（读完那一格花了 ${Date.now() - tType} 毫秒）===`)
  const t0 = Date.now()
  await clickExact(d, '智能续写', 0, 10)

  // ⚠️ **不拿「第 1 轮出现了」当骨架到过的凭据**（第一版就是这么写的，错了）：
  //    `ROUND_START` 排在骨架那一发**前面**，实拍 `stay` 那一趟第 1 轮 **1 秒**就有了，
  //    而骨架那一发要等假模型慢的那 7 秒。**「看到 ≠ 那件事发生了」的又一张脸。**
  //    判据换成**直接盯库**：`spine` 从 0 变成非 0 的那一刻，就是 `persistSkeleton` 落地的那一刻。
  const pollSpine = async (budgetMs, everyMs = 1000) => {
    const t = Date.now()
    const hit = await until(async () => {
      const s = await dbSkeleton(d, noteId)
      return (s.spine && s.spine.length) ? Math.round((Date.now() - t0) / 1000) : null
    }, budgetMs, everyMs)
    return { 秒: hit, 等了几秒: Math.round((Date.now() - t) / 1000) }
  }

  let landed
  if (phase === 'away') {
    // ⚠️ **不等任何东西**：`onSkeleton` 是最上游那一发，等一下它就已经到了。
    const away = await switchAway(d, t0)
    console.log('  切走那一下:', JSON.stringify(away))
    if (away.第几毫秒真的切走了 === null) throw new Error('dispatch 完 8 秒 `current` 还在那一篇上——没真的切走，这一趟作废')
    // **在别处的这段时间里一直盯着库**（fetch 跟屏幕上开着哪一篇无关）。
    landed = await pollSpine(awayMs)
    console.log(`  在别处盯了 ${landed.等了几秒} 秒，库里 spine 变非 0 了吗: `
      + (landed.秒 === null ? 'null（**一直是 0**——`until` 超时是静默 return null，等的就是这 ' + Math.round(awayMs / 1000) + ' 秒）' : `第 ${landed.秒} 秒`))
    await d.openNoteById(noteId, titleHead)
    await wait(2500)
    console.log('  切回来开着的是:', await d.noteId(), '（该是', noteId, '）')
  } else {
    landed = await pollSpine(awayMs)
    console.log(`  原地盯了 ${landed.等了几秒} 秒，库里 spine 变非 0 了吗: `
      + (landed.秒 === null ? 'null（**一直是 0**——超时，不是「跑完了」）' : `第 ${landed.秒} 秒`))
    // **对照组自己得先站得住**：落库那一刻必须**晚于**假模型那一发的延时。
    // 落在第 1 秒 = 后端**没有现生成**（前端把内存里那份一起发过去了，见抬头第 3 条）
    // ⇒ 这一趟比的就不是「切不切走」，**是废掉的一趟**。
    if (landed.秒 !== null && landed.秒 < 5) {
      throw new Error(`对照组第 ${landed.秒} 秒就落库了——那一发没现生成（内存里那份非空），前提不成立，这一趟作废`)
    }
  }
  const afterSkel = await snap(d, '骨架那一发之后', prefix, noteId)

  const done = await until(async () => (/· \d+ 轮 ·/.test(await pageText(d)) ? true : null), 300000, 2000)
  console.log(`  收工那行等到了吗: ${done === true}（等了 ${Math.round((Date.now() - t0) / 1000)} 秒）`)
  await wait(3000)
  const fin = await snap(d, '跑完', prefix, noteId)

  console.log('=== 关掉重开（renderer reload：内存里那份从此不存在）===')
  await d.eval('location.reload()')
  await wait(9000)
  const up = await until(async () => (await d.exists('.cm-content')) || null, 60000, 1000)
  console.log('  重开之后编辑器起来了吗:', up === true)
  await wait(1500)
  if ((await d.noteId()) !== noteId) await d.openNoteById(noteId, titleHead)
  await wait(2000)
  const re = await snap(d, '重开之后', prefix, noteId)

  console.log('=== 并排（**判就判「★ 盯库那一格」**，见抬头第 2 条）===')
  console.log('  ', JSON.stringify({
    档: phase,
    '打完字·还没点': { 库spine: base['库里 spine 几个字'], 库beats: base['库里 beats 几条'] },
    '★库里 spine 第几秒变非 0（null = 这一窗口里一次都没有）': landed.秒,
    '★盯了几秒': landed.等了几秒,
    骨架那一发之后: { 库spine: afterSkel['库里 spine 几个字'], 库beats: afterSkel['库里 beats 几条'] },
    '跑完（会被后台那条重新填上，不下判）': { 库spine: fin['库里 spine 几个字'], 库beats: fin['库里 beats 几条'] },
    '重开之后（同上）': { 库spine: re['库里 spine 几个字'], 库beats: re['库里 beats 几条'] },
  }))
}
