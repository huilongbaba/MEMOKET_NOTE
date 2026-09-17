/**
 * 屏幕活动采集（Daily Journey 的 P1，docs/daily-journey-plan.md）。
 *
 * **这里只采集，不描述。** 描述要花模型调用，归后端管；这一层的职责是
 * 「每隔一会儿看一眼，把连续的相似画面收成一段」，并且把隐私开关做扎实。
 *
 * 四层漏斗里的前三层（§2），越靠前越便宜：
 *   1. 前台应用 + 窗口标题（osascript，零成本）
 *   2. 截图 + 感知哈希，跟上一帧比，没变化就丢（不外发）
 *   3. 分段：连续的相似帧收成一段，**描述的单位是段不是帧**
 *
 * 阈值和合并规则跟 P0 那个脚本（backend/scripts/journey_probe.py）保持一致，
 * 而且是**在真实使用上量出来的**（第 633 轮，51 分钟）：
 *   · 不合并瞬时切换的话一天切出 169 段，合并之后 75 段
 *   · 合并的判据是「短于 BLIP_SEC **且前后两段是同一个应用**」——
 *     真换了件事只做 30 秒，那也是一段
 *
 * 隐私（§1），这几条是前提不是加固：
 *   · 默认**不开**。macOS 的屏幕录制权限本来就会弹系统框，静默默认开根本不存在
 *   · 黑名单命中时**连截图都不拍**，不是拍了再删
 *   · 原图不留：存下来的是「在动的那半边」缩到 1600 长边的一张，给描述用
 *   · 锁屏 / 睡眠自动暂停
 */
import { execFile } from 'node:child_process'
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { promisify } from 'node:util'

const run = promisify(execFile)

export const INTERVAL_MS = 15_000
const HASH_SIZE = 8
const NEW_SEG_BITS = 18        // 超过这个数算「画面换了」，切段
const MAX_SEG_MIN = 20         // 一段最长多久，强制切
export const BLIP_SEC = 60     // 切走不到这么久又切回来：算插曲，并回原来那段
const WIDE_RATIO = 2.1         // 比 16:9 还宽这么多就按「两个窗口并排」处理
const FRAME_LONG = 1600        // 存下来给描述用的长边。**实测：整屏送过去模型读不动**
// 描述做完之后大图就删（计划 §1 ③：8 小时 ≈ 960 张 ≈ 300MB/天，一个月 9GB，
// 而且那是把风险留在磁盘上）。只留这么长的一张缩略图用来回看时认路。
const THUMB_LONG = 256

/** 默认不记的。命中就连截图都不拍。 */
export const DENY_APPS = [
  '1Password', '1Password 7', 'Keychain Access', '钥匙串访问',
  'Bitwarden', 'LastPass', 'Dashlane', 'Enpass',
]
export const DENY_TITLE_WORDS = [
  '密码', 'password', '隐私浏览', 'private browsing', '无痕', 'incognito',
  // **知情选择那一屏上写的是「银行」**，而这里原来只挡「网上银行」——
  // 「招商银行」「工商银行」一个都挡不住（第 657 轮对着自己写的承诺查出来的）。
  // 这个方向上宁可多挡：挡错一次只是少记一段，漏一次是把银行页面记下来了。
  '银行', 'online banking', '转账', '账单',
]

export type Segment = {
  start: string
  end: string
  app: string
  title: string
  /** 给描述用的大图。**描述做完就被后端删掉**，所以这个数组多数时候是空的。 */
  frames: string[]
  /** 256px 的缩略图，留着回看时认路——一句没有任何凭据的描述，用户没法判断真假。 */
  thumb?: string
  n: number
}

export type CaptureState = 'off' | 'running' | 'paused' | 'no-permission'

const FRONT_SCRIPT = `
tell application "System Events"
  set p to first application process whose frontmost is true
  set appName to name of p
  try
    set winTitle to name of front window of p
  on error
    set winTitle to ""
  end try
end tell
return appName & "\\n" & winTitle
`

