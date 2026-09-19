/** 边缘记忆（docs/agent-native-editor.md §3.3）：正文右缘一条「记忆带」——哪一段跟知识库
 *  有关系（冲突 / 延续 / 叠加 / 合并 / 印证 / 缺依据）就在那一段的第一行右边亮一个点，颜色 = 关系。
 *
 *  P9 之前点只有一个原生 `title` 悬停 + 点一下切到右栏；方案 §1 第 2 行说这还是「右栏旁观者」：
 *  真正的记忆应该在你写到「DVT 延期」的那一行旁边告诉你「上次记的是 6/3」。所以现在：
 *    · 悬停 / 点圆点 → 关系卡贴在圆点旁边（`onOpen(m, 圆点的矩形, 'hover' | 'click')`）
 *    · 光标进了亮**黄点（冲突）/ 紫点（延续）**的段落 → 卡自己出来一次（`'cursor'`）：这两种是
 *      「知识库有话要说」的关系；印证 / 缺依据 / 叠加 / 合并 静默，要看才悬停
 *    · 每个点（关系 + 事实）自动弹一次，用户关掉就不再自动弹
 *  数据由上层批量算好塞进来（零 LLM 的代码候选，`relations/batch` 连事实一起回），
 *  这里只管画、跟着文档改动映射行号、和「什么时候把卡叫出来」。 */
import { StateEffect, StateField, type Extension } from '@codemirror/state'
import { EditorView, gutter, GutterMarker } from '@codemirror/view'
import type { Fact, MemoryRelationKind } from '../api'

export type MarginMark = {
  /** 1 起的行号（段落第一行） */
  line: number
  relation: MemoryRelationKind
  say: string
  /** 这段一共判出几种关系；点只画最要紧的一种 */
  kinds?: number
  /** 卡上要列的那几条记录（日期 + 原话），`relations/batch` 一起回（P9） */
  fact_ids?: string[]
  facts?: Fact[]
  /** 只有「缺依据」有：`no_record` = 知识库里连沾边的记录都没有；`no_value` = 沾边的有、但都没带这段的量。
   *  后端 `kb/relations.detect()` 判的（零模型，就是 `related` 空不空）。 */
  why?: string
}

/** **哪些点真的画到页边上**（P25 #4，P22 #8）。
 *
 *  P7 修好了「该有点没点」（40 → 137 个点），代价是真库最长那篇 26.7k 字的展厅讲解词
 *  右边缘挂了 **106 个灰圈**（136 个含数字段的 78%）。逐条读过那 106 段：**89 段**是
 *  `no_record`——召回回来的 8 条没有一条沾边，昇腾份额、NVL72 单柜卡数、深圳 25 万路
 *  摄像头，知识库里根本没这个话题。
 *
 *  **一个点该告诉用户什么**：「**这一段**跟知识库之间有一件你该知道的事」。
 *  `no_value` 是这样的一件事——「有沾边的记录，但那条记录里没有你写的这个数，这个数还没有出处」，
 *  用户看得懂、也能去核。`no_record` 不是：它说的是「这篇笔记跟你的知识库不搭界」，
 *  **这是整篇的属性，不是这一段的**；逐段画就是把同一句话说 89 遍，一整列灰圈等于噪声。
 *  所以 `no_record` 不画点，改成面板上**一句话说清楚有多少段**（`noRecordNote`）；
 *  光标停在那一段时右栏的关系卡照旧逐字说（`POST /memory/relations` 那条路一个字没改）。
 */
export function dotWorthy(m: { relation: MemoryRelationKind; why?: string }): boolean {
  return !(m.relation === 'unsupported' && m.why === 'no_record')
}

/** 被折起来的那一档在面板上的一句话（`n` = 这篇里 `no_record` 的段数）。 */
export function noRecordNote(n: number): string {
  return `这篇还有 ${n} 段带了数字，知识库里连沾边的记录都没有——没有逐段画点（一整列灰圈说的是同一件事）；光标停在那一段上，右栏会说。`
}

/** 六种关系的人话。右栏关系卡、页边圆点的悬停、图例三处同一份。 */
export const RELATION_LABEL: Record<MemoryRelationKind, string> = {
  conflict: '冲突', continuation: '延续', corroborated: '印证', unsupported: '缺依据', accumulation: '叠加', merge: '合并',
}

/** 圆点的规则，一句话（P1-1d，用户第 768 轮问「一个点代表一行还是一段？绿色黄色是什么？」）。
 *  写在这里而不是散在各处：悬停提示、右栏图例读的是同一句。 */
