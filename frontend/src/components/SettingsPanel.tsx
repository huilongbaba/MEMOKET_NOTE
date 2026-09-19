import { useEffect, useState } from 'react'
import { friendlyError } from '../util/friendlyError'
import * as api from '../api'
import type { ProviderConfig } from '../api'
import { toast } from '../toast'
import { applyTheme, canSwitchTheme, getTheme, type Theme } from '../theme'
import Icon from './Icon'

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
      <div className="row" style={{ gap: 14, flexWrap: 'wrap', fontSize: 'var(--t-md)' }}>
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
      <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: '4px 0 0' }}>
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
            <Icon n={o.icon} /> {o.label}
          </button>
        ))}
      </div>
      {!canSwitchTheme() && <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: '4px 0 0' }}>浏览器里只能跟随系统；桌面版可以固定浅色 / 深色。</p>}
    </>
  )
}

/**
 * LLM 供应商设置：本地模型 or OpenAI 兼容端点。全局设置，不分用户——切了之后写作
 * 三件套/续写/知识库抽取/实体去重全部跟着换，不用重启后端。
 *
 * 本地模型免费但慢（实测批量任务单次调用常见 10-45s）；OpenAI 兼容那档需要自己的
 * API key、按量计费，但通常快很多——两者的取舍留给用户自己判断，这里
 * 只负责让切换这件事简单、随时能切回去。
 *
 * **P19 #1**：第一天用户打开装好的包，原来「本地模型」这一档被选中却**没有地址栏**，
 * 状态栏和每个 AI 按钮都报 `LLM 不可达 (http://192.168.77.8:8080/v1)`——一个他没有的
 * 内网 IP（P17 #1 实拍 `p17-1-new-light` / `p17-7-new-light-settings`）。现在：
 *   · 本地模型有地址 / 模型名 / key 三栏，placeholder 是本机默认（`http://127.0.0.1:11434/v1`）；
 *   · OpenAI 兼容有 base_url / key / 模型名三栏；
 *   · 每一栏后面一个「测一下」——后端真发一次 `/models`（拿不到再发一次最小 completion），
 *     结果当场显示，不用先保存、也不用回去点一个 AI 按钮才知道配对没有；
 *   · 看图 / 语音各自一栏，看图默认「跟着写作模型走」，勾掉才单独配；
 *   · 没配过模型时顶上一条「还没配模型」的提示（跟状态栏那行红字同一件事）。
 */

/** 一栏的「测一下」按钮 + 结果行（P19 #1）。**结果是这一次真连出来的**：ok 绿、失败红，
 *  带地址、带耗时，失败时把原因说清（连不上 / key 不对 / 没这个模型）。 */
function TestButton({ label = '测一下', disabled, run }: {
  label?: string
  disabled?: boolean
  run: () => Promise<api.ProviderTest>
}) {
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<api.ProviderTest | null>(null)
  return (
    <>
      <div className="row" style={{ gap: 8, marginTop: 6 }}>
        <button className="chip chip-action" disabled={busy || disabled}
                title={disabled ? '先把地址填上' : '真连一次这个地址，结果显示在下面'}
                onClick={async () => {
                  setBusy(true); setRes(null)
                  try { setRes(await run()) } catch (e) { setRes({ ok: false, message: '测不了：' + friendlyError(e), models: [], model_found: null, elapsed_ms: 0 }) } finally { setBusy(false) }
                }}>
          {busy ? <span className="spinner" /> : <Icon n="bx-link" />} {label}
        </button>
        {busy && <span className="muted" style={{ fontSize: 'var(--t-sm)' }}>正在连…</span>}
      </div>
      {res && (
        <p className={'probe-result' + (res.ok ? ' ok' : ' bad')}>
          <Icon n={res.ok ? 'bx-check-circle' : 'bx-error'} /> {res.message}
        </p>
      )}
    </>
  )
}

