import { useEffect, useRef, useState } from 'react'
import { memoryRelations, mergeFacts, recall, supersedeFact } from '../api'
import type { Fact, MemoryRelation } from '../api'
import { toast } from '../toast'

const REL_LABEL: Record<MemoryRelation['relation'], { text: string; cls: string; icon: string }> = {
  conflict: { text: '冲突', cls: 'rel-conflict', icon: 'bx-error' },
  continuation: { text: '延续', cls: 'rel-continuation', icon: 'bx-trending-up' },
  corroborated: { text: '印证', cls: 'rel-corroborated', icon: 'bx-check-shield' },
  unsupported: { text: '缺依据', cls: 'rel-unsupported', icon: 'bx-question-mark' },
  accumulation: { text: '叠加', cls: 'rel-accumulation', icon: 'bx-layer-plus' },
  merge: { text: '合并', cls: 'rel-merge', icon: 'bx-git-merge' },
}
const IGNORED_KEY = 'memoket-note-ignored-relations'
function ignoredSet(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(IGNORED_KEY) || '[]')) } catch { return new Set() }
}

const IDLE_MS = 900
const TAIL_CHARS = 500
const MIN_CHARS = 8

/**
 * Ambient recall: related facts surface on their own while you write, no
 * query typed -- the "Heads Up"/"Connections pane" pattern several
 * competitors use (Mem, Obsidian's Smart Connections) instead of only
 * offering search-on-demand. Cheap to run this aggressively: /api/memory/recall
 * is a zero-LLM keyword lookup (observed ~30ms), unlike skeleton/edit/magic-tap
 * which hit the LLM and need long debounce windows.
 */
