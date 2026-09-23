/**
 * 知识库页面的公共小件。图按 dataviz 的规矩：单色序列（accent 一种色）表示
 * 数量、细 mark、圆角端、hover 有值、文字用文字色。
 */
import { isSpeakerTag } from '../../util/kbNoise'
import { entityIcon } from '../../util/entityIcon'
import { clickable } from '../../util/clickable'
import { useState, type ReactNode } from 'react'

import type { FactDetail, KbMonth } from '../../api'
import Icon from '../Icon'

/** 虚拟节点指向的东西已经没了（旧标签、改名过的实体、重建过的知识库）：说清是什么、
 *  给条回去的路。之前三个页各写一行灰字，没有出口（实拍）。 */
export function MissingPage({ what, id, actions, back = 'kb', backLabel = '回知识库总览' }: {
  what: string; id: string; actions: KbActions; back?: string; backLabel?: string
}) {
  return (
    <div className="stack" style={{ gap: 8 }}>
      <h3 style={{ margin: 0 }}>没有这个{what}</h3>
      <p className="muted" style={{ margin: 0 }}><code>{id}</code> 在知识库里不存在——可能是旧标签、改过名，或者知识库重建过。</p>
      <div><button onClick={() => actions.onOpen(back)}><Icon n="bx-left-arrow-alt" /> {backLabel}</button></div>
    </div>
  )
}

export type KbActions = {
  onOpen: (id: string) => void                 // 虚拟节点 kb:…
  onOpenNote: (noteId: string) => void
  /** 把 `原文 [id]` 送进正在写的笔记；没有正在写的就是 null（页面上退化成「复制引用」） */
  onCite: ((f: { id: string; text: string }) => void) | null
}

export function StatTile({ value, label, hint, onClick }: {
  value: ReactNode; label: string; hint?: string; onClick?: () => void
}) {
  const body = <>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {onClick && <Icon n="bx-right-arrow-alt" className="stat-open" />}
    </>
  return onClick
    ? <button type="button" className="stat-tile interactive" title={hint} onClick={onClick}>{body}</button>
    : <div className="stat-tile" title={hint}>{body}</div>
}

/** 单色条形图：月份 × 数量。hover 显示值；首尾标月份。
 *  用 div 不用 svg：svg 拉伸到容器宽时三根柱子会变成三块大砖；div 给每根柱子
 *  一个上限宽（28px），少的时候就是几根细柱靠左站着。 */
export function MiniBars({ data, height = 64, label = '条事实' }: { data: KbMonth[]; height?: number; label?: string }) {
  if (data.length === 0) return <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: 0 }}>还没有按月的数据。</p>
  const max = Math.max(1, ...data.map((d) => d.facts))
  return (
    <div className="mini-bars" style={{ maxWidth: Math.max(data.length * 31, 132) }}>{/* 只有一两个月时也要放得下两个「2026-03」标签，不然标签折成两行 */}
      <div className="mini-bars-row" style={{ height }}>
        {data.map((d) => (
          <div key={d.month} className="mini-bar" title={`${d.month} · ${d.facts} ${label}`}
               style={{ height: d.facts ? `${Math.max(3, (d.facts / max) * 100)}%` : 0, opacity: d.facts ? undefined : 0 }} />
        ))}
      </div>
      <div className="mini-bars-axis muted">
        <span>{data[0].month}</span>
        {data.length > 1 && <span>{data[data.length - 1].month}</span>}
      </div>
    </div>
  )
}

export function Chip({ icon, children, count, onClick, title }: {
  icon?: string; children: ReactNode; count?: number; onClick?: () => void; title?: string
}) {
  return (
    <button className="chip" onClick={onClick} title={title} disabled={!onClick}>
      {icon && <Icon n={icon} />}
      <span>{children}</span>
      {count !== undefined && <span className="chip-count">{count}</span>}
    </button>
  )
}

/** 分组标题现在是**大标题**（第 689 轮），所以「标题里塞一句注解」就不行了：
 *  「近 12 个月（按事实里的日期，计划里的未来日期也算）」整句 20px 粗体，
 *  读起来像文章标题。`note` 单独一行灰字——**标题说是什么，注解说怎么算**。 */