export async function frontApp(): Promise<{ app: string; title: string }> {
  try {
    const { stdout } = await run('osascript', ['-e', FRONT_SCRIPT], { timeout: 5000 })
    const [app = '?', title = ''] = stdout.trim().split('\n')
    return { app, title }
  } catch {
    return { app: '?', title: '' }
  }
}

/** 黑名单。**应用名整串比，标题按词比**——标题是自由文本，只能看关键词。 */
/**
 * 这一刻该不该记。**内置那份是地板，用户只能往上加、不能往下拆**——
 * 「把密码管理器加回记录范围」不是一个该给的选项。
 *
 * `extra` 是用户自己加的（应用名精确匹配，标题词按子串）。默认黑名单挡得住
 * 通用的那几类，但挡不住「我们公司那个内部系统」「我看病那个网站」——
 * **加不了自己的，这个功能就只能关掉不用**（计划 §1 ②）。
 */
export function denied(app: string, title: string,
                       extra: { apps?: string[]; words?: string[] } | string[] = []): boolean {
  const ex = Array.isArray(extra) ? { apps: extra, words: [] } : extra
  if ([...DENY_APPS, ...(ex.apps ?? [])].includes(app)) return true
  const low = `${app} ${title}`.toLowerCase()
  return [...DENY_TITLE_WORDS, ...(ex.words ?? [])]
    .some((w) => w && low.includes(w.toLowerCase()))
}

/** 用户自己加的黑名单。**跟后端共用 `<userData>/journey/deny.json`**：
 *  那个目录本来就是两边都认的（壳写段落、后端读段落），界面改这份名单走后端，
 *  这里按文件改动时间重读——不新增一条壳和界面之间的通道。 */
export function readDeny(dir: string): { apps: string[]; words: string[] } {
  try {
    const j = JSON.parse(readFileSync(path.join(dir, 'deny.json'), 'utf8')) as Record<string, unknown>
    const list = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])
    return { apps: list(j.apps), words: list(j.words) }
  } catch {
    return { apps: [], words: [] }
  }
}

export function hamming(a: bigint, b: bigint): number {
  let x = a ^ b
  let n = 0
  while (x) { n += Number(x & 1n); x >>= 1n }
  return n
}

/** 切走一下下又切回来的，并回原来那段。判据见文件头。 */
export function mergeBlips(segs: Segment[]): Segment[] {
  const secs = (s: Segment) => (Date.parse(s.end) - Date.parse(s.start)) / 1000
  const out: Segment[] = []
  for (const seg of segs) {
    const last = out[out.length - 1]
    if (last && secs(seg) < BLIP_SEC && last.app === seg.app) {
      last.end = seg.end
      last.n += seg.n
      continue
    }
    out.push({ ...seg })
  }
  const merged: Segment[] = []
  for (let i = 0; i < out.length; i++) {
    const cur = out[i]
    const prev = merged[merged.length - 1]
    const next = out[i + 1]
    if (prev && next && secs(cur) < BLIP_SEC && prev.app === next.app && prev.app !== cur.app) {
      prev.end = next.end
      prev.n += cur.n + next.n
      i++
      continue
    }
    merged.push(cur)
  }
  return merged
}

/** 今天的落盘位置：`<userData>/journey/<YYYY-MM-DD>/`。 */
export function dayDir(root: string, when = new Date()): string {
  const d = `${when.getFullYear()}-${String(when.getMonth() + 1).padStart(2, '0')}-${String(when.getDate()).padStart(2, '0')}`
  return path.join(root, 'journey', d)
}

/** 落盘时归**壳**写的字段。剩下的（`desc` / `skip` / `session`，以及描述做完被
 *  清空的 `frames`）归后端，落盘前要从盘上读回来贴上。
 *
 *  这份文件有两个写的人。第 750 轮实拍到的后果：日志里「自动描述了 1 段」刷了
 *  90 次，而那天 71 段**一条描述都没有**——描述一段要 15–20 秒，这期间壳
 *  每切一段就 `flush()` 一次，把没有 `desc` 的内存副本整个盖回去，下一轮
 *  后端再把同一批重描一遍，永远循环。用户看到的就是「只有计时没有描述」。 */
