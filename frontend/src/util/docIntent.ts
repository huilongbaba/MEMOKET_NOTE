/**
 * 文档意图（Doc Intent，docs/agent-native-editor.md §3.1）：每篇笔记知道自己要干什么。
 *
 * 三个可选字段——目标 / 读者 / 完成标准——收在标题下面的「写作任务」里，存在 `notes.intent`。
 * **所有作用在这篇上的 AI 动作把它当 system 的第一段**（骨架 / 续写 / 重写 / 润色 /
 * 扩展 / 校验 / 排版）：润色终于知道这篇是给谁看的，校验按「完成标准」核。
 *
 * 新笔记不从标题推断任务。用户明确填写后 source 变成 user，之后标题变化不覆盖。
 * `prefill` 只为兼容历史数据；读取时不会把它当成用户意图。
 * 这里只有纯函数；后端 `editor/intent.py` 的 `as_text` 跟 `intentText` 同一格式。
 */

export type DocIntent = {
  goal: string; reader: string; done: string; source: '' | 'prefill' | 'user'
  /** 「完成标准」里代码判不了、用户自己勾过的那几条（原文）。P12 §3.1「完成标准可检查」：跟三个字段一起存在 `notes.intent`，不另开表。 */
  checked?: string[]
}

export const EMPTY_INTENT: DocIntent = { goal: '', reader: '', done: '', source: '', checked: [] }
export const INTENT_FIELD_MAX = 200
export const INTENT_LABEL: Record<'goal' | 'reader' | 'done', string> = { goal: '目标', reader: '读者', done: '完成标准' }
export const INTENT_PLACEHOLDER: Record<'goal' | 'reader' | 'done', string> = {
  goal: '这篇要说清什么', reader: '写给谁看', done: '写到什么程度算完',
}

/**
 * 高频写作工作流。只有用户主动点选才会套用；它们不会根据标题、用户或知识库自动匹配。
 * 三个值仍是普通 Doc Intent，套用后可继续编辑，也走现有 Harness，不引入另一套执行器。
 */
export type WritingScenario = {
  id: 'daily' | 'weekly' | 'journal' | 'meeting'
  label: string
  intent: Pick<DocIntent, 'goal' | 'reader' | 'done'>
}

export const WRITING_SCENARIOS: WritingScenario[] = [
  {
    id: 'daily', label: '日报', intent: {
      goal: '根据当天已有记录整理事实、阻塞和下一步',
      reader: '自己或协作者',
      done: '事实、阻塞、下一步各有一节；只使用当天已有记录，不补写未发生的经历',
    },
  },
  {
    id: 'weekly', label: '周报', intent: {
      goal: '根据本周已有材料形成可供协作和决策的周度总结',
      reader: '协作者或决策者',
      done: '目标、进展、风险、下周行动各有一节；每个阻塞项写清影响、所需支持和下一步；关键结论有出处',
    },
  },
  {
    id: 'journal', label: '日记', intent: {
      goal: '记录当天经历、感受和仍未想清楚的问题',
      reader: '自己',
      done: '保持第一人称和原有语气；事实与感受分开；不强行总结或升华',
    },
  },
  {
    id: 'meeting', label: '会议纪要', intent: {
      goal: '从会议材料中整理讨论、决定和后续行动',
      reader: '参会者和执行者',
      done: '讨论、决定、行动项各有一节；行动项只写材料中已有的负责人和时间；缺失信息标为待确认',
    },
  },
]

export function isEmptyIntent(i: DocIntent | null | undefined): boolean {
  return !i || !(i.goal || i.reader || i.done)
}

/** 「目标：…；读者：…；完成标准：…」——只列填了的字段。随每个 AI 动作带给后端。 */
export function intentText(i: DocIntent | null | undefined): string {
  // 历史版本按标题生成的 prefill 不代表用户选择。即使热更新保留了旧 state，
  // 也不能把界面准备清掉的要求继续悄悄发给后端。
  if (!i || i.source === 'prefill') return ''
  return (['goal', 'reader', 'done'] as const)
    .filter((k) => i[k].trim())
    .map((k) => `${INTENT_LABEL[k]}：${i[k].trim()}`)
    .join('；')
}

/** 打开一篇：只恢复用户显式写过的任务；历史自动预填一律当作空。 */
export function resolveIntent(stored: DocIntent | null | undefined, _title: string): DocIntent {
  // 用户改过的（source=user）、或不知道来源但填了字的（接口直接写进来的）都算他的。
  if (stored && !isEmptyIntent(stored) && stored.source !== 'prefill') return { ...stored, source: stored.source || 'user' }
  return { ...EMPTY_INTENT }
}

/**
 * 智能续写是否缺少最小方向。已有明确目标、骨架或足够正文时，Harness 可以直接从页面理解；
 * 只有短而零散的草稿才请用户补一句目标，避免每次续写都先填表。
 */
export function needsHarnessGoal(
  intent: DocIntent | null | undefined,
  content: string,
  spine: string,
  beats: Array<{ text?: string } | string>,
): boolean {
  if (intent?.goal.trim() || spine.trim()) return false
  if (beats.some((beat) => (typeof beat === 'string' ? beat : beat.text ?? '').trim())) return false
  const plain = content
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/^\s{0,3}#{1,6}\s+.*$/gm, ' ')
    .trim()
  const paragraphs = plain.split(/\n\s*\n/).map((p) => p.trim()).filter((p) => p.length >= 12)
  return plain.replace(/\s/g, '').length < 120 && paragraphs.length < 2
}
