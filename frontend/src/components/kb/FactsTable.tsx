import { useEffect, useState } from 'react'

import { kbDashboard, memoryFacts, type FactsFilter, type FactsPage, type KbDashboard } from '../../api'
import { FactList, KbSection, Pager, type KbActions } from './KbBits'

const LIMIT = 50

/** 事实表：一行过滤器 + 列表 + 分页。过滤条件从 id 的查询串来（kb:facts?kind=plan）。 */
export default function FactsTable({ query, actions }: { query: string; actions: KbActions }) {
  const [filter, setFilter] = useState<FactsFilter>(() => Object.fromEntries(new URLSearchParams(query)) as FactsFilter)
  const [page, setPage] = useState<FactsPage | null>(null)
  const [meta, setMeta] = useState<KbDashboard | null>(null)
  useEffect(() => { setFilter(Object.fromEntries(new URLSearchParams(query)) as FactsFilter) }, [query])
  useEffect(() => { kbDashboard().then(setMeta).catch(() => {}) }, [])
  useEffect(() => {
    let alive = true
    memoryFacts({ ...filter, limit: LIMIT, offset: filter.offset ?? 0 }).then((p) => { if (alive) setPage(p) }).catch(() => {})
    return () => { alive = false }
  }, [filter])
  const set = (k: keyof FactsFilter, v: string) => setFilter((f) => ({ ...f, [k]: v || undefined, offset: 0 }))

  return (
    <div className="kb-page">
      <div className="kb-head">
        <h2 className="kb-note-title"><i className="bx bx-table muted" /> 事实表</h2>
        <div className="muted" style={{ fontSize: 13 }}>按类型 / 说话人 / 主题 / 实体 / 置信度筛。想按关键词找，用首页的搜索或 ⌘K。</div>
      </div>
      <div className="filter-row">
        <select value={filter.kind ?? ''} onChange={(e) => set('kind', e.target.value)}>
          <option value="">全部类型</option>
          {meta?.kinds.map((k) => <option key={k.kind} value={k.kind}>{k.kind} · {k.facts}</option>)}
        </select>
        <select value={filter.who ?? ''} onChange={(e) => set('who', e.target.value)}>
          <option value="">全部说话人</option>
          {meta?.speakers.map((s) => <option key={s.who} value={s.who}>{s.who} · {s.facts}</option>)}
        </select>
        <input placeholder="主题（含子主题）" value={filter.topic ?? ''} onChange={(e) => set('topic', e.target.value)} />
        <input placeholder="实体" value={filter.entity ?? ''} onChange={(e) => set('entity', e.target.value)} />
        <select value={filter.conf_min ?? ''} onChange={(e) => set('conf_min', e.target.value)}>
          <option value="">任意置信度</option>
          <option value="med">≥ 中</option>
          <option value="high">高</option>
        </select>
        {(filter.kind || filter.who || filter.topic || filter.entity || filter.conf_min) && (
          <button className="icon-btn" title="清空筛选" onClick={() => setFilter({})}><i className="bx bx-x" /></button>
        )}
      </div>
      {!page ? <p className="muted"><span className="spinner" /> 加载中…</p> : (
        <KbSection title={`${page.total} 条`}>
          <FactList facts={page.facts} actions={actions} showTopics />
          <Pager total={page.total} limit={page.limit} offset={page.offset} onPage={(o) => setFilter((f) => ({ ...f, offset: o }))} />
        </KbSection>
      )}
    </div>
  )
}
