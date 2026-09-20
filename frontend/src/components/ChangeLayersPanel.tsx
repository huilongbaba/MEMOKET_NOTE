/**
 * 改动的分层账本（agent-native-editor.md §3.2）：每次 AI 动作是一层（润色、格式化、
 * 智能续写…），整层接受 / 撤回。痛点 8：AI 改了三轮，只想保留第一轮——之前只有
 * 「这一轮」一层高亮，做不到。
 *
 * 层是**可开关的**：关掉 = 每一处还原成改之前，但记住它改成了什么；再打开 = 写回去
 * （原文那处被改过就重放不了，说清楚）。「接受」定稿、「丢弃」忘掉，这两个才是终点。
 *
 * **没烧的那一层关掉就没了**（P37 #5 / P35 #9）：层活在 CodeMirror 的编辑器状态里，
 * **一行都不落库**——P37 在真库上量过（44 行 `note_revisions` 里 `run_id` / `round_no`
 * 全是空的；除了 `round_snapshot` 那条路，九种改动层里有八种在库里什么都不留；
 * 能顶上的 `auto` 那一档又卡在 `REVISION_INTERVAL_S = 600s` 上）。所以重建不出来，
 * 落库是下一批的事。在那之前**至少说一句**：关掉 = 按「接受」处理。
 *
 * **烧之后还在**（P16）：接受 = 烧进正文，层就没了；但后端每轮开始前存了一版（`note_revisions.reason='round'`），
 * 所以这次跑的每一轮还列在下面——「回到这轮之前」恢复那一版（恢复前会再存一版，可逆）、「只撤这一轮」
 * 拿这一轮前后两版做 diff 反向应用到现在的正文（`editor/undoRound`，冲突说清楚）。留一二轮、丢第三轮，烧之后也做得到。
 */
import { useState, type RefObject } from 'react'
import type { EditorView } from '@codemirror/view'
import { acceptLayer, dropLayer, layersOf, turnLayerOff, turnLayerOn } from '../editor/roundDiff'
import { runTitle, type RunHistory, type RunRound } from '../util/runRounds'
import { toast } from '../toast'

const when = (t: number | string) => new Date(t).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })

export default function ChangeLayersPanel({ viewRef, tick, runs = [], onRestoreBefore, onUndoRound, busy = false }: {
  viewRef: RefObject<EditorView | null>
  tick: number
  /** 烧过的跑（`util/runRounds.groupRuns`），新的在前 */
  runs?: RunHistory[]
  onRestoreBefore?: (r: RunRound) => void
  onUndoRound?: (r: RunRound) => void
  busy?: boolean
}) {
  void tick                                            // 只为了在处置后重渲染
  const [, bump] = useState(0)
  const view = viewRef.current
  const layers = view ? layersOf(view) : []
  const toggle = (id: number, off: boolean) => {
    if (!view) return
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
      {!view || layers.length === 0
        ? <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: 0 }}>AI 改过的地方会按动作分层列在这里：整层接受、整层撤回。现在没有待处置的改动。</p>
        : <>
          <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: 0 }}>{layers.length} 层 · 早的在上。开关一层 = 它改的每一处还原 / 写回；「接受」定稿、「丢弃」忘掉。<strong>关掉这个 app 就当接受了</strong>——这几层活在这次会话里，不会留到下次打开（下面「烧过的跑」那一段会留）。</p>
          {layers.map((l, i) => (
            <div key={l.id} className={'card layer-card' + (l.off ? ' off' : '')} style={{ padding: '6px 10px' }}>
              <div className="row" style={{ gap: 8, alignItems: 'center' }}>
                <button className={'switch' + (l.off ? '' : ' on')} role="switch" aria-checked={!l.off} title={l.off ? '打开这层：把它改的写回去' : '关掉这层：每一处还原成改之前，随时能再打开'} onClick={() => toggle(l.id, l.off)}><span /></button>
                <strong style={{ fontSize: 'var(--t-md)' }}>{l.label} {layers.filter((x) => x.label === l.label).length > 1 ? '①②③④⑤⑥⑦⑧⑨'[layers.filter((x, j) => x.label === l.label && j <= i).length - 1] ?? '' : ''}</strong>
                <span className="muted" style={{ fontSize: 'var(--t-xs)' }}>{when(l.at)} · {l.count} 处</span>
                <span style={{ marginInlineStart: 'auto', display: 'flex', gap: 4 }}>
                  {!l.off && <button style={{ fontSize: 'var(--t-sm)', padding: '2px 8px' }} title="保留这层改的全部（定稿）" onClick={() => view.dispatch({ effects: acceptLayer.of(l.id) })}>接受</button>}
                  <button style={{ fontSize: 'var(--t-sm)', padding: '2px 8px' }} title={l.off ? '忘掉这层（正文已经是原文）' : '把这层改的每一处还原并忘掉'} onClick={() => dropLayer(view, l.id)}>{l.off ? '丢弃' : '撤回'}</button>
                </span>
              </div>
            </div>
          ))}
        </>}
      {runs.length > 0 && (
        <div className="stack run-history" style={{ gap: 6, marginTop: layers.length ? 10 : 4 }}>
          <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: 0 }}>烧进正文之后每一轮还在：「回到这轮之前」恢复那一版（恢复前会再存一版）；「只撤这一轮」把它改的反向应用到现在的正文，别的轮留着。</p>
          {runs.map((run, ri) => (
            <details key={run.run_id} className="run-card" open={ri === 0}>
              <summary className="run-title"><strong>{runTitle(run)}</strong><span className="muted" style={{ fontSize: 'var(--t-xs)' }}> · {when(run.at)}</span></summary>
              <div className="stack" style={{ gap: 4, marginTop: 4 }}>
                {run.rounds.map((r) => {
                  const delta = r.after ? r.after.chars - r.before.chars : null
                  return (
                    <div key={r.before.id} className="card run-round" style={{ padding: '5px 10px' }}>
                      <div className="row" style={{ gap: 8, alignItems: 'center' }}>
                        <strong style={{ fontSize: 'var(--t-md)' }}>第 {r.round_no} 轮</strong>
                        <span className="muted" style={{ fontSize: 'var(--t-xs)' }}>{when(r.before.created_at)}{delta == null ? ' · 还没收尾' : ` · ${delta >= 0 ? '+' : ''}${delta} 字`}</span>
                        <span style={{ marginInlineStart: 'auto', display: 'flex', gap: 4 }}>
                          <button style={{ fontSize: 'var(--t-sm)', padding: '2px 8px' }} disabled={busy}
                                  title={`正文回到第 ${r.round_no} 轮开始前的样子（这一轮和之后的都没了；恢复前的正文会再存一版，随时能回来）`}
                                  onClick={() => onRestoreBefore?.(r)}>回到这轮之前</button>
                          <button style={{ fontSize: 'var(--t-sm)', padding: '2px 8px' }} disabled={busy || !r.after}
                                  title={r.after ? `只把第 ${r.round_no} 轮改的撤掉，别的轮留着；改过的地方对不上会说清楚` : '这一轮还没收尾，没有「之后」可比'}
                                  onClick={() => onUndoRound?.(r)}>只撤这一轮</button>
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  )
}
