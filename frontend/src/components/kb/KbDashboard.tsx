/** 知识库首页：搜索在第一屏，然后是数字、近 12 个月、主题 Top、实体 Top、最近摄入。 */
import { useEffect, useState } from 'react'
import { entityIcon } from '../../util/entityIcon'

import { kbDashboard, recall, type Fact, type FactDetail, type KbDashboard as Data } from '../../api'
import { Chip, ExampleFacts, FactList, KbSection, MiniBars, StatTile, type KbActions } from './KbBits'
import { isSpeakerTag } from '../../util/kbNoise'
import { takePendingKbQuery } from '../../util/pendingKbQuery'
import ConflictInbox from './ConflictInbox'
import Icon from '../Icon'

const toDetail = (f: Fact): FactDetail => ({ id: f.id, text: f.text, when: f.when, kind: f.kind, who: '', conf: '', topics: [], entities: [], unit: '' })

export default function KbDashboard({ actions }: { actions: KbActions }) {
  const [data, setData] = useState<Data | null>(null)
  const [q, setQ] = useState(takePendingKbQuery)
  const [hits, setHits] = useState<{ facts: FactDetail[]; took: number; terms: string[] } | null>(null)
  const [searching, setSearching] = useState(false)

  useEffect(() => { kbDashboard().then(setData).catch(() => setData(null)) }, [])

  // 侧栏搜笔记没搜到时，那里给了一条「到知识库里搜同一个词」的去处。词走
  // `pendingKbQuery`（挂载时自取，不赌时序）；这一页已经开着的时候走事件。
  // 虚拟 id 里塞查询串要动一整条链路（knownVirtual / openVirtual / 面包屑父链 /
  // probes 父链），为一个搜索词不值当。
  useEffect(() => {
    const on = (e: Event) => setQ(String((e as CustomEvent).detail || ''))
    window.addEventListener('kb-search', on)
    return () => window.removeEventListener('kb-search', on)
  }, [])

  // 即搜即显：零 LLM 的符号检索，毫秒级
  useEffect(() => {
    if (!q.trim()) { setHits(null); return }
    setSearching(true)
    const t = setTimeout(() => {
      recall(q, 20).then((r) => setHits({ facts: r.facts.map(toDetail), took: r.took_ms, terms: r.terms }))
        .catch(() => setHits({ facts: [], took: 0, terms: [] })).finally(() => setSearching(false))
    }, 250)
    return () => clearTimeout(t)
  }, [q])

  return (
    <div className="kb-page">
      {/* 空库不摆搜索框：一条事实都没有，搜出来只能是空，autoFocus 的光标停在那里像在等你输入 */}
      {!(data && data.stats.facts === 0) && (
        <div className="kb-search">
          <Icon n="bx-search" />
          <input aria-label="搜知识库" value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜知识库：人、事、数字、日期…"
                 autoFocus onKeyDown={(e) => { if (e.key === 'Escape') setQ('') }} />
          {searching && <span className="spinner" />}
          {q && <button className="icon-btn" title="清空" aria-label="清空搜索" onClick={() => setQ('')}><Icon n="bx-x" /></button>}
        </div>
      )}

      {/* 一条都没召回时，那几个词**不是命中的词，是找过的词**（P81 ③，下面那个 `extra`）。
          后端 `UserMemory.recall` 背靠背两支：主路排出东西 → `surfaces` 接的是
          `matched_terms(facts, …)` = 真跟这几条对上的词；主路空 → 走 `_recall_via_lines`，
          `surfaces` 接的是 `_cjk_terms(query)[:3]` = **只是拿去找过的词**。
          这一行原来两支共用一个标签「命中词」，于是真库上「0 条结果 · 命中词：潜水艇」
          摆了出来（P79 ② 实测 10 条里 9 条）。P48 ③ 判过这条路「今天 0 个用户看得见」→
          P69 更正「不成立」→ P79 第三次核实仍在摆，从 2026-09-15 `d51ea29` 起就在。
          **不是不摆，是改口**：0 结果时这几个词是唯一能告诉用户「系统到底拿什么去找的」
          那一格（打 `9月14日` 它找的是 `9月14`、打 `2026-09` 它找的是 `2026`），
          不摆等于把「为什么 0 条」也一起藏了。
          **为什么判据是 `facts.length` 而不是问后端走了哪一支**：两者在**唯一真摆这一行的
          那条路**（搜索框）上逐条重合——`kb_search_ruler` 110 条实测「走了回退又捞回东西」
          **0 条**，`facts.length === 0` ⇔ 走了回退。（765 那条自动召回上有 7 条不重合，
          但 P77 ② 量过那条路 `evidence=null` 退回 `terms` 是 **0/765**，这一行在那边
          一次都不渲染。）**判据宁可窄。** */}
      {hits ? (
        <KbSection title={`${hits.facts.length} 条结果`}
                   extra={<span className="muted" style={{ fontSize: 'var(--t-sm)' }}>{Math.round(hits.took)} ms{hits.terms.length ? (hits.facts.length ? ' · 命中词：' : ' · 找过：') + hits.terms.slice(0, 6).join('、') : ''}</span>}>
          <FactList facts={hits.facts} actions={actions} />
          {/* 空库上「换个说法」是句废话——换多少个说法都是空。分开说（第 677 轮） */}
          {hits.facts.length === 0 && <p className="muted" style={{ fontSize: 'var(--t-sm)' }}>
            {data && data.stats.facts === 0
              ? '知识库还是空的——先导入会议记录或笔记，这里才搜得到东西。'
              : '换个说法，或者到「事实表」按主题 / 实体筛。'}
          </p>}
        </KbSection>
      ) : !data ? (
        <p className="muted"><span className="spinner" /> 加载中…</p>
      ) : data.stats.facts === 0 ? (
        <div className="kb-empty">
          <Icon n="bx-brain" />
          <h3>知识库还是空的</h3>
          <p className="muted">把会议记录、录音、其他应用的笔记导进来，或者把一篇写好的笔记「存入知识库」——之后这里会长出主题、实体和时间线，写作时右栏会自动浮现相关的记忆。</p>
          <div className="row" style={{ gap: 8 }}>
            <button className="primary" onClick={() => window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'app:import' }))}><Icon n="bx-import" /> 导入</button>
          </div>
          <ExampleFacts />
        </div>
      ) : (
        <>
          <div className="stat-row">
            <StatTile value={data.stats.facts.toLocaleString()} label="条事实" />
            <StatTile value={data.stats.topics} label="个主题" />
            <StatTile value={data.stats.entities.toLocaleString()} label="个实体" />
            <StatTile value={data.stats.units.toLocaleString()} label="场会议" />
            {/* 两边各掐掉 2%：这个数要回答「我攒了多久的记录」，而不是「有没有
                一条离群的日期」。掐掉的那截写在 title 里——**掐掉的东西要能看见**。 */}
            <StatTile
              value={<span className="stat-span" style={{ fontSize: 'var(--t-lg)' }}
                           title={data.stats.full_start && data.stats.full_start !== data.stats.start_date
                             ? `连最早最晚那几条一起算是 ${data.stats.full_start.slice(0, 7)} → ${(data.stats.full_end ?? '').slice(0, 7)}（两头各掐掉 2%，那些多半是句子里提到的年份）`
                             : undefined}>
                       {data.stats.start_date ? `${data.stats.start_date.slice(0, 7)} → ${data.stats.end_date.slice(0, 7)}` : '—'}
                     </span>}
              label="跨度（按事实里的日期）" />
            {/* 体检。原来这个数字只有一条前端从没调过的接口拿得到（第 665 轮翻出来的）。
                **第一版把它写成「能用的事实 84%」，那是过头了**——第 667 轮抽样逐条读过
                被标记的那 3256 条：里面有「这款手机的价格是2999元」「用户量级几千的量级」
                这种**又短又有用**的句子。这条判据量的是**形状**（太短 / 是提问 / 有口水话 /
                只有说话人+短语），不是「有没有用」。所以标签只说形状，别替它下结论。 */}
            {data.quality && data.quality.unusable_rate >= 0.03 && (
              <StatTile
                value={<span title={Object.entries(data.quality.reasons)
                                     .map(([k, v]) => `${k} ${v}`).join(' · ')
                                     + `；另有 ${data.quality.speaker_labels} 条带说话人标签。`
                                     + '这是形状上的信号，不是说它们没用——里面有「这款手机的价格是2999元」这种又短又有用的句子。'}>
                         {Math.round(data.quality.unusable_rate * 100)}%
                       </span>}
                label={`形状可疑（${data.quality.unusable.toLocaleString()} 条太短 / 提问 / 口水话）`} />
            )}
          </div>

          <ConflictInbox actions={actions} />

          <KbSection title="近 12 个月" note="按事实里的日期算；计划里的未来日期也算进来。" extra={<a href="#" className="muted" style={{ fontSize: 'var(--t-sm)' }} onClick={(e) => { e.preventDefault(); actions.onOpen('kb:timeline') }}>全部时间线 →</a>}>
            <MiniBars data={data.months} />
          </KbSection>

          <div className="kb-two-col">
            <KbSection title="主题" extra={<a href="#" className="muted" style={{ fontSize: 'var(--t-sm)' }} onClick={(e) => { e.preventDefault(); actions.onOpen('kb:topics') }}>全部 →</a>}>
              <div className="chip-wrap">
                {data.top_topics.map((t) => (
                  <Chip key={t.code} icon="bx-hash" count={t.facts} onClick={() => actions.onOpen('kb:topic:' + t.code)}
                        title={t.children ? `${t.children} 个子主题` : undefined}>{t.code}</Chip>
                ))}
              </div>
            </KbSection>
            <KbSection title="实体" extra={<a href="#" className="muted" style={{ fontSize: 'var(--t-sm)' }} onClick={(e) => { e.preventDefault(); actions.onOpen('kb:entities') }}>全部 →</a>}>
              <div className="chip-wrap">
                {data.top_entities.filter((t) => !isSpeakerTag(t.name)).map((t) => (
                  <Chip key={t.code} icon={entityIcon(t.name)} count={t.facts} onClick={() => actions.onOpen('kb:entity:' + t.code)}>{t.name}</Chip>
                ))}
              </div>
            </KbSection>
          </div>

          <div className="kb-two-col">
            <KbSection title="最近摄入" extra={<a href="#" className="muted" style={{ fontSize: 'var(--t-sm)' }} onClick={(e) => { e.preventDefault(); actions.onOpen('kb:recent') }}>全部 →</a>}>
              <div className="stack" style={{ gap: 4 }}>
                {data.recent_units.map((u) => (
                  <a key={u.id} href="#" className="kb-link" onClick={(e) => { e.preventDefault(); actions.onOpen('kb:unit:' + u.id) }} title={u.title || u.id}>
                    <Icon n="bx-conversation" className="muted" /> <span className="muted" style={{ flex: 'none' }}>{u.date}</span>
                    {/* 标题长了省略，日期 / 条数不换行（第 142 轮实拍：日期折成两行、「4 条」竖排） */}
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{u.title || u.id}</span>
                    <span className="muted" style={{ marginInlineStart: 'auto', flex: 'none', whiteSpace: 'nowrap' }}>{u.facts} 条</span>
                  </a>
                ))}
              </div>
            </KbSection>
            <KbSection title="类型 · 说话人">
              <div className="chip-wrap">
                {data.kinds.map((k) => <Chip key={k.kind} count={k.facts} onClick={() => actions.onOpen('kb:facts?kind=' + k.kind)}>{k.kind}</Chip>)}
              </div>
              <div className="chip-wrap" style={{ marginTop: 6 }}>
                {data.speakers.map((s) => <Chip key={s.who} icon="bx-user-voice" count={s.facts} onClick={() => actions.onOpen('kb:facts?who=' + s.who)}>{s.who}</Chip>)}
              </div>
            </KbSection>
          </div>

          <div className="chip-wrap" style={{ marginTop: 4 }}>
            <Chip icon="bx-table" onClick={() => actions.onOpen('kb:facts')}>事实表</Chip>
            <Chip icon="bx-network-chart" onClick={() => actions.onOpen('kb:graph')}>主题地图</Chip>
            <Chip icon="bx-history" onClick={() => actions.onOpen('kb:digest')}>定期回顾</Chip>
          </div>
        </>
      )}
    </div>
  )
}
