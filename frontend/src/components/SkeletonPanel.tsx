type Props = {
  spine: string
  beats: string[]
  loading: boolean
  onRun: () => void
}

/** 线 1：核心张力（spine）+ 结构节拍（beats）。也是 magic tap 和智能编辑的输入。
 * beats 是这篇东西各部分承担的修辞/叙事功能，不是内容大纲——所以不用 <ol>
 * 编号呈现成待办事项，用带标签的列表强调"这是一个功能位"。 */
export default function SkeletonPanel({ spine, beats, loading, onRun }: Props) {
  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0 }}>写作骨架</h2>
        <button onClick={onRun} disabled={loading}>
          {loading ? <span className="spinner" /> : '生成骨架'}
        </button>
      </div>
      {!spine && beats.length === 0 && !loading && (
        <p className="muted">还没有骨架。生成后会作为智能编辑和续写的主线依据。</p>
      )}
      {spine && (
        <p
          style={{
            margin: '10px 0',
            padding: '10px 12px',
            fontSize: 14,
            fontStyle: 'italic',
            borderLeft: '3px solid var(--accent, #888)',
            background: 'var(--card-alt, rgba(127,127,127,0.08))',
          }}
        >
          {spine}
        </p>
      )}
      {beats.length > 0 && (
        <ul style={{ listStyle: 'none', padding: 0, margin: '8px 0 0' }}>
          {beats.map((b, i) => (
            <li
              key={i}
              className="muted"
              style={{ marginBottom: 6, fontSize: 13, display: 'flex', gap: 6 }}
            >
              <span style={{ opacity: 0.5 }}>·</span>
              <span>{b}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
