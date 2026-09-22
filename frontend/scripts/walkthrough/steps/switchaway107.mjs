// **走查第 ⑫ 步：「跑着切走再切回」**（P105 A 立的；**P107 A 升级判⑤**：点的名得是对的名）。
//
// ⚠️ 为什么是新一份文件而不是改 `switchaway105.mjs`：出处闸（`check-walkthrough-provenance`）把
//    每一批入库日志第一行的 sha 跟**今天仓库里那份**比，改了 105 那份，`p105/41-…` 就永远红
//    ——跟 `rounds95` → `rounds99` → `rounds101` 一个规矩：**一批一份，旧的一个字节不动**。
//
// ── 为什么非有这一步不可 ──────────────────────────────────────────────────
// P103 跑完第二十九次走查，跨批 diff 里「**产品改了**」那一格是 **0 行**，
// 而那一批真的改了产品（`onSkeleton` 落库 + 两条 toast 点名）。它自己写下了这句：
//
//     **十一步那条路一次都不经过「切走」**，A / B 的证据全在新加的四份探针日志里。
//     ⇒ **「走查全绿」≠「这一批的改动被走查验过」。**
//
// 而「切走」这一族这几批已经出过**三个真缺陷**：
//   · **P95**（收 P93 问题 #1）：A 篇跑完 2 轮，⌘K 新建一篇**空**笔记，
//     右栏「计划」写着 `计划 2`，底下摆着 **A 那两轮的执行记录**——**轮次卡串台**；
//   · **P101**：`guarded` 那层一刀切，把**按 noteId 记账**的那 11 条也拦了
//     ——P99 实拍「跑着切走 20 秒再切回 ⇒ 卡上『本轮写出的正文』**2 → 1**」；
//   · **P103**：`onSkeleton` 被同一刀误伤 ⇒ 跑着切走，**那一次生成的骨架永久丢**
//     （盯库 60 秒一直是 0，跑完 0，关掉重开还是 0）；三条 toast 里
//     `onCost` / `onCrossRun` 切走之后**整条不弹**，停机的理由一个字看不到。
//
// **十一步该有这一步了。**
//
// ── 它跟 `steps/` 里那几份专题探针不一样：**它判**────────────────────────
// `rounds95` / `rounds99` / `skel103` / `toast103` 都写着「**只读不判**，判在台账」。
// 这一份**自己判**，判不过**当场 EXIT 非 0 并点名到是哪一条缺陷长回来了**。
// 理由：一份「只读」的步骤要有人每批把日志读一遍才发现回退，
// 而**一条靠人记得的闸不是闸**（跨批 diff 那条闸自己的注释里写着同一句）。
//
// ── 五条判据，逐条钉的是哪一件事 ──────────────────────────────────────────
// | 判 | 钉的缺陷 | 判据（**一个会变的数都不钉**） |
// |---|---|---|
// | ① | **P95 轮次卡串台** | 切走之后 ⌘K 新建的那篇**空**笔记 B：「计划」页签**不带数字** + 底下 **0 种「第 N 轮」** |
// | ② | **P95 切回来不许空** | 切回 A：底下「第 N 轮」**至少 1 种**（`useEffect(…, [current?.id])` 那条路的代价就落在这一格） |
// | ③ | **P101 `guarded` 误伤** | 切回 A：「本轮写出的正文」**至少 1 次**（`TOKEN_CAP=1` ⇒ 只跑一轮，而那一轮整个落在「已经切走」那段时间里）|
// | ④ | **P103 骨架永久丢** | **库里**那一篇的 `spine` 从 0 变非 0，**而且切走那一刻排在落库前面**（比的是两个毫秒数，不是「第几秒」） |
// | ⑤ | **P103 停机理由丢** | 切走之后攒到的 toast 并集里，有一条**既点了名**（`「…」：` 开头）**又带着停机的理由** |
//
// ⚠️ **判据一律「不变式 / floor」，不钉具体数**：第几秒落的库跟着假模型的延时和机器快慢走，
//    跑几轮跟着 token cap 走，卡上几种轮次跟着后端策略走。**钉了那个数的闸，红的理由跟对错无关。**
//
// ── 它**够不着**什么（照 P72 的规矩写在自己身上，不许含糊）────────────────
//  1. ~~**「点了名」≠「点对了名」**（P103 问题 #6）：那句篇名来自 handler 建起来那一刻的
//     `notes` 闭包，**一篇刚新建、标题还没落库的笔记会读成「另一篇笔记」**。~~
//     **P107 A 那一刀做了**（`App.tsx` 的 `noteName()`：读 `notesRef.current` + 走 `displayTitle`）
//     ⇒ 判 ⑤ **从这一批起也判「点的是对的名」**：点了名又带理由的那几条里，
//     **至少一条以这一趟自己的标题记号开头**。P105 这一趟实拍是 0 条（读成「另一篇笔记」1 条），
//     那正是这一批的反例。这一步现造的那篇**标题是打完字才落库的**，正是最容易点错的那一档。
//  2. **`onCrossRun` / `onWarning` 两条摆不出来**：前者要「这一篇上一次跑得更好」，
//     后者要一条 middleware 真抛异常。判 ⑤ 拿 `onCost` 当那一族的实拍
//     （`MEMOKET_RUN_TOKEN_CAP=1` 一设，第一轮末尾必发），形状那一半归
//     `scripts/check-harness-guard.mts` 第 ⑥ 条。
//  3. **「关掉重开还剩什么」不在这一步里**：那是第 ⑩ 步和 `steps/rounds101.mjs` 的射程。
//     这一步从头到尾**不 reload**。
//  4. **它读不到 `harness_runs` / `harness_rounds` 有几行**：没有那条 API，
//     要数在外头拿 sqlite 数（同 `steps/rounds99.mjs` 抬头那条）。
//
// ── 跑它要什么（**三样缺一样这一步就量不到东西**，抬头逐条写死，别删）──────
//  1. **`LLM_MODE=adv`**：`--mode ok` 的假模型压根不回骨架 JSON
//     （`walkthrough_fakellm.py` 的 `is_skeleton` 只在 adv / floor / ship / shapes 有分支）
//     ⇒ 判 ④ 恒读 0，**那是量具够不着，不是产品坏了**（P103 第一趟栽过）。
//  2. **`LLM_DELAY_MS` 给几秒**：`--mode ok` 整趟一两秒就完，「切走」在那种速度上**演不出来**
//     ——**「量具最早能到场就已经晚了」**（P97 那条）。
//  3. **`MEMOKET_RUN_TOKEN_CAP=1`**：判 ⑤ 要的那条 `onCost` 靠它逼出来。
//
// ⚠️ **打完字到点「智能续写」之间不许超过 8 秒**（`SKELETON_IDLE_MS`）：
//    前端自己还有一条后台骨架，等够了它就把 `spine` 填上，这一趟量到的就成了「本来就有」。
//    所以点之前**只读一次库**（一发 fetch，百来毫秒），右栏留到点完之后再读。
// ⚠️ **别拿 `d.noteId()` 当「现在开着哪一篇」**（P103 问题 #8）：它读的是
//    `localStorage['memoket-note-active:<user>']` = **上次打开的那一篇**，开虚拟页不清它。
//    真正对得上 `currentRef.current === null` 的是**活动标签换了 + 编辑器整个不在了**。
// ⚠️ **这一步自己造两篇笔记**，所以它**跟十一步共用一份 udd 就会把十一步弄脏**
//    （P103 问题 #1 那一族第三次）——它自己起一趟壳、自己一份 udd。
//
//   node cdp.mjs <port> steps/switchaway107.mjs <截图名前缀> [盯多久毫秒]
import { clickExact } from './clickexact.mjs'
import { docText, pageText, until, wait } from './lib.mjs'
import { USER } from '../whoami.mjs'

