import { EditorView } from '@codemirror/view'
import { toast } from '../toast'

// Not a hard cap -- large images still get inlined, just with a heads-up,
// since the doc has no separate asset store to reject into. Base64 runs
// ~33% larger than the source file.
const WARN_BYTES = 3 * 1024 * 1024

/**
 * Paste/drop an image -> inline as a data: URI markdown image. No backend
 * asset storage exists yet, so this keeps the doc self-contained (still a
 * single plain string, still portable via export) rather than half-wiring
 * an upload endpoint. Trade-off: large screenshots bloat the note's size
 * since there's no compression/resizing here -- acceptable for v1, but a
 * real asset-storage backend would be the next step if note sizes become
 * a problem.
 */
function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function insertImage(view: EditorView, file: File, pos: number) {
  if (file.size > WARN_BYTES) {
    toast(`「${file.name}」有点大（${(file.size / 1024 / 1024).toFixed(1)}MB），会让这篇笔记变重，但还是会插入`)
  }
  fileToDataUrl(file).then((dataUrl) => {
    const alt = file.name.replace(/\.[^.]+$/, '') || 'image'
    const md = `![${alt}](${dataUrl})`
    view.dispatch({
      changes: { from: pos, to: pos, insert: md },
      selection: { anchor: pos + md.length },
    })
  })
}

export const imagePaste = EditorView.domEventHandlers({
  paste(event, view) {
    const items = event.clipboardData?.items
    if (!items) return false
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile()
        if (file) {
          event.preventDefault()
          insertImage(view, file, view.state.selection.main.from)
          return true
        }
      }
    }
    return false
  },
  drop(event, view) {
    const files = event.dataTransfer?.files
    if (!files || files.length === 0) return false
    const imageFile = Array.from(files).find((f) => f.type.startsWith('image/'))
    if (!imageFile) return false
    event.preventDefault()
    const pos = view.posAtCoords({ x: event.clientX, y: event.clientY }) ?? view.state.selection.main.from
    insertImage(view, imageFile, pos)
    return true
  },
})
