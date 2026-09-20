// P66 B：**锁屏那条接到产品上**（P62 ④-① 的后半 / P20 #6，四批都挂着）。
//
// P62 已经验通了量具侧：`postnote.m` 发一条 `NSDistributedNotificationCenter` 通知
// （`com.apple.screenIsLocked` / `com.apple.screenIsUnlocked`），Electron 的
// `powerMonitor` **真收到 `lock-screen` / `unlock-screen`**（反例 `[]`，EXIT=3）。
// 这一批把**产品那一格**摆出来：开到「正在记录 → 用户自己按了暂停」→ 发 unlock →
// **暂停不许被解掉**（`capture.onPowerEvent('unlock', 'paused', autoPaused=false)` 回 `null`）。
//
// ⚠️ **这一步会往整台机器发一条分布式通知**：别的在监听 `com.apple.screenIsLocked`
// 的 app 也会收到（它们会以为屏幕锁了）。跑之前心里有数。
//
// **「红了」和「红的是那条」分开核**：先做**正向对照**（running 上锁 → 自动暂停；
// 再解锁 → 自动恢复）。正向对照过了，才证明**这一个实例里那条监听是活的**——
// 否则「解锁之后还是暂停」可能只是因为通知根本没到，那不叫摆出来。
//
// usage: lock64.mjs <postnote 可执行件> <截图前缀>
import { execFileSync } from 'node:child_process'
import { openJourney, pageText, until, wait } from './lib52.mjs'

const LOCK = 'com.apple.screenIsLocked'
const UNLOCK = 'com.apple.screenIsUnlocked'

function post(bin, name) {
  const out = execFileSync(bin, [name], { encoding: 'utf8' }).trim()
  console.log('   ' + out)
  if (!out.includes('posted ' + name)) throw new Error('postnote 没发出去：' + out)
}

/** 壳那边真正的状态（`journey:state` IPC，跟菜单栏图标同一个来源）。 */
async function st(d) {
  return d.eval(`window.memoketDesktop.journey.state()`)
}