const SEED = [
  'P107 走查第 ⑫ 步：跑着切走再切回，看看切走那几秒里产品到底还干不干活。',
  '众筹页面那一版文案是 3 月 12 号上线的，当天点击 12700，退款率 1.8%。',
  '预热名单回收了 860 份，按渠道排了一遍：自然搜索 41%、朋友转发 33%、广告 26%。',
  '下一步要把「谁来付钱」这条线单独拆出来，别跟「谁会用」混在一张表里。',
]

/** 停机那句话（`middleware/cost.py`）里必然出现的词。**两个都要在**，
 *  只认「上限」会被别的文案蹭到（状态行里也说「上限」）。 */
const COST_WORDS = ['上限', '就停在这儿了']

/** 点名的形状：`「<篇名>」：<原话>`（`App.tsx` 的 `awayToast`）。
 *  **钉的是形状不是篇名**——篇名点不点得对，见抬头「够不着」第 1 条。 */
const NAMED_RE = /^「[^」]{1,60}」：/

/** 库里那一篇（**判就判这一格**：「编辑器里有 ≠ 库里有」）。 */
async function dbNote(d, noteId) {
  return d.eval(`(async () => {
    const r = await fetch('/api/notes/' + ${JSON.stringify(noteId)}, { headers: { 'X-User-Id': ${USER} } })
    if (!r.ok) return { status: r.status, spine: null, beats: null, len: null }
    const j = await r.json()
    return { status: r.status, spine: (j.spine ?? ''), beats: (j.beats ?? []), len: (j.content ?? '').length }
  })()`)
}

