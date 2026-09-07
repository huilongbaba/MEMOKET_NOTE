import { StateEffect, StateField, type Range } from '@codemirror/state'
import {
  Decoration, EditorView, WidgetType, showTooltip,
  type DecorationSet, type Tooltip,
} from '@codemirror/view'

/** 「这一轮改了什么」——高亮 + 逐处接受/撤回。
 *
 * harness 是**自动应用**改动的：正文突然多了几段、少了几句，用户完全不知道
 * 被动了哪里。这一层先补上可见性（新增标绿、删掉的原文以删除线就地补出来），
 * 再补上处置权：鼠标移到任意一处改动上，就地出现「接受 / 撤回」。
 *
 * **改动是按 hunk 管理的，位置跟着文档编辑一起映射**——所以用户可以先在
 * 绿色新增里改几个字，改完再点接受。第一版是"文档一变就把所有高亮丢掉"，
 * 那样连"改完再接受"都做不到，光标一动整轮改动就看不见了。
 *
 * 跟 revisions.ts 区分：那个是**还没应用**的修订建议；这里是**已经应用**的，
 * 撤回要把原文写回去。
 */

export type DiffPart = { type: 'keep' | 'ins' | 'del'; text: string }

/** 切成可比较的片段：中文按单字、英文/数字按词、空白和标点各自成段。
 * 中文按字切是刻意的——按整句切的话，改一个词整段都会标红标绿，看不出
 * 到底动了哪里。 */
function segment(s: string): string[] {
  return s.match(/[一-鿿]|[A-Za-z0-9_]+|\s+|[^\s一-鿿 A-Za-z0-9_]/g) ?? []
}

/** 词级 diff。先掐掉公共前后缀再对中间做 LCS——一轮的改动通常只占全文
 * 很小一块，掐完之后要跑 LCS 的部分很小，不用担心 O(n·m)。 */
export function diffParts(before: string, after: string): DiffPart[] {
  const a = segment(before)
  const b = segment(after)

  let head = 0
  while (head < a.length && head < b.length && a[head] === b[head]) head++
  let tail = 0
  while (tail < a.length - head && tail < b.length - head
    && a[a.length - 1 - tail] === b[b.length - 1 - tail]) tail++

  const am = a.slice(head, a.length - tail)
  const bm = b.slice(head, b.length - tail)

  const out: DiffPart[] = []
  const push = (type: DiffPart['type'], text: string) => {
    if (!text) return
    const last = out[out.length - 1]
    if (last && last.type === type) last.text += text
    else out.push({ type, text })
  }

  push('keep', a.slice(0, head).join(''))

  // 中间段太大时不做 LCS，直接整段标成删+增。真实场景里这意味着这一轮
  // 几乎重写了全文，逐词对比也没有阅读价值，还会卡住 UI。
  if (am.length * bm.length > 400_000) {
    push('del', am.join(''))
    push('ins', bm.join(''))
  } else {
    const n = am.length
    const m = bm.length
    const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0))
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        dp[i][j] = am[i] === bm[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
      }
    }
    let i = 0
    let j = 0
    while (i < n && j < m) {
      if (am[i] === bm[j]) { push('keep', am[i]); i++; j++ }
      else if (dp[i + 1][j] >= dp[i][j + 1]) { push('del', am[i]); i++ }
      else { push('ins', bm[j]); j++ }
    }
    while (i < n) { push('del', am[i]); i++ }
    while (j < m) { push('ins', bm[j]); j++ }
  }

  push('keep', a.slice(a.length - tail).join(''))
  return out
}


// ---------------------------------------------------------------- hunk 模型

/** 一处改动。``from``/``to`` 是**文档里的活位置**：每次文档变动都跟着映射，
 * 所以用户可以在绿色新增里改字、改完再接受。``del`` 是被删掉的原文
 * （它已经不在文档里，只能靠 widget 补出来；撤回时写回去的也是它）。 */
export type Hunk = { id: number; from: number; to: number; del: string }

/** 相邻两处改动之间没动过的文字不超过这么多字，就并成一处。
 * 8 个字大约是「改了一个词、隔几个字又改一个词」的距离——再大就会
 * 把两件不相干的修改捆在一起，用户想只接受其中一处都做不到。 */
const MERGE_GAP = 8

