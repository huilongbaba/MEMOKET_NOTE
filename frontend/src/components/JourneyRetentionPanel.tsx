import { useCallback, useEffect, useRef, useState } from 'react'

import { journeyRetention, journeySetRetention, journeyWipeAll, type JourneyRetention } from '../api'
import { friendlyError } from '../util/friendlyError'
import { toast } from '../toast'
import Icon from './Icon'

/**
 * 「留多久」+「全部删掉」（docs/daily-journey-plan.md §8.3 ③、§8.4）。
 *
 * **为什么这一块非有不可**（第 779 轮 / P21）：在这之前这个功能**没有保留期**
 * ——`FRAME_KEEP_DAYS=3` 只管那张送给模型的大图，段落描述和缩略图一天都不删。
 * 也就是说这台机器上无限期堆着一份「这个人每天在屏幕上干了什么」的文字记录，
 * 而那一屏知情选择上**一个字都没提留多久**（计划写的是五条，少的正是这条）。
 *
 * 三件事摆在一起是有意的，它们回答的是同一个问题「我能不能把它抹掉」（§8.1）：
 *   · 留多久（能改，含「一直留着」——**是一个选项，不是默认**）
 *   · 现在盘上有多少（「30 天」是个抽象设置，「4 天 295 段 136MB」才能做决定）
 *   · 全部删掉（**删之前把要删的东西一条条列出来**）
 */

/** 天数写成人话。`0` = 一直留着。 */
export function sayKeep(days: number): string {
  if (!days) return '一直留着'
  if (days % 30 === 0 && days >= 30) return `${days / 30} 个月（${days} 天）`
  if (days % 7 === 0) return `${days / 7} 周（${days} 天）`
  return `${days} 天`
}

/** 体量写成人话。**不出现「0.0 MB」**——那读起来像坏了，而不是「没有东西」。 */
export function saySize(bytes: number): string {
  if (bytes <= 0) return '没占地方'
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
}

/** 「全部删掉」之前要说清楚删的是什么。**一句「确定吗」不算说清楚**：
 *  用户要知道这一下动的是几天、多少段、多少张图、几份日报、还有知识库里的记忆。 */
export function wipeLines(r: JourneyRetention): string[] {
  const out = [`${r.days} 天的记录（最早 ${r.oldest || '—'}）`,
               `${r.segments} 段，其中 ${r.described} 段有描述`]
  if (r.thumbs) out.push(`${r.thumbs} 张缩略图，连同还没删的原始截图`)
  if (r.reports) out.push(`${r.reports} 份写好的日报`)
  out.push('这些描述抽进知识库的那些记忆')
  out.push(`一共 ${saySize(r.bytes)}`)
  return out
}

