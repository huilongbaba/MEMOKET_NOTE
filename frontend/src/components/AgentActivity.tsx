import { useState } from 'react'
import type { NoteHarnessToolCall } from '../api'

/** 一轮里 agent 干了什么。按轮聚合而不是按事件平铺——用户关心的是
 * "这一轮它查了什么、改了什么、打了几分、然后决定下一轮怎么跑"这条
 * 因果链，事件流水账反而看不出所以然。 */
export type AgentRound = {
  round: number
  /** 跳过续写、只做重复清理的轮次。这类轮次不会有续写增量，
   * 标出来免得用户以为卡住了。 */
  cleanupOnly: boolean
  revisions: number
  toolCalls: NoteHarnessToolCall[]
  toolTruncated: boolean
  scores: Record<string, { level: number; note: string }>
  status: string
  weakest: string | null
  /** 这一轮结束后策略控制器做的调整。空数组 = 没调整（一切正常）。 */
  policyReasons: string[]
  /** 第 0 轮（开跑前按历史记录定的初始策略）可能只带部分字段，所以都是可选的 */
  policy: Partial<{ tool_iters: number; continue_temperature: number;
                    max_revisions: number; require_verification: boolean }> | null
  errors: string[]
  /** 被防线丢弃的修订及原因。跟 errors 分开：这是防线正常起作用，
   * 混在报错里会让界面变成一片红。 */
  dropped: string[]
  /** 代码判据（不是模型）当场判这一轮不合格。命中时这一轮**不会**再花一次
   * 模型调用去打分——所以要标出来，否则用户看到一个 0 分却不知道是谁判的。 */
  checkHit?: { dimension: string; note: string }
  /** 当前阶段（retrieval/edit/write/evaluate）和它的人话标签 */
  phase?: string
  phaseLabel?: string
  /** 每个阶段的实时输出，按阶段分开存。thinking 是模型的思考过程。 */
  phaseText?: Record<string, { thinking: string; output: string }>
  /** 这一轮流式写出来的正文。两段式之后编辑器有几十秒完全不动（检索规划
   * 是非流式的），面板里实时显示写出来的字，比一行干等的状态文案有用。 */
  streamed?: string
}

type Props = {
  rounds: AgentRound[]
  status: string
  running: boolean
}

const LEVEL_COLOR: Record<number, string> = { 0: 'var(--del)', 1: '#d68910', 2: 'var(--ins)' }
const LEVEL_LABEL: Record<number, string> = { 0: '不足', 1: '部分', 2: '达标' }

/** 维度的中文名。后端用英文 key 是因为 writer_harness 是要开源出去的独立包，
 * 不带任何中文领域词汇；中文只在展示层出现。 */
const DIM_LABEL: Record<string, string> = {
  spine_fidelity: '扣题',
  topic_fidelity: '扣题',
  beat_coverage: '节拍覆盖',
  non_repetition: '不重复',
  coherence: '连贯自洽',
  factual_grounding: '事实依据',
  material_use: '用上你的材料',
  style_fit: '风格贴合',
}

const PHASE_LABEL: Record<string, string> = {
  retrieval: '① 判断要不要查知识库',
  edit: '② 通读全文找问题',
  write: '③ 写正文',
  evaluate: '④ 打分',
}

const TOOL_LABEL: Record<string, string> = {
  search_memory: '关键词检索',
  list_topics: '看知识库有哪些主题',
  list_entities: '看有哪些人/产品',
  filter_facts: '按主题精确取',
  facts_in_range: '按时间范围取',
  fact_sources: '回溯到原始对话',
  search_session_context: '回到原始对话里追问',
}

/** 0/1/2 三档画成三格信号条——比纯数字更容易一眼扫过一排维度看出哪个塌了。 */
function LevelBars({ level }: { level: number }) {
  return (
    <span style={{ display: 'inline-flex', gap: 2, alignItems: 'flex-end', height: 11 }}>
      {[1, 2, 3].map((i) => (
        <i
          key={i}
          style={{
            display: 'block',
            width: 3,
            height: `${i * 33}%`,
            background: i <= level + 1 ? LEVEL_COLOR[level] : 'var(--line)',
          }}
        />
      ))}
    </span>
  )
}

