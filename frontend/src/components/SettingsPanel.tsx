import { useEffect, useState } from 'react'
import { friendlyError } from '../util/friendlyError'
import * as api from '../api'
import type { ProviderConfig } from '../api'
import { toast } from '../toast'
import { applyTheme, canSwitchTheme, getTheme, type Theme } from '../theme'

const FEATURE_LABEL: Record<string, string> = {
  'magic-tap': '续写', 'note-harness/run': '智能续写', 'note-harness/resume': '智能续写', 'writing-plan/run': '无限续写',
  'writing-plan/start': '无限续写 · 定分段',
  'compose/block': '/ 块生成', 'compose/restructure': '智能排版', skeleton: '骨架', rewrite: '重写 / 润色', expand: '扩写',
  verify: '校验', digest: '定期回顾', 'memory/trace': '来龙去脉', 'memory/relations': '记忆关系', 'skills/generate': 'Skill 生成',
  'kb/quality/judged': '抽取质量', 'ingest/text': '存入知识库', 'kb/extract~': '知识库抽取（估算）',
}

/** 功能名是**中间件从 URL 路径自动生成的**（main.py 去掉 /api/ 和 id 段），
 *  而这张标签表是手工维护的——新加一条会调模型的路由，用量里就多出一个没人
 *  认领的 key。第 612 轮截图实拍：设置页的用量那一行里混着一个裸的
 *  `writing-plan/start`，旁边全是中文。
 *
 *  所以补一层**按前缀兜底**：同一块功能下面新长出来的路由，至少能读出它属于
 *  哪块，而不是把内部路由名甩给用户。整块都没见过才原样显示。 */
const FEATURE_GROUP: Record<string, string> = {
  'note-harness': '智能续写', 'writing-plan': '无限续写', compose: '插入块',
  memory: '记忆', skills: 'Skill', kb: '知识库', ingest: '存入知识库',
}

export function featureLabel(key: string): string {
  const exact = FEATURE_LABEL[key]
  if (exact) return exact
  const head = key.split('/')[0]
  const group = FEATURE_GROUP[head]
  return group ? `${group} · 其他` : key
}
const fmtTok = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n))

/** 模型用量：24 小时 / 7 天 / 30 天 / 全部，按功能分（都是滚动窗口，不是日历天——服务端按 UTC 算，「今天」在 UTC+8 的凌晨会对不上）。付费 API 的用户得知道钱花在哪儿了。 */
function UsageSection() {
  const [u, setU] = useState<api.UsageSummary | null>(null)
  useEffect(() => { api.usageSummary().then(setU).catch(() => setU(null)) }, [])
  if (!u) return null
  const cell = (b: api.UsageBucket) => `${b.calls} 次 · ${fmtTok(b.prompt_tokens + b.completion_tokens)} token`
  return (
    <>
      <p className="kb-section-title" style={{ marginTop: 18 }}>模型用量</p>
      <div className="row" style={{ gap: 14, flexWrap: 'wrap', fontSize: 13 }}>
        <span><span className="muted">24 小时</span> {cell(u.today)}</span>
        <span><span className="muted">7 天</span> {cell(u.week)}</span>
        <span><span className="muted">30 天</span> {cell(u.month)}</span>
        <span><span className="muted">全部</span> {cell(u.all)}</span>
      </div>
      {u.by_feature.length > 0 && (
        <div className="chip-wrap" style={{ marginTop: 6 }}>
          {u.by_feature.map((f) => <span key={f.feature} className="badge" title={`${f.feature} · ${f.calls} 次`}>{featureLabel(f.feature)} {fmtTok(f.tokens)}</span>)}
        </div>
      )}
      <p className="muted" style={{ fontSize: 12, margin: '4px 0 0' }}>
        token 数取自供应商响应，按 30 天内的功能排；「知识库抽取（估算）」走 KITE 自己的调用，拿不到 usage，按字数估。{u.models.length ? ` 模型：${u.models.join('、')}` : ''}
      </p>
    </>
  )
}

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
                  disabled={!canSwitchTheme() && o.v !== 'system'} title={!canSwitchTheme() && o.v !== 'system' ? '网页版只能跟随系统，桌面版才能手动选' : undefined}
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
/** 设置页最底下的出处行：AGPL §13 要求向使用者提供源码，仓库地址就放在这。 */
export function AboutLine() {
  return (
    <p className="muted" style={{ fontSize: 11, marginTop: 28 }}>
      MEMOKET NOTE · AGPL-3.0 · 源码 <a href="https://github.com/huilongbaba/MEMOKET_NOTE" target="_blank" rel="noreferrer">github.com/huilongbaba/MEMOKET_NOTE</a> · 复用了 Trilium 的设计与主题（AGPL-3.0），依赖清单见仓库 docs/third-party-notices.md
    </p>
  )
}

