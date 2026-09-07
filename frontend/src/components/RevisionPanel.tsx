import { useMemo } from 'react'
import type { Revision } from '../api'

/**
 * track-changes 面板。
 *
 * 修订是 anchor 锚定的（后端保证 anchor 逐字出现在正文里），所以接受一条
 * 修订就是在正文里做一次字符串替换 —— 不需要富文本编辑器的 diff 引擎。
 * 用户不接受就什么都不动，原始输入永远不会被模型直接覆盖。
 */

type Props = {
  revisions: Revision[]
  content: string
  loading: boolean
  onAccept: (r: Revision) => void
  onReject: (r: Revision) => void
  onRun: () => void
}

function applyPreview(content: string, r: Revision): { before: string; after: string } {
  const i = content.indexOf(r.anchor)
  if (i < 0) return { before: r.anchor, after: r.text }
  if (r.op === 'insert') return { before: r.anchor, after: r.anchor + r.text }
  if (r.op === 'insert_before') return { before: r.anchor, after: r.text + r.anchor }
  if (r.op === 'delete') return { before: r.anchor, after: '' }
  return { before: r.anchor, after: r.text }
}

export function applyRevision(content: string, r: Revision): string {
  const i = content.indexOf(r.anchor)
  if (i < 0) return content // anchor 已被用户改掉，放弃这条
  let end = i + r.anchor.length
  if (r.anchor_end) {
    // 给了结尾标记：要动的是"起始标记开头 → 结尾标记结尾"这一整段。
    // **必须跟后端 _apply_revision 保持同一套语义**——自动应用走后端、
    // 手动点接受走这里，两边算出不同的范围就会让同一条修订产生两种结果。
    // 找不到结尾标记就退回只用 anchor，宁可少改一点也不要按错误范围改。
    const j = content.indexOf(r.anchor_end, end)
    if (j >= 0) end = j + r.anchor_end.length
  }
  if (r.op === 'insert') return content.slice(0, end) + r.text + content.slice(end)
  if (r.op === 'insert_before') return content.slice(0, i) + r.text + content.slice(i)
  if (r.op === 'delete') return content.slice(0, i) + content.slice(end)
  return content.slice(0, i) + r.text + content.slice(end)
}

export default function RevisionPanel({
  revisions, content, loading, onAccept, onReject, onRun,
}: Props) {
  // anchor 找不到的修订不该显示 —— 用户已经改动了那段文字
  const live = useMemo(
    () => revisions.filter((r) => !r.anchor || content.includes(r.anchor)),
    [revisions, content],
  )

  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0 }}>智能编辑</h2>
        <button onClick={onRun} disabled={loading}>
          {loading ? <span className="spinner" /> : '生成修订'}
        </button>
      </div>

      {!loading && live.length === 0 && (
        <p className="muted">暂无修订建议。点「生成修订」让模型对照骨架和知识库检查正文。</p>
      )}

      {live.map((r) => {
        const p = applyPreview(content, r)
        return (
          <div className="card" key={r.id}>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <span className="badge">{r.op}</span>
              <div className="row">
                <button onClick={() => onAccept(r)}>接受</button>
                <button onClick={() => onReject(r)}>拒绝</button>
              </div>
            </div>

            <div style={{ marginTop: 8 }}>
              {r.op !== 'insert' && r.op !== 'insert_before' && <div><span className="del">{p.before}</span></div>}
              {r.op !== 'delete' && <div><span className="ins">{r.text}</span></div>}
            </div>

            {r.reason && <p className="muted" style={{ margin: '8px 0 0' }}>{r.reason}</p>}
            {r.sources.length > 0 && (
              <p className="muted" style={{ margin: '4px 0 0' }}>
                依据：{r.sources.join('；')}
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}
