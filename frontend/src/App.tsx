import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from './api'
import type { Note, Revision, TapMeta } from './api'
import AudioRecorder from './components/AudioRecorder'
import MemoryPanel from './components/MemoryPanel'
import RevisionPanel, { applyRevision } from './components/RevisionPanel'
import SkeletonPanel from './components/SkeletonPanel'

export default function App() {
  const [notes, setNotes] = useState<Note[]>([])
  const [current, setCurrent] = useState<Note | null>(null)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')

  const [skeleton, setSkeleton] = useState<string[]>([])
  const [revisions, setRevisions] = useState<Revision[]>([])
  const [loading, setLoading] = useState<'' | 'skeleton' | 'edit' | 'tap'>('')
  const [tapMeta, setTapMeta] = useState<TapMeta | null>(null)
  const [job, setJob] = useState('')
  const [healthMsg, setHealthMsg] = useState('')

  const editorRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

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
    setSkeleton([])
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
    const n = await api.createNote('未命名', '')
    await reload()
    open(n)
  }

  async function save() {
    if (!current) return
    const n = await api.saveNote(current.id, title, content)
    setCurrent(n)
    await reload()
  }

  // 自动保存：停止输入 1.5 秒后落库
  useEffect(() => {
    if (!current) return
    if (title === current.title && content === current.content) return
    const t = setTimeout(save, 1500)
    return () => clearTimeout(t)
  }, [title, content])  // eslint-disable-line react-hooks/exhaustive-deps

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
      setSkeleton(r.skeleton)
    } catch (e) {
      alert('生成骨架失败：' + e)
    } finally {
      setLoading('')
    }
  }

  async function runEdit() {
    setLoading('edit')
    try {
      const r = await api.genRevisions(content, skeleton)
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
        skeleton,
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
            onClick={() => open(n)}
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

            <textarea
              ref={editorRef}
              className="editor"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="开始写…  写到一半点 magic tap，会先查你的知识库再续写。"
            />
          </>
        )}
      </div>

      <div className="col">
        <SkeletonPanel
          skeleton={skeleton}
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
