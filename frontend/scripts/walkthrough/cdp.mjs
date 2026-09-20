// P17 走查驱动：零依赖的 CDP 客户端（Node 22 自带 WebSocket）。
// usage: WALKTHROUGH_SHOT_DIR=<放截图的目录> node cdp.mjs <cdp-port> <step.mjs> [args...]
//        step.mjs 默认导出 async (d, args) => {}
// 走的是真输入事件（Input.dispatchMouseEvent / dispatchKeyEvent / insertText），不是往 React 里灌状态。
//
// ─────────────────────────────────────────────────────────────────────────────
// **P66：这份从 scratch 搬进了仓库**（P64 留的第 4 条：「壳那一侧的量具还在 scratch 里，
// 下一次壳上的数还是复现不出来」）。搬进来之后变的只有一处：
// `d.shot()` 的落盘目录从**写死的 scratch 绝对路径**改成
// `WALKTHROUGH_SHOT_DIR`（**没设就抛**，不猜一个目录静默写进去）——
// 一份进 git 的文件里写死某一次会话的 scratch 路径，换一台机器就是静默写错地方。
// 别的一个字节没动（`must` / `toasts` / `dots` / `expandDetails` / `noteId` / `shot`
// 的判据和措辞全是 P49 / P62 那两批量出来的，改一个字就得重新量）。
//
// **步骤脚本（`steps/*.mjs`）没跟着进来**，理由见 `README.md`：它们要一个真打出来的
// `.app` + 一份真用户库 + 一个活着的 CDP 端口，这三样 `npm test` 里一样都没有。
// 进链的是**不需要壳的那一半**：`scripts/check-walkthrough-selectors.mts`
// 把这份文件里选的每一个类名对着 `frontend/src` 点一遍名。
// ─────────────────────────────────────────────────────────────────────────────
//
// ─────────────────────────────────────────────────────────────────────────────
// **P49 ④ 收掉的两条量具毛病**（P47 问题 #4 / #5，以后每批都用这一份）：
//
//  1. **同名笔记两篇时按标题点不准**（P47 差点把「改动页签没了」记成缺陷）。
//     判据从「点了」改成「**打开之后的 note id**」——`d.noteId()` 读的是 app 自己
//     记「现在开着哪一篇」的那一格（`localStorage['memoket-note-active:<user>']`，
//     `App.tsx` 每次 `current` 变就写一次），`d.openNoteById()` 点完**核 id**，
//     对不上就接着点下一个候选，候选点完还对不上**直接抛**。
//     （P47 那版 `openid.mjs` 找的是 `[data-note-id]`——**整个前端里根本没有这个属性**，
//      那条路永远走不通。「选不到 ≠ 没有」的反面：**选择器指着一个不存在的东西，
//      也得吵出来**。）
//
//  2. **截图名写死**（`darknarrow` / `cmdk` 写死 `-old-`，新用户那一趟覆盖了老用户几张）。
//     `d.shot(name)` 现在两条都管：**名字必须由调用方给**（空就抛），
//     **而且不许静默覆盖**（同名文件已经在了就抛，真要覆盖得显式说 `{overwrite:true}`）。
//     后一条是结构性的：不管哪个步骤脚本把名字写死，覆盖那一刻就会吵，
//     不必逐个脚本去找。
// ─────────────────────────────────────────────────────────────────────────────
// **P62 收口的三条**（P60 问题 #2 #3 #4 #5 #6，以后每批都用这一份）：
//
//  3. **`d.must(sel)` / `d.mustTexts(sel)`：选不到就抛，别静默返回空。**
//     `d.count()` / `d.texts()` 选不到时回 `0` / `[]`，读起来跟「产品里真的没有」
//     一模一样 —— P17 / P31 / P35 / P47 / P60 各栽过一次。判据里要的那几格一律走
//     `must*`：**选择器指着一个不存在的东西，得当场吵。**
//
//  4. **`d.toasts()` / `d.dots()` / `d.menuItems()`：真类名，别用通配。**
//     通配既会漏也会多，**多出来那一份长得跟真的一模一样，比漏更难看出来**。
//     P58 / P60 两批的 `[class*="toast"]` **同时选中了外层容器 `.toaster`**
//     （这个串里含 `toast`），容器的 `textContent` 正好等于里面那一条 ——
//     于是「一条」读回来是两条一模一样的字，两批都记成了「同一条 toast 连出两遍」。
//     实拍截图 `p60-b7-2-ro-toast-light.png` 上**只有一个 toast 框**。
//     **「选不到 ≠ 没有」的镜像是「选到两个 ≠ 真有两个」。**
//     闸在仓里：`frontend/src/editor/__tests__/p62Toast.test.tsx`。
//
//  5. **`d.expandDetails()` / `d.readCard()`：读之前先把 `<details>` 摊开。**
//     轮次卡片的判据那几行在 `<details>` 里，收着的时候 `innerText` **读不到**
//     （不是选择器错，是**读法**错）。P58 / P60 两批「判据那几行」都是 `[]`，
//     而 P58 台账那一格是靠截图断的 —— **日志里其实是 0**。
// ─────────────────────────────────────────────────────────────────────────────
const port = process.argv[2]
const stepPath = process.argv[3]
const args = process.argv.slice(4)

