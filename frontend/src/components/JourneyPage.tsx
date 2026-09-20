import { useCallback, useEffect, useRef, useState } from 'react'

import { journeyCatchUp, journeyDay, journeyDays, journeyDeleteDay, journeyDeleteSegment,
         journeyReport, journeyRetention, journeySaveReport, journeySpan, journeyThumb,
         type JourneyDay, type JourneyRetention, type JourneySegment } from '../api'
import { friendlyError } from '../util/friendlyError'
import { JOURNEY_DAY_EVENT, JOURNEY_SPAN_EVENT, takePendingJourneyDay, takePendingJourneySpan } from '../util/journeyOpen'
import { groupRuns } from '../util/journeyRuns'
import { parseMini, type Inline } from '../util/miniMarkdown'
import { usePoll } from '../util/poll'
import JourneyDenyPanel from './JourneyDenyPanel'
import JourneyRetentionPanel, { sayKeep } from './JourneyRetentionPanel'
import { toast } from '../toast'
import Icon from './Icon'

/**
 * 「今天」——屏幕活动这一天长什么样（docs/daily-journey-plan.md §8.3）。
 *
 * **这个功能的 UX 难点不是时间轴，是信任**：一个整天看着你屏幕的东西，必须在
 * 任何时刻、不用翻设置页就能回答「现在在记吗 / 刚才记了什么 / 我能不能抹掉」。
 * 所以这一页从上到下是：状态 → 一天一条带 → 时间轴，而删除就在手边。
 *
 * 报告（日报）是 P3，这里先留位置。
 */

/** 每个应用一个固定颜色，**按出现顺序分配、不循环**——同一个应用在整页里
 *  必须是同一个颜色，不然那条带就读不成「时间去哪了」。超过 8 个收进「其他」。
 *
 *  八个色值定在 CSS 里（`--jn-1..8`，深浅色各一套）而不是写死在这儿：亮色那套
 *  在 #242424 上会糊成一片。这八个是**量过的**——色盲相邻对 ΔE 9.1 亮 / 8.4 暗，
 *  正常视力 19.6 / 19.3，都过线。但那条带上谁挨着谁是数据说了算（不是槽位顺序），
 *  所以还叠了两层不靠颜色的编码：段与段之间留 2px 底色缝，下面的时间轴每行都
 *  写着应用名。**别为了好看换色值**，换了要重新量。 */
const BAND = Array.from({ length: 8 }, (_, i) => `var(--jn-${i + 1})`)
const OTHER = 'var(--jn-other)'

export function appColors(apps: string[]): Map<string, string> {
  const seen: string[] = []
  for (const a of apps) if (a && !seen.includes(a)) seen.push(a)
  const m = new Map<string, string>()
  seen.forEach((a, i) => m.set(a, i < BAND.length ? BAND[i] : OTHER))
  return m
}

const secs = (s: { start: string; end: string }) =>
  Math.max(0, (Date.parse(s.end) - Date.parse(s.start)) / 1000)

/** 时长写成人话。分钟级就够了——秒级的精度在「今天时间去哪了」这个问题上没有意义。
 *  但**不能出现「0 分钟」**：刚开始记的那一段四舍五入成 0，读起来像坏了（实拍）。 */
export function saySpan(sec: number): string {
  const m = Math.round(sec / 60)
  if (m < 1) return '不到 1 分钟'
  if (m < 60) return `${m} 分钟`
  return `${Math.floor(m / 60)} 小时 ${m % 60 ? `${m % 60} 分钟` : ''}`.trim()
}

/** 两段之间隔了这么久，就算一段「没在记」的空档：中午出去吃饭、下午开会。
 *  带上不画出来的话，`合计 4 小时 24 分钟` 和一条从早排到晚的实心带互相矛盾。 */
export const GAP_MIN = 15
/** 空档在带上最多占这么久的宽度：隔夜 12 小时不能把一整天挤成两条缝。 */
const GAP_CAP_SEC = 20 * 60

/** 在**有记录的日子**之间翻。按日期加一减一会走进一串什么都没有的日子——
 *  病了一周、出差没带电脑，翻七下才回到上一条记录。
 *
 *  `days` 是新的在前。回到今天就还原成空串：让后端继续负责「今天是哪天」，
 *  不然开着页面过零点，日期就钉死在昨天了。翻到头就返回 null（按钮置灰）。
 *
 *  **`today` 这个参数是第 794 轮（P52）补的，因为「今天一定是 `days[0]`」不成立。**
 *  原来 `date === ''`（= 今天）直接当 `i = 0`，而 `j === 0` 又直接当「回到今天」。
 *  今天一段记录都没有的时候（停了几天没开、或者今天的段被删光了）今天**不在列表里**，
 *  `days[0]` 是最近**记过**的那一天，于是实拍（`$S/p52/stepday_probe.mjs`，
 *  `days=['2026-09-19','2026-09-18']`、今天 09-20）：
 *    · 今天按「上一条记录」→ `2026-09-18`，**把 09-19 整个跳过去了**；
 *    · 09-18 按「下一条记录」→ `''`（今天），**又把 09-19 跳过去了**。
 *  09-19 是最近记的那一天，翻页**两个方向都够不着它**。
 *  `today` 不给（老的调用方 / 还没拉到今天是哪天）时行为跟以前逐字一样。 */
