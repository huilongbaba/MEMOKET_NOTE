export type NoteAttachment = { id: string; name: string; url: string; kind: 'image' | 'file'; bytes: number }

/** Restore only app-owned asset references; a draft never grants access to a local path. */
export function readNoteAttachments(value: unknown): NoteAttachment[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is NoteAttachment => !!item && typeof item === 'object'
    && typeof item.id === 'string' && typeof item.name === 'string'
    && typeof item.url === 'string' && /^\/api\/assets\/[a-zA-Z0-9_-]+\.[a-zA-Z0-9]+$/.test(item.url)
    && (item.kind === 'image' || item.kind === 'file') && typeof item.bytes === 'number' && Number.isFinite(item.bytes) && item.bytes >= 0)
}

export function noteContentWithAttachments(content: string, attachments: NoteAttachment[] = []): string {
  if (!attachments.length) return content
  const references = attachments.map(item => {
    const label = item.name.replace(/[\r\n]+/g, ' ').replace(/[\\[\]<>]/g, character => `\\${character}`)
    return `${item.kind === 'image' ? '!' : ''}[${label}](${item.url})`
  }).join('\n\n')
  return content ? `${content.replace(/\s+$/, '')}\n\n${references}` : references
}

export function attachmentSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.ceil(bytes / 1024))} KB`
}
