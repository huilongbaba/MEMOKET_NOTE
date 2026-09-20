// 把这个窗口的身份设成老用户（`localStorage[USER_KEY]`，见 `../whoami.mjs`），然后刷新。
//
// **为什么要它**（P60 走查量具坑 #1）：P58 那份 `old/udd` 里已经躺着一份
// 身份 = terrence（那个目录是上一批留下来的），这一批的 `old/udd` 是
// `setup.py` 现建的空目录，身份回到「(默认)」，于是 482 篇一篇都看不见、
// `whoami52` 报 `200 []`、`b1old` 在「编辑器聚焦失败」上当场死。
// **「库里有」跟「这个窗口看得见」是两件事。**
import { wait } from './lib.mjs'
import { USER_KEY } from '../whoami.mjs'

export default async function (d, args) {
  const user = args[0] || 'terrence'
  console.log('设身份前:', await d.eval(`localStorage.getItem(${JSON.stringify(USER_KEY)})`))
  await d.eval(`(localStorage.setItem(${JSON.stringify(USER_KEY)}, ${JSON.stringify(user)}), 'ok')`)
  await d.eval(`location.reload()`)
  await wait(6000)
  console.log('设身份后:', await d.eval(`localStorage.getItem(${JSON.stringify(USER_KEY)})`))
  const n = await d.eval(`(async () => {
    const r = await fetch('/api/notes?limit=3', { headers: { 'X-User-Id': ${JSON.stringify(user)} } })
    const j = await r.json()
    return Array.isArray(j) ? j.length : -1
  })()`)
  console.log('  这个身份下 /api/notes?limit=3 拿到几篇:', n)
}