/** 设置页最底下的出处行：AGPL §13 要求向使用者提供源码，仓库地址就放在这。 */
export function AboutLine() {
  return (
    <p className="muted" style={{ fontSize: 'var(--t-xs)', marginTop: 28 }}>
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
  // 本地模型那一档自己的三栏（P19 #1）
  const [localBaseUrl, setLocalBaseUrl] = useState('')
  const [localModel, setLocalModel] = useState('')
  const [localApiKey, setLocalApiKey] = useState('')
  // 看图：默认跟着写作模型走；勾掉才单独配
  const [visionOwn, setVisionOwn] = useState(false)
  const [visionBaseUrl, setVisionBaseUrl] = useState('')
  const [visionModel, setVisionModel] = useState('')
  const [visionApiKey, setVisionApiKey] = useState('')

  useEffect(() => {
    api.getProviderConfig().then((c) => {
      setCfg(c)
      setProvider(c.provider)
      setGptModel(c.gpt_model)
      setGptBaseUrl(c.gpt_base_url)
      setAsrBaseUrl(c.asr_base_url)
      setAutoSync(!!c.auto_sync_notes)
      setLocalBaseUrl(c.local_base_url)
      setLocalModel(c.local_model)
      setVisionOwn(!c.vision_follows_llm)
      setVisionBaseUrl(c.vision_base_url)
      setVisionModel(c.vision_model)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  // 「测一下」当场用输入框里的值，不是已保存的那份——用户填完就想知道对不对，不该逼他先保存
  const localUrlNow = localBaseUrl.trim() || cfg?.local_default_url || ''
  const localModelNow = localModel.trim() || cfg?.local_default_model || ''
  const visionUrlNow = visionOwn ? visionBaseUrl.trim() : (provider === 'gpt' ? gptBaseUrl.trim() : localUrlNow)
  const visionModelNow = visionOwn ? visionModel.trim() : (provider === 'gpt' ? gptModel.trim() : localModelNow)

  async function save() {
    setSaving(true)
    try {
      const body: Parameters<typeof api.setProviderConfig>[0] = {
        provider, gpt_model: gptModel, gpt_base_url: gptBaseUrl,
        // 语音地址传空串就是「清掉、退回默认」——跟 key 不同，这里空是合法值
        asr_base_url: asrBaseUrl.trim(),
        auto_sync_notes: autoSync,
        // 本地模型三栏同理：地址 / 模型名传空串 = 清掉退回默认（P19 #1）
        local_base_url: localBaseUrl.trim(),
        local_model: localModel.trim(),
        // 「跟着写作模型走」= 把看图那两栏清空，后端据此回退（`get_active_vision_config`）
        vision_base_url: visionOwn ? visionBaseUrl.trim() : '',
        vision_model: visionOwn ? visionModel.trim() : '',
      }
      // 空字符串不传——传了会被当成"清空 key"（后端语义：不传=保留原值，
      // 传空字符串=真的清空），用户只是切换 provider 没重新填 key 时
      // 不该把已经存的 key 误删掉
      if (gptApiKey.trim()) body.gpt_api_key = gptApiKey.trim()
      if (localApiKey.trim()) body.local_api_key = localApiKey.trim()
      if (visionOwn && visionApiKey.trim()) body.vision_api_key = visionApiKey.trim()
      const updated = await api.setProviderConfig(body)
      setCfg(updated)
      setGptApiKey(''); setLocalApiKey(''); setVisionApiKey('')
      toast(updated.configured
        ? `已切换到${updated.provider === 'gpt' ? 'OpenAI 兼容' : '本地模型'}：${updated.active_model || '（模型名还没填）'} @ ${updated.active_url}`
        : '保存了，但模型还没配全——填上地址和模型名，AI 功能才用得了')
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
        className={embedded ? '' : 'panel-dialog settings-dialog'}
        onClick={(e) => e.stopPropagation()}
      >
        {!embedded && (
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <h2 style={{ margin: 0 }}><Icon n="bx-cog" /> 设置</h2>
            <button className="icon-btn" title="关闭（Esc）" aria-label="关闭" onClick={onClose}><Icon n="bx-x" /></button>
          </div>
        )}

        {loading ? (
          <p className="muted"><span className="spinner" /> 加载中…</p>
        ) : (
          <div className="stack" style={{ marginTop: 12 }}>
            {embedded && <AppearanceSection />}
            {/* 还没配过模型（出厂默认）：**这一条排在最上面**——第一天用户打开设置页就是为了这件事，
                而原来这一页从头到尾没有一句话告诉他「你还没配」（P19 #1 / P17 #1）。 */}
            {cfg && !cfg.configured && (
              <p className="probe-result bad" style={{ marginBottom: 4 }}>
                <Icon n="bx-error" /> 还没配模型，AI 功能全都用不了。下面选一档填上，填完点「测一下」看通不通，再保存。
              </p>
            )}
            <h3 className="kb-section-title">写作模型</h3>
            <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: '2px 0 8px' }}>
              续写、修订、知识库抽取这些功能背后调用的模型——本地模型免费但慢，
              OpenAI 兼容那档（OpenAI / 各家网关 / 自建代理）需要自己的 API key，通常快很多。
            </p>

            <label className="row" style={{ gap: 8, cursor: 'pointer' }}>
              <input type="radio" checked={provider === 'local'}
                    onChange={() => setProvider('local')} />
              <span>本地模型</span>
            </label>

            {provider === 'local' && (
              <div className="stack" style={{ marginTop: 4, paddingLeft: 24 }}>
                {/* **这三栏是 P19 #1 的正题**：原来这一档被默认选中却一个输入框都没有，
                    地址只能改 `.env` 重启，装好的包里根本改不了。 */}
                <label className="muted" style={{ fontSize: 'var(--t-sm)' }}>模型地址（OpenAI 兼容）</label>
                <input aria-label="本地模型地址"
                  placeholder={`默认 ${cfg?.local_default_url ?? 'http://127.0.0.1:11434/v1'}`}
                  value={localBaseUrl}
                  onChange={(e) => setLocalBaseUrl(e.target.value)}
                />
                <p className="muted" style={{ fontSize: 'var(--t-xs)', margin: 0 }}>
                  Ollama 是 <code>http://127.0.0.1:11434/v1</code>，LM Studio 是 <code>http://127.0.0.1:1234/v1</code>，
                  llama.cpp / vLLM 填它们自己的 <code>/v1</code>。留空用默认。
                </p>
                <label className="muted" style={{ fontSize: 'var(--t-sm)', marginTop: 4 }}>模型名</label>
                <input aria-label="本地模型名"
                  placeholder={cfg?.local_default_model ? `默认 ${cfg.local_default_model}` : '比如 qwen3:8b'}
                  value={localModel}
                  onChange={(e) => setLocalModel(e.target.value)}
                />
                <label className="muted" style={{ fontSize: 'var(--t-sm)', marginTop: 4 }}>API key（本地一般不用填）</label>
                <input aria-label="本地模型 API key"
                  type="password"
                  placeholder={cfg?.local_api_key_set ? '已设置，留空则不改' : '大多数本地服务不校验，留空即可'}
                  value={localApiKey}
                  onChange={(e) => setLocalApiKey(e.target.value)}
                />
                <TestButton disabled={!localUrlNow}
                  run={() => api.testProvider({ kind: 'llm', base_url: localUrlNow, model: localModelNow, api_key: localApiKey.trim() || undefined, saved_key_of: 'local' })} />
              </div>
            )}

            <label className="row" style={{ gap: 8, cursor: 'pointer' }}>
              <input type="radio" checked={provider === 'gpt'}
                    onChange={() => setProvider('gpt')} />
              <span>OpenAI 兼容（OpenAI / 各家网关）</span>
            </label>

            {provider === 'gpt' && (
              <div className="stack" style={{ marginTop: 4, paddingLeft: 24 }}>
                {/* 看得见的字段名。**占位符不是名字**：填上字它就没了——实拍
                    （第 675 轮）这三个框填着 `gpt-5.6-luna`、`https://api.openai.com/v1`，
                    旁边一个字都没说这是什么。aria-label 管屏幕阅读器，这几行管眼睛。 */}
                <label className="muted" style={{ fontSize: 'var(--t-sm)' }}>API key</label>
                <input aria-label="GPT API key"
                  type="password"
                  placeholder={cfg?.gpt_api_key_set ? `已设置 ${cfg.gpt_api_key_preview}，留空则不改` : 'sk-...'}
                  value={gptApiKey}
                  onChange={(e) => setGptApiKey(e.target.value)}
                />
                <label className="muted" style={{ fontSize: 'var(--t-sm)', marginTop: 4 }}>模型名</label>
                <input aria-label="GPT 模型名"
                  placeholder="默认 gpt-4.1-mini"
                  value={gptModel}
                  onChange={(e) => setGptModel(e.target.value)}
                />
                <label className="muted" style={{ fontSize: 'var(--t-sm)', marginTop: 4 }}>API base URL</label>
                <input aria-label="GPT API base URL"
                  placeholder="默认 OpenAI 官方端点"
                  value={gptBaseUrl}
                  onChange={(e) => setGptBaseUrl(e.target.value)}
                />
                <TestButton disabled={!gptBaseUrl.trim()}
                  run={() => api.testProvider({ kind: 'llm', base_url: gptBaseUrl.trim(), model: gptModel.trim(), api_key: gptApiKey.trim() || undefined, saved_key_of: 'gpt' })} />
                {!cfg?.gpt_api_key_set && !gptApiKey.trim() && (
                  <p className="muted" style={{ fontSize: 'var(--t-sm)', color: 'var(--del)' }}>
                    还没设置 API key，保存后选中这一档也用不了，会自动退回本地模型。
                  </p>
                )}
              </div>
            )}

            {/* 语音服务地址。之前只能改 .env 重启；状态栏挂着「语音离线」、录音钮
                提示「在设置里检查语音服务地址」，设置里却没这一项。 */}
            <p className="kb-section-title" style={{ marginTop: 18 }}>语音服务</p>
            <p className="muted" style={{ fontSize: 'var(--t-sm)', marginTop: 0 }}>
              录音转写用的 whisper.cpp server 地址。留空用默认；改完保存，状态栏的「语音离线」会立刻重查。
            </p>
            <input aria-label="语音服务地址"
              placeholder={`默认 ${cfg?.asr_default_url ?? ''}`}
              value={asrBaseUrl}
              onChange={(e) => setAsrBaseUrl(e.target.value)}
            />
            <TestButton disabled={!(asrBaseUrl.trim() || cfg?.asr_default_url)}
              run={() => api.testProvider({ kind: 'asr', base_url: asrBaseUrl.trim() || (cfg?.asr_default_url ?? '') })} />

            {/* 看图那台。**摆出来是因为知情选择那一屏上写着「截图发到哪」**——
                说得出口的承诺必须看得见，否则就是一句安慰。
                P19 #1：原来这里写死 .env 里那个内网地址、只读，第一天用户改不了也用不上；
                现在默认**跟着写作模型走**（配好一个就能用），要分开走再勾掉单独填。 */}
            <p className="kb-section-title" style={{ marginTop: 18 }}>看图（屏幕活动 / 图片转表格）</p>
            <label className="row" style={{ gap: 8, fontSize: 'var(--t-md)', alignItems: 'center' }}>
              <input type="checkbox" checked={!visionOwn} onChange={(e) => setVisionOwn(!e.target.checked)} />
              跟着上面的写作模型走
            </label>
            {!visionOwn ? (
              <>
                <p className="muted" style={{ fontSize: 'var(--t-sm)', marginTop: 0 }}>
                  截图和图片会发到<b>写作模型那一台</b>。要让截图只留在本机 / 内网，就勾掉这一项，单独填一个本地的带视觉的模型。
                </p>
                <p className="mono-line">{cfg?.vision_active_model || '（模型名还没填）'} @ {cfg?.vision_active_url || '（未配置）'}</p>
              </>
            ) : (
              <div className="stack" style={{ marginTop: 4 }}>
                <p className="muted" style={{ fontSize: 'var(--t-sm)', marginTop: 0 }}>
                  截图只发到这一处，<b>跟上面选的写作供应商无关</b>——写作切到 OpenAI，截图也不会跟着出去。
                </p>
                <label className="muted" style={{ fontSize: 'var(--t-sm)' }}>看图模型地址</label>
                <input aria-label="看图模型地址"
                  placeholder="http://127.0.0.1:11434/v1"
                  value={visionBaseUrl}
                  onChange={(e) => setVisionBaseUrl(e.target.value)}
                />
                <label className="muted" style={{ fontSize: 'var(--t-sm)', marginTop: 4 }}>看图模型名（要带视觉）</label>
                <input aria-label="看图模型名"
                  placeholder="比如 qwen2.5vl:7b"
                  value={visionModel}
                  onChange={(e) => setVisionModel(e.target.value)}
                />
                <label className="muted" style={{ fontSize: 'var(--t-sm)', marginTop: 4 }}>API key（本地一般不用填）</label>
                <input aria-label="看图 API key"
                  type="password"
                  placeholder={cfg?.vision_api_key_set ? '已设置，留空则不改' : '留空即可'}
                  value={visionApiKey}
                  onChange={(e) => setVisionApiKey(e.target.value)}
                />
              </div>
            )}
            <TestButton disabled={!visionUrlNow}
              run={() => api.testProvider({ kind: 'vision', base_url: visionUrlNow, model: visionModelNow, api_key: visionApiKey.trim() || undefined, saved_key_of: visionOwn ? 'vision' : (provider === 'gpt' ? 'gpt' : 'local') })} />

            <p className="kb-section-title" style={{ marginTop: 18 }}>笔记 ↔ 知识库</p>
            <label className="row" style={{ gap: 8, fontSize: 'var(--t-md)', alignItems: 'center' }}>
              <input type="checkbox" checked={autoSync} onChange={(e) => setAutoSync(e.target.checked)} />
              笔记改动后自动同步到知识库
            </label>
            <p className="muted" style={{ fontSize: 'var(--t-sm)', marginTop: 0 }}>
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
