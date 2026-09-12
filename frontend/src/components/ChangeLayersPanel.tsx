/**
 * 改动的分层账本（agent-native-editor.md §3.2）：每次 AI 动作是一层（润色、格式化、
 * 智能续写…），整层接受 / 撤回。痛点 8：AI 改了三轮，只想保留第一轮——之前只有
 * 「这一轮」一层高亮，做不到。
 *
 * 层是**可开关的**：关掉 = 每一处还原成改之前，但记住它改成了什么；再打开 = 写回去
 * （原文那处被改过就重放不了，说清楚）。「接受」定稿、「丢弃」忘掉，这两个才是终点。
 */
import { useState, type RefObject } from 'react'
import type { EditorView } from '@codemirror/view'
import { acceptLayer, dropLayer, layersOf, turnLayerOff, turnLayerOn } from '../editor/roundDiff'
import { toast } from '../toast'

export default function ChangeLayersPanel({ viewRef, tick }: { viewRef: RefObject<EditorView | null>; tick: number }) {
  void tick                                            // 只为了在处置后重渲染
  const [, bump] = useState(0)
  const view = viewRef.current
  const layers = view ? layersOf(view) : []
  if (!view || layers.length === 0) {
    return <p className="muted" style={{ fontSize: 12, margin: 0 }}>AI 改过的地方会按动作分层列在这里：整层接受、整层撤回。现在没有待处置的改动。</p>
  }
  const when = (t: number) => new Date(t).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  const toggle = (id: number, off: boolean) => {
    if (off) {
      const r = turnLayerOn(view, id)
      if (r.lost) toast(`打开了 ${r.replayed} 处，${r.lost} 处因为原文改过没能重放`, 'error')
    } else {
      turnLayerOff(view, id)
    }
    bump((n) => n + 1)                                 // 关 / 开是 dispatch 出去的，React 不知道
  }
  return (
    <div className="stack" style={{ gap: 6 }}>
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>{layers.length} 层 · 早的在上。开关一层 = 它改的每一处还原 / 写回；「接受」定稿、「丢弃」忘掉。</p>
      {layers.map((l, i) => (
        <div key={l.id} className={'card layer-card' + (l.off ? ' off' : '')} style={{ padding: '6px 10px' }}>
          <div className="row" style={{ gap: 8, alignItems: 'center' }}>
            <button className={'switch' + (l.off ? '' : ' on')} role="switch" aria-checked={!l.off} title={l.off ? '打开这层：把它改的写回去' : '关掉这层：每一处还原成改之前，随时能再打开'} onClick={() => toggle(l.id, l.off)}><span /></button>
            <strong style={{ fontSize: 13 }}>{l.label} {layers.filter((x) => x.label === l.label).length > 1 ? '①②③④⑤⑥⑦⑧⑨'[layers.filter((x, j) => x.label === l.label && j <= i).length - 1] ?? '' : ''}</strong>
            <span className="muted" style={{ fontSize: 11 }}>{when(l.at)} · {l.count} 处</span>
            <span style={{ marginInlineStart: 'auto', display: 'flex', gap: 4 }}>
              {!l.off && <button style={{ fontSize: 12, padding: '2px 8px' }} title="保留这层改的全部（定稿）" onClick={() => view.dispatch({ effects: acceptLayer.of(l.id) })}>接受</button>}
              <button style={{ fontSize: 12, padding: '2px 8px' }} title={l.off ? '忘掉这层（正文已经是原文）' : '把这层改的每一处还原并忘掉'} onClick={() => dropLayer(view, l.id)}>{l.off ? '丢弃' : '撤回'}</button>
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}
