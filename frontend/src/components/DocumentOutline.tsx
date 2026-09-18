import { useEffect, useMemo, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { EditorView } from '@codemirror/view'
import { SECTION_LABEL, materialsText, sectionStatuses, sectionSummary } from '../util/sectionStatus'

type Heading = { level: number; text: string; pos: number }

/** 正文里的标题。**围栏代码块里的不算**——Python 和 Shell 的注释正好是
 * `# ` 开头，跟一级标题一个样子，不排除的话大纲面板里会冒出「读取退货
 * 工单」这种条目，点一下光标跳进代码块中间。
 *
 * 后端 `app/editor/outline.py` 的 `_mask_fences()` 干的是同一件事，而且
 * 后果更重（那边这个 bug 会让普通笔记被误判成大纲、把结构冻死）。这两处
 * 各自解析各自的标题是合理的——一个是导航面板，一个是 harness 的结构防线，
 * 不构成共享契约；但踩的是同一个坑。
 */
export function parseHeadings(content: string): Heading[] {
  const out: Heading[] = []
  const re = /^(#{1,6})\s+(.+)$/gm
  const fence = /^\s*(`{3,}|~{3,})/
  // 每一行的起始偏移 → 它在不在围栏里
  const inFence = new Set<number>()
  let fenced = false
  let at = 0
  for (const line of content.split('\n')) {
    const isFence = fence.test(line)
    if (isFence || fenced) inFence.add(at)
    if (isFence) fenced = !fenced
    at += line.length + 1
  }
  let m: RegExpExecArray | null
  while ((m = re.exec(content))) {
    if (inFence.has(m.index)) continue
    out.push({ level: m[1].length, text: m[2].trim(), pos: m.index })
  }
  return out
}

/** 没有 `#` 标题时的目录（P7，P4 #3）：26.7k 字的展厅讲解词零个 `#`，目录面板一片空白，用户在最长的一篇里
 * 没有任何导航。退两步：
 *   1. 「算力底座：」「案例：」「英伟达对比：」这种**短行 + 冒号结尾**的段落当伪标题（≥ 3 个才用这档）；
 *   2. 都没有就**按段落列**，每段取首句（≤ 28 字）。
 * 两档都在面板顶上说一句「这篇没有 # 标题，按 xx 列」，别让人以为它认出了标题。 */
export type FallbackOutline = { items: Heading[]; how: 'colon' | 'paragraph' | 'none' }
const COLON_HEAD = /^(.{1,16}?)\s*[：:]\s*$/
const PARA_MIN_CHARS = 20
const FALLBACK_MAX = 200

function firstSentence(s: string): string {
  const t = s.replace(/^[-*>\s]+|^\d+[.、]\s*/g, '').trim()
  const m = t.match(/^(.{4,28}?)(?:[。！？；!?;]|$)/)
  const head = m ? m[1] : t.slice(0, 28)
  return head.length < t.length ? head + '…' : head
}

export function parseFallbackAnchors(content: string): FallbackOutline {
  const fence = /^\s*(`{3,}|~{3,})/
  const paras: { pos: number; first: string; len: number }[] = []
  let cur: { pos: number; first: string; len: number } | null = null
  let fenced = false
  let at = 0
  for (const line of content.split('\n')) {
    const isFence = fence.test(line)
    if (isFence) fenced = !fenced
    if (!line.trim() || isFence || fenced) {
      if (cur) { paras.push(cur); cur = null }
    } else {
      if (!cur) cur = { pos: at, first: line.trim(), len: 0 }
      cur.len += line.trim().length
    }
    at += line.length + 1
  }
  if (cur) paras.push(cur)
  const colon = paras.filter((p) => p.len <= 17 && COLON_HEAD.test(p.first))
  if (colon.length >= 3) {
    return { how: 'colon', items: colon.slice(0, FALLBACK_MAX).map((p) => ({ level: 1, text: p.first.replace(/\s*[：:]\s*$/, ''), pos: p.pos })) }
  }
  const long = paras.filter((p) => p.len >= PARA_MIN_CHARS)
  if (long.length >= 2) {
    return { how: 'paragraph', items: long.slice(0, FALLBACK_MAX).map((p) => ({ level: 1, text: firstSentence(p.first), pos: p.pos })) }
  }
  return { how: 'none', items: [] }
}

/** Jump-to-heading outline -- cheap to add now that the editor is real
 * markdown with real heading syntax, and it's table-stakes for anything
 * pitching itself as a Notion-class editor for longer documents. */
export default function DocumentOutline({ content, viewRef, withStatus = false }: {
  content: string
  viewRef: RefObject<EditorView | null>
  /** 目录 = 计划（P12 §3.5）：每一节带状态（空 / 草稿 / 有依据）和「用了什么材料」。只对真正的 `#` 标题算——
   *  按「xx：」短行 / 段落退化出来的目录，每一项本身就是一段，状态没意义。 */
  withStatus?: boolean
}) {
  const real = useMemo(() => parseHeadings(content), [content])
  const fallback = useMemo<FallbackOutline | null>(() => (real.length ? null : parseFallbackAnchors(content)), [content, real.length])
  const headings = useMemo(() => (real.length ? real : (fallback?.items ?? [])), [real, fallback])
  const statuses = useMemo(() => (withStatus && real.length ? sectionStatuses(content, real) : []), [withStatus, content, real])
  const statusAt = useMemo(() => new Map(statuses.map((s) => [s.pos, s])), [statuses])
  const summary = useMemo(() => sectionSummary(statuses), [statuses])
  // 正在看哪一节：跟着正文滚动区顶部那一行走（Obsidian 的 outline 也这么做）。
  // 滚动的是 .note-scroll 不是 CM 自己，所以听它。
  const [activePos, setActivePos] = useState(-1)
  const listRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const view = viewRef.current
    const scroller = view?.scrollDOM.closest('.note-scroll') as HTMLElement | null
    if (!view || !scroller || headings.length === 0) return
    const update = () => {
      const r = scroller.getBoundingClientRect()
      const pos = view.posAtCoords({ x: r.left + 60, y: r.top + 90 }) ?? view.posAtCoords({ x: r.left + 60, y: r.top + 90 }, false)
      let active = -1
      for (const h of headings) if (h.pos <= pos) active = h.pos
      setActivePos(active)
    }
    update()
    scroller.addEventListener('scroll', update, { passive: true })
    return () => scroller.removeEventListener('scroll', update)
  }, [headings, viewRef])
  // 当前节在目录里也要看得见：300 个标题的长文滚到第 136 节时，目录还停在第 1～23 节（实拍）
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>('.outline-item.active')?.scrollIntoView({ block: 'nearest' })
  }, [activePos])
  if (headings.length === 0) return (
    <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: 0 }}>
      正文里的 <code>#</code> 标题会列在这里，点一下跳过去{withStatus ? '；每一节带状态（空 / 草稿 / 有依据），空的就是还没写的' : ''}。
    </p>
  )

  function jump(pos: number) {
    const view = viewRef.current
    if (!view) return
    view.dispatch({
      selection: { anchor: pos },
      effects: EditorView.scrollIntoView(pos, { y: 'center' }),
    })
    view.focus()
  }

  return (
    <div>
      {fallback && fallback.how !== 'none' && (
        <p className="muted outline-fallback-note" style={{ fontSize: 'var(--t-xs)', margin: '0 0 6px', lineHeight: 1.6 }}>
          {fallback.how === 'colon'
            ? '这篇没有 # 标题，按「xx：」这样的短行列；加上 # 标题就按标题列。'
            : `这篇没有 # 标题，按段落列（${headings.length} 段，每段取首句）；加上 # 标题就按标题列。`}
        </p>
      )}
      {statuses.length > 0 && (
        <p className="muted plan-outline-summary" title="每一节的状态从正文算出来：空 = 标题下面一个字都没有；草稿 = 有字、没出处；有依据 = 引用了知识库事实或链到了别的笔记">
          {statuses.length} 节 · 空 {summary.empty} · 草稿 {summary.draft} · 有依据 {summary.sourced}
        </p>
      )}
      <div className="stack" style={{ gap: 2 }} ref={listRef}>
        {headings.map((h, i) => {
          const s = statusAt.get(h.pos)
          const mats = s ? materialsText(s) : ''
          return (
            <a
              key={i}
              className={'link outline-item' + (h.pos === activePos ? ' active' : '') + (s ? ' with-state' : '')}
              style={{
                display: s ? 'flex' : 'block', fontSize: 'var(--t-sm)',
                paddingLeft: 6 + (h.level - 1) * 12,
                textDecoration: 'none',
              }}
              title={s ? `${SECTION_LABEL[s.state]}${s.words ? ` · ${s.words} 字` : ''}${mats ? ` · ${mats}` : ''}` : undefined}
              onClick={() => jump(h.pos)}
            >
              <span className="outline-text">{h.text}</span>
              {s && (
                <span className={'plan-state ' + s.state}>
                  {SECTION_LABEL[s.state]}{s.cites + s.links > 0 ? ` ${s.cites + s.links}` : ''}
                </span>
              )}
            </a>
          )
        })}
      </div>
    </div>
  )
}
