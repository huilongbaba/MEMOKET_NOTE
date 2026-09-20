/** 走查量具「这个窗口是谁」的**唯一出处**（P78 A）。
 *
 * ── 那笔账长什么样 ───────────────────────────────────────────────────────
 * P76 量出来：**16 份步骤脚本**读库时拿
 *
 *     const u = localStorage.getItem('memoket.user') || 'terrence'
 *
 * 取身份，而**整个前端里没有 `memoket.user` 这个键**——真键是 `memoket-note-user`
 * （`src/api.ts` 的 `USER_KEY`）。`getItem` 读不到回 `null`，于是每一次都走
 * `|| 'terrence'` 那个兜底，而**那个兜底恰好等于老用户的身份**：
 * 从 P47 到 P74，整整十四批走查，这条一次没露过馅。
 *
 * 换成空库新用户就当场现形。P78 开工那一趟实拍（`p74-newbie` 身份）：
 *
 *     跑之前：编辑器 105  库 {"len":0,"json":false}
 *     库: {"len":0,"json":false} ← len 该跟编辑器一样、json 该是 false
 *     库里的层: {"detail":"note not found"}
 *
 * 而**库里那篇好好的**：同一刻闸自己按真身份 `p74-newbie` 问后端，205 字、
 * 恰好 1 层 `on`。也就是说这三行读的全是**另一个人**的那一格。
 *
 * 这是「选不到 ≠ 没有」的**默认参数**那一张脸，第三次（P64 问题 #2 的
 * `d.noteId(user = 'terrence')`、P68 B 的驱动默认身份，现在是步骤脚本）。
 * 形状每次都一样：**一个猜出来的默认值，在当时那个环境里碰巧是对的。**
 * 「在真库上碰巧对」不是对。
 *
 * ── 为什么是一份文件，不是「把 16 处都改对」──────────────────────────────
 * 把 16 份里的键逐个改对，下一份新步骤脚本照样会抄一份旧的、照样写错——
 * P76 自己就干过一次：写新量具时把键写成了 `memoket.user`（那次是
 * `check-walkthrough-selectors.mts` 当场点出来的）。**抄得到的地方就会被抄。**
 * 所以键和读法只留一份，步骤脚本一律 `import` 它；
 * 而「只有一个出处」这件事**由闸钉住**（`check-walkthrough-selectors.mts` 第三件事）：
 * 任何地方再写一遍这个键，闸当场红。
 *
 * ── 读法照抄 `api.getUser()`，不是「差不多一样」────────────────────────────
 * `?user=` 优先（壳把 `identity.json` 挂在窗口 URL 上靠的就是它），
 * 其次 `localStorage[USER_KEY]`。两步的顺序也一样——顺序反了，
 * 「用另一个身份打开这个链接」那条路就量不出东西来。
 */

/** 前端记身份的那个 localStorage 键。**跟 `src/api.ts` 的 `USER_KEY` 必须是同一个**，
 *  闸会拿 `src/api.ts` 当对照物去核（那边改了名这儿没跟上 = 静默读空）。 */
export const USER_KEY = 'memoket-note-user'

const MSG = '走查量具：这个窗口的身份读不出来（?user= 和 localStorage["' + USER_KEY + '"] 都是空的）'
  + '——不猜一个（猜就是 P78 A 那次静默读了别人那一格）'

/** **在浏览器里跑**的那一段：读得出来给身份，读不出来给 `''`。
 *  只给「打印一下现在是谁」这种诊断用——**不许拿它当 `X-User-Id`**，
 *  空串发出去后端会当成另一个身份收下，又是一次静默读错。 */
export const USER_SOFT = `(() => { try {`
  + ` const q = new URLSearchParams(location.search).get('user');`
  + ` return (q && q.trim()) || localStorage.getItem(${JSON.stringify(USER_KEY)}) || ''`
  + ` } catch (e) { return '' } })()`

/** **在浏览器里跑**的那一段：身份，读不出来**当场抛**。
 *  凡是要往 `X-User-Id` 里塞的一律用这个——**吵闹地失败，比安静地读错强得多**。
 *
 *  用法（在步骤脚本的 `d.eval` 模板串里插进去）：
 *
 *      import { USER } from '../whoami.mjs'
 *      await d.eval(`(async () => {
 *        const u = ${USER}
 *        const r = await fetch('/api/notes', { headers: { 'X-User-Id': u } })
 *        ...
 *      })()`)
 */
export const USER = `(() => { const u = ${USER_SOFT};`
  + ` if (!u) throw new Error(${JSON.stringify(MSG)}); return u })()`
