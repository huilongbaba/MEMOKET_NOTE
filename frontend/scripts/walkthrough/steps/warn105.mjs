// **轮次卡上那一格「这一轮少了什么」的实拍**（P105 C，收 P103 问题 #7）。
//
// ── P103 逐字留下来的那一条 ───────────────────────────────────────────────
//   > `onWarning` 被拦掉之后，**「这一轮少了哪个能力」在界面上就没有第二个出处了**
//   > （轮次卡上没有这一格）。要接就得先给轮次卡加一格——**那是另一刀**。
//
// 这一份是那一刀的**用户那一头**：真壳、真后端、真事件，屏幕上那几个字。
//
// ── 怎么逼出一条 warning（**不靠模型出错**）───────────────────────────────
// `hooks/note.skeleton` 跑一遍 `store.truncated_beats(self.beats)`：
// **存着的骨架里有一条正好 60 字、又不以句读收尾** ⇒ 当场发一条 `warning`
//（「这篇存着的骨架第 N 条是半句…」）。真库里现在还有 5 篇是这样的。
// ⇒ 这一份**自己造一篇这样的**（`PUT /api/notes/<id>/skeleton`，**写完读回来再断言**），
//   于是必来一条，**一次模型故障都不用等**。
// ⚠️ **它是「开跑之前」那一发，不是每一轮一发**：`hooks.skeleton` 是 router 在
//    `loop.run` **之前**跑完的（`middleware/cost.py` 抬头逐字写着）。
//    实拍：点完第 412 毫秒那条 toast 就弹了，而那一刻**一张轮次卡都还没有**。
//    第一版的 `onWarning` 写的是 `if (!rs.length) return rs`（抄 `onError` 的形状），
//    于是那一条**当场被丢掉**，卡上那一格一处都没有——这份探针第一趟红的正是这个。
//
// ⚠️ **骨架得存在库里、而且前端得读到**：`api.runNoteHarness(…, spine, beats, …)`
//    发的是**前端内存里那份**。所以这一步先按 API 造好、**再 `openNoteById` 开进来**
//    ——反过来（先开着再写库）前端内存里还是空的，那一趟 `self.beats` 是空的，
//    走的是「现生成一份骨架」那一支，**一条 warning 都不会有**（量具够不着）。
//
// ── 五条判据，逐条钉的是哪一件事 ─────────────────────────────────────────
// | 判 | 钉的 | 判据（**一个会变的数都不钉**） |
// |---|---|---|
// | ① | 前提站得住 | 库里那一篇的 beats 里**真有一条正好 60 字且不以句读收尾**（写完读回来） |
// | ② | **没切走的时候它是弹的**（对照） | 点完之后那几秒里，toast 里有一条逐字带「本轮少了这个能力」 |
// | ③ | **切走之后一个字都不弹**（P103 B ③ 判的那半边**没变**）| 切走那段时间里攒到的 toast 并集里，带那句话的**恰好 0 条** |
// | ④ | **P105 C 那一格在**（P103 问题 #7 的正面）| 切回来右栏「计划」上有「本轮少了 N 个能力」+ 那条原话 |
// | ⑤ | **切走再切回之后那一格还在** | 那一格是**按 noteId 记的**（`writeRounds(noteId, …)`），切出去 45 秒再回来照样在卡上 |
//
// ── 它**够不着**什么 ─────────────────────────────────────────────────────
//  1. **关掉重开之后那一格还在不在**：不在——这一格不落库。
//     `store.ROUND_SKELETON_MISSING` 里逐字写着「本轮少了哪个能力」，
//     读回来的卡会照实标。那一格归 `steps/rounds101.mjs` 的射程。
//  2. **别的 middleware 抛异常那一族**：这一份只造得出「骨架存着半句」这一种
//     （`loop._fire` 那条要一条 middleware 真抛异常）。形状那一半在
//     `src/components/__tests__/p105.test.tsx`（一轮两条、同一步两条…）。
//  3. **它不判「几轮」**：跑几轮跟着后端策略和假模型走。
//  4. ⚠️ **「切走那几秒里到的那条 warning 记不记得住」这一档它够不着**：
//     这一份唯一造得出的那条（骨架存着半句）**在开跑之前就到了**
//     ——`hooks.skeleton` 是 router 在 `loop.run` **之前**跑完的
//     （`middleware/cost.py` 抬头逐字写着），实拍是第 412 毫秒，而切走发生在那之后；
//     而且**整次跑只来这一条**，切走的那 45 秒里一条都没有。
//     所以判 ⑤ 钉的是**「切走再切回之后那一格还在」**（按 noteId 记的那一半），
//     「切走那一刻到的也记得住」那一半由 `scripts/check-harness-guard.mts`
//     第 ④ 条从源码那头钉（记账那一句排在 guard 前面）。**别把这两件事混成一句。**
//
// ⚠️ **跑它要 `LLM_MODE=adv` + `LLM_DELAY_MS` 给几秒**：`--mode ok` 一两秒就跑完，
//    「切走」在那种速度上演不出来（P97 那条「量具最早能到场就已经晚了」）。
// ⚠️ **别设 `MEMOKET_RUN_TOKEN_CAP=1`**：设了第一轮末尾就停，这一趟量的是「一轮的跑」，
//    而这一格该在**一次真跑几轮**的那一屏上看得见（实拍 3 轮）。
//
//   node cdp.mjs <port> steps/warn105.mjs <截图名前缀> [切走之后盯多久毫秒]
import { clickExact } from './clickexact.mjs'
import { pageText, until, wait } from './lib.mjs'
import { USER } from '../whoami.mjs'