export default function RelatedMemory({ content, paragraph = '', onInsert }: {
  /** 光标所在段落：按它查关系（不是尾部 500 字） */
  paragraph?: string
  content: string
  onInsert: (text: string) => void
}) {
  const [facts, setFacts] = useState<Fact[]>([])
  const [loading, setLoading] = useState(false)
  const lastQueried = useRef('')

  // 关系：光标停在一段上 900ms 就查一次。只对有具体数字 / 日期的段落有意义（后端没量就回空）。
  const [rels, setRels] = useState<MemoryRelation[]>([])
  const [relBusy, setRelBusy] = useState(false)
  const [ignored, setIgnored] = useState<Set<string>>(() => ignoredSet())
  const lastPara = useRef('')
  useEffect(() => {
    const p = paragraph.trim()
    if (p.length < 8 || !/\d/.test(p)) { setRels([]); return }
    if (p === lastPara.current) return
    const t = setTimeout(() => {
      lastPara.current = p
      setRelBusy(true)
      memoryRelations(p).then((r) => setRels(r.relations)).catch(() => {}).finally(() => setRelBusy(false))
    }, IDLE_MS)
    return () => clearTimeout(t)
  }, [paragraph])
  function ignore(key: string) {
    const next = new Set(ignored); next.add(key); setIgnored(next)
    try { localStorage.setItem(IGNORED_KEY, JSON.stringify([...next].slice(-200))) } catch { /* 无所谓 */ }
  }
  async function supersede(rel: MemoryRelation) {
    // 「新的取代旧的」：正文里这句是新值，旧记录标成被取代——但正文这句还没成为事实，
    // 先把它作为手工事实的责任交给「引用」页；这里只能在有两条记录时标旧的被新的取代。
    const old = rel.facts[0]
    const latest = rel.facts[rel.facts.length - 1]
    if (!old || !latest || old.id === latest.id) { toast('正文这句还不是知识库里的记录——先在「引用」页「补一条」，再来标取代'); return }
    try { await supersedeFact(old.id, latest.id); toast('已标记：旧记录被新的取代'); ignore(rel.relation + ':' + rel.fact_ids.join(',')) }
    catch (e) { toast('标不上：' + String(e), 'error') }
  }
  async function merge(rel: MemoryRelation) {
    // 「合成一条」：留晚的那条，早的标成被它取代（merged）；结果记住，下次不再提这一对
    const [a, b] = rel.facts
    if (!a || !b) return
    try { await mergeFacts(b.id, a.id); toast('已合成一条：留下了 ' + (b.when || '晚的那条')); ignore(rel.relation + ':' + rel.fact_ids.join(',')) }
    catch (e) { toast('合不了：' + String(e), 'error') }
  }
  function fillIn(rel: MemoryRelation) {
    // 「补进来」：把知识库里那几个条件带引用插进正文
    onInsert(rel.facts.map((f) => `${f.text} [${f.id}]`).join('\n'))
    ignore(rel.relation + ':' + rel.fact_ids.join(','))
  }
  const visibleRels = rels.filter((r) => !ignored.has(r.relation + ':' + r.fact_ids.join(',')))

  useEffect(() => {
    const tail = content.slice(-TAIL_CHARS).trim()
    if (tail.length < MIN_CHARS) { setFacts([]); return }
    if (tail === lastQueried.current) return
    const t = setTimeout(() => {
      lastQueried.current = tail
      setLoading(true)
      recall(tail, 5)
        .then((r) => setFacts(r.facts))
        .catch(() => {})
        .finally(() => setLoading(false))
    }, IDLE_MS)
    return () => clearTimeout(t)
  }, [content])

  // 之前 facts 是空的时候整个组件（连带标题）直接 return null——这是这个
  // 面板在"写作"/"相关记忆"/"知识库" 三个 tab 里唯一的内容，点进"相关记忆"
  // 这个 tab 却看到完全空白，用户分不清是"还没写够内容触发检索"还是"面板
  // 坏了"。保留标题，用不同文案区分"内容太短还没触发"和"检索了但没找到"
  // 这两种不同的空状态。
  const tooShort = content.slice(-TAIL_CHARS).trim().length < MIN_CHARS

  return (
    <div>
      <p className="muted" style={{ fontSize: 12, margin: '4px 0 8px', display: 'flex', gap: 6, alignItems: 'center' }}>
        跟着你写的内容自动浮现，点一下插入引用。{loading && <span className="spinner" />}
      </p>
      {(visibleRels.length > 0 || relBusy) && (
        <div className="stack" style={{ gap: 6, marginBottom: 10 }}>
          <div className="muted" style={{ fontSize: 11 }}>光标这段跟知识库的关系{relBusy && <> <span className="spinner" /></>}</div>
          {visibleRels.map((r) => {
            const L = REL_LABEL[r.relation]
            const key = r.relation + ':' + r.fact_ids.join(',')
            return (
              <div key={key} className={'card rel-card ' + L.cls}>
                <div className="row" style={{ gap: 6, alignItems: 'center' }}>
                  <span className={'badge ' + L.cls}><i className={'bx ' + L.icon} /> {L.text}</span>
                  <span style={{ fontSize: 13, flex: 1 }}>{r.say}</span>
                </div>
                {r.facts.length > 0 && (
                  <div className="stack" style={{ gap: 2, marginTop: 4 }}>
                    {r.facts.map((f) => (
                      <div key={f.id} className="muted" style={{ fontSize: 12, cursor: 'pointer' }} title="打开这条"
                           onClick={() => window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb:fact:' + f.id }))}>
                        <span className="badge" style={{ marginInlineEnd: 4 }}>{f.when || '—'}</span>{f.text}
                      </div>
                    ))}
                  </div>
                )}
                <div className="row" style={{ gap: 4, marginTop: 6 }}>
                  {r.facts.length > 0 && <button style={{ fontSize: 12, padding: '2px 8px' }} onClick={() => onInsert(`${r.facts[r.facts.length - 1].text} [${r.facts[r.facts.length - 1].id}]`)}>引用这条</button>}
                  {r.relation === 'conflict' && <button style={{ fontSize: 12, padding: '2px 8px' }} onClick={() => void supersede(r)}>新的取代旧的</button>}
                  {r.relation === 'accumulation' && r.facts.length > 0 && <button style={{ fontSize: 12, padding: '2px 8px' }} onClick={() => fillIn(r)}>补进来</button>}
                  {r.relation === 'merge' && r.facts.length === 2 && <button style={{ fontSize: 12, padding: '2px 8px' }} onClick={() => void merge(r)}>合成一条</button>}
                  <button style={{ fontSize: 12, padding: '2px 8px' }} onClick={() => ignore(key)}>忽略</button>
                </div>
              </div>
            )
          })}
        </div>
      )}
      {facts.length === 0 && !loading && (
        <p className="muted" style={{ fontSize: 13 }}>
          {tooShort ? '再多写几个字就会开始自动检索。' : '知识库里暂时没有找到相关内容。'}
        </p>
      )}
      {facts.map((f) => (
        <div
          className="card memory-card"
          key={f.id}
          style={{ cursor: 'pointer' }}
          onClick={() => onInsert(`${f.text} [${f.id}]`)}
          title="点击插入引用到光标处"
        >
          <div style={{ fontSize: 13 }}>{f.text}</div>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', marginTop: 4 }}>
            <span className="row" style={{ gap: 4 }}>
              {f.when ? <span className="badge">{f.when}</span> : null}
              {/* 正文里已经引过的标出来——不然同一条会被插两次（实拍：一段里两个同样的出处） */}
              {content.includes(`[${f.id}]`) && <span className="badge ok" title="正文里已经引用了这条">已引用</span>}
            </span>
            <span className="memory-card-actions">
              <button className="icon-btn" title="打开这条事实"
                      onClick={(e) => { e.stopPropagation(); window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb:fact:' + f.id })) }}>
                <i className="bx bx-link-external" />
              </button>
              <button className="icon-btn" title="插入引用到光标处" onClick={(e) => { e.stopPropagation(); onInsert(`${f.text} [${f.id}]`) }}>
                <i className="bx bx-link" />
              </button>
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}
