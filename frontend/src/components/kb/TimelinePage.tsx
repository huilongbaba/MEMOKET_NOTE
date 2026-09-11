import { useEffect, useMemo, useState } from 'react'

import { kbDay, kbTimeline, type FactDetail, type KbTimelineMonth } from '../../api'
import { FactList, type KbActions } from './KbBits'

/** 纵向时间线：年 → 月 → 日。条形是当月 / 当天的事实数，点一天展开事实。 */
export default function TimelinePage({ actions }: { actions: KbActions }) {
  const [months, setMonths] = useState<KbTimelineMonth[] | null>(null)
  const [openMonth, setOpenMonth] = useState<string | null>(null)
  const [openDay, setOpenDay] = useState<string | null>(null)
  const [dayFacts, setDayFacts] = useState<Record<string, FactDetail[]>>({})
  useEffect(() => { kbTimeline().then((m) => { setMonths(m); const heavy = [...m].reverse().find((x) => x.facts >= 10) ?? m[m.length - 1]; setOpenMonth(heavy?.month ?? null) }).catch(() => setMonths([])) }, [])
  useEffect(() => {
    if (!openDay || dayFacts[openDay]) return
    kbDay(openDay).then((f) => setDayFacts((m) => ({ ...m, [openDay]: f }))).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openDay])

  const years = useMemo(() => {
    const out: { year: string; months: KbTimelineMonth[] }[] = []
    for (const m of [...(months ?? [])].reverse()) {
      const y = m.month.slice(0, 4)
      const g = out[out.length - 1]
      if (g && g.year === y) g.months.push(m); else out.push({ year: y, months: [m] })
    }
    return out
  }, [months])
  // sqrt 标度：一个月一万条、别的月几十条，线性标度下后者是零（实拍）
  const sq = (n: number) => Math.sqrt(Math.max(0, n))
  const max = Math.max(1, ...(months ?? []).map((m) => sq(m.facts)))

  if (!months) return <p className="muted"><span className="spinner" /> 加载中…</p>
  if (months.length === 0) return <p className="muted">还没有带日期的事实。</p>
  return (
    <div className="kb-page">
      <div className="kb-head">
        <h2 className="kb-note-title"><i className="bx bx-calendar muted" /> 时间线</h2>
        <div className="muted" style={{ fontSize: 13 }}>{months.length} 个月 · 新的在上。点一个月展开到天，点一天看事实。</div>
      </div>
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        {years.map((y) => <a key={y.year} href={'#y' + y.year} className="chip" onClick={(e) => { e.preventDefault(); document.getElementById('y' + y.year)?.scrollIntoView({ block: 'start', behavior: 'smooth' }) }}>{y.year}</a>)}
      </div>
      {years.map((y) => (
        <div key={y.year} id={'y' + y.year} className="tl-year">
          <div className="tl-year-label">{y.year}</div>
          {y.months.map((m) => {
            const open = openMonth === m.month
            const dmax = Math.max(1, ...m.days.map((d) => sq(d.facts)))
            return (
              <div key={m.month} className={'tl-month' + (open ? ' open' : '')}>
                <div className="tl-row" onClick={() => setOpenMonth(open ? null : m.month)}>
                  <span className="tl-label">{m.month.slice(5)} 月</span>
                  <span className="tl-bar"><span style={{ width: `${(sq(m.facts) / max) * 100}%` }} /></span>
                  <span className="tl-num muted">{m.facts} 条 · {m.units} 场</span>
                </div>
                {open && (
                  <div className="tl-days">
                    {m.days.map((d) => (
                      <div key={d.date}>
                        <div className={'tl-row day' + (openDay === d.date ? ' open' : '')} onClick={() => setOpenDay(openDay === d.date ? null : d.date)}>
                          <span className="tl-label">{d.date.length >= 10 ? d.date.slice(8) + ' 日' : '不详'}</span>
                          <span className="tl-bar"><span style={{ width: `${(sq(d.facts) / dmax) * 100}%` }} /></span>
                          <span className="tl-num muted">{d.facts} 条{d.units ? ` · ${d.units} 场` : ''}</span>
                        </div>
                        {openDay === d.date && (
                          <div className="tl-facts">
                            {dayFacts[d.date] ? <FactList facts={dayFacts[d.date]} actions={actions} showTopics /> : <span className="spinner" />}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}
