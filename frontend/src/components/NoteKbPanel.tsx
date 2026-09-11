/**
 * ribbon 里的「知识库」标签：**这篇笔记跟知识库的全部关系，一处看全**。
 * 设计见 docs/kb-fusion-design.md §3.4。
 *
 * 三件事：引用了哪几条（每条可 peek）、摄入过没有、有没有引用了**已经不存在**
 * 的事实——最后这条是真问题（模型编的、或者知识库重建过 id 变了），藏起来
 * 等于让一篇笔记建立在不存在的依据上。
 */
import { useEffect, useState } from 'react'

import { factPeek, notesCiting, type CitingNote, type FactPeek, type TreeRow } from '../api'
import { displayTitle } from '../util/displayTitle'

export default function NoteKbPanel({ citedIds, row, noteId, onIngest, ingesting, onOpenNote }: {
  citedIds: string[]
  row: TreeRow | undefined
  noteId: string
  onIngest: () => void
  ingesting: boolean
  onOpenNote: (id: string) => void
}) {
  // 反向链接：同一条依据还被哪几篇引用。Trilium 的 Backlinks 是「谁链到我」，
  // 这里的问法是「跟我共享证据的是谁」——对笔记工具来说这才是有用的邻居。
  const [citing, setCiting] = useState<Record<string, CitingNote[]>>({})
  // null = 查过了但不存在；undefined = 还没查
  const [facts, setFacts] = useState<Record<string, FactPeek | null | undefined>>({})

  useEffect(() => {
    let alive = true
    for (const id of citedIds) {
      if (facts[id] !== undefined) continue
      void factPeek(id).then((f) => { if (alive) setFacts((m) => ({ ...m, [id]: f })) })
      void notesCiting(id).then((ns) => { if (alive) setCiting((m) => ({ ...m, [id]: ns })) })
    }
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [citedIds])

  const missing = citedIds.filter((id) => facts[id] === null)

  return (
    <div className="stack" style={{ fontSize: 13 }}>
      <div className="row" style={{ gap: 8, alignItems: 'center' }}>
        {row?.ingested_at
          ? <span className="muted">⇡ 已摄入知识库 · {row.ingested_at.slice(0, 10)}</span>
          : <span className="muted">还没摄入知识库</span>}
        <button onClick={onIngest} disabled={ingesting} style={{ marginInlineStart: 'auto' }}>
          {ingesting ? <span className="spinner" /> : (row?.ingested_at ? '重新摄入' : '📥 存入知识库')}
        </button>
      </div>

      {missing.length > 0 && (
        // **找不到的要醒目。** 这是一篇笔记建立在不存在的依据上。
        <div className="card" style={{ borderColor: 'var(--del)', color: 'var(--del)' }}>
          {missing.length} 条引用在知识库里找不到：{missing.join('、')}
          <div className="muted" style={{ fontSize: 12 }}>可能是引用写错了，或者知识库重建过</div>
        </div>
      )}

      {citedIds.length === 0
        ? <p className="muted" style={{ margin: 0 }}>这篇还没有引用知识库里的记录。续写和「来龙去脉」插入的内容会自动带上引用。</p>
        : citedIds.map((id) => {
          const f = facts[id]
          return (
            <div key={id} className="card" style={{ padding: '6px 8px' }}>
              <div className="muted" style={{ fontSize: 11 }}>
                {f ? `${f.when} · ${f.kind}` : id}
              </div>
              <div>{f === undefined ? '…' : f === null ? '（找不到）' : f.text}</div>
              {(citing[id] ?? []).filter((n) => n.id !== noteId).length > 0 && (
                <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                  也引用于：
                  {(citing[id] ?? []).filter((n) => n.id !== noteId).map((n) => (
                    <a key={n.id} href="#" onClick={(e) => { e.preventDefault(); onOpenNote(n.id) }}
                       style={{ marginInlineStart: 6 }}>{displayTitle(n)}</a>
                  ))}
                </div>
              )}
            </div>
          )
        })}
    </div>
  )
}
