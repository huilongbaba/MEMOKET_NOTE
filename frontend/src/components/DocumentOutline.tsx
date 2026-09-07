import { useMemo } from 'react'
import type { RefObject } from 'react'
import { EditorView } from '@codemirror/view'

type Heading = { level: number; text: string; pos: number }

function parseHeadings(content: string): Heading[] {
  const out: Heading[] = []
  const re = /^(#{1,6})\s+(.+)$/gm
  let m: RegExpExecArray | null
  while ((m = re.exec(content))) {
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