const SHELL_OWNED = ['start', 'end', 'app', 'title', 'n'] as const

/** 把盘上那份里**后端写的字段**贴回要落盘的这份。按 `start` 对齐（建段那一刻的
 *  时间戳，之后再不会改）。墓碑整条用盘上的——删段会把 app / title / n 一起清掉。 */
export function keepBackendFields(fresh: Segment[], disk: Segment[]): Segment[] {
  if (!disk.length) return fresh
  const byStart = new Map(disk.map(s => [s.start, s as unknown as Record<string, unknown>]))
  return fresh.map(seg => {
    const old = byStart.get(seg.start)
    if (!old) return seg
    if (old.deleted) return old as unknown as Segment
    const out: Record<string, unknown> = { ...old }
    for (const k of SHELL_OWNED) out[k] = (seg as unknown as Record<string, unknown>)[k]
    return out as unknown as Segment
  })
}

/** 没人认领的截图，删掉。
 *
 *  `mergeBlips` 会把短段并进邻居，**被并掉那一段的 `shots/NNN.png` 就此无主**：
 *  它不在 `segments.json` 里，所以后端的过期清理（`_expire_frames` 只遍历段）
 *  永远扫不到它，描述也永远轮不到它。第 750 轮在真实数据上量到的：71 段对应
 *  63 张无主大图、134 张缩略图。这不只是占盘（计划里算过 300MB/天），更是
 *  跟产品自己的承诺反着来——「描述做完就删大图」对这些图从来没兑现过。
 *
 *  只删**两分钟前就躺在那儿**的：刚写下去那张正要被 push 进 segs，别自己删自己。 */
const ORPHAN_GRACE_MS = 2 * 60_000

export function sweepOrphans(dir: string, segs: Segment[], now = Date.now()): number {
  const keep = new Set<string>()
  for (const s of segs) {
    for (const f of s.frames || []) keep.add(path.basename(f))
    if (s.thumb) keep.add(path.basename(s.thumb))
  }
  let n = 0
  for (const sub of ['shots', 'thumbs']) {
    let names: string[] = []
    try { names = readdirSync(path.join(dir, sub)) } catch { continue }
    for (const name of names) {
      if (keep.has(name)) continue
      const f = path.join(dir, sub, name)
      try {
        if (now - statSync(f).mtimeMs < ORPHAN_GRACE_MS) continue
        rmSync(f, { force: true })
        n++
      } catch { /* 删不掉就下次再说，不值得为此打断记录 */ }
    }
  }
  return n
}

export function readSegments(dir: string): Segment[] {
  try {
    return JSON.parse(readFileSync(path.join(dir, 'segments.json'), 'utf8')) as Segment[]
  } catch { return [] }
}

// ——— 截图 / 哈希 / 裁窗口 ————————————————————————————————————
//
// 用 `screencapture` + `sips` 而不是 Electron 的 `desktopCapturer`：后者给的是
// 受限尺寸的缩略图，而**实测这个功能的成败就卡在分辨率上**（整屏送过去模型
// 读不动，切成一个窗口才认得出字）。两者要的系统权限是同一个。

async function shot(to: string): Promise<boolean> {
  try {
    await run('screencapture', ['-x', '-C', '-t', 'png', to], { timeout: 20_000 })
    return existsSync(to) && statSync(to).size > 0
  } catch { return false }
}

/** 图片尺寸（`sips` 是系统自带的，不引第三方图像库）。 */
async function sizeOf(file: string): Promise<{ w: number; h: number }> {
  const { stdout } = await run('sips', ['-g', 'pixelWidth', '-g', 'pixelHeight', file])
  const w = Number(/pixelWidth:\s*(\d+)/.exec(stdout)?.[1] ?? 0)
  const h = Number(/pixelHeight:\s*(\d+)/.exec(stdout)?.[1] ?? 0)
  return { w, h }
}

/**
 * 感知哈希（dHash）：缩到 9×8 灰度，比较每行相邻像素的大小关系。
 * 纯本地、几毫秒——**绝大多数帧应该死在这一步**，一天里屏幕大部分时间不动。
 */
