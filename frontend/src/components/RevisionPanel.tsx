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

/** 这条修订要动的区间 `[起, 止)`。找不到返回 `[-1, -1]`。
 *
 * anchor 在正文里出现多处时，取**跨度最小**的那一组 (anchor, 其后最近的
 * anchor_end)。这是去重场景的正确语义：
 *
 *     ## 众筹节奏      ← anchor 第一处
 *     三月上旬启动。
 *     ## 众筹节奏      ← anchor 第二处
 *     三月上旬启动众筹。 ← anchor_end
 *
 * 「删掉重复的那一节」给出的就是这一对。从第一处 anchor 往后找 anchor_end
 * 会把两节整个删掉；取最小跨度才落在第二节上。
 *
 * **这段是照着后端 `harness/revision.py` 的 `_locate()` 搬过来的。** 之前
 * 这里只有 `indexOf(anchor)`，跟后端算出的范围不一样——自动应用走后端、
 * 手动点「接受」走这里，同一条去重修订：后端删掉重复的那一节，前端把整篇
 * 笔记删光（实测上面那个例子，前端只剩一个换行）。两份实现同一套语义是
 * 有意的（后端要在没人审核时自动应用，不能指望只跑在浏览器里的那份），
 * 代价就是必须钉住——`scripts/check-revision-parity.mts` 和后端的
 * `tests/test_revision_parity.py` 读同一份用例表。
 */
function locate(content: string, anchor: string, anchorEnd: string): [number, number] {
  let i = content.indexOf(anchor)
  if (i < 0) return [-1, -1]
  if (!anchorEnd) return [i, i + anchor.length]
  const first = i
  let best: [number, number] = [-1, -1]
  while (i >= 0) {
    const j = content.indexOf(anchorEnd, i + anchor.length)
    if (j >= 0) {
      const end = j + anchorEnd.length
      if (best[0] < 0 || end - i < best[1] - best[0]) best = [i, end]
    }
    i = content.indexOf(anchor, i + 1)
  }
  // 结尾标记一次都没匹配上时退回只用 anchor：宁可少改一点，也不要按错误的
  // 范围改，更不要因为一个写错的结尾标记就整条丢弃。
  return best[0] >= 0 ? best : [first, first + anchor.length]
}

export function applyRevision(content: string, r: Revision): string {
  const [i, located] = locate(content, r.anchor, r.anchor_end ?? '')
  if (i < 0) return content // anchor 已被用户改掉，放弃这条
  const end = r.anchor_end && located <= i + r.anchor.length
    ? i + r.anchor.length
    : located
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
