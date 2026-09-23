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
 * 其余（「每个阻塞项写清影响、所需支持和下一步」「争议点两边都写」「写成可执行的条目」）代码判不了，
 * AI 写作时会参考，但完成后要由用户确认。
 *
 * **跟后端 `harness/checks/done.py` 是同一份判定**（P13 #1）：智能续写跑的时候后端拿同一套规则判这一轮，命中走
 * `check_hit` 进下一轮的 steer。前端不能 import 后端，所以两边各一份——`DONE_RULES` / `DONE_WHY` 里每一条字面
 * 跟那边一字不差（`backend/tests/test_p13.py` 逐句核对），`shared/done-cases.json` 一张用例表两边各跑一遍。
 * 改这里的任何一条正则或措辞，必须同时改那边。
 *
 * 只有纯函数；勾过的条目记在 `notes.intent.checked`（后端 `editor/intent.py` 一起收），不另开表。
 */
import { wordCount } from './wordCount'
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

/** 规则正则的唯一源（`String.raw`，跟后端 `checks/done.py::RULES` 逐条一字不差）。 */
export const DONE_RULES = {
  max: String.raw`(?:≤|<=|不超过|不多于|少于|控制在|最多)(\d+)字`,
  max2: String.raw`(\d+)字(?:以内|以下|之内|内)`,
  min: String.raw`(?:≥|>=|至少|不少于|不低于|最少)(\d+)字`,
  min2: String.raw`(\d+)字(?:以上|起)`,
  nonempty: String.raw`写下来就算完|写了就算`,
  sections: String.raw`^(.+?)各有一节`,
  sections2: String.raw`^(.+?)(?:各|都)?(?:单独)?(?:有|成)一节`,
  section_split: String.raw`[、，,和与及]`,
  section_lead: String.raw`^(?:要|需要|得)`,
  conclusion: String.raw`结论在前|先说结论|结论先行|开头.*结论`,
  conclusion_head: String.raw`结论|总结|摘要|TL;?DR|一句话`,
  conclusion_open: String.raw`结论|总之|一句话|判断是|建议`,
  date_want: String.raw`有日期|有时间|带日期|标日期`,
  cite_want: String.raw`有依据|有出处|有引用|事实支撑|有来源|有证据|引用或出处|标出处|注明出处`,
  numeric_only: String.raw`数字|数据`,
  date: String.raw`\d{1,2}\s*[月/.-]\s*\d{1,2}|\d{4}\s*[-/年]\s*\d{1,2}|\d{1,2}\s*月(?:底|初|末|中)?|今天|昨天|前天|明天|本周|上周|下周|周[一二三四五六日天]|星期[一二三四五六日天]|Q[1-4]\b|\d+\s*号`,
  link: String.raw`\[[^\]\n]*\]\([^)\s]+\)|https?://\S+`,
  cite: String.raw`\[([A-Za-z][A-Za-z0-9_-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+)\]`,
  note_link: String.raw`\]\(note://([0-9a-f]{12})\)`,
  item: String.raw`^\s*(?:[-*+]|\d+[.)])\s+\S`,
  item_strip: String.raw`^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s*)?`,
  fence: String.raw`^\s*(\x60{3,}|~{3,})`,
  split: String.raw`[；;。\n]+`,
} as const
/** 「为什么」的措辞——跟后端 `checks/done.py::WHY` 一字不差（`{x}` 是占位）。 */
export const DONE_WHY = {
  max_ok: '现在 {words} 字',
  max_over: '现在 {words} 字，超出 {over} 字',
  min_ok: '现在 {words} 字',
  min_short: '现在 {words} 字，还差 {short} 字',
  nonempty_ok: '写了 {words} 字',
  nonempty_no: '正文还是空的',
  sections_missing: '标题里没有：{missing}',
  sections_ok: '{n} 节都有',
  conclusion_ok: '开头就是结论',
  conclusion_no: '开头没看到「结论」',
  no_units: '正文里还没有条目',
  no_numbers: '正文里没有数字',
  date_miss: '{n} {unit}里 {miss} {unit}没有日期',
  date_ok: '{n} {unit}都有日期',
  cite_miss: '{n} {unit}里 {miss} {unit}没有出处',
  cite_ok: '{n} {unit}都有出处',
} as const
const fmt = (tpl: string, v: Record<string, string | number>) => tpl.replace(/\{(\w+)\}/g, (_, k) => String(v[k]))
const R = Object.fromEntries(Object.entries(DONE_RULES).map(([k, v]) => [k, new RegExp(v)])) as Record<keyof typeof DONE_RULES, RegExp>
const HEAD_I = new RegExp(DONE_RULES.conclusion_head, 'i')
const HEADING = /^#{1,6}\s/
/** 没有列表时按段落，短于这个字数的段不算「一条」 */
export const PARA_MIN = 20

/** 「完成标准」一句拆成几条：分号 / 句号 / 换行分开；逗号不拆（「有日期、有依据」是一条里的两件事）。 */
export function splitDone(done: string): string[] {
  return (done || '').split(R.split).map((s) => s.trim()).filter(Boolean)
}