export const setRoundDiff = StateEffect.define<DiffPart[] | null>()
/** 接受：只是把这一处从待处置列表里去掉，正文保持现状。 */
export const acceptHunk = StateEffect.define<number>()
/** 撤回：连同一次文档改动一起 dispatch（把 from..to 换回 del），这里只负责摘掉标记。 */
export const dropHunk = StateEffect.define<number>()
export const acceptAllHunks = StateEffect.define<null>()

/** diff 结果 → hunk 列表。
 *
 * **相邻的 del + ins 合并成一处**：那是一次"替换"，用户要的是把它当一件事
 * 接受或撤回，拆成两处的话点了接受还剩半截删除线挂在那儿。 */
export function toHunks(parts: DiffPart[] | null): Hunk[] {
  if (!parts?.length) return []
  const out: Hunk[] = []
  let pos = 0
  let id = 0
  // 距上一处改动之间「没动过」的文字。中文是**逐字** diff 的（按整句切的话
  // 改一个词整段都标红标绿，看不出动了哪儿），代价是"四月中旬"vs"三月上旬"
  // 会切成两处、各自只盖一个字——悬停操作的粒度太碎。隔得很近的两处合并成
  // 一处：合并后 del 要带上中间这段没动过的文字，撤回才能精确还原。
  let gap = ''
  const push = (h: Omit<Hunk, 'id'>) => {
    const prev = out[out.length - 1]
    if (prev && gap.length <= MERGE_GAP && prev.to + gap.length === h.from) {
      prev.to = h.to
      prev.del = prev.del + gap + h.del
    } else {
      out.push({ id: id++, ...h })
    }
    gap = ''
  }
  for (let i = 0; i < parts.length; i++) {
    const p = parts[i]
    if (p.type === 'keep') { pos += p.text.length; gap += p.text; continue }
    if (p.type === 'del') {
      const next = parts[i + 1]
      if (next?.type === 'ins') {                 // 替换：合成一处
        push({ from: pos, to: pos + next.text.length, del: p.text })
        pos += next.text.length
        i++
      } else {
        push({ from: pos, to: pos, del: p.text })
      }
      continue
    }
    push({ from: pos, to: pos + p.text.length, del: '' })
    pos += p.text.length
  }
  return out
}

// ---------------------------------------------------------------- 装饰

/** 被删掉的原文——它已经不在文档里了，只能用 widget 就地补一个。 */
class DeletedWidget extends WidgetType {
  constructor(readonly text: string, readonly id: number) { super() }
  eq(other: DeletedWidget) { return other.text === this.text && other.id === this.id }
  toDOM() {
    const span = document.createElement('span')
    span.className = 'harness-del'
    span.textContent = this.text
    span.title = '这一轮删掉的内容'
    return span
  }
  ignoreEvent() { return true }
}

function build(hunks: Hunk[]): DecorationSet {
  const decos: Range<Decoration>[] = []
  for (const h of hunks) {
    if (h.del) {
      decos.push(Decoration.widget({ widget: new DeletedWidget(h.del, h.id), side: -1 })
        .range(h.from))
    }
    if (h.to > h.from) {
      decos.push(Decoration.mark({
        class: 'harness-ins',
        attributes: { title: '这一轮新增的内容' },
      }).range(h.from, h.to))
    }
  }
  return Decoration.set(decos, true)
}

// ---------------------------------------------------------------- state

export const roundDiffField = StateField.define<{ hunks: Hunk[]; decos: DecorationSet }>({
  create() { return { hunks: [], decos: Decoration.none } },
  update(value, tr) {
    for (const e of tr.effects) {
      if (e.is(setRoundDiff)) {
        const hunks = toHunks(e.value)
        return { hunks, decos: build(hunks) }
      }
      if (e.is(acceptAllHunks)) return { hunks: [], decos: Decoration.none }
    }
    let hunks = value.hunks
    for (const e of tr.effects) {
      if (e.is(acceptHunk) || e.is(dropHunk)) hunks = hunks.filter((h) => h.id !== e.value)
    }
    if (tr.docChanged && hunks.length) {
      // **跟着文档改动映射，而不是把高亮丢掉。** 用户在绿色新增里打字时这一处
      // 要跟着变长，所以两端的 assoc 都取 1：
      //   from=1 → 正好插在起点的字排在这处**外面**（在改动前面打字不算改动）
      //   to  =1 → 正好插在终点的字排在这处**里面**（在末尾续写算这处的一部分）
      // 第一版 to 取了 -1，注释写的是"让插入落在区间内部"，代码是反的——
      // 在绿色新增末尾补一个字，那个字会被排除出去，改完再接受就接受不全。
      hunks = hunks
        .map((h) => ({
          ...h,
          from: tr.changes.mapPos(h.from, 1),
          to: tr.changes.mapPos(h.to, 1),
        }))
        // 新增被用户整段删光、且没有原文可撤回 —— 这处已经不存在了
        .filter((h) => h.to >= h.from && (h.to > h.from || h.del))
    }
    if (hunks === value.hunks) return value
    return { hunks, decos: build(hunks) }
  },
  provide: (f) => EditorView.decorations.from(f, (v) => v.decos),
})

