/**
 * 目录 = 计划（P12，docs/agent-native-editor.md §3.5「目录 = 计划（每个标题带状态和「用了什么材料」）」）。
 *
 * 目录里每一节带一个状态，**全部从正文算出来、零存储**：
 *   空      标题下面一个字都没有（连子节都没有）——待写
 *   草稿    有字、没有一条出处
 *   有依据  有字、且引用了知识库事实（`[id]`）或链到了别的笔记（`note://`）
 * 「用了什么材料」= 这一节里引用的事实条数 + 链到的笔记数。
 *
 * 状态的三个词跟骨架节拍的「已写 / 待补」是同一套色（`.plan-state`）：待补 ≈ 空，已写 ≈ 草稿 / 有依据——
 * 目录（按标题）和骨架（按节拍）看的是同一件事的两个切面，颜色对上，用户不用学两套。
 *
 * `splitBeatLabel` 是后端 `harness/checks/skeleton.py::split_beat_label` 的前端版：同一批状态写法。
 */
import { citedFactIds, linkedNoteIds, wordCount } from './wordCount'

export type SectionState = 'empty' | 'draft' | 'sourced'
export type SectionStatus = {
  pos: number
  state: SectionState
  words: number
  cites: number
  links: number
}
export const SECTION_LABEL: Record<SectionState, string> = { empty: '空', draft: '草稿', sourced: '有依据' }

type Heading = { level: number; text: string; pos: number }

/** 每个标题 → 它到下一个同级或更高级标题之间的正文（子节算进父节：父节自己没字但子节有，父节不算空）。 */
export function sectionStatuses(content: string, headings: Heading[]): SectionStatus[] {
  const out: SectionStatus[] = []
  for (let i = 0; i < headings.length; i++) {
    const h = headings[i]
    let end = content.length
    for (let j = i + 1; j < headings.length; j++) if (headings[j].level <= h.level) { end = headings[j].pos; break }
    // 去掉标题行本身
    const nl = content.indexOf('\n', h.pos)
    const bodyStart = nl === -1 ? content.length : nl + 1
    const body = bodyStart < end ? content.slice(bodyStart, end)
      // 子节的标题行也去掉（只算正文字数）
      .replace(/^#{1,6}\s.*$/gm, '') : ''
    const words = wordCount(body)
    const cites = citedFactIds(body).length
    const links = linkedNoteIds(body).length
    const state: SectionState = words === 0 ? 'empty' : cites + links > 0 ? 'sourced' : 'draft'
    out.push({ pos: h.pos, state, words, cites, links })
  }
  return out
}

export function sectionSummary(s: SectionStatus[]): { empty: number; draft: number; sourced: number } {
  return {
    empty: s.filter((x) => x.state === 'empty').length,
    draft: s.filter((x) => x.state === 'draft').length,
    sourced: s.filter((x) => x.state === 'sourced').length,
  }
}

/** 一节的「用了什么材料」一句：「3 条出处 · 链 1 篇」。 */
export function materialsText(s: SectionStatus): string {
  const parts: string[] = []
  if (s.cites) parts.push(`${s.cites} 条出处`)
  if (s.links) parts.push(`链 ${s.links} 篇`)
  return parts.join(' · ')
}

// 状态标签的各种写法（跟后端 skeleton.py::_STATUS 一致：「已写：」「【已写】」「已写并需继续收紧」「待补」「尚缺」…）。
// 比后端多一道：标签后面得跟标点 / 括号 / 「（正文第」/ 行尾——「已写部分先建立…」（真库 574f 第 2 条）是一句话的开头，不是标签，
// 后端那条把它也算成「已写」，界面上就会出现「已写 部分先建立…」这种被劈开的句子（实拍）。
const BEAT_STATUS = /^\s*[【[（(]?\s*(?:(?<w>已写(?:并需继续收紧|并需收紧|但需收紧)?|已有|已完成)|(?<m>待补充|待补|尚缺|缺失|未写|待写|尚未写|待写入))(?=\s*(?:[】\]）):：,，、—-]|（正文第|$))/
const BEAT_TAIL = /^\s*[】\]）)]?\s*(?:（正文第\s*(\d+)\s*行起）)?\s*[:：,，、—-]*\s*/

export type BeatLabel = { status: 'written' | 'missing' | null; text: string; line: number | null }

/** 「已写（正文第 12 行起）：xxx」→ { written, 'xxx', 12 }；没标的 → { null, 原文, null }。 */
export function splitBeatLabel(beat: string): BeatLabel {
  const m = BEAT_STATUS.exec(beat || '')
  if (!m) return { status: null, text: (beat || '').trim(), line: null }
  const rest = (beat || '').slice(m[0].length)
  const t = BEAT_TAIL.exec(rest)
  const line = t?.[1] ? Number(t[1]) : null
  return { status: m.groups?.w ? 'written' : 'missing', text: rest.slice(t?.[0].length ?? 0).trim(), line }
}
