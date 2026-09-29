/** 灵动岛笔记编辑器底下那一条「相关记忆」。
 *
 *  只有东西可摆的时候才出现（写够 8 个字、知识库有货、召回到了没引过的事实）；
 *  一行 28px 的头，点开才是最多三条。**它自己不会打开，也不会抢焦点**：
 *  展开状态由父级持有（跟 AI 抽屉互斥），这里只报告 `onExpandedChange`。 */
import { useRef, type KeyboardEvent } from 'react'
import type { Fact } from '../api'
import { useAmbientRecall } from '../util/useAmbientRecall'
import Icon from './Icon'
import '../companion-memory.css'

export type CompanionMemoryProps = {
  content: string
  enabled: boolean
  expanded: boolean
  onExpandedChange: (expanded: boolean) => void
  onCite: (fact: Fact) => void
}

const SHOWN_MAX = 3

export default function CompanionMemory({ content, enabled, expanded, onExpandedChange, onCite }: CompanionMemoryProps) {
  const { facts } = useAmbientRecall(content, enabled)
  const headRef = useRef<HTMLButtonElement>(null)
  if (!enabled || facts.length === 0) return null

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== 'Escape' || !expanded || e.nativeEvent.isComposing) return
    e.stopPropagation(); e.preventDefault()
    onExpandedChange(false)
    headRef.current?.focus()
  }

  return (
    <div className="dc-memory-strip" data-expanded={expanded} onKeyDown={onKeyDown}>
      <button ref={headRef} type="button" className="dc-memory-head" aria-expanded={expanded} aria-label="相关记忆"
              title={expanded ? '收起相关记忆' : '展开相关记忆'} onClick={() => onExpandedChange(!expanded)}>
        <Icon n="bx-bookmark-plus" />
        <span className="dc-memory-count">{facts.length} 条相关记忆</span>
        <span className="dc-memory-lead">{facts[0].text}</span>
        <Icon n="bx-chevron-down" className="dc-memory-chevron" />
      </button>
      <div className="dc-memory-body" inert={!expanded} aria-hidden={!expanded}>
        <div className="dc-memory-inner">
          {facts.slice(0, SHOWN_MAX).map((fact) => (
            <div key={fact.id} className="dc-memory-fact">
              <span className="dc-memory-text">{fact.text}</span>
              {fact.when && <span className="dc-memory-when">{fact.when}</span>}
              <button type="button" className="dc-memory-cite" title="引用到正在写的笔记" onClick={() => onCite(fact)}>引用</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
