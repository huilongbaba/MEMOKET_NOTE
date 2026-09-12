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

  // 中间段太大时逐词 LCS 会卡住 UI（8000 字 ≈ 8000×8000 的表）。先按**行**对齐，
  // 只在真正变了的行对里再逐词比——格式化这种「每行补几个空格」的改动，之前会
  // 退化成整篇删+增，满屏绿；现在只有变了的词标出来。
  if (am.length * bm.length > 400_000) {
    diffByLines(am.join(''), bm.join(''), push)
  } else {
    lcs(am, bm, push)
  }

  push('keep', a.slice(a.length - tail).join(''))
  // 只差空白的增删（格式化补的空格 / 空行）不标绿——但**不能在这里把它改成 keep**：
  // 一个 del " " 变成 keep 之后，后面所有位置都按「这个空格还在」算，整串 hunk 错位一格，
  // 撤回还原出来的是错的（check-hunks 随机 2000 例里 15% 还原失败，有的丢字）。
  // 类型保持精确，「不标绿」放到 toHunks 的 soft 标记上，装饰层跳过它即可。
  const merged: DiffPart[] = []
  for (const part of out) {
    const last = merged[merged.length - 1]
    if (last && last.type === part.type) last.text += part.text
    else merged.push({ type: part.type, text: part.text })
  }
  return merged
}



type Push = (type: DiffPart['type'], text: string) => void