export default function SettingsPanel({ onClose, embedded = false }: { onClose?: () => void; embedded?: boolean }) {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [cfg, setCfg] = useState<ProviderConfig | null>(null)
  const [provider, setProvider] = useState<'local' | 'gpt'>('local')
  const [gptApiKey, setGptApiKey] = useState('')
  const [gptModel, setGptModel] = useState('gpt-4.1-mini')
  const [gptBaseUrl, setGptBaseUrl] = useState('https://api.openai.com/v1')
  const [asrBaseUrl, setAsrBaseUrl] = useState('')
  const [autoSync, setAutoSync] = useState(false)

  useEffect(() => {
    api.getProviderConfig().then((c) => {
      setCfg(c)
      setProvider(c.provider)
      setGptModel(c.gpt_model)
      setGptBaseUrl(c.gpt_base_url)
      setAsrBaseUrl(c.asr_base_url)
      setAutoSync(!!c.auto_sync_notes)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  async function save() {
    setSaving(true)
    try {
      const body: Parameters<typeof api.setProviderConfig>[0] = {
        provider, gpt_model: gptModel, gpt_base_url: gptBaseUrl,
        // 语音地址传空串就是「清掉、退回默认」——跟 key 不同，这里空是合法值
        asr_base_url: asrBaseUrl.trim(),
        auto_sync_notes: autoSync,
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
                {/* 看得见的字段名。**占位符不是名字**：填上字它就没了——实拍
                    （第 675 轮）这三个框填着 `gpt-5.6-luna`、`https://api.openai.com/v1`，
                    旁边一个字都没说这是什么。aria-label 管屏幕阅读器，这几行管眼睛。 */}
                <label className="muted" style={{ fontSize: 12 }}>API key</label>
                <input aria-label="GPT API key"
                  type="password"
                  placeholder={cfg?.gpt_api_key_set ? `已设置 ${cfg.gpt_api_key_preview}，留空则不改` : 'sk-...'}
                  value={gptApiKey}
                  onChange={(e) => setGptApiKey(e.target.value)}
                />
                <label className="muted" style={{ fontSize: 12, marginTop: 4 }}>模型名</label>
                <input aria-label="GPT 模型名"
                  placeholder="默认 gpt-4.1-mini"
                  value={gptModel}
                  onChange={(e) => setGptModel(e.target.value)}
                />
                <label className="muted" style={{ fontSize: 12, marginTop: 4 }}>API base URL</label>
                <input aria-label="GPT API base URL"
                  placeholder="默认 OpenAI 官方端点"
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

            {/* 语音服务地址。之前只能改 .env 重启；状态栏挂着「语音离线」、录音钮
                提示「在设置里检查语音服务地址」，设置里却没这一项。 */}
            <p className="kb-section-title" style={{ marginTop: 18 }}>语音服务</p>
            <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
              录音转写用的 whisper.cpp server 地址。留空用默认；改完保存，状态栏的「语音离线」会立刻重查。
            </p>
            <input aria-label="语音服务地址"
              placeholder={`默认 ${cfg?.asr_default_url ?? ''}`}
              value={asrBaseUrl}
              onChange={(e) => setAsrBaseUrl(e.target.value)}
            />

            {/* 看图那台。**摆出来是因为知情选择那一屏上写着「截图发到哪」**——
                说得出口的承诺必须看得见，否则就是一句安慰。它是部署配置，
                跟语音的默认地址一样只读。 */}
            <p className="kb-section-title" style={{ marginTop: 18 }}>看图（屏幕活动）</p>
            <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
              屏幕活动的截图只发到这一处，<b>跟上面选的写作供应商无关</b>——写作切到 GPT，截图也不会跟着出去。
            </p>
            <p className="mono-line">{cfg?.vision_model || '（未配置）'} @ {cfg?.vision_base_url || '（未配置）'}</p>

            <p className="kb-section-title" style={{ marginTop: 18 }}>笔记 ↔ 知识库</p>
            <label className="row" style={{ gap: 8, fontSize: 13, alignItems: 'center' }}>
              <input type="checkbox" checked={autoSync} onChange={(e) => setAutoSync(e.target.checked)} />
              笔记改动后自动同步到知识库
            </label>
            <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
              只对摄入过的笔记生效：停止编辑 2 分钟后、或切到别的笔记时，自动删掉上次抽的事实重新抽（你手工加的留着）。每次同步是一次模型调用。关着的话树上会用黄色 ⇡ 提醒你哪些改过没同步。
            </p>

            <button className="primary" onClick={save} disabled={saving} style={{ marginTop: 8 }}>
              {saving ? <span className="spinner" /> : '保存'}
            </button>
            {embedded && <UsageSection />}
          </div>
        )}
      </div>
    </div>
  )
}
