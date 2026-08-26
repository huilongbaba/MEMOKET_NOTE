type Props = {
  skeleton: string[]
  loading: boolean
  onRun: () => void
}

/** 线 1：主线逻辑骨架。也是 magic tap 和智能编辑的输入。 */
export default function SkeletonPanel({ skeleton, loading, onRun }: Props) {
  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0 }}>写作骨架</h2>
        <button onClick={onRun} disabled={loading}>
          {loading ? <span className="spinner" /> : '生成骨架'}
        </button>
      </div>
      {skeleton.length === 0 && !loading && (
        <p className="muted">还没有骨架。生成后会作为智能编辑和续写的主线依据。</p>
      )}
      <ol style={{ paddingLeft: 18, margin: '8px 0 0' }}>
        {skeleton.map((s, i) => (
          <li key={i} style={{ marginBottom: 6, fontSize: 13 }}>{s}</li>
        ))}
      </ol>
    </div>
  )
}
