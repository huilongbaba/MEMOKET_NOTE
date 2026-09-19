/**
 * 「只撤这一轮」（P16，agent-native-editor §3.2 / 痛点 8）：烧进正文之后，拿第 N 轮「之前 / 之后」两版快照做词级 diff，
 * 把这一轮改的每一处**反向**应用到现在的正文上——留一二轮、丢第三轮。
 *
 * 跟 `roundDiff` 里活着的层不同，这里没有位置可映射（层已经烧掉了）：每一处靠**文字**定位——这处改成的新文字
 * 带前后各 24 字上下文在现在的正文里找，唯一命中才换回原文；上下文被后来改过就缩短再找；多处命中 / 找不到 = 冲突，
 * 说清是哪一处，不猜。
 *
 * P18 #3：**后一轮改过第 N 轮的句子**原来只能报冲突（P16 下一步①）。现在把第 N 轮之后每一轮的快照
 * （`later` = 第 N+1 轮之后、…、收尾）接成一条链，第 N 轮那一处的位置沿链逐轮**映射**过去（`mapPos`）：
 * 后一轮改了它的几个字，映射到的就是改过之后的那段，撤第 N 轮 = 把那段换回第 N 轮之前的原文（后一轮对它的
 * 修改是对第 N 轮文字的修改，跟着一起走）；后一轮把它整个删了、而第 N 轮之前那儿还有原文——原文要不要回来说不准，
 * 仍报冲突。映射用的 diff 按段落对齐（`paragraphDiff`，理由见它的注释），映射完再拿现在的正文（用户可能又改过）
 * 按文字定位，规矩同上。纯函数，测试在 `__tests__/p16.test.ts` / `p18.test.ts`。
 */
import { diffParts, toHunks, type DiffPart } from './roundDiff'

export type UndoRoundResult = {
  text: string
  /** 撤回了几处 */
  undone: number
  /** 这一轮一共几处 */
  total: number
  /** 没能撤的：哪一处、为什么 */
  conflicts: string[]
}

const CTX = [24, 12, 6, 0]

/** 唯一命中的位置；-1 = 没有，-2 = 不止一处 */
function findUnique(hay: string, needle: string): number {
  const at = hay.indexOf(needle)
  if (at < 0) return -1
  return hay.indexOf(needle, at + 1) >= 0 ? -2 : at
}

const snippet = (s: string) => { const t = s.replace(/\s+/g, ' ').trim(); return t.length > 24 ? t.slice(0, 24) + '…' : t }

/** 冲突那句话的开头：有原文就引原文，没有就说清是第几处。
 *
 * **不能直接 `「${snippet(x)}」`**（P31 #4）：`snippet` 会把空白折掉再 `trim`，所以
 * 纯空行 / 纯换行的那一处引出来是空字符串，用户读到的是「**「」**在现在的正文里出现了
 * 不止一处，不知道撤哪一处」——一对空引号，看着像程序出错。实拍：第 2 轮已经撤过一次，
 * 再点一次「只撤这一轮」，剩下的三处全是段落间的空行。 */
export const conflictLead = (s: string, k: number) => { const t = snippet(s); return t ? `「${t}」` : `第 ${k} 处（只有空行、没有可引的原文）` }

/** 两段文字像不像：字符 2-gram 的 Dice 系数（0–1）。配对「改过的段落」用。 */
export function similarity(a: string, b: string): number {
  if (a === b) return 1
  if (a.length < 2 || b.length < 2) return 0
  const grams = (s: string) => { const m = new Map<string, number>(); for (let i = 0; i + 1 < s.length; i++) { const g = s.slice(i, i + 2); m.set(g, (m.get(g) ?? 0) + 1) } return m }
  const ga = grams(a); const gb = grams(b)
  let hit = 0
  for (const [g, n] of ga) hit += Math.min(n, gb.get(g) ?? 0)
  return (2 * hit) / (a.length - 1 + b.length - 1)
}

/** 配对时两段至少要像到这个程度；再低就当成一段删了、另一段新写的 */
const PAIR_MIN = 0.4

/**
 * 按**段落**对齐的 diff（给映射用）。`diffParts` 是逐字的、先掐公共前后缀——两版正文尾巴上都是「。」时，
 * 它会把第 N 轮那句的句号跟后一轮新写的最后一句的句号对上，于是「第 N 轮那句」的终点被映射到全文末尾，
 * 后一轮新写的整段都被当成第 N 轮的（实拍：撤第 1 轮把第 2 轮那段也撤了）。
 * 这里先把两版切成段落（`\n\n` 分隔，分隔符也是一个单元）做 LCS：没动的段照抄、改过的段按相似度配对后再逐字比、
 * 配不上的整段算删 / 增。产出跟 `diffParts` 同一个形状，`mapPos` 照用。
 */
