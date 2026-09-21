// P58 · 第九次全流程走查（老用户）第二趟：⑥⑦⑩（前半）
//   ⑥ 智能续写 → 轮次卡片 → **读库**（P45 #1 / P44 问题 #1 的回归）
//   ⑦ 导回到 Obsidian（浅走）
//   ⑩ 改动层：润色生一层 → 右栏「改动」页签 → 库里真有那一行（关掉重开在下一趟）
import { clickExact } from './clickexact.mjs'
import { selectLineAndRightClick } from './ctxmenu52.mjs'
import { docText, pageText, toasts, until, wait } from './lib.mjs'
import { USER } from '../whoami.mjs'

async function dbContent(d, id) {
  return d.eval(`(async () => {
    const u = ${USER}
    const r = await fetch('/api/notes/${id}', { headers: { 'X-User-Id': u } })
    const j = await r.json()
    return { len: (j.content || '').length, json: /\\{"text":|"reason": "假模型"/.test(j.content || '') }
  })()`)
}
async function layers(d, id) {
  return d.eval(`(async () => {
    const u = ${USER}
    const r = await fetch('/api/notes/${id}/change-layers', { headers: { 'X-User-Id': u } })
    return JSON.stringify(await r.json()).slice(0, 400)
  })()`)
}

export default async function (d, [noteId]) {
  await d.setTheme('light'); await wait(400)
  await d.openNoteById(noteId, 'P58 走查')
  await wait(2000)
  console.log('开着的是:', await d.noteId())

  console.log('=== ⑥ 智能续写 → 轮次卡片 → 读库 ===')
  const before = await docText(d)
  console.log('  跑之前：编辑器', before.length, ' 库', JSON.stringify(await dbContent(d, noteId)))
  await clickExact(d, '智能续写', 0, 10)
  await wait(2000)
  // **判「跑完了」不能用「完成」两个字**：这一页上本来就有「完成标准」，
  // 第一轮还没开始就命中 —— 上一趟「+0 字 / 1 轮」的读数有一半是这么来的。
  // 认收工那一行自己的措辞（`· N 轮 ·`），它只在 RUN_FINISHED 之后才出现。
  await until(async () => {
    const t = await pageText(d)
    return /· \d+ 轮 ·/.test(t) ? t : null
  }, 300000, 2000)
  await wait(3000)
  // **P66：读之前先把 `<details>` 摊开**。P62 把这条收进了 `cdp.mjs`（`d.expandDetails()`）
  // 和 `rounds60.mjs`，**这一份没跟上** —— 于是这一格在 P58 / P60 / P62 三批里
  // 照旧读回 `[]`（「⚑ 判据那几行」「收工那行」全是空的）。
  // 那不是「这几句没了」，是**没摊开**：收着的 `<details>` 里的字 `innerText` 读不到。
  console.log('  摊开了', await d.expandDetails(), '个折叠块')
  await wait(600)
  const after = await docText(d)
  const right = await d.eval(`(() => { const el = document.querySelector('.pane-body, [class*="pane"] [class*="body"]'); return el ? el.innerText : document.body.innerText })()`)
  const n = (s) => right.split(s).length - 1
  console.log('  跑完：编辑器', after.length, '（+', after.length - before.length, '）')
  console.log('  库:', JSON.stringify(await dbContent(d, noteId)), '← len 该跟编辑器一样、json 该是 false')
  console.log('  「照它改的」', n('照它改的'), '次；「判词就是下面」', n('判词就是下面'), '次；空括号「（）」', n('（）'), '次（该 0）')
  const t = await pageText(d)
  console.log('  「这一次不再往下写了」:', t.includes('这一次不再往下写了'), ' 「照常打分」:', t.includes('照常打分'))
  console.log('  收工那行:', JSON.stringify((t.match(/[^\n]*(正文没有改动|落进正文|收工)[^\n]*/g) || []).slice(0, 3)))
  console.log('  ⚑ 判据那几行:', JSON.stringify((right.match(/[^\n]*(代码判据|判据)[^\n]*/g) || []).slice(0, 8)))
  console.log('  「照常打分」出现:', n('照常打分'), '次；「没再花模型调用去打分」出现:', n('没再花模型调用去打分'), '次')
  console.log('  「当提醒看」出现:', n('当提醒看'), '次')
  console.log('  垃圾尾巴那条:', JSON.stringify((right.match(/[^\n]*硬贴了一句[^\n]*/) || [])[0]))
  console.log('  残骸编号那条:', JSON.stringify((right.match(/[^\n]*查不到[^\n]*/) || [])[0]))
  console.log('  正文里还有「做爰片」吗（该 false）:', (after || '').includes('做爰片'))
  console.log('  正文里还有「[terrence-8F6]」吗（该 false）:', (after || '').includes('terrence-8F6'))
  await d.shot('p70-b2d-old-rounds-light.png')

  // ⑩ **P89 A 把这一格重写了一遍**。P87 问题 #2（「P85 印到『改了 1 处』、P87 印到
  // `undefined`，而库里那一层两批逐字节相同 ⇒ 差的是右栏刷没刷到」）的真根因**不在产品上**：
  //
  //  ① 假模型那一侧，润色这一发（`/api/rewrite`）**在每个 mode 里都落到最后那个 `else`**，
  //     回的是 `REPORT`（一段 markdown）。后端 `extract_json` 当场 `None` →
  //     `revisions: []` + `unparsed: true` + **HTTP 200**（P87 记的那个 200 是真的，
  //     但 200 ≠ 落了一层）。**这一格自称的「润色生一层」一次都没成立过。**
  //  ② 于是下面这个 `until(文档变了)` **每一趟都干等满 120 秒**，而 `until` 超时
  //     **静默回 `null`** —— 日志上「落地了」和「等了两分钟没等到」长得一模一样。
  //  ③ 等满的这 123 秒里后台一直在动（健康轮询 30s、停顿 8 秒的后台骨架、
  //     改动层 1.6s 防抖落库），于是印出来的**其实是 ⑥ 留下的残留**，
  //     P85 印到 1、P87 印到 0 —— 两个数都不是这一格自己做出来的。
  //
  // 改法：假模型认得出这一发了（`walkthrough_fakellm._system_text` + `edit_json`，
  // 只在选中那一段**前面**加 8 个字的记号），这一格于是能把三件事各自量成一个数：
  // **正文真长了几个字** / **等到了还是等超时** / **改动条、页签、编辑器高亮是不是同一份判据**。
  console.log('=== ⑩ 改动层：润色生一层 ===')
  const lines = await d.eval(`Array.from(document.querySelectorAll('.cm-content .cm-line')).map((l, i) => [i, (l.textContent||'').slice(0, 18)])`)
  const idx = (lines.find(([, s]) => s.includes('预热名单')) || lines.find(([i]) => i === 4) || [4])[0]
  console.log('  在第', idx, '行上右键「润色」')
  const doc0 = await docText(d)
  await selectLineAndRightClick(d, idx)
  await clickExact(d, '润色', 0, 10)
  // **超时不许静默**（P89 A ②）：`until` 回 null 就是「等了 120 秒没等到」，
  // 跟「等到了」必须在日志上分得开——这两件事下一批还要拿来逐行 diff。
  const t0 = Date.now()
  const landed = await until(async () => (await docText(d)) !== doc0, 120000, 800)
  const waited = Math.round((Date.now() - t0) / 1000)
  await wait(3000)
  const doc1 = await docText(d)
  console.log('  正文字数:', doc0.length, '→', doc1.length, `（${doc1.length - doc0.length >= 0 ? '+' : ''}${doc1.length - doc0.length}）`)
  console.log('  文档变了吗:', !!landed, `（等了 ${waited} 秒；false = 干等超时，不是「润色落地了」）`)
  // 「看到 ≠ 真在正文里」：假模型只在选中那一段前面加了 8 个字的记号，那就去正文里数它。
  console.log('  假模型那一段落地了吗（记号「（假模型润色过）」几处，该 1）:', (doc1.match(/（假模型润色过）/g) || []).length)
  console.log('  toast:', JSON.stringify(await toasts(d)))
  const t2 = await pageText(d)
  const bar = (t2.match(/[^\n]*改了 (\d+) 处[^\n]*/) || [])
  const tabs = await d.texts('.pane-tab', 12)
  // **编辑器那一头自己说一次**。`.harness-ins` 是 `editor/roundDiff.build()`
  // 给每一处新增打的那个类，不是量具自己造的名字。
  //
  // ⚠️ **它是「段」不是「处」**（P89 A 当场量错过一次，照实记）：CodeMirror 把跨行的
  // `Decoration.mark` **按行切成一个 span**，空行那一段宽度为 0、**一个 span 都不出**。
  // 这一趟实测 9 段 = ⑥ 那一处 ins 的 **8 个非空行** + ⑩ 润色那一处的 1 行，
  // 而「处」数是 2。**拿段数去等处数就是拿两把尺当一把用**，那正是这一格
  // 原来那个毛病的同族。所以下面**只钉得准的那一条**：
  //   · `改动条的数 == 页签角标的数` —— 两处读的是同一个 `pendingDiff`，飘开就是产品的事；
  //   · 高亮**有 / 没有**跟处数**有 / 没有**同步（两个方向都判）——
  //     「页签摆着 N 处、正文里一处都没标出来」是 P43 #1 真要拦的那件事。
  const ins = await d.eval(`document.querySelectorAll('.harness-ins').length`)
  const barN = bar[1] ? Number(bar[1]) : 0
  const tabN = Number((tabs.find((s) => /^改动/.test(s)) || '').replace(/\D+/g, '') || 0)
  console.log('  改动条:', JSON.stringify(bar[0]))
  console.log('  右栏页签:', JSON.stringify(tabs))
  console.log('  编辑器里的新增高亮 .harness-ins:', ins, '段（**段 ≠ 处**：CM 把跨行的 mark 按行切开，空行不出 span）')
  console.log('  P43 #1 ①（改动条 == 页签角标，同一个 pendingDiff）:', barN === tabN, `{条 ${barN} · 角标 ${tabN}}`)
  console.log('  P43 #1 ②（有处数就该有高亮、没处数就不该有，两个方向）:', (barN > 0) === (ins > 0), `{处 ${barN} · 段 ${ins}}`)
  console.log('  库里的层:', await layers(d, noteId))
  await d.shot('p70-b2d-old-layer-light.png')

  console.log('=== ⑦ 导回到 Obsidian ===')
  await d.key('Escape'); await wait(300)
  await d.key('k', ['meta']); await wait(1000)
  await d.insert('导回'); await wait(1000)
  await clickExact(d, '导回到 Obsidian / Notion / 飞书…', 0, 10).catch((e) => console.log('  ⌘K 里没点到:', e.message))
  await wait(2500)
  const t3 = await pageText(d)
  console.log('  面板在吗:', t3.includes('Obsidian'))
  for (const s of ['vault', '树的层级变成文件夹', '克隆写成 .link.txt', '_assets/']) {
    console.log(`  逐字「${s}」:`, t3.includes(s))
  }
  console.log('  「导回 N 篇」:', JSON.stringify((t3.match(/导回 \d+ 篇/) || [])[0]))
  await d.shot('p70-b2d-old-export-light.png')
  console.log('  toast:', JSON.stringify(await toasts(d)))
}