export function KbSection({ title, note, extra, children }: { title: string; note?: string; extra?: ReactNode; children: ReactNode }) {
  return (
    <section className="kb-section">
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
        <h3 className="kb-section-title">{title}</h3>
        {extra}
      </div>
      {note && <p className="muted" style={{ margin: '-6px 0 0', fontSize: 'var(--t-sm)' }}>{note}</p>}
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
      <div className={'fact-text' + (f.superseded_by ? ' superseded' : '')} {...clickable(() => actions.onOpen('kb:fact:' + f.id))}>{f.text}</div>
      {f.superseded_by && (
        <div className="fact-tags">
          <Chip icon={f.merged ? 'bx-git-merge' : 'bx-right-arrow-alt'} onClick={() => actions.onOpen('kb:fact:' + f.superseded_by)} title={f.merged ? '这条已经合并进另一条，点开合并后的那条' : '这条已经过时，点开取代它的那条'}>{f.merged ? '已合并' : '已被取代'}</Chip>
        </div>
      )}
      {f.note_id && (
        // 从笔记摄入的：反链回那篇（知识库 → 笔记这一向之前是断的）
        <div className="fact-tags">
          <Chip icon="bx-note" onClick={() => actions.onOpenNote(f.note_id!)} title="打开摄入它的那篇笔记">{f.manual ? '手工加在笔记里' : '来自笔记'}</Chip>
        </div>
      )}
      {showTopics && (f.topics.length > 0 || f.entities.length > 0) && (
        <div className="fact-tags">
          {f.topics.map((t) => <Chip key={t} icon="bx-hash" onClick={() => actions.onOpen('kb:topic:' + t)}>{t}</Chip>)}
          {/* 说话人标签（speaker_c）不是实体，每张卡都挂一个只是噪声（第 211 轮实拍会议页） */}
          {f.entities.map((e, i) => [e, f.entity_names?.[i] ?? e] as const).filter(([, n]) => !isSpeakerTag(n)).map(([e, n]) => <Chip key={e} icon={entityIcon(n)} onClick={() => actions.onOpen('kb:entity:' + e)}>{n}</Chip>)}
        </div>
      )}
      <div className="fact-actions">
        <button className="icon-btn" title="打开这条事实" onClick={() => actions.onOpen('kb:fact:' + f.id)}><Icon n="bx-link-external" /></button>
        <button className="icon-btn" title={actions.onCite ? '引用到正在写的笔记' : '复制引用（原文 [id]）'} onClick={cite}>
          <Icon n={(copied ? 'bx-check' : actions.onCite ? 'bx-link' : 'bx-copy')} />
        </button>
      </div>
    </div>
  )
}

export function FactList({ facts, actions, showTopics }: { facts: FactDetail[]; actions: KbActions; showTopics?: boolean }) {
  if (facts.length === 0) return <p className="muted" style={{ fontSize: 'var(--t-md)', margin: 0 }}>没有事实。</p>
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

/** 空库时那句「看看事实表长什么样」要兑现的东西。
 *
 *  原来那儿是一个按钮，点进去是事实表页——五个空下拉 + 「0 条 · 没有事实。」。
 *  **按钮承诺给你看长什么样，给出来的是空的**（第 673 轮拿全新用户走一遍实拍到的）。
 *  承诺要么兑现要么撤掉；这里兑现：拿真正的 `FactRow` 渲染两条示例，跟导入之后
 *  长得一模一样——只是整块 `inert`，点不动也 tab 不进去（假数据点开只会是 404）。
 *  `inert` 顺带把它从无障碍树里摘掉了：这是**有意的**——屏幕阅读器读上面那句
 *  说明就够了，逐条读两条假事实反而分不清哪些是自己的数据。
 *
 *  两条示例特意各带一样东西：第一条有说话人和类型（会议录音抽出来的样子），
 *  第二条带「来自笔记」的反链（自己写的笔记存进来的样子）。 */
const EXAMPLE_FACTS: FactDetail[] = [
  { id: 'demo-1', text: '样机的续航实测 11 小时，比上一版多 2 小时。', when: '2026-03-04',
    kind: '结论', who: '李工', conf: 'high', topics: ['硬件'], entities: [], unit: 'demo' },
  { id: 'demo-2', text: '这一版的定价定在 199 美元，先在北美上。', when: '2026-03-11',
    kind: '决定', who: '', conf: 'high', topics: ['定价'], entities: [], unit: 'demo',
    note_id: 'demo-note' },
]

const NO_ACTIONS: KbActions = { onOpen: () => {}, onOpenNote: () => {}, onCite: null }

export function ExampleFacts() {
  return (
    <div className="kb-example">
      <div className="muted" style={{ fontSize: 'var(--t-sm)', marginBottom: 4 }}>
        示例 —— 导入之后每一句话会变成这样一条：带日期、说话人、类型，点得开，也能一键引到正文里。
      </div>
      <div className="fact-list" inert>
        <div className="fact-month muted">2026-03</div>
        {EXAMPLE_FACTS.map((f) => <FactRow key={f.id} f={f} actions={NO_ACTIONS} showTopics />)}
      </div>
    </div>
  )
}

export function Pager({ total, limit, offset, onPage, tail }: { total: number; limit: number; offset: number; onPage: (o: number) => void; tail?: ReactNode }) {
  if (total <= limit) return null
  const page = Math.floor(offset / limit) + 1, pages = Math.ceil(total / limit)
  return (
    <div className="row" style={{ gap: 6, alignItems: 'center', marginTop: 8 }}>
      <button className="icon-btn" title="上一页" aria-label="上一页" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - limit))}><Icon n="bx-chevron-left" /></button>
      <span className="muted" style={{ fontSize: 'var(--t-sm)' }}>{page} / {pages} · 共 {total} 条</span>
      <button className="icon-btn" title="下一页" aria-label="下一页" disabled={offset + limit >= total} onClick={() => onPage(offset + limit)}><Icon n="bx-chevron-right" /></button>
      {/* 一页页翻 121 页没人翻得动：翻页器旁边给一条「去事实表筛」的出口（主题 / 实体页传进来） */}
      {tail && <span className="muted" style={{ fontSize: 'var(--t-sm)' }}>· {tail}</span>}
    </div>
  )
}
