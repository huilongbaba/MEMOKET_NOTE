#!/usr/bin/env node
// ═══════════════════════════════════════════════════════════════════════════
// **「真跑一趟」的那条闸**（P74 A）：起一个假壳，把真的步骤脚本**真跑一遍**，
// 每一步的判据写在这儿、逐条核。
//
// ── 为什么有它 ──────────────────────────────────────────────────────────────
// P72 把 30 份步骤脚本收进了 `walkthrough/steps/`，`check-walkthrough-selectors.mts`
// 核「选的类名前端里有没有」、`check-walkthrough-runnable.mts` 核「装得进 node 吗 /
// 符不符合入口契约」。**这两条加起来只挡掉了三分之一**，P72 自己写着剩下的三分之二：
//
//     壳打不打得出来 / CDP 连不连得上 / **每一步跑起来对不对**
//     （`d.must()` 选不到 / 判据读回 null / 等得够不够 / 截图存没存下）
//
// 那三分之二里，只有「打不打得出 `.app`」非要打包不可。**剩下的都不用。**
// 这个文件把不用打包的那部分接上闸：
//
//     真 Chromium（`desktop/node_modules/electron`）
//   + 真前端（`frontend/dist`，`vite build` 的产物）
//   + 真后端（`backend/.venv` 跑源码 uvicorn，同源托管前端）
//   + 真 userData（`backend/scripts/walkthrough_udd.py` 那一套）
//   + 真 CDP（`--remote-debugging-port`）+ 仓库那份 `walkthrough/cdp.mjs`
//   + **真的步骤脚本**（`walkthrough/steps/*.mjs`，一个字节都不改）
//
// ── **够不着什么**（照 P72 的写法，写在闸自己身上，不许含糊）────────────────
//  1. **`npm run dist` 打不打得出壳** —— 假壳换掉的正是这一层。
//     `pyinstaller` / `electron-builder` / adhoc 重签 / `extraResources` / 公证
//     这一圈，这条闸一个字都答不了。（`desktop/package.json` 的 `build.extraResources`
//     被写坏那次，唯一发现它的是 `backend/tests/test_packaging.py`，不是这儿。）
//  2. **主进程那一圈**：`backend.ts` 的端口重试 / `MEMOKET_NOTE_PARENT_PID` 自杀 /
//     后端崩了重起 / 换端口 `loadURL`；应用菜单；`pickDirectory` / `exportCreds` /
//     `slidesToPdf`；**屏幕活动的采集**（在主进程里）。假壳的 preload 只暴露
//     `setTheme` / `rememberUser` / `backendInfo` 三件，其余一件不挂
//     （理由见 `fakeshell/preload.cjs`：挂一个接不住的桩比没有更难查）。
//     → 走查第 ⑦ 步（选 vault 的系统对话框）和第 ⑧ 步的采集那一半，这儿跑不到。
//  3. **482 篇老用户那一趟**：默认跑的是**空库新用户**那个身份。真库不进 git，
//     拷一份还要扫全库换真 key——那一圈留在走查的人手上（`--real-db` 能指过去，
//     但**默认不指**：一条会去碰真库的闸不该是默认行为）。
//  4. **CI 跑不了**：要 `desktop/node_modules/electron`（一个真 Chromium）、
//     `backend/.venv`、`frontend/dist`。缺任何一样这条闸**当场红着退**，
//     **不是静默跳过**——「没装就算了」的闸是一条永远绿的闸。
//     所以它不在 `npm test` 里；`npm test` 里的是
//     `check-walkthrough-fakeshell.mts`（核「这条路还接着吗」，核不了「它跑得绿吗」）。
//  5. **一次只跑得到走查十一步里的几步**。跑哪几步、每一步核什么，全在下面
//     `PLAN` 里明写；**没核的就是没核**，别从「这条闸绿了」推出别的。
//  6. **收尾那个通道对照组是从 node 发的**，不经渲染进程：它证得了「后端收得到、
//     打得出来」，证不了「前端那一头发得出去」。详见文件末尾那一段。
//
// ── 怎么证明它会红 ────────────────────────────────────────────────────────
// 把某一步里的选择器改错（比如 `steps/bnew.mjs` 里的 `.pane-tab` → `.pane-tabX`），
// 这条闸必须红，**而且红的是那一步**（输出里点名到步骤文件 + 哪一条判据）。
// 突变验的刀和结果记在 `docs/TRACELOG-product.md` 的 P74 节。
//
// ── 怎么跑 ────────────────────────────────────────────────────────────────
//     cd frontend
//     WALKTHROUGH_SCRATCH=<一个空目录> node scripts/run-walkthrough-fakeshell.mjs
//     # 只跑一步：--only whoami52
//     # 留着壳不收摊（自己接 CDP 上去看）：--keep
// ═══════════════════════════════════════════════════════════════════════════
import { spawn } from 'node:child_process'
import net from 'node:net'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND = path.resolve(HERE, '..')
const ROOT = path.resolve(FRONTEND, '..')
const WALK = path.join(FRONTEND, 'scripts/walkthrough')
const STEPS = path.join(WALK, 'steps')

