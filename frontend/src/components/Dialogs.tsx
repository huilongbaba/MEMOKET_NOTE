/**
 * 应用内的小对话框——替掉 `window.prompt`。
 *
 * 为什么不能继续用 prompt：在 Electron 里它是**系统级模态**，样式完全不受
 * 主题控制；而「移动到…」那个 prompt 把整棵树拍平成编号列表让用户输序号，
 * 笔记上百篇之后会长到滚不动。Trilium 的对应物是 `dialogs/{item_picker,
 * move_to, clone_to, branch_prefix}.tsx`——带搜索的选择器。
 */
import { useEffect, useMemo, useRef, useState } from 'react'

import { ROOT_ID, isVirtualId, type TreeRow } from '../api'
import { displayTitle } from '../util/displayTitle'

// ------------------------------------------------------------ 选一个节点

export type PickerRequest = {
  title: string
  /** 不能选的（自己和自己的子树——选了会成环） */
  exclude: Set<string>
  resolve: (noteId: string | null) => void
}

export function NotePicker({ req, rows }: { req: PickerRequest; rows: TreeRow[] }) {
  const [q, setQ] = useState('')
  const [i, setI] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => { input.current?.focus() }, [])

  // 路径给用户认位置：克隆之后同名笔记会出现在多处，光看标题分不清
  const paths = useMemo(() => {
    const byId = new Map<string, TreeRow>()
    for (const r of rows) if (!byId.has(r.note_id)) byId.set(r.note_id, r)
    const of = (r: TreeRow): string => {
      const parts: string[] = []
      let cur: TreeRow | undefined = byId.get(r.parent_note_id)
      let guard = 0
      while (cur && guard++ < 50) { parts.unshift(displayTitle(cur)); cur = byId.get(cur.parent_note_id) }
      return parts.join(' / ')
    }
    return new Map(rows.map((r) => [r.id, of(r)]))
  }, [rows])

  const items = useMemo(() => {
    const seen = new Set<string>()
    const list = rows.filter((r) => !isVirtualId(r.note_id) && !req.exclude.has(r.note_id)
      && !seen.has(r.note_id) && seen.add(r.note_id))
    const needle = q.trim().toLowerCase()
    const hit = needle
      ? list.filter((r) => (displayTitle(r) + ' ' + (paths.get(r.id) ?? '')).toLowerCase().includes(needle))
      : list
    return [{ id: 'root', note_id: ROOT_ID, label: '（树根）', path: '' },
            ...hit.slice(0, 200).map((r) => ({ id: r.id, note_id: r.note_id, label: displayTitle(r), path: paths.get(r.id) ?? '' }))]
  }, [rows, q, req.exclude, paths])

  const choose = (k: number) => { const it = items[k]; if (it) req.resolve(it.note_id) }

  return (
    <div className="palette-backdrop" onMouseDown={() => req.resolve(null)}>
      <div className="palette" role="dialog" onMouseDown={(e) => e.stopPropagation()}>
        <div className="muted" style={{ fontSize: 12, padding: '2px 4px 6px' }}>{req.title}</div>
        <input
          ref={input} value={q} placeholder="搜标题或路径…"
          onChange={(e) => { setQ(e.target.value); setI(0) }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setI((v) => Math.min(v + 1, items.length - 1)) }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setI((v) => Math.max(v - 1, 0)) }
            else if (e.key === 'Enter') { e.preventDefault(); choose(i) }
            else if (e.key === 'Escape') { e.preventDefault(); req.resolve(null) }
          }}
        />
        <div className="palette-list">
          {items.map((it, k) => (
            <div key={it.id} className={'palette-item' + (k === i ? ' active' : '')}
                 onMouseEnter={() => setI(k)} onClick={() => choose(k)}>
              {it.label}
              {it.path && <span className="muted" style={{ marginInlineStart: 8, fontSize: 12 }}>{it.path}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ------------------------------------------------------------ 输一行字

export type PromptRequest = {
  title: string
  initial: string
  resolve: (value: string | null) => void
}

export function TextPrompt({ req }: { req: PromptRequest }) {
  const [v, setV] = useState(req.initial)
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => { input.current?.focus(); input.current?.select() }, [])
  return (
    <div className="palette-backdrop" onMouseDown={() => req.resolve(null)}>
      <div className="palette" role="dialog" style={{ width: 420 }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="muted" style={{ fontSize: 12, padding: '2px 4px 6px' }}>{req.title}</div>
        <input
          ref={input} value={v} onChange={(e) => setV(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); req.resolve(v) }
            else if (e.key === 'Escape') { e.preventDefault(); req.resolve(null) }
          }}
        />
        <div className="row" style={{ justifyContent: 'flex-end', gap: 6, marginTop: 8 }}>
          <button onClick={() => req.resolve(null)}>取消</button>
          <button className="primary" onClick={() => req.resolve(v)}>确定</button>
        </div>
      </div>
    </div>
  )
}


// ------------------------------------------------------------ 确认一下

export type ConfirmRequest = {
  title: string
  detail?: string
  okLabel?: string
  danger?: boolean
  resolve: (ok: boolean) => void
}

/** 只给**看不见后果**的动作用（删一棵子树会连带删掉看不见的东西）。单篇
 *  删除走的是乐观删除 + 撤销，比确认框好——别把这个用滥了。 */
export function ConfirmDialog({ req }: { req: ConfirmRequest }) {
  const btn = useRef<HTMLButtonElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  // 危险操作（删整棵子树）默认焦点放在「取消」上：顺手一个回车不该删掉几十篇。
  // 普通确认才把焦点给确定键。
  useEffect(() => { (req.danger ? cancel : btn).current?.focus() }, [req.danger])
  return (
    <div className="palette-backdrop" onMouseDown={() => req.resolve(false)}>
      <div className="palette" role="alertdialog" style={{ width: 440 }} onMouseDown={(e) => e.stopPropagation()}
           onKeyDown={(e) => { if (e.key === 'Escape') req.resolve(false) }}>
        <div style={{ fontWeight: 600, padding: '2px 4px 4px' }}>{req.title}</div>
        {req.detail && <div className="muted" style={{ fontSize: 13, padding: '0 4px 8px', whiteSpace: 'pre-wrap' }}>{req.detail}</div>}
        <div className="row" style={{ justifyContent: 'flex-end', gap: 6, marginTop: 8 }}>
          <button ref={cancel} onClick={() => req.resolve(false)}>取消</button>
          <button ref={btn} className="primary" style={req.danger ? { background: 'var(--del)', borderColor: 'var(--del)' } : undefined}
                  onClick={() => req.resolve(true)}>{req.okLabel ?? '确定'}</button>
        </div>
      </div>
    </div>
  )
}
