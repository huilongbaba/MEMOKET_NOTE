/**
 * 完成标准可检查（P12，docs/agent-native-editor.md §3.1「完成标准是可检查的（每条进展有日期、有依据、≤ 800 字…）」）。
 *
 * 文档意图里的「完成标准」一句话，拆成一条条；**能用代码判的当场判**（零模型、毫秒级，跟骨架的「已写 / 待补」
 * 一个做法），判不了的留给用户打勾。判据 3 说「每一轮的判据要看得见」——这就是这篇的判据，摆在右栏「计划」顶上，
 * 不是藏在 prompt 里的一句 `DONE_HINT`。
 *
 * 能判的几类（都是 P9 预填规则里用户第一天就会写的话）：
 *   字数上限 / 下限          「≤ 800 字」「不超过 800 字」「800 字以内」「至少 300 字」
 *   每条有日期               「每条进展有日期」「有负责人和日期」——以条目（列表项）为单位，没有列表就按段落
 *   有依据 / 出处 / 引用      「每个结论有事实支撑」「数字有出处」「每个论断有依据」——单位里要有 `[id]` 引用或链接
 *   各有一节                 「范围、里程碑、风险各有一节」——这几个词得出现在 `#` 标题里
 *   结论在前                 第一个标题或开头一段里要有「结论 / 总结 / 摘要」
 *   写下来就算完             正文非空就算
 * 其余（「卡住的说清要什么」「争议点两边都写」「写成可执行的条目」）代码判不了，是「要你判」的勾。
 *
 * 只有纯函数；勾过的条目记在 `notes.intent.checked`（后端 `editor/intent.py` 一起收），不另开表。
 */
import { CITATION_RE, NOTE_LINK_TAIL_RE, wordCount } from './wordCount'
import { parseHeadings } from '../components/DocumentOutline'

export type DoneStatus = 'pass' | 'fail' | 'manual'
export type DoneItem = {
  text: string
  status: DoneStatus
  /** 代码判的：为什么过 / 为什么没过（「5 条里 3 条没有日期」）；要你判的：空 */
  why: string
  /** 用户勾过（只对 manual 有意义） */
  checked: boolean
}

/** 「完成标准」一句拆成几条：分号 / 句号 / 换行分开；逗号不拆（「有日期、有依据」是一条里的两件事）。 */
export function splitDone(done: string): string[] {
  return (done || '').split(/[；;。\n]+/).map((s) => s.trim()).filter(Boolean)
}