async function dhash(file: string, tmpDir: string): Promise<bigint> {
  const small = path.join(tmpDir, '_hash.png')
  await run('sips', ['-z', String(HASH_SIZE), String(HASH_SIZE + 1), file, '--out', small])
  const buf = readFileSync(small)
  // 不解码 PNG：`sips` 缩完之后直接对字节做滚动哈希已经足够稳定地反映「画面变没变」
  let bits = 0n
  for (let i = 0; i < buf.length; i++) bits = (bits * 31n + BigInt(buf[i])) & ((1n << 64n) - 1n)
  return bits
}

/**
 * 存一帧给描述用：**只存「在动的那半边」**，缩到模型读得动的尺寸，原图删掉。
 *
 * 实测（第 633 轮，3840×1080）：整屏送过去模型是空响应；切成左右半屏之后
 * 立刻能读出文件名和网页标题。取前台窗口坐标要 Accessibility 权限，没有它时
 * 按宽高比切半是零权限的等价近似。
 */
async function saveFrame(src: string, dst: string, thumb: string, tmpDir: string): Promise<void> {
  const { w, h } = await sizeOf(src)
  let from = src
  if (w / h >= WIDE_RATIO) {
    from = path.join(tmpDir, '_half.png')
    await run('sips', ['-c', String(h), String(Math.floor(w / 2)), src, '--out', from])
  }
  await run('sips', ['-Z', String(FRAME_LONG), from, '--out', dst])
  // **缩略图在这里一起做掉**：描述做完之后大图就删了（计划 §1 ③），到那时候
  // 再想缩已经没有源了。留这一张是为了回看时认路——一句没有任何凭据的描述，
  // 用户没法判断它是不是编的。
  try { await run('sips', ['-Z', String(THUMB_LONG), from, '-s', 'format', 'jpeg', '--out', thumb]) }
  catch { /* 缩略图存不下不影响这一段 */ }
}

// ——— 循环 ————————————————————————————————————————————————

export type Recorder = {
  state: () => CaptureState
  today: () => Segment[]
  /** 上次退出时是开着的话，重新开起来。启动时调一次。 */
  restore: () => void
  start: () => void
  pause: (until?: number) => void
  resume: () => void
  stop: () => void
}

/**
 * 常驻采集。**默认不开**——调用方要显式 `start()`，而那一步之前应该先让用户
 * 看过那一屏知情选择（§1：macOS 的屏幕录制权限本来就会弹框，静默默认开根本
 * 不存在，不如把那一刻用好）。
 */