export default function JourneyRetentionPanel({ onChanged }: { onChanged?: () => void }) {
  const [r, setR] = useState<JourneyRetention | null>(null)
  const [busy, setBusy] = useState(false)
  /** 「全部删掉」按下之后先摊开要删的东西——**确认框不是弹窗，是这一块自己展开**：
   *  系统弹窗只能塞一句话，而这里要列六行。 */
  const [confirming, setConfirming] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  const load = useCallback(() => { journeyRetention().then(setR).catch(() => setR(null)) }, [])
  useEffect(() => { load() }, [load])
  // 这一块住在页面最下面：展开出来的六行多半在屏幕外，不滚一下的话，
  // 用户点了「全部删掉」只看见按钮变了，读不到「会删掉什么」
  useEffect(() => { if (confirming) box.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }) }, [confirming])

  async function set(segment: number, thumb: number) {
    setBusy(true)
    try {
      const out = await journeySetRetention(segment, thumb)
      setR(out)
      const s = out.swept
      const gone = s?.days_removed?.length ?? 0
      // **改完当场清一遍，并把清掉了什么说出来**：一个「看不出有没有生效」的
      // 隐私开关跟没有一样。
      toast(gone || s?.thumbs_removed
        ? `留多久改好了——顺手清掉了${gone ? ` ${gone} 天` : ''}${s?.thumbs_removed ? ` ${s.thumbs_removed} 张缩略图` : ''}${s?.facts_removed ? `、${s.facts_removed} 条记忆` : ''}`
        : '留多久改好了——现在没有到期的记录')
      onChanged?.()
    } catch (e) { toast(friendlyError(e), 'error') } finally { setBusy(false) }
  }

  async function wipe() {
    setBusy(true)
    try {
      const out = await journeyWipeAll()
      setR(out)
      setConfirming(false)
      const s = out.swept
      toast(`删掉了 ${s?.days_removed?.length ?? 0} 天的屏幕活动${s?.facts_removed ? `，连带 ${s.facts_removed} 条记忆` : ''}`)
      onChanged?.()
    } catch (e) { toast(friendlyError(e), 'error') } finally { setBusy(false) }
  }

  if (!r) return null
  const fails = r.swept?.failures?.length ? r.swept.failures : (r.failures ?? [])

  return (
    <div className="journey-keep">
      <h3 className="kb-section-title">留多久</h3>
      <p className="muted journey-keep-why">
        到期的自己删掉，<b>连它抽进知识库的记忆一起删</b>。
        现在盘上有 <b>{r.days} 天 · {r.segments} 段 · {saySize(r.bytes)}</b>
        {r.oldest && `（最早 ${r.oldest}）`}。
      </p>

      <div className="journey-keep-rows">
        <label className="journey-keep-row">
          <span>段落描述</span>
          <select aria-label="段落描述留多久" value={r.segment_days} disabled={busy}
                  onChange={(e) => void set(Number(e.target.value), r.thumb_days)}>
            {r.segment_choices.map((d) => <option key={d} value={d}>{sayKeep(d)}</option>)}
          </select>
          <span className="muted">一句话描述 + 时间轴 + 那天的日报</span>
        </label>
        <label className="journey-keep-row">
          <span>缩略图</span>
          <select aria-label="缩略图留多久" value={r.thumb_days} disabled={busy}
                  onChange={(e) => void set(r.segment_days, Number(e.target.value))}>
            {r.thumb_choices.map((d) => <option key={d} value={d}>{sayKeep(d)}</option>)}
          </select>
          <span className="muted">回看时核对描述用的那张小图</span>
        </label>
        {/* 大图是**没得选**的一档：描述做完当场就删，这 3 天只是给「看图那台
            一直连不上」留的窗口。摆出来是因为「存在哪 / 留多久」这两句话要对得上。 */}
        <div className="journey-keep-row">
          <span>原始截图</span>
          <span className="journey-keep-fixed">最多 {r.frame_days} 天</span>
          <span className="muted">描述做完当场就删，没做完最多留这么久</span>
        </div>
      </div>

      {fails.length > 0 && (
        <p className="journey-keep-fail">
          <Icon n="bx-error" /> 有 {fails.length} 个文件没删掉，它们还在盘上：
          {fails.slice(0, 5).map((f, i) => <span key={i} className="mono-line">{f}</span>)}
        </p>
      )}

      {confirming ? (
        <div className="journey-keep-confirm" ref={box}>
          <b>删掉全部屏幕活动？这一下会删掉：</b>
          <ul>{wipeLines(r).map((l, i) => <li key={i}>{l}</li>)}</ul>
          <p className="muted">
            删完就真的没有了，没有回收站。
            <b>开关、不记这些、留多久这几样设置留着</b>——那是设置，不是记录。
          </p>
          <div className="row" style={{ gap: 6 }}>
            <button className="danger" disabled={busy} onClick={() => void wipe()}>
              {busy ? <span className="spinner" /> : <Icon n="bx-trash" />} 确认删掉这 {r.days} 天
            </button>
            <button onClick={() => setConfirming(false)}>先不删</button>
          </div>
        </div>
      ) : (
        <button className="linklike danger" disabled={busy || !r.days}
                title={r.days ? '' : '现在没有任何记录'}
                onClick={() => setConfirming(true)}>全部删掉</button>
      )}
    </div>
  )
}
