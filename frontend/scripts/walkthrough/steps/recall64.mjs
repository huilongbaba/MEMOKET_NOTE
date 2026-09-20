// P66 C 重点盯的那一格：**P61 换量程之后，真实老用户库上的召回在界面上长什么样**。
//
// P61 量的是全库对拍（765 条查询），走查看的是**界面**——两件事。
// 这一趟把光标逐段停一遍，把右栏「记忆」里那几行原样打出来：
//   · 「命中：…」那一行（P38 ⑤ 接分词之后**拿给用户看的**那一列）
//   · P44 问题 #4 / P40 问题 #4 的那个反例：原文「3 月 12 号上线」曾经切出
//     **「号上」**这个不是词的词，逐字摆在用户眼前。
//   · 关系卡（冲突 / 印证 / 缺依据）和页边圆点各一份。
//
// **判据是界面上的原话，不是我记得的那句**：每一段都把整块原文打出来，
// 台账里引的就是这里的字。
//
// usage: recall64.mjs <截图前缀>
import { docText, pageText, until, wait } from './lib.mjs'
import { clickExact } from './clickexact.mjs'

const SEED = [
  'P66 走查：召回换量程之后，界面上这一列长什么样。',
  '众筹页面那一版文案是 3 月 12 号上线的，当天点击 12700。',
  '预热名单回收了 860 份，转化率按渠道排了一遍。',
  'EVT 准备 4 台主机，15 套 PCBA，下周进模具。',
]

/** 右栏「记忆」那一块。**先把页签点过去再读**：
 *  第一版直接从 `.pane-tab` 往上找容器就读，读回来的是**当时开着的那个页签**
 *  （「计划」）的内容 —— 三段读回来的「命中行」全是 `null`，看着像
 *  「换完量程一条都不命中了」，其实是**读错了面板**。「选不到 ≠ 没有」的又一个形状。 */
async function memPane(d) {
  await clickExact(d, '记忆', 0, 6).catch(() => {})
  await wait(2500)
  const now = await d.texts('.pane-tab', 12)
  const body = await d.eval(`(() => { const t = document.querySelectorAll('.pane-tab')[0]; return t ? t.parentElement.parentElement.innerText.slice(0, 4000) : null })()`)
  // 读之前核一眼：读回来的这一块里得有「记忆」那一块自己的字，别再读到「计划」上去
  const ok = /托盘|知识库|光标这段|页边圆点/.test(body || '')
  if (!ok) console.log('   ⚠ 读回来的不像「记忆」那一块（页签：' + JSON.stringify(now) + '）')
  return body
}

export default async function (d, [shot]) {
  await until(async () => (await pageText(d)).length > 50, 30000)
  await wait(1500)
  await d.setTheme('light'); await wait(400)

  await d.key('Escape'); await wait(300)
  await d.key('k', ['meta']); await wait(1000)
  await d.insert('新建笔记'); await wait(900)
  await clickExact(d, '新建笔记', 0, 8)
  await wait(3000)
  console.log('新建出来的:', await d.noteId())
  await d.focusEditor()
  await d.insert('# P66 召回走查（可删）'); await d.key('Enter'); await d.key('Enter')
  for (const s of SEED) { await d.insert(s); await d.key('Enter'); await d.key('Enter') }
  await wait(5000)
  console.log('正文字数:', (await docText(d) ?? '').length)

  const lines = await d.eval(`Array.from(document.querySelectorAll('.cm-content .cm-line')).map((l, i) => [i, (l.textContent||'').slice(0, 24)])`)
  console.log('行:', JSON.stringify(lines))

  for (const want of ['3 月 12 号上线', '预热名单', 'EVT 准备']) {
    const row = lines.find(([, t]) => t.includes(want.slice(0, 6)))
    if (!row) { console.log(`\n【${want}】这一行没找到（**选不到 ≠ 没有**，行文本：`, JSON.stringify(lines), '）'); continue }
    const r = await d.rect('.cm-content .cm-line', row[0])
    await d.clickAt(r.x + 8, r.cy)
    await wait(3500)           // 光标停 0.9 秒才查，多等一会儿
    const mem = await memPane(d)
    console.log(`\n═══ 光标停在【${want}】那一段 ═══`)
    console.log('  命中行:', JSON.stringify((mem || '').match(/命中[：:][^\n]{0,140}/g)))
    console.log('  关系卡那几行:', JSON.stringify(((mem || '').match(/[^\n]*(冲突|印证|缺依据|叠加|合并|延续)[^\n]*/g) || []).slice(0, 4)))
    console.log('  「没有一条记录同时命中两个」在吗:', (mem || '').includes('同时命中两个'))
    console.log('  圆点:', JSON.stringify(await d.dots()))
  }

  console.log('\n=== P44 问题 #4 / P40 问题 #4 的那个反例 ===')
  const all = await memPane(d)
  console.log('  整块「记忆」里出现过「号上」吗（P38 ⑤ 切错的那个词，**该 false**）:',
              (all || '').includes('号上'))
  console.log('--- 右栏「记忆」整块 ---')
  console.log(all)
  await d.shot(shot + '-light.png')
  await d.setTheme('dark'); await wait(900)
  await d.shot(shot + '-dark.png')
  await d.setTheme('light'); await wait(400)
}
