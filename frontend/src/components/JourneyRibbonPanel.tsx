import { useEffect, useState } from 'react'

import { journeyDay, type JourneyDay } from '../api'
import { openJourneyDay } from '../util/journeyOpen'
import Icon from './Icon'
import { saySpan } from './JourneyPage'

/**
 * 日记那篇笔记上的「这一天的屏幕活动」（`docs/daily-journey-plan.md` §8.4）。
 *
 * **摘要 + 一条进去的链接，仅此而已。** 计划那句话的后半截是重点：
 * 「两边互相找得到，但**不把机器写的内容直接塞进用户的笔记正文**」——
 * 正文是用户写的东西（§1「树是我写的、我摆的」）。机器写的那份住在屏幕活动
 * 那一页，这里只放一个够得着它的把手。想把日报变成笔记有专门的
 * 「存为笔记」，那一下是**用户按的**。
 *
 * 为什么是 ribbon 不是右栏：ribbon 放的是**这篇笔记的元数据**，而
 * 「这一天我在屏幕上干了什么」正是这篇日记的元数据。
 */
export default function JourneyRibbonPanel({ date }: { date: string }) {
  const [day, setDay] = useState<JourneyDay | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let stale = false
    setDay(null); setFailed(false)
    journeyDay(date).then((d) => { if (!stale) setDay(d) }).catch(() => { if (!stale) setFailed(true) })
    return () => { stale = true }
  }, [date])

  const segs = day?.segments ?? []
  const byApp = new Map<string, number>()
  for (const s of segs) {
    const sec = Math.max(0, (Date.parse(s.end) - Date.parse(s.start)) / 1000)
    byApp.set(s.app, (byApp.get(s.app) ?? 0) + sec)
  }
  const top = [...byApp.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4)
  /** 日报的头一段：它是这一天的结论。**只摘一段**——ribbon 是元数据区，
   *  整份日报摊在这儿会把正文顶下去。 */
  const lead = (day?.report ?? '').split('\n').map((l) => l.trim())
    .find((l) => l && !l.startsWith('#') && !l.startsWith('|') && !l.startsWith('-') && !l.startsWith('·'))

  return (
    <div className="journey-ribbon">
      {failed ? (
        <p className="muted"><Icon n="bx-error" /> 读不到这一天的屏幕活动（后端没应答）。</p>
      ) : !day ? (
        <p className="muted">…</p>
      ) : segs.length === 0 ? (
        <p className="muted">这一天没有屏幕活动记录——那天没开着，或者还没记到一段。</p>
      ) : (
        <>
          <p className="journey-ribbon-sum">
            <b>{segs.length} 段</b>，合计 {saySpan(segs.reduce((n, s) => n + Math.max(0, (Date.parse(s.end) - Date.parse(s.start)) / 1000), 0))}
            {top.length > 0 && <>　{top.map(([a, sec]) => `${a} ${saySpan(sec)}`).join('　')}</>}
          </p>
          {lead && <p className="journey-ribbon-lead">{lead.slice(0, 140)}{lead.length > 140 ? '…' : ''}</p>}
        </>
      )}
      {/* **一条进去的链接**：这一页只给摘要，明细 / 删除 / 写日报都在那一页 */}
      <button className="chip chip-action" onClick={() => openJourneyDay(date)}>
        <Icon n="bx-desktop" /> 打开这一天的屏幕活动
      </button>
    </div>
  )
}
