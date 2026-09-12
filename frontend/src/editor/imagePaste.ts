import { EditorView } from '@codemirror/view'
import { toast } from '../toast'
import { uploadAsset } from '../api'

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

/** 先传到后端的资产库（/api/assets，按内容哈希去重），正文里只留一个短地址；
 *  传不上去（后端不在）才退回 data: URI——之前一律内嵌 base64，一张截图就让
 *  笔记胖几 MB，续写时整段 base64 还会跟着正文进提示词。 */
async function insertImage(view: EditorView, file: File, pos: number) {
  const alt = file.name.replace(/\.[^.]+$/, '') || 'image'
  let src: string
  try {
    src = (await uploadAsset(file)).url
  } catch {
    if (file.size > WARN_BYTES) {
      toast(`「${file.name}」有点大（${(file.size / 1024 / 1024).toFixed(1)}MB），后端没接上只能内嵌，这篇笔记会变重`)
    }
    src = await fileToDataUrl(file)
  }
  const line = view.state.doc.lineAt(pos)
  const { at, text } = imageInsertion(line.text, line.to, pos, `![${alt}](${src})`)
  view.dispatch({
    changes: { from: at, to: at, insert: text },
    selection: { anchor: at + text.length },
  })
}

/** 图片自己占一段（Notion 也是块级插入）。光标落在一行中间——尤其是标题行——
 *  不能在光标处切开：实拍拖进「# 创业一年回顾」，标题被切成「#」+ 图 + 裸文字。
 *  非空行一律插到**这一行末尾**之后，自成一段；空行就原地放。 */
export function imageInsertion(lineText: string, lineTo: number, pos: number, md: string): { at: number; text: string } {
  if (!lineText.trim()) return { at: pos, text: md }
  return { at: lineTo, text: `\n\n${md}\n` }
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
          void insertImage(view, file, view.state.selection.main.from)
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
    void insertImage(view, imageFile, pos)
    return true
  },
})
