import { useEffect, useState } from 'react'
import { friendlyError } from '../util/friendlyError'
import { createNote, digest, memoryScope, SCOPE_LABEL, type MemoryScope, setNoteIcon } from '../api'
import type { Digest } from '../api'
import { toast } from '../toast'
import MarkdownEditor from './MarkdownEditor'

const RANGES = [
  { label: '最近 7 天', days: 7 },
  { label: '最近 30 天', days: 30 },
  { label: '最近 90 天', days: 90 },
]

/**
 * Periodic回顾 -- none of the researched competitors ship this cleanly (see
 * [[memoket_note_memory_editor]] research notes: "resurfacing" is flagged as
 * white space, Roam's version is a community hack). Reuses MarkdownEditor in
 * read-only mode so the generated headings/lists render styled instead of
 * as raw markdown text.
 */
export default function DigestPanel() {
  const [result, setResult] = useState<Digest | null>(null)
  // 记的是"哪个区间在跑"，不是单纯的 boolean——这是个 LLM 调用，不是瞬间
  // 完成，之前三个按钮共用一个 loading 布尔值，点了"最近 7 天"之后三个
  // 按钮会一起转圈，用户分不清自己点的是哪个。
  const [loading, setLoading] = useState<number | null>(null)
  const [scope, setScope] = useState<MemoryScope>(() => memoryScope())
  useEffect(() => {
    const on = (e: Event) => setScope((e as CustomEvent<MemoryScope>).detail)
    window.addEventListener('memory-scope-changed', on)
    return () => window.removeEventListener('memory-scope-changed', on)
  }, [])
  const scopeLabel = scope === 'all' ? '' : SCOPE_LABEL[scope].replace(/^只看/, '')   // 提示里已经有「只看」了，别写成「只看『只看会议记录』」（第 234 轮实拍）
  // 跑的时候页面除了一个转圈什么都没有（第 127 轮实拍）：这是一次几十秒的模型调用，
  // 得告诉人在做什么、已经等了多久
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (loading === null) { setElapsed(0); return }
    const t0 = Date.now()
    const id = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000)
    return () => clearInterval(id)
  }, [loading])

  const [saving, setSaving] = useState(false)
  async function saveAsNote() {
    if (!result) return
    setSaving(true)
    try {
      const title = `回顾 ${result.date_from} ~ ${result.date_to}`
      const body = `# ${title}\n\n> 由「定期回顾」生成 · ${result.fact_count} 条事实\n\n${result.summary.trim()}\n`
      const n = await createNote(title, body)
      await setNoteIcon(n.id, 'bx-history').catch(() => {})     // 回顾生成的笔记带个「历史」图标，树上一眼分得出
      toast('已存为笔记「' + title + '」')
      window.dispatchEvent(new CustomEvent('open-note', { detail: n.id }))
      window.dispatchEvent(new CustomEvent('notes-changed'))
    } catch (e) { toast('存笔记失败：' + friendlyError(e), 'error') }
    finally { setSaving(false) }
  }

  async function run(days: number) {
    setLoading(days)
    try { setResult(await digest(days)) }
    catch (e) { toast('生成回顾失败：' + friendlyError(e), 'error') }
    finally { setLoading(null) }
  }

  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0 }}>阶段回顾</h2>
      </div>
      <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: '4px 0 8px' }}>
        把一段时间的记录汇总成核心结论/关键决定/待跟进——不用自己翻记录找。
        {scopeLabel && <>只看「{scopeLabel}」（范围在右栏「相关记忆」里切）。</>}
      </p>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        {RANGES.map((r) => (
          <button key={r.days} onClick={() => run(r.days)} disabled={loading !== null}
                  title={loading !== null ? `正在汇总最近 ${loading} 天，跑完才能换范围` : undefined}>
            {loading === r.days ? <><span className="spinner" /> {r.label}</> : r.label}
          </button>
        ))}
      </div>
      {loading !== null && (
        <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: '8px 0 0' }}>
          正在把最近 {loading} 天的记录汇总成结论 / 决定 / 待跟进——一次模型调用，通常 20–40 秒 · 已等 {elapsed} 秒
        </p>
      )}
      {result && (
        <div className="card" style={{ marginTop: 8 }}>
          <div className="row" style={{ alignItems: 'center', gap: 8, margin: '0 0 6px' }}>
            <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: 0 }}>
              {result.date_from} ~ {result.date_to} · {result.fact_count} 条事实
            </p>
            <span style={{ flex: 1 }} />
            {/* 回顾是一次性的，关掉页就没了——想留就存成一篇笔记，之后还能续写、引用 */}
            <button className="chip chip-action" disabled={saving || result.fact_count === 0} title={result.fact_count === 0 ? '没有事实，没什么可存的' : undefined} onClick={() => void saveAsNote()}><i className="bx bx-save" /> 存为笔记</button>
          </div>
          <MarkdownEditor content={result.summary} readOnly />
        </div>
      )}
    </div>
  )
}
