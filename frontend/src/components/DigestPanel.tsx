import { useState } from 'react'
import { digest } from '../api'
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

  async function run(days: number) {
    setLoading(days)
    try { setResult(await digest(days)) }
    catch (e) { toast('生成回顾失败：' + e, 'error') }
    finally { setLoading(null) }
  }

  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0 }}>阶段回顾</h2>
      </div>
      <p className="muted" style={{ fontSize: 12, margin: '4px 0 8px' }}>
        把一段时间的记录汇总成核心结论/关键决定/待跟进——不用自己翻记录找。
      </p>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        {RANGES.map((r) => (
          <button key={r.days} onClick={() => run(r.days)} disabled={loading !== null}>
            {loading === r.days ? <span className="spinner" /> : r.label}
          </button>
        ))}
      </div>
      {result && (
        <div className="card" style={{ marginTop: 8 }}>
          <p className="muted" style={{ fontSize: 12, margin: '0 0 6px' }}>
            {result.date_from} ~ {result.date_to} · {result.fact_count} 条事实
          </p>
          <MarkdownEditor content={result.summary} readOnly />
        </div>
      )}
    </div>
  )
}