const argv = process.argv.slice(2)
const only = argv.includes('--only') ? argv[argv.indexOf('--only') + 1] : null
const keep = argv.includes('--keep')
const USER = 'p74-newbie'

// ── 走哪几步、每一步核什么 ────────────────────────────────────────────────
// 判据一律**对着步骤脚本自己打出来的那几行**问，因为那几行正是走查台账里抄的数。
// `must` 是「这一行必须出现」，`refute` 是「这一行绝不许出现」（反例，防止
// 判据宽到什么都算过）。**每一步至少一条 `refute`**：只有 `must` 的闸，
// 步骤脚本整个不跑、只打一句话，照样可能全过。
const PLAN = [
  {
    name: 'whoami52',
    step: 'whoami52.mjs',
    args: [],
    why: '每次起壳之后第一条（P50 量具坑 #2）：窗口连的是哪个后端、那个后端开的是哪个库、现在开着哪一篇',
    must: [
      // 窗口真从后端那个 origin 加载的（不是 file:// 也不是 vite 的 5173）
      [/窗口 origin: http:\/\/127\.0\.0\.1:(\d+)/, (m, ctx) => Number(m[1]) === ctx.backendPort,
        '窗口 origin 得是后端那个端口'],
      // `/api/health` 真答话了，而且 data_dir 指着这一趟的 udd（不是 ~/Library 里那份）
      [/\/api\/health: .*"data_dir"/, null, '/api/health 得报出 data_dir'],
      // 身份是 udd 里 identity.json 写的那个——**不是前端随手生成的 user-xxxxxx**
      // （P60 #2：没写 identity.json 就会静默回落，482 篇一篇看不见）
      [new RegExp(`窗口自己认的身份: ${USER}$`, 'm'), null, '身份得是 identity.json 里那个'],
      // 带 X-User-Id 头问得到 200（P47 那版拿 `?user=` 查询串量身份，一律 []）
      [/带头问 \/api\/notes\?limit=1: 200 /, null, '带头问 /api/notes 得回 200'],
      // 自检横幅（P45 #2）。**这一格到 P74 才第一次真的在量东西**：
      // `whoami52.mjs` 原来选的三个类名前端里一个字都没有，于是它每批都报 `(没有)`。
      // 选择器改成真的那个 id 之后，这条判据才分得开「没有横幅」和「选不到横幅」
      // ——分得开的证据是第 ③ 刀（故意报错一个后端 pid，这一行当场变成「⚠︎ 连错后端了」）。
      [/自检横幅: \(没有\)/, null, '健康的假壳上不该有自检横幅'],
    ],
    refute: [
      [/窗口自己认的身份: user-/, '身份回落成前端随机生成的那种（P60 #2 的症状）'],
      [/窗口自己认的身份: \(默认\)/, '身份根本没挂上去'],
      [/自检横幅: ⚠︎ 连错后端了/, '界面在喊「连错后端了」——假壳的 backendInfo() 给错了 pid'],
    ],
  },
  {
    name: 'bnew',
    step: 'bnew.mjs',
    args: ['@llmPort'],       // 假模型端点的端口，跑之前替换成真端口
    why: '走查表第 ①②③⑧⑨⑪ 步（空库新用户那一趟）——**一个字节没改的那份步骤脚本**。'
       + '判据只挑假壳够得着的那几格：⑧ 的采集那一半要主进程，这儿核不了（见「够不着什么」第 2 条）',
    must: [
      // ① 第一次打开：状态栏那句 + **一个内网 IP 都没有**（P19 #1 / P17 #1）
      [/含「还没配模型」: true/, null, '状态栏得摆「还没配模型」'],
      [/含「去设置」: true/, null, '状态栏得摆「去设置」'],
      // ① 后半：填假端点 → 测一下 → 保存 → 那句话消失（P47）
      [/测一下结果: 连上了/, null, '假模型端点得连得上（假模型监听的端口 = 前端填进去的端口）'],
      [/含「模型名还没填」: true/, null, '没点 chip 时得提示模型名还没填'],
      // ⚠️ 这一格读回 **true**，**那是对的行为不是缺陷**（P58 ①，`bnew3.mjs` 的头一段写着）：
      // `bnew.mjs` 填完地址就按保存、**没点模型名那个 chip**，于是 toast 是
      //「保存了，但模型还没配全」、红条留着。**P70 在真打好的壳上读到的也正是 true**
      //（`p70/log/bnew.txt:15`），而同一批的 `bnew3.mjs`（补上点 chip 那一步）读到 false。
      // 第一版这条判据抄成了 false，闸当场红——**红得对**：判据比产品窄的又一张脸，
      // 只不过这次窄在「我以为该 false」。点 chip 那条路由下面 `bnew3` 那一步核。
      [/保存之后「还没配模型」还在吗（该 false）: true/, null,
        '没点 chip 就保存 → 红条**该**留着（P58 ①；点了 chip 的那条路在 bnew3 那一步）'],
      // ②③ 新建 → 打正文 → 右栏页签 / 空库两句
      [/正文字数: (\d+)/, (m) => Number(m[1]) > 20, '正文得真打进编辑器'],
      [/右栏页签: \[".+"\]/, null, '右栏页签得选得到（`.pane-tab`）'],
      [/P32 #3 空库图例收成一句: true/, null, '空库图例那一句（P32 #3）'],
      [/P35 #8 空托盘收成一句: true/, null, '空托盘那一句（P35 #8）'],
      // ⑨ ⌘K
      [/项数: (\d+)/, (m) => Number(m[1]) > 0, '⌘K 得摆出去处'],
      // ⑪ 深色 + 900px
      [/深色 body: (rgb\([^)]*\))\s+近白大块: (\d+)/, (m) => Number(m[2]) === 0,
        '深色下不许有近白大块'],
      [/900px 横向溢出: (\d+)/, null, '900px 那一格得量得出来'],
    ],
    refute: [
      // 内网 IP 一个都不许露（走查第 ① 步每批都核的反例）
      [/含「192\.168」: true/, '状态栏露了内网 IP'],
      [/含「10\.0\.」: true/, '状态栏露了内网 IP'],
      [/正文字数: 0$/m, '编辑器里一个字都没进去'],
      [/右栏页签: \[\]/, '页签读回空数组——「选不到 ≠ 没有」那一张脸'],
      [/没找到那一行，①后半没摆出来/, '状态栏那一行没摆出来，① 后半整段跳过了'],
      // **假壳自己的错，不是产品的错**：`backendInfo()` 回的 pid 要是主进程自己的，
      // 界面就摆这条横幅（P45 #2 的自检）。第一版正是这样，被这条反例抓出来的。
      [/⚠︎ 连错后端了/, '界面在喊「连错后端了」——假壳的 backendInfo() 给错了 pid'],
    ],
  },
  {
    name: 'bnew3',
    step: 'bnew3.mjs',
    args: ['@llmPort'],
    why: '走查第 ① 步的**另一半**（P58 ①，P47 的原话）：填端点 → 测一下 → **点 chip** → 保存 '
       + '→ 红条和状态栏那句同时消失、toast 恰好 1 条、**库里真落了**',
    must: [
      [/模型名 chip: \[\{"i":\d+,"t":"fake-/, null, '「先用第一个」那个 chip 得摆出来'],
      [/点完之后哪个格里写着模型名: \["fake-[^"]*"\]/, null, '点完 chip 模型名得落进输入格'],
      [/保存之后「还没配模型」还在吗（该 false）: false/, null, '点了 chip 再保存，红条得消失'],
      [/红条还在吗: false/, null, '红条那一整句也得消失'],
      // toast **恰好 1 条**（P43 / P47；`d.toasts()` 走的是精确类名，不是通配——
      // 通配会把外层 `.toaster` 一起选中，一条读回来是两条一模一样的字，P58/P60 栽过）
      [/toast: \["已切换到本地模型：fake-[^"]*"\]/, null, 'toast 恰好 1 条、逐字对'],
      // **库里真落了**，而且 `local_base_url` 里的端口 = 假模型真正监听的那个端口。
      // 这一条是 P68 那条老坑（`go.sh` 的 LLM 端口跟 udd 库里 `provider_config` 对不上）
      // 第一次有闸看着：**「填进去了」跟「落库了」跟「落的是同一个端口」是三件事**。
      [/库里: \{"provider":"local","local_base_url":"http:\/\/127\.0\.0\.1:(\d+)\/v1","local_model":"fake-[^"]*"\}/,
        (m, ctx) => Number(m[1]) === ctx.llmPort, '库里落的 base_url 端口得 = 假模型监听的端口'],
      // 900px 标签条那一格（P52 #3 系列，每批都判成「不是缺陷」的那一个）
      [/"stripScroll":\{"sw":(\d+),"cw":(\d+),"overflowX":"auto"\}/,
        (m) => Number(m[1]) > Number(m[2]), '900px 标签条 sw > cw 且 overflow-x: auto'],
    ],
    refute: [
      [/模型名 chip: \[\]/, 'chip 一个都没选到——「选不到 ≠ 没有」'],
      [/库里: \{"provider":"local","local_base_url":null/, '库里根本没落 base_url'],
      // ⚠️ 这儿**不放**「连错后端了」那条反例：`bnew3.mjs` 从头到尾没打印过整页文本
      //（它打的是 `t.includes(...)` 的布尔值），那条反例在它的输出上**永远开不了火**。
      // 第 ③ 刀当场量到了这件事：预测它会点名 bnew3，实际只点名了 bnew。
      // **一条永远开不了火的反例不是反例**，删掉比留着好看强。
    ],
  },
]

// ── 小工具 ────────────────────────────────────────────────────────────────

// 起过的子进程都记在这儿，**任何一条出口都先收摊**（`die()` 也走这条）。
const procs = []
function teardown() {
  for (const p of procs) { try { p.kill('SIGKILL') } catch { /* 已经没了 */ } }
}
process.on('exit', () => { if (!keep) teardown() })

const wait = (ms) => new Promise((r) => setTimeout(r, ms))

function freePort() {
  return new Promise((res, rej) => {
    const s = net.createServer()
    s.on('error', rej)
    s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)) })
  })
}

/** 红着退。**不 throw**：throw 出来的那一大坨栈会把真正的那句话推到屏幕外面，
 *  而这条闸的输出正是给人看「哪一步、哪一条判据」的。 */
function die(msg) { console.error('\n✗ ' + msg); teardown(); process.exit(1) }

/** 前置一样都不许缺。**缺了当场红，不是静默跳过**（够不着什么 · 第 4 条）。 */
function preflight() {
  const need = [
    [path.join(ROOT, 'desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron'),
      '真 Chromium：desktop 那边 `npm i` 过没有'],
    [path.join(ROOT, 'backend/.venv/bin/python'), '后端 venv'],
    [path.join(FRONTEND, 'dist/index.html'), '前端 dist：先 `cd frontend && npm run build`'],
    [path.join(WALK, 'cdp.mjs'), '走查驱动'],
    [path.join(ROOT, 'backend/scripts/walkthrough_udd.py'), 'userData 造法'],
    [path.join(ROOT, 'backend/scripts/walkthrough_fakellm.py'), '假模型端点'],
    [path.join(WALK, 'fakeshell/main.cjs'), '假壳的主进程'],
    [path.join(WALK, 'fakeshell/preload.cjs'), '假壳的 preload'],
  ]
  const missing = need.filter(([p]) => !fs.existsSync(p))
  if (missing.length) {
    console.error('前置缺了 ' + missing.length + ' 样：')
    for (const [p, why] of missing) console.error(`  · ${p}\n      ← ${why}`)
    die('前置不齐——这条闸**不会**因此变绿')
  }
  for (const { step } of PLAN) {
    if (!fs.existsSync(path.join(STEPS, step))) die(`PLAN 里点名的步骤脚本不在：steps/${step}`)
  }
}

/** userData：身份写死、目录现建。**真库一个字节不碰**（够不着什么 · 第 3 条）。 */
function makeUdd(scratch) {
  const udd = path.join(scratch, 'udd')
  fs.mkdirSync(path.join(udd, 'data'), { recursive: true })
  fs.mkdirSync(path.join(udd, 'journey'), { recursive: true })
  fs.writeFileSync(path.join(udd, 'identity.json'),
    JSON.stringify({ user: USER, saved_at: '2026-09-21T00:00:00.000Z' }))
  const back = JSON.parse(fs.readFileSync(path.join(udd, 'identity.json'), 'utf8'))
  if (back.user !== USER) die('identity.json 写完读回来不对')
  return udd
}

async function waitHealth(port, ms = 60000) {
  const t0 = Date.now()
  for (;;) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/api/health`, { signal: AbortSignal.timeout(2000) })
      if (r.ok) return await r.text()
    } catch { /* 还没起来 */ }
    if (Date.now() - t0 > ms) return null
    await wait(500)
  }
}

/** 壳的窗口起来了没有：CDP 应答**而且**真有一个 page target。
 *  光有 `/json/version` 不够——那一刻窗口还没建出来，下一条 cdp.mjs 就会
 *  「没有 page target: []」。`fetch` 一律带 timeout：上一趟留下的壳占着端口、
 *  接受连接却不回时，不带 timeout 的探针会永远挂着——**一个会永远挂着的探针不是探针**（P58）。 */
async function waitPage(port, ms = 60000) {
  const t0 = Date.now()
  for (;;) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json`, { signal: AbortSignal.timeout(3000) })).json()
      const p = list.find((t) => t.type === 'page' && /127\.0\.0\.1:\d+/.test(t.url))
      if (p) return p.url
    } catch { /* 还没起来 */ }
    if (Date.now() - t0 > ms) return null
    await wait(500)
  }
}

