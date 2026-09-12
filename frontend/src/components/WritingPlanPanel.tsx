import { useEffect, useState } from 'react'
import { friendlyError } from '../util/friendlyError'
import * as api from '../api'
import type { TreeRow, WritingPlan, WritingSection } from '../api'
import type { HarnessState } from '../App'
import { toast } from '../toast'

const STATUS_LABEL: Record<WritingSection['status'], string> = {
  pending: '⬜ 待写', in_progress: '🔄 写作中', done: '✅ 已完成',
}

/**
 * 子树级别的无限续写 harness 控制台：设定目标 -> 自动拆分段 -> 一段接
 * 一段自动写（每段落成一篇笔记）-> 写完已知分段后自动检查还有没有更多，
 * 没有才真正停。跟笔记级别的 magic tap 是两回事，所以是独立入口，不是
 * 编辑器工具栏里的一个按钮。
 *
 * 运行状态（harness）由 App 持有，不是这个组件自己的 state——关掉这个
 * 面板不会停止正在跑的 harness（回应"必须要写作计划那一页吗？？不能在
 * 后台吗？"），这里只是"看这个状态、控制这个状态"的一个视图。没有活跃
 * harness（或者活跃的是别的文件夹）时，本地拉一份这个文件夹当前的
 * plan/sections 做"静止"展示。
 */