const DATE_RE = /\d{1,2}\s*[月/.-]\s*\d{1,2}|\d{4}\s*[-/年]\s*\d{1,2}|\d{1,2}\s*月(?:底|初|末|中)?|今天|昨天|前天|明天|本周|上周|下周|周[一二三四五六日天]|星期[一二三四五六日天]|Q[1-4]\b|\d+\s*号/
const LINK_RE = /\[[^\]\n]*\]\([^)\s]+\)|https?:\/\/\S+/
const isFence = (l: string) => /^\s*(`{3,}|~{3,})/.test(l)

/** 「每条」的单位：列表项优先（周报 / 纪要的进展、待办都是列表）；一条列表都没有就按段落（标题、围栏不算）。 */
export function units(content: string): { kind: 'item' | 'paragraph'; texts: string[] } {
  const lines = (content || '').split('\n')
  const items: string[] = []
  const paras: string[] = []
  let fenced = false
  let cur: string[] = []
  const flush = () => { if (cur.length) { paras.push(cur.join('\n')); cur = [] } }
  for (const l of lines) {
    if (isFence(l)) { fenced = !fenced; flush(); continue }
    if (fenced) continue
    if (/^\s*(?:[-*+]|\d+[.)])\s+\S/.test(l)) items.push(l.replace(/^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s*)?/, ''))
    if (!l.trim() || /^#{1,6}\s/.test(l)) { flush(); continue }
    cur.push(l)
  }
  flush()
  if (items.length) return { kind: 'item', texts: items }
  return { kind: 'paragraph', texts: paras.filter((p) => p.replace(/\s/g, '').length >= 20) }
}

const hasCite = (s: string) => { CITATION_RE.lastIndex = 0; NOTE_LINK_TAIL_RE.lastIndex = 0; return CITATION_RE.test(s) || NOTE_LINK_TAIL_RE.test(s) || LINK_RE.test(s) }
const num = (s: string) => Number(s.replace(/[０-９]/g, (c) => String(c.charCodeAt(0) - 0xff10)))

/** 判一条。回 null = 代码判不了（要你判）。 */
export function checkDoneItem(item: string, content: string): { status: 'pass' | 'fail'; why: string } | null {
  const t = item.replace(/\s+/g, '')
  const words = wordCount(content)
  let m: RegExpMatchArray | null
  if ((m = t.match(/(?:≤|<=|不超过|不多于|少于|控制在|最多)(\d+)字/)) || (m = t.match(/(\d+)字(?:以内|以下|之内|内)/))) {
    const n = num(m[1])
    return words <= n ? { status: 'pass', why: `现在 ${words} 字` } : { status: 'fail', why: `现在 ${words} 字，超出 ${words - n} 字` }
  }
  if ((m = t.match(/(?:≥|>=|至少|不少于|不低于|最少)(\d+)字/)) || (m = t.match(/(\d+)字(?:以上|起)/))) {
    const n = num(m[1])
    return words >= n ? { status: 'pass', why: `现在 ${words} 字` } : { status: 'fail', why: `现在 ${words} 字，还差 ${n - words} 字` }
  }
  if (/写下来就算完|写了就算/.test(t)) {
    return words > 0 ? { status: 'pass', why: `写了 ${words} 字` } : { status: 'fail', why: '正文还是空的' }
  }
  if ((m = t.match(/^(.+?)各有一节/)) || (m = t.match(/^(.+?)(?:各|都)?(?:单独)?(?:有|成)一节/))) {
    const names = m[1].split(/[、，,和与及]/).map((s) => s.replace(/^(?:要|需要|得)/, '').trim()).filter((s) => s && s.length <= 8)
    if (names.length) {
      const heads = parseHeadings(content).map((h) => h.text)
      const missing = names.filter((n) => !heads.some((h) => h.includes(n)))
      return missing.length ? { status: 'fail', why: `标题里没有：${missing.join('、')}` } : { status: 'pass', why: `${names.length} 节都有` }
    }
  }
  if (/结论在前|先说结论|结论先行|开头.*结论/.test(t)) {
    const heads = parseHeadings(content)
    const firstHead = heads[0]?.text ?? ''
    const opening = (content || '').split('\n').filter((l) => l.trim() && !/^#{1,6}\s/.test(l)).slice(0, 2).join('\n')
    const ok = /结论|总结|摘要|TL;?DR|一句话/i.test(firstHead) || /结论|总之|一句话|判断是|建议/.test(opening)
    return ok ? { status: 'pass', why: '开头就是结论' } : { status: 'fail', why: '开头没看到「结论」' }
  }
  // 「每条 / 每个 … 有日期」「… 有依据 / 出处 / 引用 / 事实支撑」——两件事可能写在同一条里（「有日期、有依据」），各判各的
  const wantDate = /有日期|有时间|带日期|标日期/.test(t)
  const wantCite = /有依据|有出处|有引用|事实支撑|有来源|有证据|引用或出处|标出处|注明出处/.test(t)
  if (wantDate || wantCite) {
    const u = units(content)
    const unit = u.kind === 'item' ? '条' : '段'
    if (!u.texts.length) return { status: 'fail', why: '正文里还没有条目' }
    // 「数字有出处」：只看含数字的单位
    const scope = /数字|数据/.test(t) && wantCite ? u.texts.filter((s) => /\d/.test(s)) : u.texts
    if (!scope.length) return { status: 'pass', why: '正文里没有数字' }
    const parts: string[] = []
    let fail = false
    if (wantDate) {
      const miss = scope.filter((s) => !DATE_RE.test(s)).length
      if (miss) { fail = true; parts.push(`${scope.length} ${unit}里 ${miss} ${unit}没有日期`) } else parts.push(`${scope.length} ${unit}都有日期`)
    }
    if (wantCite) {
      const miss = scope.filter((s) => !hasCite(s)).length
      if (miss) { fail = true; parts.push(`${scope.length} ${unit}里 ${miss} ${unit}没有出处`) } else parts.push(`${scope.length} ${unit}都有出处`)
    }
    return { status: fail ? 'fail' : 'pass', why: parts.join('；') }
  }
  return null
}

/** 整句「完成标准」→ 逐条状态。`checked` 是用户勾过的条目原文。 */
export function checkDone(done: string, content: string, checked: string[] = []): DoneItem[] {
  return splitDone(done).map((text) => {
    const r = checkDoneItem(text, content)
    if (r) return { text, status: r.status, why: r.why, checked: false }
    return { text, status: 'manual', why: '', checked: checked.includes(text) }
  })
}

/** 角标用：过了几条 / 一共几条（要你判的勾了才算过）。 */
export function doneSummary(items: DoneItem[]): { ok: number; total: number; failing: number } {
  const ok = items.filter((i) => i.status === 'pass' || (i.status === 'manual' && i.checked)).length
  return { ok, total: items.length, failing: items.filter((i) => i.status === 'fail').length }
}
