import { useEffect, useState } from 'react'

import { kbDashboard, memoryFacts, type FactsFilter, type FactsPage, type KbDashboard } from '../../api'
import { ExampleFacts, FactList, KbSection, Pager, type KbActions } from './KbBits'

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
        {/* 空库时这行讲的是下面根本不存在的那排筛选器——说明要跟着眼前的东西走 */}
        {!(meta && meta.stats.facts === 0) && (
          <div className="muted" style={{ fontSize: 'var(--t-md)' }}>按类型 / 说话人 / 主题 / 实体 / 置信度筛。想按关键词找，用首页的搜索或 ⌘K。</div>
        )}
      </div>
      {/* 整个库还是空的：五个空下拉 + 「0 条 · 没有事实。」没有一处能动，
          也说不出下一步该干什么（第 673 轮新用户实拍）。摆样子 + 一个导入出口。 */}
      {meta && meta.stats.facts === 0 ? (
        <div className="kb-empty">
          <i className="bx bx-table" />
          <h3>知识库还是空的，所以事实表也是空的</h3>
          <p className="muted">导进一场会议录音或一批笔记，抽出来的每一句都会落在这张表里，按类型 / 说话人 / 主题 / 实体筛。</p>
          <div className="row" style={{ gap: 8 }}>
            <button className="primary" onClick={() => window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'app:import' }))}><i className="bx bx-import" /> 导入</button>
            <button onClick={() => actions.onOpen('kb')}><i className="bx bx-left-arrow-alt" /> 回知识库总览</button>
          </div>
          <ExampleFacts />
        </div>
      ) : (<>
      <div className="filter-row">
        <select aria-label="类型" value={filter.kind ?? ''} onChange={(e) => set('kind', e.target.value)}>
          <option value="">全部类型</option>
          {meta?.kinds.map((k) => <option key={k.kind} value={k.kind}>{k.kind} · {k.facts}</option>)}
        </select>
        <select aria-label="说话人" value={filter.who ?? ''} onChange={(e) => set('who', e.target.value)}>
          <option value="">全部说话人</option>
          {meta?.speakers.map((s) => <option key={s.who} value={s.who}>{s.who} · {s.facts}</option>)}
        </select>
        <input aria-label="按主题筛" placeholder="主题（含子主题）" value={filter.topic ?? ''} onChange={(e) => set('topic', e.target.value)} />
        <input aria-label="按实体筛" placeholder="实体" value={filter.entity ?? ''} onChange={(e) => set('entity', e.target.value)} />
        <select aria-label="置信度" value={filter.conf_min ?? ''} onChange={(e) => set('conf_min', e.target.value)}>
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
      </>)}
    </div>
  )
}