/** 还剩几处没处置。给上层显示「本轮 N 处改动」用。 */
export function pendingHunks(view: EditorView): number {
  return view.state.field(roundDiffField, false)?.hunks.length ?? 0
}

// ---------------------------------------------------------------- 悬停工具条

/** 「接受 / 撤回」为什么用 tooltip 而不是塞一个 widget 进正文，靠 CSS 相邻
 * 选择器显示：
 *
 * **CM6 会在不可编辑的 inline widget 两侧插入 `<img class="cm-widgetBuffer">`**
 * （绕开光标贴着 widget 时的浏览器 bug），真实 DOM 是
 * `…<span class="harness-ins">…</span><img class="cm-widgetBuffer"><span class="harness-actions">`，
 * 于是 `.harness-ins:hover + .harness-actions` 永远匹配不上——按钮根本不出现。
 * 而这个 buffer 是按情况插的，写成 `+ img + span` 同样脆弱。
 *
 * 改成 JS 判定悬停在哪一处 + tooltip 定位，跟 DOM 长什么样无关。
 */
/** 导出仅为可测：这套 UI 做坏过两版（构建通过、按钮不出现），
 * scripts/check-diff-ui.mts 要能直接构造悬停状态来验 tooltip。 */
export const setHover = StateEffect.define<number | null>()

const hoverField = StateField.define<number | null>({
  create: () => null,
  update(v, tr) {
    for (const e of tr.effects) if (e.is(setHover)) return e.value
    // 这一处被接受/撤回之后就不该再吊着工具条
    for (const e of tr.effects) {
      if ((e.is(acceptHunk) || e.is(dropHunk)) && e.value === v) return null
    }
    if (tr.effects.some((e) => e.is(setRoundDiff) || e.is(acceptAllHunks))) return null
    return v
  },
})

function actionsDom(view: EditorView, h: Hunk): HTMLElement {
  const wrap = document.createElement('div')
  wrap.className = 'harness-actions'
  const mk = (label: string, title: string, cls: string, run: () => void) => {
    const b = document.createElement('button')
    b.type = 'button'
    b.className = cls
    b.textContent = label
    b.title = title
    // mousedown + preventDefault：click 之前编辑器就会把焦点和选区挪到按钮上，
    // 正文里的光标位置会丢。
    b.addEventListener('mousedown', (e) => {
      e.preventDefault()
      e.stopPropagation()
      pinned = false
      keepHover = false
      run()
    })
    return b
  }
  wrap.append(
    mk('✓ 接受', '保留这处改动', 'harness-accept',
      () => view.dispatch({ effects: acceptHunk.of(h.id) })),
    mk(h.del ? '↩ 撤回' : '↩ 删掉', h.del ? '把原文改回去' : '删掉这段新增', 'harness-reject',
      () => {
        const cur = view.state.field(roundDiffField).hunks.find((x) => x.id === h.id)
        if (!cur) return
        // 撤回是一次真正的文档改动：把 from..to 换回被删掉的原文。同一个事务里
        // 带上 dropHunk，剩下的 hunk 会跟着这次改动映射位置。
        view.dispatch({
          changes: { from: cur.from, to: cur.to, insert: cur.del },
          effects: dropHunk.of(h.id),
        })
      }),
  )
  wrap.addEventListener('mouseenter', () => { keepHover = true; cancelClear() })
  wrap.addEventListener('mouseleave', () => { keepHover = false; scheduleClear(view) })
  return wrap
}