const MOD = { alt: 1, ctrl: 2, meta: 4, shift: 8 }
const VK = { Enter: 13, Escape: 27, Backspace: 8, Tab: 9, Space: 32, ArrowLeft: 37, ArrowUp: 38, ArrowRight: 39, ArrowDown: 40, Delete: 46, Home: 36, End: 35, '/': 191, '\\': 220, '[': 219, ']': 221, ',': 188, '.': 190, '-': 189, '=': 187, ';': 186, "'": 222, '`': 192 }
const CODE = { Enter: 'Enter', Escape: 'Escape', Backspace: 'Backspace', Tab: 'Tab', Space: 'Space', ArrowLeft: 'ArrowLeft', ArrowUp: 'ArrowUp', ArrowRight: 'ArrowRight', ArrowDown: 'ArrowDown', Delete: 'Delete', Home: 'Home', End: 'End', '/': 'Slash', '\\': 'Backslash', '[': 'BracketLeft', ']': 'BracketRight', ',': 'Comma', '.': 'Period', '-': 'Minus', '=': 'Equal', ';': 'Semicolon', "'": 'Quote', '`': 'Backquote' }

class Conn {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.handlers = []
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data)
      if (m.id && this.pending.has(m.id)) { const { res, rej } = this.pending.get(m.id); this.pending.delete(m.id); m.error ? rej(new Error(m.error.message + ' ' + (m.error.data ?? ''))) : res(m.result) }
      else if (m.method) for (const h of this.handlers) h(m.method, m.params)
    }
  }
  static open(url) { return new Promise((res, rej) => { const ws = new WebSocket(url); ws.onopen = () => res(new Conn(ws)); ws.onerror = (e) => rej(new Error('ws error ' + url)) }) }
  send(method, params = {}) { const id = ++this.id; this.ws.send(JSON.stringify({ id, method, params })); return new Promise((res, rej) => this.pending.set(id, { res, rej })) }
  on(h) { this.handlers.push(h) }
  close() { this.ws.close() }
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms))

