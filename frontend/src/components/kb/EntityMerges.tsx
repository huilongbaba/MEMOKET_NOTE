import { useCallback, useEffect, useState } from 'react'

import { decideEntityMerge, entityMergeCandidates, undoEntityMerge,
         type EntityMergeCandidate, type EntityMergeDecision } from '../../api'
import { toast, toastAction } from '../../toast'

/**
 * 「可能是同一个」——实体合并的收件箱（docs/kb-entities-plan.md 第二部分）。
 *
 * **为什么值得点**：实体页是按事实数排序的，而那些数字现在全是真值的一部分——
 * 自家产品 MemoCat 真实 189 条、列表上显示 93；Anker 真实 109、显示 37；
 * 用户自己被拆成五个（惠龙 / 汇龙 / 慧龙 / Hui Long / Huilong）。
 * **一个按错的数字排的列表，排序本身就是错的。**
 *
 * **为什么不自动合**：四条信号在真库上四到七成准，而 `德惠达`/`德威达` 是不是
 * 同一家、`安克莱` 是不是 Anker，**只有用户知道**。
 *
 * 每一对给的东西，是按「判起来要什么」定的，不是按「我有什么」：
 *   · 两边各两句原话——**没有原话是判不了的**；
 *   · 同时提到两个名字的句子（有的话）——判起来最快的东西；
 *   · 合并之后是多少条——那是这一下点击的收益。
 *
 * 五个答案里「拿不准」是正经答案：`elisa` 和 `Lisa` 一次都没同时出现过，
 * 两边都不能证明，逼人二选一只会换来乱猜（用户第 660 轮原话）。
 */
const WHY: Record<string, string> = {
  initials: '首字母缩写', translit: '音译', spelling: '拼写相近', substring: '一个包着另一个',
}

export default function EntityMerges({ onDone }: { onDone?: () => void }) {
  const [rows, setRows] = useState<EntityMergeCandidate[] | null>(null)
  const [decided, setDecided] = useState(0)
  const [busy, setBusy] = useState('')

  const load = useCallback(() => {
    entityMergeCandidates().then((d) => { setRows(d.candidates); setDecided(d.decided) })
      .catch(() => setRows([]))
  }, [])
  useEffect(load, [load])

  async function decide(c: EntityMergeCandidate, d: EntityMergeDecision) {
    const key = c.a + c.b
    setBusy(key)
    try {
      await decideEntityMerge(c.a, c.b, d, c.why)
      // 判完就从列表里拿掉：不重新拉整张表——用户在连着点，重排会让手底下的东西跳走
      setRows((r) => (r ?? []).filter((x) => x.a + x.b !== key))
      setDecided((n) => n + 1)
      // **「随时可撤」这句话得有地方兑现。** 连着点一屏，点错一下是常事，
      // 而这一对判完就从列表里消失了——没有这个撤销，那句话就是假的。
      const said = d === 'same' ? `合并了：${c.name_a} + ${c.name_b} → ${c.facts_total} 条`
        : d === 'drop_a' ? `「${c.name_a}」不再当实体`
          : d === 'drop_b' ? `「${c.name_b}」不再当实体`
            : d === 'unsure' ? `记下「拿不准」：${c.name_a} / ${c.name_b}`
              : `记下「不是」：${c.name_a} / ${c.name_b}`
      toastAction(said, '撤销', () => {
        void undoEntityMerge(c.a, c.b).then(() => {
          setRows((r) => [c, ...(r ?? [])])       // 放回最前面，用户刚才就在看它
          setDecided((n) => Math.max(0, n - 1))
          onDone?.()
        }).catch((e) => toast(e instanceof Error ? e.message : String(e), 'error'))
      }, 7000)
      onDone?.()
    } catch (e) { toast(e instanceof Error ? e.message : String(e), 'error') } finally { setBusy('') }
  }

  if (rows === null) return <p className="muted" style={{ fontSize: 12 }}>…</p>
  if (!rows.length) {
    return (
      <p className="muted" style={{ fontSize: 13 }}>
        没有待判的了{decided ? `（判过 ${decided} 对）` : ''}。库里新增内容之后可以再扫一次。
      </p>
    )
  }

  return (
    <div className="stack">
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>
        {rows.length} 对可能是同一个东西{decided ? ` · 判过 ${decided} 对` : ''}。
        <b>合并只影响显示和检索，知识库本身不动，随时可撤。</b>
      </p>
      {rows.map((c) => (
        <div key={c.a + c.b} className="card merge-card">
          <div className="merge-head">
            <span className="merge-side"><b>{c.name_a}</b> <span className="muted">{c.facts_a} 条</span></span>
            <span className="muted merge-eq">＝?</span>
            <span className="merge-side"><b>{c.name_b}</b> <span className="muted">{c.facts_b} 条</span></span>
            <span className="badge">{WHY[c.why] ?? c.why}</span>
            <span style={{ flex: 1 }} />
            <span className="muted" style={{ fontSize: 12 }}>合并后 {c.facts_total} 条</span>
          </div>

          {c.both.length > 0 ? (
            <div className="merge-both">
              <span className="muted">两个名字同时出现在这句话里：</span>
              {c.both.map((t, i) => <p key={i}>{t}</p>)}
            </div>
          ) : (
            <p className="muted merge-none">这两个名字从没同时出现过——两边都没有证据。</p>
          )}

          <div className="merge-samples">
            <div><span className="muted">{c.name_a}：</span>{(c.sample_a[0] ?? '（没有原话）')}</div>
            <div><span className="muted">{c.name_b}：</span>{(c.sample_b[0] ?? '（没有原话）')}</div>
          </div>

          {/* 三个主答案一行、两个「不该是实体」另起一行。**不靠 flex-wrap 碰运气**：
              名字一长就折，折出来的那一行长短还随名字变（实拍第三张卡片就折了）。 */}
          <div className="row" style={{ gap: 6, marginTop: 8 }}>
            <button className="primary" disabled={!!busy} onClick={() => void decide(c, 'same')}>是同一个</button>
            <button disabled={!!busy} onClick={() => void decide(c, 'different')}>不是</button>
            <button disabled={!!busy} onClick={() => void decide(c, 'unsure')}
                    title="两边都没有证据的时候，这是正经答案——记下来不再问，但跟「不是」分得开">拿不准</button>
          </div>
          <div className="row merge-drops" style={{ gap: 10 }}>
            <span className="muted">要是哪个压根不该算实体：</span>
            <button className="linklike" disabled={!!busy} onClick={() => void decide(c, 'drop_a')}>{c.name_a}</button>
            <button className="linklike" disabled={!!busy} onClick={() => void decide(c, 'drop_b')}>{c.name_b}</button>
          </div>
        </div>
      ))}
    </div>
  )
}