// 鼠标是不是正停在工具条上。整个编辑器只有一个实例，模块级状态够用。
let keepHover = false
let clearTimer: ReturnType<typeof setTimeout> | null = null

function cancelClear() {
  if (clearTimer) { clearTimeout(clearTimer); clearTimer = null }
}

/** 鼠标离开改动之后**延迟**再关工具条。
 *
 * 不延迟的话它根本点不到：工具条浮在改动**上方**，鼠标往上移会先经过上一行
 * 普通文字，那一下 mousemove 判定"不在任何改动上"就立刻把它关了——用户看到的
 * 是"能浮出来、但一伸手就没了"。220ms 够走完这一小段路，又短到不会在正文上
 * 拖着一个甩不掉的浮层。 */
function scheduleClear(view: EditorView) {
  cancelClear()
  clearTimer = setTimeout(() => {
    clearTimer = null
    if (keepHover || pinned) return
    if (view.state.field(hoverField, false) != null) view.dispatch({ effects: setHover.of(null) })
  }, 220)
}

const hunkTooltip = showTooltip.compute([roundDiffField, hoverField], (state): Tooltip | null => {
  const id = state.field(hoverField)
  if (id == null) return null
  const h = state.field(roundDiffField).hunks.find((x) => x.id === id)
  if (!h) return null
  return {
    pos: h.from,
    end: h.to,
    above: true,
    arrow: false,
    create: (view) => ({ dom: actionsDom(view, h) }),
  }
})

/** 钉住：点一下改动，工具条就不再自动消失。
 *
 * 悬停这条路依赖"鼠标从文字挪到浮层"这段路径上的时机，宽限期只是把窗口
 * 放大，仍然是个时机问题。点击钉住不依赖任何时机——按钮一定点得到。
 * 按 Esc、点别处、或者点完接受/撤回都会解钉。 */
let pinned = false

/** 悬停判定。用 posAtCoords 直接问「鼠标在文档的哪个位置」，比读 DOM 结构可靠。 */
const hoverWatcher = EditorView.domEventHandlers({
  mousedown(e, view) {
    if (e.button !== 0) return false
    const hunks = view.state.field(roundDiffField, false)?.hunks
    if (!hunks?.length) return false
    const pos = view.posAtCoords({ x: e.clientX, y: e.clientY })
    const hit = pos == null ? null : hunks.find((h) => pos >= h.from - 1 && pos <= h.to + 1)
    cancelClear()
    pinned = !!hit
    const next = hit ? hit.id : null
    if (next !== view.state.field(hoverField)) view.dispatch({ effects: setHover.of(next) })
    return false                                   // 不拦截：光标该落哪落哪
  },
  keydown(e, view) {
    if (e.key !== 'Escape') return false
    if (view.state.field(hoverField) == null) return false
    pinned = false
    view.dispatch({ effects: setHover.of(null) })
    return true
  },
  mousemove(e, view) {
    const hunks = view.state.field(roundDiffField, false)?.hunks
    if (!hunks?.length) return false
    const pos = view.posAtCoords({ x: e.clientX, y: e.clientY })
    // 前后各放宽一个字符：正好停在改动边界上时也算命中，否则边缘很难悬住
    const hit = pos == null ? null : hunks.find((h) => pos >= h.from - 1 && pos <= h.to + 1)
    const next = hit ? hit.id : null
    if (next != null) {
      cancelClear()
      if (next !== view.state.field(hoverField)) view.dispatch({ effects: setHover.of(next) })
      return false
    }
    if (pinned) return false                       // 钉住了就不跟着鼠标走
    // 离开了改动：**不要立刻关**，给一段够把鼠标挪到工具条上的时间
    if (view.state.field(hoverField) != null && !keepHover) scheduleClear(view)
    return false
  },
  mouseleave(_e, view) {
    // 同样走延迟：CM6 的 tooltip 挂在编辑器 DOM 之外，鼠标从正文挪到工具条上
    // 会先触发这里的 mouseleave，立刻关掉就永远够不到按钮。
    if (!keepHover) scheduleClear(view)
    return false
  },
})

/** 装进编辑器的完整扩展：高亮 + 悬停工具条。 */
export const roundDiff = [roundDiffField, hoverField, hunkTooltip, hoverWatcher]
