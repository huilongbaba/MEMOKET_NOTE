import { useEffect, useState } from 'react'
import { toast } from '../toast'
import { CRED_HOWTO, canRememberCreds, loadCreds, saveCreds } from '../util/exportCreds'
import { openRemote, useExportBack } from '../util/useExportBack'
import Icon from './Icon'

/**
 * 导回（docs/import-sync-plan.md §2）：把这里的笔记按目标平台的规则渲染出去。
 * 这里是真相：每篇带 memoket_id，下次再导按 id 覆盖而不是新建；对方在那边改过的
 * 先跳过报冲突，不自动拉回来——双向同步是无底洞，明确不做。凭证：桌面版记在主进程
 * （util/exportCreds，P2-fix），网页版每次填。
 *
 * 这一块是**整库导**，长在导入页里（整页宽、第一次配置）。单篇导回是另一个
 * 场景（窄弹层、重复动作、只一篇），排版完全不同，在 `ExportNotePanel`——
 * 第 628 轮把这块原样塞进弹层是错的：说明文字比控件还多（用户实拍指出）。
 * **会漂的是逻辑不是排版**，所以两边共用 `util/useExportBack`，各写各的界面。
 */
export default function ExportBack() {
  const [vaultDir, setVaultDir] = useState(() => { try { return localStorage.getItem('memoket-note:vault-dir') || '' } catch { return '' } })
  const [force, setForce] = useState(false)
  const [notionToken, setNotionToken] = useState('')
  const [notionParent, setNotionParent] = useState('')
  const [feishuAppId, setFeishuAppId] = useState('')
  const [feishuSecret, setFeishuSecret] = useState('')
  const [feishuFolder, setFeishuFolder] = useState('')
  const remember = canRememberCreds()
  useEffect(() => {
    let alive = true
    void loadCreds().then((c) => {
      if (!alive) return
      if (c.notion_token) setNotionToken(c.notion_token); if (c.notion_parent) setNotionParent(c.notion_parent)
      if (c.feishu_app_id) setFeishuAppId(c.feishu_app_id); if (c.feishu_app_secret) setFeishuSecret(c.feishu_app_secret); if (c.feishu_folder) setFeishuFolder(c.feishu_folder)
    })
    return () => { alive = false }
  }, [])

  async function pickVault() {
    const pick = window.memoketDesktop?.pickDirectory
    if (!pick) { toast('网页版没法选本机目录，直接把路径贴进输入框', 'error'); return }
    const dir = await pick('选择 Obsidian vault 文件夹')
    if (dir) { setVaultDir(dir); try { localStorage.setItem('memoket-note:vault-dir', dir) } catch { /* 无所谓 */ } }
  }

  // 逻辑共用（util/useExportBack）：会漂的是「怎么调、memoket_id 怎么覆盖、
  // 冲突怎么报」，不是排版。整库导 = 不传 noteIds。
  const { busy, result, toObsidian, toNotion, toFeishu } = useExportBack()

  const spin = (w: string, label: string) => busy === w ? <span className="spinner" /> : label

  return (
    <>
      <h2>导回</h2>
      <div className="stack export-back">
        <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: 0 }}>
          把这里的笔记写回到别的地方。这里是真相：每篇带 <code>memoket_id</code>，再导一次是<strong>覆盖</strong>不是新建；
          对方那边改过的会先跳过并列出来，不会自动拉回来。
          <br />
          {/* 桌面版记在主进程的 export-credentials.json（P2-fix）；网页版不存——说清楚，
              不然用户会以为是 bug：「我上次不是填过吗」。 */}
          {remember ? 'Notion / 飞书的凭证写成功后记在本机（应用数据目录），下次自动带出来。' : 'Notion / 飞书的凭证在网页版里不会存下来，每次要重填；Obsidian 只是个本机路径，记得住。'}
        </p>

        <div className="row" style={{ gap: 8, alignItems: 'center' }}>
          <span style={{ width: 88 }}>Obsidian</span>
          <input aria-label="Obsidian vault 文件夹路径" placeholder="vault 文件夹路径" value={vaultDir} onChange={(e) => setVaultDir(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          <button className="icon-btn" aria-label="选文件夹" onClick={() => void pickVault()} title="选文件夹"><Icon n="bx-dots-horizontal-rounded" /></button>
          <label className="muted" style={{ fontSize: 'var(--t-sm)', whiteSpace: 'nowrap' }}>
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> 覆盖对方改过的
          </label>
          <button onClick={() => void toObsidian(vaultDir, force)} disabled={!vaultDir.trim() || !!busy}
                  title={!vaultDir.trim() ? '先填 vault 目录' : busy ? '正在写，等这一次完成' : undefined}>
            {spin('obsidian', '写入')}
          </button>
        </div>
        <p className="muted" style={{ fontSize: 'var(--t-xs)', margin: '0 0 6px 96px' }}>
          树的层级变成文件夹，克隆写成 .link.txt，图片 / 录音复制进 _assets/。Obsidian 打开这个 vault 就能看到。
        </p>

        <div className="row" style={{ gap: 8, alignItems: 'center' }}>
          <span style={{ width: 88 }}>Notion</span>
          <input aria-label="Notion Integration token" type="password" placeholder="Integration token" value={notionToken} onChange={(e) => setNotionToken(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          <input placeholder="父页面 id" title="页面链接末尾那 32 位" value={notionParent} onChange={(e) => setNotionParent(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          <button onClick={() => void toNotion(notionToken, notionParent, force).then((o) => { if (o) void saveCreds({ notion_token: notionToken.trim(), notion_parent: notionParent.trim() }) })} disabled={!notionToken.trim() || !notionParent.trim() || !!busy}
                  title={!notionToken.trim() ? '先填 Integration token' : !notionParent.trim() ? '先填父页面 id' : busy ? '正在写，等这一次完成' : undefined}>
            {spin('notion', '写入')}
          </button>
        </div>
        <p className="muted" style={{ fontSize: 'var(--t-xs)', margin: '0 0 6px 96px' }}>
          每篇建成父页面下的一个子页面；标题 / 段落 / 列表 / 表格 / 代码 / 引用 / 粗体会变成 Notion 块（本地图片 Notion API 收不了，写成一行说明）。父页面要先 Connect 给这个 integration。
          {' '}<a href={CRED_HOWTO.notion.url} className="link" title={CRED_HOWTO.notion.text} onClick={(e) => { e.preventDefault(); openRemote(CRED_HOWTO.notion.url) }}>怎么拿凭证</a>
        </p>

        <div className="row" style={{ gap: 8, alignItems: 'center' }}>
          <span style={{ width: 88 }}>飞书</span>
          <input aria-label="飞书 App ID" placeholder="App ID（cli_…）" value={feishuAppId} onChange={(e) => setFeishuAppId(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          <input aria-label="飞书 App Secret" type="password" placeholder="App Secret" value={feishuSecret} onChange={(e) => setFeishuSecret(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          {/* 之前这里写「留空 = 应用根目录」而后端 400「没填」，前后端打架（P2 报告 §4.7）。
              飞书 API 确实允许空 token（建在应用自己的空间里），但用户在飞书里根本找不到那份——所以改成必填。 */}
          <input aria-label="飞书文件夹 token" placeholder="文件夹 token（必填）" title="文件夹链接 /drive/folder/ 后面那串；新文档建在它下面" value={feishuFolder} onChange={(e) => setFeishuFolder(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          <button onClick={() => void toFeishu(feishuAppId, feishuSecret, feishuFolder, force).then((o) => { if (o) void saveCreds({ feishu_app_id: feishuAppId.trim(), feishu_app_secret: feishuSecret.trim(), feishu_folder: feishuFolder.trim() }) })} disabled={!feishuAppId.trim() || !feishuSecret.trim() || !feishuFolder.trim() || !!busy}
                  title={!feishuAppId.trim() ? '先填 App ID' : !feishuSecret.trim() ? '先填 App Secret' : !feishuFolder.trim() ? '先填文件夹 token' : busy ? '正在写，等这一次完成' : undefined}>
            {spin('feishu', '写入')}
          </button>
        </div>
        <p className="muted" style={{ fontSize: 'var(--t-xs)', margin: '0 0 6px 96px' }}>
          应用要有 docx / drive 的写权限，目标文件夹要把应用加为可编辑的协作者。表格 / 图片 / 列表 / 代码 / 粗体都会变成飞书块。
          {' '}<a href={CRED_HOWTO.feishu.url} className="link" title={CRED_HOWTO.feishu.text} onClick={(e) => { e.preventDefault(); openRemote(CRED_HOWTO.feishu.url) }}>怎么拿凭证</a>
        </p>

        {result && (
          <div className="card export-back-result">
            <strong style={{ fontSize: 'var(--t-md)' }}>
              {result.where === 'obsidian' ? 'Obsidian' : result.where === 'notion' ? 'Notion' : '飞书'}：
              {result.out.written != null && <> 写入 {result.out.written} 篇 · 没变 {result.out.skipped ?? 0} 篇</>}
              {result.out.created != null && <> 新建 {result.out.created} 篇 · 覆盖 {result.out.updated ?? 0} 篇</>}
            </strong>
            {!!result.out.conflicts?.length && (
              <div style={{ marginTop: 6 }}>
                <span className="muted" style={{ fontSize: 'var(--t-sm)' }}>对方改过、这次没动（勾「覆盖对方改过的」再写一次就会覆盖）：</span>
                <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 'var(--t-sm)' }}>
                  {result.out.conflicts.slice(0, 20).map((p) => <li key={p}>{p}</li>)}
                </ul>
              </div>
            )}
            {!!result.out.missing?.length && (
              <div className="muted" style={{ marginTop: 6, fontSize: 'var(--t-sm)' }}>有 {result.out.missing.length} 个笔记 id 在库里找不到（可能已经删掉）。</div>
            )}
            {!!result.out.untried && (
              <div className="muted" style={{ marginTop: 6, fontSize: 'var(--t-sm)' }}>同一类错误连着出现，剩下 {result.out.untried} 篇没再试——先把上面的错修好再来一次。</div>
            )}
            {!!result.out.urls?.length && (
              <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 'var(--t-sm)' }}>
                {result.out.urls.slice(0, 20).map((u) => <li key={u.note_id}><a href={u.url} className="link" onClick={(e) => { e.preventDefault(); openRemote(u.url) }}>{u.title}</a></li>)}
              </ul>
            )}
            {!!result.out.failed?.length && (
              <div style={{ marginTop: 6 }}>
                <span className="muted" style={{ fontSize: 'var(--t-sm)', color: 'var(--del)' }}>失败：</span>
                <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 'var(--t-sm)' }}>
                  {result.out.failed.slice(0, 20).map((p) => <li key={p}>{p}</li>)}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  )
}