export default function WritingPlanPanel({ parent, onClose, onNoteChanged, harness, onRun, onToggleFollow }: {
  parent: TreeRow
  onClose: () => void
  onNoteChanged: () => void
  harness: HarnessState | null
  onRun: () => void
  onToggleFollow: () => void
}) {
  const [localPlan, setLocalPlan] = useState<WritingPlan | null>(null)
  const [localSections, setLocalSections] = useState<WritingSection[]>([])
  const [goal, setGoal] = useState('')
  const [starting, setStarting] = useState(false)

  const isActive = harness?.folderId === parent.note_id
  const plan = isActive ? harness.plan : localPlan
  const sections = isActive ? harness.sections : localSections
  const running = isActive && harness.running

  useEffect(() => {
    api.getWritingPlan(parent.note_id).then((r) => {
      setLocalPlan(r.plan)
      setLocalSections(r.sections)
    })
  }, [parent.note_id])

  // harness 更新了这个文件夹的 plan/sections（跑起来之后）就同步一份到
  // 本地，这样即使中途关了又重开面板、或者切去另一个文件夹的 harness，
  // 这个文件夹的"静止"视图仍然是最新的，不会退回打开面板那一刻的旧快照。
  useEffect(() => {
    if (isActive && harness) {
      setLocalPlan(harness.plan)
      setLocalSections(harness.sections)
    }
  }, [isActive, harness])

  /** 放弃当前计划，好在同一个文件夹里换个目标重开。
   *
   * 没有这个动作的话，一个文件夹起过计划就再也换不掉：计划状态只有两个来源
   * ——跑完了置 `done`，和这里置 `abandoned`。这个按钮不接的话 `abandoned`
   * 永远不会出现，而上面那个「没有计划就显示表单」的分支也就永远等不到。
   *
   * 已经写出来的笔记**一篇都不动**——放弃的是这份计划，不是它的产出。 */
  async function abandon() {
    if (!plan) return
    if (!window.confirm(`放弃「${plan.goal}」这份计划？已经写出来的笔记会保留，只是不再按这个目标往下写。`)) return
    try {
      await api.abandonWritingPlan(parent.note_id)
      setLocalPlan({ ...plan, status: 'abandoned' })
      setLocalSections([])
      setGoal('')
      onNoteChanged()
    } catch (e) {
      toast('放弃计划失败：' + friendlyError(e), 'error')
    }
  }

  async function start() {
    if (!goal.trim()) return
    setStarting(true)
    try {
      const r = await api.startWritingPlan(parent.note_id, goal.trim())
      setLocalPlan(r.plan)
      setLocalSections(r.sections)
      onNoteChanged()
    } catch (e) {
      toast('生成写作计划失败：' + friendlyError(e), 'error')
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div
        className="modal"
        style={{ background: 'var(--bg)', border: '1px solid var(--line)', borderRadius: 10,
                maxWidth: 640, width: '90vw', maxHeight: '80vh', overflowY: 'auto', padding: 24 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2 style={{ margin: 0 }}><i className="bx bx-rocket" /> <span className="plain-case">{parent.title}</span> · 写作计划</h2>
          <button onClick={onClose}>✕</button>
        </div>

        {!plan || plan.status === 'abandoned' ? (
          <div className="stack" style={{ marginTop: 12 }}>
            <p className="muted" style={{ fontSize: 13 }}>
              给一个写作目标，会自动拆成若干分段，每个分段独立成一篇笔记，一段接一段自动写下去；
              写完已知分段后还会检查有没有更多值得写的内容，没有才真正停下来。
            </p>
            <textarea
              rows={3}
              placeholder="比如：梳理 XX 项目从技术方案到上线计划的完整推进思路"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
            />
            <button className="primary" onClick={start} disabled={starting || !goal.trim()}>
              {starting ? <span className="spinner" /> : '生成写作计划'}
            </button>
          </div>
        ) : (
          <div className="stack" style={{ marginTop: 12 }}>
            <p className="muted" style={{ fontSize: 13 }}>{plan.goal}</p>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <span className={'badge' + (plan.status === 'done' ? ' ok' : '')}>
                {plan.status === 'done' ? '已完成' : '进行中'}
              </span>
              <div className="row" style={{ gap: 6 }}>
                {/* nowrap 同 App.tsx 那个「逐轮我来定」：中文在 flex 行里能被
                    压到一个字一行，这个面板更窄，更容易中招。 */}
                {running && (
                  <label className="muted"
                         style={{ fontSize: 12, cursor: 'pointer',
                                  whiteSpace: 'nowrap', flexShrink: 0 }}>
                    <input type="checkbox" checked={harness.follow} onChange={onToggleFollow} style={{ marginRight: 4 }} />
                    编辑器跟随写作
                  </label>
                )}
                {plan.status === 'active' && (
                  <button
                    className="primary"
                    onClick={onRun}
                    disabled={!!harness?.running && !running}
                    title={!!harness?.running && !running ? `「${harness.folderName}」正在跑，先停掉那边才能开始这个` : undefined}
                  >
                    {running ? '■ 停止' : '▶ 继续写'}
                  </button>
                )}
                {!running && (
                  <button onClick={abandon} title="换个目标重开。已经写出来的笔记会保留">
                    换个目标
                  </button>
                )}
              </div>
            </div>

            {/* 固定在顶部、不用滚动找——之前流式预览是嵌在对应 section 卡片
               里的一小块灰字，如果 harness 已经推进到列表靠后的分段，用户
               看着列表靠前的部分就完全看不到任何变化，反馈直接说"看不到
               进展"。这块不管当前在写哪个分段，位置永远不变，字号和对比度
               也高得多——一眼就能看出"正在写"还是"卡住了"。 */}
            {running && (
              <div className="card" style={{ background: 'var(--panel)' }}>
                <div className="row" style={{ gap: 6 }}>
                  <span className="spinner" />
                  <strong style={{ fontSize: 13 }}>
                    {harness.currentSectionTitle ? `正在写：${harness.currentSectionTitle}` : '正在启动…'}
                  </strong>
                </div>
                {harness.waitingFirstToken ? (
                  <p className="muted" style={{ fontSize: 12, margin: '6px 0 0' }}>
                    检索知识库、启动模型中…（本地模型这一步通常要几秒）
                  </p>
                ) : (
                  <div style={{ fontSize: 13, marginTop: 8, whiteSpace: 'pre-wrap',
                               maxHeight: 220, overflowY: 'auto' }}>
                    {harness.preview || '…'}
                  </div>
                )}
              </div>
            )}

            <div className="stack" style={{ marginTop: 8 }}>
              {sections.map((s) => (
                <div key={s.id} className="card">
                  <div>{STATUS_LABEL[s.status]} <strong>{s.title}</strong></div>
                  {s.summary && (
                    <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{s.summary}</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