/** toast 收一次。**并集**，每条只记第一次出现在第几毫秒。 */
async function pump(d, seen, t0) {
  let now = []
  try { now = await d.toasts() } catch { return }
  for (const t of now) {
    if (!seen.has(t)) {
      seen.set(t, Math.round(Date.now() - t0))
      console.log(`  [第 ${seen.get(t)} 毫秒] toast: ${JSON.stringify(t)}`)
    }
  }
}

/** 等一段，但**每 400 毫秒把 toast 收一次**。
 *
 *  ⚠️ 这一步里**所有的「等」都走这一条**，一处干等都不许有：toast 活几秒就没
 *  （P97 实拍某一句在屏幕上活了 3501 毫秒），干等 5 秒就会**整条漏掉**，
 *  而漏掉之后读起来跟「产品压根没弹」一模一样。 */
async function nap(d, ms, seen, t0) {
  const end = Date.now() + ms
  for (;;) {
    await pump(d, seen, t0)
    const left = end - Date.now()
    if (left <= 0) return
    await wait(Math.min(400, left))
  }
}

/** 右栏「计划」那一格这一刻的样子。**点进去 + 摊开折叠块再读**（P60 那一课：
 *  `<details>` 收着 / 页签没选中时 `innerText` 读不到里头的字）。 */
async function readPlan(d, tag, shotPrefix) {
  const tabs = await d.eval(`Array.from(document.querySelectorAll('.pane-tab')).map((e) => {
    const r = e.getBoundingClientRect()
    return { t: (e.textContent||'').replace(/\\s+/g,' ').trim(), cx: r.x + r.width/2, cy: r.y + r.height/2 }
  })`)
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
  // 「第 N 轮」是 `AgentActivity` 那张卡的抬头，「本轮写出的正文」是卡里那一块。
  // 两个串都**先去 AgentActivity.tsx 里核过在不在**——写一个产品里没有的串，
  // 这一格会永远是 0，读起来跟「真的丢了」一模一样（**判据比产品窄**的那张脸）。
  const rounds = [...new Set(flat.match(/第 \d+ 轮/g) || [])]
  const wrote = flat.split('本轮写出的正文').length - 1
  const out = {
    档: tag,
    '「计划」页签逐字': plan.t,
    页签里有数字吗: /\d/.test(plan.t),
    几种轮次卡: rounds.length,
    轮次卡: rounds,
    本轮写出的正文出现几次: wrote,
    摊开了几个折叠块: opened,
    '底下头 200 字': flat.slice(0, 200),
  }
  console.log(`  [${tag}]`, JSON.stringify(out))
  await d.shot(`${shotPrefix}-${tag}-计划.png`)
  return { tab: plan.t, rounds, wrote, flat }
}

