import { useCallback, useEffect, useState } from 'react'

import { journeyCatchUp, journeyDay, journeyDays, journeyDeleteDay, journeyDeleteSegment,
         journeyReport, journeySaveReport, journeySpan, journeyThumb,
         type JourneyDay, type JourneySegment } from '../api'
import { groupRuns } from '../util/journeyRuns'
import { parseMini, type Inline } from '../util/miniMarkdown'
import { usePoll } from '../util/poll'
import JourneyDenyPanel from './JourneyDenyPanel'
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
 *  `days` 是新的在前。回到最新的那天就还原成空串：让后端继续负责「今天是哪天」，
 *  不然开着页面过零点，日期就钉死在昨天了。翻到头就返回 null（按钮置灰）。 */
export function stepDay(days: string[], date: string, delta: number): string | null {
  if (!days.length) return null
  const i = date ? days.indexOf(date) : 0
  if (i < 0) return null
  const j = i + (delta < 0 ? 1 : -1)          // 往前翻 = 往列表后面走（新的在前）
  if (j < 0 || j >= days.length) return null
  return j === 0 ? '' : days[j]
}

type Cell = { seg?: JourneySegment; sec: number; gap?: [string, string] }

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

type Props = { onLater: () => void; onOpenNote: (id: string) => void }

