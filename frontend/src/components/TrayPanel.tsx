/**
 * 材料托盘（P14，docs/agent-native-editor.md §3.4）：右栏「记忆」页签顶上的一格。
 *
 * 判据 2「不离开页面就用得上记忆」的另一半：记忆卡是 agent 猜你要什么，托盘是你说「写这篇就用这几篇」。
 * 放进来的东西不进正文——它是材料层：续写 / 智能续写 / `/` 块 / 右键动作取材料时这几条排最前、
 * 不被相关性筛掉、不会滚出材料窗口（后端 `harness/tray.py` 三条规矩）。
 *
 * **不开新页签**（P12 刚把目录和计划合一：右栏页签只能减不能加）——托盘就是「记忆」的第一格。
 * 入口都在别处（记忆卡「放进托盘」、`[[` 链接右键「摊到这篇桌上」、`/` 菜单「从托盘写」），
 * 它们只往 window 发 `tray-add`，这里收、落库、广播 `tray-changed`。
 * 正文永远 `--fg`：材料的标题和摘要是 `--fg`，种类标 / 说明是元信息（灰）。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { deleteTrayItem, listTray, putTray, type TrayItem, type TrayKind } from '../api'
import { clickable } from '../util/clickable'
import { friendlyError } from '../util/friendlyError'
import { moveItem, setTrayCache, TRAY_KIND_ICON, TRAY_KIND_LABEL, TRAY_PREVIEW_CHARS, withItem, alreadyInTray, type TrayAddDetail } from '../util/tray'
import { toast } from '../toast'
import Icon from './Icon'

/** 种类标的类名写成字面量：`check-css-classes` 不认拼出来的类名（P9 被抓过一次） */
const KIND_CLS: Record<TrayKind, string> = { note: 'tray-kind-note', fact: 'tray-kind-fact', import: 'tray-kind-import', selection: 'tray-kind-selection' }

