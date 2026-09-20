// P70 A：把「收工那行 +N 字」那一格量到底。
//
// 跟 `adv64.mjs` 跑的是**同一趟**（同一档 `--mode adv`、同一个新建笔记、同一份种子），
// 只多做三件事，而且三件都**不发网络包**（第一版探针走 `api.clientLog`，
// 每条一次 fetch，把那一格的竞态自己压掉了：干净构建复现得出 790，带探针两趟都 1106）：
//
//   ① 正文长度**两头各读一次**：`.cm-line` 拼出来的（老量具）和库里那一份
//      （带 `X-User-Id` 问 `/api/notes/<id>`）。**「编辑器里没有 ≠ 库里没有」**：
//      这两个数在修之前是 807 / 807、而后端交出去的是 1103 —— 两头一起错，
//      所以光看编辑器读不出问题，得跟**后端交出去那一份**比。
//      （打包版里 CM 的 `.cm-content.cmView` 拿不到，别在那上面花时间。）
//   ② 收工那一行逐字。
//   ③ `window.__p70`（前端那个内存探针）整串读走。
//
// usage: adv68.mjs <seed 标题> <截图前缀>
import { clickExact } from './clickexact.mjs'
import { docText, pageText, statusWords, until, wait } from './lib.mjs'
import { USER, USER_SOFT } from '../whoami.mjs'

export default async function (d, [tag, shot]) {
  await until(async () => (await pageText(d)).length > 50, 30000)
  await wait(1500)
  await d.setTheme('light'); await wait(500)

  await d.key('Escape'); await wait(300)
  await d.key('k', ['meta']); await wait(1000)
  await d.insert('新建笔记'); await wait(900)
  await clickExact(d, '新建笔记', 0, 8)
  await wait(3000)
  // **不用默认参数**（P70 B）：这个窗口的身份从页面上读，别读另一个人的那一格。
  const who = await d.eval(USER_SOFT)
  const noteId = await d.noteId(who)
  console.log('窗口身份:', who, ' 新建出来的:', noteId)
  await d.focusEditor()
  await d.insert('# ' + tag); await d.key('Enter'); await d.key('Enter')
  await d.insert('把 EVT 这一阶段的口径、责任人、判据三件事写清楚。')
  await d.key('Enter'); await d.key('Enter')
  await wait(2500)
  const before = await docText(d)
  console.log('跑之前 编辑器(.cm-line):', (before ?? '').length)

  await clickExact(d, '智能续写', 0, 10)
  await wait(2000)
  await until(async () => (/· \d+ 轮 ·/.test(await pageText(d)) ? true : null), 300000, 2000)
  await wait(5000)

  const three = await d.eval(`(async () => {
    const lines = Array.from(document.querySelectorAll('.cm-content .cm-line')).map((l) => l.textContent ?? '').join('\\n')
    const user = ${USER}
    let db = null
    try {
      const r = await fetch('/api/notes/' + ${JSON.stringify('')} + ${JSON.stringify(noteId)}, { headers: { 'X-User-Id': user } })
      const j = await r.json()
      db = (j.content || '').length
    } catch (e) { db = 'fetch 失败 ' + e }
    return { lines: lines.length, db }
  })()`)
  console.log('=== 正文两头 ===', JSON.stringify(three))

  const t = await pageText(d)
  console.log('--- 收工那一行 ---', JSON.stringify((t.match(/[^\n]*· \d+ 轮 ·[^\n]*/g) || []).slice(0, 3)))
  // **走 `lib.mjs` 那一份，不再在这儿抄一遍正则**（P72）：这一处原来是抄的，
  // 而抄的那份就是 P70 问题 #2 里读回 `null` 的那条 —— 截图上写着「1072 字」。
  // 两把尺子必然飘，修一处等于只修一半。
  console.log('--- 状态栏那个字数 ---', JSON.stringify(await statusWords(d)))

  const trace = await d.eval(`(window.__p70 || ['没有 __p70：这一份壳不是带探针那一版'])`)
  console.log('--- window.__p70（' + trace.length + ' 条）---')
  for (const line of trace) console.log('  ' + line)

  await d.shot(shot + '-light.png')
}