async function main() {
  const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json()
  const page = list.find((t) => t.type === 'page' && /127\.0\.0\.1:\d+/.test(t.url)) ?? list.find((t) => t.type === 'page')
  if (!page) throw new Error('没有 page target: ' + JSON.stringify(list.map((t) => [t.type, t.url])))
  const c = await Conn.open(page.webSocketDebuggerUrl)
  const ver = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json()
  const browser = await Conn.open(ver.webSocketDebuggerUrl).catch(() => null)
  const consoleLines = []
  c.on((m, p) => {
    if (m === 'Runtime.consoleAPICalled' && (p.type === 'error' || p.type === 'warning')) consoleLines.push(`[console.${p.type}] ` + p.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 300))
    if (m === 'Runtime.exceptionThrown') consoleLines.push('[exception] ' + (p.exceptionDetails.exception?.description ?? p.exceptionDetails.text).slice(0, 400))
  })
  await c.send('Runtime.enable'); await c.send('Page.enable'); await c.send('DOM.enable')

  const d = {
    c, browser, url: page.url, consoleLines, wait,
    log: (...a) => console.log(...a),
    async eval(expr) {
      const r = await c.send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
      if (r.exceptionDetails) throw new Error('eval: ' + (r.exceptionDetails.exception?.description ?? r.exceptionDetails.text) + ' :: ' + expr.slice(0, 120))
      return r.result.value
    },
    async rect(sel, idx = 0) {
      return this.eval(`(() => { const els = document.querySelectorAll(${JSON.stringify(sel)}); const el = els[${idx}]; if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, cx: r.x + r.width / 2, cy: r.y + r.height / 2, n: els.length, text: (el.textContent || '').slice(0, 80) } })()`)
    },
    async exists(sel) { return this.eval(`!!document.querySelector(${JSON.stringify(sel)})`) },
    async count(sel) { return this.eval(`document.querySelectorAll(${JSON.stringify(sel)}).length`) },
    async text(sel, idx = 0) { return this.eval(`(document.querySelectorAll(${JSON.stringify(sel)})[${idx}]?.textContent ?? null)`) },
    async texts(sel, max = 40) { return this.eval(`Array.from(document.querySelectorAll(${JSON.stringify(sel)})).slice(0, ${max}).map((e) => (e.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 120))`) },
    /** **选不到就抛**（P62 收口 3）。判据里要的那几格一律走这个，别走 `count()`。
     *
     * `count()` 选不到回 0、`texts()` 回 `[]`，跟「产品里真的没有」读起来一模一样。
     * `{ min, max }` 两头都能钉：`must('.toaster', { max: 1 })` 就是
     * 「容器只许有一个」——**「选到两个 ≠ 真有两个」那一类当场吵**。 */
    async must(sel, { min = 1, max = Infinity, why = '' } = {}) {
      const n = await this.count(sel)
      if (n < min || n > max) {
        throw new Error(`must: 「${sel}」选到 ${n} 个，要的是 ${min}${max === Infinity ? '+' : '–' + max}`
          + (why ? `（${why}）` : '') + '。**选不到 ≠ 没有；选到两个 ≠ 真有两个**')
      }
      return n
    },
    /** `texts()` 的会吵版本：一个都选不到就抛。 */
    async mustTexts(sel, max = 40, opts = {}) { await this.must(sel, opts); return this.texts(sel, max) },
    /** **现在屏上的 toast**（P62 收口 4）。
     *
     * 精确到 `.toaster > .toast` —— 用 `[class*="toast"]` 会把外层容器 `.toaster`
     * 一起选进来，一条读成两条（P58 / P60 两批的那个「连出两遍」）。
     * 同时钉住「容器只许有一个」：容器真被渲染了两遍是另一条路，这里一并排除。 */
    async toasts() {
      await this.must('.toaster', { min: 0, max: 1, why: '<Toaster/> 只许挂一处' })
      return this.eval(`Array.from(document.querySelectorAll('.toaster > .toast')).map((e) => (e.textContent || '').trim()).filter(Boolean)`)
    },
    /** **页边圆点**（P62 收口 4）。真类是 `.mm-dot` / `.mm-<relation>`，
     * 不是 `.cm-margin-dot`（**整个前端里没有这个类**，P60 问题 #6 那两趟报的 0 是假的）。
     * 而且**只数编辑器落槽里那些**：`.mm-dot` 右栏「记忆」的图例里也有一份
     * （`.mem-legend .mm-dot`），页面通配会把图例一起数进去。 */
    async dots() {
      return this.eval(`(() => {
        const q = (s) => document.querySelectorAll(s).length
        const g = (s) => document.querySelectorAll('.cm-gutters ' + s).length
        return { 落槽合计: g('.mm-dot'), 图例: q('.mem-legend .mm-dot'), 页面合计: q('.mm-dot'),
                 冲突: g('.mm-conflict'), 印证: g('.mm-corroborated'), 缺依据: g('.mm-unsupported'),
                 延续: g('.mm-continuation'), 叠加: g('.mm-accumulation'), 合并: g('.mm-merge') }
      })()`)
    },
    /** **右键菜单 / 命令面板的条目**（P62 收口 4）。真类是 `.palette-item`，
     * 不是 `.context-menu`（那个类只在 `probes*.ts` 的老探针里，编辑器右键菜单不用它）。 */
    async menuItems(max = 20) { return this.texts('.palette-item', max) },
    /** **把 `<details>` 全摊开**，返回这一趟真摊开了几个（P62 收口 5）。
     *
     * 收着的 `<details>` 里的字 `innerText` **读不到**。轮次卡片的判据那几行就在里头 ——
     * P58 / P60 两批读回来都是 `[]`，而那不是「这几句没了」，是**没摊开**。 */
    async expandDetails(root = 'body') {
      return this.eval(`(() => {
        const r = document.querySelector(${JSON.stringify(root)}); if (!r) return -1
        const ds = Array.from(r.querySelectorAll('details')).filter((d) => !d.open)
        ds.forEach((d) => { d.open = true }); return ds.length
      })()`)
    },
    /** 读一块卡片的正文：**先摊开里面所有 `<details>`**，再取 `innerText`。 */
    async readCard(sel, idx = 0) {
      const n = await this.must(sel, { why: '要读的那块卡片' })
      const opened = await this.eval(`(() => {
        const el = document.querySelectorAll(${JSON.stringify(sel)})[${idx}]; if (!el) return -1
        const ds = Array.from(el.querySelectorAll('details')).filter((d) => !d.open)
        ds.forEach((d) => { d.open = true }); return ds.length
      })()`)
      await wait(120)
      const text = await this.eval(`(document.querySelectorAll(${JSON.stringify(sel)})[${idx}]?.innerText ?? null)`)
      return { n, opened, text }
    },
    // 找文字匹配的元素（按钮 / 菜单项）：sel 里 textContent 包含 txt 的第一个
    async findText(sel, txt, idx = 0) {
      return this.eval(`(() => { const all = Array.from(document.querySelectorAll(${JSON.stringify(sel)})).filter((e) => (e.textContent || '').includes(${JSON.stringify(txt)})); const el = all[${idx}]; if (!el) return null; el.scrollIntoView({ block: 'nearest' }); const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, cx: r.x + r.width / 2, cy: r.y + r.height / 2, n: all.length, text: (el.textContent || '').slice(0, 80), tag: el.tagName, cls: el.className?.toString?.().slice(0, 80) } })()`)
    },
    async mouse(type, x, y, opts = {}) { return c.send('Input.dispatchMouseEvent', { type, x, y, button: opts.button ?? 'left', clickCount: opts.clickCount ?? 1, modifiers: opts.modifiers ?? 0, buttons: opts.buttons }) },
    async clickAt(x, y, opts = {}) {
      const button = opts.button ?? 'left'; const cc = opts.clickCount ?? 1; const modifiers = opts.modifiers ?? 0
      await this.mouse('mouseMoved', x, y, { button: 'none', modifiers })
      for (let i = 1; i <= cc; i++) { await this.mouse('mousePressed', x, y, { button, clickCount: i, modifiers }); await this.mouse('mouseReleased', x, y, { button, clickCount: i, modifiers }) }
    },
    async click(sel, opts = {}) { const r = typeof sel === 'string' ? await this.rect(sel, opts.idx ?? 0) : sel; if (!r) throw new Error('click: 找不到 ' + (typeof sel === 'string' ? sel : JSON.stringify(sel))); await this.clickAt(r.cx, r.cy, opts); return r },
    async clickText(sel, txt, opts = {}) { const r = await this.findText(sel, txt, opts.idx ?? 0); if (!r) throw new Error(`clickText: 找不到 ${sel} 含「${txt}」`); await this.clickAt(r.cx, r.cy, opts); return r },
    async rclick(sel, opts = {}) { return this.click(sel, { ...opts, button: 'right' }) },
    async hover(x, y, modifiers = 0) { return this.mouse('mouseMoved', x, y, { button: 'none', modifiers }) },
    async insert(text) { return c.send('Input.insertText', { text }) },
    // key: 'a' / 'Enter' / 'ArrowDown'；mods: ['meta','shift','alt','ctrl']
    async key(key, mods = [], opts = {}) {
      const modifiers = mods.reduce((a, m) => a | MOD[m], 0)
      const isChar = key.length === 1
      const upper = isChar ? key.toUpperCase() : key
      const vk = VK[key] ?? (isChar && /[A-Z0-9]/.test(upper) ? upper.charCodeAt(0) : undefined)
      const code = CODE[key] ?? (isChar && /[A-Z]/.test(upper) ? 'Key' + upper : isChar && /[0-9]/.test(upper) ? 'Digit' + upper : key)
      const text = opts.text ?? (isChar && !mods.includes('meta') && !mods.includes('ctrl') ? (mods.includes('shift') ? upper : key) : undefined)
      const base = { key: isChar ? (mods.includes('shift') ? upper : key) : key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, modifiers }
      await c.send('Input.dispatchKeyEvent', { type: text ? 'keyDown' : 'rawKeyDown', ...base, ...(text ? { text, unmodifiedText: text } : {}), ...(opts.commands ? { commands: opts.commands } : {}) })
      await c.send('Input.dispatchKeyEvent', { type: 'keyUp', ...base })
    },
    async typeText(text) { for (const ch of text) { if (/[a-zA-Z0-9 ]/.test(ch)) await this.key(ch === ' ' ? 'Space' : ch, /[A-Z]/.test(ch) ? ['shift'] : []); else await this.insert(ch); await wait(15) } },
    /** 截图。**名字由调用方给，而且不许静默覆盖**（P49 ④ / P47 问题 #5）。
     *
     * P47 实拍：`darknarrow` / `cmdk` 两个步骤脚本把截图名写死成 `-old-`，
     * 新用户那一趟跑完，老用户那几张**被无声覆盖**了——台账上那几个文件名还在，
     * 里面的图已经是另一个身份的。截图是走查唯一的物证，**它被覆盖了得吵**。
     *
     * 两条闸：名字空 → 抛（写死默认值这条路直接堵死）；同名文件已经在 → 抛
     * （真要覆盖得显式 `{ overwrite: true }`，比如同一步重跑）。
     *
     * **第三条（P66 搬进仓库时加的）**：相对名要落在 `WALKTHROUGH_SHOT_DIR` 下，
     * **这个环境变量没设就抛**。原来这儿写死着一次会话的 scratch 绝对路径——
     * 那条路进了 git 之后在别的机器上会静默写到一个不存在 / 不相干的目录里，
     * 而截图是走查唯一的物证。要落在别处就传绝对路径。 */
    async shot(name, clip, opts = {}) {
      if (!name || typeof name !== 'string' || !name.trim()) {
        throw new Error('shot: 截图名得由调用方给——步骤脚本里写死默认名就是 P47 问题 #5 那次覆盖')
      }
      await wait(150)
      const fs = await import('node:fs')
      const dir = process.env.WALKTHROUGH_SHOT_DIR
      if (!name.startsWith('/') && !dir) {
        throw new Error('shot: 相对名要落在 WALKTHROUGH_SHOT_DIR 下，但这个环境变量没设——'
          + '不猜一个目录静默写进去（截图是走查唯一的物证）。'
          + '要么 export WALKTHROUGH_SHOT_DIR=<目录>，要么传绝对路径')
      }
      const p = name.startsWith('/') ? name : `${dir.replace(/\/$/, '')}/${name}`
      if (!opts.overwrite && fs.existsSync(p)) {
        throw new Error(`shot: ${p} 已经有一张了——覆盖它等于把上一趟的物证抹掉。`
          + '换个名字（把身份 / 步骤写进去），真要覆盖就显式传 { overwrite: true }')
      }
      const r = await c.send('Page.captureScreenshot', { format: 'png', ...(clip ? { clip: { ...clip, scale: 1 } } : {}) })
      fs.writeFileSync(p, Buffer.from(r.data, 'base64')); console.log('shot →', p); return p
    },
    /** **现在开着的是哪一篇**（判据用的那个 id，不是标题）。
     *
     * 读的是 app 自己记这件事的那一格：`App.tsx` 每次 `current` 变就写一次
     * `localStorage['memoket-note-active:' + api.getUser()]`，重启也是靠它回到上次那篇。
     * **不是另造一把尺子**，是问 app 它自己认为现在开着哪一篇。
     *
     * **身份默认从这个窗口自己身上读**，不写死一个名字（P68 B）：
     * 这里原来是 `user = 'terrence'`，于是身份不是 terrence 的那一趟（空库新用户）
     * **静默读了另一个人的那一格**，`localStorage.getItem` 读不到回 `null`——
     * 跟「产品压根没写」长得一模一样。P64 问题 #2 就是它，P66 三头各读一次才核清楚。
     * 量过：全部 6 批步骤脚本 + 这份驱动自己，**92 处裸调 / 5 处带参**——
     * 所以修的是默认值，不是去改 92 个调用点（改调用点漏一个就还是静默读错）。
     *
     * 读法跟 `api.getUser()` **同一条**（`?user=` 优先，其次
     * `localStorage['memoket-note-user']`）：不是「差不多一样」，是照抄它那两步，
     * 否则就又多了一把尺子。两样都没有就**抛**——猜一个身份正是这条的病根。
     * 显式传 `user` 仍然管用（跨身份读别人那一格时必须显式写出来）。 */
    async noteId(user) {
      const who = user ?? await this.eval(
        `(() => { try {
           const u = new URLSearchParams(location.search).get('user')
           return (u && u.trim()) || localStorage.getItem('memoket-note-user') || ''
         } catch (e) { return '' } })()`)
      if (!who) {
        throw new Error('noteId: 这个窗口的身份读不出来（?user= 和 localStorage["memoket-note-user"] 都是空的）'
          + '——不猜一个（猜就是 P64 问题 #2 那次静默读了别人那一格）；要跨身份读就显式传 user')
      }
      const key = JSON.stringify('memoket-note-active:' + who)
      return this.eval(`(() => { try { return localStorage.getItem(${key}) } catch (e) { return null } })()`)
    },
    /** 等到「开着的那一篇」变成 `id`（或超时）。 */
    async untilNote(id, ms = 15000) {
      const t0 = Date.now()
      for (;;) {
        if (await this.noteId() === id) return true
        if (Date.now() - t0 > ms) return false
        await wait(250)
      }
    },
    /** 按 **note id** 打开一篇：⌘K 搜标题 → 逐个候选点 → **每点一个核一次 id**。
     *
     * P47 问题 #4：两次 seed 各建了一篇同名的走查笔记，⌘K / 左栏树点的都是另一篇，
     * **差点把「改动页签没了」记成缺陷**。判据得是「打开之后的 note id」，不是「点了」。
     * 候选全点完还对不上就抛——**宁可吵，也别拿另一篇的屏当证据**。 */
    async openNoteById(id, title, { max = 6 } = {}) {
      if (!id) throw new Error('openNoteById: 得给 note id——按标题开就是 P47 问题 #4 那次')
      await this.key('Escape'); await wait(200)
      await this.key('k', ['meta']); await wait(900)
      await this.insert((title ?? '').slice(0, 8)); await wait(1200)
      const cands = await this.eval(`Array.from(document.querySelectorAll('[role="option"], [class*="palette"] [class*="item"], .palette-item')).map((e, i) => i).length`)
      for (let i = 0; i < Math.min(cands, max); i++) {
        const r = await this.eval(`(() => {
          const all = Array.from(document.querySelectorAll('[role="option"], [class*="palette"] [class*="item"], .palette-item'))
          const el = all[${i}]; if (!el) return null
          el.scrollIntoView({ block: 'center' })
          const b = el.getBoundingClientRect()
          return { cx: b.x + b.width / 2, cy: b.y + b.height / 2, text: (el.textContent||'').trim().slice(0,40) }
        })()`)
        if (!r) break
        await this.clickAt(r.cx, r.cy)
        if (await this.untilNote(id, 8000)) { console.log('开的是', id, '（第', i, '个候选：', r.text, '）'); return id }
        await this.key('Escape'); await wait(200)
        await this.key('k', ['meta']); await wait(900)
        await this.insert((title ?? '').slice(0, 8)); await wait(1000)
      }
      throw new Error(`openNoteById: 点了 ${Math.min(cands, max)} 个候选，开着的还是 ${await this.noteId()}，不是 ${id}`)
    },
    async setTheme(t) { return this.eval(`(window.memoketDesktop?.setTheme(${JSON.stringify(t)}), localStorage.setItem('memoket.theme', ${JSON.stringify(t)}), 'ok')`) },
    async viewport() { return this.eval('({ w: innerWidth, h: innerHeight, dpr: devicePixelRatio })') },
    // Electron 的 CDP 没有 Browser.setWindowBounds：用 Emulation 把视口按 900px 排版（版式 / 遮挡看得见；窗口 chrome 不变）。w=0 恢复。
    async resize(w, h) {
      if (!w) { await c.send('Emulation.clearDeviceMetricsOverride') } else { await c.send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 0, mobile: false }) }
      await wait(500); return this.viewport()
    },
    async cmText() { return this.eval(`(() => { const c = document.querySelector('.cm-content'); if (!c) return null; if (c.querySelector('.cm-placeholder')) return ''; return c.innerText })()`) },
    async focusEditor() { const ok = await this.eval(`(() => { const c = document.querySelector('.cm-content'); if (!c) return false; c.focus(); return document.activeElement === c })()`); if (!ok) throw new Error('编辑器聚焦失败'); await wait(80); return ok },
    async clearEditor() {
      for (let i = 0; i < 3; i++) {
        await this.eval(`document.querySelector('.cm-content')?.focus()`); await wait(120)
        await this.key('a', ['meta'], { commands: ['selectAll'] }); await wait(120)
        await this.key('Backspace'); await wait(250)
        if ((await this.cmText() ?? '') === '') return true
      }
      return false
    },
    async cmEnd() { await this.focusEditor(); await this.key('End', ['meta']); },
    async storage() { return this.eval(`Object.fromEntries(Object.keys(localStorage).map((k) => [k, (localStorage.getItem(k) || '').slice(0, 200)]))`) },
  }
  const mod = await import(stepPath.startsWith('/') ? stepPath : process.cwd() + '/' + stepPath)
  try {
    await mod.default(d, args)
  } finally {
    if (consoleLines.length) { console.log('--- renderer console (' + consoleLines.length + ') ---'); for (const l of consoleLines.slice(0, 40)) console.log(l) }
    c.close(); browser?.close()
  }
}
main().catch((e) => { console.error('FAIL', e.message); process.exit(1) })