export function stepDay(days: string[], date: string, delta: number, today = ''): string | null {
  if (!days.length) return null
  const cur = date || today
  const i = cur ? days.indexOf(cur) : 0
  if (i < 0) {
    // 今天不在「有记录的日子」里：它排在列表最前面**之外**——
    // 往前翻就是列表第一条，往后翻没有了。
    if (!date) return delta < 0 ? (days[0] ?? null) : null
    return null
  }
  const j = i + (delta < 0 ? 1 : -1)          // 往前翻 = 往列表后面走（新的在前）
  if (j < 0 || j >= days.length) return null
  return days[j] === (today || days[0]) ? '' : days[j]
}

type Cell = { seg?: JourneySegment; sec: number; gap?: [string, string] }

/** 还能补描述的段：没描述、**后端没判它出局**、而且大图还在。
 *
 *  没大图的（黑名单挡过、存图失败、三天过期）再点多少次「描述」都还是没描述
 *  ——原来它们也被数进「描述这 N 段」，09-17 那天 71 段没截图，按钮一直亮着、
 *  点了只回一句「没有要描述的了」（第 778 轮 / P20 走查）。
 *
 *  **`skip` 那一半是第 793 轮（P50）补的，因为 `has_frame` 会骗人**：后端
 *  `catch_up` 判定「没有截图」时只写了 `skip`，**那条指向不存在的文件的路径
 *  留在 `frames` 里**，于是 `has_frame` 照样是 true。真实数据上 09-16 有 37 段、
 *  09-17 有 71 段正是这个样子——P20 修过的死胡同从另一扇门原样回来了，
 *  而且每点一次「描述」还会新造出几段。后端那一侧已经把路径抹掉了，
 *  这里再守一道：**「补不了」是后端说了算的事实，不是拿 `has_frame` 猜出来的**。 */
export function describable(segs: { desc: string; has_frame: boolean; skip?: string }[]): number {
  return segs.filter((s) => !s.desc && !s.skip && s.has_frame).length
}

/** 一行没有描述时写什么。**「还没描述」是句承诺**——等一等就会有；
 *  补不了的那些要当场说清是为什么，别让人一直等下去。 */
export function sayNoDesc(s: { has_frame: boolean; skip?: string }): string {
  if (s.skip) return `${s.skip}，补不了描述`
  return s.has_frame ? '还没描述' : '没截图，补不了描述'
}

/** 壳那边的状态（`journey:state`）。`until` / `stalled` 是 P20 加的、`fake` 是 P52 加的，
 *  老壳都没有——全可选。 */
type BridgeState = { state: JourneyState; today: number; until?: number; stalled?: string; fake?: boolean }

/** 段 + 空档，按时间排成一条带能画的东西。 */
export function bandCells(segs: JourneySegment[]): Cell[] {
  const out: Cell[] = []
  segs.forEach((s, i) => {
    const prev = segs[i - 1]
    if (prev) {
      const idle = (Date.parse(s.start) - Date.parse(prev.end)) / 1000
      if (idle >= GAP_MIN * 60) out.push({ sec: Math.min(idle, GAP_CAP_SEC), gap: [prev.end, s.start] })
    }
    out.push({ seg: s, sec: secs(s) })
  })
  return out
}

/** 壳落盘用的是 `toISOString()`——**带 Z 的 UTC**。直接 `iso.slice(11,16)` 印出来
 *  会整整差一个时区（东八区就是差 8 小时），而时间轴上的时间差一点都不行。 */
export const hhmm = (iso: string) =>
  new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })

/** 「先不开」就是关掉这一页——**不要引到设置页去**：
 *  不想开的人不欠我们一次设置之旅。 */
/** 日报正文。排得比编辑器紧——它是这一页的开头，不是这一页的全部。 */
function ReportBody({ md }: { md: string }) {
  const ink = (parts: Inline[]) => parts.map((p, i) =>
    p.t === 'b' ? <b key={i}>{p.s}</b> : p.t === 'code' ? <code key={i}>{p.s}</code> : <span key={i}>{p.s}</span>)
  return (
    <div className="jr-md">
      {parseMini(md).map((b, i) =>
        b.kind === 'h' ? <h4 key={i}>{ink(b.parts)}</h4>
        : b.kind === 'ul' ? <ul key={i}>{b.items.map((it, k) => <li key={k}>{ink(it)}</li>)}</ul>
        : b.kind === 'pre' ? <pre key={i}>{b.text}</pre>
        : <p key={i}>{ink(b.parts)}</p>)}
    </div>
  )
}

type Props = {
  onLater: () => void
  onOpenNote: (id: string) => void
  /** 「去这天的日记」（P23 #6）：日记 → 屏幕活动那条路 P21 做了（ribbon 上那一块），
   *  反过来一直没有——从这一页看完一天，想写点什么得自己回树上一层层翻到那个日子。
   *  找或建都在后端那一份 `journal_node`（`POST /notes/today?day=`），这里只递日期。 */
  onOpenJournal: (date: string) => void
}

