/** 灵动岛的正文编辑器：跟完整笔记库同一个 markdown 编辑器（表格、图片、Mermaid、标题都就地渲染），
 *  外加两样岛上才有的东西——剪贴板候选（浅色浮现，Tab 补齐）和选区旁的 AI 胶囊。
 *  正文的真值仍在父级的 draft 里；这里只是把它画出来、把操作交回去。 */
import { useCallback, useEffect, useId, useImperativeHandle, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from 'react'
import { EditorSelection, StateEffect, StateField, type Extension } from '@codemirror/state'
import { Decoration, EditorView, WidgetType } from '@codemirror/view'
import MarkdownEditor from './MarkdownEditor'
import Icon from './Icon'
import '../companion-draft-editor.css'

export type CompanionEditorHandle = {
  focus(): void
  hasFocus(): boolean
  getSelection(): { start: number; end: number }
  setSelection(start: number, end?: number): void
}

type Props = {
  editorRef: RefObject<CompanionEditorHandle | null>
  value: string
  disabled: boolean
  busy: boolean
  candidate: { text: string; truncated: boolean } | null
  modifier: string
  onChange: (value: string) => void
  onAccept: () => void
  onDismiss: () => void
  /** Right-click, ContextMenu key or the selection pill: open the AI menu at these client coordinates. */
  onContextMenu: (clientX: number, clientY: number) => void
  onKeyDown?: (event: ReactKeyboardEvent<HTMLDivElement>) => void
}

/** The clipboard candidate rendered after the last character, in the same layout as the text it would join. */
class GhostWidget extends WidgetType {
  constructor(readonly prefix: string, readonly text: string) { super() }
  eq(other: GhostWidget) { return other.text === this.text && other.prefix === this.prefix }
  toDOM() {
    const ghost = document.createElement('span')
    ghost.className = 'dc-draft-ghost'
    ghost.setAttribute('aria-hidden', 'true')
    const gap = document.createElement('span')
    gap.className = 'dc-draft-ghost-prefix'
    gap.textContent = this.prefix
    const text = document.createElement('span')
    text.className = 'dc-draft-ghost-text'
    text.textContent = this.text
    ghost.append(gap, text)
    return ghost
  }
  ignoreEvent() { return true }
}
const setGhost = StateEffect.define<string>()
const ghostField = StateField.define<string>({
  create: () => '',
  update(value, tr) {
    for (const effect of tr.effects) if (effect.is(setGhost)) return effect.value
    return value
  },
})
const ghostDecorations = EditorView.decorations.compute([ghostField, 'doc', 'selection'], (state) => {
  const text = state.field(ghostField)
  const selection = state.selection.main
  if (!text || !selection.empty || selection.head !== state.doc.length) return Decoration.none
  const prefix = state.doc.length && !/\s$/.test(state.doc.sliceString(state.doc.length - 1)) ? '\n\n' : ''
  return Decoration.set(Decoration.widget({ widget: new GhostWidget(prefix, text), side: 1 }).range(state.doc.length))
})

export default function CompanionDraftEditor({ editorRef, value, disabled, busy, candidate, modifier, onChange, onAccept, onDismiss, onContextMenu, onKeyDown }: Props) {
  const viewRef = useRef<EditorView | null>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [selection, setSelection] = useState({ start: value.length, end: value.length, focused: false })
  const [composing, setComposing] = useState(false)
  const [pointerDown, setPointerDown] = useState(false)
  const [dismissedSnapshot, setDismissedSnapshot] = useState('')
  const [pill, setPill] = useState<{ top: number; left: number } | null>(null)
  const hintId = useId()
  const live = useRef({ onAccept, onDismiss, canAccept: false, ghostVisible: false })

  useEffect(() => {
    if (dismissedSnapshot && candidate && candidate.text !== dismissedSnapshot) setDismissedSnapshot('')
  }, [candidate, dismissedSnapshot])

  useImperativeHandle(editorRef, () => ({
    focus: () => viewRef.current?.focus(),
    hasFocus: () => !!viewRef.current?.hasFocus,
    getSelection: () => {
      const main = viewRef.current?.state.selection.main
      return main ? { start: main.from, end: main.to } : { start: 0, end: 0 }
    },
    setSelection: (start, end = start) => {
      const view = viewRef.current
      if (!view) return
      const length = view.state.doc.length
      view.dispatch({ selection: EditorSelection.range(Math.min(start, length), Math.min(end, length)), scrollIntoView: true })
    },
  }), [])

  const atEnd = !value || (selection.start === selection.end && selection.end === value.length)
  const ghostVisible = !!candidate?.text && candidate.text !== dismissedSnapshot && atEnd && !composing && !disabled
  const canAccept = ghostVisible && !candidate?.truncated && !busy
  live.current = { onAccept, onDismiss, canAccept, ghostVisible }

  // Island-only editor behaviour: the ghost candidate, its Tab/Esc keys, the accessible name, and selection tracking.
  const extensions = useMemo<Extension[]>(() => [
    ghostField,
    ghostDecorations,
    EditorView.contentAttributes.of({ 'aria-label': '随手记正文' }),
    EditorView.updateListener.of((update) => {
      if (!update.selectionSet && !update.docChanged && !update.focusChanged) return
      const main = update.state.selection.main
      setSelection(previous => previous.start === main.from && previous.end === main.to && previous.focused === update.view.hasFocus ? previous : { start: main.from, end: main.to, focused: update.view.hasFocus })
    }),
  ], [])

  // The ghost text lives in editor state so it lays out with the document; keep it in step with what the parent shows.
  useEffect(() => {
    const view = viewRef.current
    if (!view) return
    const text = ghostVisible ? candidate!.text : ''
    if (view.state.field(ghostField) !== text) view.dispatch({ effects: setGhost.of(text) })
  }, [ghostVisible, candidate])

  const hasSelection = selection.end > selection.start && !!value.slice(selection.start, selection.end).trim()
  const pillVisible = hasSelection && selection.focused && !pointerDown && !composing && !disabled
  // The pill sits right after the last selected character, or on the next line when the line has no room; never over the text.
  useEffect(() => {
    if (!pillVisible) { setPill(null); return }
    const view = viewRef.current
    const wrapper = wrapperRef.current
    if (!view || !wrapper) { setPill(null); return }
    const anchor = selection.end - (value.slice(selection.start, selection.end).length - value.slice(selection.start, selection.end).trimEnd().length)
    let coords: { left: number; right: number; top: number; bottom: number } | null = null
    try { coords = view.coordsAtPos(anchor) } catch { coords = null }   // no layout in jsdom
    if (!coords) { setPill(null); return }
    const box = wrapper.getBoundingClientRect()
    const lineHeight = coords.bottom - coords.top || 24
    const left = coords.right - box.left + 8
    const top = coords.top - box.top
    if (left + 60 <= box.width) setPill({ top: top + Math.max(0, (lineHeight - 24) / 2), left })
    else setPill({ top: top + lineHeight + 2, left: Math.max(0, Math.min(coords.left - box.left, box.width - 60)) })
  }, [pillVisible, selection, value])

  const dismiss = useCallback(() => {
    if (candidate) setDismissedSnapshot(candidate.text)
    onDismiss()
  }, [candidate, onDismiss])

  function accept() {
    if (!canAccept) return
    setDismissedSnapshot(candidate!.text)
    onAccept()
  }

  // Tab and Escape are decided here, before the editor sees them: Tab either takes the candidate or keeps its
  // ordinary focus-moving job (the island is a small window, not a code editor), Escape dismisses the candidate
  // without reaching the island's own Escape (which would collapse it).
  function onKeyDownCapture(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Tab' && !event.altKey && !event.metaKey && !event.ctrlKey) {
      const composingNow = composing || event.nativeEvent.isComposing
      if (!event.shiftKey && !composingNow && canAccept) { event.preventDefault(); event.stopPropagation(); accept(); return }
      event.stopPropagation()
      return
    }
    if (event.key === 'Escape' && ghostVisible && !event.nativeEvent.isComposing) { event.preventDefault(); event.stopPropagation(); dismiss() }
  }

  return <div ref={wrapperRef} className="dc-draft-editor" data-busy={busy || undefined}
    onContextMenu={event => { event.preventDefault(); onContextMenu(event.clientX, event.clientY) }} onKeyDownCapture={onKeyDownCapture}
    onPointerDown={() => setPointerDown(true)} onPointerUp={() => setPointerDown(false)}
    onCompositionStart={() => setComposing(true)} onCompositionEnd={() => setComposing(false)}
    onKeyDown={event => {
      if (event.nativeEvent.isComposing || composing) return
      if (event.key === 'ContextMenu' || (event.key === 'F10' && event.shiftKey)) {
        event.preventDefault()
        const box = event.currentTarget.getBoundingClientRect()
        onContextMenu(box.left + 16, box.top + 28)
        return
      }
      onKeyDown?.(event)
    }}>
    <MarkdownEditor content={value} onChange={text => { if (candidate) dismiss(); onChange(text) }} placeholder={ghostVisible ? '' : '写下想法，或粘贴内容…'}
      viewRef={viewRef} readOnly={disabled} scrollPad={false} extensions={extensions} />
    {pillVisible && pill && <button type="button" className="dc-draft-selection-ai" style={pill} aria-label="对选中文字调用 AI" title="对选中文字调用 AI" onMouseDown={event => event.preventDefault()} onClick={event => onContextMenu(event.clientX, event.clientY + 8)}><Icon n="bx-brain" />AI</button>}
    {ghostVisible && <div className="dc-draft-clipboard-controls" id={hintId}>
      {candidate!.truncated
        ? <span className="dc-draft-clipboard-hint"><kbd>{modifier}V</kbd>内容较长，粘贴全文</span>
        : <button type="button" className="dc-draft-clipboard-accept" aria-label="接入剪贴板内容" disabled={!canAccept} title="把浅色内容接入当前笔记" onMouseDown={event => event.preventDefault()} onClick={accept}><kbd>Tab</kbd><span>补齐</span></button>}
      <button type="button" className="dc-draft-clipboard-dismiss" aria-label="忽略这次剪贴板建议" title="忽略这次建议 · Esc" onMouseDown={event => event.preventDefault()} onClick={dismiss}><Icon n="bx-x" /></button>
    </div>}
  </div>
}
