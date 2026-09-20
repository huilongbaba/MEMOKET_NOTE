// **窗口连的是哪个后端、那个后端开的是哪个库、现在开着哪一篇**。
// 每次起 app 之后第一条就跑它（P50 量具坑 #2：P47 那版拿 `?user=` 查询串量身份，
// 而后端认的是 `X-User-Id` 头 —— 一律报 `[]`，什么都没量到）。
import { api, whoami } from './lib52.mjs'

export default async function (d) {
  const origin = await d.eval('location.origin')
  const health = await d.eval(`fetch('/api/health').then(r => r.text()).then(t => t.slice(0, 200))`)
  console.log('窗口 origin:', origin)
  console.log('  /api/health:', health)
  console.log('  窗口自己认的身份:', await whoami(d))
  console.log('  带头问 /api/notes?limit=1:', (await api(d, '/api/notes?limit=1')).slice(0, 200))
  console.log('  带头问 /api/journey/days:', await api(d, '/api/journey/days'))
  console.log('  现在开着哪一篇（note id）:', await d.noteId())
  // 自检横幅（「⚠︎ 连错后端了」，P45 #2）。
  //
  // **P74 修的**：这一行原来选的是 `.selfcheck, [class*="selfcheck"], .banner-error`
  // —— 三个类名**前端里一个字都没有**，于是它从 P50 到 P72 **每一批都报 `(没有)`**，
  // 而台账每一批都把那个「没有」抄了进去。真的那条横幅是
  // `frontend/src/util/backendIdentity.ts` 的 `shout()` 现建的一个 `div`：
  // **`id="memoket-wrong-backend"`、`role="alert"`、一个 class 都没有**。
  // （为什么一直没人吵：`check-walkthrough-selectors.mts` 第 ② 遍的引号正则
  //  吃不下「单引号包着、里头带双引号」的选择器，整串静默跳过——P74 一并修了，
  //  并且给那一遍配了例 / 反例。**判据的字符类比产品窄**，跟 P72 那条 `\w` 同形。）
  //
  // 反例在假壳那条闸上（`scripts/run-walkthrough-fakeshell.mjs` 的第 ③ 刀）：
  // 故意让壳报错一个后端 pid，这一行必须读回「⚠︎ 连错后端了」而不是「(没有)」。
  const banner = await d.eval(`(() => { const e = document.querySelector('#memoket-wrong-backend'); return e ? e.textContent.replace(/\\s+/g, ' ').slice(0, 120) : '(没有)' })()`)
  console.log('  自检横幅:', banner)
}