function runStep(cdpPort, stepFile, args, shotDir, logFile) {
  return new Promise((res) => {
    const out = []
    const p = spawn(process.execPath, [path.join(WALK, 'cdp.mjs'), String(cdpPort),
      path.join(STEPS, stepFile), ...args], {
      cwd: FRONTEND,
      env: { ...process.env, WALKTHROUGH_SHOT_DIR: shotDir, ELECTRON_RUN_AS_NODE: undefined },
    })
    p.stdout.on('data', (b) => out.push(b))
    p.stderr.on('data', (b) => out.push(b))
    p.on('close', (code) => {
      const text = Buffer.concat(out).toString('utf8')
      fs.writeFileSync(logFile, text)
      res({ code, text })
    })
  })
}

// ── 主流程 ────────────────────────────────────────────────────────────────
const scratch = process.env.WALKTHROUGH_SCRATCH
if (!scratch) die('得给 WALKTHROUGH_SCRATCH（放 udd / 截图 / 日志的目录）——不猜一个目录静默写进去')
fs.mkdirSync(scratch, { recursive: true })
const shotDir = path.join(scratch, 'shots'); fs.mkdirSync(shotDir, { recursive: true })
const logDir = path.join(scratch, 'log'); fs.mkdirSync(logDir, { recursive: true })

