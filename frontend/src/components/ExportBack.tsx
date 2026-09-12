import { useState } from 'react'
import { exportFeishu, exportNotion, exportObsidian, type ExportBackOut } from '../api'
import { toast } from '../toast'

/**
 * 导回（docs/import-sync-plan.md §2）：把这里的笔记按目标平台的规则渲染出去。
 * 这里是真相：每篇带 memoket_id，下次再导按 id 覆盖而不是新建；对方在那边改过的
 * 先跳过报冲突，不自动拉回来——双向同步是无底洞，明确不做。凭证不落库，每次填。
 */
export default function ExportBack() {
  const [vaultDir, setVaultDir] = useState(() => { try { return localStorage.getItem('memoket-note:vault-dir') || '' } catch { return '' } })
  const [force, setForce] = useState(false)
  const [notionToken, setNotionToken] = useState('')
  const [notionParent, setNotionParent] = useState('')
  const [feishuAppId, setFeishuAppId] = useState('')
  const [feishuSecret, setFeishuSecret] = useState('')
  const [feishuFolder, setFeishuFolder] = useState('')
  const [busy, setBusy] = useState<'' | 'obsidian' | 'notion' | 'feishu'>('')
  const [result, setResult] = useState<{ where: string; out: ExportBackOut } | null>(null)

  async function pickVault() {
    const pick = window.memoketDesktop?.pickDirectory
    if (!pick) { toast('网页版没法选本机目录，直接把路径贴进输入框', 'error'); return }
    const dir = await pick('选择 Obsidian vault 文件夹')
    if (dir) { setVaultDir(dir); try { localStorage.setItem('memoket-note:vault-dir', dir) } catch { /* 无所谓 */ } }
  }

  async function run(where: 'obsidian' | 'notion' | 'feishu', fn: () => Promise<ExportBackOut>) {
    setBusy(where)
    try {
      const out = await fn()
      setResult({ where, out })
      const n = (out.written ?? 0) + (out.created ?? 0) + (out.updated ?? 0)
      toast(n ? `导回 ${n} 篇` : '没有需要写的：都是上次导回后没改过的')
      window.dispatchEvent(new CustomEvent('note-remotes-changed'))
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    } finally {
      setBusy('')
    }
  }

  const spin = (w: string, label: string) => busy === w ? <span className="spinner" /> : label

  return (
    <>
      <h2>导回</h2>
      <div className="stack export-back">
        <p className="muted" style={{ fontSize: 12, margin: 0 }}>
          把这里的笔记写回到别的地方。这里是真相：每篇带 <code>memoket_id</code>，再导一次是<strong>覆盖</strong>不是新建；
          对方那边改过的会先跳过并列出来，不会自动拉回来。
        </p>

        <div className="row" style={{ gap: 8, alignItems: 'center' }}>
          <span style={{ width: 88 }}>Obsidian</span>
          <input placeholder="vault 文件夹路径" value={vaultDir} onChange={(e) => setVaultDir(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          <button onClick={() => void pickVault()} title="选文件夹">…</button>
          <label className="muted" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> 覆盖对方改过的
          </label>
          <button onClick={() => void run('obsidian', () => exportObsidian(vaultDir.trim(), [], force))} disabled={!vaultDir.trim() || !!busy}>
            {spin('obsidian', '写入')}
          </button>
        </div>
        <p className="muted" style={{ fontSize: 11, margin: '0 0 6px 96px' }}>
          树的层级变成文件夹，克隆写成 .link.txt，图片 / 录音复制进 _assets/。Obsidian 打开这个 vault 就能看到。
        </p>

        <div className="row" style={{ gap: 8, alignItems: 'center' }}>
          <span style={{ width: 88 }}>Notion</span>
          <input type="password" placeholder="Integration token（ntn_… / secret_…）" value={notionToken} onChange={(e) => setNotionToken(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          <input placeholder="父页面 id（页面链接末尾 32 位）" value={notionParent} onChange={(e) => setNotionParent(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          <button onClick={() => void run('notion', () => exportNotion(notionToken.trim(), notionParent.trim().replace(/-/g, '')))} disabled={!notionToken.trim() || !notionParent.trim() || !!busy}>
            {spin('notion', '写入')}
          </button>
        </div>
        <p className="muted" style={{ fontSize: 11, margin: '0 0 6px 96px' }}>
          每篇建成父页面下的一个子页面；标题 / 段落 / 列表 / 代码 / 引用会变成 Notion 块。父页面要先 Connect 给这个 integration。
        </p>

        <div className="row" style={{ gap: 8, alignItems: 'center' }}>
          <span style={{ width: 88 }}>飞书</span>
          <input placeholder="App ID（cli_…）" value={feishuAppId} onChange={(e) => setFeishuAppId(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          <input type="password" placeholder="App Secret" value={feishuSecret} onChange={(e) => setFeishuSecret(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          <input placeholder="文件夹 token（可空 = 应用根目录）" value={feishuFolder} onChange={(e) => setFeishuFolder(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          <button onClick={() => void run('feishu', () => exportFeishu(feishuAppId.trim(), feishuSecret.trim(), feishuFolder.trim()))} disabled={!feishuAppId.trim() || !feishuSecret.trim() || !!busy}>
            {spin('feishu', '写入')}
          </button>
        </div>
        <p className="muted" style={{ fontSize: 11, margin: '0 0 6px 96px' }}>
          应用要有 docx / drive 的写权限，目标文件夹要把应用加为可编辑的协作者。凭证不会存下来。
        </p>

        {result && (
          <div className="card export-back-result">
            <strong style={{ fontSize: 13 }}>
              {result.where === 'obsidian' ? 'Obsidian' : result.where === 'notion' ? 'Notion' : '飞书'}：
              {result.out.written != null && <> 写入 {result.out.written} 篇 · 没变 {result.out.skipped ?? 0} 篇</>}
              {result.out.created != null && <> 新建 {result.out.created} 篇 · 覆盖 {result.out.updated ?? 0} 篇</>}
            </strong>
            {!!result.out.conflicts?.length && (
              <div style={{ marginTop: 6 }}>
                <span className="muted" style={{ fontSize: 12 }}>对方改过、这次没动（勾「覆盖对方改过的」再写一次就会覆盖）：</span>
                <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12 }}>
                  {result.out.conflicts.slice(0, 20).map((p) => <li key={p}>{p}</li>)}
                </ul>
              </div>
            )}
            {!!result.out.failed?.length && (
              <div style={{ marginTop: 6 }}>
                <span className="muted" style={{ fontSize: 12, color: 'var(--del)' }}>失败：</span>
                <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12 }}>
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
