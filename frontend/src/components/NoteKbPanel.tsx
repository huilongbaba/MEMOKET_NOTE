/**
 * ribbon 里的「知识库」标签：**这篇笔记跟知识库的全部关系，一处看全**。
 * 设计见 docs/kb-fusion-design.md §3.4。
 *
 * 三件事：引用了哪几条（每条可 peek）、摄入过没有、有没有引用了**已经不存在**
 * 的事实——最后这条是真问题（模型编的、或者知识库重建过 id 变了），藏起来
 * 等于让一篇笔记建立在不存在的依据上。
 */
import { useEffect, useState } from 'react'
import { fmtDate } from '../util/time'

import { addFact, deleteFact, factPeek, noteKb, notesCiting, updateFact, type CitingNote, type FactPeek, type NoteKb, type TreeRow } from '../api'
import { displayTitle } from '../util/displayTitle'
import { toast } from '../toast'

export default function NoteKbPanel({ citedIds, row, noteId, onIngest, onSync, ingesting, onOpenNote, refreshTick = 0 }: {
  citedIds: string[]
  row: TreeRow | undefined
  noteId: string
  onIngest: () => void
  /** 同步：服务端读最新正文，删旧 session 重抽（手工加的事实留着） */
  onSync: () => void
  ingesting: boolean
  onOpenNote: (id: string) => void
  /** 摄入 / 同步跑完 +1，贡献列表重拉 */
  refreshTick?: number
}) {
  // 这篇贡献了哪些事实 + 改过没同步。摄入过的才查；跑完摄入再查一次。
  const [kb, setKb] = useState<NoteKb | null>(null)
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null)
  const [adding, setAdding] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    setKb(null)
    noteKb(noteId).then((k) => { if (alive) setKb(k) }).catch(() => {})
    return () => { alive = false }
  }, [noteId, refreshTick, row?.ingested_at])

  async function saveEdit() {
    if (!editing) return
    const text = editing.text.trim()
    if (!text) { setEditing(null); return }
    try {
      const f = await updateFact(editing.id, text)
      setKb((k) => (k ? { ...k, facts: k.facts.map((x) => (x.id === f.id ? { ...x, text: f.text } : x)) } : k))
      setEditing(null)
    } catch (e) { toast('改不了：' + String(e), 'error') }
  }
  async function remove(id: string) {
    try {
      await deleteFact(id)
      setKb((k) => (k ? { ...k, facts: k.facts.filter((x) => x.id !== id) } : k))
    } catch (e) { toast('删不了：' + String(e), 'error') }
  }
  async function saveAdd() {
    const text = (adding ?? '').trim()
    if (!text) { setAdding(null); return }
    try {
      const f = await addFact(noteId, text)
      setKb((k) => (k ? { ...k, ingested_at: k.ingested_at || new Date().toISOString(), facts: [...k.facts, f] } : k))
      setAdding(null)
    } catch (e) { toast('加不上：' + String(e), 'error') }
  }

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
          ? <span className="muted">⇡ 已摄入知识库 · {fmtDate(row.ingested_at)}</span>
          : <span className="muted">还没摄入知识库</span>}
        {row?.ingested_at
          ? <button onClick={onSync} disabled={ingesting} style={{ marginInlineStart: 'auto' }} title="服务端读最新正文，删掉上次抽出来的事实重新抽；你手工加的留着">
              {ingesting ? <span className="spinner" /> : (kb?.stale ? '同步到知识库' : '重新同步')}
            </button>
          : <button onClick={onIngest} disabled={ingesting} style={{ marginInlineStart: 'auto' }}>
              {ingesting ? <span className="spinner" /> : '📥 存入知识库'}
            </button>}
      </div>
      {kb?.stale && !ingesting && (
        // 改过没同步要醒目：树上的 ⇡ 也会变黄。自动同步开着的话过一会儿会自己跑。
        <div className="card" style={{ borderColor: 'var(--warn)', color: 'var(--warn)', padding: '6px 8px' }}>
          笔记在 {fmtDate(kb.ingested_at)} 摄入之后又改过，知识库里还是旧版——点「同步到知识库」，或在设置里打开自动同步。
        </div>
      )}

      {/* 这篇贡献的事实：可改、可删、可补。抽取器抽错了改一下，比重新摄入省一次模型调用。 */}
      {row?.ingested_at && (
        <div className="stack" style={{ gap: 6 }}>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
            <strong style={{ fontSize: 12 }}>这篇贡献的事实{kb ? ` · ${kb.facts.length} 条` : ''}</strong>
            {adding === null && <button onClick={() => setAdding('')} style={{ fontSize: 12, padding: '2px 8px' }}>＋ 补一条</button>}
          </div>
          {adding !== null && (
            <div className="stack" style={{ gap: 4 }}>
              <textarea rows={2} value={adding} autoFocus placeholder="一句话说清一件事（谁、什么时候、什么）"
                        onChange={(e) => setAdding(e.target.value)} />
              <div className="row" style={{ gap: 6 }}>
                <button className="primary" onClick={() => void saveAdd()} style={{ fontSize: 12, padding: '2px 10px' }}>加上</button>
                <button onClick={() => setAdding(null)} style={{ fontSize: 12, padding: '2px 10px' }}>算了</button>
              </div>
            </div>
          )}
          {kb === null && <p className="muted" style={{ margin: 0, fontSize: 12 }}><span className="spinner" /> 在查…</p>}
          {kb && kb.facts.length === 0 && <p className="muted" style={{ margin: 0, fontSize: 12 }}>这篇摄入时没抽出可记的事实。</p>}
          {kb?.facts.map((f) => (
            <div key={f.id} className="card" style={{ padding: '6px 8px' }}>
              {editing?.id === f.id ? (
                <div className="stack" style={{ gap: 4 }}>
                  <textarea rows={2} value={editing.text} autoFocus onChange={(e) => setEditing({ id: f.id, text: e.target.value })} />
                  <div className="row" style={{ gap: 6 }}>
                    <button className="primary" onClick={() => void saveEdit()} style={{ fontSize: 12, padding: '2px 10px' }}>保存</button>
                    <button onClick={() => setEditing(null)} style={{ fontSize: 12, padding: '2px 10px' }}>取消</button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="row" style={{ gap: 6, alignItems: 'flex-start' }}>
                    <div style={{ flex: 1, minWidth: 0 }}>{f.text}</div>
                    <button className="icon-btn" title="改" onClick={() => setEditing({ id: f.id, text: f.text })}><i className="bx bx-edit-alt" /></button>
                    <button className="icon-btn" title="从知识库删掉这条" onClick={() => void remove(f.id)}><i className="bx bx-x" /></button>
                  </div>
                  <div className="muted" style={{ fontSize: 11 }}>
                    {f.when || '—'}{f.who ? ` · ${f.who}` : ''}{f.kind ? ` · ${f.kind}` : ''}{f.manual ? ' · 手工加的' : ''}
                    <code style={{ fontSize: 10, marginInlineStart: 6 }}>[{f.id}]</code>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}

      {missing.length > 0 && (
        // **找不到的要醒目。** 这是一篇笔记建立在不存在的依据上。
        <div className="card" style={{ borderColor: 'var(--del)', color: 'var(--del)' }}>
          {/* 只列前 8 个：300 条找不到时（实拍造的长文）整块红字把面板撑满一屏 */}
          {missing.length} 条引用在知识库里找不到：{missing.slice(0, 8).join('、')}{missing.length > 8 ? `…还有 ${missing.length - 8} 个` : ''}
          <div className="muted" style={{ fontSize: 12 }}>可能是引用写错了，或者知识库重建过</div>
        </div>
      )}

      <strong style={{ fontSize: 12 }}>这篇引用的事实{citedIds.length ? ` · ${citedIds.length} 条` : ''}</strong>
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
