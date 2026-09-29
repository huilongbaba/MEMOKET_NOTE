/** 灵动岛 · 拿主意（CompanionDecide）：在别的应用里选中一段，按热键，岛展开成一块「拿主意」的台面。
 *  什么都没选时用的是剪贴板里刚复制的那一样东西（origin 是 clipboard）：文字走同一套；图片先由 Gemini
 *  读成一两句（digest），台面上放缩略图，那句话替代引文，记下来 / 问 Claude 引的也是它。
 *
 *  三步都在后端（/api/desktop/decide）：Jev 判断这段是不是要拿主意的事 → Gemini 出候选（理由里引用知识库
 *  里召回的事实）→ Jev 给每个候选校准过的概率。不是决定题时先反问：三个「你可能想问的问题」，选了再走。
 *  这里只负责把结果摆清楚、让键盘走得通，**从不替用户动手**：记下来、变成待办、问 Claude、复制都要点一下。
 *
 *  诚实的状态一个都不省：没权限、没选中、看不出要选什么、知识库没记录、没有可靠数字就不显示数字。
 *  键盘：↑↓ 换高亮，Enter 选中（动作行出现），Esc 交给岛收起；「补一句背景」有字先清字，没字才收。 */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import * as api from '../api'
import type { DecideSelection } from '../desktop'
import Icon from './Icon'
import '../companion-decide.css'

export type DecidePhase = 'idle' | 'thinking' | 'ready' | 'error'

type Props = {
  /** 热键读到的选区；每按一次都是一个新对象，所以同一段文字也会重跑。 */
  request: DecideSelection | null
  /** 台面正在岛上显示（不是藏在别的标签后面）。 */
  active: boolean
  /** 记下来：一段 markdown 进正在写的笔记。 */
  onInsert: (text: string) => void
  /** 变成待办：候选的标题进今天的待办。 */
  onTask: (text: string) => void
  /** 问 Claude 展开：把题目、候选与概率放进会话的输入框。 */
  onAskClaude: (text: string) => void
  /** Esc：交给岛收起。 */
  onEscape: () => void
  /** 阶段变化：收起后岛上要显示「正在拿主意」「选项已备好 · N 个」；反问时 mode 是 questions，药丸不说「选项」。 */
  onPhase: (phase: DecidePhase, count: number, mode?: 'options' | 'questions') => void
  /** 双击 ⌃ 截图那条入口起来了没：空态里顺便说一句。 */
  tap?: boolean
  /** 实际注册成功的热键（键帽符号），空态那句用它；拿不到就写默认的 ⌥D。 */
  hotkey?: string
}

export const PERMISSION_NOTE = '读不到别的应用里的选区：系统设置 › 隐私与安全性 里，「辅助功能」和「自动化」都要允许 MEMOKET NOTE'
export const DEFAULT_HOTKEY_LABEL = '⌥D'
/** 「先选中……再按 ⌥D」：显示的是主进程实际注册成功的那个键，不写死。 */
export const TAP_LABEL = '⌃⌃'
export const emptyNote = (hotkey = DEFAULT_HOTKEY_LABEL, tap = false) => `先选中一段文字，或先复制一段文字 / 一张图片，再按 ${hotkey || DEFAULT_HOTKEY_LABEL}${tap ? `；或双击 ${TAP_LABEL} 框一块屏幕` : ''}`
export const EMPTY_NOTE = emptyNote()
/** Electron 的快捷键写法 → 键帽符号：Control+Shift+Space → ⌃⇧Space，Alt+D → ⌥D。 */
export function hotkeyLabel(accelerator: string): string {
  const symbols: Record<string, string> = { control: '⌃', ctrl: '⌃', alt: '⌥', option: '⌥', shift: '⇧', command: '⌘', cmd: '⌘', commandorcontrol: '⌘', super: '⌘', meta: '⌘', space: 'Space', return: '↩', enter: '↩', escape: 'Esc', esc: 'Esc', tab: '⇥' }
  return accelerator.split('+').map(part => part.trim()).filter(Boolean).map(part => symbols[part.toLowerCase()] ?? part.toUpperCase()).join('')
}
export const STALE_NOTE = '这次没读到新的选区，这是上一次的'
export const KEYS_HINT = '↑↓ 选 · ↵ 定 · esc 收起'
export const NO_FACTS_NOTE = '知识库里没有相关记录，只按这段文字判断'
export const NO_CHOICE_NOTE = '这段看不出要选什么'
export const QUESTIONS_LEAD = '这段更像信息。你想拿主意的是：'
const FLASH_MS = 2000
const QUOTE_LINE_MAX = 80
const ASK_TEXT_MAX = 600