export function paragraphDiff(a: string, b: string): DiffPart[] {
  const split = (s: string) => s.split(/(\n{2,})/).filter((t) => t.length > 0)
  const ta = split(a); const tb = split(b)
  // LCS on paragraph tokens
  const n = ta.length; const m = tb.length
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = ta[i] === tb[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
  const out: DiffPart[] = []
  const push = (type: DiffPart['type'], text: string) => {
    if (!text) return
    const last = out[out.length - 1]
    if (last && last.type === type) last.text += text
    else out.push({ type, text })
  }
  const flush = (dels: string[], inss: string[]) => {
    // 改过的段按相似度配对（保持顺序），配上的逐字比，其余整段删 / 增
    let j = 0
    for (const d of dels) {
      let best = -1; let bestSim = PAIR_MIN
      for (let k = j; k < inss.length; k++) { const s = similarity(d, inss[k]); if (s > bestSim) { best = k; bestSim = s } }
      if (best < 0) { push('del', d); continue }
      for (let k = j; k < best; k++) push('ins', inss[k])
      for (const p of diffParts(d, inss[best])) push(p.type, p.text)
      j = best + 1
    }
    for (let k = j; k < inss.length; k++) push('ins', inss[k])
  }
  let i = 0; let j = 0
  let dels: string[] = []; let inss: string[] = []
  while (i < n || j < m) {
    if (i < n && j < m && ta[i] === tb[j]) {
      flush(dels, inss); dels = []; inss = []
      push('keep', ta[i]); i++; j++
    } else if (j < m && (i >= n || dp[i][j + 1] >= dp[i + 1][j])) {
      inss.push(tb[j]); j++
    } else {
      dels.push(ta[i]); i++
    }
  }
  flush(dels, inss)
  return out
}

/**
 * a 里的位置 → b 里的位置（按 `paragraphDiff(a, b)` / `diffParts(a, b)` 的 parts）。落在 b 里删掉的那段上就贴到它左边（塌缩）。
 * `bias`：'start' 是一段的起点——正好停在插入点上时算在插入之后（后一轮在它前面插的字不属于它）；
 * 'end' 是一段的终点——停在插入点上时算在插入之前（后一轮在它后面接的字也不属于它）。
 */
export function mapPos(parts: DiffPart[], pos: number, bias: 'start' | 'end'): number {
  let a = 0
  let b = 0
  for (const p of parts) {
    const n = p.text.length
    if (p.type === 'keep') {
      if (pos < a + n || (bias === 'end' && pos === a + n)) return b + (pos - a)
      a += n; b += n
    } else if (p.type === 'del') {
      if (pos < a + n) return b
      a += n
    } else {
      b += n
    }
  }
  return b
}

/**
 * @param before  第 N 轮之前的正文
 * @param after   第 N 轮之后的正文（= 第 N+1 轮之前）
 * @param current 现在的正文
 * @param later   第 N 轮之后每一轮的快照，按时间正序（第 N+1 轮之后、…、收尾）；没有就只靠文字定位
 */
export function undoRound(before: string, after: string, current: string, later: string[] = []): UndoRoundResult {
  const hunks = toHunks(diffParts(before, after))
  // 后几轮的 diff 链：每一段是 (上一版 → 这一版) 的 parts
  const chain: DiffPart[][] = []
  let prev = after
  for (const snap of later) {
    chain.push(paragraphDiff(prev, snap))
    prev = snap
  }
  const latest = prev
  let text = current
  let undone = 0
  const conflicts: string[] = []
  // 从后往前：前面那处的上下文不会被自己刚换回去的原文污染
  for (let k = hunks.length - 1; k >= 0; k--) {
    const h = hunks[k]
    const ins0 = after.slice(h.from, h.to)
    // 第 N 轮的这一处沿后几轮映射到最后一版里的位置
    let from = h.from
    let to = h.to
    for (const parts of chain) {
      from = mapPos(parts, from, 'start')
      to = Math.max(from, mapPos(parts, to, 'end'))
    }
    const ins = latest.slice(from, to)
    if (ins0 && !ins && h.del) {
      conflicts.push(`${conflictLead(ins0, k + 1)}后一轮把它整个删掉了，原文要不要回来说不准`)
      continue
    }
    let why = ''
    let done = false
    for (const n of CTX) {
      const pre = latest.slice(Math.max(0, from - n), from)
      const post = latest.slice(to, to + n)
      const needle = pre + ins + post
      if (!needle) { why = '原来的位置找不到了（前后文都改过）'; break }
      const at = findUnique(text, needle)
      if (at === -2) { why = ins ? '在现在的正文里出现了不止一处，不知道撤哪一处' : '原来的位置不止一处，不知道补在哪'; break }
      if (at < 0) { why = ins ? '在现在的正文里找不到了（后来改过）' : '原来的位置找不到了（前后文改过）'; continue }
      text = text.slice(0, at + pre.length) + h.del + text.slice(at + pre.length + ins.length)
      done = true
      break
    }
    if (done) undone++
    else conflicts.push(`${conflictLead(ins0 || h.del, k + 1)}${why}`)
  }
  return { text, undone, total: hunks.length, conflicts: conflicts.reverse() }
}
