import Icon from './Icon'
import '../workspace-notes-status.css'

export type WorkspaceNotesStatusProps = {
  notesLoading?: boolean
  notesError?: string
  onRetry?: () => void
}

export default function WorkspaceNotesStatus({ notesLoading = false, notesError = '', onRetry, hasNotes }: WorkspaceNotesStatusProps & { hasNotes: boolean }) {
  if (!notesLoading && !notesError) return null
  return <div className="ws-notes-status" role={notesError ? 'alert' : 'status'}>
    {notesLoading ? <span className="spinner" aria-hidden="true" /> : <Icon n="bx-error" />}
    <div><p>{notesError ? hasNotes ? '笔记暂时无法更新' : '暂时无法读取笔记' : hasNotes ? '正在更新笔记…' : '正在读取笔记…'}</p>
      {notesError && <small>{notesError}{hasNotes ? ' 仍显示上次加载的笔记。' : ''}</small>}
    </div>
    {notesError && onRetry && <button type="button" disabled={notesLoading} title={notesLoading ? '正在重新读取笔记，请稍候' : '重新读取笔记'} onClick={onRetry}>{notesLoading ? '重试中' : '重试'}</button>}
  </div>
}
