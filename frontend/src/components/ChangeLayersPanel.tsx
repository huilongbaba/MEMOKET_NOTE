/**
 * 改动的分层账本（agent-native-editor.md §3.2）：每次 AI 动作是一层（润色、格式化、
 * 智能续写…），整层接受 / 撤回。痛点 8：AI 改了三轮，只想保留第一轮——之前只有
 * 「这一轮」一层高亮，做不到。
 *
 * 层是**可开关的**：关掉 = 每一处还原成改之前，但记住它改成了什么；再打开 = 写回去
 * （原文那处被改过就重放不了，说清楚）。「接受」定稿、「丢弃」忘掉，这两个才是终点。
 *
 * **关掉重开还在**（P39）：层和每一处的处置状态落在 `note_change_layers` 里
 * （P37 #5 量出来的四个缺口——八种层什么都不留、`auto` 那档被 600s 掐掉、
 * `harness_runs` 没有 `note_id`、处置状态根本没有载体——就是这张表要补的）。
 * 逐处接受 / 撤回过的那几下也留着：`roundDiffField` 里另记了一本 `settled` 账，
 * 不然按下去的那一刻 hunk 就从列表里没了，什么都写不进库。
 * 烧之后（「全部接受」）这张表清空，那一段改由下面的「烧过的跑」接手（P16）。
 *
 * **烧之后还在**（P16）：接受 = 烧进正文，层就没了；但后端每轮开始前存了一版（`note_revisions.reason='round'`），
 * 所以这次跑的每一轮还列在下面——「回到这轮之前」恢复那一版（恢复前会再存一版，可逆）、「只撤这一轮」
 * 拿这一轮前后两版做 diff 反向应用到现在的正文（`editor/undoRound`，冲突说清楚）。留一二轮、丢第三轮，烧之后也做得到。
 */
import { useState, type RefObject } from 'react'
import type { EditorView } from '@codemirror/view'
import { acceptLayer, dropLayer, layersOf, settledOf, turnLayerOff, turnLayerOn } from '../editor/roundDiff'
import { runTitle, type RunHistory, type RunRound } from '../util/runRounds'
import { toast } from '../toast'

const when = (t: number | string) => new Date(t).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })

export default function ChangeLayersPanel({ viewRef, tick, runs = [], stuck = [], onRecomputeStuck, onDropStuck,
                                            onRestoreBefore, onUndoRound, busy = false }: {
  viewRef: RefObject<EditorView | null>
  tick: number
  /** 烧过的跑（`util/runRounds.groupRuns`），新的在前 */
  runs?: RunHistory[]
  /** 重开时**放不回来**的那几层（正文在别处改过，按文字也定位不到）。
   *  原来只有一句 toast——话说完用户没有任何可按的东西（P41 #5 ② / P39「留给下一批」②）。 */
  stuck?: { id: string; label: string; why: string[] }[]
  onRecomputeStuck?: (id: string) => void
  onDropStuck?: (id: string) => void
  onRestoreBefore?: (r: RunRound) => void
  onUndoRound?: (r: RunRound) => void
  busy?: boolean
}) {
  void tick                                            // 只为了在处置后重渲染
  const [, bump] = useState(0)
  const view = viewRef.current
  const layers = view ? layersOf(view) : []
  const settled = view ? settledOf(view) : []
  const settledOn = (id: number) => settled.find((x) => x.id === id)
  /** 处置完的层：一处活的都不剩，但「2 接受 · 1 撤回」这几下是用户真做过的决定，
   *  关掉重开还得看得见（P39）。列成一行灰字，不给它一张带按钮的卡片——
   *  卡片上那两个钮按下去什么都不会发生。 */
  const settledOnly = settled.filter((x) => !layers.some((l) => l.id === x.id))
  const settledLines = settledOnly.map((x) => (
    <p key={x.id} className="muted layer-settled" style={{ fontSize: 'var(--t-xs)', margin: 0 }}>
      {x.label} · {when(x.at)} · 已处置：{x.accepted} 处接受、{x.reverted} 处撤回
    </p>
  ))
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
  /** 放不回来的那几层：**每一层一张卡，两个出路**（P41 #5 ②）。
   *  摆在最上面——它是一个「等你做决定」的东西，而下面那些层已经好好地在那儿了。 */
  const stuckCards = stuck.length === 0 ? null : (
    <div className="stack layer-stuck" style={{ gap: 6 }}>
      <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: 0 }}>
        下面 {stuck.length} 层是上次留下、<strong>这次放不回来</strong>的：正文在别处改过，按文字也定位不到原来那几处。
        <strong>正文一个字没动</strong>——要么按现在的正文重新算一次，要么丢掉它。
      </p>
      {stuck.map((s) => (
        <div key={s.id} className="card layer-card stuck" style={{ padding: '6px 10px' }}>
          <div className="row" style={{ gap: 8, alignItems: 'center' }}>
            <strong style={{ fontSize: 'var(--t-md)' }}>{s.label}</strong>
            <span className="muted" style={{ fontSize: 'var(--t-xs)' }}>{s.why.length} 处对不上：{s.why.slice(0, 2).join('；')}</span>
            <span style={{ marginInlineStart: 'auto', display: 'flex', gap: 4 }}>
              <button style={{ fontSize: 'var(--t-sm)', padding: '2px 8px' }}
                      title="拿这一层改的每一处，在现在这份正文里再找一次；找得到就放回「改动」里"
                      onClick={() => onRecomputeStuck?.(s.id)}>重新算这一层</button>
              <button style={{ fontSize: 'var(--t-sm)', padding: '2px 8px' }}
                      title="不要这一层了（正文一个字没动，只是不再留着这个待办）"
                      onClick={() => onDropStuck?.(s.id)}>丢掉这一层</button>
            </span>
          </div>
        </div>
      ))}
    </div>
  )
  return (
    <div className="stack" style={{ gap: 6 }}>
      {stuckCards}
      {!view || layers.length === 0
        ? <>
          {/* **上面还摆着放不回来的层时不许说「现在没有待处置的改动」**（P41）——
              同一块面板上一句说有、一句说没有，就是这一批在别处修的那种「两块面板打架」。 */}
          <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: 0 }}>AI 改过的地方会按动作分层列在这里：整层接受、整层撤回。{stuck.length ? '除了上面那几层，没有别的待处置改动。' : '现在没有待处置的改动。'}</p>
          {settledLines}
        </>
        : <>
          <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: 0 }}>{layers.length} 层 · 早的在上。开关一层 = 它改的每一处还原 / 写回；「接受」定稿、「丢弃」忘掉。<strong>关掉这个 app 再打开，这几层和你逐处按下去的接受 / 撤回都还在</strong>（下面「烧过的跑」那一段也留）。</p>
          {layers.map((l, i) => (
            <div key={l.id} className={'card layer-card' + (l.off ? ' off' : '')} style={{ padding: '6px 10px' }}>
              <div className="row" style={{ gap: 8, alignItems: 'center' }}>
                <button className={'switch' + (l.off ? '' : ' on')} role="switch" aria-checked={!l.off} title={l.off ? '打开这层：把它改的写回去' : '关掉这层：每一处还原成改之前，随时能再打开'} onClick={() => toggle(l.id, l.off)}><span /></button>
                <strong style={{ fontSize: 'var(--t-md)' }}>{l.label} {layers.filter((x) => x.label === l.label).length > 1 ? '①②③④⑤⑥⑦⑧⑨'[layers.filter((x, j) => x.label === l.label && j <= i).length - 1] ?? '' : ''}</strong>
                <span className="muted" style={{ fontSize: 'var(--t-xs)' }}>{when(l.at)} · {l.count} 处{(() => { const x = settledOn(l.id); return x ? ` · 已处置 ${x.accepted} 接受 / ${x.reverted} 撤回` : '' })()}</span>
                <span style={{ marginInlineStart: 'auto', display: 'flex', gap: 4 }}>
                  {!l.off && <button style={{ fontSize: 'var(--t-sm)', padding: '2px 8px' }} title="保留这层改的全部（定稿）" onClick={() => view.dispatch({ effects: acceptLayer.of(l.id) })}>接受</button>}
                  <button style={{ fontSize: 'var(--t-sm)', padding: '2px 8px' }} title={l.off ? '忘掉这层（正文已经是原文）' : '把这层改的每一处还原并忘掉'} onClick={() => dropLayer(view, l.id)}>{l.off ? '丢弃' : '撤回'}</button>
                </span>
              </div>
            </div>
          ))}
          {settledLines}
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