/** 那一条半句节拍：**正好 60 个字**、结尾不是句读（`store.truncated_beats` 的判据）。 */
// （**60 这个数是后端 `store.LEGACY_BEAT_MAX`**，不是随手挑的；
//  少一个字这条探针就哑了，所以判 ① 先把长度读回来断言一次。）
const HALF = '先把众筹那一版文案是谁写的、按什么口径改的、改完之后点击和退款分别怎么动的说清楚，再把预热名单按三个渠道各自拆一遍并将问'

/** 卡上那一格里必然出现的两句（`AgentActivity.warningsHead` / `warningLine`）。 */
const HEAD_RE = /本轮少了 (\d+) 个能力/
const SAYS = '本轮少了这个能力'

const SEED = [
  'P105 C：轮次卡上那一格「这一轮少了什么」的实拍。',
  '这一篇的骨架里存着一条半句节拍，于是每一轮后端都会发一条 warning。',
  '众筹页面那一版文案是 3 月 12 号上线的，当天点击 12700，退款率 1.8%。',
]

async function api(d, path, init = null) {
  return d.eval(`(async () => {
    const r = await fetch(${JSON.stringify(path)}, {
      ...${JSON.stringify(init ?? {})},
      headers: { 'X-User-Id': ${USER}, 'Content-Type': 'application/json' },
    })
    return { status: r.status, body: await r.json().catch(() => null) }
  })()`)
}

/** toast 收一次，**并集**，每条只记第一次出现在第几毫秒（P97 那条：toast 活几秒就没）。 */
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

/** 等一段，**每 400 毫秒收一次 toast**。这一步里所有的「等」都走这一条。 */
async function nap(d, ms, seen, t0) {
  const end = Date.now() + ms
  for (;;) {
    await pump(d, seen, t0)
    const left = end - Date.now()
    if (left <= 0) return
    await wait(Math.min(400, left))
  }
}

/** 右栏「计划」那一格这一刻的样子（点进去 + 摊开折叠块再读）。 */
async function readPlan(d, tag, shotPrefix) {
  const tabs = await d.eval(`Array.from(document.querySelectorAll('.pane-tab')).map((e) => {
    const r = e.getBoundingClientRect()
    return { t: (e.textContent||'').replace(/\\s+/g,' ').trim(), cx: r.x + r.width/2, cy: r.y + r.height/2 }
  })`)
  const plan = tabs.find((x) => x.t.startsWith('计划'))
  if (!plan) throw new Error('「计划」那一格不在条上——**选不到 ≠ 没有**，先去读 App.tsx 的 tabs')
  await d.clickAt(plan.cx, plan.cy)
  await wait(800)
  await d.eval(`(() => { for (const e of document.querySelectorAll('.right-pane-body details')) e.open = true })()`)
  const body = await d.eval(`(document.querySelector('.right-pane-body')?.innerText ?? null)`)
  if (body === null) throw new Error('`.right-pane-body` 整个选不到——右栏没渲染出来')
  const flat = body.replace(/\s+/g, ' ').trim()
  const rounds = [...new Set(flat.match(/第 \d+ 轮/g) || [])]
  console.log(`  [${tag}]`, JSON.stringify({
    '「计划」页签逐字': plan.t,
    几种轮次卡: rounds.length,
    轮次卡: rounds,
    '「本轮少了 N 个能力」出现几次': (flat.match(/本轮少了 \d+ 个能力/g) || []).length,
    '底下头 240 字': flat.slice(0, 240),
  }))
  await d.shot(`${shotPrefix}-${tag}-计划.png`)
  return { tab: plan.t, rounds, flat }
}

/** 切到 ⌘K 那种虚拟页。回「第几毫秒真的切走的」——
 *  **`d.noteId()` 不是「现在开着哪一篇」**（它读 localStorage 里上次那一篇）。 */
