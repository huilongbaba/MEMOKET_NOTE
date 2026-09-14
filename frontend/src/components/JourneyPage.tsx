import { useCallback, useEffect, useState } from 'react'

import { journeyCatchUp, journeyDay, journeyDeleteDay, type JourneyDay, type JourneySegment } from '../api'
import { toast } from '../toast'

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
const GAP_MIN = 15
/** 空档在带上最多占这么久的宽度：隔夜 12 小时不能把一整天挤成两条缝。 */
const GAP_CAP_SEC = 20 * 60

/** 翻一天。回到今天就还原成空串——让后端继续负责「今天是哪天」，
 *  不然开着页面过零点，日期就钉死在昨天了。 */
export function shiftDay(date: string, delta: number, today = new Date()): string {
  const base = date ? new Date(date + 'T12:00:00') : today
  const d = new Date(base.getFullYear(), base.getMonth(), base.getDate() + delta)
  const iso = [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-')
  const now = [today.getFullYear(), String(today.getMonth() + 1).padStart(2, '0'), String(today.getDate()).padStart(2, '0')].join('-')
  return iso >= now ? '' : iso
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
type Props = { onLater: () => void }

export default function JourneyPage({ onLater }: Props) {
  // `null` = 还没问到。**问不到不能当成「没开过」**：那会把一个正在记录的
  // 应用画成「要不要开启」，用户再点一次「开始记录」——看着像没生效。
  const [state, setState] = useState<JourneyState | 'unknown' | null>(null)
  const [day, setDay] = useState<JourneyDay | null>(null)
  // 只用来翻前几天；空串 = 今天（后端自己取当天，跨零点不用刷新页面）
  const [date, setDate] = useState('')
  const [busy, setBusy] = useState(false)
  const bridge = window.memoketDesktop?.journey

  const refresh = useCallback(async () => {
    // 网页版压根没有壳：那不是出错，就是「没开过」（这一页会告诉你要用桌面版）。
    if (!bridge) setState('off')
    else await bridge.state().then((s) => setState(s.state)).catch(() => setState((v) => v ?? 'unknown'))
    journeyDay(date).then(setDay).catch(() => setDay(null))
  }, [bridge, date])

  useEffect(() => { void refresh(); const t = setInterval(() => void refresh(), 30_000); return () => clearInterval(t) }, [refresh])

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

  async function wipe() {
    if (!day) return
    if (!window.confirm(`删掉 ${day.date} 的屏幕活动？\n\n连同它抽进知识库的记忆一起删——删完就真的没有了。`)) return
    const r = await journeyDeleteDay(day.date)
    toast(`删掉了这一天${r.removed_facts ? `，连带 ${r.removed_facts} 条记忆` : ''}`)
    await refresh()
  }

  if (state === null) return <p className="muted" style={{ padding: 16 }}>…</p>
  if (state === 'unknown') {
    return (
      <div className="kb-page kb-empty">
        <i className="bx bx-error" />
        <h3>问不到采集状态</h3>
        <p className="muted">应用的采集那半边没应答，<b>现在是开是关都说不准</b>。
          菜单栏那个图标才是准的；重启一次应用通常就好了。</p>
      </div>
    )
  }

  // —— 没开过：那一屏知情选择。**不能跳过、不能默认勾选**（§1 ①）————————
  if (state === 'off') {
    return (
      <div className="kb-page journey-consent">
        <h2>屏幕活动记录</h2>
        <p className="muted">
          每隔一会儿看一眼你的屏幕，把「你在做什么」记成一句话，到晚上汇成一份今天做了什么。
        </p>
        <dl className="journey-facts">
          <dt>记什么</dt><dd>只记「在哪个应用、在做什么」的一句话描述；截图不保存</dd>
          <dt>存在哪</dt><dd>全在这台机器上。看图用的是本机的模型，一张图都不出这台电脑</dd>
          <dt>不记什么</dt><dd>密码管理器、银行、隐私窗口——默认就不记，命中时连截图都不拍</dd>
          <dt>怎么关</dt><dd>菜单栏一直有个开关；删掉某一天会<b>连它抽进知识库的记忆一起删</b></dd>
        </dl>
        <div className="row" style={{ gap: 8, marginTop: 14 }}>
          <button className="primary" onClick={() => { void bridge?.start().then(refresh) }}
                  disabled={!bridge} title={bridge ? '' : '网页版没有采集能力，要用桌面版'}>开始记录</button>
          <button onClick={onLater}>先不开</button>
        </div>
        <p className="muted" style={{ fontSize: 12, margin: 0 }}>
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
        <i className="bx bx-error" />
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
  const total = segs.reduce((n, s) => n + secs(s), 0)
  const byApp = new Map<string, number>()
  for (const s of segs) byApp.set(s.app, (byApp.get(s.app) ?? 0) + secs(s))
  const left = segs.filter((s) => !s.desc).length

  return (
    <div className="kb-page">
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span className="row" style={{ gap: 6, alignItems: 'baseline' }}>
          <h2>{day?.date ?? '今天'} · 屏幕活动</h2>
          {/* 一天一页、翻得动。没有这两个箭头，「昨天我在干嘛」就只能干瞪眼 */}
          <button className="icon-btn sm" title="前一天" onClick={() => setDate((d) => shiftDay(d, -1))}><i className="bx bx-chevron-left" /></button>
          <button className="icon-btn sm" title="后一天" disabled={!date} onClick={() => setDate((d) => shiftDay(d, 1))}><i className="bx bx-chevron-right" /></button>
        </span>
        <span className="row" style={{ gap: 6 }}>
          {state === 'paused'
            ? <button onClick={() => { void bridge?.resume().then(refresh) }}>继续记录</button>
            : <button onClick={() => { void bridge?.pause(60).then(refresh) }}>暂停 1 小时</button>}
          <button className="linklike danger" onClick={() => void wipe()} disabled={!segs.length} title={segs.length ? '' : '今天还没有记录'}>删掉这一天</button>
        </span>
      </div>

      <p className="muted journey-state">
        {/* 翻到往日时「记录中」是句废话，还容易被读成「在补记那天」 */}
        {date ? '' : state === 'paused' ? '已暂停 —— 这段时间不会记录。' : '记录中。'}
        {segs.length > 0 && ` ${date ? '这天' : '今天'} ${segs.length} 段，合计 ${saySpan(total)}。`}
      </p>

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
            {segs.map((s, i) => (
              <div key={i} className="journey-row">
                <span className="journey-time">{hhmm(s.start)}–{hhmm(s.end)}</span>
                <span className="journey-app" title={s.title || s.app}>
                  <i className="journey-dot" style={{ background: colors.get(s.app) ?? OTHER }} />
                  <span className="journey-app-name">{s.app}</span>
                </span>
                <span className={'journey-desc' + (s.desc ? '' : ' muted')}>
                  {s.desc || '还没描述'}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