/** 标准 LCS 逐 token 对比。调用方保证 a.length * b.length 在可算的范围内。 */
function lcs(am: string[], bm: string[], push: Push) {
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

/** 先按行对齐，变了的行对（一删一增等量成对）再逐词比。
 *
 * 行数一多（1500 行 × 1500 行 = 225 万格）之前直接放弃成「整段删 + 整段增」——实拍 47k 字
 * 的长文格式化后满屏绿。现在先拿**两边都只出现一次的行**当锚点（patience diff 的思路：
 * 锚点用最长递增子序列对齐，O(k log k)），锚点之间的小块再走 LCS；块还是太大且行数相等
 * 就逐行配对；实在不行才整块删增。 */
function diffByLines(before: string, after: string, push: Push) {
  const al = before.split('\n').map((l, i, arr) => (i < arr.length - 1 ? l + '\n' : l))
  const bl = after.split('\n').map((l, i, arr) => (i < arr.length - 1 ? l + '\n' : l))
  diffLineRange(al, 0, al.length, bl, 0, bl.length, push)
}

const LINE_LCS_CELLS = 400_000

function diffLineRange(al: string[], a0: number, a1: number, bl: string[], b0: number, b1: number, push: Push) {
  const n = a1 - a0
  const m = b1 - b0
  if (n === 0 && m === 0) return
  if (n * m <= LINE_LCS_CELLS) {
    const ops: DiffPart[] = []
    lcs(al.slice(a0, a1), bl.slice(b0, b1), (type, text) => ops.push({ type, text }))
    pairLineOps(ops, push)
    return
  }
  // 锚点：这一段里两边都恰好出现一次的行
  const ca = new Map<string, number>()
  const cb = new Map<string, number>()
  for (let i = a0; i < a1; i++) ca.set(al[i], (ca.get(al[i]) ?? 0) + 1)
  for (let j = b0; j < b1; j++) cb.set(bl[j], (cb.get(bl[j]) ?? 0) + 1)
  const posB = new Map<string, number>()
  for (let j = b0; j < b1; j++) if (cb.get(bl[j]) === 1 && ca.get(bl[j]) === 1) posB.set(bl[j], j)
  const cand: { ia: number; ib: number }[] = []
  for (let i = a0; i < a1; i++) { const ib = posB.get(al[i]); if (ib !== undefined && ca.get(al[i]) === 1) cand.push({ ia: i, ib }) }
  const anchors = longestIncreasing(cand)
  if (anchors.length === 0) {
    if (n === m) {                                  // 行数一样：逐行配对逐词比
      for (let r = 0; r < n; r++) pairLineOps([{ type: 'del', text: al[a0 + r] }, { type: 'ins', text: bl[b0 + r] }], push)
    } else {
      push('del', al.slice(a0, a1).join('')); push('ins', bl.slice(b0, b1).join(''))
    }
    return
  }
  let pa = a0
  let pb = b0
  for (const { ia, ib } of anchors) {
    diffLineRange(al, pa, ia, bl, pb, ib, push)
    push('keep', al[ia])
    pa = ia + 1; pb = ib + 1
  }
  diffLineRange(al, pa, a1, bl, pb, b1, push)
}

/** 候选按 ia 递增给进来，取 ib 也递增的最长子序列（标准 LIS，O(k log k)）。 */
function longestIncreasing(cand: { ia: number; ib: number }[]): { ia: number; ib: number }[] {
  const tails: number[] = []          // tails[len-1] = 长度为 len 的递增序列里最小的末尾 ib 所在下标
  const prev = new Array<number>(cand.length).fill(-1)
  for (let k = 0; k < cand.length; k++) {
    let lo = 0
    let hi = tails.length
    while (lo < hi) { const mid = (lo + hi) >> 1; if (cand[tails[mid]].ib < cand[k].ib) lo = mid + 1; else hi = mid }
    if (lo > 0) prev[k] = tails[lo - 1]
    tails[lo] = k
  }
  const out: { ia: number; ib: number }[] = []
  for (let k = tails.length ? tails[tails.length - 1] : -1; k >= 0; k = prev[k]) out.push(cand[k])
  return out.reverse()
}

/** 把「连续的 del 行」和紧跟的「连续的 ins 行」配对：数量相等就逐行逐词比 */
function pairLineOps(ops: DiffPart[], push: Push) {
  let k = 0
  while (k < ops.length) {
    if (ops[k].type !== 'del') { push(ops[k].type, ops[k].text); k++; continue }
    const dels: string[] = []
    while (k < ops.length && ops[k].type === 'del') dels.push(ops[k++].text)
    const inss: string[] = []
    while (k < ops.length && ops[k].type === 'ins') inss.push(ops[k++].text)
    if (dels.length === inss.length) {
      for (let r = 0; r < dels.length; r++) {
        const sa = segment(dels[r])
        const sb = segment(inss[r])
        if (sa.length * sb.length > LINE_LCS_CELLS) { push('del', dels[r]); push('ins', inss[r]) }
        else lcs(sa, sb, push)
      }
    } else {
      for (const d of dels) push('del', d)
      for (const x of inss) push('ins', x)
    }
  }
}

// ---------------------------------------------------------------- hunk 模型

/** 一处改动。``from``/``to`` 是**文档里的活位置**：每次文档变动都跟着映射，
 * 所以用户可以在绿色新增里改字、改完再接受。``del`` 是被删掉的原文
 * （它已经不在文档里，只能靠 widget 补出来；撤回时写回去的也是它）。 */
export type Hunk = {
  id: number; from: number; to: number; del: string
  /** 只差空白（格式化补的空格 / 空行）：位置照记、撤回照还原，但不画绿、不给悬停条。 */
  soft?: boolean
  /** 属于哪一层提案（见 Layer）。toHunks 给 0，进 field 时按当前层改写。 */
  layer?: number
}

/** 提案层：一次 AI 动作产生的一批改动（润色 ①、格式化、第 3 轮…）。层可以整层接受 /
 *  撤回——痛点 8「保留第一次改的、放弃第三次改的」就是按层操作（agent-native-editor §3.2）。 */
export type Layer = { id: number; label: string; at: number }

/** 上层往编辑器塞一层新提案用的值：seq 变了才 dispatch（React 的 prop 比较）。
 *  replace = 先清掉已有的层再加（智能续写每轮都拿整次 run 的起点重算，是累积的，不能叠层）。 */
export type DiffPush = { label: string; parts: DiffPart[]; seq: number; replace?: boolean }

/** 相邻两处改动之间没动过的文字不超过这么多字，就并成一处。
 * 8 个字大约是「改了一个词、隔几个字又改一个词」的距离——再大就会
 * 把两件不相干的修改捆在一起，用户想只接受其中一处都做不到。 */
const MERGE_GAP = 8

/** 老接口：清掉所有层，用这批 diff 建一层「改动」。 */
export const setRoundDiff = StateEffect.define<DiffPart[] | null>()
/** 加一层提案（不动已有的层；已有层的位置由这次事务之前的文档改动映射过了）。 */
export const addLayer = StateEffect.define<{ label: string; parts: DiffPart[]; replace?: boolean }>()
/** 整层接受：这层的 hunk 全摘掉，正文保持现状。整层撤回由调用方逐处 dispatch 改动 + dropHunk。 */
export const acceptLayer = StateEffect.define<number>()
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
      prev.soft = !!(prev.soft && h.soft)
    } else {
      out.push({ id: id++, ...h })
    }
    gap = ''
  }
  const soft = (del: string, ins: string) => !del.trim() && !ins.trim()
  for (let i = 0; i < parts.length; i++) {
    const p = parts[i]
    if (p.type === 'keep') { pos += p.text.length; gap += p.text; continue }
    if (p.type === 'del') {
      const next = parts[i + 1]
      if (next?.type === 'ins') {                 // 替换：合成一处
        push({ from: pos, to: pos + next.text.length, del: p.text, soft: soft(p.text, next.text) })
        pos += next.text.length
        i++
      } else {
        push({ from: pos, to: pos, del: p.text, soft: soft(p.text, '') })
      }
      continue
    }
    push({ from: pos, to: pos + p.text.length, del: '', soft: soft('', p.text) })
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
    // 删得多（整段大纲被重写）就折成一个小标签，悬停看原文；把几百字划线原文
    // 塞回正文里，读者看到的是一坨红字，分不清什么是现在的正文（实拍：跑了
    // 六轮之后正文底部堆着整份被删掉的旧大纲）。
    const t = this.text.replace(/\s+/g, ' ').trim()
    if (t.length > 40) {
      span.classList.add('harness-del-pill')
      span.textContent = `已删 ${t.length} 字`
      span.title = '这一轮删掉的内容：\n' + this.text.slice(0, 600) + (this.text.length > 600 ? '…' : '')
    } else {
      span.textContent = t
      span.title = '这一轮删掉的内容'
    }
    return span
  }
  ignoreEvent() { return true }
}