preflight()
const udd = makeUdd(scratch)
const backendPort = await freePort()
const cdpPort = await freePort()
const llmPort = await freePort()
console.log(`假壳：后端 ${backendPort} / CDP ${cdpPort} / 假模型 ${llmPort} / udd ${udd}`)

// 假模型端点。**`go.sh` 那条老坑**（P68 栽过）：壳里前端填进去的端口和这个进程
// 监听的端口必须是同一个。这儿两边是**同一个变量**，抄错这件事在结构上没地方发生。
const llm = spawn(path.join(ROOT, 'backend/.venv/bin/python'),
  [path.join(ROOT, 'backend/scripts/walkthrough_fakellm.py'), String(llmPort), '--mode', 'ok'],
  { cwd: path.join(ROOT, 'backend'), stdio: ['ignore', 'pipe', 'pipe'] })
procs.push(llm)
const llmLog = fs.createWriteStream(path.join(logDir, 'fakellm.log'))
llm.stdout.pipe(llmLog); llm.stderr.pipe(llmLog)

const be = spawn(path.join(ROOT, 'backend/.venv/bin/python'),
  ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(backendPort)], {
  cwd: path.join(ROOT, 'backend'),
  env: {
    ...process.env,
    PYTHONPATH: path.join(ROOT, 'backend'),
    PYTHONUNBUFFERED: '1',
    MEMOKET_NOTE_WEB_DIR: path.join(FRONTEND, 'dist'),
    KITE_DATA_DIR: path.join(udd, 'data'),
    MEMOKET_JOURNEY_DIR: path.join(udd, 'journey'),
  },
  stdio: ['ignore', 'pipe', 'pipe'],
})
procs.push(be)
const beLog = fs.createWriteStream(path.join(logDir, 'backend.log'))
be.stdout.pipe(beLog); be.stderr.pipe(beLog)