function ToolCallRow({ call }: { call: NoteHarnessToolCall }) {
  const [open, setOpen] = useState(false)
  // 检索词是模型自己想出来的，是判断"它有没有找对方向"的关键信息，
  // 所以放在收起状态也能看见的位置，结果原文才藏在展开里。
  const query = Object.entries(call.args)
    .filter(([k]) => k !== 'limit')
    .map(([, v]) => String(v))
    .join(' / ')
  const empty = call.result.startsWith('（')
  return (
    <li style={{ marginBottom: 4, fontSize: 12, lineHeight: 1.5 }}>
      <button
        onClick={() => setOpen((v) => !v)}
        title={open ? '收起结果' : '展开查到的原文'}
        style={{
          all: 'unset', cursor: 'pointer', display: 'flex', gap: 6,
          alignItems: 'baseline', width: '100%',
        }}
      >
        <span className="muted" style={{ width: 10, flexShrink: 0 }}>{open ? '▾' : '▸'}</span>
        <span style={{ color: 'var(--accent)', flexShrink: 0 }}>
          {TOOL_LABEL[call.tool] ?? call.tool}
        </span>
        <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {query || '（无参数）'}
        </span>
        {empty && <span className="muted" style={{ flexShrink: 0 }}>没查到</span>}
      </button>
      {open && (
        <pre
          style={{
            margin: '4px 0 6px 16px', padding: '6px 8px', fontSize: 11, lineHeight: 1.6,
            whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 200, overflowY: 'auto',
            background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 4,
          }}
        >
          {call.result}
        </pre>
      )}
    </li>
  )
}

/** agent 行为可视化：这一轮查了什么、改了几处、六个维度各打几分、
 * 然后策略控制器把下一轮的运行参数调成了什么、为什么。
 *
 * 之前这些信息只有一行状态文案（"第 2 轮：修订 3 处，续写中…"），
 * agent 自主检索和策略调整这两件事在界面上完全不可见——用户既看不到
 * 它凭什么说自己有依据，也看不到 runtime 为什么突然变慢/变快。 */
