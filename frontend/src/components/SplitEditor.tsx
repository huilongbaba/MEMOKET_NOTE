/** 分屏第二栏的可编辑正文（Trilium 的分屏每一栏都能写；我们之前第二栏只读）。
 *
 *  跟主编辑器不共享状态：自己持有正文、自己防抖自动保存（`util/autosave`），
 *  存完把服务端回来的那篇交给 App 就地替换列表里的那条。不带 harness / 续写 /
 *  提案层 / 引用高亮那些——那些都长在主编辑器上，分屏的定位是「看着另一篇改几笔」。
 *  同一篇在主栏也开着的时候 App 不会用这个组件（那边只读渲染），两边不会互相盖。 */
import { useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react'
import * as api from '../api'
import type { Note } from '../api'
import MarkdownEditor from './MarkdownEditor'
import { createAutosave } from '../util/autosave'
import { friendlyError } from '../util/friendlyError'
import { toast } from '../toast'

const SAVE_DELAY_MS = 800

/** 必须用 `key={note.id}` 挂载。 */
export default function SplitEditor({ note, onSaved, flushRef }: {
  note: Note
  onSaved: (n: Note) => void
  /** App 在把这篇切到主栏之前先 flush：不然分屏里最后 0.8 秒的改动会被主栏拿着旧正文的自动保存盖掉 */
  flushRef?: MutableRefObject<(() => Promise<void>) | null>
}) {
  const [content, setContent] = useState(note.content)
  const [status, setStatus] = useState<'' | 'saving' | 'saved' | 'error'>('')
  const live = useRef({ note, onSaved })
  live.current = { note, onSaved }
  // 探针模式不落库：跟主编辑器 save() 同一条纪律（探针塞的假内容曾污染真笔记三次）
  const probing = useMemo(() => !!new URLSearchParams(location.search).get('probe'), [])

  const saver = useMemo(() => createAutosave({
    delay: SAVE_DELAY_MS,
    save: async (c) => {
      if (probing) { setStatus('saved'); return }      // 探针：只走到这一步，不落库
      setStatus('saving')
      const n = await api.saveNote(live.current.note.id, live.current.note.title, c)
      live.current.onSaved(n)
      setStatus('saved')
    },
    onError: (e) => { setStatus('error'); toast('分屏这篇没存上：' + friendlyError(e), 'error') },
  }), [probing])

  // App 用 key={note.id} 挂这个组件：换一篇 = 重挂，正文从 useState 初始值来。
  // 卸载（关分屏 / 换篇）时把没存的冲掉再丢。
  useEffect(() => () => { void saver.flush(); saver.dispose() }, [saver])
  useEffect(() => {
    if (!flushRef) return
    flushRef.current = () => saver.flush()
    return () => { flushRef.current = null }
  }, [flushRef, saver])

  // 别处改了这篇（导入 / 撤回 / 恢复历史版本）而这里没有未存改动：跟着刷新
  useEffect(() => {
    if (!saver.dirty()) setContent(note.content)
  }, [note.content, saver])

  const onChange = (c: string) => { setContent(c); saver.change(c) }

  return (
    <>
      <MarkdownEditor content={content} onChange={onChange} placeholder="在这里写…" />
      {status && (
        <div className="split-save-status muted" aria-live="polite">
          {status === 'saving' ? '保存中…' : status === 'saved' ? '已保存' : '没存上，改动留在这里，再改一笔会重试'}
        </div>
      )}
    </>
  )
}