const health = await waitHealth(backendPort)
if (!health) die(`后端 ${backendPort} 起不来，看 ${path.join(logDir, 'backend.log')}`)
console.log('后端起来了：' + health.slice(0, 160))

// `ELECTRON_RUN_AS_NODE` 必须摘掉：留着的话 Electron 当 node 跑，**没有窗口**，
// 而症状是「CDP 连不上」，看起来像端口问题。（README 每批都重记一遍的那条。）
// `FAKESHELL_BACKEND_PID`：界面拿 `backendInfo()` 跟 `/api/health` 自报的那份对一次
// （P45 #2）。给错了它就摆「⚠︎ 连错后端了」——**那会是一条假缺陷**。
const eenv = {
  ...process.env,
  FAKESHELL_BACKEND_PORT: String(backendPort),
  FAKESHELL_BACKEND_PID: String(be.pid),
}
delete eenv.ELECTRON_RUN_AS_NODE
delete eenv.VSCODE_ESM_ENTRYPOINT
delete eenv.VSCODE_IPC_HOOK
delete eenv.VSCODE_PID
const el = spawn(path.join(ROOT, 'desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron'),
  [path.join(WALK, 'fakeshell/main.cjs'), `--user-data-dir=${udd}`, `--remote-debugging-port=${cdpPort}`],
  { env: eenv, stdio: ['ignore', 'pipe', 'pipe'] })
