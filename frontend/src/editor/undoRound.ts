/**
 * 「只撤这一轮」（P16，agent-native-editor §3.2 / 痛点 8）：烧进正文之后，拿第 N 轮「之前 / 之后」两版快照做词级 diff，
 * 把这一轮改的每一处**反向**应用到现在的正文上——留一二轮、丢第三轮。
 *
 * 跟 `roundDiff` 里活着的层不同，这里没有位置可映射（层已经烧掉了）：每一处靠**文字**定位——这处改成的新文字
 * 带前后各 24 字上下文在现在的正文里找，唯一命中才换回原文；上下文被后来改过就缩短再找；多处命中 / 找不到 = 冲突，
 * 说清是哪一处，不猜。纯函数，测试在 `__tests__/p16.test.ts`。
 */
import { diffParts, toHunks } from './roundDiff'

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

export function undoRound(before: string, after: string, current: string): UndoRoundResult {
  const hunks = toHunks(diffParts(before, after))
  let text = current
  let undone = 0
  const conflicts: string[] = []
  // 从后往前：前面那处的上下文不会被自己刚换回去的原文污染
  for (let k = hunks.length - 1; k >= 0; k--) {
    const h = hunks[k]
    const ins = after.slice(h.from, h.to)
    let why = ''
    let done = false
    for (const n of CTX) {
      const pre = after.slice(Math.max(0, h.from - n), h.from)
      const post = after.slice(h.to, h.to + n)
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
    else conflicts.push(`「${snippet(ins || h.del)}」${why}`)
  }
  return { text, undone, total: hunks.length, conflicts: conflicts.reverse() }
}
