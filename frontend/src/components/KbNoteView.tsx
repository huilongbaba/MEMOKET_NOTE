/**
 * 知识库虚拟子树上的节点，打开就是这个——**一条事实 = 一篇只读笔记**
 * （docs/kb-fusion-design.md §3.3），分类节点 = 一篇列出名下事实的只读笔记。
 *
 * 为什么不是右栏的一个面板：右栏是「跟着当前笔记走」的东西，而用户点开
 * 一条事实时想看的是**它本身**——原话、谁引用了它、它的邻居。这些占一整
 * 屏才看得清，也才能用标签页把它留着、跟笔记并排。
 */
import { useEffect, useState } from 'react'

import DigestPanel from './DigestPanel'
import MemoryBrowser from './MemoryBrowser'

import {
  factPeek, factSources, kbTreeChildren, notesCiting, recall,
  isFactId, type CitingNote, type Fact, type FactPeek, type SourceLine, type TreeRow,
} from '../api'

type Props = {
  id: string
  /** 整棵树（真笔记 + 虚拟节点），拿来找标题和子分类。 */
  rows: TreeRow[]
  onOpen: (id: string) => void
  onOpenNote: (noteId: string) => void
  /** 把 `[fact-id]` 这条引用送进当前正在写的笔记；没有正在写的就是 null。 */
  onCite: ((factId: string) => void) | null
}

export default function KbNoteView(props: Props) {
  if (isFactId(props.id)) return <FactNote {...props} />
  // 可视化与配套工具，也是树上的节点：打开一张图跟打开一篇笔记是同一个动作
  if (props.id === 'kb:overview') return <ToolNote title="总览" icon="▤"><MemoryBrowser embedded initialTab="overview" /></ToolNote>
  if (props.id === 'kb:graph') return <ToolNote title="主题地图" icon="◉"><MemoryBrowser embedded initialTab="topics" /></ToolNote>
  if (props.id === 'kb:digest') return <ToolNote title="定期回顾" icon="↻"><DigestPanel /></ToolNote>
  return <CollectionNote {...props} />
}

function ToolNote({ title, icon, children }: { title: string; icon: string; children: React.ReactNode }) {
  return (
    <div className="kb-note" style={{ maxWidth: 'none' }}>
      <div className="muted kb-note-meta"><span>{icon} 知识库</span></div>
      <h2 className="kb-note-title">{title}</h2>
      {children}
    </div>
  )
}

// ----------------------------------------------------------------- 一条事实

function FactNote({ id, onOpen, onOpenNote, onCite }: Props) {
  const factId = id.slice('kb:fact:'.length)
  const [fact, setFact] = useState<FactPeek | null | undefined>(undefined)
  const [sources, setSources] = useState<SourceLine[]>([])
  const [citing, setCiting] = useState<CitingNote[]>([])
  const [related, setRelated] = useState<Fact[]>([])
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let alive = true
    setFact(undefined); setSources([]); setCiting([]); setRelated([])
    void factPeek(factId).then((f) => {
      if (!alive) return
      setFact(f)
      if (!f) return
      // 邻居：拿这条的原文去召回，去掉自己。同一次会议/同一主题的事实
      // 天然靠前——这是「相关事实」最便宜也最准的实现。
      void recall(f.text, 7).then((r) => {
        if (alive) setRelated(r.facts.filter((x) => x.id !== factId).slice(0, 6))
      }).catch(() => {})
    })
    void factSources(factId).then((s) => { if (alive) setSources(s) }).catch(() => {})
    void notesCiting(factId).then((n) => { if (alive) setCiting(n) }).catch(() => {})
    return () => { alive = false }
  }, [factId])

  function copyCite() {
    void navigator.clipboard.writeText(`[${factId}]`).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 1200)
    })
  }

  if (fact === undefined) return <p className="muted">…</p>
  if (fact === null) {
    return (
      <div className="kb-note">
        <h2 className="kb-note-title" style={{ color: 'var(--del)' }}>找不到这条事实</h2>
        <p className="muted">{factId} 在知识库里不存在——可能是引用写错了，或者知识库重建过。</p>
      </div>
    )
  }

  return (
    <div className="kb-note">
      <div className="muted kb-note-meta">
        <span>◆ {fact.when || '未知时间'}</span>
        {fact.kind && <span>· {fact.kind}</span>}
        <code className="kb-note-id">[{factId}]</code>
        <span style={{ marginInlineStart: 'auto' }} className="row">
          {onCite && <button onClick={() => onCite(factId)} title="把引用插到正在写的笔记里">↩ 引用到笔记</button>}
          <button onClick={copyCite}>{copied ? '已复制' : '复制引用'}</button>
        </span>
      </div>
      <h2 className="kb-note-title">{fact.text}</h2>

      <Section title="原话" empty="这条没有保留原话">
        {sources.map((s) => <Quote key={s.id} line={s} />)}
      </Section>

      {/* 融合的关键：这条依据活在哪几篇笔记里。改了它、删了它，会影响谁。 */}
      <Section title="被这些笔记引用" empty="还没有笔记引用这条。写作时它会在「相关记忆」里出现，一点插入。">
        {citing.map((n) => (
          <a key={n.id} href="#" className="kb-link"
             onClick={(e) => { e.preventDefault(); onOpenNote(n.id) }}>
            {n.title || '未命名'}
            <span className="muted" style={{ marginInlineStart: 8 }}>{n.updated_at.slice(0, 10)}</span>
          </a>
        ))}
      </Section>

      <Section title="相关事实" empty="">
        {related.map((f) => (
          <a key={f.id} href="#" className="kb-link"
             onClick={(e) => { e.preventDefault(); onOpen('kb:fact:' + f.id) }}>
            <span className="muted" style={{ marginInlineEnd: 8 }}>{f.when}</span>{f.text}
          </a>
        ))}
      </Section>
    </div>
  )
}

