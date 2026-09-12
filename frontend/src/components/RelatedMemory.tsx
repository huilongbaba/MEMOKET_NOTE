import { useEffect, useRef, useState } from 'react'
import { recall } from '../api'
import type { Fact } from '../api'

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
export default function RelatedMemory({ content, onInsert }: {
  content: string
  onInsert: (text: string) => void
}) {
  const [facts, setFacts] = useState<Fact[]>([])
  const [loading, setLoading] = useState(false)
  const lastQueried = useRef('')

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
