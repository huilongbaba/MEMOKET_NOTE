/**
 * 改动的分层账本（agent-native-editor.md §3.2）：每次 AI 动作是一层（润色、格式化、
 * 智能续写…），整层接受 / 撤回。痛点 8：AI 改了三轮，只想保留第一轮——之前只有
 * 「这一轮」一层高亮，做不到。
 *
 * 撤回一层 = 把这层每一处还原成改之前；之后叠在同一处上的改动会跟着没掉，说清楚。
 */
import type { RefObject } from 'react'
import type { EditorView } from '@codemirror/view'
import { acceptLayer, dropLayer, layersOf } from '../editor/roundDiff'

export default function ChangeLayersPanel({ viewRef, tick }: { viewRef: RefObject<EditorView | null>; tick: number }) {
  void tick                                            // 只为了在处置后重渲染
  const view = viewRef.current
  const layers = view ? layersOf(view) : []
  if (!view || layers.length === 0) {
    return <p className="muted" style={{ fontSize: 12, margin: 0 }}>AI 改过的地方会按动作分层列在这里：整层接受、整层撤回。现在没有待处置的改动。</p>
  }
  const when = (t: number) => new Date(t).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  return (
    <div className="stack" style={{ gap: 6 }}>
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>{layers.length} 层 · 早的在上。撤回一层会把它改的每一处还原，之后叠在同一处的改动也会跟着退。</p>
      {layers.map((l, i) => (
        <div key={l.id} className="card" style={{ padding: '6px 10px' }}>
          <div className="row" style={{ gap: 8, alignItems: 'center' }}>
            <span style={{ color: 'var(--ins)' }}>●</span>
            <strong style={{ fontSize: 13 }}>{l.label} {layers.filter((x) => x.label === l.label).length > 1 ? '①②③④⑤⑥⑦⑧⑨'[layers.filter((x, j) => x.label === l.label && j <= i).length - 1] ?? '' : ''}</strong>
            <span className="muted" style={{ fontSize: 11 }}>{when(l.at)} · {l.count} 处</span>
            <span style={{ marginInlineStart: 'auto', display: 'flex', gap: 4 }}>
              <button style={{ fontSize: 12, padding: '2px 8px' }} title="保留这层改的全部" onClick={() => view.dispatch({ effects: acceptLayer.of(l.id) })}>接受</button>
              <button style={{ fontSize: 12, padding: '2px 8px' }} title="把这层改的每一处还原" onClick={() => dropLayer(view, l.id)}>撤回</button>
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}