export default function JourneyPage({ onLater, onOpenNote }: Props) {
  // `null` = 还没问到。**问不到不能当成「没开过」**：那会把一个正在记录的
  // 应用画成「要不要开启」，用户再点一次「开始记录」——看着像没生效。
  const [state, setState] = useState<JourneyState | 'unknown' | null>(null)
  const [day, setDay] = useState<JourneyDay | null>(null)
  // 只用来翻前几天；空串 = 今天（后端自己取当天，跨零点不用刷新页面）
  const [date, setDate] = useState('')
  // 有记录的日子（新的在前）。翻天按它走——**按日期加一减一会走进一串空日子**。
  const [days, setDays] = useState<string[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [writing, setWriting] = useState(false)
  const [spanning, setSpanning] = useState(0)
  /** 哪几块展开着（按块首时间记）。翻天 / 刷新之后自然回到收起——
   *  展开是「我要核对这一段」的一次性动作，不是一种偏好。 */
  const [opened, setOpened] = useState<Set<string>>(new Set())
  const bridge = window.memoketDesktop?.journey

  const refresh = useCallback(async () => {
    // 网页版压根没有壳：那不是出错，就是「没开过」（这一页会告诉你要用桌面版）。
    if (!bridge) setState('off')
    else await bridge.state().then((s) => setState(s.state)).catch(() => setState((v) => v ?? 'unknown'))
    journeyDay(date).then(setDay).catch(() => setDay(null))
    journeyDays().then(setDays).catch(() => setDays([]))
  }, [bridge, date])

  // 每 30 秒对一次状态和段数；**窗口看不见就不轮询**，回到前台立刻对一次（util/poll）
  useEffect(() => { void refresh() }, [refresh])
  usePoll(() => void refresh(), 30_000)

  async function catchUp() {
    setBusy(true)
    try {
      const r = await journeyCatchUp(date, 10)
      toast(r.described
        ? `描述了 ${r.described} 段，入库 ${r.ingested} 段${r.left ? `，还剩 ${r.left} 段` : ''}`
        : '没有要描述的了')
      await refresh()
    } catch (e) { toast(e instanceof Error ? e.message : String(e), 'error') } finally { setBusy(false) }
  }

  async function writeReport() {
    setWriting(true)
    try {
      const r = await journeyReport(date)
      setDay((d) => (d ? { ...d, report: r.report, report_segments: r.segments,
                           report_at: r.report_at, report_notes: r.notes ?? [] } : d))
      toast(`日报写好了（${r.segments} 段，${(r.took_ms / 1000).toFixed(0)} 秒）`)
    } catch (e) { toast(e instanceof Error ? e.message : String(e), 'error') } finally { setWriting(false) }
  }

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
    } catch (e) { toast(e instanceof Error ? e.message : String(e), 'error') }
  }

  /** 一段时间的回顾。**产出是一篇笔记**——写完直接把人送过去，
   *  不在这一页里再开一个只读小窗：那种东西关掉就没了。 */
  async function runSpan(days: number) {
    setSpanning(days)
    try {
      const r = await journeySpan(days)
      window.dispatchEvent(new CustomEvent('notes-changed'))
      toast(`按 ${r.days} 天的日报写好了${r.missing.length ? `（${r.missing.length} 天没有日报）` : ''}`)
      onOpenNote(r.note_id)
    } catch (e) { toast(e instanceof Error ? e.message : String(e), 'error') } finally { setSpanning(0) }
  }

  /** 删一段。**黑名单挡不住所有东西**——同事发来的一张截图、一封还没公开的
   *  邮件、一个忘了关的窗口。只能删一整天的话，用户为了抹掉一分钟会丢掉一整天，
   *  或者干脆把这个功能关掉。 */
  async function dropSeg(s: JourneySegment) {
    if (!day) return
    if (!window.confirm(`删掉 ${hhmm(s.start)}–${hhmm(s.end)} 这一段？\n\n${s.desc || '（还没描述）'}\n\n连它抽进知识库的记忆一起删。`)) return
    const r = await journeyDeleteSegment(day.date, s.i)
    toast(`删掉了这一段${r.removed_facts ? `，连带 ${r.removed_facts} 条记忆` : ''}`)
    await refresh()
  }

  async function wipe() {
    if (!day) return
    if (!window.confirm(`删掉 ${day.date} 的屏幕活动？\n\n连同它抽进知识库的记忆一起删——删完就真的没有了。`)) return
    const r = await journeyDeleteDay(day.date)
    toast(`删掉了这一天${r.removed_facts ? `，连带 ${r.removed_facts} 条记忆` : ''}`)
    await refresh()
  }

  const known = days ?? []
  const prev = stepDay(known, date, -1)
  const next = stepDay(known, date, 1)

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
  const left = segs.filter((s) => !s.desc).length
  const described = segs.length - left
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
          <button className="linklike danger" onClick={() => void wipe()} disabled={!segs.length} title={segs.length ? '' : '这一天还没有记录'}>删掉这一天</button>
        </span>
      </div>

      <p className="muted journey-state">
        {/* 翻到往日时「记录中」是句废话，还容易被读成「在补记那天」。
            「没在记」反过来要说——那是用户最需要知道的一种状态。 */}
        {state === 'off' ? '没在记录 —— 以前记的还在，可以回看、可以删。'
          : date ? '' : state === 'paused' ? '已暂停 —— 这段时间不会记录。' : '记录中。'}
        {segs.length > 0 && ` ${date ? '这天' : '今天'} ${segs.length} 段，合计 ${saySpan(total)}。`}
      </p>

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
            <button className={'chip chip-action' + (grown > 0 ? ' hot' : '')} disabled={writing}
                    onClick={() => void writeReport()}
                    title={writing ? '正在重写' : '按现在的记录重写一份'}>
              {writing ? <span className="spinner" /> : <Icon n="bx-refresh" />} 重写
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
          <button className="primary" disabled={writing} onClick={() => void writeReport()}>
            {writing ? <><span className="spinner" /> 正在写…</> : `写这一天的回顾（${described} 段）`}
          </button>
          <span className="muted" style={{ fontSize: 'var(--t-sm)', alignSelf: 'center', marginInlineStart: 8 }}>
            一次模型调用。时长是数出来的，模型只写推进了什么、卡在哪。
          </span>
        </div>
      )}

      {segs.length === 0 ? (
        <p className="muted">{date ? '这一天没有记录。' : '今天刚开始记，攒够一段就会出现在这儿。'}</p>
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
                        {run.desc || '还没描述'}
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
                        {s.desc || '还没描述'}
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
                              onClick={() => void dropSeg(s)}><Icon n="bx-trash" /></button>
                    </div>
                  ))}
                </div>
              )
            })}
          </div>
        </>
      )}

      <JourneyDenyPanel />

      {/* 一段时间的回顾：**日报 → 长报告 → 一篇笔记**。放在最下面——
          它不是「今天」这一页的主角，是从这一页出去的一条路（§4.2）。 */}
      <div className="journey-span">
        <h3 className="kb-section-title">回顾一段时间</h3>
        <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: '2px 0 6px' }}>
          把这些天的日报汇成一篇长回顾，落成一篇笔记——之后还能接着编辑、接着续写。
          没写过日报的那几天会被跳过，并写在笔记里。
        </p>
        <div className="row" style={{ gap: 6 }}>
          {[7, 30].map((d) => (
            <button key={d} disabled={spanning !== 0} onClick={() => void runSpan(d)}
                    title={spanning !== 0 ? '正在写，跑完才能换范围' : undefined}>
              {spanning === d ? <><span className="spinner" /> 最近 {d} 天</> : `最近 ${d} 天`}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
