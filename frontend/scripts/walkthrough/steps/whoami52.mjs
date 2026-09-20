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
  const banner = await d.eval(`(() => { const e = document.querySelector('.selfcheck, [class*="selfcheck"], .banner-error'); return e ? e.textContent.slice(0, 120) : '(没有)' })()`)
  console.log('  自检横幅:', banner)
}
