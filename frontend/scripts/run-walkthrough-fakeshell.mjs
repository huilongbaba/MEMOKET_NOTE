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
//     **P76 之后是七步 ①②③④⑤⑥⑨⑩⑪**（⑦ 和 ⑧ 的采集那一半仍然够不着，见第 2 条）。
//  6. **收尾那个通道对照组是从 node 发的**，不经渲染进程：它证得了「后端收得到、
//     打得出来」，证不了「前端那一头发得出去」。详见文件末尾那一段。
//  7. **第 ⑩ 步「关掉重开」重起的是壳，不是后端**（P76 加的那一步）。
//     后端端口一换，页面的 origin 就跟着换，`localStorage` 里的身份 / 标签条 /
//     「上次开着哪一篇」那几格**当场清空**——那一趟量的就不是「重开」了。
//     所以后端和假模型全程不动，**关掉重起的是 Electron 那个进程**
//     （`ctx.shellPids` 前后两个 pid 不一样，第 ⑩ 步有一条判据专门盯这件事）。
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
import { spawn, spawnSync } from 'node:child_process'
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
/** `ok` 档一轮智能续写之后那一篇有多长（P74 在**真打好的壳**上读到的是 105 → 205）。
 *  ⑥ 的三处判据（编辑器、库、重开之后的正文字数）**用同一个常数**：
 *  三处各抄一遍那个数，改错一处另外两处不会吵——那正是「两把尺」那类坑。 */
