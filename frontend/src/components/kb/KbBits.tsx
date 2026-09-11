/**
 * 知识库页面的公共小件。图按 dataviz 的规矩：单色序列（accent 一种色）表示
 * 数量、细 mark、圆角端、hover 有值、文字用文字色。
 */
import { useState, type ReactNode } from 'react'

import type { FactDetail, KbMonth } from '../../api'

export type KbActions = {
  onOpen: (id: string) => void                 // 虚拟节点 kb:…
  onOpenNote: (noteId: string) => void
  /** 把 `原文 [id]` 送进正在写的笔记；没有正在写的就是 null（页面上退化成「复制引用」） */
  onCite: ((f: { id: string; text: string }) => void) | null
}

export function StatTile({ value, label, hint }: { value: ReactNode; label: string; hint?: string }) {
  return (
    <div className="stat-tile" title={hint}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  )
}

/** 单色条形图：月份 × 数量。hover 显示值；首尾标月份。
 *  用 div 不用 svg：svg 拉伸到容器宽时三根柱子会变成三块大砖；div 给每根柱子
 *  一个上限宽（28px），少的时候就是几根细柱靠左站着。 */
export function MiniBars({ data, height = 64, label = '条事实' }: { data: KbMonth[]; height?: number; label?: string }) {
  if (data.length === 0) return <p className="muted" style={{ fontSize: 12, margin: 0 }}>还没有按月的数据。</p>
  const max = Math.max(1, ...data.map((d) => d.facts))
  return (
    <div className="mini-bars" style={{ maxWidth: data.length * 31 }}>
      <div className="mini-bars-row" style={{ height }}>
        {data.map((d) => (
          <div key={d.month} className="mini-bar" title={`${d.month} · ${d.facts} ${label}`}
               style={{ height: `${Math.max(3, (d.facts / max) * 100)}%` }} />
        ))}
      </div>
      <div className="mini-bars-axis muted">
        <span>{data[0].month}</span>
        <span>{data[data.length - 1].month}</span>
      </div>
    </div>
  )
}

export function Chip({ icon, children, count, onClick, title }: {
  icon?: string; children: ReactNode; count?: number; onClick?: () => void; title?: string
}) {
  return (
    <button className="chip" onClick={onClick} title={title} disabled={!onClick}>
      {icon && <i className={'bx ' + icon} />}
      <span>{children}</span>
      {count !== undefined && <span className="chip-count">{count}</span>}
    </button>
  )
}

export function KbSection({ title, extra, children }: { title: string; extra?: ReactNode; children: ReactNode }) {
  return (
    <section className="kb-section">
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
        <h3 className="kb-section-title">{title}</h3>
        {extra}
      </div>
      {children}
    </section>
  )
}

/** 一条事实：日期 · 说话人 · 类型 · 正文 · 打开 / 引用。 */
export function FactRow({ f, actions, showTopics = false }: { f: FactDetail; actions: KbActions; showTopics?: boolean }) {
  const [copied, setCopied] = useState(false)
  const cite = () => {
    if (actions.onCite) { actions.onCite(f); return }
    void navigator.clipboard.writeText(`${f.text} [${f.id}]`).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200) })
  }
  return (
    <div className="fact-row">
      <div className="fact-meta muted">
        <span>{f.when || '—'}</span>
        {f.who && <span>· {f.who}</span>}
        {f.kind && <span className="fact-kind">{f.kind}</span>}
      </div>
      <div className="fact-text" onClick={() => actions.onOpen('kb:fact:' + f.id)}>{f.text}</div>
      {showTopics && (f.topics.length > 0 || f.entities.length > 0) && (
        <div className="fact-tags">
          {f.topics.map((t) => <Chip key={t} icon="bx-hash" onClick={() => actions.onOpen('kb:topic:' + t)}>{t}</Chip>)}
          {f.entities.map((e) => <Chip key={e} icon="bx-user" onClick={() => actions.onOpen('kb:entity:' + e)}>{e}</Chip>)}
        </div>
      )}
      <div className="fact-actions">
        <button className="icon-btn" title="打开这条事实" onClick={() => actions.onOpen('kb:fact:' + f.id)}><i className="bx bx-link-external" /></button>
        <button className="icon-btn" title={actions.onCite ? '引用到正在写的笔记' : '复制引用（原文 [id]）'} onClick={cite}>
          <i className={'bx ' + (copied ? 'bx-check' : actions.onCite ? 'bx-link' : 'bx-copy')} />
        </button>
      </div>
    </div>
  )
}

export function FactList({ facts, actions, showTopics }: { facts: FactDetail[]; actions: KbActions; showTopics?: boolean }) {
  if (facts.length === 0) return <p className="muted" style={{ fontSize: 13, margin: 0 }}>没有事实。</p>
  // 按月分组：一眼看出「哪个月在说这件事」
  const groups: { month: string; items: FactDetail[] }[] = []
  for (const f of facts) {
    const m = (f.when || '未知').slice(0, 7)
    const g = groups[groups.length - 1]
    if (g && g.month === m) g.items.push(f); else groups.push({ month: m, items: [f] })
  }
  return (
    <div className="fact-list">
      {groups.map((g) => (
        <div key={g.month}>
          <div className="fact-month muted">{g.month}</div>
          {g.items.map((f) => <FactRow key={f.id} f={f} actions={actions} showTopics={showTopics} />)}
        </div>
      ))}
    </div>
  )
}

export function Pager({ total, limit, offset, onPage }: { total: number; limit: number; offset: number; onPage: (o: number) => void }) {
  if (total <= limit) return null
  const page = Math.floor(offset / limit) + 1, pages = Math.ceil(total / limit)
  return (
    <div className="row" style={{ gap: 6, alignItems: 'center', marginTop: 8 }}>
      <button className="icon-btn" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - limit))}><i className="bx bx-chevron-left" /></button>
      <span className="muted" style={{ fontSize: 12 }}>{page} / {pages} · 共 {total} 条</span>
      <button className="icon-btn" disabled={offset + limit >= total} onClick={() => onPage(offset + limit)}><i className="bx bx-chevron-right" /></button>
    </div>
  )
}
