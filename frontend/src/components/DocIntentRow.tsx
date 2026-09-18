/**
 * 标题下面那一行「这篇要干什么」（Doc Intent，docs/agent-native-editor.md §3.1）。
 *
 * 为什么在标题下面而不是 ribbon 的一个页签：它是这篇的**前提**，不是可有可无的属性。
 * 判据 3 说「用户说的是我要什么」——这一行就是「我要什么」，写一次，之后每个按钮都按它办。
 * 三个字段就地可编辑（无边框输入，跟标题一个做法：插入符就是焦点指示）；
 * 预填的带一个「预填」小标，改一个字它就变成你的。
 * 正文永远 `--fg`：这里三个值是正文级的内容，标签才是元信息（灰）。
 */
import { useEffect, useState } from 'react'
import { INTENT_FIELD_MAX, INTENT_LABEL, INTENT_PLACEHOLDER, type DocIntent } from '../util/docIntent'

const KEYS = ['goal', 'reader', 'done'] as const

export default function DocIntentRow({ intent, onChange }: {
  intent: DocIntent
  /** 用户改了任何一个字段（已经标成 source=user） */
  onChange: (next: DocIntent) => void
}) {
  // 本地一份：输入时逐键更新本地，失焦 / 停 800ms 才往上报（上层会落库）
  const [draft, setDraft] = useState<DocIntent>(intent)
  useEffect(() => { setDraft(intent) }, [intent])
  const [dirty, setDirty] = useState(false)
  useEffect(() => {
    if (!dirty) return
    const t = setTimeout(() => { setDirty(false); onChange({ ...draft, source: 'user' }) }, 800)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, dirty])
  const edit = (k: typeof KEYS[number], v: string) => { setDraft((d) => ({ ...d, [k]: v.slice(0, INTENT_FIELD_MAX) })); setDirty(true) }
  const commit = () => { if (dirty) { setDirty(false); onChange({ ...draft, source: 'user' }) } }

  return (
    <div className="doc-intent" role="group" aria-label="这篇要干什么">
      <span className="doc-intent-head" title="这篇的前提：骨架、续写、润色、校验、排版都先看这一行。写一次，不用每个按钮再说一遍。">这篇要干什么</span>
      {KEYS.map((k) => (
        <label key={k} className="doc-intent-field">
          <span className="doc-intent-label">{INTENT_LABEL[k]}</span>
          <input
            className="doc-intent-input"
            value={draft[k]}
            placeholder={INTENT_PLACEHOLDER[k]}
            aria-label={INTENT_LABEL[k]}
            onChange={(e) => edit(k, e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); (e.target as HTMLInputElement).blur() } }}
          />
        </label>
      ))}
      {draft.source === 'prefill' && !dirty && (
        <span className="doc-intent-src" title="按标题预填的（零模型）。改一个字就是你的，之后标题再变也不覆盖。">预填</span>
      )}
    </div>
  )
}
