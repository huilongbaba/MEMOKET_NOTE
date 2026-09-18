/**
 * 页边圆点旁边的关系卡（P9，docs/agent-native-editor.md §3.3 边缘记忆）。
 *
 * 方案 §1 第 2 行说右栏「记忆」是被动的旁观者——真正的记忆应该在你写到「DVT 延期」的那一行
 * 旁边告诉你「上次记的是 6/3，后来改到 8/5」。这张卡就贴在那个圆点旁边：那句人话、那几条
 * 记录（日期 + 原话）、和能直接按的动作（引用这条 / 用新的 / 补进来 / 合成一条 / 忽略）。
 * 动作跟右栏的卡**同一份**（`util/relationActions`）。
 *
 * 三种来法：悬停（离开就收）、点圆点（Esc / 点别处收）、光标进了黄点 / 紫点的段（自己出来一次）。
 * 判据 2：看一条旧记录不该离开这一页——现在连转头都不用。
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { clickable } from '../util/clickable'
import { RELATION_LABEL, markKey, type MarginMark } from '../editor/marginMemory'
import { alreadyCited, citeText, fillInText, ignoreRelation, mergeRelation, supersedeRelation, type RelationLike } from '../util/relationActions'
import Icon from './Icon'
import { CARD_WIDTH, placeCard } from '../util/cardPlacement'

const REL_CLS: Record<MarginMark['relation'], string> = {
  conflict: 'rel-conflict', continuation: 'rel-continuation', corroborated: 'rel-corroborated',
  unsupported: 'rel-unsupported', accumulation: 'rel-accumulation', merge: 'rel-merge',
}
const REL_ICON: Record<MarginMark['relation'], string> = {
  conflict: 'bx-error', continuation: 'bx-trending-up', corroborated: 'bx-check-shield',
  unsupported: 'bx-question-mark', accumulation: 'bx-layer-plus', merge: 'bx-git-merge',
}
/** 关系是什么意思，一句（卡上那句 say 是「这一段」的话，这句是「这种颜色」的话） */
const REL_HINT: Record<MarginMark['relation'], string> = {
  conflict: '知识库里记的跟这段不一样',
  continuation: '这件事在知识库里有一条随时间变的线',
  corroborated: '知识库里有记录跟这段对得上',
  unsupported: '没有一条记录对上这段里的量或日期',
  accumulation: '知识库里关于这件事还有你没写的条件',
  merge: '知识库里两条记录说的是同一件事',
}

const GAP = 10
export { CARD_WIDTH }

export type MarginCardState = { m: MarginMark; anchor: DOMRect; reason: 'hover' | 'click' | 'cursor' }