/** 切到另一个去处（⌘K 那种虚拟页——跟 `steps/rounds99.mjs` / `skel103.mjs` 同一份做法）。
 *  回的是「**第几毫秒真的切走的**」，那个数是判 ④ 的承重件。 */
async function switchAway(d, t0) {
  await d.key('Escape'); await wait(150)
  await d.eval(`window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'app:journey' }))`)
  // **「我 dispatch 了」≠「current 真的换了」**：`openVirtual` 里先 `await save()`
  // 才 `setCurrent(null)`。盯到它真的换了为止。
  const gone = await until(async () => {
    const st = await d.eval(`(() => ({
      tab: (document.querySelector('.note-tab.active')?.textContent ?? '').trim(),
      cm: !!document.querySelector('.cm-content'),
    }))()`)
    return (st.tab.startsWith('屏幕活动') && !st.cm) ? Math.round(Date.now() - t0) : null
  }, 8000, 100)
  return gone
}

export default async function (d, [shotPrefixRaw, budgetRaw]) {
  const prefix = shotPrefixRaw || 'p107-switchaway'
  const budget = Number(budgetRaw || 300000)
  /** 判不过的那几条。**攒齐再抛**——一次只报一条的话，下一批还得再跑一趟才知道第二条。 */
  const reds = []
  const red = (tag, why) => { reds.push(`${tag} ${why}`); console.log(`  ❌ ${tag} ${why}`) }
  const green = (tag, what) => console.log(`  ✅ ${tag} ${what}`)

  await d.setTheme('light'); await wait(400)
  await until(async () => await d.exists('.cm-content'), 30000)
  await wait(1200)

  console.log('=== ① 现造 A 篇（**这一趟自己造的**，不拿上一趟那篇顶上去）===')
  await d.key('Escape'); await wait(300)
  await d.key('k', ['meta']); await wait(1000)
  await d.insert('新建笔记'); await wait(1000)
  await clickExact(d, '新建笔记', 0, 8)
  await wait(2500)
  const aId = await d.noteId()
  if (!aId) throw new Error('新建之后读不到 note id——**别往下跑**')
  // **标题带一个这一趟独有的记号**：同一份 udd 上跑过几趟之后标题会撞，
  // `openNoteById` 会在一堆同名候选里逐个点，点不中就 FAIL（P103 实拍过）。
  const nonce = 'S' + Date.now().toString(36).slice(-6)
  const titleHead = `P107切走${nonce}`
  console.log('  新建出来的 note id:', aId, ' 标题记号:', titleHead)
  await d.focusEditor()
  await d.insert(`# ${titleHead}（可删）`); await d.key('Enter'); await d.key('Enter')
  for (const s of SEED) { await d.insert(s); await d.key('Enter'); await d.key('Enter'); await wait(200) }
  await wait(1200)

  // **点之前只读一次库**（见抬头那条 8 秒的预算）。
  const tType = Date.now()
  const base = await dbNote(d, aId)
  console.log('  [打完字·还没点·只读库]', JSON.stringify({ spine: base.spine.length, beats: base.beats.length, 正文: base.len }))
  if (base.spine.length !== 0 || base.beats.length !== 0) {
    // **这一步的前提**：这一篇没有骨架，跑起来才会现生成一份。
    // 有的话量到的是「本来就有」，跟切不切走无关——**那不是读数，是废掉的一趟**。
    throw new Error(`还没点就有骨架了（spine ${base.spine.length} 字 / beats ${base.beats.length} 条）——前提不成立，这一趟作废`)
  }

  console.log(`=== ② 点「智能续写」，**不等任何东西**立刻切走（读那一格花了 ${Date.now() - tType} 毫秒）===`)
  const seen = new Map()
  const t0 = Date.now()
  await clickExact(d, '智能续写', 0, 10)
  const goneMs = await switchAway(d, t0)
  console.log('  第几毫秒真的切走了:', goneMs)
  if (goneMs === null) throw new Error('dispatch 完 8 秒 `current` 还在那一篇上——没真的切走，这一趟作废')
  await d.shot(`${prefix}-切走了.png`)

  console.log('=== ③ 人在别处：一边盯库（判 ④）一边攒 toast（判 ⑤）===')
  // 盯库跟屏幕上开着哪一篇无关（fetch 就是 fetch）。
  let landedMs = null
  let landed = null
  const tEnd = Date.now() + budget
  let doneSeen = false
  while (Date.now() < tEnd) {
    await nap(d, 1600, seen, t0)
    if (landedMs === null) {
      const s = await dbNote(d, aId)
      if (s.spine && s.spine.length) {
        landedMs = Math.round(Date.now() - t0)
        landed = s
        console.log(`  ★ 库里 spine 变非 0 了：第 ${landedMs} 毫秒（${s.spine.length} 字 / ${s.beats.length} 条）`)
      }
    }
    // 收工那句 toast 到了就收摊（**别干等满 budget**）。`onDone` 归 `self`，
    // 切走了它照样发一条——**这一条在这儿只当「跑完了」的信号，判在下面**。
    if ([...seen.keys()].some((t) => t.includes('已保存在那篇里') || t.includes('智能续写已结束'))) {
      doneSeen = true
      await nap(d, 4000, seen, t0)   // 收工那条之后可能还跟着一条，再收 4 秒
      break
    }
  }
  const waitedS = Math.round((Date.now() - t0) / 1000)
  console.log(`  在别处待了 ${waitedS} 秒；收工那条 toast 见到了吗: ${doneSeen}`
    + `（false = 盯满了 ${Math.round(budget / 1000)} 秒还没等到，**不是「跑完了」**）`)
  if (landedMs === null) console.log('  ★ 库里 spine: **一直是 0**（`until` 那一族超时是静默的，等的就是上面那几秒）')

  console.log('=== ④ 还在别处：⌘K 新建一篇**空**笔记 B（P93 实拍「计划 2」那一屏）===')
  await d.key('Escape'); await nap(d, 300, seen, t0)
  await d.key('k', ['meta']); await nap(d, 1000, seen, t0)
  await d.insert('新建笔记'); await nap(d, 900, seen, t0)
  await clickExact(d, '新建笔记', 0, 8)
  await nap(d, 3000, seen, t0)
  const bId = await d.noteId()
  console.log('  新建出来的 note id:', bId, '（**跟 A 不是同一篇**:', bId !== aId, '）')
  console.log('  B 的正文（该是空的）:', JSON.stringify(await d.cmText()))
  if (bId === aId) throw new Error('⌘K 新建出来的还是 A——没真的新建，这一趟作废')
  const bPlan = await readPlan(d, 'B新建空笔记', prefix)

  console.log('=== ⑤ 切回 A ===')
  await d.openNoteById(aId, titleHead)
  await nap(d, 2500, seen, t0)
  const backId = await d.noteId()
  console.log('  切回来开着的是:', backId, '（该是', aId, '）')
  if (backId !== aId) throw new Error('切不回 A——**别拿别的顶**，这一趟作废')
  const aPlan = await readPlan(d, 'A切回来', prefix)
  const fin = await dbNote(d, aId)
  console.log('  A 篇收尾:', JSON.stringify({
    库里正文字数: fin.len,
    '库里 spine 几个字': fin.spine.length,
    '库里 beats 几条': fin.beats.length,
    '编辑器字数（只作参考·docText 只数得到视口里那几行）': ((await docText(d)) ?? '').length,
    状态栏: ((await pageText(d)).match(/\d[\d,]*\s*字/) || [''])[0],
  }))
  await d.shot(`${prefix}-收尾.png`)

  // ── 判 ──────────────────────────────────────────────────────────────────
  console.log('=== 逐条判（**判据一律不变式 / floor，一个会变的数都不钉**）===')

  // 判 ①：P95 轮次卡串台。空笔记 B 上不许有 A 的卡。
  if (bPlan.rounds.length !== 0 || bPlan.wrote !== 0 || /\d/.test(bPlan.tab)) {
    red('[判①·P95 轮次卡串台]',
      `切走之后新建的那篇**空**笔记 B 上，「计划」页签是 ${JSON.stringify(bPlan.tab)}、`
      + `底下有 ${bPlan.rounds.length} 种「第 N 轮」${JSON.stringify(bPlan.rounds)}、`
      + `「本轮写出的正文」出现 ${bPlan.wrote} 次 —— **那是 A 篇的执行记录摆进了 B**（P93 问题 #1 长回来了）`)
  } else green('[判①·P95 轮次卡串台]', `空笔记 B：页签 ${JSON.stringify(bPlan.tab)} 不带数字、0 种「第 N 轮」、0 次「本轮写出的正文」`)

  // 判 ②：切回来不许空。
  if (aPlan.rounds.length < 1) {
    red('[判②·P95 切回来卡没了]',
      `切回 A 之后「计划」底下 0 种「第 N 轮」（页签 ${JSON.stringify(aPlan.tab)}）`
      + ' —— **轮次卡被「换篇就清」清掉了**，那正是 P93 判「不照抄 P17 那两条」的理由')
  } else green('[判②·P95 切回来卡没了]', `切回 A：${aPlan.rounds.length} 种「第 N 轮」${JSON.stringify(aPlan.rounds)}`)

  // 判 ③：P101 `guarded` 误伤。
  //
  // ⚠️ **判据宁可窄**：钉的是「**切走那几秒里写出来的字，卡上留住了**」，
  //    也就是「本轮写出的正文」**至少 1 次**——**不钉「几次」**。
  //    想写成不变式 `次数 == 轮次卡种数` 试过，**那条不成立**：
  //    `skipped_continue` 那种轮次后端根本不发 delta（`cleanupOnly`），卡上本来就没有这一块，
  //    钉了它红的理由跟对错无关（**闸别钉会变的数**那一条）。
  //    这一步跑在 `MEMOKET_RUN_TOKEN_CAP=1` 上 ⇒ **只跑得出一轮**，
  //    而那一轮整个落在「已经切走」那段时间里 ⇒ 在这一档上 `>= 1` 跟那条不变式是同一件事。
  //    两个数都照实打出来，人读得到。
  if (aPlan.rounds.length >= 1 && aPlan.wrote < 1) {
    red('[判③·P101 guarded 误伤]',
      `切回 A 之后 ${aPlan.rounds.length} 种「第 N 轮」${JSON.stringify(aPlan.rounds)}，`
      + '可「本轮写出的正文」**一次都没有** —— 这几轮整个跑在「已经切走」那段时间里，'
      + '丢的就是 `onDelta` 那句 `writeRounds(noteId, … streamed …)`（P99 实拍的 2 → 1，这一档是 1 → 0）')
  } else if (aPlan.rounds.length >= 1) {
    green('[判③·P101 guarded 误伤]', `${aPlan.rounds.length} 种「第 N 轮」/ ${aPlan.wrote} 次「本轮写出的正文」`)
  }

  // 判 ④：P103 骨架永久丢。**比的是两个毫秒数**，不是「第几秒」。
  if (landedMs === null) {
    red('[判④·P103 骨架永久丢]',
      `点完 ${goneMs} 毫秒就切走，之后盯了 ${waitedS} 秒，**库里 \`spine\` 一直是 0**`
      + ' —— 全仓只有 `PUT /api/notes/<id>/skeleton` 一条路能把跑里现生成的骨架写进笔记，'
      + '发它的只有前端 `persistSkeleton` ⇒ **那一次生成的骨架永久没了**')
  } else if (!(goneMs < landedMs)) {
    // **对照组自己得先站得住**：切走要排在落库前面，不然这一趟比的不是「切不切走」。
    red('[判④·P103 骨架永久丢·这一趟作废]',
      `切走在第 ${goneMs} 毫秒，而库里 \`spine\` 第 ${landedMs} 毫秒就变非 0 了`
      + ' —— **切走没赶在落库前面**，这一趟量的不是「切走之后还落不落库」。'
      + '把假模型的 `LLM_DELAY_MS` 调大，或者检查 `--mode` 是不是 `adv`（`ok` 档不回骨架 JSON）')
  } else green('[判④·P103 骨架永久丢]',
    `切走第 ${goneMs} 毫秒 → 库里 \`spine\` 第 ${landedMs} 毫秒变非 0（${landed.spine.length} 字 / ${landed.beats.length} 条）`)

  // 判 ⑤：P103 停机的理由丢。**既点名、又带理由**。
  const named = [...seen.entries()].filter(([t]) => NAMED_RE.test(t))
  const hit = named.filter(([t]) => COST_WORDS.every((w) => t.includes(w)))
  if (hit.length < 1) {
    red('[判⑤·P103 停机理由丢]',
      `切走之后攒到 ${seen.size} 条 toast，点了名的 ${named.length} 条，`
      + `**没有一条同时带着停机的理由**（要 ${JSON.stringify(COST_WORDS)} 都在）`
      + ' —— `onCost` 要么被整条拦掉（用户一个字看不到「为什么只跑了这几轮、花了多少」），'
      + '要么那句 `awayToast` 不点名了（屏幕上开着 B，这句话会被读成 B 的事）。'
      + `攒到的逐条：${JSON.stringify([...seen.keys()])}`)
  } else {
    green('[判⑤·P103 停机理由丢]', `点了名又带理由的 ${hit.length} 条：${JSON.stringify(hit.map(([t, ms]) => ({ 毫秒: ms, 字: t })))}`)
    // ⚠️ **「点了名」≠「点对了名」**（P107 A 升级：**判**，不再只是照实记）。
    //
    // 钉的是**这一趟自己的标题记号**开头（`「P107切走S…`）：那篇是这一步现造的、
    // 名字打在正文 `# …` 那一行里（库里 `title` 是 `''`）——P105 实拍这一格 **0 条对得上 / 1 条「另一篇笔记」**；
    // P107 **只加 ref 那一版真壳上照样 0 / 1**（两半的洞只补了一半），加上 `displayTitle` 之后
    // 这一格该是 **≥ 1 条对得上**。**不钉「全部对得上」**：`onDone` 收工那条走的是另一句
    // （`「…」的智能续写已结束`，不带停机理由，`hit` 里本来就没有它）。
    const right = hit.filter(([t]) => t.startsWith(`「${titleHead}`)).length
    const stale = hit.filter(([t]) => t.startsWith('「另一篇笔记」')).length
    if (right < 1) {
      red('[判⑤·P107 点对了名]',
        `点了名又带理由的 ${hit.length} 条里，对得上这一趟标题记号「${titleHead}」的 **0 条**，`
        + `读成「另一篇笔记」的 ${stale} 条 —— 篇名读的是 handler 建起来那一刻的 \`notes\` 闭包`
        + '（P103 问题 #6 / P105 问题 #7 那个洞长回来了）：屏幕上开着 B，这句话说的是哪一篇用户看不出来。'
        + `点的名逐条：${JSON.stringify(hit.map(([t]) => t.slice(0, 40)))}`)
    } else {
      green('[判⑤·P107 点对了名]',
        `对得上这一趟标题记号「${titleHead}」的 ${right} 条 / 读成「另一篇笔记」的 ${stale} 条`)
    }
  }

  console.log('=== 第 ⑫ 步并排 ===')
  console.log('  ', JSON.stringify({
    A篇: aId,
    B篇: bId,
    第几毫秒切走的: goneMs,
    '★库里 spine 第几毫秒变非 0（null = 一直是 0）': landedMs,
    在别处待了几秒: waitedS,
    收工那条见到了吗: doneSeen,
    B新建空笔记: { 页签: bPlan.tab, 几种轮次卡: bPlan.rounds.length, 本轮写出的正文: bPlan.wrote },
    A切回来: { 页签: aPlan.tab, 几种轮次卡: aPlan.rounds.length, 本轮写出的正文: aPlan.wrote },
    攒到几条toast: seen.size,
    点了名的几条: named.length,
    判不过几条: reds.length,
  }))

  if (reds.length) {
    throw new Error(`第 ⑫ 步判不过 ${reds.length} 条：\n    ` + reds.join('\n    '))
  }
  console.log('OK: 第 ⑫ 步五条判据全过（P95 串台 / P95 切回来 / P101 误伤 / P103 骨架 / P103 停机理由 + P107 点对了名）')
}
