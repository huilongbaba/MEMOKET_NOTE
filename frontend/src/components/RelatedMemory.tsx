import { useEffect, useRef, useState } from 'react'
import { clickable } from '../util/clickable'
import { memoryRelations, memoryScope, recall, SCOPE_LABEL, setMemoryScope, type MemoryScope } from '../api'
import type { Fact, MemoryRelation, RecallEvidence } from '../api'
import { stripForRecall } from '../util/wordCount'
import { cardFromBefore, cardFromCurrent, evidenceLine, evidencePool, factInBody, FROM_BEFORE_NOTE, recallQuery, RECALL_TAIL_CHARS } from '../util/recallContext'
import { KB_EMPTY_NOTE, MARGIN_RULE, noRecordNote, RECALL_FAILED_NOTE, RELATION_LABEL } from '../editor/marginMemory'
import { citeText, fillInText, ignoreRelation, ignoredSet, mergeRelation, relationKey, supersedeRelation } from '../util/relationActions'
import Icon from './Icon'
import { requestTrayAdd } from '../util/tray'

const REL_LABEL: Record<MemoryRelation['relation'], { text: string; cls: string; icon: string }> = {
  conflict: { text: '冲突', cls: 'rel-conflict', icon: 'bx-error' },
  continuation: { text: '延续', cls: 'rel-continuation', icon: 'bx-trending-up' },
  corroborated: { text: '印证', cls: 'rel-corroborated', icon: 'bx-check-shield' },
  unsupported: { text: '缺依据', cls: 'rel-unsupported', icon: 'bx-question-mark' },
  accumulation: { text: '叠加', cls: 'rel-accumulation', icon: 'bx-layer-plus' },
  merge: { text: '合并', cls: 'rel-merge', icon: 'bx-git-merge' },
}

const REL_HELP: Record<MemoryRelation['relation'], string> = {
  conflict: '和旧记录不一致', continuation: '是旧记录的后续', corroborated: '已有记录可以支持',
  unsupported: '暂时没有找到支撑', accumulation: '可以补充到旧记录', merge: '两条记录可以整理成一条',
}

/** 召回是本地零模型检索，短防抖即可；关系判定更重，仍等用户真正停在一段上。 */
const RECALL_IDLE_MS = 450
const RELATION_IDLE_MS = 900
const TAIL_CHARS = RECALL_TAIL_CHARS
const MIN_CHARS = 8
/** 记忆列表最多显示几条（已在正文里的折叠掉，位子让给新的——P4 #8） */
const LIST_MAX = 5
/** 多要几条，折叠掉「已在正文」的之后还够 LIST_MAX 条 */
const RECALL_LIMIT = 8

/**
 * Ambient recall: related facts surface on their own while you write, no
 * query typed -- the "Heads Up"/"Connections pane" pattern several
 * competitors use (Mem, Obsidian's Smart Connections) instead of only
 * offering search-on-demand. Cheap to run this aggressively: /api/memory/recall
 * is a zero-LLM keyword lookup (observed ~30ms), unlike skeleton/edit/magic-tap
 * which hit the LLM and need long debounce windows.
 */
