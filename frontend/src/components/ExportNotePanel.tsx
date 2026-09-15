import { useEffect, useState } from 'react'

import { noteRemotes, type NoteRemote } from '../api'
import { toast } from '../toast'
import { fmtDate } from '../util/time'
import { WHERE_LABEL, loadVault, saveVault, useExportBack, type ExportWhere } from '../util/useExportBack'

/**
 * 把**一篇**导回到别处。
 *
 * 跟导入页那块（`ExportBack`）是同一件事、不同场景：那边整页宽、第一次配置、
 * 整库导；这边是窄弹层、重复动作、只一篇。第 628 轮直接把那块塞进弹层是错的
 * ——说明文字比控件多，三个平台一起摊开，而最该出现的一行（这一篇上次导到
 * 哪儿了、之后改没改过）反而没有。逻辑共用 `useExportBack`，排版各写各的。
 *
 * 这一版的三条取舍：
 * · **先说状态**：已有副本排在最上面。重复动作里，「上次导到哪、之后改没改过」
 *   比任何说明都有用。
 * · **一次只问一个去处**：三个平台是互斥的选择，不是三张要一起填的表。
 *   默认停在「这一篇已经有副本的那个」，其次是上次用过的。
 * · **说明缩到一行**：进到这个弹层的人已经知道自己要干什么；完整说明在导入页。
 */
export default function ExportNotePanel({ noteId, title, onClose }:
  { noteId: string; title: string; onClose: () => void }) {
  const [remotes, setRemotes] = useState<NoteRemote[] | null>(null)
  const [where, setWhere] = useState<ExportWhere | null>(null)
  const [vault, setVault] = useState(loadVault)
  const [force, setForce] = useState(false)
  const [token, setToken] = useState('')
  const [parent, setParent] = useState('')
  const [appId, setAppId] = useState('')
  const [secret, setSecret] = useState('')
  const [folder, setFolder] = useState('')
  const ex = useExportBack([noteId])

  useEffect(() => {
    let alive = true
    noteRemotes(noteId).then((r) => { if (alive) setRemotes(r) }).catch(() => { if (alive) setRemotes([]) })
    return () => { alive = false }
  }, [noteId])

  // 默认停在「这一篇已经有副本的那个」——重复导回是常态，头一次才是例外
  useEffect(() => {
    if (where || remotes === null) return
    const had = remotes[0]?.platform as ExportWhere | undefined
    setWhere(had && WHERE_LABEL[had] ? had : (loadVault() ? 'obsidian' : 'obsidian'))
  }, [remotes, where])

  async function pickVault() {
    const pick = window.memoketDesktop?.pickDirectory
    if (!pick) { toast('网页版没法选本机目录，直接把路径贴进输入框', 'error'); return }
    const dir = await pick('选择 Obsidian vault 文件夹')
    if (dir) { setVault(dir); saveVault(dir) }
  }

  const HINT: Record<ExportWhere, string> = {
    obsidian: '按树的层级写成文件夹，图片和录音复制进 _assets/。',
    notion: '建成父页面下的一个子页面；凭证不会存下来，每次要填。',
    feishu: '应用要有 docx / drive 写权限，目标文件夹要加它为协作者；凭证不会存下来。',
  }
  const ready = where === 'obsidian' ? !!vault.trim()
    : where === 'notion' ? !!token.trim() && !!parent.trim()
      : !!appId.trim() && !!secret.trim() && !!folder.trim()

  function go() {
    if (where === 'obsidian') void ex.toObsidian(vault, force)
    else if (where === 'notion') void ex.toNotion(token, parent)
    else if (where === 'feishu') void ex.toFeishu(appId, secret, folder)
  }

  return (
    <div className="export-note">
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
        <h2>导回「<span className="plain-case">{title}</span>」</h2>
        <button className="icon-btn" title="关闭（Esc）" aria-label="关闭" onClick={onClose}><i className="bx bx-x" /></button>
      </div>

      {/* ① 状态先说。重复动作里这一行比任何说明都有用 */}
      <p className="muted export-note-state">
        {remotes === null ? '…'
          /* 「再导一次是覆盖」对一篇**从没导过**的笔记是句糊涂话：还没有「同一处」。
             说清楚两步：这一次新建，之后才是覆盖。 */
          : remotes.length === 0 ? '这一篇还没导回过——这一次会在对方那边新建一份，之后再导就是覆盖它。'
            : remotes.map((r) => `${WHERE_LABEL[r.platform as ExportWhere] ?? r.platform} · ${fmtDate(r.exported_at)} 导回`).join('；')}
      </p>

      {/* ② 一次只问一个去处 */}
      <div className="seg export-note-seg">
        {(['obsidian', 'notion', 'feishu'] as ExportWhere[]).map((w) => (
          <button key={w} className={where === w ? 'on' : ''} aria-pressed={where === w}
                  onClick={() => setWhere(w)}>
            {WHERE_LABEL[w]}
            {remotes?.some((r) => r.platform === w) && <i className="bx bx-check" />}
          </button>
        ))}
      </div>

      {/* ③ 只显示选中那个的字段 */}
      <div className="export-note-fields">
        {where === 'obsidian' && (
          <>
            <div className="row" style={{ gap: 6 }}>
              <input aria-label="Obsidian vault 文件夹路径" placeholder="vault 文件夹路径" value={vault} style={{ flex: 1, minWidth: 0 }}
                     onChange={(e) => { setVault(e.target.value); saveVault(e.target.value) }} />
              <button onClick={() => void pickVault()} title="选文件夹">…</button>
            </div>
            <label className="muted" style={{ fontSize: 12 }}>
              <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> 覆盖对方改过的
            </label>
          </>
        )}
        {where === 'notion' && (
          <>
            <input aria-label="Notion Integration token" placeholder="Integration token（ntn_… / secret_…）" value={token} onChange={(e) => setToken(e.target.value)} />
            <input aria-label="Notion 父页面 id" placeholder="父页面 id" value={parent} onChange={(e) => setParent(e.target.value)} />
          </>
        )}
        {where === 'feishu' && (
          <>
            <input aria-label="飞书 App ID" placeholder="App ID（cli_…）" value={appId} onChange={(e) => setAppId(e.target.value)} />
            <input aria-label="飞书 App Secret" placeholder="App Secret" value={secret} onChange={(e) => setSecret(e.target.value)} />
            <input aria-label="飞书文件夹 token" placeholder="文件夹 token" value={folder} onChange={(e) => setFolder(e.target.value)} />
          </>
        )}
      </div>

      <p className="muted export-note-hint">{where ? HINT[where] : ''}</p>

      <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
        <button onClick={onClose}>取消</button>
        <button className="primary" disabled={!ready || !!ex.busy} onClick={go}>
          {ex.busy ? <span className="spinner" /> : `写入 ${where ? WHERE_LABEL[where] : ''}`}
        </button>
      </div>

      {ex.result && (ex.result.out.conflicts?.length ?? 0) > 0 && (
        <p className="muted export-note-hint">
          对方那边改过，跳过了：{ex.result.out.conflicts?.join('、')}。勾上「覆盖对方改过的」再写一次。
        </p>
      )}
    </div>
  )
}
