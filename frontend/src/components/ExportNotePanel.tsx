import { useEffect, useState } from 'react'

import { noteRemotes, type NoteRemote } from '../api'
import { toast } from '../toast'
import { fmtDate } from '../util/time'
import { CRED_HOWTO, canRememberCreds, loadCreds, saveCreds } from '../util/exportCreds'
import { WHERE_LABEL, loadVault, openRemote, remoteUrl, saveVault, useExportBack, type ExportWhere } from '../util/useExportBack'
import Icon from './Icon'

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
 *
 * P2-fix（docs/_research/export-verification-P2.md §4.4 / 4.5 / 4.8 / 4.16）：
 * 副本那一行能点开对面文档；桌面版凭证记住、弹层给「怎么拿」；已经有飞书副本的
 * 更新不再要文件夹 token；失败的篇目列在底下，不只靠 6 秒的 toast。
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
    // 桌面版：上次填过的凭证直接带出来
    void loadCreds().then((c) => {
      if (!alive) return
      if (c.notion_token) setToken(c.notion_token); if (c.notion_parent) setParent(c.notion_parent)
      if (c.feishu_app_id) setAppId(c.feishu_app_id); if (c.feishu_app_secret) setSecret(c.feishu_app_secret); if (c.feishu_folder) setFolder(c.feishu_folder)
    })
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

  const has = (w: ExportWhere) => !!remotes?.some((r) => r.platform === w)
  const remember = canRememberCreds()
  const HINT: Record<ExportWhere, string> = {
    obsidian: '按树的层级写成文件夹，图片和录音复制进 _assets/。',
    notion: `建成父页面下的一个子页面；页面要先 Connect 给这个 integration。表格 / 列表 / 代码 / 粗体都会变成 Notion 块，本地图片 Notion API 收不了、会写成一行说明。${remember ? '凭证记在本机。' : '凭证不会存下来，每次要填。'}`,
    feishu: `应用要有 docx / drive 写权限，目标文件夹要加它为协作者。表格 / 图片 / 列表 / 代码都会变成飞书块。${remember ? '凭证记在本机。' : '凭证不会存下来，每次要填。'}`,
  }
  // 文件夹 token / 父页面 id 只有**新建**时才用得上：已经有副本的那一篇更新不该被它拦住（§4.8）
  const ready = where === 'obsidian' ? !!vault.trim()
    : where === 'notion' ? !!token.trim() && (has('notion') || !!parent.trim())
      : !!appId.trim() && !!secret.trim() && (has('feishu') || !!folder.trim())

  async function go() {
    let out = null
    if (where === 'obsidian') out = await ex.toObsidian(vault, force)
    else if (where === 'notion') out = await ex.toNotion(token, parent, force)
    else if (where === 'feishu') out = await ex.toFeishu(appId, secret, folder, force)
    if (!out) return
    if (where === 'notion') void saveCreds({ notion_token: token.trim(), notion_parent: parent.trim() })
    if (where === 'feishu') void saveCreds({ feishu_app_id: appId.trim(), feishu_app_secret: secret.trim(), feishu_folder: folder.trim() })
    noteRemotes(noteId).then(setRemotes).catch(() => { /* 没有就没有 */ })
  }

  const howto = where && where !== 'obsidian' ? CRED_HOWTO[where] : null

  return (
    <div className="export-note">
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
        <h2>导回「<span className="plain-case">{title}</span>」</h2>
        <button className="icon-btn" title="关闭（Esc）" aria-label="关闭" onClick={onClose}><Icon n="bx-x" /></button>
      </div>

      {/* ① 状态先说。重复动作里这一行比任何说明都有用；副本能点去对面 */}
      <p className="muted export-note-state">
        {remotes === null ? '…'
          /* 「再导一次是覆盖」对一篇**从没导过**的笔记是句糊涂话：还没有「同一处」。
             说清楚两步：这一次新建，之后才是覆盖。 */
          : remotes.length === 0 ? '这一篇还没导回过——这一次会在对方那边新建一份，之后再导就是覆盖它。'
            : remotes.map((r, i) => {
              const url = remoteUrl(r, vault)
              const label = `${WHERE_LABEL[r.platform as ExportWhere] ?? r.platform} · ${fmtDate(r.exported_at)} 导回`
              return (
                <span key={r.platform}>
                  {i > 0 && '；'}
                  {url ? <a href={url} className="link" onClick={(e) => { e.preventDefault(); openRemote(url) }} title={url}>{label}<Icon n="bx-link-external" /></a> : label}
                </span>
              )
            })}
      </p>

      {/* ② 一次只问一个去处 */}
      <div className="seg export-note-seg">
        {(['obsidian', 'notion', 'feishu'] as ExportWhere[]).map((w) => (
          <button key={w} className={where === w ? 'on' : ''} aria-pressed={where === w}
                  onClick={() => setWhere(w)}>
            {WHERE_LABEL[w]}
            {has(w) && <Icon n="bx-check" />}
          </button>
        ))}
      </div>

      {/* ③ 只显示选中那个的字段 */}
      <div className="export-note-fields">
        {where === 'obsidian' && (
          <div className="row" style={{ gap: 6 }}>
            <input aria-label="Obsidian vault 文件夹路径" placeholder="vault 文件夹路径" value={vault} style={{ flex: 1, minWidth: 0 }}
                   onChange={(e) => { setVault(e.target.value); saveVault(e.target.value) }} />
            <button className="icon-btn" aria-label="选文件夹" onClick={() => void pickVault()} title="选文件夹"><Icon n="bx-dots-horizontal-rounded" /></button>
          </div>
        )}
        {where === 'notion' && (
          <>
            <input aria-label="Notion Integration token" type="password" placeholder="Integration token（ntn_… / secret_…）" value={token} onChange={(e) => setToken(e.target.value)} />
            <input aria-label="Notion 父页面 id" placeholder={has('notion') ? '父页面 id（已有副本，更新不用填）' : '父页面 id（页面链接末尾那 32 位）'} value={parent} onChange={(e) => setParent(e.target.value)} />
          </>
        )}
        {where === 'feishu' && (
          <>
            <input aria-label="飞书 App ID" placeholder="App ID（cli_…）" value={appId} onChange={(e) => setAppId(e.target.value)} />
            <input aria-label="飞书 App Secret" type="password" placeholder="App Secret" value={secret} onChange={(e) => setSecret(e.target.value)} />
            <input aria-label="飞书文件夹 token" placeholder={has('feishu') ? '文件夹 token（已有副本，更新不用填）' : '文件夹 token（必填：新文档建在它下面）'} value={folder} onChange={(e) => setFolder(e.target.value)} />
          </>
        )}
        <label className="muted" style={{ fontSize: 'var(--t-sm)' }}>
          <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> 覆盖对方改过的
        </label>
      </div>

      <p className="muted export-note-hint">
        {where ? HINT[where] : ''}
        {howto && <> <a href={howto.url} className="link" title={howto.text} onClick={(e) => { e.preventDefault(); openRemote(howto.url) }}>怎么拿凭证</a></>}
      </p>

      <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
        <button onClick={onClose}>取消</button>
        <button className="primary" disabled={!ready || !!ex.busy} onClick={() => void go()}>
          {ex.busy ? <span className="spinner" /> : `写入 ${where ? WHERE_LABEL[where] : ''}`}
        </button>
      </div>

      {ex.result && (ex.result.out.conflicts?.length ?? 0) > 0 && (
        <p className="muted export-note-hint">
          对方那边改过，跳过了：{ex.result.out.conflicts?.join('、')}。勾上「覆盖对方改过的」再写一次。
        </p>
      )}
      {ex.result && (ex.result.out.failed?.length ?? 0) > 0 && (
        <p className="export-note-hint" style={{ color: 'var(--del)' }}>
          失败：{ex.result.out.failed?.join('；')}
        </p>
      )}
    </div>
  )
}