const errorText = (error: unknown) => {
  const message = error instanceof Error ? error.message : String(error || '')
  if (/Failed to fetch|NetworkError|Load failed/i.test(message)) return '笔记服务暂时不可用，请稍后重试。'
  return message || '没拿到结果，请重试。'
}
const percent = (probability: number) => `${Math.round(Math.max(0, Math.min(1, probability)) * 100)}%`
/** 事实小片上只写序号 [1] [2]（同一篇笔记的事实 id 只差末尾几位，截头看不出区别）；标题里是原文，复制的是完整 [id]。 */
const ordinal = (facts: api.DecideFact[], id: string) => { const index = facts.findIndex(fact => fact.id === id); return index >= 0 ? String(index + 1) : Array.from(id).slice(-6).join('') }
/** 引用原文的第一行：多出来的行、超出的字，都用一个省略号交代。 */
function quoteLine(text: string) {
  const lines = text.split('\n').map(line => line.trim()).filter(Boolean)
  const first = Array.from(lines[0] || '')
  const clipped = first.length > QUOTE_LINE_MAX
  return (clipped ? first.slice(0, QUOTE_LINE_MAX).join('') : first.join('')) + (clipped || lines.length > 1 ? '…' : '')
}
/** 来源一行：选区写「来自 Safari」；剪贴板写「来自剪贴板」，知道当时前台是哪个应用就补在后面。 */
function sourceLabel(request: DecideSelection) {
  if (request.origin === 'screenshot') return request.source ? `截图 · ${request.source}` : '截图'
  if (request.origin === 'clipboard') return request.source ? `来自剪贴板 · ${request.source}` : '来自剪贴板'
  return request.source ? `来自 ${request.source}` : ''
}

