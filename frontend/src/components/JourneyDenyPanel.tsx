import { useEffect, useState } from 'react'

import { journeyDeny, journeySetDeny, type JourneyDeny } from '../api'
import { toast } from '../toast'

/**
 * 「不记这些」。
 *
 * **加不了自己的，这个功能就只能关掉不用**（docs/daily-journey-plan.md §1 ②）：
 * 默认那份挡得住密码管理器、银行、隐私窗口这些通用的，但挡不住「我们公司那个
 * 内部系统」「我看病那个网站」——而正是这类东西决定了一个人敢不敢一直开着。
 *
 * 内置那份只读：**「把密码管理器加回记录范围」不是一个该给的选项。**
 */
export default function JourneyDenyPanel() {
  const [d, setD] = useState<JourneyDeny | null>(null)
  const [draft, setDraft] = useState('')
  const [kind, setKind] = useState<'apps' | 'words'>('apps')

  useEffect(() => { journeyDeny().then(setD).catch(() => setD(null)) }, [])

  async function put(apps: string[], words: string[]) {
    try { setD(await journeySetDeny(apps, words)) }
    catch (e) { toast(e instanceof Error ? e.message : String(e), 'error') }
  }

  function add() {
    const t = draft.trim()
    if (!d || !t) return
    setDraft('')
    if (d[kind].includes(t)) return
    void put(kind === 'apps' ? [...d.apps, t] : d.apps, kind === 'words' ? [...d.words, t] : d.words)
  }

  if (!d) return null
  const drop = (k: 'apps' | 'words', v: string) =>
    put(k === 'apps' ? d.apps.filter((x) => x !== v) : d.apps,
        k === 'words' ? d.words.filter((x) => x !== v) : d.words)

  return (
    <div className="journey-deny">
      <h3 className="kb-section-title">不记这些</h3>
      <p className="muted" style={{ fontSize: 12, margin: '2px 0 8px' }}>
        命中就<b>连截图都不拍</b>。应用名要写全（跟菜单栏上显示的一样），标题词按包含匹配。
      </p>

      <div className="chip-wrap">
        {[...d.builtin_apps, ...d.builtin_words].map((x) => (
          <span key={x} className="chip" title="默认就不记的，去不掉">{x}</span>
        ))}
      </div>

      {(d.apps.length > 0 || d.words.length > 0) && (
        <div className="chip-wrap" style={{ marginTop: 6 }}>
          {d.apps.map((x) => (
            <span key={'a' + x} className="chip mine">{x}
              <button className="icon-btn sm" title="去掉" onClick={() => void drop('apps', x)}><i className="bx bx-x" /></button>
            </span>
          ))}
          {d.words.map((x) => (
            <span key={'w' + x} className="chip mine">标题含「{x}」
              <button className="icon-btn sm" title="去掉" onClick={() => void drop('words', x)}><i className="bx bx-x" /></button>
            </span>
          ))}
        </div>
      )}

      <div className="row" style={{ gap: 6, marginTop: 8 }}>
        <span className="seg">
          <button className={kind === 'apps' ? 'on' : ''} onClick={() => setKind('apps')}>应用</button>
          <button className={kind === 'words' ? 'on' : ''} onClick={() => setKind('words')}>标题词</button>
        </span>
        <input value={draft} onChange={(e) => setDraft(e.target.value)} style={{ flex: 1 }}
               placeholder={kind === 'apps' ? '比如：Signal' : '比如：体检报告'}
               onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }} />
        <button onClick={add} disabled={!draft.trim()} title={draft.trim() ? '' : '先填一个'}>加上</button>
      </div>
    </div>
  )
}
