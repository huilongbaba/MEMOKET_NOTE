import { useMemo } from 'react'
import type { RefObject } from 'react'
import { EditorView } from '@codemirror/view'

type Heading = { level: number; text: string; pos: number }

/** 正文里的标题。**围栏代码块里的不算**——Python 和 Shell 的注释正好是
 * `# ` 开头，跟一级标题一个样子，不排除的话大纲面板里会冒出「读取退货
 * 工单」这种条目，点一下光标跳进代码块中间。
 *
 * 后端 `app/editor/outline.py` 的 `_mask_fences()` 干的是同一件事，而且
 * 后果更重（那边这个 bug 会让普通笔记被误判成大纲、把结构冻死）。这两处
 * 各自解析各自的标题是合理的——一个是导航面板，一个是 harness 的结构防线，
 * 不构成共享契约；但踩的是同一个坑。
 */
export function parseHeadings(content: string): Heading[] {
  const out: Heading[] = []
  const re = /^(#{1,6})\s+(.+)$/gm
  const fence = /^\s*(`{3,}|~{3,})/
  // 每一行的起始偏移 → 它在不在围栏里
  const inFence = new Set<number>()
  let fenced = false
  let at = 0
  for (const line of content.split('\n')) {
    const isFence = fence.test(line)
    if (isFence || fenced) inFence.add(at)
    if (isFence) fenced = !fenced
    at += line.length + 1
  }
  let m: RegExpExecArray | null
  while ((m = re.exec(content))) {
    if (inFence.has(m.index)) continue
    out.push({ level: m[1].length, text: m[2].trim(), pos: m.index })
  }
  return out
}

/** Jump-to-heading outline -- cheap to add now that the editor is real
 * markdown with real heading syntax, and it's table-stakes for anything
 * pitching itself as a Notion-class editor for longer documents. */
export default function DocumentOutline({ content, viewRef }: {
  content: string
  viewRef: RefObject<EditorView | null>
}) {
  const headings = useMemo(() => parseHeadings(content), [content])
  if (headings.length === 0) return null

  function jump(pos: number) {
    const view = viewRef.current
    if (!view) return
    view.dispatch({
      selection: { anchor: pos },
      effects: EditorView.scrollIntoView(pos, { y: 'center' }),
    })
    view.focus()
  }

  return (
    <div>
      <h2 style={{ margin: '0 0 6px' }}>大纲</h2>
      <div className="stack" style={{ gap: 2 }}>
        {headings.map((h, i) => (
          <a
            key={i}
            className="link"
            style={{
              display: 'block', fontSize: 12,
              paddingLeft: (h.level - 1) * 12,
              textDecoration: 'none',
            }}
            onClick={() => jump(h.pos)}
          >
            {h.text}
          </a>
        ))}
      </div>
    </div>
  )
}