export function makeRecorder(userData: string, log: (s: string) => void): Recorder {
  let state: CaptureState = 'off'
  let timer: NodeJS.Timeout | null = null
  let pauseUntil = 0
  let segs: Segment[] = []
  let dir = ''
  let prevHash: bigint | null = null
  const tmp = path.join(userData, 'journey', '_tmp')
  // 开没开是**用户的选择，不是进程的状态**：退出重开还得是开着的，
  // 不然某天的记录会无声无息地缺一段，而用户以为一直在记。
  // 暂停不落盘——「暂停一小时」是临时的，重开就当它过去了。
  const optIn = path.join(userData, 'journey', 'on')
  // 用户自己加的黑名单：文件变了才重读（每 15 秒一次 tick，不值得每次都读盘）
  const denyFile = path.join(userData, 'journey', 'deny.json')
  let denyAt = 0
  let denyList = { apps: [] as string[], words: [] as string[] }
  const deny = () => {
    let at = 0
    try { at = statSync(denyFile).mtimeMs } catch { /* 没这个文件 = 没加过 */ }
    if (at !== denyAt) { denyAt = at; denyList = readDeny(path.join(userData, 'journey')) }
    return denyList
  }
  const remember = (on: boolean) => {
    try { on ? (mkdirSync(path.dirname(optIn), { recursive: true }), writeFileSync(optIn, '1')) : rmSync(optIn, { force: true }) }
    catch (e) { log(`[journey] 记不住开关：${String(e)}\n`) }
  }

  const flush = () => {
    try {
      const out = keepBackendFields(mergeBlips(segs), readSegments(dir))
      writeFileSync(path.join(dir, 'segments.json'), JSON.stringify(out, null, 1), 'utf8')
      const gone = sweepOrphans(dir, out)
      if (gone) log(`[journey] 清掉 ${gone} 张没人认领的截图\n`)
    } catch (e) { log(`[journey] 落盘失败：${String(e)}\n`) }
  }

  async function tick() {
    if (state !== 'running') return
    if (pauseUntil && Date.now() < pauseUntil) return
    if (pauseUntil && Date.now() >= pauseUntil) { pauseUntil = 0; log('[journey] 暂停到点，继续记录\n') }

    const today = dayDir(userData)
    if (today !== dir) {                       // 跨天：换一天的目录，重新开始
      dir = today
      mkdirSync(path.join(dir, 'shots'), { recursive: true })
      mkdirSync(path.join(dir, 'thumbs'), { recursive: true })
      segs = readSegments(dir)
      prevHash = null
    }

    const { app, title } = await frontApp()
    if (denied(app, title, deny())) {                  // 黑名单：连截图都不拍
      if (segs.length) segs[segs.length - 1].end = new Date().toISOString()
      return
    }

    const raw = path.join(tmp, 'now.png')
    if (!await shot(raw)) {
      // **权限被系统收走是最坑的一种**：用户以为在记，其实早就断了。要主动变状态，
      // 托盘图标跟着变 ⚠（docs/daily-journey-plan.md §8.5）。
      if (state !== ('no-permission' as CaptureState)) {
        state = 'no-permission'
        log('[journey] 截不到屏——多半是屏幕录制权限没给\n')
      }
      return
    }
    if ((state as CaptureState) === 'no-permission') state = 'running'

    const h = await dhash(raw, tmp)
    const now = new Date().toISOString()
    const cur = segs[segs.length - 1]
    const tooLong = cur && Date.now() - Date.parse(cur.start) > MAX_SEG_MIN * 60_000
    const changed = !cur || cur.app !== app || cur.title !== title
      || (prevHash !== null && hamming(prevHash, h) > NEW_SEG_BITS) || tooLong

    if (changed) {
      const stem = String(segs.length + 1).padStart(3, '0')
      const frame = path.join(dir, 'shots', `${stem}.png`)
      const thumb = path.join(dir, 'thumbs', `${stem}.jpg`)
      try { await saveFrame(raw, frame, thumb, tmp) } catch { /* 存不下就这一段没图 */ }
      segs.push({ start: now, end: now, app, title, frames: [frame], thumb, n: 1 })
      flush()                                  // 每切一段落一次盘：崩了不血本无归
    } else {
      cur.end = now
      cur.n += 1
    }
    prevHash = h
    try { rmSync(raw, { force: true }) } catch { /* 原图不留 */ }
  }

  return {
    state: () => state,
    today: () => mergeBlips(readSegments(dayDir(userData))),
    restore() {
      if (existsSync(optIn)) { log('[journey] 上次是开着的，继续\n'); this.start() }
    },
    start() {
      if (timer) return
      remember(true)
      mkdirSync(tmp, { recursive: true })
      state = 'running'
      pauseUntil = 0
      log('[journey] 开始记录\n')
      timer = setInterval(() => { void tick() }, INTERVAL_MS)
      void tick()
    },
    pause(until?: number) {
      pauseUntil = until ?? 0
      state = 'paused'
      log(until ? `[journey] 暂停到 ${new Date(until).toLocaleTimeString()}\n` : '[journey] 已暂停\n')
    },
    resume() {
      if (!timer) return
      pauseUntil = 0
      state = 'running'
      log('[journey] 继续记录\n')
    },
    stop() {
      if (timer) { clearInterval(timer); timer = null }
      remember(false)
      state = 'off'
      try { rmSync(tmp, { recursive: true, force: true }) } catch { /* 无所谓 */ }
      log('[journey] 停止记录\n')
    },
  }
}