async function switchAway(d, t0) {
  await d.key('Escape'); await wait(150)
  await d.eval(`window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'app:journey' }))`)
  return until(async () => {
    const st = await d.eval(`(() => ({
      tab: (document.querySelector('.note-tab.active')?.textContent ?? '').trim(),
      cm: !!document.querySelector('.cm-content'),
    }))()`)
    return (st.tab.startsWith('屏幕活动') && !st.cm) ? Math.round(Date.now() - t0) : null
  }, 8000, 100)
}

export default async function (d, [shotPrefixRaw, budgetRaw]) {
  const prefix = shotPrefixRaw || 'p105-warn'
  const budget = Number(budgetRaw || 60000)
  const reds = []
  const red = (tag, why) => { reds.push(`${tag} ${why}`); console.log(`  ❌ ${tag} ${why}`) }
  const green = (tag, what) => console.log(`  ✅ ${tag} ${what}`)

  await d.setTheme('light'); await wait(400)
  await until(async () => await d.exists('.cm-content'), 30000)
  await wait(1200)

  console.log('=== ① 按 API 造一篇「骨架里存着半句」的笔记（**写完读回来再断言**）===')
  const nonce = 'W' + Date.now().toString(36).slice(-6)
  const titleHead = `P105少了什么${nonce}`
  const made = await api(d, '/api/notes', {
    method: 'POST',
    body: JSON.stringify({
      title: `${titleHead}（可删）`,
      content: `# ${titleHead}（可删）\n\n${SEED.join('\n\n')}\n`,
      parent_note_id: 'root',
    }),
  })
  const nid = made.body?.id
  console.log('  建出来的 note id:', nid, ' HTTP', made.status)
  if (!nid) throw new Error('建不出来那一篇——别往下跑')
  await api(d, `/api/notes/${nid}/skeleton`, {
    method: 'PUT',
    body: JSON.stringify({ spine: '把「谁来付钱」这条线单独说清楚。', beats: ['先交代这一版文案的来历。', HALF] }),
  })
  // **「我发了一条 PUT」≠「库里现在是那个值」**（P87 / P89 那一课）：读回来再断言。
  const back = await api(d, `/api/notes/${nid}`)
  const beats = back.body?.beats ?? []
  const half = beats.map((b, i) => [i + 1, b.length, /[。！？；.!?;」”")）]$/.test(b)])
    .filter(([, n, end]) => n === 60 && !end)
  console.log('  读回来的 beats:', JSON.stringify(beats.map((b) => b.length)), ' 半句的那几条:', JSON.stringify(half))
  if (!half.length) {
    red('[判①·前提]', `库里那一篇的 beats 里**没有一条正好 60 字且不以句读收尾**（读回来的长度 ${JSON.stringify(beats.map((b) => b.length))}）`
      + ' —— 后端那条 `truncated_beats` 压根不会响，这一趟量的不是「少了能力」而是量具够不着')
    throw new Error('前提不成立，这一趟作废：' + reds.join('；'))
  }
  green('[判①·前提]', `库里那一篇第 ${half.map(([i]) => i).join('/')} 条正好 60 字、不以句读收尾`)

  console.log('=== ② 开进来（**先写库再开**，前端内存里那份骨架才是库里那份）===')
  await d.openNoteById(nid, titleHead)
  await wait(2000)
  const planBefore = await readPlan(d, '开进来还没跑', prefix)
  if (!planBefore.flat.includes('并将问')) {
    red('[判①b·前端读到了吗]', '右栏「计划」里找不到那条半句节拍的尾巴「并将问」'
      + ' —— 前端内存里那份骨架不是库里那份，这一跑不会带上它')
  } else green('[判①b·前端读到了吗]', '右栏「计划」上摆着那条半句节拍')

  console.log('=== ③ 点「智能续写」，**先不切走**：这几秒里它该弹那句红字（对照）===')
  const seenNear = new Map()
  const t0 = Date.now()
  await clickExact(d, '智能续写', 0, 10)
  await nap(d, 12000, seenNear, t0)
  const nearHit = [...seenNear.keys()].filter((t) => t.includes(SAYS))
  if (!nearHit.length) {
    red('[判②·没切走时它是弹的]', `点完盯了 12 秒，攒到 ${seenNear.size} 条 toast，`
      + `**没有一条带「${SAYS}」**：${JSON.stringify([...seenNear.keys()])}`
      + ' —— 要么后端没发那条 warning（去看假模型的 mode / 那条半句还在不在），'
      + '要么 `onWarning` 那句 toast 没了')
  } else green('[判②·没切走时它是弹的]', `${nearHit.length} 条：${JSON.stringify(nearHit)}`)
  await d.shot(`${prefix}-没切走就弹了.png`)

  console.log('=== ④ 切走，一边盯 toast（判 ③：切走之后一个字都不许弹）===')
  const seenAway = new Map()
  const tAway = Date.now()
  const goneMs = await switchAway(d, tAway)
  console.log('  第几毫秒真的切走了:', goneMs)
  if (goneMs === null) throw new Error('dispatch 完 8 秒 `current` 还在那一篇上——没真的切走，这一趟作废')
  await nap(d, budget, seenAway, tAway)
  const awayHit = [...seenAway.keys()].filter((t) => t.includes(SAYS))
  console.log(`  在别处待了 ${Math.round((Date.now() - tAway) / 1000)} 秒，攒到 ${seenAway.size} 条 toast：`
    + JSON.stringify([...seenAway.keys()]))
  if (awayHit.length) {
    red('[判③·切走之后不许弹]', `切走那段时间里弹了 ${awayHit.length} 条「${SAYS}」：${JSON.stringify(awayHit)}`
      + ' —— P103 B ③ 判的是「切走之后照拦」（跑还在继续、用户这一刻做不了任何事，'
      + '而且一轮能来好几条 ⇒ 是噪声不是通知）。这一批只该动「记」那一半')
  } else green('[判③·切走之后不许弹]', `攒到 ${seenAway.size} 条 toast，带「${SAYS}」的 **0 条**`)

  console.log('=== ⑤ 切回来：卡上那一格在不在 ===')
  await d.openNoteById(nid, titleHead)
  await wait(2500)
  const plan = await readPlan(d, '切回来', prefix)
  await d.shot(`${prefix}-收尾.png`)

  const heads = [...plan.flat.matchAll(/本轮少了 (\d+) 个能力/g)]
  if (!heads.length) {
    red('[判④·那一格在吗]', '切回来右栏「计划」上**一句「本轮少了 N 个能力」都没有**'
      + `（卡 ${plan.rounds.length} 种：${JSON.stringify(plan.rounds)}）`
      + ' —— P103 问题 #7 那条还没被收：`onWarning` 的账没记在卡上')
  } else if (!plan.flat.includes('并将问')) {
    red('[判④·那一格在吗]', '抬头在，可**那条原话不在**（找不到「并将问」）'
      + ' —— 只摆了个数，用户还是不知道少的是哪一步、为什么')
  } else green('[判④·那一格在吗]', `${heads.length} 处「本轮少了 N 个能力」，逐条原话也在`)

  // 判 ⑤：**切走再切回之后那一格还在**（这一格是按 noteId 记的）。
  // 判法：按「第 N 轮」把右栏那段字切成段，看带抬头的那几段是第几轮——
  // **照实打出来，不钉「第几轮」**（那条 warning 在开跑之前就到，落在第 1 轮那张卡上；
  // 哪一轮是后端什么时候发那条事件说了算，钉它就是钉一个会变的数）。
  const marks = [...plan.flat.matchAll(/第 (\d+) 轮/g)]
  const withHead = []
  marks.forEach((m, i) => {
    const seg = plan.flat.slice(m.index, i + 1 < marks.length ? marks[i + 1].index : plan.flat.length)
    if (HEAD_RE.test(seg)) withHead.push(Number(m[1]))
  })
  console.log('  带那一格的是第几轮:', JSON.stringify(withHead), ' 一共几轮:', JSON.stringify(marks.map((m) => Number(m[1]))))
  if (!withHead.length) {
    red('[判⑤·切走再切回之后那一格还在]',
      `右栏上 ${marks.length} 段「第 N 轮」，**没有一段带着那一格**`
      + ' —— 要么那一格根本没挂在卡上（它是按 noteId 记的，切回来该跟着回来），'
      + '要么切走那一下把这一篇的卡整叠清了（P93 那条「换篇就清」长回来）')
  } else green('[判⑤·切走再切回之后那一格还在]', `第 ${withHead.join('/')} 轮的卡上有那一格`
    + `（切出去 ${Math.round(budget / 1000)} 秒再回来，照实记：那条 warning 在开跑之前就到）`)

  console.log('=== C 并排 ===')
  console.log('  ', JSON.stringify({
    那一篇: nid,
    第几毫秒切走的: goneMs,
    没切走那几秒弹了几条: nearHit.length,
    切走那段弹了几条: awayHit.length,
    切走那段一共几条toast: seenAway.size,
    卡上那一格几处: heads.length,
    带那一格的是第几轮: withHead,
    一共几种轮次卡: plan.rounds.length,
    判不过几条: reds.length,
  }))

  if (reds.length) throw new Error(`C 这一步判不过 ${reds.length} 条：\n    ` + reds.join('\n    '))
  console.log('OK: C 五条判据全过（前提 / 没切走弹 / 切走不弹 / 那一格在 / 切回来还在）')
}
