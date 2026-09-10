type Props = {
  spine: string
  beats: string[]
  /** 智能续写每轮跑一次 writer_harness.evaluate() 之后的整体节拍覆盖打分
   * （0/1/2，note 是模型给的一句话说明）——null 表示还没跑过一次评分
   * （骨架刚生成、或者用的是 magic tap 不是智能续写）。这是一次聚合打分，
   * 不是逐条节拍的覆盖列表：之前有过基于 beats_coverage_user() 的逐条
   * 核对，现在这个判断吸收进统一的原则打分闭环（见
   * writer_harness/README.md），换来的代价是节拍列表本身不再单独标记
   * 每一条的勾选状态，用聚合分数 + 一句话说明代替。 */
  beatCoverage: { level: number; note: string } | null
  loading: boolean
  onRun: () => void
}

const LEVEL_LABEL: Record<number, string> = { 0: '还不够', 1: '部分覆盖', 2: '已覆盖' }
const LEVEL_COLOR: Record<number, string> = { 0: 'var(--del)', 1: 'var(--warn)', 2: 'var(--ins)' }

/** 线 1：核心张力（spine）+ 结构节拍（beats）。也是 magic tap 和智能编辑的输入。
 * beats 是这篇东西各部分承担的修辞/叙事功能，不是内容大纲——所以不用 <ol>
 * 编号呈现成待办事项，用带标签的列表强调"这是一个功能位"。 */
export default function SkeletonPanel({ spine, beats, beatCoverage, loading, onRun }: Props) {
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
            <li key={i} style={{ marginBottom: 6, fontSize: 13, display: 'flex', gap: 6 }}>
              <span className="muted">·</span>
              <span>{b}</span>
            </li>
          ))}
        </ul>
      )}
      {beatCoverage && (
        <p style={{ marginTop: 8, fontSize: 12, display: 'flex', gap: 6, alignItems: 'baseline' }}>
          <span style={{ color: LEVEL_COLOR[beatCoverage.level], fontWeight: 600 }}>
            节拍覆盖：{LEVEL_LABEL[beatCoverage.level] ?? beatCoverage.level}
          </span>
          <span className="muted">{beatCoverage.note}</span>
        </p>
      )}
    </div>
  )
}