procs.push(el)
const elLog = fs.createWriteStream(path.join(logDir, 'electron.log'))
el.stdout.pipe(elLog); el.stderr.pipe(elLog)

const pageUrl = await waitPage(cdpPort)
if (!pageUrl) die(`假壳的窗口没起来，看 ${path.join(logDir, 'electron.log')}`)
console.log('窗口起来了：' + pageUrl)
await wait(3000)

// ── 逐步跑 + 逐条判 ───────────────────────────────────────────────────────
const ctx = { backendPort, cdpPort, llmPort, user: USER }
const failures = []
let checked = 0
for (const s of PLAN) {
  if (only && s.name !== only) continue
  console.log(`\n── ${s.name}（steps/${s.step}）`)
  const args = s.args.map((a) => (a === '@llmPort' ? String(llmPort) : a))
  const { code, text } = await runStep(cdpPort, s.step, args, shotDir, path.join(logDir, `${s.name}.txt`))
  if (code !== 0) {
    failures.push(`${s.name}（steps/${s.step}）：cdp.mjs 退出码 ${code}`
      + `\n    尾巴：${text.trim().split('\n').slice(-6).join('\n    ')}`)
    continue
  }
  for (const [re, fn, why] of s.must) {
    checked++
    const m = text.match(re)
    if (!m) { failures.push(`${s.name}（steps/${s.step}）· 缺判据「${why}」：${re} 没命中`); continue }
    if (fn && !fn(m, ctx)) failures.push(`${s.name}（steps/${s.step}）· 判据「${why}」命中了但不对：${JSON.stringify(m[0])}`)
  }
  for (const [re, why] of s.refute) {
    checked++
    if (re.test(text)) failures.push(`${s.name}（steps/${s.step}）· 反例出现了「${why}」：${re}`)
  }
  console.log(`   判据 ${s.must.length} + 反例 ${s.refute.length} 条`)
}

