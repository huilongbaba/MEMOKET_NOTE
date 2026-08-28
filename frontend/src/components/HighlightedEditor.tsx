import type { RefObject } from 'react'
import type { Revision } from '../api'

/**
 * The editor, with pending revisions drawn directly on the text instead of
 * only listed in the side panel. A plain <textarea> can't render part of its
 * value in a different color, so this uses the standard trick: the textarea
 * that actually receives typing has transparent text (only its caret shows),
 * and a backdrop div behind it -- same font, padding, border, wrapping --
 * renders the same string with revision spans colored in. The two layers
 * line up pixel-for-pixel, so it reads as if the textarea's own text were
 * highlighted, and clicking a highlighted span accepts that revision.
 *
 * The backdrop always renders EXACTLY `content`, just wrapped in <span>s --
 * never more or fewer characters (e.g. never ghost-inserting an "insert"
 * revision's proposed text). Anything that changed the rendered length would
 * desync the two layers' line-wrapping below that point. So every op type
 * highlights its *anchor* (text that already exists in `content`) rather
 * than previewing the replacement inline; what the revision would actually
 * do is in the hover tooltip.
 */

type Segment =
  | { kind: 'plain'; text: string }
  | { kind: 'revision'; text: string; revision: Revision }

function buildSegments(content: string, revisions: Revision[]): Segment[] {
  const matches = revisions
    .filter((r) => r.anchor && content.includes(r.anchor))
    .map((r) => {
      const start = content.indexOf(r.anchor)
      return { start, end: start + r.anchor.length, revision: r }
    })
    .sort((a, b) => a.start - b.start)

  // Two anchors can't highlight overlapping ranges without one clobbering the
  // other's span boundaries -- keep the earlier one, drop the rest. Dropped
  // revisions are still visible/actionable in the side panel list.
  const nonOverlapping: typeof matches = []
  let lastEnd = -1
  for (const m of matches) {
    if (m.start >= lastEnd) { nonOverlapping.push(m); lastEnd = m.end }
  }

  const segments: Segment[] = []
  let cursor = 0
  for (const m of nonOverlapping) {
    if (m.start > cursor) segments.push({ kind: 'plain', text: content.slice(cursor, m.start) })
    segments.push({ kind: 'revision', text: content.slice(m.start, m.end), revision: m.revision })
    cursor = m.end
  }
  if (cursor < content.length) segments.push({ kind: 'plain', text: content.slice(cursor) })
  return segments
}

function tooltipFor(r: Revision): string {
  const base = r.op === 'insert' ? `点击接受：在此之后插入「${r.text}」`
    : r.op === 'delete' ? '点击接受：删除这段'
    : `点击接受：替换为「${r.text}」`
  return r.reason ? `${base}\n理由：${r.reason}` : base
}

export default function HighlightedEditor({
  content, onChange, revisions, onAcceptInline, placeholder, textareaRef, backdropRef, onScroll,
}: {
  content: string
  onChange: (v: string) => void
  revisions: Revision[]
  onAcceptInline: (r: Revision) => void
  placeholder?: string
  textareaRef: RefObject<HTMLTextAreaElement | null>
  backdropRef: RefObject<HTMLDivElement | null>
  onScroll: () => void
}) {
  const segments = buildSegments(content, revisions)

  return (
    <div className="editor-wrap">
      <div ref={backdropRef} className="editor-backdrop" aria-hidden="true">
        {segments.map((seg, i) => seg.kind === 'plain'
          ? <span key={i}>{seg.text}</span>
          : (
            <span
              key={i}
              className={seg.revision.op === 'delete' ? 'del' : seg.revision.op === 'insert' ? 'ins' : 'replace'}
              title={tooltipFor(seg.revision)}
              onClick={() => onAcceptInline(seg.revision)}
            >
              {seg.text}
            </span>
          ))}
        {/* A textarea's value always ends up with a trailing newline's worth
           of extra box space; matching it here keeps scrollHeight equal so
           the very last line never clips out of sync between the layers. */}
        {'\n'}
      </div>
      <textarea
        ref={textareaRef}
        className="editor editor-input"
        value={content}
        onChange={(e) => onChange(e.target.value)}
        onScroll={onScroll}
        placeholder={placeholder}
      />
    </div>
  )
}
