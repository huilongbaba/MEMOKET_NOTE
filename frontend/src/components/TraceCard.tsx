/**
 * ⌥ 悬停的来龙去脉卡（P16，docs/agent-native-editor.md §3.3 / 场景 B）：贴在词边，不在右栏等你。
 *
 * 方案原话：写到「众筹定价 199」不确定当初怎么定的，把光标放上去按 ⌥（或悬停半秒），旁边弹出来龙去脉卡。
 * 这张卡**零模型**——`/api/memory/recall` 词法召回，几十毫秒：这个词在知识库里第一次出现、最近一次、相关的两条。
 * 「查完整来龙去脉」（模型、20–30 秒、结果在右栏「脉络」）留给卡上的按钮，你要才打。
 * 判据 2：看一条旧记录不该离开这一页；痛点 11 / 12。
 *
 * 词是谁定的：编辑器按分词器切；分词器不认识的（「众筹」→ 众 | 筹）交过来的是相邻单字连成的一串（「众筹等」）+ 鼠标停的
 * 那个字的偏移，这里先查一次拿知识库真正用上的整词（`recall.terms`），挑盖住那个字的当这个词，再按它查一次——两次都是词法、零模型。
 *
 * 来法：⌥ 悬停（鼠标离开词和卡就收）、⌥↩（键盘；卡拿焦点，Esc 收、焦点回编辑器）。位置走 P9 / P10 的 `cardPlacement`：
 * 正文栏内放得下贴词右边，放不下挂在这一行下面、绝不伸出正文栏。
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import * as api from '../api'
import type { Fact } from '../api'
import { clickable } from '../util/clickable'
import { CARD_WIDTH, placeCard, pushLineBelow, seamPush } from '../util/cardPlacement'
import { candidates, emptyReason, summarizeTrace, type TraceSummary } from '../util/traceCard'
import type { AltHoverRange } from '../editor/altHover'
import Icon from './Icon'

const GAP = 10

export type TraceCardState = { phrase: string; anchor: DOMRect; reason: 'hover' | 'key'; range: AltHoverRange }
type Loaded = { phrase: string; summary: TraceSummary; why?: '' | 'no_terms' | 'weak'; kbEmpty?: boolean }

// 同一个词悬停两次不用再查（词法召回本来就快，但卡一收一开之间闪一下「查知识库…」很难看）
const cache = new Map<string, Loaded>()

/** 查知识库。单字连成的串（分词器不认识的词）：盖住鼠标那个字的两字窗口各查一次，谁有记录用谁，都没有再查整串（`util/traceCard.candidates`）。 */
export async function lookup(phrase: string, focus: number | undefined): Promise<Loaded> {
  const key = focus == null ? phrase : `${phrase}#${focus}`
  const hit = cache.get(key)
  if (hit) return hit
  let shown = phrase
  let r: Awaited<ReturnType<typeof api.recall>>
  if (focus == null) {
    r = await api.recall(phrase, 8)
  } else {
    const cands = candidates(phrase, focus)               // 两字窗口在前，整串在最后（三次都是词法，并行）
    const got = await Promise.all(cands.map((c) => api.recall(c, 8)))
    const windows = cands.length > 1 ? cands.length - 1 : 1
    let best = 0
    for (let i = 1; i < windows; i++) if (got[i].facts.length > got[best].facts.length) best = i
    // 两字窗口都没有才轮到整串；整串也没有就说最左的那个两字窗口（不是整串——用户停的是一个词）
    if (got[best].facts.length === 0 && windows < cands.length && got[cands.length - 1].facts.length > 0) best = cands.length - 1
    shown = cands[best]; r = got[best]
  }
  const loaded: Loaded = { phrase: shown, summary: summarizeTrace(r.facts), why: r.why_empty, kbEmpty: r.kb_empty }
  cache.set(key, loaded)
  return loaded
}