export const MARGIN_RULE = '页边圆点：每段一个（空行隔开算一段），只看含数字 / 日期的段落——判的是量的比对，圆点零模型'
/** 空库时右栏「记忆」顶上那**一句**（P31 #8；它替掉了 P17 加的 `KB_EMPTY_DOTS_NOTE`，
 *  那句话说的事一个字没少——知识库空着时一个点都不会有，后端 `relations_batch` 直接回一排 null，
 *  不说出来新用户会照着写了带数字的段等半天）。
 *
 *  **为什么并成一句**：第一天的用户在这儿看到的原来是**四段**图例——圆点规则 / 六种颜色 /
 *  光标停 0.9 秒 / 冲突才让模型复核，再加这一句。**一条记录都没有的时候这几段的信息量是零**，
 *  却占掉大半屏。规则本身没删，收进「想看再展开」里，旁边给一个真的能点的「导入」。 */
export const KB_EMPTY_NOTE = '知识库还是空的，导入或录一段就有了——存进第一条记录之前页边不画圆点，这里也不会有记忆。'

/** 图例里「零模型」差的那一个条件（P4 #10）：右栏关系卡判到「冲突」时，后端会让模型把那句人话复核 / 改写一次
 *  （`routers/memory.py` `relations`，只对 conflict 候选）；圆点（`relations/batch`）不会。 */
export const MODEL_NOTE = '关系卡里判到「冲突」时会让模型复核一次那句话；其余（圆点、印证、缺依据、叠加、合并、延续）全是代码判的。'

/** 哪几种关系值得**自己**贴到行边上来（不用悬停）：知识库有话要说的两种。其余静默，要看才悬停。 */
export const AUTO_SHOW: ReadonlySet<MemoryRelationKind> = new Set<MemoryRelationKind>(['conflict', 'continuation'])

/** 一个点的身份：关系 + 事实。行号会变，这个不变——「自动弹过一次」按它记。 */
export function markKey(m: MarginMark): string { return m.relation + ':' + (m.fact_ids ?? []).join(',') }

/** 悬停在点上看到的话（卡片顶上那行；原生 title 保留给读屏）：这一段 · 关系 · 那句人话。 */
export function markTitle(m: MarginMark): string {
  const more = (m.kinds ?? 1) > 1 ? `这段还判出另外 ${(m.kinds ?? 1) - 1} 种关系，` : ''
  return `这一段（第 ${m.line} 行起）· ${RELATION_LABEL[m.relation]}\n${m.say}\n${MARGIN_RULE}\n${more}点一下在右栏「记忆」看全部`
}

/** 哪些段落会拿去判关系：**跟后端 `relations_batch` 同一条门槛**（≥8 字、含数字、不是标题）。
 *  不封顶——原来 `.slice(0, 80)` 把 30k 字笔记第 80 个含数字的段落之后全丢了，
 *  「有的段有点、有的段没有」正是从这儿来的；请求按 80 一批分几次发（后端每批上限 80）。 */
export const MARGIN_BATCH = 80
export function marginParagraphs(content: string, clean: (s: string) => string): { text: string; line: number }[] {
  return paragraphsWithLines(content).map((p) => ({ ...p, text: clean(p.text).trim() }))
    .filter((p) => /\d/.test(p.text) && !p.text.startsWith('#') && p.text.length >= 8)
}
/** 一段的判定结果（不带行号）；null = 这段没关系。 */
export type MarginVerdict = Omit<MarginMark, 'line'> | null

/** 按段落文本缓存判定（P10 C3-5）：30k 字的笔记 244 段要 3 批请求、停手后 **15.6 秒**才画出第一个点
 *  （`p10-perf-before`），而且每敲一个字整批重来——真在写长文时圆点等于永远不出现。判定只看段落文本
 *  （+ 知识库），文本没变的段不用再问；改了一段就只问那一段。返回：命中的直接带行号，没命中的去问后端。
 *  知识库变了（摄入 / 换范围）由上层清缓存。 */
export function splitCached(paras: { text: string; line: number }[], cache: Map<string, MarginVerdict>):
    { hits: MarginMark[]; misses: { text: string; line: number }[] } {
  const hits: MarginMark[] = []
  const misses: { text: string; line: number }[] = []
  for (const p of paras) {
    if (cache.has(p.text)) { const v = cache.get(p.text); if (v) hits.push({ ...v, line: p.line }) }
    else misses.push(p)
  }
  return { hits, misses }
}
/** 缓存别无限长：超过这个数就清空重来（一篇 30k 字的笔记也就 250 段）。 */
export const MARGIN_CACHE_MAX = 3000

export function chunked<T>(xs: T[], n: number): T[][] {
  const out: T[][] = []
  for (let i = 0; i < xs.length; i += n) out.push(xs.slice(i, i + n))
  return out
}

export const setMarginMarks = StateEffect.define<MarginMark[]>()

class Dot extends GutterMarker {
  constructor(readonly m: MarginMark) { super() }
  eq(other: Dot) { return other.m.relation === this.m.relation && other.m.say === this.m.say && other.m.line === this.m.line }
  toDOM() {
    const el = document.createElement('span')
    el.className = 'mm-dot mm-' + this.m.relation
    el.title = markTitle(this.m)
    el.dataset.line = String(this.m.line)
    el.setAttribute('aria-label', RELATION_LABEL[this.m.relation])
    return el
  }
}

