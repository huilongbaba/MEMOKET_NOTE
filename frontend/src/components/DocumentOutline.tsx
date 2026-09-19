import { useEffect, useMemo, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { EditorView } from '@codemirror/view'
import { SECTION_LABEL, materialsText, sectionStatuses, sectionSummary } from '../util/sectionStatus'

type Heading = { level: number; text: string; pos: number }

/** 一行里**夹着第二个标题标记**（P22 #9）。实拍：真库 `92d07b760f1e` 的 L23 是
 *  `## 我们该如何克服挑战：### 如何克服挑战：`——harness 早期留下的重复标题，两半说的是同一件事。
 *  `/^(#{1,6})\s+(.+)$/` 把行尾整段当标题文字，目录里就原样显示 `我们该如何克服挑战：### 如何克服挑战：`，
 *  一行 markdown 源码冒在导航面板上。目录那一行要的是**读得懂的字**（跟 `stripInline` 同一条理由），
 *  所以在这个标记处**截断**，只留外层那一句。
 *
 *  为什么是截断而不是拆成两条：在真库 482 篇上扫过（`<scratch>/p25/scan_inline_headings.py`），
 *  这种行**总共只有这 1 处**，而且内层（`如何克服挑战：`）是外层的近似重复——拆成两条等于给同一节
 *  两行导航。真要是内容不同的一天，截断至少不会把源码摆到面板上。
 *
 *  **不能误伤真标题里的 `#`**：`## 关于 C# 的笔记`（`#` 前面是字母）、`## 问题 #3 复盘`（`#` 后面
 *  不是空格）都不算——所以要求「前面不是字母 / 数字 / `#`」且「后面至少一个空格再接非空白」。 */
const INLINE_HEADING = /(?<![A-Za-z0-9#])#{1,6}\s+\S/

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
    const inner = INLINE_HEADING.exec(m[2])
    const text = (inner ? m[2].slice(0, inner.index) : m[2]).trim()
    if (!text) continue                            // 整行就是一个夹进来的标记，没有外层文字
    out.push({ level: m[1].length, text, pos: m.index })
  }
  return out
}

/** 没有 `#` 标题时的目录（P7，P4 #3）：26.7k 字的展厅讲解词零个 `#`，目录面板一片空白，用户在最长的一篇里
 * 没有任何导航。退两步：
 *   1. 单独占一段的**短行**当伪标题（≥ 3 个才用这档）：「算力底座：」这种冒号收尾的，和
 *      「智慧教育」「鲲鹏」这种**不带标点**的（P25 #2 / P22 #9 补的第二种）；
 *   2. 都没有就**按段落列**，每段取首句（≤ 28 字）。
 * 两档都在面板顶上说一句「这篇没有 # 标题，按 xx 列」，别让人以为它认出了标题。
 *
 * **为什么不收「油气：主要是跟随一滴油的生命周期…」这种「冒号后面接正文」的**（P22 #9 的另一半）：
 * 在 N1 上量过（`<scratch>/p25/` 那次 fallback 重放）——这种段落全篇 **80 段**，去掉重复前缀（案例 ×8、
 * 方案 ×5、华为 ×2）还有 **65 段**，收进来目录从 24 条涨到 89 条，多出来的是「同时」「问题」「（细节数据」
 * 「- 全光通信*光模块」这类，而真正想要的行业段只有「油气」「化工」两条。**代码分不开「行业名：」和
 * 「案例：」——它们是同一个形状**，按重复次数过滤也只砍掉 3 个前缀。拿 65 条噪声换 2 条，不换。 */
export type FallbackOutline = { items: Heading[]; how: 'short' | 'paragraph' | 'none' }
const COLON_HEAD = /^(.{1,16}?)\s*[：:]\s*$/
/** 不带冒号的短行伪标题（「智慧教育」「鲲鹏」「山东东营 HG14 海上光伏」）：整段就这么一行、
 *  **不以标点收尾**（「双方共建 AI 场景。」是句子不是标题）、**不是列表项 / 编号条**
 *  （`- 72-1024 卡区间`、`（2） 翻译准确率显著` 是正文的一条，不是一节）。 */
const BARE_HEAD = /^(?![-*+>])(?!\(?（?\d+[）)、.]\s*)[^\s].{0,15}[^\s。！？；，、：:.!?;,…—-]$/
const PARA_MIN_CHARS = 20
const FALLBACK_MAX = 200

/** 目录里那一行要的是**读得懂的字**，不是 markdown 源码（P19 #4 / P17 #11）。
 *  实拍：只有一个链接的段落在「计划」页签里列成 `[试菜单](note://9aab…)`（`p17-12-new-dark-plan`）——
 *  一串 id 占满整行，人看不出那是哪篇。这里把链接 / 强调 / 行内代码 / 图片的语法壳剥掉，只留标签文字。 */
export function stripInline(s: string): string {
  return s
    .replace(/!\[([^\]\n]*)\]\([^)\s]*\)/g, (_m, alt) => (alt ? `图：${alt}` : '图'))   // 图片：留 alt
    .replace(/\[([^\]\n]*)\]\([^)\s]*\)/g, '$1')                                      // 链接：留标签
    .replace(/\[\[([^\]|\n]*\|)?([^\]\n]*)\]\]/g, '$2')                                 // wiki 链接：留标签
    .replace(/`([^`\n]*)`/g, '$1')                                                      // 行内代码
    .replace(/\*\*([^*\n]+)\*\*|__([^_\n]+)__/g, (_m, a, b) => a ?? b)                   // 粗体
    .replace(/(?<![*\w])\*([^*\n]+)\*(?!\*)/g, '$1')                                    // 斜体
    .replace(/~~([^~\n]+)~~/g, '$1')                                                    // 删除线
    .trim()
}

function firstSentence(s: string): string {
  const t = stripInline(s.replace(/^[-*>\s]+|^\d+[.、]\s*/g, '').trim())
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
  const heads = paras.filter((p) => p.len <= 17 && p.len >= 2 && (COLON_HEAD.test(p.first) || BARE_HEAD.test(p.first)))
  if (heads.length >= 3) {
    return { how: 'short', items: heads.slice(0, FALLBACK_MAX).map((p) => ({ level: 1, text: stripInline(p.first.replace(/\s*[：:]\s*$/, '')), pos: p.pos })) }
  }
  const long = paras.filter((p) => p.len >= PARA_MIN_CHARS)
  if (long.length >= 2) {
    return { how: 'paragraph', items: long.slice(0, FALLBACK_MAX).map((p) => ({ level: 1, text: firstSentence(p.first), pos: p.pos })) }
  }
  return { how: 'none', items: [] }
}

/** 目录里该亮哪一节（P13 #3；P12 下一步④）。纯函数，`headings` 按位置升序。
 *
 *  老规则：滚动区顶部那一行属于哪一节（Obsidian 的 outline 也这么做）。它有两个漏：
 *   · **滚到底了**：文末那一节短到撑不满一屏时，顶上那一行永远属于上一节——点目录最后一节跳过去，
 *     高亮的却是上一节（P12 `p12-jump` 实拍 `active=团队建设`）。滚到底就亮视口里最后一个标题。
 *   · **刚点过目录**：`pinned` 是刚点的那一节，只要它的标题还在视口里就亮它——用户点了「反思」，
 *     就不该因为顶上那一行是「团队建设」的尾巴而亮「团队建设」；滚走了（标题出了视口）才交回老规则。 */
export function activeHeadingPos(
  headings: { pos: number }[],
  topPos: number, bottomPos: number, atBottom: boolean, pinned: number | null = null,
): number {
  if (pinned != null && headings.some((h) => h.pos === pinned) && pinned >= topPos && pinned <= bottomPos) return pinned
  let active = -1
  for (const h of headings) if (h.pos <= topPos) active = h.pos
  if (atBottom) for (const h of headings) if (h.pos <= bottomPos) active = h.pos
  return active
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
  // 刚点过目录的那一节（P13 #3）：标题还在视口里就亮它；滚走了才交回「顶上那一行」的老规则
  const pinnedRef = useRef<number | null>(null)
  useEffect(() => {
    const view = viewRef.current
    const scroller = view?.scrollDOM.closest('.note-scroll') as HTMLElement | null
    if (!view || !scroller || headings.length === 0) return
    const update = () => {
      const r = scroller.getBoundingClientRect()
      const at = (y: number) => view.posAtCoords({ x: r.left + 60, y }) ?? view.posAtCoords({ x: r.left + 60, y }, false) ?? 0
      const topPos = at(r.top + 90)
      const bottomPos = at(r.bottom - 10)
      const atBottom = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 2
      const active = activeHeadingPos(headings, topPos, bottomPos, atBottom, pinnedRef.current)
      if (pinnedRef.current != null && active !== pinnedRef.current) pinnedRef.current = null
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
    pinnedRef.current = pos
    setActivePos(pos)
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
          {fallback.how === 'short'
            ? '这篇没有 # 标题，按「算力底座：」「智慧教育」这样单独一行的短行列；加上 # 标题就按标题列。'
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
