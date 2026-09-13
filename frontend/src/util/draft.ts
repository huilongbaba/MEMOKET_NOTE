/** 没存上的草稿（save() 失败那几秒里用户还在写）落本机；下次打开这篇如果库里的版本更旧，把草稿放回去。
 *  从 App.tsx 挪出来（第 476 轮）：读写三个小函数 + 一条纯判断。 */
export interface Draft { title: string; content: string; at: number }

const key = (noteId: string) => 'memoket-note-draft:' + noteId

export function readDraft(noteId: string): Draft | null {
  try {
    const raw = localStorage.getItem(key(noteId))
    return raw ? (JSON.parse(raw) as Draft) : null
  } catch { return null }
}
export function writeDraft(noteId: string, title: string, content: string) {
  try { localStorage.setItem(key(noteId), JSON.stringify({ title, content, at: Date.now() })) } catch { /* 无所谓 */ }
}
export function clearDraft(noteId: string) {
  try { localStorage.removeItem(key(noteId)) } catch { /* 无所谓 */ }
}

/** 打开一篇时草稿要不要放回来：比库里的新、内容又不一样才放；否则用库里的、草稿清掉。
 *  探针模式下 save() 被拦，放回来的草稿永远「存不回去」，会留在 dev 实例的 localStorage 里，
 *  下一次不带探针启动就被当真草稿存进真实笔记（第 136 轮：测试笔记末尾多了一行探针文案）——所以也清。 */
export function resolveDraft(note: { title: string; content: string; updated_at: string }, draft: Draft | null, isProbe: boolean):
  { title: string; content: string; restored: boolean; clear: boolean } {
  if (draft && draft.content !== note.content && draft.at > Date.parse(note.updated_at)) {
    return { title: draft.title || note.title, content: draft.content, restored: true, clear: isProbe }
  }
  return { title: note.title, content: note.content, restored: false, clear: !!draft }
}
