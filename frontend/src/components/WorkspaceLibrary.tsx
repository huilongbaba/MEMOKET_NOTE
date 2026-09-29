import { useId, useMemo, useRef, useState } from 'react'
import { getUser, type Note } from '../api'
import { displayTitle } from '../util/displayTitle'
import { previewLine } from '../util/virtual'
import { fmtWhen } from '../util/time'
import { wordCount } from '../util/wordCount'
import { friendlyError } from '../util/friendlyError'
import { toast } from '../toast'
import Icon from './Icon'
import WorkspaceNotesStatus, { type WorkspaceNotesStatusProps } from './WorkspaceNotesStatus'

type Props = WorkspaceNotesStatusProps & {
  notes: Note[]
  onOpen: (note: Note) => void
  onNew: () => void
  onImport: () => void
  onPin: (note: Note) => Promise<void>
}

type Preferences = { view: 'grid' | 'list'; sort: 'recent' | 'name' }
const DEFAULT_PREFERENCES: Preferences = { view: 'grid', sort: 'recent' }
const PREFERENCE_STORAGE_ERROR = '本机视图偏好暂不可用，本次设置仍然有效。'
const preferenceKey = (user: string) => `memoket-workspace:${encodeURIComponent(user)}:library`

function readPreferences(user: string | null): { value: Preferences; error: string } {
  try {
    if (user === null) throw new Error('No persistent identity')
    const raw = localStorage.getItem(preferenceKey(user))
    if (!raw) return { value: DEFAULT_PREFERENCES, error: '' }
    const stored: unknown = JSON.parse(raw)
    if (!stored || typeof stored !== 'object' || Array.isArray(stored)) return { value: DEFAULT_PREFERENCES, error: '' }
    const candidate = stored as Partial<Preferences>
    return { value: {
      view: candidate.view === 'list' ? 'list' : 'grid',
      sort: candidate.sort === 'name' ? 'name' : 'recent',
    }, error: '' }
  } catch (error) {
    // A malformed preference is safe to reset; unavailable storage needs an honest notice.
    return { value: DEFAULT_PREFERENCES, error: error instanceof SyntaxError ? '' : PREFERENCE_STORAGE_ERROR }
  }
}

export default function WorkspaceLibrary(props: Props) {
  let user: string | null = null
  try { user = getUser() } catch { /* Keep the library usable when browser storage is blocked. */ }
  return <WorkspaceLibraryContent key={user === null ? 'storage-unavailable' : `user:${user}`} user={user} {...props} />
}