function build(hunks: Hunk[], layers: Layer[] = []): DecorationSet {
  const decos: Range<Decoration>[] = []
  const label = (h: Hunk) => layers.find((l) => l.id === h.layer)?.label ?? '这一轮'
  for (const h of hunks) {
    if (h.soft) continue                          // 只差空白：不画
    if (h.del) {
      decos.push(Decoration.widget({ widget: new DeletedWidget(h.del, h.id), side: -1 })
        .range(h.from))
    }
    if (h.to > h.from) {
      decos.push(Decoration.mark({
        class: 'harness-ins',
        attributes: { title: `${label(h)} · 新增的内容` },
      }).range(h.from, h.to))
    }
  }
  return Decoration.set(decos, true)
}

let nextHunkId = 1
let nextLayerId = 1

/** 把一批 diff 建成带层号的 hunk：位置夹到文档长度内（diff 是拿 liveContentRef 算的，
 *  编辑器可能还没跟上——越界的位置下一次 mapPos 直接抛 RangeError，整棵 React 树被卸掉，
 *  用户看到一片白），id 用全局计数（几层的 hunk 混在一起，不能各自从 0 起）。 */
function hunksForLayer(parts: DiffPart[] | null, layer: number, docLen: number): Hunk[] {
  return toHunks(parts)
    .map((h) => ({ ...h, id: nextHunkId++, layer, from: Math.min(h.from, docLen), to: Math.min(h.to, docLen) }))
    .filter((h) => h.to > h.from || h.del)
}

// ---------------------------------------------------------------- state