export default function MarginCard({ card, content, onClose, onInsert, onSeeAll }: {
  card: MarginCardState
  content: string
  onClose: () => void
  onInsert: (text: string) => void
  onSeeAll: () => void
}) {
  const { m, reason } = card
  const rel: RelationLike = { relation: m.relation, fact_ids: m.fact_ids ?? [], facts: m.facts ?? [] }
  const ref = useRef<HTMLDivElement>(null)
  const [anchor, setAnchor] = useState<DOMRect>(card.anchor)
  useEffect(() => { setAnchor(card.anchor) }, [card])
  const [pos, setPos] = useState<{ left: number; top: number; width: number }>({ left: anchor.right + GAP, top: anchor.top - 8, width: CARD_WIDTH })

  // 边界是**正文栏**，不是窗口（P10：P9 那版按窗口判，卡伸出去压在右栏的记忆卡上）：
  // 圆点右边栏内放得下就贴右边，放不下就挂在这一行下面、右缘对齐栏的右缘（`util/cardPlacement`）
  useLayoutEffect(() => {
    const h = ref.current?.offsetHeight ?? 160
    const pane = (ref.current?.closest('.note-pane') ?? document.querySelector('.note-pane')) as HTMLElement | null
    const b = pane?.getBoundingClientRect()
    const bounds = b && b.width > 0 ? b : { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight, width: window.innerWidth, height: window.innerHeight }
    const p = placeCard(anchor, bounds, h, window.innerHeight)
    setPos({ left: p.left, top: p.top, width: p.width })
  }, [anchor, m])

  // 正文滚了：圆点挪了就跟着挪，滚出视口就收
  useEffect(() => {
    const onScroll = () => {
      const el = document.querySelector(`.cm-memory-gutter .mm-dot[data-line="${m.line}"]`)
      if (!el) { onClose(); return }
      setAnchor(el.getBoundingClientRect())
    }
    document.addEventListener('scroll', onScroll, true)
    return () => document.removeEventListener('scroll', onScroll, true)
  }, [m.line, onClose])

  // Esc 收；点卡外面收；悬停来的：鼠标既不在圆点也不在卡上就收
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    const onDown = (e: MouseEvent) => {
      const t = e.target as HTMLElement
      if (ref.current?.contains(t) || t.closest?.('.mm-dot')) return
      onClose()
    }
    const onMove = (e: MouseEvent) => {
      if (reason !== 'hover') return
      const inCard = ref.current?.contains(e.target as Node)
      const a = anchor
      const nearDot = e.clientX >= a.left - 8 && e.clientX <= a.right + GAP + 4 && e.clientY >= a.top - 8 && e.clientY <= a.bottom + 8
      if (!inCard && !nearDot) onClose()
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('mousemove', onMove)
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', onDown); document.removeEventListener('mousemove', onMove) }
  }, [reason, anchor, onClose])

  const key = markKey(m)
  const ignore = () => { ignoreRelation(key); onClose() }
  const facts = rel.facts
  const cited = alreadyCited(rel, content)

  return (
    <div ref={ref} className={'margin-card rel-card ' + REL_CLS[m.relation]} role="dialog" aria-label={`这一段跟知识库的关系：${RELATION_LABEL[m.relation]}`}
         style={{ left: pos.left, top: pos.top, width: pos.width }}>
      <div className="row margin-card-head">
        <span className={'badge ' + REL_CLS[m.relation]} title={REL_HINT[m.relation]}><Icon n={REL_ICON[m.relation]} /> {RELATION_LABEL[m.relation]}</span>
        <span className="muted margin-card-where">这一段（第 {m.line} 行起）{(m.kinds ?? 1) > 1 ? ` · 还判出 ${(m.kinds ?? 1) - 1} 种` : ''}</span>
        <button className="icon-btn margin-card-close" title="收起（Esc）" onClick={onClose}><Icon n="bx-x" /></button>
      </div>
      <div className="margin-card-say">{m.say}</div>
      {facts.length > 0 && (
        <div className="stack margin-card-facts">
          {facts.map((f) => (
            <div key={f.id} className="margin-card-fact" title="打开这条记录"
                 {...clickable(() => window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb:fact:' + f.id })))}>
              <span className="badge">{f.when || '—'}</span><span>{f.text}</span>
            </div>
          ))}
        </div>
      )}
      <div className="row margin-card-actions">
        {facts.length > 0 && (cited
          ? <span className="badge ok" title="正文里已经引用了这条">已引用</span>
          : <button onClick={() => { onInsert(citeText(rel)); onClose() }} title="把最新那条带出处插到光标处">引用这条</button>)}
        {m.relation === 'conflict' && <button onClick={() => void supersedeRelation(rel).then((ok) => ok && onClose())} title="库里早的那条标成被晚的取代">新的取代旧的</button>}
        {m.relation === 'accumulation' && facts.length > 0 && <button onClick={() => { onInsert(fillInText(rel)); ignoreRelation(key); onClose() }} title="把知识库里那几个条件带引用插进正文">补进来</button>}
        {m.relation === 'merge' && facts.length === 2 && <button onClick={() => void mergeRelation(rel).then((ok) => ok && onClose())} title="留晚的那条，早的标成被它取代">合成一条</button>}
        <button onClick={ignore} title="这一对不再提（记在本机）">忽略</button>
        <button className="linklike margin-card-more" onClick={onSeeAll} title="右栏「记忆」里看这段全部的关系和召回">右栏看全部</button>
      </div>
    </div>
  )
}