export default function CompanionDecide({ request, active, onInsert, onTask, onAskClaude, onEscape, onPhase, hotkey, tap = false }: Props) {
  /** 跑之前就能判定的诚实状态：没权限、什么都没选。 */
  const [note, setNote] = useState<'permission' | 'empty' | ''>('')
  const [thinking, setThinking] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<api.DecideOut | null>(null)
  const [highlight, setHighlight] = useState(0)
  /** 高亮那张卡的动作行是否展开（Enter / 点卡片）。 */
  const [opened, setOpened] = useState(false)
  const [context, setContext] = useState('')
  /** 一闪而过的提示：已复制。 */
  const [flash, setFlash] = useState('')
  /** 热键按了但没读到新选区：把上次的结果留着，说明一句。 */
  const [stale, setStale] = useState(false)
  /** 台面上这份结果是对着哪份材料出的：热键空按一下（stale）时材料不换，图和 digest 还留在上面。 */
  const [material, setMaterial] = useState<typeof request>(null)
  const lastInput = useRef<api.DecideIn | null>(null)
  const controller = useRef<AbortController | null>(null)
  const live = useRef(true)
  const rootRef = useRef<HTMLElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const flashTimer = useRef(0)
  const phaseRef = useRef(onPhase)
  phaseRef.current = onPhase

  const run = useCallback((input: api.DecideIn) => {
    controller.current?.abort()
    const current = new AbortController()
    controller.current = current
    lastInput.current = input
    setNote('')
    setError('')
    setFlash('')
    setStale(false)
    setThinking(true)
    setOpened(false)
    phaseRef.current('thinking', 0)
    api.decide(input, current.signal).then(out => {
      // 被后来的一次盖掉的结果不算数——晚到的旧答案不能把新题的候选换掉。
      if (!live.current || current.signal.aborted) return
      setResult(out)
      setThinking(false)
      setHighlight(0)
      setOpened(false)
      phaseRef.current('ready', out.items.length, out.mode)
    }).catch((cause: unknown) => {
      if (!live.current || current.signal.aborted) return
      setError(errorText(cause))
      setThinking(false)
      phaseRef.current('error', 0)
    })
  }, [])

  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
      controller.current?.abort()
      window.clearTimeout(flashTimer.current)
      phaseRef.current('idle', 0)
    }
  }, [])

  const resultRef = useRef<api.DecideOut | null>(null)
  resultRef.current = result

  useEffect(() => {
    if (!request) return
    setContext('')
    setFlash('')
    setError('')
    setOpened(false)
    setHighlight(0)
    // 剪贴板里是图片时 text 是空串，但这不是「什么都没有」：图交给 Gemini 读。
    const text = request.text.trim() ? request.text : ''
    if (request.error === 'accessibility' || request.error === 'empty' || (!text && !request.image)) {
      controller.current?.abort()
      controller.current = null
      setThinking(false)
      // 没读到新选区、但上次的结果还在：留着它，说一句就好，不把人扔回空态。
      if (request.error !== 'accessibility' && resultRef.current) { setStale(true); setNote(''); phaseRef.current('ready', resultRef.current.items.length, resultRef.current.mode); return }
      setResult(null)
      setMaterial(null)
      lastInput.current = null
      setNote(request.error === 'accessibility' ? 'permission' : 'empty')
      phaseRef.current('idle', 0)
      return
    }
    setResult(null)
    setMaterial(request)
    run({ text, ...(request.image ? { image: request.image } : {}), ...(request.source ? { source: request.source } : {}), mode: 'auto' })
  }, [request, run])

  // 热键一按，焦点就到台面上：想的那两三秒里 Esc 也要能收起。正在补背景的输入框不被打断。
  useEffect(() => {
    if (!request || !active || !document.hasFocus()) return
    if (document.activeElement instanceof HTMLInputElement && rootRef.current?.contains(document.activeElement)) return
    rootRef.current?.focus()
  }, [request, active])

  // 结果到了就把焦点放到台面上，↑↓ / Enter 立刻可用；正在补背景的输入框不被打断。
  useEffect(() => {
    if (!result || thinking || !active || !document.hasFocus()) return
    if (document.activeElement instanceof HTMLInputElement && rootRef.current?.contains(document.activeElement)) return
    rootRef.current?.focus()
  }, [result, thinking, active])

  // 动作行一出现，焦点落在第一个动作上：再按一次 Enter 就是「记下来」。
  useEffect(() => {
    if (!opened) return
    listRef.current?.querySelector<HTMLButtonElement>('[data-highlight="true"] .dc-decide-act')?.focus()
  }, [opened, highlight])

  function showFlash(text: string) {
    setFlash(text)
    window.clearTimeout(flashTimer.current)
    flashTimer.current = window.setTimeout(() => { if (live.current) setFlash('') }, FLASH_MS)
  }

  function copyText(text: string, done: string) {
    const clip = typeof navigator === 'undefined' ? undefined : navigator.clipboard
    if (!clip || typeof clip.writeText !== 'function') { showFlash('这里无法复制'); return }
    clip.writeText(text)
      .then(() => { if (live.current) showFlash(done) })
      .catch(() => { if (live.current) showFlash('这里无法复制') })
  }

  function move(next: number) {
    setHighlight(next)
    setOpened(false)
    if (document.activeElement instanceof HTMLInputElement) return
    listRef.current?.querySelectorAll<HTMLButtonElement>('.dc-decide-pick')[next]?.focus()
  }

  /** 选中一张卡：候选模式展开动作行；反问模式则带着那个问题重跑。 */
  function select(index: number, toggle: boolean) {
    const item = result?.items[index]
    if (!result || !item) return
    if (result.mode === 'questions') { ask(item.label); return }
    setHighlight(index)
    setOpened(current => toggle && index === highlight ? !current : true)
  }

  function ask(question: string) {
    const base = lastInput.current
    if (!base) return
    run({ text: base.text, ...(base.image ? { image: base.image } : {}), ...(base.source ? { source: base.source } : {}), ...(base.context ? { context: base.context } : {}), question, mode: 'options' })
  }

  function rerunWithContext() {
    const value = context.trim()
    const base = lastInput.current
    if (!value || !base) return
    run({ ...base, context: value })
  }

  function retry() { if (lastInput.current) run(lastInput.current) }

  /** 引的原文：选中 / 剪贴板里的文字；剪贴板里是图片时，引 Gemini 从图里读出来的那句。 */
  const fromImage = !!material?.image && !material.text.trim()
  const quoted = fromImage ? result?.digest || '' : material?.text || ''

  function noteBlock(item: api.DecideItem) {
    const cites = item.factIds.map(id => `[${id}]`).join(' ')
    return `> ${quoteLine(quoted)}\n\n**决定：** ${item.label}\n${item.why}${cites ? ` ${cites}` : ''}`
  }

  function askText(item: api.DecideItem) {
    if (!result || !material) return item.label
    const text = Array.from(quoted.trim())
    const quote = (text.length > ASK_TEXT_MAX ? text.slice(0, ASK_TEXT_MAX).join('') + '…' : text.join('')).split('\n').map(line => `> ${line}`)
    const numbers = result.scorer !== 'none'
    const source = sourceLabel(material)
    const lines = ['帮我把这个决定展开想想。', '', fromImage ? `原文（${material?.origin === 'screenshot' ? '截图' : '剪贴板图片'}，Gemini 读出）：` : `原文${source ? `（${source}）` : ''}：`, ...quote, '']
    if (result.frame) lines.push(`题目：${result.frame}`)
    lines.push('候选：', ...result.items.map((entry, index) => `${index + 1}. ${entry.label}${numbers ? `（${percent(entry.probability)}）` : ''}${entry.why ? ` — ${entry.why}` : ''}`))
    lines.push('', `先展开「${item.label}」：它的利弊、还要确认什么、什么情况下该换别的。`)
    return lines.join('\n')
  }

  function onKey(event: KeyboardEvent<HTMLElement>) {
    if (event.nativeEvent.isComposing) return
    const target = event.target as HTMLElement
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      onEscape()
      return
    }
    const count = result?.items.length ?? 0
    if (!count || thinking) return
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      move((highlight + (event.key === 'ArrowDown' ? 1 : -1) + count) % count)
      return
    }
    // 按钮和输入框自己处理 Enter（按钮的 Enter 就是点击）；只有落在台面 / 卡片上的 Enter 才算「选中」。
    if (event.key === 'Enter' && !target.closest('button, input, textarea, a')) {
      event.preventDefault()
      select(highlight, false)
    }
  }

  const numbers = !!result && result.scorer !== 'none'
  const facts = new Map((result?.facts || []).map(fact => [fact.id, fact]))
  const showQuote = !!material && !note
  const canRerun = !!(result || error)
  const skeleton = thinking && !result
  const quoteText = material?.text.trim() ? material.text : ''
  /** 图片的 digest 要等结果到了才有；在想的那几秒图下面什么都不写，不编。文字请求不看 digest。 */
  const digest = fromImage && result?.digest ? result.digest : ''
  const source = material ? sourceLabel(material) : ''

  return <section ref={rootRef} className="dc-decide" aria-label="拿主意" tabIndex={-1} onKeyDown={onKey}>
    {showQuote && <header className="dc-decide-quote">
      {material.image && <img className="dc-decide-image" src={material.image} alt={material.origin === 'screenshot' ? '框下来的那块屏幕' : '剪贴板里的图片'} />}
      {quoteText && <p className="dc-decide-text" title={quoteText}>{quoteText}</p>}
      {digest && <p className="dc-decide-digest" title={digest}><span className="dc-decide-digest-lead">图里说的是</span>{digest}</p>}
      {source && <span className="dc-decide-source">{source}</span>}
    </header>}
    {thinking && <div className="dc-decide-progress" role="status" aria-label="正在拿主意"><i /></div>}
    {skeleton && <ul className="dc-decide-skeleton" aria-hidden="true"><li /><li /><li /></ul>}
    {note === 'permission' && <div className="dc-decide-state"><Icon n="bx-lock" /><p>{PERMISSION_NOTE}</p></div>}
    {(note === 'empty' || !request) && <div className="dc-decide-state"><p>{emptyNote(hotkey, tap)}</p></div>}
    {error && <div className="dc-decide-state" role="alert"><Icon n="bx-error" /><p>{error}</p><button type="button" className="dc-decide-retry" onClick={retry}>重试</button></div>}
    {result && !error && <>
      <div className="dc-decide-head">
        <p className="dc-decide-frame">{result.mode === 'questions' ? QUESTIONS_LEAD : result.frame || '要拿主意的是'}</p>
        {numbers && <span className="dc-decide-scorer" title={result.scorer === 'jev' ? `概率由 Jev 校准（${result.model}）` : '没有 Jev 密钥，概率是模型的估计'}>{result.scorer === 'jev' ? 'Jev' : '模型估计'}</span>}
        {result.items.length > 0 && <span className="dc-decide-keys" aria-hidden="true">{KEYS_HINT}</span>}
      </div>
      {stale && <p className="dc-decide-note">{STALE_NOTE}</p>}
      {result.items.length === 0 ? <p className="dc-decide-note">{NO_CHOICE_NOTE}</p>
        : <ul ref={listRef} className="dc-decide-list" aria-label={result.mode === 'questions' ? '你可能想问的' : '候选'} aria-busy={thinking}>
          {result.items.map((item, index) => {
            const current = index === highlight
            return <li key={item.id} className="dc-decide-card" data-highlight={current} aria-current={current ? 'true' : undefined} style={{ '--dc-i': index } as React.CSSProperties}>
              <button type="button" className="dc-decide-pick" aria-expanded={result.mode === 'options' ? current && opened : undefined} onClick={() => select(index, true)}>
                <span className="dc-decide-label">{item.label}</span>
                {numbers && <span className="dc-decide-pct">{percent(item.probability)}</span>}
                {item.why && <span className="dc-decide-why">{item.why}</span>}
                {numbers && result.mode === 'options' && <span className="dc-decide-bar" style={{ '--dc-p': Math.max(0, Math.min(1, item.probability)) } as React.CSSProperties}><i /></span>}
              </button>
              {item.factIds.length > 0 && <span className="dc-decide-facts">
                {item.factIds.map(id => <button key={id} type="button" className="dc-decide-fact" title={facts.get(id)?.text || id} aria-label={`引用 ${id}：${facts.get(id)?.text || ''}`} onClick={() => copyText(`[${id}]`, `已复制引用 [${id}]`)}>[{ordinal(result.facts, id)}]</button>)}
              </span>}
              {result.mode === 'options' && current && opened && <div className="dc-decide-actions">
                <button type="button" className="dc-decide-act" title="作为一段引用与结论写进正在写的笔记" onClick={() => onInsert(noteBlock(item))}><Icon n="bx-note" />记下来</button>
                <button type="button" className="dc-decide-act" title="把这个选项加进今天的待办" onClick={() => onTask(item.label)}><Icon n="bx-list-check" />变成待办</button>
                <button type="button" className="dc-decide-act" title="把题目、候选和概率放进会话，让 Claude 展开" onClick={() => onAskClaude(askText(item))}><Icon n="bx-message-dots" />问 Claude 展开</button>
                <button type="button" className="dc-decide-act" title="复制这个选项和理由" onClick={() => copyText(`${item.label}\n${item.why}`, '已复制')}><Icon n="bx-copy" />复制</button>
              </div>}
            </li>
          })}
        </ul>}
      {(!result.grounded || !result.facts.length) && <p className="dc-decide-note">{NO_FACTS_NOTE}</p>}
    </>}
    {flash && <p className="dc-decide-note" role="status">{flash}</p>}
    {canRerun && <form className="dc-decide-context" onSubmit={event => { event.preventDefault(); rerunWithContext() }}>
      <Icon n="bx-subdirectory-right" />
      <input aria-label="补一句背景" placeholder="补一句背景…" maxLength={400} value={context} onChange={event => setContext(event.target.value)}
        onKeyDown={event => {
          if (event.nativeEvent.isComposing) return
          if (event.key === 'Enter') { event.preventDefault(); event.stopPropagation(); rerunWithContext(); return }
          if (event.key !== 'Escape') return
          event.preventDefault()
          event.stopPropagation()
          if (context) setContext('')
          else onEscape()
        }} />
    </form>}
  </section>
}
