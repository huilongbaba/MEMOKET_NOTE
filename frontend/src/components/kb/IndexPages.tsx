/** 三个分类页：主题 / 实体 / 最近摄入。数据就是树上那些行——不再请求一次
 *  （实体多的库树里不带实体，实体页自己取一次）。 */
import { useEffect, useMemo, useState } from 'react'
import { entityIcon } from '../../util/entityIcon'
import { entityMergeCandidates } from '../../api'

import { kbTreeChildren, type TreeRow } from '../../api'
import { Chip, KbSection, type KbActions } from './KbBits'
import { isSpeakerTag } from '../../util/kbNoise'
import Icon from '../Icon'

export function TopicsIndex({ rows, actions }: { rows: TreeRow[]; actions: KbActions }) {
  const roots = rows.filter((r) => r.parent_note_id === 'kb:topics').sort((a, b) => b.fact_count - a.fact_count)
  const kids = (code: string) => rows.filter((r) => r.parent_note_id === 'kb:topic:' + code).sort((a, b) => b.fact_count - a.fact_count)
  return (
    <div className="kb-page">
      <div className="kb-head">
        <h2 className="kb-note-title"><Icon n="bx-hash" className="muted" /> 主题</h2>
        <div className="muted" style={{ fontSize: 'var(--t-md)' }}>{roots.length ? `${roots.length} 个一级主题。计数含子主题。` : '还没有主题。'}</div>
      </div>
      {roots.length === 0 && (
        <p className="muted" style={{ fontSize: 'var(--t-md)' }}>导入会议记录或把笔记存入知识库之后，抽出来的事实会自动归到主题下，这里就会长出来。</p>
      )}
      <div className="topic-grid">
        {roots.map((t) => (
          <div key={t.id} className="topic-card">
            <a href="#" className="topic-card-title" onClick={(e) => { e.preventDefault(); actions.onOpen(t.note_id) }}>
              <Icon n="bx-hash" className="muted" /> {t.title}<span className="muted" style={{ marginInlineStart: 'auto', fontSize: 'var(--t-sm)' }}>{t.fact_count}</span>
            </a>
            <div className="chip-wrap">
              {kids(t.title).slice(0, 8).map((k) => <Chip key={k.id} count={k.fact_count} onClick={() => actions.onOpen(k.note_id)}>{k.title}</Chip>)}
              {kids(t.title).length > 8 && (
                <a href="#" className="muted" style={{ fontSize: 'var(--t-sm)' }} title="进这个主题页看全部子主题"
                   onClick={(e) => { e.preventDefault(); actions.onOpen(t.note_id) }}>…还有 {kids(t.title).length - 8} 个 →</a>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ASR 的说话人标签（Speaker A / speaker_c…）会被抽成「实体」，而且事实数最多——
// 实体页前二十个全是它们。默认藏掉，一个开关放出来（util/kbNoise.ts）。

/** 实体类型节点的中文名（跟后端 virtual_tree.ETYPE_LABELS 一致） */
const ETYPE_LABELS: Record<string, string> = { person: '人', org: '组织', product: '产品', place: '地点', event: '事件', project: '项目', other: '其他' }

/** `node` 默认是全部实体；传 `kb:etype:<type>` 就只列那一类（树上分了类的库点类型节点进来，
 *  之前这种 id 没有页面，中栏只显示一行裸 id——第 235 轮实拍）。 */
export function EntitiesIndex({ rows, actions, node = 'kb:entities' }: { rows: TreeRow[]; actions: KbActions; node?: string }) {
  const [q, setQ] = useState('')
  const [showSpeakers, setShowSpeakers] = useState(false)
  const etype = node.startsWith('kb:etype:') ? node.slice(9) : ''
  // 类型节点的标签页一开始只知道裸 id（「kb:etype:…」挂在标签栏上，第 296 轮实拍）：给个名字
  useEffect(() => {
    if (!etype) return
    // 标签页是 openVirtual 里稍后才加上的：同一帧发事件会扑空（第 296 轮实拍还是裸 id），下一拍再发
    const t = setTimeout(() => window.dispatchEvent(new CustomEvent('virtual-title', { detail: { id: node, title: `实体 · ${ETYPE_LABELS[etype] ?? etype}` } })), 0)
    return () => clearTimeout(t)
  }, [etype, node])
  const fromTree = useMemo(() => rows.filter((r) => r.note_id.startsWith('kb:entity:') && (!etype || r.parent_note_id === node)), [rows, etype, node])
  // 实体超过 200 个的库树里不带它们（每次刷树 358KB 太重）：这页自己取一次
  const [fetched, setFetched] = useState<TreeRow[] | null>(null)
  useEffect(() => {
    if (fromTree.length > 0) { setFetched(null); return }
    let alive = true
    kbTreeChildren(node).then((r) => { if (alive) setFetched(r) }).catch(() => { if (alive) setFetched([]) })
    return () => { alive = false }
  }, [fromTree.length, node])
  const all = useMemo(() => [...(fromTree.length ? fromTree : (fetched ?? []))].sort((a, b) => b.fact_count - a.fact_count), [fromTree, fetched])
  const speakers = useMemo(() => all.filter((r) => isSpeakerTag(r.title)).length, [all])
  const base = showSpeakers ? all : all.filter((r) => !isSpeakerTag(r.title))
  const list = q ? base.filter((r) => (r.title + ' ' + r.preview).toLowerCase().includes(q.toLowerCase())) : base.slice(0, 200)
  return (
    <div className="kb-page">
      <div className="kb-head">
        <h2 className="kb-note-title"><Icon n="bx-group" className="muted" /> {etype ? `实体 · ${ETYPE_LABELS[etype] ?? etype}` : '实体'}</h2>
        <div className="muted" style={{ fontSize: 'var(--t-md)' }}>{!etype && all.length === 0 ? '还没有实体。' : `${all.length} 个。按事实数排序${!q && all.length > 200 ? '，先给前 200 个——搜一下能找到其余的' : ''}。`}{etype && fetched !== null && all.length === 0 ? '这个库的实体没有按类型分组——去「实体」看全部。' : ''}</div>
      </div>
      {!etype && all.length === 0 && (
        <p className="muted" style={{ fontSize: 'var(--t-md)' }}>导入会议记录或把笔记存入知识库之后，事实里提到的人、公司、产品会自动收在这里。</p>
      )}
      {/* 去合并收件箱的入口。**摆在实体页上**是因为问题在这儿被看见：
          列表按事实数排序，而那些数字现在是真值的一部分（MemoCat 真实 189 显示 93）。 */}
      {!etype && all.length > 0 && <MergeEntry onOpen={() => actions.onOpen('kb:merges')} />}
      {all.length > 0 && <div className="kb-search">
        <Icon n="bx-search" />
        <input aria-label="搜实体名或别名" value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜实体名或别名…" />
      </div>}
      {speakers > 0 && (
        <label className="row muted" style={{ gap: 6, fontSize: 'var(--t-sm)', alignItems: 'center', margin: '-2px 0 8px' }}>
          <input type="checkbox" checked={showSpeakers} onChange={(e) => setShowSpeakers(e.target.checked)} />
          显示 {speakers} 个说话人标签（Speaker A 这类是录音转写的角色名，不是真实体）
        </label>
      )}
      <div className="chip-wrap">
        {list.map((e) => <Chip key={e.id} icon={entityIcon(e.title)} count={e.fact_count} onClick={() => actions.onOpen(e.note_id)} title={e.preview || undefined}>{e.title}</Chip>)}
      </div>
    </div>
  )
}

/** 「有 N 对可能是重复的」那一条。数字自己去取——**没有数字的入口没人会点**。 */
function MergeEntry({ onOpen }: { onOpen: () => void }) {
  const [n, setN] = useState<number | null>(null)
  // 取一条就够——要的是 `total`（待判总数），不是这一页有几条
  useEffect(() => { entityMergeCandidates(1).then((d) => setN(d.total)).catch(() => setN(0)) }, [])
  if (!n) return null
  return (
    <p className="muted" style={{ fontSize: 'var(--t-md)', margin: '-2px 0 8px' }}>
      有 <b>{n} 对</b>可能是同一个东西（`Anker` / `安克` / `安克莱` 这类）——
      合并之后这一列的事实数才是真的。<a className="link" onClick={onOpen}>去看看 →</a>
    </p>
  )
}

export function RecentIndex({ rows, actions }: { rows: TreeRow[]; actions: KbActions }) {
  const units = rows.filter((r) => r.parent_note_id === 'kb:recent').sort((a, b) => a.position - b.position)
  return (
    <div className="kb-page">
      <div className="kb-head">
        <h2 className="kb-note-title"><Icon n="bx-time-five" className="muted" /> 最近摄入</h2>
        <div className="muted" style={{ fontSize: 'var(--t-md)' }}>{units.length ? `最近 ${units.length} 场会议。点开看这场会抽出来的事实。` : '还没有摄入过。'}</div>
      </div>
      {units.length === 0 && (
        <p className="muted" style={{ fontSize: 'var(--t-md)' }}>导入一场会议录音、一批笔记，或把一篇写好的笔记「存入知识库」——之后每一份材料都会列在这里。</p>
      )}
      {units.length > 0 && <KbSection title="会议">
        <div className="stack" style={{ gap: 4 }}>
          {units.map((u) => (
            <a key={u.id} href="#" className="kb-link" onClick={(e) => { e.preventDefault(); actions.onOpen(u.note_id) }}>
              <Icon n="bx-conversation" className="muted" /> {u.title}
              <span className="muted" style={{ marginInlineStart: 'auto', whiteSpace: 'nowrap', flexShrink: 0 }}>{u.fact_count} 条</span>
            </a>
          ))}
        </div>
      </KbSection>}
    </div>
  )
}
