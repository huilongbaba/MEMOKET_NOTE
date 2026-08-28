import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from './api'
import type { Note, Revision, TapMeta } from './api'
import AudioRecorder from './components/AudioRecorder'
import HighlightedEditor from './components/HighlightedEditor'
import MemoryPanel from './components/MemoryPanel'
import RevisionPanel, { applyRevision } from './components/RevisionPanel'
import SkeletonPanel from './components/SkeletonPanel'

// 后台自动生成的节流参数。骨架/编辑都是真实 LLM 调用（本地模型上约 8-15s），
// 不能跟着每次按键触发——用"停止输入 N 秒 + 内容变化够多"两条门槛，既保证
// 不是纯手动，又不会打字过程中疯狂重复调用模型。
const SKELETON_IDLE_MS = 8000
const SKELETON_MIN_CHARS = 30
const SKELETON_MIN_DELTA = 20
const EDIT_IDLE_MS = 15000
const EDIT_MIN_CHARS = 30
const EDIT_MIN_DELTA = 20

export default function App() {
  const [notes, setNotes] = useState<Note[]>([])
  const [current, setCurrent] = useState<Note | null>(null)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')

  const [spine, setSpine] = useState('')
  const [beats, setBeats] = useState<string[]>([])
  const [revisions, setRevisions] = useState<Revision[]>([])
  const [loading, setLoading] = useState<'' | 'skeleton' | 'edit' | 'tap' | 'ingest'>('')
  const [tapMeta, setTapMeta] = useState<TapMeta | null>(null)
  const [job, setJob] = useState('')
  const [healthMsg, setHealthMsg] = useState('')

  const editorRef = useRef<HTMLTextAreaElement>(null)
  const backdropRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  // setTimeout callbacks close over whatever `loading` was at schedule time,
  // which is stale by the time they fire seconds later -- a ref mirror gives
  // them the live value so a background run doesn't stack on top of another
  // one (manual or auto) that's already in flight.
  const loadingRef = useRef(loading)
  useEffect(() => { loadingRef.current = loading }, [loading])
  const lastSkeletonContent = useRef('')
  const lastEditContent = useRef('')

  // ---------------------------------------------------------------- 加载

  const reload = useCallback(async () => {
    const list = await api.listNotes()
    setNotes(list)
    return list
  }, [])

  function open(n: Note) {
    setCurrent(n)
    setTitle(n.title)
    setContent(n.content)
    setSpine('')
    setBeats([])
    setRevisions([])
    setTapMeta(null)
  }

  useEffect(() => {
    reload().then((list) => {
      if (list.length) open(list[0])
    })
    api.health().then((h) => {
      const bad: string[] = []
      if (!h.llm?.ok) bad.push('LLM 不可达 (' + h.llm?.base_url + ')')
      if (!h.asr?.ok) bad.push('语音服务不可达 (' + h.asr?.base_url + ')')
      setHealthMsg(bad.join(' · '))
    }).catch(() => setHealthMsg('后端不可达'))
  }, [reload])

  async function newNote() {
    await save()
    const n = await api.createNote('未命名', '')
    await reload()
    open(n)
  }

  async function save() {
    if (!current) return
    if (title === current.title && content === current.content) return
    const n = await api.saveNote(current.id, title, content)
    setCurrent(n)
    await reload()
  }

  /** Leaving the current note (switching to another, creating a new one)
   * used to just call open()/createNote() directly -- if you did that within
   * the 1.5s autosave window, the debounce effect's cleanup cancelled the
   * pending save on its way out, and open() immediately overwrote
   * title/content with the new note's values. The edits were never sent to
   * the backend and never came back: silent data loss, no error, nothing to
   * undo. Every path that leaves the current note must flush first. */
  async function switchTo(n: Note) {
    if (current?.id === n.id) return
    await save()
    open(n)
  }

  // 自动保存：停止输入 1.5 秒后落库
  useEffect(() => {
    if (!current) return
    if (title === current.title && content === current.content) return
    const t = setTimeout(save, 1500)
    return () => clearTimeout(t)
  }, [title, content])  // eslint-disable-line react-hooks/exhaustive-deps

  // 后台自动生成骨架：停顿 8 秒、且内容比上次生成时至少多变了 20 字才重新
  // 生成——骨架本身要求"补上显然还没写但该写的部分"（见 prompts.py），跑在
  // 后台就是一份持续预测下一步该写什么的活骨架，不用手动点。
  useEffect(() => {
    if (!current) return
    if (content.trim().length < SKELETON_MIN_CHARS) return
    if (content === lastSkeletonContent.current) return
    if (lastSkeletonContent.current
        && Math.abs(content.length - lastSkeletonContent.current.length) < SKELETON_MIN_DELTA) return
    const t = setTimeout(() => {
      if (loadingRef.current) return
      lastSkeletonContent.current = content
      runSkeleton()
    }, SKELETON_IDLE_MS)
    return () => clearTimeout(t)
    // `loading` isn't read in the body, but it's a dep on purpose: if the
    // timer fires while something else is running, it backs off and does
    // nothing -- without `loading` here, nothing would ever re-run this
    // effect to give it another chance once that something else finishes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, current, loading])

  // 后台自动生成修订建议：门槛比骨架更保守（停顿更久），避免骨架和修订两个
  // 后台任务在同一次停顿窗口里抢着跑。
  useEffect(() => {
    if (!current) return
    if (content.trim().length < EDIT_MIN_CHARS) return
    if (content === lastEditContent.current) return
    if (lastEditContent.current
        && Math.abs(content.length - lastEditContent.current.length) < EDIT_MIN_DELTA) return
    const t = setTimeout(() => {
      if (loadingRef.current) return
      lastEditContent.current = content
      runEdit()
    }, EDIT_IDLE_MS)
    return () => clearTimeout(t)
    // same reasoning as the skeleton effect above: `loading` as a dep gives
    // this a chance to retry once whatever was blocking it (e.g. the
    // skeleton auto-run) finishes, instead of silently never firing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, current, loading])

  async function remove(n: Note) {
    if (!confirm('删除「' + (n.title || '未命名') + '」？')) return
    await api.deleteNote(n.id)
    const list = await reload()
    if (current?.id === n.id) {
      if (list.length) open(list[0])
      else {
        setCurrent(null)
        setTitle('')
        setContent('')
      }
    }
  }

  // ---------------------------------------------------------------- AI 动作

  async function runSkeleton() {
    setLoading('skeleton')
    try {
      const r = await api.genSkeleton(title, content)
      setSpine(r.spine)
      setBeats(r.beats)
    } catch (e) {
      alert('生成骨架失败：' + e)
    } finally {
      setLoading('')
    }
  }

  async function runEdit() {
    setLoading('edit')
    try {
      const r = await api.genRevisions(content, spine, beats)
      setRevisions(r.revisions)
      if (r.revisions.length === 0) alert('模型认为当前正文没有需要修订的地方。')
    } catch (e) {
      alert('生成修订失败：' + e)
    } finally {
      setLoading('')
    }
  }

  /** magic tap：流式续写，边到边写进编辑器。再点一次可中断。 */
  async function runMagicTap() {
    if (loading === 'tap') {
      abortRef.current?.abort()
      return
    }
    setLoading('tap')
    setTapMeta(null)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      await api.magicTap(
        content,
        spine,
        beats,
        setTapMeta,
        (piece) => setContent((c) => c + piece),
        ctrl.signal,
      )
    } catch (e) {
      if ((e as Error).name !== 'AbortError') alert('续写失败：' + e)
    } finally {
      setLoading('')
      abortRef.current = null
    }
  }

  function acceptRevision(r: Revision) {
    setContent((c) => applyRevision(c, r))
    setRevisions((rs) => rs.filter((x) => x.id !== r.id))
  }

  /** Keeps the highlight backdrop's scroll position glued to the (invisible)
   * textarea's -- the two layers only look like one piece of text if they
   * scroll together. */
  function syncEditorScroll() {
    if (editorRef.current && backdropRef.current) {
      backdropRef.current.scrollTop = editorRef.current.scrollTop
      backdropRef.current.scrollLeft = editorRef.current.scrollLeft
    }
  }

  /** Manually push the current note into the knowledge base. Not wired to
   * autosave: autosave fires every 1.5s of idle typing, so tying ingestion
   * to it would re-ingest the whole note repeatedly while the user is still
   * writing -- wasting LLM calls and producing a pile of near-duplicate
   * facts. */
  async function ingestCurrentNote() {
    if (!content.trim()) return
    setLoading('ingest')
    try {
      const r = await api.ingestText(content, title || '未命名', 'note')
      setJob(r.job_id)
    } catch (e) {
      alert('存入知识库失败：' + e)
    } finally {
      setLoading('')
    }
  }

  function insertAtCursor(text: string) {
    if (!text) return
    const el = editorRef.current
    if (!el) {
      setContent((c) => c + text)
      return
    }
    const start = el.selectionStart ?? content.length
    const end = el.selectionEnd ?? content.length
    setContent(content.slice(0, start) + text + content.slice(end))
  }

  // ---------------------------------------------------------------- 渲染

  return (
    <div className="app">
      <div className="col sidebar">
        <h1>memoket-NOTE</h1>
        <p className="muted" style={{ fontSize: 12 }}>用户 {api.getUser()}</p>
        <button className="primary" style={{ width: '100%' }} onClick={newNote}>
          + 新建笔记
        </button>

        <h2>笔记</h2>
        {notes.length === 0 && <p className="muted">还没有笔记。</p>}
        {notes.map((n) => (
          <div
            key={n.id}
            className={'note-item ' + (current?.id === n.id ? 'active' : '')}
            onClick={() => switchTo(n)}
          >
            <div className="t">{n.title || '未命名'}</div>
            <div className="muted" style={{ fontSize: 11 }}>
              {n.updated_at.slice(0, 16).replace('T', ' ')}
              <span
                style={{ float: 'right' }}
                onClick={(e) => {
                  e.stopPropagation()
                  remove(n)
                }}
              >
                ✕
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="col">
        {healthMsg && <p className="card" style={{ color: 'var(--del)' }}>{healthMsg}</p>}

        {!current ? (
          <p className="muted">左侧新建一篇笔记开始。</p>
        ) : (
          <>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="标题"
              style={{ fontSize: 20, fontWeight: 600, border: 'none', padding: '4px 0' }}
            />

            <div className="row" style={{ margin: '10px 0' }}>
              <button className="primary" onClick={runMagicTap}>
                {loading === 'tap' ? '■ 停止' : '✨ magic tap 续写'}
              </button>
              <AudioRecorder onTranscript={insertAtCursor} onIngested={setJob} />
              <button onClick={save}>保存</button>
              <button onClick={ingestCurrentNote} disabled={!content.trim() || loading === 'ingest'}>
                {loading === 'ingest' ? <span className="spinner" /> : '📥 存入知识库'}
              </button>
            </div>

            {tapMeta && (
              <p className="muted" style={{ fontSize: 12 }}>
                {tapMeta.grounded ? (
                  <>
                    <span className="badge ok">引用知识库</span> 检索到 {tapMeta.facts} 条事实（
                    {tapMeta.recall_ms} ms）：{tapMeta.sources.slice(0, 3).join('；')}
                  </>
                ) : (
                  <>
                    <span className="badge">自由续写</span> 知识库中没有相关记录
                  </>
                )}
              </p>
            )}

            <HighlightedEditor
              content={content}
              onChange={setContent}
              revisions={revisions}
              onAcceptInline={acceptRevision}
              placeholder="开始写…  写到一半点 magic tap，会先查你的知识库再续写。"
              textareaRef={editorRef}
              backdropRef={backdropRef}
              onScroll={syncEditorScroll}
            />
          </>
        )}
      </div>

      <div className="col">
        <SkeletonPanel
          spine={spine}
          beats={beats}
          loading={loading === 'skeleton'}
          onRun={runSkeleton}
        />
        <RevisionPanel
          revisions={revisions}
          content={content}
          loading={loading === 'edit'}
          onAccept={acceptRevision}
          onReject={(r) => setRevisions((rs) => rs.filter((x) => x.id !== r.id))}
          onRun={runEdit}
        />
        <MemoryPanel pendingJob={job} />
      </div>
    </div>
  )
}