export default function AgentActivity({ rounds, status, running }: Props) {
  if (!rounds.length && !status) return null
  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
        <h2 style={{ margin: 0 }}>Agent 运行</h2>
        {running && <span className="spinner" />}
      </div>

      {status && (
        <p className="muted" style={{ margin: '6px 0 10px', fontSize: 12 }}>{status}</p>
      )}

      {rounds.map((r) => (
        <div
          key={r.round}
          style={{
            marginBottom: 10, padding: '8px 10px', fontSize: 12,
            border: '1px solid var(--line)', borderRadius: 6, background: 'var(--panel)',
          }}
        >
          <div className="row" style={{ gap: 8, alignItems: 'baseline', marginBottom: 6 }}>
            <strong>第 {r.round} 轮</strong>
            {r.cleanupOnly && (
              <span className="muted" title="上一轮评分说已写内容自身有毛病，这一轮只理顺不加新内容">
                只清理，不续写
              </span>
            )}
            <span className="muted">修订 {r.revisions} 处</span>
            {r.phaseLabel && (
              <span style={{ color: 'var(--accent)', marginLeft: 'auto' }}>
                {r.phaseLabel}
              </span>
            )}
          </div>

          {r.toolCalls.length > 0 && (
            <>
              <div className="muted" style={{ marginBottom: 3 }}>
                agent 自己决定查了 {r.toolCalls.length} 次
                {r.toolTruncated && '（撞上限，还想继续查）'}
              </div>
              <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 6px' }}>
                {r.toolCalls.map((c, i) => <ToolCallRow key={i} call={c} />)}
              </ul>
            </>
          )}

          {Object.keys(r.scores).length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', margin: '4px 0 6px' }}>
              {Object.entries(r.scores).map(([dim, sc]) => (
                <span
                  key={dim}
                  title={`${LEVEL_LABEL[sc.level] ?? sc.level}：${sc.note}`}
                  style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}
                >
                  <LevelBars level={sc.level} />
                  <span style={{ color: sc.level < 2 ? LEVEL_COLOR[sc.level] : 'inherit' }}>
                    {DIM_LABEL[dim] ?? dim}
                  </span>
                </span>
              ))}
            </div>
          )}

          {/* 最弱维度的诊断原文——这句话现在也是喂回下一轮的东西，
              让用户看到它，才能理解下一轮为什么那么跑 */}
          {r.weakest && r.scores[r.weakest]?.note && (
            <p className="muted" style={{ margin: '0 0 6px', lineHeight: 1.55 }}>
              最弱是「{DIM_LABEL[r.weakest] ?? r.weakest}」：{r.scores[r.weakest].note}
            </p>
          )}

          {r.policyReasons.length > 0 && (
            <div
              style={{
                marginTop: 6, paddingTop: 6, borderTop: '1px dashed var(--line)',
              }}
            >
              <div className="muted" style={{ marginBottom: 3 }}>
                据此调整了下一轮的跑法
                {r.policy && (
                  <span>
                    　·　检索预算 {r.policy.tool_iters}
                    　·　续写温度 {r.policy.continue_temperature}
                    　·　修订额度 {r.policy.max_revisions}
                    {r.policy.require_verification && '　·　要求溯源核对'}
                  </span>
                )}
              </div>
              <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                {r.policyReasons.map((reason, i) => (
                  <li key={i} style={{ display: 'flex', gap: 5, lineHeight: 1.55 }}>
                    <span style={{ color: 'var(--accent)', flexShrink: 0 }}>↻</span>
                    <span>{reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {r.phaseText && Object.entries(r.phaseText).map(([ph, txt]) => (
            <details key={ph} style={{ marginTop: 4 }}>
              <summary style={{ cursor: 'pointer', color: 'var(--muted)' }}>
                {PHASE_LABEL[ph] ?? ph}
                {r.phase === ph && <span style={{ color: 'var(--accent)' }}> · 进行中</span>}
                <span className="muted">
                  （思考 {txt.thinking.length} 字 · 输出 {txt.output.length} 字）
                </span>
              </summary>
              {txt.thinking && (
                <pre style={{
                  margin: '4px 0 0', padding: '6px 8px', fontSize: 11, lineHeight: 1.6,
                  whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 160,
                  overflowY: 'auto', background: 'var(--bg)', border: '1px dashed var(--line)',
                  borderRadius: 4, color: 'var(--muted)', fontStyle: 'italic',
                }}>{txt.thinking}</pre>
              )}
              {txt.output && (
                <pre style={{
                  margin: '4px 0 0', padding: '6px 8px', fontSize: 11, lineHeight: 1.6,
                  whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 200,
                  overflowY: 'auto', background: 'var(--bg)', border: '1px solid var(--line)',
                  borderRadius: 4,
                }}>{txt.output}</pre>
              )}
            </details>
          ))}

          {r.streamed && (
            <details open style={{ marginTop: 6 }}>
              <summary style={{ cursor: 'pointer', color: 'var(--muted)' }}>
                本轮写出的正文（{r.streamed.length} 字）
              </summary>
              <pre style={{
                margin: '4px 0 0', padding: '6px 8px', fontSize: 11, lineHeight: 1.7,
                whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 260,
                overflowY: 'auto', background: 'var(--bg)', border: '1px solid var(--line)',
                borderRadius: 4,
              }}>{r.streamed}</pre>
            </details>
          )}

          {r.checkHit && (
            <p className="muted" style={{ margin: '4px 0 0', lineHeight: 1.55,
                                          display: 'flex', gap: 5 }}>
              <span style={{ flexShrink: 0 }}>⚑</span>
              <span>
                代码判据判了 <b>{r.checkHit.dimension}</b> 不合格，这一轮没再花模型
                调用去打分。{r.checkHit.note}
              </span>
            </p>
          )}

          {r.dropped.length > 0 && (
            <details style={{ marginTop: 4 }}>
              <summary style={{ cursor: 'pointer', color: 'var(--muted)' }}>
                丢弃了 {r.dropped.length} 条修订
                <span className="muted">（防线拦下的，不是出错）</span>
              </summary>
              <ul style={{ listStyle: 'none', padding: 0, margin: '4px 0 0 6px' }}>
                {r.dropped.map((d, i) => (
                  <li key={i} className="muted" style={{ display: 'flex', gap: 5, lineHeight: 1.55 }}>
                    <span style={{ flexShrink: 0 }}>✕</span>
                    <span>{d}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}

          {r.errors.map((e, i) => (
            <p key={i} style={{ margin: '4px 0 0', color: 'var(--del)', lineHeight: 1.55 }}>
              {e}
            </p>
          ))}
        </div>
      ))}
    </div>
  )
}