export default function JourneyPage({ onLater, onOpenNote, onOpenJournal }: Props) {
  // `null` = 还没问到。**问不到不能当成「没开过」**：那会把一个正在记录的
  // 应用画成「要不要开启」，用户再点一次「开始记录」——看着像没生效。
  const [state, setState] = useState<JourneyState | 'unknown' | null>(null)
  const [day, setDay] = useState<JourneyDay | null>(null)
  // 只用来翻前几天；空串 = 今天（后端自己取当天，跨零点不用刷新页面）。
  // 初值从「待打开的那一天」取——日记那篇笔记的 ribbon 点进来时要落在那一天
  // （`util/journeyOpen`，计划 §8.4）
  const [date, setDate] = useState(takePendingJourneyDay)
  // 有记录的日子（新的在前）。翻天按它走——**按日期加一减一会走进一串空日子**。
  const [days, setDays] = useState<string[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [writing, setWriting] = useState(false)
  const [spanning, setSpanning] = useState(0)
  /** 哪几块展开着（按块首时间记）。翻天 / 刷新之后自然回到收起——
   *  展开是「我要核对这一段」的一次性动作，不是一种偏好。 */
  const [opened, setOpened] = useState<Set<string>>(new Set())
  /** 限时暂停到几点（毫秒）；自动描述卡在哪（空串 = 没卡） */
  const [until, setUntil] = useState(0)
  const [stalled, setStalled] = useState('')
  /** 后端没应答时**要说出来**：原来 `journeyDay` 失败就 `setDay(null)`，页面照样写着
   *  「记录中。今天刚开始记…」——后端死了看起来跟一天没记一模一样（第 778 轮 / P20）。 */
  const [offline, setOffline] = useState(false)
  /** 留多久。**知情选择那一屏也要用它**——「留多久」那一条得写用户**现在**
   *  设的数，不是文档里的数（第 779 轮 / P21）。 */
  const [keepFor, setKeepFor] = useState<JourneyRetention | null>(null)
  /** 「写这一天的回顾」/「最近 N 天」转起来时的停止（P3 / P9 给别的忙态钮加过，
   *  这两个一直没跟上——转起来只能干等满 300 秒，页面上一个出口都没有）。 */
  const writeAbort = useRef<AbortController | null>(null)
  const spanAbort = useRef<AbortController | null>(null)
  /** 删一段 / 删掉这一天的确认，**摊在页面里，不是 `window.confirm`**（P23 #5）。
   *  两个理由，第二个是硬的：
   *    · 系统弹窗只塞得下一句话，而这两下要说清「连知识库里那条记忆一起删」；
   *      「全部删掉」P21 已经是页面内的红框了，这两处不该是另一种东西。
   *    · **`window.confirm` 会把整个渲染进程挡住**——P21 实拍：探针点下去之后
   *      页面一帧都不再画，只能靠 `confirmyes` 把它换掉才走得下去。挡得住探针，
   *      也就挡得住自动保存、轮询和正在跑的续写。
   *  `null` = 没在确认；删一段记的是段的序号 `i`。 */
  const [confirmSeg, setConfirmSeg] = useState<number | null>(null)
  const [confirmDay, setConfirmDay] = useState(false)
  /** ⌘K 的「这一周的屏幕活动」把人送到这一页时，把「最近 7 天」标出来**但不开跑**
   *  （P23 #7）。理由写在 `util/journeyOpen.takePendingJourneySpan` 上。 */
  /** 今天是哪天。**后端说了算**（开着页面过零点也跟得上），第一次加载时 `date` 是空串，
   *  回来的 `day.date` 就是今天。`stepDay` 要它——见那个函数（P52）。 */
  const [today, setToday] = useState('')
  const [fake, setFake] = useState(false)
  const [spanHint, setSpanHint] = useState(takePendingJourneySpan)
  const spanBox = useRef<HTMLDivElement>(null)
  const bridge = window.memoketDesktop?.journey

  const refresh = useCallback(async () => {
    // 网页版压根没有壳：那不是出错，就是「没开过」（这一页会告诉你要用桌面版）。
    if (!bridge) setState('off')
    else await bridge.state().then((s: BridgeState) => { setState(s.state); setUntil(s.until ?? 0); setStalled(s.stalled ?? ''); setFake(!!s.fake) })
      .catch(() => setState((v) => v ?? 'unknown'))
    journeyDay(date).then((d) => { setDay(d); setOffline(false); if (!date) setToday(d.date) }).catch(() => { setDay(null); setOffline(true) })
    journeyDays().then(setDays).catch(() => setDays((v) => v ?? []))
    // 后端读不到就保住上一份：那一屏知情选择上「留多久」宁可不写，也不能写错
    journeyRetention().then(setKeepFor).catch(() => setKeepFor((v) => v ?? null))
  }, [bridge, date])

  // 每 30 秒对一次状态和段数；**窗口看不见就不轮询**，回到前台立刻对一次（util/poll）
  useEffect(() => { void refresh() }, [refresh])
  usePoll(() => void refresh(), 30_000)

  // 这一页已经开着时从日记 ribbon 再点一次：页面不会重挂，得当场翻过去
  useEffect(() => {
    const on = (e: Event) => setDate((e as CustomEvent<string>).detail ?? '')
    window.addEventListener(JOURNEY_DAY_EVENT, on)
    return () => window.removeEventListener(JOURNEY_DAY_EVENT, on)
  }, [])

  // 翻到别的一天，没确认完的那两个确认就作废——**段的序号是「这一天的第几段」**，
  // 留着的话翻过去正好撞上另一天同序号的那一段（P23 #5）。
  useEffect(() => { setConfirmSeg(null); setConfirmDay(false) }, [date])

  // ⌘K 已经开着这一页时再按一次：页面不重挂，同样得当场把提示摆出来 + 滚过去（P23 #7）
  useEffect(() => {
    const on = (e: Event) => setSpanHint(Number((e as CustomEvent<number>).detail) || 0)
    window.addEventListener(JOURNEY_SPAN_EVENT, on)
    return () => window.removeEventListener(JOURNEY_SPAN_EVENT, on)
  }, [])
  // **也要等这一页真的画出来**（第一版实拍就栽在这）：`state`/`days` 还没回来时整页只有一个
  // 「…」，`spanBox` 是 null，scroll 白跑一次、之后 `spanHint` 再没变过也就不会重来——
  // 用户从 ⌘K 过来只看见页顶，那条提示在两屏以下。把加载完这件事也算进依赖，
  // 再补一次延时：「不记这些」「留多久」是各自异步拉的，落下来会把这一块又顶下去。
  useEffect(() => {
    if (spanHint <= 0) return
    const go = () => spanBox.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
    go()
    const t = setTimeout(go, 700)
    return () => clearTimeout(t)
  }, [spanHint, state, days, keepFor])

  async function catchUp() {
    setBusy(true)
    try {
      const r = await journeyCatchUp(date, 10)
      // **一段都没描述成，不等于「什么都没发生」**（第 793 轮 / P50 实拍）：
      // 这一下常常是把几段**永久判成补不上**（截图早就没了）。原来一律回
      // 「没有要描述的了」——用户刚看着按钮写「描述这 10 段」，点完那句话等于
      // 说「本来就没有」，而盘上刚刚多了 9 条 `skip`。
      toast(r.described
        ? `描述了 ${r.described} 段，入库 ${r.ingested} 段${r.left ? `，还剩 ${r.left} 段` : ''}`
        : r.skipped
          ? `这 ${r.skipped} 段的截图已经没了，补不了描述${r.left ? `，还剩 ${r.left} 段等着` : ''}`
          : '没有要描述的了')
      await refresh()
    } catch (e) { toast(friendlyError(e), 'error') } finally { setBusy(false) }
  }

  /** 写这一天的回顾。**转起来要能停**（P21，跟 P3 / P9 给骨架 / 智能排版 /
   *  做幻灯片加的「停止」是同一条）：一次模型调用可以跑满 300 秒，而在这之前
   *  页面上一个出口都没有——按钮禁用、Esc 没用，只能干等。 */
  async function writeReport() {
    if (writing) { stopWrite(); return }
    setWriting(true)
    const ctrl = new AbortController()
    writeAbort.current = ctrl
    try {
      const r = await journeyReport(date, ctrl.signal)
      setDay((d) => (d ? { ...d, report: r.report, report_segments: r.segments,
                           report_at: r.report_at, report_notes: r.notes ?? [] } : d))
      toast(`日报写好了（${r.segments} 段，${(r.took_ms / 1000).toFixed(0)} 秒）`)
    } catch (e) {
      // **停下来要说一句**：不说的话用户分不清是停了还是卡了（P3 第 13 条）
      if ((e as Error).name === 'AbortError') toast('已停止，这一天的回顾没写成——上一份（如果有）还在')
      else toast(friendlyError(e), 'error')
    } finally { writeAbort.current = null; setWriting(false) }
  }

  function stopWrite() { writeAbort.current?.abort() }

  /** 日报是跟着这一天走的，删这一天就没了。**想留就存成一篇笔记**——
   *  它会挂在当天那页日记下面（回顾是跟着日期走的东西，日记树就是按日期组织的），
   *  同名覆盖，重写一次不会在树上留一串。 */
  async function saveReport() {
    if (!day?.report) return
    try {
      const r = await journeySaveReport(day.date)
      window.dispatchEvent(new CustomEvent('notes-changed'))
      toast('存进了当天那页日记下面')
      onOpenNote(r.note_id)
    } catch (e) { toast(friendlyError(e), 'error') }
  }

  /** 一段时间的回顾。**产出是一篇笔记**——写完直接把人送过去，
   *  不在这一页里再开一个只读小窗：那种东西关掉就没了。 */
  async function runSpan(days: number) {
    if (spanning === days) { spanAbort.current?.abort(); return }   // 第二下 = 停止
    setSpanning(days)
    const ctrl = new AbortController()
    spanAbort.current = ctrl
    try {
      const r = await journeySpan(days, ctrl.signal)
      window.dispatchEvent(new CustomEvent('notes-changed'))
      toast(`按 ${r.days} 天的日报写好了${r.missing.length ? `（${r.missing.length} 天没有日报）` : ''}`)
      onOpenNote(r.note_id)
    } catch (e) {
      if ((e as Error).name === 'AbortError') toast('已停止，这份回顾没写成，树上也没多出笔记')
      else toast(friendlyError(e), 'error')
    } finally { spanAbort.current = null; setSpanning(0) }
  }

  /** 删一段。**黑名单挡不住所有东西**——同事发来的一张截图、一封还没公开的
   *  邮件、一个忘了关的窗口。只能删一整天的话，用户为了抹掉一分钟会丢掉一整天，
   *  或者干脆把这个功能关掉。 */
  async function dropSeg(s: JourneySegment) {
    if (!day) return
    setConfirmSeg(null)
    // **删不成必须说一句。** 第 779 轮（P21）实拍：后端没起来时这两个动作
    // 一个字都不说（`promise Failed to fetch` 进日志、`toasts=[]`），而用户
    // 刚点过「确定」——他会以为删掉了。「我以为删干净了」是这个功能最不能出的错。
    try {
      const r = await journeyDeleteSegment(day.date, s.i)
      toast(`删掉了这一段${r.removed_facts ? `，连带 ${r.removed_facts} 条记忆` : ''}`)
      await refresh()
    } catch (e) { toast('没删成这一段，它还在：' + friendlyError(e), 'error') }
  }

  async function wipe() {
    if (!day) return
    setConfirmDay(false)
    try {
      const r = await journeyDeleteDay(day.date)
      toast(`删掉了这一天${r.removed_facts ? `，连带 ${r.removed_facts} 条记忆` : ''}`)
      await refresh()
    } catch (e) { toast(`没删成 ${day.date}，这一天还在：` + friendlyError(e), 'error') }
  }

  const known = days ?? []
  const prev = stepDay(known, date, -1, today)
  const next = stepDay(known, date, 1, today)

  if (state === null || days === null) return <p className="muted" style={{ padding: 16 }}>…</p>
  if (state === 'unknown') {
    return (
      <div className="kb-page kb-empty">
        <Icon n="bx-error" />
        <h3>问不到采集状态</h3>
        <p className="muted">应用的采集那半边没应答，<b>现在是开是关都说不准</b>。
          菜单栏那个图标才是准的；重启一次应用通常就好了。</p>
      </div>
    )
  }

  // —— 没开过：那一屏知情选择。**不能跳过、不能默认勾选**（§1 ①）————————
  //
  // 「没开过」的判断必须看**有没有记录过**，不能只看当前状态：停掉之后如果
  // 也退回这一屏，以前记的东西就既看不到也删不掉了（第 645 轮自查）。
  if (state === 'off' && known.length === 0) {
    return (
      <div className="kb-page journey-consent">
        <h2 className="kb-note-title"><Icon n="bx-desktop" className="muted" /> 屏幕活动记录</h2>
        <p className="muted">
          每隔一会儿看一眼你的屏幕，把「你在做什么」记成一句话，到晚上汇成一份今天做了什么。
        </p>
        <dl className="journey-facts">
          <dt>记什么</dt><dd>只记「在哪个应用、在做什么」的一句话描述。截图看完就删，只留一张缩略图给你核对</dd>
          {/* **这里的每一句都要跟代码对得上。** 段落和描述确实只在这台机器上，
              但看图那台是配置里指定的（默认是内网那台），不是「本机」——写成
              「不出这台电脑」就是假的（第 641 轮自查）。设置页里能看到它指向哪。 */}
          <dt>存在哪</dt><dd>段落和描述只在这台机器上。截图发给设置里那台看图的模型（默认是内网那台），跟写作用哪家模型无关</dd>
          {/* **第五条（P21 补上）。** 计划 §8.3 那一屏本来就是五条，一直少这一条
              ——因为在 P21 之前**真的没有保留期**：段落描述和缩略图永远不删。
              先做出清理，才敢把这句话写上去。数字**从后端读用户现在设的那份**，
              不写死在这儿：设置里改完这一屏还写着 30 天就又是一句假话。 */}
          <dt>留多久</dt>
          <dd>{keepFor
            ? <>描述留 <b>{sayKeep(keepFor.segment_days)}</b>，缩略图留 <b>{sayKeep(keepFor.thumb_days)}</b>，
                原始截图最多 {keepFor.frame_days} 天（描述做完当场就删）。到期的自己删掉，
                <b>连它抽进知识库的记忆一起删</b>。这几个数在这一页下面「留多久」那块随时改，也能一键全部删掉</>
            : <>到期的自己删掉，连它抽进知识库的记忆一起删。开了之后在这一页下面「留多久」那块能看到和改</>}
          </dd>
          <dt>不记什么</dt><dd>密码管理器、银行、隐私窗口——默认就不记，命中时连截图都不拍</dd>
          <dt>怎么关</dt><dd>菜单栏一直有个开关。删一段或删一整天，都会<b>连它抽进知识库的记忆一起删</b></dd>
        </dl>
        <div className="row" style={{ gap: 8, marginTop: 14 }}>
          <button className="primary" onClick={() => { void bridge?.start().then(refresh) }}
                  disabled={!bridge} title={bridge ? '' : '网页版没有采集能力，要用桌面版'}>开始记录</button>
          <button onClick={onLater}>先不开</button>
        </div>
        <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: 0 }}>
          {bridge ? '点「开始记录」之后，macOS 会问一次屏幕录制权限——那一下必须给，不然什么都记不到。'
                  : '网页版没有采集能力，要用桌面版。'}
        </p>
      </div>
    )
  }

  // —— 权限被系统收走：**最容易漏也最坑的一种**（§8.5）————————————————
  if (state === 'no-permission') {
    return (
      <div className="kb-page kb-empty">
        <Icon n="bx-error" />
        <h3>截不到屏了</h3>
        <p className="muted">
          多半是 macOS 的「屏幕录制」权限被关掉了——<b>现在什么都记不到</b>。
          到「系统设置 › 隐私与安全性 › 屏幕录制」里把 MEMOKET NOTE 打开，再回来。
        </p>
      </div>
    )
  }

  const segs = day?.segments ?? []
  const colors = appColors(segs.map((s) => s.app))
  const runs = groupRuns(segs)
  const total = segs.reduce((n, s) => n + secs(s), 0)
  const byApp = new Map<string, number>()
  for (const s of segs) byApp.set(s.app, (byApp.get(s.app) ?? 0) + secs(s))
  const left = describable(segs)
  const described = segs.filter((s) => s.desc).length
  // 日报写完之后又多出来的段数（>0 就该提醒重写）
  const grown = day?.report ? Math.max(0, described - (day.report_segments || 0)) : 0

  return (
    <div className="kb-page">
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span className="row" style={{ gap: 6, alignItems: 'baseline' }}>
          <h2>{day?.date ?? '今天'} · 屏幕活动</h2>
          {/* 一天一页、翻得动。没有这两个箭头，「昨天我在干嘛」就只能干瞪眼 */}
          <button className="icon-btn sm" title="上一条记录" disabled={!prev}
                  onClick={() => prev !== null && setDate(prev)}><Icon n="bx-chevron-left" /></button>
          <button className="icon-btn sm" title="下一条记录" disabled={next === null}
                  onClick={() => next !== null && setDate(next)}><Icon n="bx-chevron-right" /></button>
        </span>
        <span className="row" style={{ gap: 6 }}>
          {/* 停掉之后这一页还在（要能回看、要能删），所以这里也得能**重新开起来** */}
          {state === 'off'
            ? <button className="primary" onClick={() => { void bridge?.start().then(refresh) }}
                      disabled={!bridge} title={bridge ? '' : '网页版没有采集能力，要用桌面版'}>开始记录</button>
            : state === 'paused'
              ? <button onClick={() => { void bridge?.resume().then(refresh) }}>继续记录</button>
              : <button onClick={() => { void bridge?.pause(60).then(refresh) }}>暂停 1 小时</button>}
          {/* **反过来那条路**（P23 #6）：日记 → 屏幕活动 P21 做了（那篇日记 ribbon 上
              一块摘要 + 一条链接），屏幕活动 → 日记一直没有。看完这一天想写点什么，
              原来得自己回树上「日记 / 年 / 月 / 日」翻四层。没有那篇就建一篇——
              跟启动栏「今天的日记」同一个规矩（后端 `journal_node` 那一份）。 */}
          <button className="linklike" onClick={() => onOpenJournal(day?.date ?? '')}
                  title="打开这一天的日记（没有就建一篇）">去这天的日记</button>
          {/* **有日报、段被删光的那一天也得删得掉**（第 794 轮 / P52）：后端 `days()` 现在按
              「有活的段**或者**有日报」列天，那一天照样在翻天列表里、页面上照样画着那张日报卡，
              这个钮却只看 `segs.length`——于是列得出来、删不掉。判据跟后端那句对齐。 */}
          <button className="linklike danger" onClick={() => setConfirmDay(true)}
                  disabled={(!segs.length && !day?.report) || confirmDay}
                  title={segs.length || day?.report ? '' : '这一天还没有记录'}>删掉这一天</button>
        </span>
      </div>

      {/* 删掉这一天：**页面里的确认，不是系统弹窗**（P23 #5，跟「全部删掉」一致）。
          把这一下会删掉什么一条条摆出来——一句「确定吗」说不清「连记忆一起删」。 */}
      {confirmDay && day && (
        <div className="journey-keep-confirm" role="alertdialog" aria-label={`删掉 ${day.date} 的屏幕活动`}>
          <b>删掉 {day.date} 的屏幕活动？这一下会删掉：</b>
          <ul>
            {/* 段已经删光、只剩日报的那一天也走这条路（P52）：那时候写
                「0 段，其中 0 段有描述」是句废话，删掉的其实只有日报。 */}
            {segs.length > 0 && <li>{segs.length} 段，其中 {segs.filter((s) => s.desc).length} 段有描述</li>}
            {segs.some((s) => s.has_thumb) && <li>{segs.filter((s) => s.has_thumb).length} 张缩略图，连同还没删的原始截图</li>}
            {day.report && <li>这一天写好的那份日报</li>}
            {segs.length > 0 && <li>这些描述抽进知识库的那些记忆</li>}
          </ul>
          <p className="muted">删完就真的没有了，没有回收站。存成笔记的那几份日报留着——那是笔记，不是记录。</p>
          <div className="row" style={{ gap: 6 }}>
            <button className="danger" onClick={() => void wipe()}>
              <Icon n="bx-trash" /> 确认删掉这一天
            </button>
            <button onClick={() => setConfirmDay(false)}>先不删</button>
          </div>
        </div>
      )}

      <p className="muted journey-state">
        {/* 翻到往日时「记录中」是句废话，还容易被读成「在补记那天」。
            「没在记」反过来要说——那是用户最需要知道的一种状态。 */}
        {state === 'off' ? '没在记录 —— 以前记的还在，可以回看、可以删。'
          : date ? '' : state === 'paused'
            ? (until ? `已暂停 —— 到 ${hhmm(new Date(until).toISOString())} 自己继续。` : '已暂停 —— 这段时间不会记录。')
            : '记录中。'}
        {segs.length > 0 && ` ${date ? '这天' : '今天'} ${segs.length} 段，合计 ${saySpan(total)}。`}
      </p>
      {/* **挂着假采集源就得当场说**（P52）：这条路是走查用的（`journey/_fake.json`），
          可这一页的全部前提是「这里写的都是真发生过的事」。一个安静的假数据源
          比没有这条路糟得多，所以它一开，这一句就在最显眼的地方。 */}
      {fake && (
        <p className="muted journey-state"><Icon n="bx-error" /> 这一页画的不是真的屏幕活动
          ——这个实例挂着假采集源（<code>journey/_fake.json</code>），一张屏都没拍。
          删掉那个文件再重开才会真的记。</p>
      )}
      {offline && (
        <p className="muted journey-state"><Icon n="bx-error" /> 后端没应答，这一天的记录读不出来——采集照常在壳里跑，稍后再刷新。</p>
      )}
      {/* 描述卡住了要说出来：看图模型连不上时壳每 3 分钟失败一次，
          用户那边只看见一整页「还没描述」，以为功能坏了 */}
      {!date && stalled && left > 0 && state === 'running' && (
        <p className="muted journey-state"><Icon n="bx-error" /> 自动描述停了：{stalled}。每 3 分钟会再试一次；也可以下面手动点「描述」。</p>
      )}

      {/* **报告在上、证据在下**（§8.3 ②）：先看今天是怎么回事，要核对再往下看 */}
      {day?.report ? (
        <div className="card journey-report">
          <div className="row" style={{ alignItems: 'center', gap: 8, marginBottom: 2 }}>
            <span className="muted" style={{ fontSize: 'var(--t-sm)' }}
                  title={day.report_at ? `写于 ${hhmm(day.report_at)}` : undefined}>
              这一天的回顾
              {/* **日报是快照，这一天还在长**：不说清楚它按多少段写的，下午看到的
                  还是上午那份，却没有任何迹象说明它已经过期了 */}
              {grown > 0
                ? `　按 ${day.report_segments} 段写的，之后又记了 ${grown} 段`
                : day.report_segments > 0 && `　按 ${day.report_segments} 段写的`}
            </span>
            <span style={{ flex: 1 }} />
            <button className="chip chip-action" onClick={() => void saveReport()}><Icon n="bx-save" /> 存为笔记</button>
            {/* 转起来时这个钮就是「停止」——**不是禁用**。禁用掉的忙态钮等于
                把人锁在一次可以跑满 300 秒的调用里（P3 第 13 / 17 / 18 条）。 */}
            <button className={'chip chip-action' + (grown > 0 ? ' hot' : '')}
                    onClick={() => void writeReport()}
                    title={writing ? '停止这次重写' : '按现在的记录重写一份'}>
              {writing ? <><span className="spinner" /> 停止</> : <><Icon n="bx-refresh" /> 重写</>}
            </button>
          </div>
          <ReportBody md={day.report} />
          {/* 日报的确定性体检（后端 `harness/checks/journey.py`，计划 8.2）。
              **判了不拦**——一次模型调用、一次成型的产物，判据结果摆在它下面，
              要不要「重写」由用户定。跟幻灯片、骨架、续写是同一档。 */}
          {(day.report_notes ?? []).length > 0 && (
            <ul className="journey-report-notes">
              {(day.report_notes ?? []).map((n, i) => <li key={i} style={{ marginBottom: 4 }}>{n}</li>)}
            </ul>
          )}
        </div>
      ) : described > 0 && (
        <div className="row">
          <button className="primary" onClick={() => void writeReport()}
                  title={writing ? '停止，这一天的回顾就不写了' : undefined}>
            {writing ? <><span className="spinner" /> 正在写…　停止</> : `写这一天的回顾（${described} 段）`}
          </button>
          <span className="muted" style={{ fontSize: 'var(--t-sm)', alignSelf: 'center', marginInlineStart: 8 }}>
            一次模型调用。时长是数出来的，模型只写推进了什么、卡在哪。
          </span>
        </div>
      )}

      {segs.length === 0 ? (
        /* **「今天刚开始记」要先确认真的在记**（P31 #3）：这一句原来只看 `date`，不看
           `state`。停掉采集（或还没开过）再打开今天这一页，上面写着「没在记录」，下面却说
           「今天刚开始记，攒够一段就会出现在这儿」——实拍两句话贴在一起互相打脸，
           而且是句空头支票：不在记录，等到明天也不会有东西出现。 */
        !offline && <p className="muted">{
          date ? '这一天没有记录。'
            : state === 'running' ? '今天刚开始记，攒够一段就会出现在这儿。'
              : state === 'paused' ? '今天还没有记录——现在是暂停着的，「继续记录」之后才会接着记。'
                : '今天还没有记录——现在没在记录，点右上角「开始记录」才会开始攒。'
        }</p>
      ) : (
        <>
          {/* 一天一条带：**一眼回答「时间去哪了」**。不画饼图——占比不是这里的问题 */}
          <div className="journey-band" role="img" aria-label={`今天 ${saySpan(total)}`}>
            {bandCells(segs).map((c, i) => (
              <span key={i} className={c.gap ? 'journey-gap' : undefined}
                    title={c.gap ? `${hhmm(c.gap[0])}–${hhmm(c.gap[1])} 没在记`
                                 : `${hhmm(c.seg!.start)}–${hhmm(c.seg!.end)} ${c.seg!.app}`}
                    style={{ flex: `${Math.max(c.sec, 60)} 0 0`,
                             background: c.gap ? undefined : colors.get(c.seg!.app) ?? OTHER }} />
            ))}
          </div>
          <div className="chip-wrap journey-legend">
            {[...byApp.entries()].sort((a, b) => b[1] - a[1]).map(([app, sec]) => (
              <span key={app} className="badge">
                <i className="journey-dot" style={{ background: colors.get(app) ?? OTHER }} />
                {app} {saySpan(sec)}
              </span>
            ))}
          </div>

          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline', marginTop: 14 }}>
            <h3 className="kb-section-title">时间轴</h3>
            {left > 0 && (
              <button onClick={() => void catchUp()} disabled={busy}>
                {busy ? <span className="spinner" /> : `描述这 ${Math.min(left, 10)} 段`}
              </button>
            )}
          </div>
          <div className="stack">
            {/* **连着说同一件事的并成一块**（`util/journeyRuns`）。读真实产出读出来的：
                连看一个多小时 Firebase 崩溃数据，时间轴上摊成八行近似重复，
                这一页就退回成一份流水账。并在**显示层**——采集层并了就再也拆不开，
                而每一段的截图凭据和删除入口都必须还在，所以块是能展开的。 */}
            {runs.map((run, ri) => {
              const one = run.segs.length === 1
              const open = one || opened.has(run.start)
              return (
                <div key={ri} className={'journey-run' + (open && !one ? ' open' : '')}>
                  {!one && (
                    <div className="journey-row journey-run-head">
                      <span className="journey-time">{hhmm(run.start)}–{hhmm(run.end)}</span>
                      <span className={'journey-desc' + (run.desc ? '' : ' muted')}>
                        {/* 这一块里**只要还有一段补得上**就说「还没描述」；
                            一段都补不上时，说其中第一条给出的理由。 */}
                        {run.desc || sayNoDesc(run.segs.find((s) => !s.skip && s.has_frame) ?? run.segs[0])}
                      </span>
                      <span className="journey-app" title={run.app}>
                        <i className="journey-dot" style={{ background: colors.get(run.app) ?? OTHER }} />
                        <span className="journey-app-name">{run.app}</span>
                      </span>
                      <button className="chip journey-run-more"
                              aria-expanded={open}
                              title={open ? '收起这几段' : '展开看这几段各自记了什么'}
                              onClick={() => setOpened((o) => {
                                const n = new Set(o)
                                if (!n.delete(run.start)) n.add(run.start)
                                return n
                              })}>
                        {run.segs.length} 段 <Icon n={open ? 'bx-chevron-up' : 'bx-chevron-down'} />
                      </button>
                    </div>
                  )}
                  {open && run.segs.map((s) => (
                    <div key={s.i} className="journey-row">
                      <span className="journey-time">{hhmm(s.start)}–{hhmm(s.end)}</span>
                      <span className={'journey-desc' + (s.desc ? '' : ' muted')}>
                        {s.desc || sayNoDesc(s)}
                        {/* 缩略图是**凭据**：一句没有任何依据的描述，用户没法判断它是不是编的。
                            默认不占地方，鼠标停在那一行才出现。 */}
                        {s.has_thumb && (
                          <img className="journey-thumb" loading="lazy" alt=""
                               src={journeyThumb(day!.date, s.i)} />
                        )}
                      </span>
                      <span className="journey-app" title={s.title || s.app}>
                        <i className="journey-dot" style={{ background: colors.get(s.app) ?? OTHER }} />
                        <span className="journey-app-name">{s.app}</span>
                      </span>
                      <button className="icon-btn sm journey-del" title="删掉这一段（连它抽出来的记忆一起）"
                              aria-expanded={confirmSeg === s.i}
                              onClick={() => setConfirmSeg((v) => (v === s.i ? null : s.i))}><Icon n="bx-trash" /></button>
                      {/* 删一段的确认**长在这一行下面**（P23 #5）：系统弹窗里只看得到
                          一句话，而用户要核对的正是「这一段到底是哪一段」——
                          原话、时间、应用都在上面那一行摆着，摊在原地才对得上。 */}
                      {confirmSeg === s.i && (
                        <div className="journey-row-confirm" role="alertdialog"
                             aria-label={`删掉 ${hhmm(s.start)}–${hhmm(s.end)} 这一段`}>
                          <b>删掉这一段？</b>
                          <p className="muted">{s.desc || '（还没描述）'}</p>
                          <p className="muted">连它抽进知识库的记忆一起删，删完就没有了。</p>
                          <div className="row" style={{ gap: 6 }}>
                            <button className="danger" onClick={() => void dropSeg(s)}>
                              <Icon n="bx-trash" /> 确认删掉
                            </button>
                            <button onClick={() => setConfirmSeg(null)}>先不删</button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )
            })}
          </div>
        </>
      )}

      <JourneyDenyPanel />

      {/* 「留多久」+「全部删掉」。跟「不记这些」挨着——它们回答的是同一个问题：
          **我能不能把它抹掉**（§8.1 的三问之一）。清完要刷这一页：
          删掉的那几天还留在翻天列表里的话，用户会以为没删成。 */}
      <JourneyRetentionPanel onChanged={() => void refresh()} />

      {/* 一段时间的回顾：**日报 → 长报告 → 一篇笔记**。放在最下面——
          它不是「今天」这一页的主角，是从这一页出去的一条路（§4.2）。 */}
      <div className="journey-span" ref={spanBox}>
        <h3 className="kb-section-title">回顾一段时间</h3>
        <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: '2px 0 6px' }}>
          把这些天的日报汇成一篇长回顾，落成一篇笔记——之后还能接着编辑、接着续写。
          没写过日报的那几天会被跳过，并写在笔记里。<b>按一下是一次模型调用。</b>
        </p>
        {/* ⌘K 进来的那一下**只把人送到这儿、把要按的那个钮指出来**，不替他按下去
            （P23 #7，理由在 `util/journeyOpen`）。 */}
        {spanHint > 0 && spanning === 0 && (
          <p className="journey-span-hint">
            <Icon n="bx-info-circle" /> 从 ⌘K 过来的：要写「最近 {spanHint} 天」的回顾，按下面那个钮。
            <b>它是一次模型调用，所以这一下留给你按。</b>
          </p>
        )}
        <div className="row" style={{ gap: 6 }}>
          {/* 跑着的那个变成「停止」，另一个才禁用（跑完才能换范围）。
              两个都禁用的话，这次跑起来就没有出口了。 */}
          {[7, 30].map((d) => (
            <button key={d} className={spanHint === d && spanning === 0 ? 'primary' : undefined}
                    disabled={spanning !== 0 && spanning !== d} onClick={() => { setSpanHint(0); void runSpan(d) }}
                    title={spanning === d ? '停止这次回顾' : spanning !== 0 ? '正在写，跑完才能换范围' : '一次模型调用'}>
              {spanning === d ? <><span className="spinner" /> 最近 {d} 天　停止</> : `最近 ${d} 天`}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
