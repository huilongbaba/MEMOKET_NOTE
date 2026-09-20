// P66 A：**advisory / judge_floor 两档在壳上摆出来**（P62 ③ 的后半）。
//
// P62 已经在判据侧摆出来了（`adv62.py`：真中间件、真判据链），壳上差的那一步是
// **让那一跑活过第 2 轮**：手上没材料时 `material_used_up`（`modes.py:61`）第 2 轮就收工，
// 而 `citations_present` 的第一行是 `if ... not st.facts: return None` ——
// **没有材料，advisory 那一档连看都不会被看一眼**。
// `fakellm64.py` 在带 `tools` 的那一发上回**每轮不同的 `search_memory`**，
// 事实文本由真知识库给，`dry_rounds` 因此每轮归零。
//
// 判据（界面上的字，逐字来自 `AgentActivity.tsx:548-552`）：
//   advisory     → 「代码判据 … 提了…上的一件事…但没有拦这一轮——分照常打，这条当提醒看。」
//   judge_floor  → 「…已经连着 N 轮没真打过分了，这一轮不再拦、照常打分。」
//   短路那一档   → 「…判了…不合格…这一轮没再花模型调用去打分。」（**反例**，两档都不许长这样）
//
// usage: adv64.mjs <seed 标题> <截图前缀>
import { clickExact } from './clickexact.mjs'
import { docText, pageText, until, wait } from './lib.mjs'

export default async function (d, [tag, shot]) {
  await until(async () => (await pageText(d)).length > 50, 30000)
  await wait(1500)
  await d.setTheme('light'); await wait(500)

  // —— 新建一篇干净的笔记：`content_at_start` 短，`st.fresh` 就是这一轮写的那一段 ——
  await d.key('Escape'); await wait(300)
  await d.key('k', ['meta']); await wait(1000)
  await d.insert('新建笔记'); await wait(900)
  await clickExact(d, '新建笔记', 0, 8)
  await wait(3000)
  const noteId = await d.noteId()
  console.log('新建出来的:', noteId)
  await d.focusEditor()
  await d.insert('# ' + tag); await d.key('Enter'); await d.key('Enter')
  await d.insert('把 EVT 这一阶段的口径、责任人、判据三件事写清楚。')
  await d.key('Enter'); await d.key('Enter')
  await wait(2500)
  const before = await docText(d)
  console.log('跑之前 编辑器:', (before ?? '').length)

  await clickExact(d, '智能续写', 0, 10)
  await wait(2000)
  await until(async () => (/· \d+ 轮 ·/.test(await pageText(d)) ? true : null), 300000, 2000)
  await wait(4000)
  const after = await docText(d)
  console.log('跑完 编辑器:', (after ?? '').length, '（+', (after ?? '').length - (before ?? '').length, '）')

  // **读之前先把 `<details>` 摊开**（P62 收口 5）：判据那几行就在里头，
  // 收着的时候 `innerText` 读不到 —— P58 / P60 两批读回来都是 `[]`。
  const opened = await d.expandDetails()
  console.log('摊开了', opened, '个折叠块')
  await wait(800)

  // **逐条把 ⚑ 那几行打出来**，别只数次数。
  // 「选到两个 ≠ 真有两个」（P62 ①）：一个通配的计数读回来是什么形状，
  // 跟「产品里真的有几条」是两件事 —— 所以这里既数、也把每一条的原文摆出来。
  const flags = await d.eval(`(() => {
    return Array.from(document.querySelectorAll('p'))
      .map((e) => (e.innerText || '').replace(/\\s+/g, ' ').trim())
      .filter((s) => s.startsWith('⚑'))
  })()`)
  console.log('--- ⚑ 逐条（' + flags.length + ' 条）---')
  flags.forEach((s, i) => console.log(`  [${i + 1}] ${s.slice(0, 230)}`))

  const t = await pageText(d)
  const a = t
  const n = (s) => a.split(s).length - 1
  console.log('--- 收工那一行 ---', JSON.stringify((t.match(/[^\n]*· \d+ 轮 ·[^\n]*/g) || []).slice(0, 3)))
  console.log('=== 三档各几条（第三档是反例）===')
  const adv = n('但没有拦这一轮——分照常打，这条当提醒看。')
  const floorLines = (a.match(/已经连着 \d+ 轮没真打过分了，这一轮不再拦、照常打分。/g) || [])
  const short = n('这一轮没再花模型调用去打分。')
  console.log('  advisory  「但没有拦这一轮——分照常打，这条当提醒看。」:', adv, '条')
  console.log('  judge_floor「已经连着 N 轮没真打过分了…」:', floorLines.length, '条', JSON.stringify(floorLines))
  console.log('  短路（反例）「这一轮没再花模型调用去打分。」:', short, '条')
  console.log('  「代码判据 … 提了 … 上的一件事」抬头:', n('上的一件事'), '次')
  console.log('  空括号「（）」:', n('（）'), '次（该 0）')
  console.log('=== 逐条对起来（判据名 → 哪一档）===')
  for (const s of flags) {
    const name = (s.match(/代码判据\s*([^\s（(]+)/) || [])[1] || '?'
    const kind = s.includes('已经连着') && s.includes('没真打过分')
      ? 'judge_floor'
      : s.includes('这条当提醒看') ? 'advisory'
        : s.includes('没再花模型调用去打分') ? '短路（反例）'
          : s.includes('轮原样卡在这里') ? '卡死' : '?'
    console.log(`  ${name} → ${kind}`)
  }
  // 接线洞单独一条断言：advisory 的判词得**真的进了下一轮的 prompt**
  // （`prompts/note.advisory_block` 那条路）。假端点把它记在 `has_advisory_block` 上。
  console.log('  这一跑用的 note:', noteId)
  // **拍之前滚到那几行上**：右栏那一列有好几屏，不滚的话截图里只有 Agent 面板的抬头，
  // 台账上那张图证明不了任何事（「看到 ≠ 真在正文里」的孪生：**拍到了 ≠ 拍到的是那一格**）。
  const scrolled = await d.eval(`(() => {
    const p = Array.from(document.querySelectorAll('p')).filter((e) => (e.innerText || '').startsWith('⚑'))
    const hit = p.find((e) => (e.innerText || '').includes('这条当提醒看'))
    if (!hit) return 'advisory 那一行没找到'
    hit.scrollIntoView({ block: 'center' })
    return 'ok'
  })()`)
  console.log('  滚到 advisory 那一行:', scrolled)
  await wait(900)
  await d.shot(shot + '-light.png')
  await d.setTheme('dark'); await wait(900)
  await d.shot(shot + '-dark.png')
  await d.setTheme('light'); await wait(500)
}
