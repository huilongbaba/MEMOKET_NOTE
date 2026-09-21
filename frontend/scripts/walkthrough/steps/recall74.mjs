// P74 C 重点盯的那一格：**P71 那一刀（两端吸附到词边界）之后，「命中：」那一行
// 变差的那两族，在真打好的壳上长什么样。**
//
// P71 离线读完 637 条变动行，`user` 血缘里 **14 条变差**，根因分两族：
//
//   ① **`out[:8]` 先满**（6 条）：摆得多了，**具体的实体词被泛词顶掉**
//      —— `灵衢交换架构` / `灵衢互联总线` 被 `中兴` / `华为` 顶掉，
//      `欧拉操作系统` 被 `华为` 顶掉，`计算柜` 被 `鲲芯片` 顶掉。
//      P71 **一个字没动 `out[:8]`**（判据宁可窄），账记下来了。
//   ② **分词器自己切错**（8 条）：`深圳特安`→`深圳特`、`瓷器纹路`→`瓷器纹`、
//      `分钟补能约`→`分钟补`、`那天津港`（`那天`|`津港`）。
//      **「摆出来的在词边界上」不等于「摆出来的是一个词」**——`_aligned` 量的是**碎**不是**泛**。
//
// P71 那两族是**离线重放**读出来的（`recall_ruler` 的 765 条查询）。
// 这一份把它们搬到**界面上**：光标停在含这些实体的段落上，把右栏「记忆」里
// 「命中：…」那一行原样打出来。**离线那一列和用户眼前那一行是两件事**
// （`recall64.mjs` 顶上那段写的就是这个），所以两头都得看一眼。
//
// **这一份不判对错，只把字摆出来。** 两族都是 P71 明写「量了没改」的账，
// 走查这一格要的是「它在壳上到底长什么样」，不是「它该长什么样」。
//
// usage: recall74.mjs <截图前缀> [段落…]（不给段落就用下面两族各一段）
import { docText, pageText, until, wait } from './lib.mjs'
import { clickExact } from './clickexact.mjs'

/** 默认两段，**各对着一族**。用词全部取自 P71 台账里点名的那几个实体。 */
const SEED = [
  // ① `out[:8]` 先满那一族：具体实体（灵衢 / 欧拉 / 计算柜）跟泛词（华为 / 中兴）同段
  '华为和中兴都在推，灵衢交换架构、灵衢互联总线、欧拉操作系统、计算柜这几样上周对过一遍。',
  // ② 分词器切错那一族：深圳特安 / 瓷器纹路 / 分钟补能约 / 天津港
  '深圳特安那批瓷器纹路做完了，充电 20 分钟补能约 300 公里，那天津港那边也回了话。',
]

/** 右栏「记忆」那一块（跟 `recall64.mjs` 逐字同一份读法，**先把页签点过去再读**）。 */
async function memPane(d) {
  await clickExact(d, '记忆', 0, 6).catch(() => {})
  await wait(2500)
  const now = await d.texts('.pane-tab', 12)
  const body = await d.eval(`(() => { const t = document.querySelectorAll('.pane-tab')[0]; return t ? t.parentElement.parentElement.innerText.slice(0, 4000) : null })()`)
  const ok = /托盘|知识库|光标这段|页边圆点/.test(body || '')
  if (!ok) console.log('   ⚠ 读回来的不像「记忆」那一块（页签：' + JSON.stringify(now) + '）')
  return body
}

export default async function (d, args) {
  const shot = args[0]
  const seeds = args.length > 1 ? args.slice(1) : SEED
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
  await d.insert('# P74 命中行走查（可删）'); await d.key('Enter'); await d.key('Enter')
  for (const s of seeds) { await d.insert(s); await d.key('Enter'); await d.key('Enter') }
  await wait(5000)
  console.log('正文字数:', (await docText(d) ?? '').length)

  const lines = await d.eval(`Array.from(document.querySelectorAll('.cm-content .cm-line')).map((l, i) => [i, (l.textContent||'').slice(0, 30)])`)
  console.log('行:', JSON.stringify(lines))

  // 上一段那一行，用来当场回答「右栏跟上了没有」（P80 A）
  let prevLine = null
  for (let i = 0; i < seeds.length; i++) {
    const head = seeds[i].slice(0, 6)
    const row = lines.find(([, t]) => t.includes(head))
    if (!row) { console.log(`\n【${head}…】这一行没找到（**选不到 ≠ 没有**）`, JSON.stringify(lines)); continue }
    const r = await d.rect('.cm-content .cm-line', row[0])
    await d.clickAt(r.x + 8, r.cy)
    await wait(3500)           // 光标停 0.9 秒才查，多等一会儿
    const mem = await memPane(d)
    console.log(`\n═══ 光标停在第 ${i + 1} 段【${head}…】═══`)
    console.log('  整段原文:', JSON.stringify(seeds[i]))
    // **整行读元素，不从整块正文里正则抠**（P80 A 的量具那一半）：
    // 原来那条 `/命中[：:][^\n]{0,200}/` 把**「按光标这段找的」/「按正文末尾找的」**
    // 这个前缀扔掉了，而那正是这一行自称属于哪一段的唯一标签——两段都退回「按正文末尾找的」
    // 时，抠出来的「命中：…」会逐字相同，而那不是「右栏没刷新」。**判据比产品窄**。
    const termsLine = await d.text('.mem-terms')
    console.log('  那一行整行（带「按…找的」前缀）:', JSON.stringify(termsLine))
    console.log('  跟上一段逐字相同吗:', prevLine !== null && termsLine === prevLine)
    // P80 A：摆出来的词里有几个是**前一段带进来的**（面板自己标的那半句）
    console.log('  「前一段带进来的」标了几处:', ((termsLine || '').match(/前一段带进来的/g) || []).length)
    console.log('  这一段没查成那一句在吗（该 false）:', await d.exists('.mem-failed'))
    prevLine = termsLine
    console.log('  命中行:', JSON.stringify((mem || '').match(/命中[：:][^\n]{0,200}/g)))
    // **逐个点名**：这一族里 P71 说「被顶掉 / 被切错」的那几个词，界面上到底摆没摆
    const WORDS = ['灵衢交换架构', '灵衢互联总线', '灵衢', '欧拉操作系统', '欧拉', '计算柜',
                   '华为', '中兴', '鲲芯片',
                   '深圳特安', '深圳特', '瓷器纹路', '瓷器纹', '分钟补能约', '分钟补',
                   '天津港', '那天津港', '那天']
    const hit = (mem || '').match(/命中[：:][^\n]{0,200}/g)?.join(' ') ?? ''
    console.log('  这一行里逐个点名:', JSON.stringify(
      Object.fromEntries(WORDS.map((w) => [w, hit.includes(w)]))))
    console.log('  关系卡那几行:', JSON.stringify(((mem || '').match(/[^\n]*(冲突|印证|缺依据|叠加|合并|延续)[^\n]*/g) || []).slice(0, 4)))
    console.log('  圆点:', JSON.stringify(await d.dots()))
    console.log('--- 右栏「记忆」整块 ---')
    console.log(mem)
  }

  await d.shot(shot + '-light.png')
  await d.setTheme('dark'); await wait(900)
  await d.shot(shot + '-dark.png')
  await d.setTheme('light'); await wait(400)
}
