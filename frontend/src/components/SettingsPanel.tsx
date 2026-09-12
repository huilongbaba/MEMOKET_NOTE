import { useEffect, useState } from 'react'
import { friendlyError } from '../util/friendlyError'
import * as api from '../api'
import type { ProviderConfig } from '../api'
import { toast } from '../toast'
import { applyTheme, canSwitchTheme, getTheme, type Theme } from '../theme'

/** 外观三选一。放在 LLM 之前——Trilium 的设置也是 Appearance 打头。 */
function AppearanceSection() {
  const [theme, setTheme] = useState<Theme>(getTheme())
  const options: { v: Theme; label: string; icon: string }[] = [
    { v: 'system', label: '跟随系统', icon: 'bx-desktop' },
    { v: 'light', label: '浅色', icon: 'bx-sun' },
    { v: 'dark', label: '深色', icon: 'bx-moon' },
  ]
  return (
    <>
      <h3 className="kb-section-title">外观</h3>
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        {options.map((o) => (
          <button key={o.v} className={'chip' + (theme === o.v ? ' active' : '')}
                  disabled={!canSwitchTheme() && o.v !== 'system'}
                  onClick={() => { setTheme(o.v); applyTheme(o.v) }}>
            <i className={'bx ' + o.icon} /> {o.label}
          </button>
        ))}
      </div>
      {!canSwitchTheme() && <p className="muted" style={{ fontSize: 12, margin: '4px 0 0' }}>浏览器里只能跟随系统；桌面版可以固定浅色 / 深色。</p>}
    </>
  )
}

/**
 * LLM 供应商设置：本地模型 or GPT。全局设置，不分用户——切了之后写作
 * 三件套/续写/知识库抽取/实体去重全部跟着换，不用重启后端。
 *
 * 本地模型免费但慢（实测批量任务单次调用常见 10-45s）；GPT 需要自己的
 * API key、按量计费，但通常快很多——两者的取舍留给用户自己判断，这里
 * 只负责让切换这件事简单、随时能切回去。
 */
export default function SettingsPanel({ onClose, embedded = false }: { onClose?: () => void; embedded?: boolean }) {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [cfg, setCfg] = useState<ProviderConfig | null>(null)
  const [provider, setProvider] = useState<'local' | 'gpt'>('local')
  const [gptApiKey, setGptApiKey] = useState('')
  const [gptModel, setGptModel] = useState('gpt-4.1-mini')
  const [gptBaseUrl, setGptBaseUrl] = useState('https://api.openai.com/v1')

  useEffect(() => {
    api.getProviderConfig().then((c) => {
      setCfg(c)
      setProvider(c.provider)
      setGptModel(c.gpt_model)
      setGptBaseUrl(c.gpt_base_url)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  async function save() {
    setSaving(true)
    try {
      const body: Parameters<typeof api.setProviderConfig>[0] = {
        provider, gpt_model: gptModel, gpt_base_url: gptBaseUrl,
      }
      // 空字符串不传——传了会被当成"清空 key"（后端语义：不传=保留原值，
      // 传空字符串=真的清空），用户只是切换 provider 没重新填 key 时
      // 不该把已经存的 key 误删掉
      if (gptApiKey.trim()) body.gpt_api_key = gptApiKey.trim()
      const updated = await api.setProviderConfig(body)
      setCfg(updated)
      setGptApiKey('')
      toast(`已切换到${updated.provider === 'gpt' ? 'GPT' : '本地模型'}`)
      // 让外壳重查一次健康状态，状态栏的「LLM 不可达」立刻跟着变
      window.dispatchEvent(new CustomEvent('provider-changed'))
    } catch (e) {
      toast('保存失败：' + friendlyError(e), 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={embedded ? 'embedded-panel' : 'palette-backdrop'} onClick={embedded ? undefined : onClose}>
      <div
        className={embedded ? '' : 'modal'}
        style={embedded ? undefined : { background: 'var(--bg)', border: '1px solid var(--line)', borderRadius: 10,
                maxWidth: 480, width: '92vw', padding: 24 }}
        onClick={(e) => e.stopPropagation()}
      >
        {!embedded && (
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <h2 style={{ margin: 0 }}>⚙️ 设置</h2>
            <button onClick={onClose}>✕</button>
          </div>
        )}

        {loading ? (
          <p className="muted"><span className="spinner" /> 加载中…</p>
        ) : (
          <div className="stack" style={{ marginTop: 12 }}>
            {embedded && <AppearanceSection />}
            <h3 className="kb-section-title">LLM 供应商</h3>
            <p className="muted" style={{ fontSize: 12, margin: '2px 0 8px' }}>
              续写、修订、知识库抽取这些功能背后调用的模型——本地模型免费但慢，
              GPT 需要自己的 API key，通常快很多。
            </p>

            <label className="row" style={{ gap: 8, cursor: 'pointer' }}>
              <input type="radio" checked={provider === 'local'}
                    onChange={() => setProvider('local')} />
              <span>本地模型</span>
            </label>
            <label className="row" style={{ gap: 8, cursor: 'pointer' }}>
              <input type="radio" checked={provider === 'gpt'}
                    onChange={() => setProvider('gpt')} />
              <span>GPT</span>
            </label>

            {provider === 'gpt' && (
              <div className="stack" style={{ marginTop: 4, paddingLeft: 24 }}>
                <input
                  type="password"
                  placeholder={cfg?.gpt_api_key_set ? `API key（已设置 ${cfg.gpt_api_key_preview}，留空则不改）` : 'sk-...'}
                  value={gptApiKey}
                  onChange={(e) => setGptApiKey(e.target.value)}
                />
                <input
                  placeholder="模型名（默认 gpt-4.1-mini）"
                  value={gptModel}
                  onChange={(e) => setGptModel(e.target.value)}
                />
                <input
                  placeholder="API base URL（默认 OpenAI 官方端点）"
                  value={gptBaseUrl}
                  onChange={(e) => setGptBaseUrl(e.target.value)}
                />
                {!cfg?.gpt_api_key_set && !gptApiKey.trim() && (
                  <p className="muted" style={{ fontSize: 12, color: 'var(--del)' }}>
                    还没设置 API key，保存后选中 GPT 也用不了，会自动退回本地模型。
                  </p>
                )}
              </div>
            )}

            <button className="primary" onClick={save} disabled={saving} style={{ marginTop: 8 }}>
              {saving ? <span className="spinner" /> : '保存'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