export const marginField = StateField.define<MarginMark[]>({
  create: () => [],
  update(marks, tr) {
    for (const e of tr.effects) if (e.is(setMarginMarks)) return e.value
    if (!tr.docChanged || marks.length === 0) return marks
    // 行号跟着文档改动走：把段首位置映射过去再换算回行号
    const old = tr.startState.doc
    return marks.map((m) => {
      const ln = Math.min(Math.max(1, m.line), old.lines)
      const pos = tr.changes.mapPos(old.line(ln).from, 1)
      return { ...m, line: tr.newDoc.lineAt(Math.min(pos, tr.newDoc.length)).number }
    })
  },
})

/** 光标所在段落的第一行行号（空行隔开算一段）——跟 `paragraphsWithLines` 同一种分段。 */
export function paragraphStartLine(doc: { lines: number; line(n: number): { text: string } }, lineNo: number): number {
  let n = Math.min(Math.max(1, lineNo), doc.lines)
  if (!doc.line(n).text.trim()) return 0            // 光标在空行上：不属于任何段
  while (n > 1 && doc.line(n - 1).text.trim()) n--
  return n
}

/** 圆点在屏幕上的位置（画出来了才有；不在视口里的行 CM 不画） */
function dotRect(view: EditorView, line: number): DOMRect | null {
  const el = view.dom.querySelector(`.cm-memory-gutter .mm-dot[data-line="${line}"]`)
  return el ? el.getBoundingClientRect() : null
}

export type MarginOpen = (m: MarginMark | null, anchor: DOMRect | null, reason: 'hover' | 'click' | 'cursor') => void

export function marginMemory(onOpen: MarginOpen): Extension {
  // 自动弹过的点：一个点只自己出来一次，关掉就不再烦人；换一批标记（正文改了）重新算
  const autoShown = new Set<string>()
  const find = (view: EditorView, lineFrom: number) => {
    const n = view.state.doc.lineAt(lineFrom).number
    return view.state.field(marginField).find((x) => x.line === n) ?? null
  }
  return [
    marginField,
    gutter({
      class: 'cm-memory-gutter',
      side: 'after',
      lineMarker(view, line) {
        const n = view.state.doc.lineAt(line.from).number
        const m = view.state.field(marginField).find((x) => x.line === n)
        return m ? new Dot(m) : null
      },
      lineMarkerChange: (u) => u.docChanged || u.transactions.some((t) => t.effects.some((e) => e.is(setMarginMarks))),
      domEventHandlers: {
        mousedown(view, line) {
          const m = find(view, line.from)
          if (!m) return false
          view.dispatch({ selection: { anchor: line.from }, effects: EditorView.scrollIntoView(line.from, { y: 'nearest' }) })
          onOpen(m, dotRect(view, m.line), 'click')
          return true
        },
        mouseover(view, line, event) {
          if (!(event.target as HTMLElement | null)?.classList?.contains('mm-dot')) return false
          const m = find(view, line.from)
          if (m) onOpen(m, (event.target as HTMLElement).getBoundingClientRect(), 'hover')
          return false
        },
      },
    }),
    // 光标进了「知识库有话要说」的段落：卡自己贴到行边上来（一次）
    EditorView.updateListener.of((u) => {
      const marksChanged = u.transactions.some((t) => t.effects.some((e) => e.is(setMarginMarks)))
      if (!u.selectionSet && !marksChanged) return
      if (marksChanged) autoShown.clear()
      const head = u.state.selection.main.head
      const start = paragraphStartLine(u.state.doc, u.state.doc.lineAt(head).number)
      if (!start) return
      const m = u.state.field(marginField).find((x) => x.line === start)
      if (!m || !AUTO_SHOW.has(m.relation)) return
      const key = markKey(m)
      if (autoShown.has(key)) return
      autoShown.add(key)
      // 圆点要等这次更新画完才在 DOM 里
      requestAnimationFrame(() => { const r = dotRect(u.view, m.line); if (r) onOpen(m, r, 'cursor') })
    }),
  ]
}

/** 把正文按空行切成段，给每段的第一行行号（1 起）。跟后端一起用：段落文本去查关系，行号回来画点。 */
export function paragraphsWithLines(content: string): { text: string; line: number }[] {
  const out: { text: string; line: number }[] = []
  const lines = content.split('\n')
  let i = 0
  while (i < lines.length) {
    if (!lines[i].trim()) { i++; continue }
    const start = i
    const buf: string[] = []
    while (i < lines.length && lines[i].trim()) { buf.push(lines[i]); i++ }
    out.push({ text: buf.join('\n'), line: start + 1 })
  }
  return out
}
