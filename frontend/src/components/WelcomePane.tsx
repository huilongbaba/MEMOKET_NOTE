import Logo from './Logo'
import type { Note } from '../api'
import { displayTitle } from '../util/displayTitle'
import { SHORTCUT_GROUPS } from '../shortcuts'

/**
 * 没打开任何笔记时中栏放什么。之前是两行灰字（实拍：新用户第一眼就是一片白）。
 * 现在是一张「从哪开始」：三个入口 + 最近编辑 + 几个最常用的键。
 */
export default function WelcomePane({ notes, factCount, onNew, onImport, onOpen, onOpenNote, onShortcuts }: {
  notes: Note[]
  factCount: number
  onNew: () => void
  onImport: () => void
  onOpen: (virtualId: string) => void
  onOpenNote: (n: Note) => void
  onShortcuts: () => void
}) {
  const recent = [...notes].sort((a, b) => (b.updated_at > a.updated_at ? 1 : -1)).slice(0, 6)
  const keys = SHORTCUT_GROUPS.flatMap((g) => g.items).filter((i) => ['⌘N / ⌘T', '⌘K / ⌘J', '/', '@'].includes(i.keys))
  return (
    <div className="welcome">
      <div className="row" style={{ gap: 12, alignItems: 'center' }}>
        <Logo size={40} />
        <div>
          <h2 style={{ margin: 0 }}>MEMOKET NOTE</h2>
          <p className="muted" style={{ margin: '2px 0 0', fontSize: 13 }}>
            {notes.length === 0 ? '从一篇笔记或一次导入开始。' : `${notes.length} 篇笔记 · ${factCount.toLocaleString()} 条知识库事实`}
          </p>
        </div>
      </div>

      <div className="welcome-cards">
        <button className="welcome-card" onClick={onNew}>
          <i className="bx bx-plus" />
          <b>新建笔记</b>
          <span className="muted">写到一半点「续写」，会先查你的知识库再往下写。</span>
          <kbd>⌘N</kbd>
        </button>
        <button className="welcome-card" onClick={onImport}>
          <i className="bx bx-import" />
          <b>导入</b>
          <span className="muted">Markdown、Obsidian、Evernote、Notion、Apple 备忘录，或一批录音 / PDF 进知识库。</span>
        </button>
        <button className="welcome-card" onClick={() => onOpen(factCount > 0 ? 'kb' : 'app:import')}>
          <i className="bx bx-data" />
          <b>知识库</b>
          <span className="muted">{factCount > 0 ? '总览、主题地图、时间线，每个节点都是一页。' : '还是空的——导入一场会议录音就有了。'}</span>
        </button>
      </div>

      {recent.length > 0 && (
        <section>
          <p className="muted palette-group" style={{ marginInline: 0 }}>最近编辑</p>
          <div className="welcome-recent">
            {recent.map((n) => (
              <a key={n.id} className="kb-link" onClick={() => onOpenNote(n)}>
                <i className="bx bx-note" /> <span className="ellipsis">{displayTitle(n)}</span>
                <span className="muted" style={{ marginInlineStart: 'auto', fontSize: 11 }}>{n.updated_at.slice(0, 10)}</span>
              </a>
            ))}
          </div>
        </section>
      )}

      <section>
        <p className="muted palette-group" style={{ marginInline: 0 }}>常用键 <a className="link" onClick={onShortcuts}>全部 ⌘/</a></p>
        <div className="welcome-keys">
          {keys.map((k) => <div key={k.keys} className="shortcut-row"><kbd>{k.keys}</kbd><span>{k.what}</span></div>)}
        </div>
      </section>
    </div>
  )
}
