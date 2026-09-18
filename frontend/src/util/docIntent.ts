/**
 * 文档意图（Doc Intent，docs/agent-native-editor.md §3.1）：每篇笔记知道自己要干什么。
 *
 * 三个字段——目标 / 读者 / 完成标准——常驻在标题下面一行，存在 `notes.intent`。
 * **所有作用在这篇上的 AI 动作把它当 system 的第一段**（骨架 / 续写 / 重写 / 润色 /
 * 扩展 / 校验 / 排版）：润色终于知道这篇是给谁看的，校验按「完成标准」核。
 *
 * 预填是**代码**按标题推的（零模型、可见、可改）——方案 §7 说了「不做 AI 猜你想写什么」；
 * 用户改一个字就是校准（source 变成 user），之后标题再变也不覆盖他改过的。
 * 这里只有纯函数；后端 `editor/intent.py` 的 `as_text` 跟 `intentText` 同一格式。
 */

export type DocIntent = { goal: string; reader: string; done: string; source: '' | 'prefill' | 'user' }

export const EMPTY_INTENT: DocIntent = { goal: '', reader: '', done: '', source: '' }
export const INTENT_FIELD_MAX = 200
export const INTENT_LABEL: Record<'goal' | 'reader' | 'done', string> = { goal: '目标', reader: '读者', done: '完成标准' }
export const INTENT_PLACEHOLDER: Record<'goal' | 'reader' | 'done', string> = {
  goal: '这篇要说清什么', reader: '写给谁看', done: '写到什么程度算完',
}

export function isEmptyIntent(i: DocIntent | null | undefined): boolean {
  return !i || !(i.goal || i.reader || i.done)
}

/** 「目标：…；读者：…；完成标准：…」——只列填了的字段。随每个 AI 动作带给后端。 */
export function intentText(i: DocIntent | null | undefined): string {
  if (!i) return ''
  return (['goal', 'reader', 'done'] as const)
    .filter((k) => i[k].trim())
    .map((k) => `${INTENT_LABEL[k]}：${i[k].trim()}`)
    .join('；')
}

/** 按标题预填的规则。**每条都是一个用户第一天就会写的文体**：周报 / 复盘 / 会议 / 方案 /
 *  调研 / 日记；匹配不上就按标题给一个中性的。顺序有意义：先具体后泛。 */
type Rule = { test: RegExp; goal: (t: string) => string; reader: string; done: string }
export const PREFILL_RULES: Rule[] = [
  { test: /周报|月报|季报|工作汇报|汇报/, goal: (t) => `${t.replace(/[:：]\s*$/, '')}：这段时间做了什么、进展到哪、卡在哪`, reader: '老板 / 团队', done: '每条进展有日期、有依据；卡住的说清要什么' },
  { test: /复盘|反思|回顾|总结/, goal: (t) => `${t.replace(/[:：]\s*$/, '')}：发生了什么、为什么、下次怎么做`, reader: '自己 / 团队', done: '每个结论有事实支撑；下次怎么做写成可执行的条目' },
  { test: /会议|纪要|例会|讨论|同步会/, goal: (t) => `${t.replace(/[:：]\s*$/, '')}：记下结论和待办`, reader: '与会的人', done: '每条待办有负责人和日期；争议点两边都写' },
  { test: /方案|计划|PRD|需求|设计|路线图|roadmap/i, goal: (t) => `${t.replace(/[:：]\s*$/, '')}：说清要做什么、为什么、怎么做`, reader: '拍板的人 / 执行团队', done: '范围、里程碑、风险各有一节；数字有出处' },
  { test: /调研|分析|对比|评测|研究|竞品/, goal: (t) => `${t.replace(/[:：]\s*$/, '')}：回答一个问题，给出判断`, reader: '要据此做决定的人', done: '结论在前；每个判断有出处；列出没查到的' },
  { test: /日记|随笔|杂记|日志/, goal: (t) => `${t.replace(/[:：]\s*$/, '')}：记下今天`, reader: '自己', done: '写下来就算完' },
]

/** 从标题推一份预填。标题空 → 空意图（不猜）。 */
export function prefillIntent(title: string): DocIntent {
  const t = (title || '').trim()
  if (!t || t === '未命名') return { ...EMPTY_INTENT }
  const r = PREFILL_RULES.find((x) => x.test.test(t))
  if (r) return { goal: clip(r.goal(t)), reader: r.reader, done: r.done, source: 'prefill' }
  return { goal: clip(`围绕「${t.replace(/[:：]\s*$/, '')}」写清楚一件事`), reader: '自己', done: '每个论断有依据（引用或出处）', source: 'prefill' }
}

function clip(s: string): string { return s.slice(0, INTENT_FIELD_MAX) }

/** 打开一篇 / 标题变了：库里有用户改过的就用库里的；没有（或还是预填的）就按现在的标题重推。 */
export function resolveIntent(stored: DocIntent | null | undefined, title: string): DocIntent {
  // 用户改过的（source=user）、或不知道来源但填了字的（接口直接写进来的）都算他的；只有预填的才跟标题重推
  if (stored && !isEmptyIntent(stored) && stored.source !== 'prefill') return { ...stored, source: stored.source || 'user' }
  return prefillIntent(title)
}
