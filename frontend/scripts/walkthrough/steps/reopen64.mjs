// P66 C 第 10 步的**真·关掉重开**：这一发跑在一个**刚起来的壳**上（go.sh 单独一次调用）。
//
// 为什么单独一发：`b3old.mjs` 那一格写着「关掉重开」，但它跟 b1b / b2old 跑在
// **同一个 go.sh 会话**里 —— 那是「在同一个进程里换了一篇」，不是重开。
// P60 那一趟 b3 是自己一次调用（壳是新起的），所以两批的读数不能直接对。
// **「点过了 ≠ 翻过了」的同族**：换了一篇 ≠ 重开过一次。
//
// usage: reopen64.mjs <带层的 noteId> <不带层的 noteId> <截图名>
import { docText, pageText, until, wait } from './lib.mjs'

export default async function (d, [withLayer, noLayer, shot]) {
  await until(async () => (await pageText(d)).length > 50, 30000)
  await wait(2000)
  await d.setTheme('light'); await wait(400)
  console.log('壳刚起来，现在开着:', await d.noteId())
  console.log('  这一刻的 toast:', JSON.stringify(await d.toasts()))

  await d.openNoteById(withLayer, 'P58 走查')
  await wait(3500)
  console.log('=== 带层那篇（', withLayer, '）===')
  console.log('  开着的是:', await d.noteId())
  console.log('  右栏页签:', JSON.stringify(await d.texts('.pane-tab', 12)))
  const ts = await d.toasts()
  console.log('  toast:', JSON.stringify(ts))
  const t = await pageText(d)
  // P43 立的不变式：**弹了 toast ⇒ 「改动」页签一定在**。两头各读一次，别只读一头。
  const said = ts.some((x) => x.includes('上次没处置完的'))
  const tab = (await d.texts('.pane-tab', 12)).some((x) => x.includes('改动'))
  console.log('  P43 不变式（弹了 toast ⇒ 页签在）:', said ? (tab ? '成立' : '**破了**') : '没弹 toast，不适用')
  console.log('  整页搜得到「改动」这两个字吗:', t.includes('改动'))
  console.log('  正文字数:', (await docText(d) ?? '').length)
  await d.shot(shot + '-withlayer-light.png')

  await d.openNoteById(noLayer, 'harness 测试')
  await wait(3000)
  console.log('=== 不带层那篇（', noLayer, '）===')
  console.log('  开着的是:', await d.noteId())
  console.log('  右栏页签（不许有「改动」）:', JSON.stringify(await d.texts('.pane-tab', 12)))
  console.log('  toast（该一条都没有）:', JSON.stringify(await d.toasts()))
  await d.shot(shot + '-nolayer-light.png')
}
