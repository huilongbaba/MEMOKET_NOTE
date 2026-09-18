/**
 * ⌥ 悬停来龙去脉卡的内容（P16，agent-native-editor §3.3 / 场景 B；痛点 11 / 12；判据 2「不离开页面就用得上记忆」）。
 *
 * 零模型：词法召回（`/api/memory/recall`）回来的几条按日期排——这个词在知识库里**第一次**出现、**最近一次**、
 * 再挑两条相关的。「查完整来龙去脉」（模型、20 秒）留给卡上的按钮，不自动打。纯函数，测试在 `__tests__/p16.test.ts`。
 */
import type { Fact } from '../api'

export type TraceSummary = { count: number; first: Fact | null; last: Fact | null; related: Fact[] }

const dated = (f: Fact) => /^\d{4}/.test(f.when || '')

export function summarizeTrace(facts: Fact[]): TraceSummary {
  const withDate = facts.filter(dated).sort((a, b) => (a.when < b.when ? -1 : a.when > b.when ? 1 : 0))
  const first = withDate[0] ?? null
  const lastCand = withDate[withDate.length - 1] ?? null
  const last = lastCand && first && lastCand.id !== first.id ? lastCand : null
  const used = new Set([first?.id, last?.id].filter(Boolean))
  const related = facts.filter((f) => !used.has(f.id)).slice(0, 2)
  return { count: facts.length, first, last, related }
}

/** 分词器不认识的词（「众筹」被切成 众 | 筹）：编辑器把相邻单字连成一串（「众筹等」）+ 鼠标停的那个字交过来。
 *  中文词绝大多数是两个字：先拿**盖住那个字的两字窗口**（左、右）各查一次知识库，谁有记录用谁（都有取多的）；
 *  都没有再查整串。实测 `/recall` 回的 `terms` 靠不住——「众筹」和「筹等」两个 gram 都在库里时它合成「众筹等」。 */
export function candidates(run: string, focus: number): string[] {
  const out: string[] = []
  if (run.length >= 2) {
    if (focus >= 1) out.push(run.slice(focus - 1, focus + 1))
    if (focus + 2 <= run.length) out.push(run.slice(focus, focus + 2))
  }
  if (!out.includes(run)) out.push(run)
  return out
}

/** 没结果时卡上说的那句——不留空白（P4 #6 同一条规矩：空着要说清为什么）。 */
export function emptyReason(phrase: string, why?: '' | 'no_terms' | 'weak', kbEmpty?: boolean): string {
  if (kbEmpty) return '知识库还是空的——先把笔记或会议记录存进去。'
  if (why === 'no_terms') return `「${phrase}」太短或太泛，查不了。`
  return `知识库里没有「${phrase}」。`
}