export const roundDiffField = StateField.define<{ hunks: Hunk[]; layers: Layer[]; decos: DecorationSet }>({
  create() { return { hunks: [], layers: [], decos: Decoration.none } },
  update(value, tr) {
    for (const e of tr.effects) {
      if (e.is(setRoundDiff)) {
        const layer: Layer = { id: nextLayerId++, label: '改动', at: Date.now() }
        const hunks = hunksForLayer(e.value, layer.id, tr.newDoc.length)
        return { hunks, layers: hunks.length ? [layer] : [], decos: build(hunks, [layer]) }
      }
      if (e.is(acceptAllHunks)) return { hunks: [], layers: [], decos: Decoration.none }
    }
    let hunks = value.hunks
    let layers = value.layers
    for (const e of tr.effects) {
      if (e.is(acceptHunk) || e.is(dropHunk)) hunks = hunks.filter((h) => h.id !== e.value)
      if (e.is(acceptLayer)) hunks = hunks.filter((h) => h.layer !== e.value)
    }
    if (tr.docChanged && hunks.length) {
      // **跟着文档改动映射，而不是把高亮丢掉。** 用户在绿色新增里打字时这一处
      // 要跟着变长，所以两端的 assoc 都取 1：
      //   from=1 → 正好插在起点的字排在这处**外面**（在改动前面打字不算改动）
      //   to  =1 → 正好插在终点的字排在这处**里面**（在末尾续写算这处的一部分）
      // 第一版 to 取了 -1，注释写的是"让插入落在区间内部"，代码是反的——
      // 在绿色新增末尾补一个字，那个字会被排除出去，改完再接受就接受不全。
      // 同一个道理：位置超过改动前文档长度的 hunk，mapPos 会抛。先夹到旧文档长度。
      const oldLen = tr.startState.doc.length
      hunks = hunks
        .map((h) => ({
          ...h,
          from: tr.changes.mapPos(Math.min(h.from, oldLen), 1),
          to: tr.changes.mapPos(Math.min(h.to, oldLen), 1),
        }))
        // 新增被用户整段删光、且没有原文可撤回 —— 这处已经不存在了
        .filter((h) => h.to >= h.from && (h.to > h.from || h.del))
    }
    // 加层：放在文档映射之后——新层的位置是针对这次事务之后的文档算的，旧层刚映射过，
    // 两边坐标一致。replace = 智能续写那种累积 diff，先清掉再加。
    for (const e of tr.effects) {
      if (e.is(addLayer)) {
        if (e.value.replace) { hunks = []; layers = [] }
        const layer: Layer = { id: nextLayerId++, label: e.value.label, at: Date.now() }
        const fresh = hunksForLayer(e.value.parts, layer.id, tr.newDoc.length)
        if (fresh.length) { hunks = [...hunks, ...fresh]; layers = [...layers, layer] }
      }
    }
    // 一处都不剩的层收掉
    const live = new Set(hunks.map((h) => h.layer))
    if (layers.some((l) => !live.has(l.id))) layers = layers.filter((l) => live.has(l.id))
    if (hunks === value.hunks && layers === value.layers) return value
    return { hunks, layers, decos: build(hunks, layers) }
  },
  provide: (f) => EditorView.decorations.from(f, (v) => v.decos),
})

/** 还剩几处没处置。给上层显示「本轮 N 处改动」用。 */
export function pendingHunks(view: EditorView): number {
  return view.state.field(roundDiffField, false)?.hunks.filter((h) => !h.soft).length ?? 0
}

/** 各层及每层还剩几处（不算只差空白的）。右栏「改动」标签用。 */
export function layersOf(view: EditorView): (Layer & { count: number })[] {
  const st = view.state.field(roundDiffField, false)
  if (!st) return []
  return st.layers.map((l) => ({ ...l, count: st.hunks.filter((h) => h.layer === l.id && !h.soft).length }))
}

/** 整层撤回：把这层的每一处都还原（从后往前，位置才不会错位）。 */
export function dropLayer(view: EditorView, layerId: number) {
  const st = view.state.field(roundDiffField, false)
  if (!st) return
  const hunks = st.hunks.filter((h) => h.layer === layerId).sort((a, b) => b.from - a.from)
  for (const h of hunks) {
    const cur = view.state.field(roundDiffField).hunks.find((x) => x.id === h.id)
    if (!cur) continue
    view.dispatch({ changes: { from: cur.from, to: cur.to, insert: cur.del }, effects: dropHunk.of(h.id) })
  }
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
    if (tr.effects.some((e) => e.is(setRoundDiff) || e.is(acceptAllHunks) || e.is(acceptLayer))) return null
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
    const hit = pos == null ? null : hunks.find((h) => !h.soft && pos >= h.from - 1 && pos <= h.to + 1)
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
    const hit = pos == null ? null : hunks.find((h) => !h.soft && pos >= h.from - 1 && pos <= h.to + 1)
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