export default function TraceCard({ card, content, onClose, onInsert, onTrace }: {
  card: TraceCardState
  content: string
  onClose: () => void
  onInsert: (text: string) => void
  /** 走那条 20 秒的完整来龙去脉（模型），结果在右栏「脉络」 */
  onTrace: (phrase: string) => void
}) {
  const { phrase, anchor, reason, range } = card
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ left: number; top: number; width: number }>({ left: anchor.right + GAP, top: anchor.top - 8, width: CARD_WIDTH })
  const [data, setData] = useState<Loaded | null>(null)
  const [failed, setFailed] = useState('')

  useEffect(() => {
    setData(null); setFailed('')
    let alive = true
    lookup(phrase, range.focus).then((d) => { if (alive) setData(d) })
      .catch((e) => { if (alive) setFailed(String(e?.message ?? e)) })
    return () => { alive = false }
  }, [phrase, range.focus])

  useLayoutEffect(() => {
    const h = ref.current?.offsetHeight ?? 140
    const pane = (ref.current?.closest('.note-pane') ?? document.querySelector('.note-pane')) as HTMLElement | null
    const b = pane?.getBoundingClientRect()
    const bounds = b && b.width > 0 ? b : { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight, width: window.innerWidth, height: window.innerHeight }
    const p = placeCard(anchor, bounds, h, window.innerHeight)
    setPos({ left: p.left, top: p.top, width: p.width })
    // 挂在词下面时把下一行推开，别盖住正文（P19 #3）
    return pushLineBelow(anchor, seamPush(p.side, h))
  }, [anchor, data, failed])

  // 键盘来的：卡拿焦点（Tab 走得到按钮）；收起时焦点回编辑器
  useEffect(() => {
    if (reason !== 'key') return
    ref.current?.focus()
    return () => { (document.querySelector('.note-scroll .cm-content') as HTMLElement | null)?.focus() }
  }, [reason, phrase])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose() }
    const onMove = (e: MouseEvent) => {
      if (reason !== 'hover') return
      const inCard = ref.current?.contains(e.target as Node)
      const a = anchor
      const nearWord = e.clientX >= a.left - 12 && e.clientX <= a.right + GAP + 4 && e.clientY >= a.top - 10 && e.clientY <= a.bottom + 10
      if (!inCard && !nearWord) onClose()
    }
    const onScroll = () => onClose()
    document.addEventListener('keydown', onKey, true)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('mousemove', onMove)
    document.addEventListener('scroll', onScroll, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('scroll', onScroll, true)
    }
  }, [reason, anchor, onClose])

  const s = data?.summary
  const shown = data?.phrase ?? phrase
  const cited = (f: Fact) => content.includes(`[${f.id}]`)
  const row = (label: string, f: Fact) => (
    <div key={label + f.id} className="margin-card-fact trace-row" title="打开这条记录"
         {...clickable(() => window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb:fact:' + f.id })))}>
      <span className="trace-when"><span className="badge">{label}</span> {f.when || '—'}</span>
      <span>{f.text}</span>
    </div>
  )
  const latest = s?.last ?? s?.first ?? s?.related[0] ?? null

  return (
    <div ref={ref} className="margin-card trace-card" role="dialog" tabIndex={-1} aria-label={`「${shown}」的来龙去脉`}
         style={{ left: pos.left, top: pos.top, width: pos.width }}>
      <div className="row margin-card-head">
        <span className="badge"><Icon n="bx-history" /> 来龙去脉</span>
        <span className="margin-card-where trace-phrase">「{shown}」{s ? ` · 知识库里 ${s.count} 条` : ''}</span>
        <button className="icon-btn margin-card-close" title="收起（Esc）" onClick={onClose}><Icon n="bx-x" /></button>
      </div>
      {failed
        ? <div className="margin-card-say">查不了：{failed}</div>
        : !s
          ? <div className="margin-card-say muted">查知识库…</div>
          : s.count === 0
            ? <div className="margin-card-say">{emptyReason(shown, data?.why, data?.kbEmpty)}</div>
            : (
              <div className="stack margin-card-facts">
                {s.first && row('第一次', s.first)}
                {s.last && row('最近', s.last)}
                {s.related.map((f) => row('相关', f))}
              </div>
            )}
      <div className="row margin-card-actions">
        {latest && (cited(latest)
          ? <span className="badge ok" title="正文里已经引用了这条">已引用</span>
          : <button onClick={() => { onInsert(` [${latest.id}]`); onClose() }} title="把最近这条的出处插到光标处">引用最近这条</button>)}
        {s && s.count > 0 && <button onClick={() => { onTrace(shown); onClose() }} title="让模型按时间把这件事的演进整理出来（20 秒左右），结果在右栏「脉络」">查完整来龙去脉</button>}
        <span className="muted margin-card-more">{reason === 'key' ? 'Esc 收起' : '移开就收'}</span>
      </div>
    </div>
  )
}