export default function TrayPanel({ noteId, onWrite }: {
  noteId: string
  /** `/` 菜单「从托盘写」的同一件事：在光标处按托盘材料写一块 */
  onWrite?: () => void
}) {
  const [items, setItems] = useState<TrayItem[]>([])
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  const dragFrom = useRef<number | null>(null)
  const [dragOver, setDragOver] = useState<number | null>(null)
  const itemsRef = useRef(items)
  itemsRef.current = items

  const commit = useCallback((next: TrayItem[]) => { setItems(next); setTrayCache(noteId, next) }, [noteId])

  useEffect(() => {
    let alive = true
    setBusy(true)
    listTray(noteId)
      .then((r) => { if (alive) commit(r) })
      .catch((e) => { if (alive) toast('托盘读不出来：' + friendlyError(e), 'error') })
      .finally(() => { if (alive) setBusy(false) })
    return () => { alive = false }
  }, [noteId, commit])

  // 别处说「放进托盘」：这里落库。已在托盘里的说一声、不重复放。
  useEffect(() => {
    const on = (e: Event) => {
      const d = (e as CustomEvent<TrayAddDetail>).detail
      if (d.noteId && d.noteId !== noteId) return
      if (d.kind === 'note' && d.ref_id === noteId) { toast('这篇就是当前这篇，不用摊到自己桌上'); return }
      if (alreadyInTray(itemsRef.current, d)) { toast('已经在托盘里了'); return }
      putTray(noteId, withItem(itemsRef.current, d))
        .then((r) => { commit(r); toast(`已放进托盘（${r.length} 条）`) })
        .catch((err) => toast('放不进托盘：' + friendlyError(err), 'error'))
    }
    window.addEventListener('tray-add', on)
    return () => window.removeEventListener('tray-add', on)
  }, [noteId, commit])

  function reorder(from: number, to: number) {
    const next = moveItem(items, from, to)
    if (next === items) return
    commit(next)                                                     // 先动界面，落库失败再退回
    putTray(noteId, next.map(({ id, kind, ref_id, title, excerpt }) => ({ id, kind, ref_id, title, excerpt })))
      .then(commit)
      .catch((e) => { commit(items); toast('顺序没存上：' + friendlyError(e), 'error') })
  }
  function remove(it: TrayItem) {
    deleteTrayItem(noteId, it.id).then(commit).catch((e) => toast('移不掉：' + friendlyError(e), 'error'))
  }
  function openOriginal(it: TrayItem) {
    if (it.kind === 'note') window.dispatchEvent(new CustomEvent('open-note', { detail: it.ref_id }))
    else if (it.kind === 'fact') window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb:fact:' + it.ref_id }))
    else setOpen((s) => { const n = new Set(s); if (n.has(it.id)) n.delete(it.id); else n.add(it.id); return n })
  }

  return (
    <div className="tray-panel" data-count={items.length}>
      <div className="row tray-head" style={{ alignItems: 'center' }}>
        <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 'var(--s-2)' }}><Icon n="bx-layer-plus" /> 托盘</h2>
        <span className="badge" title="摊在这篇桌上的材料有几条">{items.length}</span>
        {busy && <span className="spinner" />}
        <span style={{ flex: 1 }} />
        {items.length > 0 && onWrite && (
          <button className="tray-write" onClick={onWrite} title="在光标处按托盘里的材料写一段（跟 / 菜单「从托盘写」同一件事）">
            <Icon n="bx-pen" /> 从托盘写
          </button>
        )}
      </div>
      <p className="muted tray-hint">
        摊在桌上的材料：续写、智能续写、<code>/</code> 块、右键动作取材料时，这几条排最前、不被筛掉、不会滚出窗口。
      </p>
      {items.length === 0 && !busy && (
        <p className="muted tray-empty">
          托盘还是空的。下面记忆卡上的「放进托盘」、正文里 <code>[[</code> 链接右键「摊到这篇桌上」都能放进来。
        </p>
      )}
      {items.length > 0 && (
        <ol className="tray-list" aria-label="托盘里的材料">
          {items.map((it, i) => {
            const expanded = open.has(it.id)
            const text = expanded || it.excerpt.length <= TRAY_PREVIEW_CHARS ? it.excerpt : it.excerpt.slice(0, TRAY_PREVIEW_CHARS) + '…'
            return (
              <li key={it.id}
                  className={'tray-item' + (dragOver === i ? ' drag-over' : '')}
                  draggable
                  onDragStart={(e) => { dragFrom.current = i; e.dataTransfer.effectAllowed = 'move' }}
                  onDragOver={(e) => { e.preventDefault(); if (dragOver !== i) setDragOver(i) }}
                  onDragLeave={() => setDragOver((d) => (d === i ? null : d))}
                  onDrop={(e) => { e.preventDefault(); const from = dragFrom.current; dragFrom.current = null; setDragOver(null); if (from !== null) reorder(from, i) }}
                  onDragEnd={() => { dragFrom.current = null; setDragOver(null) }}>
                <span className="tray-handle" title="拖动排序（也可以用右边的上下键）" aria-hidden="true"><Icon n="bx-dots-horizontal-rounded" /></span>
                <div className="tray-body">
                  <div className="row" style={{ gap: 'var(--s-2)', alignItems: 'center' }}>
                    <span className={'badge tray-kind ' + KIND_CLS[it.kind]}><Icon n={TRAY_KIND_ICON[it.kind]} /> {TRAY_KIND_LABEL[it.kind]}</span>
                    {it.title && <span className="tray-title" title={it.title}>{it.title}</span>}
                  </div>
                  {it.excerpt && (
                    <div className="tray-excerpt" title={expanded ? '收起' : '点一下看全文'}
                         {...clickable(() => setOpen((s) => { const n = new Set(s); if (n.has(it.id)) n.delete(it.id); else n.add(it.id); return n }))}>
                      {text}
                    </div>
                  )}
                </div>
                <span className="tray-actions">
                  <button className="icon-btn" title="上移" disabled={i === 0} onClick={() => reorder(i, i - 1)}><Icon n="bx-chevron-up" /></button>
                  <button className="icon-btn" title="下移" disabled={i === items.length - 1} onClick={() => reorder(i, i + 1)}><Icon n="bx-chevron-down" /></button>
                  <button className="icon-btn" title={it.kind === 'note' ? '打开这篇笔记' : it.kind === 'fact' ? '打开这条事实' : expanded ? '收起' : '看全文'}
                          onClick={() => openOriginal(it)}><Icon n="bx-link-external" /></button>
                  <button className="icon-btn" title="从托盘移除（原文不动）" onClick={() => remove(it)}><Icon n="bx-x" /></button>
                </span>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