function WorkspaceLibraryContent({ notes, notesLoading, notesError, onRetry, onOpen, onNew, onImport, onPin, user }: Props & { user: string | null }) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'all' | 'pinned'>('all')
  const [initialPreferences] = useState(() => readPreferences(user))
  const [preferences, setPreferences] = useState(initialPreferences.value)
  const [storageError, setStorageError] = useState(initialPreferences.error)
  const preferencesRef = useRef(preferences)
  const { view, sort } = preferences
  const searchRef = useRef<HTMLInputElement>(null)
  const resultCountId = useId()
  const notesUnavailable = notes.length === 0 && !!(notesLoading || notesError)
  const needle = query.trim()
  const queryLabel = needle.length > 60 ? needle.slice(0, 60) + '…' : needle
  const pinningRef = useRef(new Set<string>())
  const [pinningIds, setPinningIds] = useState(new Set<string>())
  const shown = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    return notes.filter((n) => (filter !== 'pinned' || n.pinned)
      && (!needle || `${displayTitle(n)}\n${n.content}`.toLocaleLowerCase().includes(needle)))
      .sort((a, b) => sort === 'name' ? displayTitle(a).localeCompare(displayTitle(b), 'zh-CN') : b.updated_at.localeCompare(a.updated_at))
  }, [notes, query, filter, sort])

  function updatePreferences(patch: Partial<Preferences>) {
    const next = { ...preferencesRef.current, ...patch }
    preferencesRef.current = next
    setPreferences(next)
    try {
      if (user === null) throw new Error('No persistent identity')
      localStorage.setItem(preferenceKey(user), JSON.stringify(next))
      setStorageError('')
    } catch { setStorageError(PREFERENCE_STORAGE_ERROR) }
  }

  function clearSearch() {
    setQuery('')
    searchRef.current?.focus()
  }

  async function pinNote(note: Note) {
    // The ref closes the gap before React paints the disabled button on a fast second click.
    if (pinningRef.current.has(note.id)) return
    pinningRef.current.add(note.id)
    setPinningIds(new Set(pinningRef.current))
    try {
      await onPin(note)
    } catch (error) {
      toast(`未能${note.pinned ? '取消固定' : '固定'}「${displayTitle(note)}」：${friendlyError(error)}`, 'error')
    } finally {
      pinningRef.current.delete(note.id)
      setPinningIds(new Set(pinningRef.current))
    }
  }

  return <section className="ws-library" aria-labelledby="ws-library-title">
    <header className="ws-page-heading">
      <div><span className="ws-eyebrow">YOUR KNOWLEDGE, CONNECTED</span><h1 id="ws-library-title">笔记与资料</h1><p>每一次记录，都成为下一次工作的起点。</p></div>
      <button className="primary ws-new-note" onClick={onNew}><Icon n="bx-plus" /> 新建笔记</button>
    </header>
    <div className="ws-library-tools">
      <div className="ws-library-filters" role="group" aria-label="笔记筛选">
        <button aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>全部笔记 <span>{notesUnavailable ? '—' : notes.length}</span></button>
        <button aria-pressed={filter === 'pinned'} onClick={() => setFilter('pinned')}><Icon n="bx-pin" /> 已固定 <span>{notesUnavailable ? '—' : notes.filter((n) => n.pinned).length}</span></button>
      </div>
      <div className="ws-library-search"><Icon n="bx-search" /><input ref={searchRef} aria-label="搜索笔记标题和正文" aria-describedby={notesUnavailable ? undefined : resultCountId} placeholder="搜索标题或内容…" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => {
        if (e.key === 'Escape' && !e.nativeEvent.isComposing) { e.preventDefault(); e.stopPropagation(); clearSearch() }
      }} />{query && <button className="icon-btn" aria-label="清空搜索" title="清空搜索 · Esc" onClick={clearSearch}><Icon n="bx-x" /></button>}</div>
      <select aria-label="笔记排序" value={sort} onChange={(e) => updatePreferences({ sort: e.target.value === 'name' ? 'name' : 'recent' })}><option value="recent">最近编辑</option><option value="name">标题顺序</option></select>
      <div className="ws-view-switch" role="group" aria-label="笔记视图">
        <button aria-label="卡片视图" aria-pressed={view === 'grid'} onClick={() => updatePreferences({ view: 'grid' })}><Icon n="bx-category" /></button>
        <button aria-label="列表视图" aria-pressed={view === 'list'} onClick={() => updatePreferences({ view: 'list' })}><Icon n="bx-list-ul" /></button>
      </div>
    </div>
    {!notesUnavailable && <p className="ws-library-summary muted" id={resultCountId} role="status" aria-live="polite" aria-atomic="true">{needle ? `找到 ${shown.length} 篇${filter === 'pinned' ? '已固定的' : ''}笔记 · “${queryLabel}”` : `显示 ${shown.length} 篇${filter === 'pinned' ? '已固定的' : ''}笔记`}</p>}
    {storageError && <p className="ws-library-preferences-error muted" role="status">{storageError}</p>}
    <WorkspaceNotesStatus notesLoading={notesLoading} notesError={notesError} onRetry={onRetry} hasNotes={notes.length > 0} />
    {shown.length > 0 ? <div className={'ws-library-results ' + (view === 'list' ? 'ws-library-list' : 'ws-library-grid')}>
      {shown.map((note) => {
        const pinning = pinningIds.has(note.id)
        return <article className="ws-library-note" key={note.id}>
        <button className="ws-library-open" onClick={() => onOpen(note)}>
          <span className="ws-document-icon"><Icon n={note.icon || 'bx-file'} /></span>
          <div className="ws-library-note-copy"><h2>{displayTitle(note)}</h2><p>{previewLine(note.content, displayTitle(note)) || '留一页空白，给下一个想法。'}</p></div>
          <span className="ws-library-note-meta">{fmtWhen(note.updated_at)}<span>·</span>{wordCount(note.content)} 字</span>
        </button>
        <button className={'ws-library-pin' + (note.pinned ? ' is-pinned' : '')} aria-label={(pinning ? '正在更新固定状态 ' : note.pinned ? '取消固定 ' : '固定 ') + displayTitle(note)} aria-pressed={note.pinned} aria-busy={pinning} disabled={pinning} title={pinning ? '正在更新固定状态，请稍候' : note.pinned ? '取消固定这篇笔记' : '固定这篇笔记'} onClick={() => void pinNote(note)}>{pinning ? <span className="spinner" aria-hidden="true" /> : <Icon n="bx-pin" />}</button>
      </article>})}
    </div> : notesUnavailable ? null : <div className="ws-library-empty">
      <span className="ws-empty-book"><Icon n={needle ? 'bx-search' : 'bx-book'} /></span>
      <h2>{needle ? '还没有找到这条记录' : filter === 'pinned' ? '把常用的笔记，放在手边' : '从一个想法开始'}</h2>
      <p>{needle ? `${filter === 'pinned' ? '已固定的笔记' : '笔记标题和正文'}中没有“${queryLabel}”。${filter === 'pinned' ? '可以搜索全部笔记，或换一个关键词。' : '试试正文里的关键词，或者缩短搜索内容。'}` : filter === 'pinned' ? '在笔记卡片上点击固定，即可在这里和侧栏快速找到。' : '记录灵感、整理会议，或导入已有的资料。'}</p>
      <div>{needle ? <>{filter === 'pinned' && <button onClick={() => setFilter('all')}>搜索全部笔记</button>}<button onClick={clearSearch}>清空搜索</button></> : filter === 'pinned' ? <button onClick={() => setFilter('all')}>查看全部笔记</button> : <><button className="primary" onClick={onNew}><Icon n="bx-plus" /> 写下第一篇笔记</button><button onClick={onImport}><Icon n="bx-import" /> 导入资料</button></>}</div>
    </div>}
    <footer className="ws-library-footer"><Icon n="bx-check-shield" /> 笔记保存在当前连接的笔记库中，可随时导出为 Markdown。</footer>
  </section>
}
