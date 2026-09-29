import { useEffect, useId, useRef, useState } from 'react'
import { getUser } from '../api'
import type { DesktopBridge } from '../desktop'
import Icon from './Icon'
import '../quick-capture.css'

type Draft = { title: string; content: string }
type DraftSession = Draft & { key: string; restored: boolean; storageError: string }

function readDraft(): DraftSession {
  let key = 'memoket.quick-capture.anonymous'
  try {
    key = `memoket.quick-capture.${encodeURIComponent(getUser())}`
    const raw = localStorage.getItem(key)
    if (!raw) return { key, title: '', content: '', restored: false, storageError: '' }
    const value: unknown = JSON.parse(raw)
    if (!value || typeof value !== 'object') throw new Error('Invalid draft')
    const draft = value as Partial<Draft>
    const title = typeof draft.title === 'string' ? draft.title : ''
    const content = typeof draft.content === 'string' ? draft.content : ''
    return { key, title, content, restored: !!(title || content), storageError: '' }
  } catch {
    return { key, title: '', content: '', restored: false, storageError: '无法读取本机草稿。请在关闭前保存笔记。' }
  }
}

export default function QuickCapture({ onClose, onSave }: {
  onClose: () => void
  onSave: (title: string, content: string) => Promise<void>
}) {
  const [session] = useState(readDraft)
  const [title, setTitle] = useState(session.title)
  const [content, setContent] = useState(session.content)
  const [error, setError] = useState('')
  const [storageError, setStorageError] = useState(session.storageError)
  const [saving, setSaving] = useState(false)
  const [pasting, setPasting] = useState(false)
  const [shortcut, setShortcut] = useState<string>('')
  const [restored, setRestored] = useState(session.restored)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const bodyRef = useRef<HTMLTextAreaElement>(null)
  const draftRef = useRef<Draft>({ title: session.title, content: session.content })
  const busyRef = useRef(false)
  const clipboardBusyRef = useRef(false)
  const mountedRef = useRef(false)
  const titleId = useId()
  const descriptionId = useId()
  const modifier = /Mac/.test(navigator.platform) ? '⌘' : 'Ctrl'
  const bridge: DesktopBridge | undefined = window.memoketDesktop

  useEffect(() => {
    mountedRef.current = true
    const dialog = dialogRef.current
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (dialog && !dialog.open) dialog.showModal()
    bodyRef.current?.focus()
    return () => {
      mountedRef.current = false
      dialog?.close()
      if (previousFocus?.isConnected) previousFocus.focus()
    }
  }, [])

  useEffect(() => {
    let active = true
    if (!bridge?.quickCapture) {
      setShortcut('浏览器内快捷捕捉')
      return
    }
    void bridge.quickCapture.status().then((status) => {
      if (!active) return
      setShortcut(status.registered ? '全局快捷键已开启' : (status.reason || '全局快捷键不可用，仍可在应用内捕捉。'))
    }).catch(() => {
      if (active) setShortcut('无法确认全局快捷键状态，仍可在应用内捕捉。')
    })
    return () => { active = false }
  }, [bridge])

  function updateDraft(draft: Draft) {
    draftRef.current = draft
    setTitle(draft.title)
    setContent(draft.content)
    setRestored(false)
    try {
      if (draft.title || draft.content) localStorage.setItem(session.key, JSON.stringify(draft))
      else localStorage.removeItem(session.key)
      setStorageError('')
    } catch {
      setStorageError('无法保存本机草稿。请在关闭前保存笔记。')
    }
  }

  async function save() {
    if (busyRef.current || clipboardBusyRef.current) return
    const draft = draftRef.current
    if (!draft.title.trim() && !draft.content.trim()) {
      setError('先写下一点内容，再保存。')
      bodyRef.current?.focus()
      return
    }
    busyRef.current = true
    setSaving(true)
    setError('')
    try {
      const noteTitle = draft.title.trim() || draft.content.trim().split('\n')[0].replace(/^#+\s*/, '').slice(0, 80) || '快速捕捉'
      await onSave(noteTitle, draft.content)
      try { localStorage.removeItem(session.key) } catch { /* The note has already been saved. */ }
      if (mountedRef.current) onClose()
    } catch (e) {
      if (mountedRef.current) setError(`保存失败，文字已保留。${e instanceof Error ? e.message : '请重试。'}`)
    } finally {
      busyRef.current = false
      if (mountedRef.current) setSaving(false)
    }
  }

  async function pasteClipboard() {
    if (clipboardBusyRef.current || busyRef.current) return
    clipboardBusyRef.current = true
    setPasting(true)
    setError('')
    try {
      const text = bridge?.quickCapture
        ? await bridge.quickCapture.readClipboard()
        : await navigator.clipboard.readText()
      if (!mountedRef.current) return
      if (!text.trim()) {
        setError('剪贴板里没有文字。可以直接输入，或先复制文字再粘贴。')
        return
      }
      const draft = draftRef.current
      updateDraft({ ...draft, content: draft.content ? `${draft.content}\n\n${text}` : text })
      bodyRef.current?.focus()
    } catch {
      if (mountedRef.current) setError(`无法读取剪贴板。请点击正文区域，按 ${modifier}V 粘贴。`)
    } finally {
      clipboardBusyRef.current = false
      if (mountedRef.current) setPasting(false)
    }
  }

  return (
    <dialog ref={dialogRef} className="ws-capture" aria-labelledby={titleId} aria-describedby={descriptionId}
      onCancel={(e) => { e.preventDefault(); if (!busyRef.current) onClose() }}
      onKeyDown={(e) => {
        // Keep application-wide shortcuts from affecting the page behind a modal.
        e.stopPropagation()
        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && !e.nativeEvent.isComposing) {
          e.preventDefault()
          void save()
        }
        if (e.key === 'Tab') {
          const controls = dialogRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), [tabindex="0"]')
          if (!controls?.length) return
          const first = controls[0]
          const last = controls[controls.length - 1]
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
        }
      }}>
      <form onSubmit={(e) => { e.preventDefault(); void save() }}>
        <header className="ws-capture-header">
          <span className="ws-capture-mark"><Icon n="bx-edit-alt" /></span>
          <span className="ws-capture-eyebrow">QUICK CAPTURE</span>
          <button className="ws-capture-close" type="button" aria-label="关闭快速捕捉" title="关闭，保留本机草稿 · Esc"
            disabled={saving} onClick={onClose}><Icon n="bx-x" /></button>
        </header>
        <div className="ws-capture-intro">
          <h2 id={titleId}>先记下来。</h2>
          <p id={descriptionId}>想法、链接、待办，都从这里开始。</p>
        </div>
        <div className="ws-capture-editor">
          <input className="ws-capture-title" aria-label="捕捉标题" placeholder="加个标题（可选）" value={title} maxLength={180}
            disabled={saving} onChange={(e) => updateDraft({ ...draftRef.current, title: e.target.value })} />
          <textarea ref={bodyRef} className="ws-capture-body" aria-label="捕捉正文" placeholder="此刻有什么值得留下？" value={content}
            disabled={saving} onChange={(e) => updateDraft({ ...draftRef.current, content: e.target.value })} />
          <div className="ws-capture-editor-footer">
            <button className="ws-capture-paste" type="button" disabled={pasting || saving} onClick={() => void pasteClipboard()}>
              <Icon n="bx-copy" />{pasting ? '读取中…' : '粘贴剪贴板'}
            </button>
            <span className="ws-capture-draft" aria-live="polite">
              <Icon n={storageError ? 'bx-error' : 'bx-lock'} />
              {storageError ? '草稿暂未保存' : restored ? '已恢复本机草稿' : title || content ? '草稿已存于本机' : '本机草稿 · 自动保留'}
            </span>
          </div>
        </div>
        {(error || storageError) && <p className="ws-capture-error" role="alert"><Icon n="bx-info-circle" />{error || storageError}</p>}
        <footer className="ws-capture-footer">
          <div className="ws-capture-shortcut"><kbd>{modifier} ⇧ N</kbd><span>{shortcut || '正在检查快捷键…'}</span></div>
          <button className="ws-capture-save" type="submit" disabled={saving || pasting || (!title.trim() && !content.trim())}
            title={!title.trim() && !content.trim() ? '写下标题或正文后即可保存' : `保存笔记 · ${modifier}Enter`}>
            {saving ? '正在保存…' : '存入笔记'}<kbd>{modifier} ↵</kbd>
          </button>
        </footer>
      </form>
    </dialog>
  )
}