// ── 收尾：`save-guard` 那条 warn 一条都没有吗 ──────────────────────────────
//
// **一个「0」只有在同一条通道上同时量到一个非 0 时才算数**（P70 B 那一课：
// `save-guard` 0 条、而同通道 `harness-sync` 有条数 = 通道是活的不是哑的）。
// 假壳这几步**不跑 harness**，`harness-sync` 天然是 0，
// 于是 P70 那个对照组在这儿不成立 —— **那就现造一个**：
// 往同一个端点发一条带特征字样的 warn，它落进后端日志才说明这条槽是通的。
//
// ⚠️ **够不着的那一半**：这条探针是从 node 发的，走的是同一个端点 `/api/client-log`、
// 同一个日志槽，但**不经渲染进程**。所以它证得了「后端这一头收得到、打得出来」，
// 证不了「前端那一头发得出去」。真要连那一半一起证，得让页面自己发一条——
// 那要一个专门的步骤脚本，而 PLAN 里只放走查本来就在跑的那几步。
const CHANNEL_PROBE = 'p74-channel-probe'
if (!only) {
  checked += 2
  try {
    const r = await fetch(`http://127.0.0.1:${backendPort}/api/client-log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-User-Id': USER },
      body: JSON.stringify({ level: 'warn', message: CHANNEL_PROBE, stack: '', where: CHANNEL_PROBE }),
      signal: AbortSignal.timeout(5000),
    })
    if (!r.ok) failures.push(`通道对照组：POST /api/client-log 回 ${r.status}`)
  } catch (e) {
    failures.push(`通道对照组：POST /api/client-log 发不出去（${e.message}）`)
  }
  await wait(600)
  const beText = fs.readFileSync(path.join(logDir, 'backend.log'), 'utf8')
  const alive = (beText.match(new RegExp(CHANNEL_PROBE, 'g')) ?? []).length
  const guard = (beText.match(/save-guard/g) ?? []).length
  if (alive < 1) {
    failures.push('通道对照组：探针那一条没进后端日志 —— 这条槽是哑的，'
      + `下面那个「save-guard ${guard} 条」什么都不说明`)
  } else if (guard !== 0) {
    failures.push(`护栏那条 warn 出现了 ${guard} 次 —— `
      + 'P70 B 的护栏在这一趟里**拦过一次该存的保存**（或者真拦到了一次退回），去看后端日志')
  }
  console.log(`\n── 通道对照组：探针 ${alive} 条（活的）/ save-guard ${guard} 条`)
}

if (!keep) teardown()
await wait(300)

const ran = PLAN.filter((s) => !only || s.name === only)
console.log(`\n跑了 ${ran.length} 步 / 核了 ${checked} 条判据（截图在 ${shotDir}）`)
if (failures.length) {
  console.error(`\n✗ ${failures.length} 条没过：`)
  for (const f of failures) console.error('  · ' + f)
  process.exit(1)
}
if (checked === 0) { console.error('\n✗ 一条判据都没核到——那不叫过'); process.exit(1) }
console.log('✓ 假壳上这几步都跑通了')
