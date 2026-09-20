// P58 · A1 第三格：**「自动描述停了：<原因>」**（P20 #4 的第三条，从第 778 轮留到现在）。
//
// 摆法：`journey/on` 事先放着（**假采集源那一份 udd 才敢这么干**——它一张屏都不拍），
// 于是壳一起来 `restore()` 就开始记；`describeBacklog` 在开机 30 秒后第一次跑，
// 而这一趟把看图模型的地址指到一个**死端口**，它一定连不上 →
// `describeStalled` 被写上 → `journey:state` 交给页面 → 页面上那一句。
import { openJourney, pageText, toTop, until, wait } from './lib52.mjs'

const line = (t, re) => (t.match(re) || [])[0] || null

export default async function (d, [tag]) {
  console.log('起来那一刻:', JSON.stringify(await d.eval(`window.memoketDesktop.journey.state()`)))
  const st = await until(async () => {
    const s = await d.eval(`window.memoketDesktop.journey.state()`)
    return s.stalled ? s : null
  }, 180000, 3000)
  console.log('壳那边记下的原因:', JSON.stringify(st))
  await openJourney(d)
  await toTop(d)
  await d.eval(`document.dispatchEvent(new Event('visibilitychange'))`)
  await wait(1500)
  const t = await pageText(d)
  console.log('页面上那一句:', line(t, /自动描述停了[^\n]*/))
  console.log('状态行:', line(t, /[^\n]*记录中[^\n]*/))
  await d.shot(`p70-${tag}-stalled-light.png`)
  await d.eval(`window.memoketDesktop.journey.stop()`)
  await wait(1000)
  console.log('收摊，停掉记录:', JSON.stringify(await d.eval(`window.memoketDesktop.journey.state()`)))
}