/** 「每条」的单位：列表项优先（周报 / 纪要的进展、待办都是列表）；一条列表都没有就按段落（标题、围栏不算）。
 *
 *  **紧跟在一条列表项后面的段落算给那一条**（P13 #2 / P12 下一步①）：周会那种「要点列表 + 带出处的展开段」
 *  （shot-demo「4 月 10 日产品周会」）第一版被判「7 条里 7 条没有出处」，出处全在列表下面的展开段里。
 *  空行隔开也算「紧跟」；下一条列表项 / 标题一出现就断。 */
export function units(content: string): { kind: 'item' | 'paragraph'; texts: string[] } {
  const lines = (content || '').split('\n')
  const items: string[] = []
  const paras: string[] = []
  let fenced = false
  let cur: string[] = []
  let lastItem = -1
  const flush = () => { if (cur.length) { paras.push(cur.join('\n')); cur = [] } }
  for (const l of lines) {
    if (R.fence.test(l)) { fenced = !fenced; flush(); continue }
    if (fenced) continue
    const isHead = HEADING.test(l)
    if (!l.trim() || isHead) { flush(); if (isHead) lastItem = -1; continue }
    if (R.item.test(l)) { items.push(l.replace(R.item_strip, '')); lastItem = items.length - 1 }
    else if (lastItem >= 0) items[lastItem] += '\n' + l
    cur.push(l)
  }
  flush()
  if (items.length) return { kind: 'item', texts: items }
  return { kind: 'paragraph', texts: paras.filter((p) => p.replace(/\s/g, '').length >= PARA_MIN) }
}

const hasCite = (s: string) => R.cite.test(s) || R.note_link.test(s) || R.link.test(s)
const halfwidth = (s: string) => s.replace(/[０-９]/g, (c) => String(c.charCodeAt(0) - 0xff10))
const opening = (content: string) => (content || '').split('\n').filter((l) => l.trim() && !HEADING.test(l)).slice(0, 2).join('\n')

/** 判一条。回 null = 代码判不了（要你判）。 */
export function checkDoneItem(item: string, content: string): { status: 'pass' | 'fail'; why: string } | null {
  const t = halfwidth((item || '').replace(/\s+/g, ''))
  const words = wordCount(content)
  let m: RegExpMatchArray | null
  if ((m = t.match(R.max)) || (m = t.match(R.max2))) {
    const n = Number(m[1])
    return words <= n ? { status: 'pass', why: fmt(DONE_WHY.max_ok, { words }) } : { status: 'fail', why: fmt(DONE_WHY.max_over, { words, over: words - n }) }
  }
  if ((m = t.match(R.min)) || (m = t.match(R.min2))) {
    const n = Number(m[1])
    return words >= n ? { status: 'pass', why: fmt(DONE_WHY.min_ok, { words }) } : { status: 'fail', why: fmt(DONE_WHY.min_short, { words, short: n - words }) }
  }
  if (R.nonempty.test(t)) {
    return words > 0 ? { status: 'pass', why: fmt(DONE_WHY.nonempty_ok, { words }) } : { status: 'fail', why: DONE_WHY.nonempty_no }
  }
  if ((m = t.match(R.sections)) || (m = t.match(R.sections2))) {
    const names = m[1].split(R.section_split).map((s) => s.replace(R.section_lead, '').trim()).filter((s) => s && s.length <= 8)
    if (names.length) {
      const heads = parseHeadings(content).map((h) => h.text)
      const missing = names.filter((n) => !heads.some((h) => h.includes(n)))
      return missing.length ? { status: 'fail', why: fmt(DONE_WHY.sections_missing, { missing: missing.join('、') }) } : { status: 'pass', why: fmt(DONE_WHY.sections_ok, { n: names.length }) }
    }
  }
  if (R.conclusion.test(t)) {
    const heads = parseHeadings(content)
    const firstHead = heads[0]?.text ?? ''
    const ok = HEAD_I.test(firstHead) || R.conclusion_open.test(opening(content))
    return ok ? { status: 'pass', why: DONE_WHY.conclusion_ok } : { status: 'fail', why: DONE_WHY.conclusion_no }
  }
  // 「每条 / 每个 … 有日期」「… 有依据 / 出处 / 引用 / 事实支撑」——两件事可能写在同一条里（「有日期、有依据」），各判各的
  const wantDate = R.date_want.test(t)
  const wantCite = R.cite_want.test(t)
  if (wantDate || wantCite) {
    const u = units(content)
    const unit = u.kind === 'item' ? '条' : '段'
    if (!u.texts.length) return { status: 'fail', why: DONE_WHY.no_units }
    // 「数字有出处」：只看含数字的单位
    const scope = R.numeric_only.test(t) && wantCite ? u.texts.filter((s) => /\d/.test(s)) : u.texts
    if (!scope.length) return { status: 'pass', why: DONE_WHY.no_numbers }
    const parts: string[] = []
    let fail = false
    if (wantDate) {
      const miss = scope.filter((s) => !R.date.test(s)).length
      if (miss) { fail = true; parts.push(fmt(DONE_WHY.date_miss, { n: scope.length, unit, miss })) } else parts.push(fmt(DONE_WHY.date_ok, { n: scope.length, unit }))
    }
    if (wantCite) {
      const miss = scope.filter((s) => !hasCite(s)).length
      if (miss) { fail = true; parts.push(fmt(DONE_WHY.cite_miss, { n: scope.length, unit, miss })) } else parts.push(fmt(DONE_WHY.cite_ok, { n: scope.length, unit }))
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
