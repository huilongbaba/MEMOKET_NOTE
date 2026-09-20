// 轮次卡片到底在哪：**「选不到 ≠ 没有」**，先把候选都列出来再换选择器。
// `rounds58.mjs` 拿「含『Agent 运行』的最后一个容器」当卡片，这一趟它只拿到表头一行。
import { pageText, wait } from './lib.mjs'

export default async function (d, [noteId]) {
  await d.setTheme('light'); await wait(400)
  await d.openNoteById(noteId, 'P58 走查')
  await wait(2500)
  const cls = await d.eval(`(() => {
    const seen = {}
    for (const e of document.querySelectorAll('[class]')) {
      for (const c of String(e.className).split(/\\s+/)) {
        if (/round|agent|check|verdict|activity|card/i.test(c)) seen[c] = (seen[c] || 0) + 1
      }
    }
    return JSON.stringify(seen)
  })()`)
  console.log('相关的 class：', cls)
  const t = await pageText(d)
  for (const s of ['当提醒看', '照常打分', '没再花模型调用去打分', '这一轮没打分',
                   '判词就是下面', '照它改的', '轮', 'Agent 运行']) {
    console.log(`  整页含「${s}」:`, t.includes(s))
  }
  const hits = (t.match(/[^\n]*(当提醒看|照常打分|没再花模型调用|这一轮没打分)[^\n]*/g) || [])
  console.log('  命中行:', JSON.stringify(hits.slice(0, 8)))
  console.log('  整页前 3000 字 ---')
  console.log(t.slice(0, 3000))
}