export default async function (d, [bin, shot]) {
  await until(async () => (await pageText(d)).length > 50, 30000)
  await wait(1200)
  await d.setTheme('light'); await wait(400)
  console.log('打开屏幕活动那一页:', await openJourney(d))
  let s0 = await st(d)
  console.log('开局:', JSON.stringify(s0))
  if (!s0.fake) throw new Error('这个实例没挂假采集源 —— 真按「开始记录」会真录屏、真弹权限框，不跑')
  // **上一趟留下的状态要清掉再开**：`capture.restore()` 会把「上次是开着的」接着开
  // （产品行为，对的），于是这一趟一进来就是 `running`、页面画的是「暂停 1 小时」——
  // 第一版就栽在这，报的是「页面上没有『开始记录』那个钮」。
  // 停掉之后**整页重挂一次**（这一页 30 秒才轮询一次，不重挂就还停在上一帧）。
  if (s0.state !== 'off') {
    console.log('  上一趟留着', s0.state, '—— 先停掉再重挂')
    await d.eval(`window.memoketDesktop.journey.stop()`)
    await wait(900)
    await d.eval(`location.reload()`)
    await wait(6000)
    await until(async () => (await pageText(d)).length > 50, 30000)
    await openJourney(d)
    s0 = await st(d)
    console.log('  重挂之后:', JSON.stringify(s0))
  }
  if (s0.state !== 'off') throw new Error('停不干净：' + JSON.stringify(s0))

  console.log('\n═══ 正向对照：锁屏该**自动**暂停，解锁该**自动**恢复 ═══')
  // **点页面上那个钮，不走 IPC**：`bridge.start().then(refresh)` 会当场把这一页
  // 重画一遍，下面那个「暂停 1 小时」才画得出来。直接调 IPC 的话壳那边状态变了、
  // 页面还停在上一帧（这一页 30 秒才轮询一次），于是「按钮不在」——
  // 那不是产品没有这个钮，是**这一帧还没画**。（「选不到 ≠ 没有」的又一个形状。）
  const startBtn = await d.findText('button', '开始记录')
  if (!startBtn) throw new Error('页面上没有「开始记录」那个钮')
  await d.clickAt(startBtn.cx, startBtn.cy)
  await wait(2000)
  const a1 = await st(d)
  console.log('① 点页面上的「开始记录」→', a1.state, '（该 running）')
  if (a1.state !== 'running') throw new Error('开不起来：' + JSON.stringify(a1))
  const pauseBtn = await until(async () => d.findText('button', '暂停 1 小时'), 40000, 1000)
  console.log('   页面现在画的是「暂停 1 小时」吗:', !!pauseBtn)

  console.log('② 发 ' + LOCK)
  post(bin, LOCK)
  await wait(2500)
  const a2 = await st(d)
  console.log('   →', a2.state, '（该 paused —— 这一下证明这个实例里那条监听是活的）')

  console.log('③ 发 ' + UNLOCK)
  post(bin, UNLOCK)
  await wait(2500)
  const a3 = await st(d)
  console.log('   →', a3.state, '（该 running —— 自己按下去的那次暂停，自己解掉）')

  console.log('\n═══ 要摆的那一格：**用户自己按的暂停，解锁不许替他打开** ═══')
  // 页面上那个钮就是用户的动作（`journey:pause(60)` → `userPause` → `autoPaused = false`）。
  const btn = await until(async () => d.findText('button', '暂停 1 小时'), 40000, 1000)
  if (!btn) throw new Error('页面上没有「暂停 1 小时」那个钮')
  await d.clickAt(btn.cx, btn.cy)
  await wait(1800)
  const b1 = await st(d)
  console.log('④ 用户自己按「暂停 1 小时」→', b1.state, ' until=', b1.until, '（该 paused + until>0）')
  if (b1.state !== 'paused' || !b1.until) throw new Error('没暂停上：' + JSON.stringify(b1))
  await d.shot(shot + '-paused-light.png')

  console.log('⑤ 发 ' + UNLOCK + '（用户没解锁过任何东西，是屏幕解锁）')
  post(bin, UNLOCK)
  await wait(2500)
  const b2 = await st(d)
  console.log('   →', b2.state, ' until=', b2.until)
  console.log('   **暂停还在吗（该 true）**:', b2.state === 'paused')
  console.log('   **到点时间一秒没动吗（该 true）**:', b2.until === b1.until)
  // **这一步得会吵**：只打一行「false」的探针当不了闸（突变验砍了 `onPowerEvent`
  // 之后它照样 EXIT=0，那就是一条永远绿的闸）。
  if (b2.state !== 'paused' || b2.until !== b1.until) {
    throw new Error(`P20 #6 破了：用户自己按的暂停被解锁解掉了 —— ${JSON.stringify(b2)}`)
  }

  console.log('⑥ 再来一遍：锁 + 解锁（锁屏对已经暂停的什么都不做，解锁照样不许恢复）')
  post(bin, LOCK)
  await wait(2000)
  const b3 = await st(d)
  console.log('   锁之后 →', b3.state, '（该还是 paused）')
  post(bin, UNLOCK)
  await wait(2500)
  const b4 = await st(d)
  console.log('   解之后 →', b4.state, ' until=', b4.until)
  console.log('   **暂停还在吗（该 true）**:', b4.state === 'paused')
  console.log('   **到点时间一秒没动吗（该 true）**:', b4.until === b1.until)
  if (b4.state !== 'paused' || b4.until !== b1.until) {
    throw new Error(`P20 #6 破了（锁+解锁那一轮）：${JSON.stringify(b4)}`)
  }
  // 正向对照也得会吵：它没过的话「解锁之后还是暂停」可能只是通知根本没到
  if (a2.state !== 'paused' || a3.state !== 'running') {
    throw new Error(`正向对照没过（通知可能根本没到这个实例）：锁后 ${a2.state} / 解后 ${a3.state}`)
  }

  // 界面那一侧也得对上：钮该是「继续记录」、那句话该是「已暂停 —— 到 HH:MM 自己继续。」
  const resumeBtn = await until(async () => d.findText('button', '继续记录'), 40000, 1000)
  console.log('   页面现在画的是「继续记录」吗（该 true）:', !!resumeBtn)
  const t = await pageText(d)
  console.log('\n页面上那句:', JSON.stringify((t.match(/已暂停[^\n]*/) || [])[0] ?? null))
  console.log('页面上有没有「假采集源」那句（该 true）:', t.includes('这一页画的不是真的屏幕活动'))
  await d.shot(shot + '-after-unlock-light.png')
  await d.setTheme('dark'); await wait(900)
  await d.shot(shot + '-after-unlock-dark.png')
  await d.setTheme('light'); await wait(400)

  // 收摊：把它停掉，别让下一个步骤继承一个「暂停中」的状态
  await d.eval(`window.memoketDesktop.journey.stop()`)
  await wait(800)
  console.log('收摊 →', (await st(d)).state)
}