const ROUNDS_LEN = 205

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
      // ── ⑧ 的**知情屏**那一半（P78 B①）────────────────────────────────────
      // **P76 之前这一格一条判据都没有。** `bnew.mjs` 每一趟都在打它（`知情屏在吗` /
      // `两个钮` / `facts` / 「留多久」那一行），而 `PLAN` 里没人接——
      // 于是走查台账上抄着的那几个数，假壳这条闸**一个都没在核**。
      // 文件头「够不着什么」第 2 条说的是 ⑧ 的**采集**那一半要主进程；
      // 知情屏这一半是纯渲染进程 + 后端，**一直够得着，只是没人接线**。
      // **「够不着」和「没接」是两件事**，混在一起就变成了一句永远成立的免责。
      [/知情屏在吗: 1$/m, null, '知情屏得恰好一个（P21 #1）'],
      [/两个钮: \["开始记录","先不开"\]/, null, '知情屏那两个钮逐字、连顺序（P21 #1）'],
      [/"consent":1,"facts":5/, null, '知情五条 facts（P32 #4）'],
      // **「留多久」里的数是从后端读的**（P21 #1 / P32 #4）：写死在前端的话，
      // 后端改了保留期这一行不会跟着变，而用户按这一行的数做决定。
      [/「留多久」那一行（从后端读的数）: 描述留 1 个月（30 天），缩略图留 1 周（7 天）/, null,
        '「留多久」那一行的数从后端读（P21 #1 / P32 #4）'],
      // ⑨ ⌘K：**项数逐个对，不是「大于 0」**。「大于 0」这条判据，
      // 18 个去处掉成 1 个照样过——跟 ④ 那条钉死 19 项是同一条理由。
      [/项数: (\d+)/, (m) => Number(m[1]) === 18, '⌘K 得摆 18 个去处（空库新用户这一档）'],
      [/搜「屏幕」: \["今天的屏幕活动","这一周的屏幕活动（最近 7 天的回顾）","屏幕活动标签"\]/, null,
        '⌘K 搜「屏幕」恰好 3 条、逐字连顺序'],
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
      // ⑧ 的两张脸（P78 B①）
      [/知情屏在吗: 0$/m, '知情屏选不到——「选不到 ≠ 没有」那一张脸'],
      [/,"facts":0[,}]/, '五条 facts 一条都没读到（选择器过时了）'],
      [/搜「屏幕」: \[\]/, '⌘K 搜「屏幕」读回空数组——选不到 ≠ 没有'],
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
  // ═══════════════════════════════════════════════════════════════════════
  // **P76 加的四步**（P74 留的第 ① 条：「十一步里 ④⑤⑥⑩ 够得着但还没进 PLAN」）。
  // 加的**只有 `PLAN`**：`steps/*.mjs` 一个字节没改（P74 立的规矩）。
  // ⑦ 和 ⑧ 的采集那一半仍然够不着（要主进程，见文件头「够不着什么」第 2 条）。
  // ═══════════════════════════════════════════════════════════════════════
  {
    name: 'b1old',
    step: 'b1old.mjs',
    args: [],
    why: '走查第 ④ 步（`/` 菜单全项 + Esc + P49 ③ 逐字回退）和第 ⑤ 步（右键六项 + 选区）。'
       + '这一份步骤脚本本来是老用户那一趟的 ①③④⑤⑨⑪，**判据只挑 ④⑤ 那两格**：'
       + '①③ 的右栏记忆要一份真知识库（假壳默认空库，`命中行` 天然是 null），'
       + '⑨⑪ 上面 `bnew` 已经核过一遍，**重复核一遍不叫多核了一格**',
    must: [
      // ④ `/` 菜单：P17 #2 那格钉的是 **19 项**，P74 在真壳上读到的也是 19。
      // **逐字对两头**（第一项 + 最后一项），只对项数的话，19 个「空表格」也算过。
      [/`\/` 菜单项数: (\d+)/, (m) => Number(m[1]) === 19, '`/` 菜单得摆 19 项（P17 #2）'],
      [/项: \["用 AI 写描述你想写什么，会结合上下文和你的知识库",/, null,
        '`/` 菜单第一项逐字'],
      [/"流程图插入一个 mermaid 模板"\]/, null, '`/` 菜单最后一项逐字'],
      [/Esc 之后还剩几项: 0$/m, null, 'Esc 得把 `/` 菜单关干净'],
      // P49 ③：末尾留着那个 `/` **是对的**，不判缺陷；退三下之后**逐字**回到打 `/` 之前
      [/正文末尾（P49 ③：`\/` 留着是对的）: "\\n\\n\/"/, null,
        '末尾那个 `/` 留着（P49 ③ 判成不是缺陷）'],
      [/收尾之后逐字回到打 `\/` 之前了吗: true/, null, '退三下之后正文得逐字回到打 `/` 之前'],
      // ⑤ 右键六项：**逐字连顺序一起对**（`d.menuItems()` 走的是真类名 `.palette-item`）
      [/右键菜单: \["校验","重写","润色","扩展上下文","来龙去脉","自定义提示…"\]/, null,
        '右键菜单逐字六项（顺序也对）'],
      [/选区还在吗: "(.+)"/, (m) => m[1].length > 4, '右键之后选区得还在（P47 那条：先分清「没点上」）'],
    ],
    refute: [
      [/`\/` 菜单项数: 0/, '`/` 菜单一项都没选到——「选不到 ≠ 没有」'],
      [/Esc 之后还剩几项: [1-9]/, 'Esc 关不掉 `/` 菜单'],
      [/收尾之后逐字回到打 `\/` 之前了吗: false/, '退完没回到原样（P49 ③ 那条不变式破了）'],
      [/右键菜单: \[\]/, '右键菜单读回空数组——P62 修过的那张脸（`.context-menu` 前端里没有）'],
      [/找不到那一行，右键这一格没摆出来/, '⑤ 整段跳过了——「没跑」跟「跑过了没问题」得分开'],
    ],
  },
  {
    name: 'ctxmenu52',
    step: 'ctxmenu52.mjs',
    // 第 8 行是 `b1old.mjs` 那三段 SEED 的最后一段（实测：「预热名单回收了 860 份…」）。
    // 截图名**从参数来**，这一份本来就是这么写的。
    args: ['8', 'p76-fs-ctx-light.png'],
    why: '走查第 ⑤ 步**单独一格**：上面 `b1old` 里那一格是顺带核的，这一格是专门核它的'
       + '——`selectLineAndRightClick()` 会先把那一行滚进视口中间再读一次 bbox（P47 那条）',
    must: [
      // 选中的**整行逐字**。只核「选区非空」不够：P47 栽的正是「选到了别的一行」。
      [/选中: "预热名单回收了 860 份，转化率按渠道排了一遍。"/, null, '选中的得是那一整行，逐字'],
      [/右键菜单: \["校验","重写","润色","扩展上下文","来龙去脉","自定义提示…"\]/, null,
        '右键六项逐字（顺序也对）'],
      // **截图存没存下**——P72 把这一条写在「够不着的那三分之二」里。
      // 这一份的截图名**本来就从参数来**（`args[1]`），所以这儿顺带钉住那件事：
      // 落盘的得是 `PLAN` 给的那个名字，不是脚本里写死的默认名。
      [/shot → .*\/p76-fs-ctx-light\.png$/m, null, '截图按 `PLAN` 给的名字落了盘'],
    ],
    refute: [
      [/右键菜单: \[\]/, '右键菜单空的——「选不到 ≠ 没有」'],
      [/p47-5-old-ctx-light\.png/, '落盘的是脚本里写死的默认名，不是 `PLAN` 给的那个'],
      [/选中: ""/, '压根没选上（选区空）'],
      [/选中: "预热名单回收了 860 份，转化率按渠道排了一遍。[^"]/, '选区越过了那一行'],
    ],
  },
  // ═══════════════════════════════════════════════════════════════════════
  // **P78 B① 加的这一步**：走查第 ② 步那一格（意图三格预填 + 「预填」角标），
  // 它**一直够得着，只是从来没人接线**。
  //
  // `b1b.mjs` 早就在仓库里，每一批真走查都跑它，台账上 P43 #2 / P44 #4 那条
  // 「✔」抄的正是它打出来的那一行。而假壳这条闸从 P74 立起来到 P76，
  // `PLAN` 里**没有它**——于是那条回归在 `npm test` 这一侧一直是**空的**，
  // 全靠每批有人手工跑一趟真壳。**「够不着」和「没接」是两件事。**
  //
  // ⑤ 那一格（右键六项）这儿**一条判据都不给**：上面 `ctxmenu52` 已经逐字核过，
  // **重复核一遍不叫多核了一格**（`b1old` 那条 why 里的同一条规矩）。
  // ═══════════════════════════════════════════════════════════════════════
  {
    name: 'b1b',
    step: 'b1b.mjs',
    args: ['@note:走查（可删）'],
    why: '走查第 ② 步（意图三格 + 「预填」角标，P43 #2 / P44 问题 #4 的回归）'
       + ' + 第 ③ 步圆点那一格的**形状**。'
       + '⚠️ 圆点的**数**这儿核不了：假壳的 udd 里没有真语料（`makeUdd` 只造空库，'
       + '不拷 codebook），落槽天然是 0。能核的是**六个档一个都不少**——'
       + 'P62 那次正是 `.mm-continues` / `.mm-adds` 两个档名写错，'
       + '「四档只加得到 6」，掉进空档里的那 2 颗三批台账上没人看见',
    must: [
      // ② 意图三格：**读 `input.doc-intent-input` 的 value**，不是右栏 innerText
      //（P47 的 `p47intent.mjs` 栽过：`innerText` 里根本读不到 input 的值）
      [/意图行: \{"found":true,/, null, '意图行得找得到（`.doc-intent`）'],
      // **「预填」角标**（`.doc-intent-src`）：P44 问题 #4 那次就是它没了。
      [/"prefill":true/, null, '「预填」角标还在（P43 #2 / P44 #4）'],
      // 三格都得**真有值**。只核 `found: true` 不够：三个空格子也算「找到了」。
      [/意图行: .*"vals":\[\["[^"]+","[^"]*"\],\["[^"]+","[^"]*"\],\["[^"]+","[^"]*"\]\]/, null,
        '意图恰好三格（每格带 aria-label）'],
      // ③ 圆点**六个档一个都不少**（P62）。名字写错的那个档静悄悄地恒为 0，
      // 跟「产品里真的没有」读起来一模一样。
      [/圆点: \{"落槽合计":\d+,"图例":\d+,"页面合计":\d+,"冲突":\d+,"印证":\d+,"缺依据":\d+,"延续":\d+,"叠加":\d+,"合并":\d+\}/,
        null, '圆点六个档 + 三个合计，一个不少（P62）'],
      // **正文一个字没动**：这一步是「看一眼」，不是「改一笔」。
      [/正文一个字没动吗: true/, null, '这一步不许动到正文'],
    ],
    refute: [
      [/意图行: \{"found":false\}/, '意图行选不到——「选不到 ≠ 没有」那一张脸'],
      [/"prefill":false/, '「预填」角标没了（P43 #2 / P44 #4 回退）'],
      [/正文一个字没动吗: false/, '这一步把正文改了——后面几步量的就不是同一篇了'],
      [/开着的是: null/, '压根没开到那一篇（`openNoteById` 那条路断了）'],
    ],
  },
  {
    name: 'b2old',
    step: 'b2old.mjs',
    args: ['@note:走查（可删）'],
    why: '走查第 ⑥ 步（智能续写 → 轮次卡片 → **读库**）+ 第 ⑩ 步的前半（润色生一层）。'
       + '⑦ 那一段这一份也会跑，但**这儿一条判据都不给它**：选 vault 的系统对话框要主进程，'
       + '假壳够不着（文件头「够不着什么」第 2 条），**没核的就是没核**',
    // ⚠️ **跑之前先对一次端口**（P68 那条老坑，P74 加的那条对照当场吵出过错开的端口）：
    // 这一步真会去调模型，库里 `provider_config` 的地址要是跟这一趟的假模型端口错开，
    // 那一跑会全部打到一个没人听的端口上，症状是「AI 功能一个都不响应」，看起来像产品坏了。
    before: async (ctx) => checkProviderPort(ctx),
    beforeCount: 3,
    must: [
      // ⑥ 跑之前 / 跑完：P74 在**真打好的壳**上读到的是 105 → 205（+100），这儿逐格相同
      [/跑之前：编辑器 (\d+)/, (m) => Number(m[1]) === 105, '跑之前编辑器 105 字'],
      [/跑完：编辑器 (\d+) （\+ (\d+) /, (m) => Number(m[1]) === ROUNDS_LEN && Number(m[2]) === 100,
        '`ok` 档一轮 105 → 205（+100）'],
      [/空括号「（）」 0 次（该 0）/, null, '空括号 0（P35 #7）'],
      // **P78 A 的那条用户可见判据**：步骤脚本**自己那一行**也得读回真数。
      // 它是从渲染进程发的（同源 + 前端自己那份身份），跟下面 `after` 那条
      // 从 node 发的**不是同一段路**——这一条红了说明前端那一头的身份读错了。
      [/库: \{"len":(\d+),"json":(true|false)\}/,
        (m) => Number(m[1]) === ROUNDS_LEN && m[2] === 'false',
        '⑥ 步骤脚本自己那一行读库得读回 205 字 / json=false（P78 A）'],
      [/库里的层: \{"layers":\[/, null, '⑩ 步骤脚本自己那一行读得到那一层（P78 A）'],
      [/正文里还有「做爰片」吗（该 false）: false/, null, '`做爰片` 没了（P55 #1）'],
      [/正文里还有「\[terrence-8F6\]」吗（该 false）: false/, null, '`terrence-8F6` 没了（P55 #2）'],
      // ⑩ 前半：润色生一层 → 改动条 + 右栏「改动」页签
      [/改动条: "改了 (\d+) 处"/, (m) => Number(m[1]) >= 1, '润色得生出「改了 N 处」那一条'],
      [/右栏页签: \[[^\]]*"改动\d+"/, null, '右栏得冒出「改动」页签'],
    ],
    refute: [
      [/跑完：编辑器 \d+ （\+ 0 /, '一个字都没写进正文——那一轮没真跑'],
      [/正文里还有「做爰片」吗（该 false）: true/, 'P55 #1 回退了'],
      [/正文里还有「\[terrence-8F6\]」吗（该 false）: true/, 'P55 #2 回退了'],
      [/空括号「（）」 [1-9]/, '空括号又出来了（P35 #7 回退）'],
      // 「改了 N 处」那一条读回 undefined = `pageText` 里压根没有那一句
      [/改动条: undefined/, '改动条没摆出来——润色那一下没落成层'],
      // **P78 A 回退的两张脸**。身份又读到别人那一格去了的话，
      // 这两行正是 P78 开工那一趟实拍到的样子（空库新用户 + `|| 'terrence'` 兜底）。
      [/库: \{"len":0[,}]/, '⑥ 读库读回 0 字 —— 身份读到别人那一格去了（P78 A 回退）'],
      [/库里的层: \{"detail":"note not found"\}/,
        '⑩ 读层读回 note not found —— 身份读到别人那一格去了（P78 A 回退）'],
    ],
    // ⑥ 的「读库」那一格**由闸自己按真身份问一遍后端**，这才是 P45 #1 / P44 #1
    // 要的那条回归。
    //
    // ⚠️ **P78 A 之前，`b2old.mjs` 自己那两行是读不到东西的**：它读的是
    // `localStorage.getItem('memoket.user')`，而**整个前端里没有这个键**，
    // 于是每次都走 `|| 'terrence'` 那个兜底。真走查里那个兜底恰好等于身份，
    // 十四批没露过馅；假壳这边身份是空库新用户，当场读回 `{"len":0}` +
    // `{"detail":"note not found"}`，而同一刻这条 `after` 按真身份问回来是 205 字 / 1 层。
    // 键收进 `walkthrough/whoami.mjs` 之后，步骤脚本那两行也读回真数了。
    //
    // **这条 `after` 留着**，而且理由比之前更硬：步骤脚本那两行是**从渲染进程里**
    // 发的（同源、带前端自己那份身份），这一条是**从 node 发的**，
    // 两条腿量的不是同一段路。一条读对了不代表另一条也对。
    after: { count: 3, run: async (ctx) => readbackAfterRounds(ctx) },
  },
  {
    name: 'reopen64',
    step: 'reopen64.mjs',
    args: ['@note:走查（可删）', '@note:P76 夹具', 'p76-fs-reopen'],
    why: '走查第 ⑩ 步（**关掉重开**：带层那篇弹 toast + 「改动」页签，不带层那篇两样都没有）。'
       + '**「换了一篇 ≠ 重开过一次」**（`reopen64.mjs` 头上逐字写着这条），所以这一步'
       + '**真把壳关掉重起一个**，并且拿 pid 变没变当判据——不拿「我调了 restart」当重开过',
    // 不带层那篇要一篇**真的一层都没有**的笔记，而 `reopen64.mjs` 写死了拿
    // 「harness 测试」这几个字去 ⌘K 里找它（步骤脚本不改）。夹具由闸来造，
    // 造完**当场问一次后端确认它 0 层**——不带层这件事得有证据，不能靠「刚建的应该没有」。
    before: async (ctx) => makeNoLayerFixture(ctx),
    beforeCount: 2,
    restart: true,
    must: [
      // 带层那篇
      [/右栏页签: \[[^\]]*"改动\d+"/, null, '带层那篇重开之后「改动」页签还在'],
      [/toast: \["上次没处置完的 1 层改动还在右栏「改动」里"\]/, null,
        'toast **恰好 1 条**、逐字（P43）'],
      [/P43 不变式（弹了 toast ⇒ 页签在）: 成立/, null, 'P43 那条不变式成立'],
      [/正文字数: (\d+)/, (m) => Number(m[1]) === ROUNDS_LEN, '带层那篇正文 205 字（跟 ⑥ 跑完一样）'],
      // 不带层那篇（P44 #5）
      [/右栏页签（不许有「改动」）: \["记忆","计划"\]/, null, '不带层那篇只有「记忆」「计划」'],
      [/toast（该一条都没有）: \[\]/, null, '不带层那篇一条 toast 都没有（P44 #5）'],
    ],
    refute: [
      [/P43 不变式（弹了 toast ⇒ 页签在）: \*\*破了\*\*/, 'P43 那条不变式破了'],
      [/P43 不变式（弹了 toast ⇒ 页签在）: 没弹 toast，不适用/,
        '带层那篇没弹 toast——那条不变式被「不适用」绕过去了，不算过'],
      [/右栏页签（不许有「改动」）: \[[^\]]*改动/, '没有层的那篇也冒出了「改动」页签（P44 #5 破了）'],
      [/toast（该一条都没有）: \[".+/, '没有层的那篇也弹了 toast（P44 #5 破了）'],
    ],
    // **接线洞单独一条断言**：壳真换了一个进程吗。少了这一条，
    // 把 `restart` 那一段整个注释掉，上面六条判据**照样全过**——
    // 那就是「点过了 ≠ 翻过了」在这条闸身上原样重演。
    after: { count: 1, run: async (ctx) => shellReallyRestarted(ctx) },
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

// ── P76：新加那四步要的几件（**闸自己的活，步骤脚本一个字节不改**）──────────

/** 带 `X-User-Id` 问后端。**一律带 timeout**：上一趟留下的进程占着端口、
 *  接受连接却不回时，不带 timeout 的探针会永远挂着（P58 那条）。 */
async function api(ctx, p, init = {}) {
  const r = await fetch(`http://127.0.0.1:${ctx.backendPort}${p}`, {
    ...init,
    headers: { 'X-User-Id': ctx.user, ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...(init.headers ?? {}) },
    signal: AbortSignal.timeout(15000),
  })
  return { status: r.status, body: await r.json().catch(() => null) }
}

/** `@note:<一段字>` → 那一篇的 id。**恰好一篇才算数**：
 *  0 篇是「选不到」，2 篇是「选到两个」——两张脸都得当场吵，不许挑第一篇凑合
 *  （P47 问题 #4 正是「两篇同名、点的是另一篇」）。解出来的**记下来**，
 *  后面几步引用同一个别名时是**同一篇**，不重新挑一次。 */
const noteCache = new Map()
async function resolveNote(ctx, needle) {
  if (noteCache.has(needle)) return noteCache.get(needle)
  const { status, body } = await api(ctx, '/api/notes')
  if (status !== 200 || !Array.isArray(body)) die(`@note:${needle} 解不开：/api/notes 回 ${status}`)
  const hit = body.filter((n) => `${n.title ?? ''}\n${n.content ?? ''}`.includes(needle))
  if (hit.length !== 1) {
    die(`@note:${needle} 命中 ${hit.length} 篇（该恰好 1 篇）：`
      + JSON.stringify(hit.map((n) => n.id)) + `；库里一共 ${body.length} 篇`)
  }
  noteCache.set(needle, hit[0].id)
  return hit[0].id
}

/** **跑 harness 之前先对一次端口**（P68 那条老坑，`go.sh --check-provider-port` 同一条）。
 *
 *  ⚠️ 这儿读的是 **udd 那份 sqlite 里的 `provider_config` 本人**，不是
 *  `/api/settings/provider`：实测那个端点**不分用户**（`default` / `p74-newbie` /
 *  `terrence` 三个身份问回来一模一样），拿它对端口，「库里到底存了什么」这件事
 *  其实没被看到。P74 加的那条对照（`bnew3` 的「库里 base_url 端口 = llmPort」）**留着**，
 *  这一条是它下面那一层。 */
function checkProviderPort(ctx) {
  const db = path.join(ctx.udd, 'data', 'notes.sqlite3')
  if (!fs.existsSync(db)) return [`端口对照：udd 里没有 ${db} —— 前面几步压根没落过库`]
  const py = path.join(ROOT, 'backend/.venv/bin/python')
  const r = spawnSync(py, ['-c',
    'import json,sqlite3,sys\n'
    + 'c=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True)\n'
    + 'cols=[r[1] for r in c.execute("PRAGMA table_info(provider_config)")]\n'
    + 'rows=[dict(zip(cols,r)) for r in c.execute("select * from provider_config")]\n'
    + 'print(json.dumps(rows,ensure_ascii=False))\n', db], { encoding: 'utf8' })
  if (r.status !== 0) return [`端口对照：读 provider_config 失败：${(r.stderr || '').slice(0, 200)}`]
  const rows = JSON.parse(r.stdout.trim())
  const out = []
  console.log('   端口对照：' + JSON.stringify(rows.map((x) => ({
    id: x.id, provider: x.provider, local_base_url: x.local_base_url, local_model: x.local_model }))))
  if (!rows.length) return ['端口对照：`provider_config` 一行都没有——前面那几步压根没保存成']
  for (const row of rows) {
    // ① **在用的那一档得是本机那一档**。这一条比「四列地址全指本机」窄，而窄得对：
    //    ⚠️ **第一版写的正是那条宽的，当场红了，而红的是判据不是产品**——
    //    空库新用户的 `gpt_base_url` 是**出厂默认** `https://api.openai.com/v1`
    //    （`gpt_api_key` 空、`provider=local`，一次都不会连出去）。
    //    **预测错了照实记**：我以为新 udd 里四列地址都是本机，实测不是。
    if (row.provider !== 'local') {
      out.push(`端口对照：在用的那一档是 ${JSON.stringify(row.provider)}，不是 local`
        + '——这一趟会往本机以外发请求')
    }
    // ② `local_base_url` 的端口 = 这一趟假模型真正监听的那个（**P68 那条老坑**，
    //    `go.sh --check-provider-port` 同一条。对不上的那一跑会全部打到一个
    //    没人听的端口上，症状是「AI 功能一个都不响应」，看起来像产品坏了）。
    if (!String(row.local_base_url ?? '').includes(`:${ctx.llmPort}/`)) {
      out.push(`端口对照：库里存的 local_base_url 是 ${JSON.stringify(row.local_base_url)}，`
        + `这一趟的假模型在 ${ctx.llmPort} —— **对不上**（P68 那条坑）`)
    }
    // ③ **一把钥匙都不许有**。上面两条管「打到哪儿去」，这一条管「打出去也没得用」：
    //    空库新用户从头到尾没填过 key，有一把就说明这份 udd 不是干净的
    //    （P23 那次真往 api.openai.com 发了两次，起因正是 scratch 库里带着真钥匙）。
    const keys = Object.entries(row).filter(([k, v]) => /api_key$/.test(k) && String(v ?? '').trim())
    if (keys.length) out.push(`端口对照：这份 udd 里带着 ${JSON.stringify(keys.map(([k]) => k))}——空库新用户不该有钥匙`)
  }
  return out
}

/** ⑥ 的「读库」那一格（P45 #1 / P44 #1 的回归）+ ⑩ 前半那一层**真落库了吗**。
 *  三条：正文长度 = 编辑器那个数 / 正文不是 JSON / 恰好一层且 `state=on`。 */
async function readbackAfterRounds(ctx) {
  const id = await resolveNote(ctx, '走查（可删）')
  const out = []
  const note = await api(ctx, `/api/notes/${id}`)
  const content = note.body?.content ?? ''
  if (content.length !== ROUNDS_LEN) {
    out.push(`⑥ 读库：库里那篇是 ${content.length} 字，编辑器跑完是 ${ROUNDS_LEN} 字 `
      + `——「编辑器里有 ≠ 库里有」（P45 #1 / P44 #1）；HTTP ${note.status}`)
  }
  if (/\{"scores"|\{"spine"|\{"text":/.test(content)) {
    out.push('⑥ 读库：库里那篇正文是 JSON，不是给人看的正文（P44 #1）')
  }
  const lay = await api(ctx, `/api/notes/${id}/change-layers`)
  const layers = lay.body?.layers ?? []
  if (!(layers.length === 1 && layers[0].state === 'on' && (layers[0].hunks ?? []).length >= 1)) {
    out.push(`⑩ 前半：库里该恰好 1 层 on 的改动，实际 ${JSON.stringify(
      layers.map((l) => `${l.label}:${(l.hunks ?? []).length}处/${l.state}`))}；HTTP ${lay.status}`)
  }
  return out
}

/** ⑩ 要的「不带层那篇」夹具。
 *
 *  `reopen64.mjs` 写死了拿「harness 测试」这几个字去 ⌘K 里找它（步骤脚本不改），
 *  所以标题里得有这几个字。造完**当场问一次后端**确认它真的 0 层——
 *  「刚建的应该没有层」是**推断**，不是判据。 */
async function makeNoLayerFixture(ctx) {
  const out = []
  const made = await api(ctx, '/api/notes', {
    method: 'POST',
    body: JSON.stringify({
      title: 'harness 测试（没有层 · P76 夹具）',
      content: '# harness 测试（没有层 · P76 夹具）\n\n第 ⑩ 步「不带层那篇」的夹具：一层改动都没有。\n',
      parent_note_id: 'root',
    }),
  })
  if (made.status !== 200 || !made.body?.id) {
    out.push(`⑩ 夹具：建不出来（HTTP ${made.status}）`)
    return out
  }
  const lay = await api(ctx, `/api/notes/${made.body.id}/change-layers`)
  const n = (lay.body?.layers ?? []).length
  if (n !== 0) out.push(`⑩ 夹具：刚建出来的那篇就带了 ${n} 层——它当不了「不带层那篇」`)
  console.log(`   ⑩ 夹具：${made.body.id}（层 ${n} 个）`)
  return out
}

/** **壳真换了一个进程吗。**
 *  `restart` 那一段整个注释掉，⑩ 上面那六条判据照样全过——
 *  少了这一条就是「点过了 ≠ 翻过了」在这条闸身上原样重演。 */
function shellReallyRestarted(ctx) {
  if (!ctx.shellPids || ctx.shellPids.length < 2) {
    return [`⑩ 接线：壳从头到尾只起过 ${(ctx.shellPids ?? []).length} 次 —— 「关掉重开」没真发生`]
  }
  const [first, last] = [ctx.shellPids[0], ctx.shellPids[ctx.shellPids.length - 1]]
  if (first === last) return [`⑩ 接线：重起前后壳还是同一个进程（pid ${first}）`]
  return []
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
/** 起一个壳，等到真有 page target。**P76 拆成函数**：第 ⑩ 步要真关掉重起一个。 */
let shellSeq = 0
let el = null
async function startShell() {
  shellSeq += 1
  el = spawn(path.join(ROOT, 'desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron'),
    [path.join(WALK, 'fakeshell/main.cjs'), `--user-data-dir=${udd}`, `--remote-debugging-port=${cdpPort}`],
    { env: eenv, stdio: ['ignore', 'pipe', 'pipe'] })
  procs.push(el)
  const elLog = fs.createWriteStream(path.join(logDir, `electron${shellSeq > 1 ? shellSeq : ''}.log`))
  el.stdout.pipe(elLog); el.stderr.pipe(elLog)
  const url = await waitPage(cdpPort)
  if (!url) die(`假壳的窗口没起来（第 ${shellSeq} 次），看 ${path.join(logDir, `electron${shellSeq > 1 ? shellSeq : ''}.log`)}`)
  console.log(`窗口起来了（第 ${shellSeq} 次，pid ${el.pid}）：` + url)
  return el.pid
}

/** 关掉这个壳。**先 SIGTERM 等它自己退，等不到再 SIGKILL。**
 *
 * ⚠️ **实测栽过一次**：直接 `SIGKILL` 之后重起，窗口开的**不是关掉之前那一篇**，
 * 标签条上还少一格。查下来不是产品问题——Chromium 的 localStorage 写盘是**异步**的
 * （JS 那一头是同步 API，落盘在后面），`kill -9` 把最后那几笔写丢了。
 * **「关掉」得是关掉，不是拔电源**；拔电源量出来的那一格会被记成产品缺陷。 */
async function stopShell(ms = 12000) {
  if (!el) return
  const dead = new Promise((r) => el.once('exit', r))
  try { el.kill('SIGTERM') } catch { /* 已经没了 */ }
  const won = await Promise.race([dead.then(() => true), wait(ms).then(() => false)])
  if (!won) { try { el.kill('SIGKILL') } catch { /* 已经没了 */ } ; await wait(1500) }
  console.log(`   壳关掉了（pid ${el.pid}，${won ? 'SIGTERM 自己退的' : '等不到，补了一刀 SIGKILL'}）`)
  el = null
  await wait(1500)
}

// ── 逐步跑 + 逐条判 ───────────────────────────────────────────────────────
const ctx = { backendPort, cdpPort, llmPort, user: USER, udd, shellPids: [] }
ctx.shellPids.push(await startShell())
await wait(3000)

const failures = []
let checked = 0
for (const s of PLAN) {
  if (only && s.name !== only) continue
  console.log(`\n── ${s.name}（steps/${s.step}）`)
  // `before` 先跑（造夹具 / 跑之前对端口），**它报的问题跟判据一样算数**
  if (s.before) {
    checked += s.beforeCount ?? 0
    for (const f of await s.before(ctx)) failures.push(`${s.name}（steps/${s.step}）· ${f}`)
  }
  // **真关掉重起一个壳**（第 ⑩ 步）。「换了一篇 ≠ 重开过一次」
  if (s.restart) {
    console.log('   ── 关掉重开：把壳关掉，起一个新的 ──')
    await stopShell()
    ctx.shellPids.push(await startShell())
    await wait(3000)
  }
  // `@llmPort` / `@note:<一段字>` 两种占位在这儿换成真值
  const args = []
  for (const a of s.args) {
    if (a === '@llmPort') args.push(String(llmPort))
    else if (a.startsWith('@note:')) args.push(await resolveNote(ctx, a.slice(6)))
    else args.push(a)
  }
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
  // `after`：**闸自己去问一次**（读库 / 接线洞）。步骤脚本打出来的那几行答不了的那几格
  // 放在这儿——它们跟上面那些判据**一样算数**，所以一起进 `checked`。
  if (s.after) {
    checked += s.after.count
    for (const f of await s.after.run(ctx, text)) failures.push(`${s.name}（steps/${s.step}）· ${f}`)
  }
  console.log(`   判据 ${s.must.length} + 反例 ${s.refute.length}`
    + `${s.beforeCount ? ` + 跑前 ${s.beforeCount}` : ''}${s.after ? ` + 闸自己问 ${s.after.count}` : ''} 条`)
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