// ----------------------------------------------------------------- 一个分类

function CollectionNote({ id, rows, onOpen }: Props) {
  const me = rows.find((r) => r.note_id === id)
  const subs = rows.filter((r) => r.parent_note_id === id && !isFactId(r.note_id))
  const [facts, setFacts] = useState<TreeRow[] | undefined>(undefined)

  useEffect(() => {
    let alive = true
    setFacts(undefined)
    void kbTreeChildren(id).then((f) => { if (alive) setFacts(f) }).catch(() => { if (alive) setFacts([]) })
    return () => { alive = false }
  }, [id])

  return (
    <div className="kb-note">
      <div className="muted kb-note-meta">
        <span>▤ 知识库</span>
        {me && me.fact_count > 0 && <span>· {me.fact_count} 条事实</span>}
      </div>
      <h2 className="kb-note-title">{me?.title ?? id}</h2>
      {me?.preview && <p className="muted" style={{ marginTop: -6 }}>别名：{me.preview}</p>}

      {subs.length > 0 && (
        <Section title={id === 'kb' ? '分类' : '子分类'} empty="">
          {subs.sort((a, b) => a.position - b.position).map((s) => (
            <a key={s.id} href="#" className="kb-link"
               onClick={(e) => { e.preventDefault(); onOpen(s.note_id) }}>
              ▤ {s.title}
              {s.fact_count > 0 && <span className="muted" style={{ marginInlineStart: 8 }}>{s.fact_count}</span>}
            </a>
          ))}
        </Section>
      )}

      {facts === undefined
        ? <p className="muted">…</p>
        : facts.length > 0 && (
          <Section title="事实" empty="">
            {facts.map((f) => (
              <a key={f.id} href="#" className="kb-link"
                 onClick={(e) => { e.preventDefault(); onOpen(f.note_id) }}>
                <span className="muted" style={{ marginInlineEnd: 8 }}>{f.updated_at}</span>{f.preview}
              </a>
            ))}
          </Section>
        )}
    </div>
  )
}

/** 一条原话可能是整段会议记录（真实库里有上千字的）。先给开头，要看再展开——
 *  「原话」的作用是核对出处，不是重读整场会。 */
const QUOTE_CHARS = 280
function Quote({ line }: { line: SourceLine }) {
  const [full, setFull] = useState(false)
  const long = line.text.length > QUOTE_CHARS
  const text = full || !long ? line.text : line.text.slice(0, QUOTE_CHARS) + '…'
  return (
    <blockquote className="kb-quote">
      <span className="muted">{line.who || '?'}{line.date ? ` · ${line.date}` : ''}：</span>{text}
      {long && (
        <a href="#" className="muted" style={{ marginInlineStart: 6 }}
           onClick={(e) => { e.preventDefault(); setFull((v) => !v) }}>
          {full ? '收起' : `展开全文（${line.text.length} 字）`}
        </a>
      )}
    </blockquote>
  )
}

function Section({ title, empty, children }: {
  title: string; empty: string; children: React.ReactNode
}) {
  const kids = Array.isArray(children) ? children.filter(Boolean) : children ? [children] : []
  if (kids.length === 0 && !empty) return null
  return (
    <section className="kb-section">
      <h3 className="kb-section-title">{title}</h3>
      {kids.length === 0 ? <p className="muted" style={{ margin: 0 }}>{empty}</p> : kids}
    </section>
  )
}