export default function RelatedMemory({ content, paragraph = '', onInsert, kbEmpty = false, noRecordDots = 0 }: {
  /** 光标所在段落：按它查关系（不是尾部 500 字） */
  paragraph?: string
  content: string
  onInsert: (text: string) => void
  /** 知识库一条事实都没有：「没找到相关内容」会让第一次用的人以为坏了，换成指引 */
  kbEmpty?: boolean
  /** 这篇里「缺依据 · 知识库连沾边的记录都没有」那一档的段数（P25 #4）：不画点，在图例下折成一句话 */
  noRecordDots?: number
}) {
  const [facts, setFacts] = useState<Fact[]>([])
  const [loading, setLoading] = useState(false)
  // 按什么查的（整词）、空着的原因、这次是按光标段还是末尾（P4 #6 / #7）
  const [terms, setTerms] = useState<string[]>([])
  // 每个命中**凭什么算证据**（计划 §2 A5）：光说「命中：再决定」不够——P31 实拍那一条
  // 说对了自己在干什么，干的这件事本身是错的。
  // **`[]` 和 `null` 不许压成一个**（P46 #1）：`[]` = 后端判过了、一条都摆不出来；
  // `null` = 这一趟没判成（老后端 / 判据自己抛了）。压成一个，「判过了」那一档就会
  // 退回 `terms` 那串没判过的碎词——那正是 P44 问题 #3。
  const [evidence, setEvidence] = useState<RecallEvidence[] | null>(null)
  const [whyEmpty, setWhyEmpty] = useState<'' | 'no_terms' | 'weak'>('')
  const [mode, setMode] = useState<'cursor' | 'tail'>('tail')
  // **发那一问时**的光标段和前一段那一截（P80 A）。
  // 摆出来的词是不是「前一段带进来的」，判的是这两段，**不是渲染这一刻的 `paragraph`**
  // ——拿新光标段去标旧结果又是一次张冠李戴（P17 #2「A 篇的校验结果挂在 B 篇上」同形）。
  const [qCtx, setQCtx] = useState<{ paragraph: string; before: string } | null>(null)
  const lastQueried = useRef('')
  // **这一问没答上**（P80 A）。`why_empty` 是后端给的三档「为什么空」，
  // 这一档是**客户端自己的**：根本没拿到回答。两件事别压成一个——
  // 压成一个就会把「没查成」说成「知识库里没有相关内容」，那是另一句谎。
  const [failed, setFailed] = useState(false)
  // 「这一问是不是最新那一问」。**只认最新那一问的回答**（P80 A 的第二条路）：
  // 光标从第 1 段挪到第 2 段，两问都在飞，第 1 问**后到**的话原来会把第 2 段的
  // 答案盖回第 1 段的，而 `lastQueried` 已经是第 2 问了 → **它不会自己修回来**。
  const recallSeq = useRef(0)
  // 记忆范围：换了就把两个缓存键清掉，让召回和关系都重来
  const [scope, setScope] = useState<MemoryScope>(() => memoryScope())
  useEffect(() => {
    const on = (e: Event) => { setScope((e as CustomEvent<MemoryScope>).detail); lastQueried.current = ''; lastPara.current = ''; setFacts([]); setRels([]) }
    window.addEventListener('memory-scope-changed', on)
    return () => window.removeEventListener('memory-scope-changed', on)
  }, [])

  // 关系：光标停在一段上 900ms 就查一次。只对有具体数字 / 日期的段落有意义（后端没量就回空）。
  const [rels, setRels] = useState<MemoryRelation[]>([])
  const [relBusy, setRelBusy] = useState(false)
  const [ignored, setIgnored] = useState<Set<string>>(() => ignoredSet())
  const lastPara = useRef('')
  const relSeq = useRef(0)
  useEffect(() => {
    const p = stripForRecall(paragraph).trim()
    if (p.length < MIN_CHARS || !/\d/.test(p)) {
      ++relSeq.current; lastPara.current = ''; setRels([]); setRelBusy(false); return
    }
    if (p === lastPara.current) return
    // 段落一变，上一段的关系立即作废。不能在 900ms 防抖期间把旧卡挂在新段下面。
    lastPara.current = p
    const seq = ++relSeq.current
    setRels([])
    setRelBusy(true)
    let started = false
    const t = setTimeout(() => {
      started = true
      memoryRelations(p)
        .then((r) => { if (seq === relSeq.current) setRels(r.relations) })
        // 跟召回那一半同一条（P80 A）：没答上就把**上一段的关系卡**撤掉。
        // 原来这儿也是空的 `catch`，于是「光标这段跟知识库的关系」底下摆着上一段的卡。
        .catch(() => { if (seq === relSeq.current) { lastPara.current = ''; setRels([]) } })
        .finally(() => { if (seq === relSeq.current) setRelBusy(false) })
    }, RELATION_IDLE_MS)
    return () => {
      clearTimeout(t)
      // 依赖变了但清洗后的段落没变时，cleanup 会先取消定时器；放开缓存键让下一轮重新挂上。
      if (!started && lastPara.current === p) lastPara.current = ''
    }
  }, [paragraph, scope])
  // 动作跟页边圆点旁边那张卡同一份（`util/relationActions`，P9）；「忽略」的名单也是同一份——
  // 那边点了忽略这边跟着灭，反过来一样（`relation-ignored` 事件）
  useEffect(() => {
    const on = () => setIgnored(ignoredSet())
    window.addEventListener('relation-ignored', on)
    return () => window.removeEventListener('relation-ignored', on)
  }, [])
  function ignore(key: string) { setIgnored(ignoreRelation(key)) }
  const supersede = (rel: MemoryRelation) => supersedeRelation(rel)
  const merge = (rel: MemoryRelation) => mergeRelation(rel)
  function fillIn(rel: MemoryRelation) { onInsert(fillInText(rel)); ignore(relationKey(rel)) }
  const visibleRels = rels.filter((r) => !ignored.has(relationKey(r)))

  // 记忆列表：按**光标所在段（+ 前一段）**召回；光标不在正文里才退回末 500 字（P4 #7：原来只看末 500 字，
  // 用户在顶部写华为芯片、右栏是尾段恒瑞翻译的记忆）。零模型，每次 ~100ms。
  useEffect(() => {
    const q = recallQuery(content, paragraph)
    if (q.query.length < MIN_CHARS) {
      ++recallSeq.current; lastQueried.current = ''; setFacts([]); setTerms([]); setEvidence(null)
      setWhyEmpty(''); setQCtx(null); setFailed(false); setLoading(false); return
    }
    if (q.query === lastQueried.current) return
    // 新段落开始检索时就撤掉旧答案，而不是等新请求成功/失败后才撤。
    // 这样防抖和网络等待期间，屏幕不会把上一段的记忆误认成当前段的。
    lastQueried.current = q.query
    const seq = ++recallSeq.current
    setFacts([]); setTerms([]); setEvidence(null); setWhyEmpty(''); setQCtx(null); setFailed(false)
    setMode(q.mode); setLoading(true)
    let started = false
    const t = setTimeout(() => {
      started = true
      recall(q.query, RECALL_LIMIT)
        .then((r) => {
          if (seq !== recallSeq.current) return       // 不是最新那一问的回答：丢掉，别盖回上一段
          setFacts(r.facts); setTerms(r.terms ?? []); setEvidence(r.evidence ?? null)
          setWhyEmpty(r.why_empty ?? ''); setMode(q.mode); setQCtx({ paragraph, before: q.before }); setFailed(false)
        })
        .catch(() => {
          if (seq !== recallSeq.current) return
          // **上一段的答案当场作废**：原来这儿是空的 `catch`，于是「按光标这段找的，
          // 命中：…」那一行**逐字还是上一段的**，而标签写着这一段。P78 在真壳上
          // 拍到过（一篇五段，第 2 段那一行跟第 1 段逐字相同）。
          lastQueried.current = ''                    // 清掉，下一次依赖变了还问得动
          setFacts([]); setTerms([]); setEvidence(null); setWhyEmpty(''); setMode(q.mode); setQCtx(null); setFailed(true)
        })
        .finally(() => { if (seq === recallSeq.current) setLoading(false) })
    }, RECALL_IDLE_MS)
    return () => {
      clearTimeout(t)
      // content 变了但有效查询没变时，不能“取消旧定时器后又因同 key 提前返回”。
      if (!started && lastQueried.current === q.query) lastQueried.current = ''
    }
  }, [content, paragraph, scope])
  // 已经在正文里的原话折叠掉（P4 #8：N4 5 条全是用户刚写的），位子让给新的
  const candidates = facts.filter((f) => !factInBody(f.text, content))
  const inBody = facts.filter((f) => factInBody(f.text, content))
  // **这一趟拿哪几个词去判卡**（P83 A）：跟上面那一行同一条三档，**同进同退**。
  // 召回和 `out[:8]` 一个字没动——变的只有「怎么说」，不是「捞什么」。
  const pool = evidencePool(evidence, terms)
  const fromBefore = (text: string) => !!qCtx && cardFromBefore(text, pool, qCtx.paragraph, qCtx.before)
  const fromCurrent = (text: string) => !!qCtx && cardFromCurrent(text, pool, qCtx.paragraph)
  // 拼入前一段能帮短段补足上下文，但混合命中时先摆当前段的结果，避免旧上下文抢占首屏。
  // 只移动被判据明确认作“前一段带回”的卡；判不清的仍保留后端原始顺序。
  const fresh = [
    ...candidates.filter((f) => fromCurrent(f.text)),
    ...candidates.filter((f) => !fromCurrent(f.text) && !fromBefore(f.text)),
    ...candidates.filter((f) => fromBefore(f.text)),
  ]
    .slice(0, LIST_MAX)

  // 之前 facts 是空的时候整个组件（连带标题）直接 return null——这是这个
  // 面板在"写作"/"相关记忆"/"知识库" 三个 tab 里唯一的内容，点进"相关记忆"
  // 这个 tab 却看到完全空白，用户分不清是"还没写够内容触发检索"还是"面板
  // 坏了"。保留标题，用不同文案区分"内容太短还没触发"和"检索了但没找到"
  // 这两种不同的空状态。
  const tooShort = stripForRecall(content.slice(-TAIL_CHARS)).trim().length < MIN_CHARS

  return (
    <div>
      <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: '4px 0 8px', display: 'flex', gap: 6, alignItems: 'center' }}>
        {/* 转圈 + 下拉一起挤上来时这句会折成两行把头部撑高（第 216 轮实拍）：文字可截断，别折行 */}
        <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>自动查找当前段相关的旧记录。</span>
        {loading && <span className="spinner" style={{ flexShrink: 0 }} />}
        {/* 记忆范围：一个库里混着会议记录 / 笔记 / 导入的，写自家复盘时别让别家汇报串进来 */}
        <select className="select-sm" value={scope} onChange={(e) => setMemoryScope(e.target.value as MemoryScope)} title="召回、关系、续写、扩写、校验、回顾、写作计划取材料都只看这一档"
                style={{ marginInlineStart: 'auto', flexShrink: 0 }}>
          {(Object.keys(SCOPE_LABEL) as MemoryScope[]).map((k) => <option key={k} value={k}>{SCOPE_LABEL[k]}</option>)}
        </select>
      </p>
      {kbEmpty ? (
        <div className="muted mem-legend" style={{ fontSize: 'var(--t-xs)', margin: '0 0 8px', lineHeight: 1.7 }}>
          {KB_EMPTY_NOTE}
          <button className="primary" style={{ fontSize: 'var(--t-sm)', padding: '2px 8px', marginInlineStart: 6 }}
                  onClick={() => window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'app:import' }))}>
            <Icon n="bx-import" /> 导入
          </button>
        </div>
      ) : (
        <div className="mem-legend" style={{ margin: '0 0 8px' }}>
          <details className="mem-help">
            <summary>页边圆点说明</summary>
            <p>{MARGIN_RULE}。</p>
            <div className="mem-rel-help">
              {(Object.keys(RELATION_LABEL) as (keyof typeof RELATION_LABEL)[]).map((k) => (
                <span key={k}><span className={'mm-dot mm-' + k} />{RELATION_LABEL[k]}：{REL_HELP[k]}</span>
              ))}
            </div>
          </details>
          {noRecordDots > 0 && <p className="muted mem-no-record-note">{noRecordNote(noRecordDots)}</p>}
        </div>
      )}
      {(visibleRels.length > 0 || relBusy) && (
        <div className="stack" style={{ gap: 6, marginBottom: 10 }}>
          <div className="muted" style={{ fontSize: 'var(--t-xs)' }}>光标这段跟知识库的关系{relBusy && <> <span className="spinner" /></>}</div>
          {visibleRels.map((r) => {
            const L = REL_LABEL[r.relation]
            const key = relationKey(r)
            return (
              <div key={key} className={'card rel-card ' + L.cls}>
                <div className="row" style={{ gap: 6, alignItems: 'center' }}>
                  <span className={'badge ' + L.cls}><Icon n={L.icon} /> {L.text}</span>
                  <span style={{ fontSize: 'var(--t-md)', flex: 1 }}>{r.say}</span>
                </div>
                {r.facts.length > 0 && (
                  <div className="stack" style={{ gap: 2, marginTop: 4 }}>
                    {r.facts.map((f) => (
                      <div key={f.id} className="muted" style={{ fontSize: 'var(--t-sm)', cursor: 'pointer' }} title="打开这条"
                           {...clickable(() => window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb:fact:' + f.id })))}>
                        <span className="badge" style={{ marginInlineEnd: 4 }}>{f.when || '—'}</span>{f.text}
                      </div>
                    ))}
                  </div>
                )}
                <div className="row" style={{ gap: 4, marginTop: 6 }}>
                  {r.facts.length > 0 && (content.includes(`[${r.facts[r.facts.length - 1].id}]`)
                    ? <span className="badge ok" title="正文里已经引用了这条">已引用</span>
                    : <button style={{ fontSize: 'var(--t-sm)', padding: '2px 8px' }} onClick={() => onInsert(citeText(r))}>引用这条</button>)}
                  {r.relation === 'conflict' && <button style={{ fontSize: 'var(--t-sm)', padding: '2px 8px' }} onClick={() => void supersede(r)}>新的取代旧的</button>}
                  {r.relation === 'accumulation' && r.facts.length > 0 && <button style={{ fontSize: 'var(--t-sm)', padding: '2px 8px' }} onClick={() => fillIn(r)}>补进来</button>}
                  {r.relation === 'merge' && r.facts.length === 2 && <button style={{ fontSize: 'var(--t-sm)', padding: '2px 8px' }} onClick={() => void merge(r)}>合成一条</button>}
                  {r.facts.length > 0 && <button style={{ fontSize: 'var(--t-sm)', padding: '2px 8px' }} title="加入本篇材料，之后 AI 写这篇时优先参考"
                          onClick={() => r.facts.forEach((f) => requestTrayAdd({ kind: 'fact', ref_id: f.id, title: f.when || '', excerpt: f.text }))}>加入本篇材料</button>}
                  <button style={{ fontSize: 'var(--t-sm)', padding: '2px 8px' }} onClick={() => ignore(key)}>忽略</button>
                </div>
              </div>
            )
          })}
        </div>
      )}
      {/* 为什么给我看这几条（A5 的第一步）：按哪几个词找的、按光标段还是末尾 */}
      {facts.length > 0 && !loading && (
        <p className="muted mem-terms" style={{ fontSize: 'var(--t-xs)', margin: '0 0 6px' }}>
          {evidenceLine(mode, evidence, terms, qCtx)}
        </p>
      )}
      {facts.length === 0 && !loading && !kbEmpty && (
        <p className={'muted' + (failed ? ' mem-failed' : '')} style={{ fontSize: 'var(--t-md)' }}>
          {/* **「没问成」排在最前**（P80 A）：没拿到回答的时候，关于知识库的任何一句
              （空库 / 没找到 / 没有可查的关键词）都是在替空气背书。 */}
          {failed ? RECALL_FAILED_NOTE
            : tooShort ? '再多写几个字就会开始自动检索。'
            // P4 #6：查询退化到一个泛词（「记录」）时原来硬凑 5 条不相干的；现在后端不凑，这里说清楚为什么空
            : whyEmpty === 'no_terms' ? (mode === 'cursor' ? '光标这段' : '正文末尾') + '没有可查的关键词（人名、项目、日期、数字这类具体的词）。'
            : whyEmpty === 'weak' ? (mode === 'cursor' ? '光标这段' : '正文末尾') + '的关键词在知识库里没有一条记录同时命中两个——不硬凑不相干的。'
            : '知识库里暂时没有找到相关内容。'}
        </p>
      )}
      {facts.length > 0 && fresh.length === 0 && !loading && (
        <p className="muted" style={{ fontSize: 'var(--t-md)' }}>召回的 {inBody.length} 条都是正文里已经写了的原话（折在下面）。</p>
      )}
      {fresh.map((f) => (
        <div
          className="card memory-card"
          key={f.id}
        >
          <div style={{ fontSize: 'var(--t-md)' }}>{f.text}</div>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', marginTop: 4 }}>
            <span className="row" style={{ gap: 4 }}>
              {f.when ? <span className="badge">{f.when}</span> : null}
              {/* **这张卡是前一段带回来的**（P83 A）。上面那一行 P80 已经会说这句了，
                  底下这几张卡在这一批之前是**混着的**：真库实测 964 张里 133 张属于这一档，
                  29 条查询里两种卡摆在一起、33 条整屏 5 张全是前一段的，而用户一点提示都没有。
                  判据两条都成立才盖（`cardFromBefore`），落差只会让它少说一句。 */}
              {fromBefore(f.text) && (
                <span className="badge mem-card-from-before" title="这条来自光标前一段，不是当前段落">
                  {FROM_BEFORE_NOTE}
                </span>
              )}
              {fromCurrent(f.text) && mode === 'cursor' && (
                <span className="badge mem-card-from-current" title="这条由当前段的内容召回">当前段</span>
              )}
              {/* 正文里已经引过的标出来——不然同一条会被插两次（实拍：一段里两个同样的出处） */}
              {content.includes(`[${f.id}]`) && <span className="badge ok" title="正文里已经引用了这条">已引用</span>}
            </span>
            <span className="memory-card-actions">
              <button title="打开这条事实"
                      onClick={(e) => { e.stopPropagation(); window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb:fact:' + f.id })) }}>
                <Icon n="bx-link-external" /> 查看
              </button>
              <button title="把原文和可核验来源插入光标处" onClick={(e) => { e.stopPropagation(); onInsert(`${f.text} [${f.id}]`) }}>
                <Icon n="bx-link" /> 引用
              </button>
              {/* 放进托盘（P14 §3.4）：不进正文，进材料层——之后续写 / `/` 块取材料时它排最前 */}
              <button className="icon-btn" title="加入本篇材料，之后 AI 写这篇时优先参考"
                      onClick={(e) => { e.stopPropagation(); requestTrayAdd({ kind: 'fact', ref_id: f.id, title: f.when || '', excerpt: f.text }) }}>
                <Icon n="bx-layer-plus" />
              </button>
            </span>
          </div>
        </div>
      ))}
      {inBody.length > 0 && (
        <details className="mem-inbody" style={{ marginTop: 8 }}>
          <summary className="muted" style={{ fontSize: 'var(--t-sm)', cursor: 'pointer' }}>已在正文里的 {inBody.length} 条（你刚写的原话，折起来）</summary>
          {inBody.map((f) => (
            <div key={f.id} className="muted" style={{ fontSize: 'var(--t-sm)', margin: '6px 0 0 8px', cursor: 'pointer' }} title="打开这条"
                 {...clickable(() => window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb:fact:' + f.id })))}>
              {f.when ? <span className="badge" style={{ marginInlineEnd: 4 }}>{f.when}</span> : null}{f.text}
            </div>
          ))}
        </details>
      )}
    </div>
  )
}
