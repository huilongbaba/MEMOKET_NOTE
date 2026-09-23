// @vitest-environment jsdom
/**
 * P9（产品就绪计划 §2 C2 + B 线遗留，`docs/TRACELOG-product.md` P9 节）：前端管得着的几条。
 *
 *   文档意图（`util/docIntent`，agent-native-editor §3.1）：标题不猜任务、用户填写后原样恢复、
 *     拼成一句随 AI 动作带给后端（格式跟后端 `editor/intent.as_text` 一样）；标题下那一行 `DocIntentRow`
 *   边缘记忆（`editor/marginMemory`，§3.3）：光标所在段的段首行、点的身份、哪两种关系自己贴到行边上
 *   关系卡动作一份两处（`util/relationActions`）：后端没起来时 toast 说人话，不再是英文 `Failed to fetch`
 *   生成骨架 / 智能排版跑着时有「停止」（P3 遗留 ❌×2）；录音钮转写中有「停止」
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { Text } from '@codemirror/state'

import { EMPTY_INTENT, WRITING_SCENARIOS, intentText, isEmptyIntent, needsHarnessGoal, resolveIntent } from '../../util/docIntent'
import { AUTO_SHOW, markKey, paragraphStartLine, type MarginMark } from '../marginMemory'
import { alreadyCited, citeText, fillInText, ignoreRelation, ignoredSet, relationKey, supersedeRelation } from '../../util/relationActions'
import DocIntentRow from '../../components/DocIntentRow'
import SkeletonPanel from '../../components/SkeletonPanel'
import MarkdownToolbar from '../../components/MarkdownToolbar'
import { checkDone } from '../../util/doneChecks'

describe('文档意图：显式设置 / 拼句（P9 §3.1）', () => {
  it('任何标题都不自动推断目标、读者或完成标准', () => {
    for (const title of ['周报', '会议纪要', '产品方案', '日记', 'Research Plan', '']) {
      expect(isEmptyIntent(resolveIntent(null, title))).toBe(true)
    }
  })
  it('用户写过的任务永远不被标题覆盖；历史 prefill 直接清空', () => {
    const mine = { goal: '我的目标', reader: '我', done: '写完', source: 'user' as const }
    expect(resolveIntent(mine, '第 37 周周报')).toEqual(mine)
    expect(resolveIntent({ goal: '自动内容', reader: '某类读者', done: '自动标准', source: 'prefill' }, '任意标题')).toEqual(EMPTY_INTENT)
    // 接口直接写进来、没标来源但填了字的，也算他的
    expect(resolveIntent({ ...EMPTY_INTENT, goal: 'x' }, '日记').source).toBe('user')
    expect(resolveIntent(null, '日记').source).toBe('')
  })
  it('拼成一句：只列填了的，「目标：…；读者：…；完成标准：…」', () => {
    expect(intentText({ goal: '本周汇报', reader: '', done: '每条有日期', source: 'user' })).toBe('目标：本周汇报；完成标准：每条有日期')
    expect(intentText({ goal: '旧周报', reader: '', done: '卡住的说清要什么', source: 'prefill' })).toBe('')
    expect(intentText(EMPTY_INTENT)).toBe('')
    expect(intentText(null)).toBe('')
  })
  it('标题下默认只显示可选任务摘要，不把三个设置冒充新建笔记必填项', () => {
    const html = renderToStaticMarkup(createElement(DocIntentRow, { intent: { goal: '整理关键判断', reader: '', done: '', source: 'user' }, onChange: () => {} }))
    expect(html).toContain('写作任务')
    expect(html).toContain('整理关键判断')
    expect(html).not.toContain('doc-intent-input')
    const mine = renderToStaticMarkup(createElement(DocIntentRow, { intent: { goal: 'g', reader: 'r', done: 'd', source: 'user' }, onChange: () => {} }))
    expect(mine).toContain('>g<')
    const empty = renderToStaticMarkup(createElement(DocIntentRow, { intent: EMPTY_INTENT, onChange: () => {} }))
    expect(empty).toContain('写作任务（可选）')
  })
  it('四个工作流都由用户主动选择，套用的是同一份可编辑 Doc Intent', () => {
    expect(WRITING_SCENARIOS.map((s) => s.label)).toEqual(['日报', '周报', '日记', '会议纪要'])
    for (const scenario of WRITING_SCENARIOS) {
      expect(scenario.intent.goal).not.toBe('')
      expect(scenario.intent.reader).not.toBe('')
      expect(scenario.intent.done).not.toBe('')
      expect(intentText({ ...scenario.intent, source: 'user' })).toContain('完成标准：')
    }
    for (const id of ['daily', 'weekly', 'meeting']) {
      const scenario = WRITING_SCENARIOS.find((s) => s.id === id)!
      const sectionCheck = checkDone(scenario.intent.done, '').find((item) => item.why.startsWith('标题里没有：'))
      expect(sectionCheck?.status).toBe('fail')
    }
    const html = renderToStaticMarkup(createElement(DocIntentRow, {
      intent: EMPTY_INTENT, onChange: () => {}, promptForGoal: true,
    }))
    expect(html).toContain('智能续写还不知道最终要写成什么')
    for (const label of ['日报', '周报', '日记', '会议纪要']) expect(html).toContain(`>${label}<`)
  })
  it('只在目标、骨架、正文都不足时追问，不让成熟草稿重复填表', () => {
    expect(needsHarnessGoal(EMPTY_INTENT, '只有一个想法', '', [])).toBe(true)
    expect(needsHarnessGoal({ ...EMPTY_INTENT, goal: '写清取舍' }, '只有一个想法', '', [])).toBe(false)
    expect(needsHarnessGoal(EMPTY_INTENT, '只有一个想法', '围绕成本和速度的取舍展开', [])).toBe(false)
    expect(needsHarnessGoal(EMPTY_INTENT, '只有一个想法', '', ['补出失败后的决策变化'])).toBe(false)
    expect(needsHarnessGoal(EMPTY_INTENT,
      '第一段已经交代了问题、背景和当前结论，足以让编辑器判断接下来要补哪一层。\n\n第二段继续给出事实和取舍，并留下一个尚未回答的问题。', '', [])).toBe(false)
  })
})

describe('边缘记忆：卡贴到行边上（P9 §3.3）', () => {
  it('光标所在段的段首行：往上找到空行为止；光标在空行上不属于任何段', () => {
    const doc = Text.of(['# 标题', '', '第一段第一行', '第一段第二行', '', '第二段'])
    expect(paragraphStartLine(doc, 4)).toBe(3)
    expect(paragraphStartLine(doc, 3)).toBe(3)
    expect(paragraphStartLine(doc, 6)).toBe(6)
    expect(paragraphStartLine(doc, 5)).toBe(0)
    expect(paragraphStartLine(doc, 1)).toBe(1)
  })
  it('点的身份 = 关系 + 事实，跟行号无关（正文改了行号会变，「自动弹过一次」按它记）', () => {
    const a: MarginMark = { line: 3, relation: 'conflict', say: 's', fact_ids: ['f1'] }
    const b: MarginMark = { line: 9, relation: 'conflict', say: 's2', fact_ids: ['f1'] }
    expect(markKey(a)).toBe(markKey(b))
    expect(markKey({ ...a, relation: 'corroborated' })).not.toBe(markKey(a))
  })
  it('只有冲突 / 延续两种自己贴到行边上；印证 / 缺依据 / 叠加 / 合并 静默（要看才悬停）', () => {
    expect([...AUTO_SHOW].sort()).toEqual(['conflict', 'continuation'])
  })
})

describe('关系卡动作一份两处（`util/relationActions`）', () => {
  beforeEach(() => { localStorage.clear() })
  const rel = { relation: 'conflict' as const, fact_ids: ['a', 'b'], facts: [
    { id: 'a', text: 'DVT 6 月 3 日', when: '2026-04-10', kind: '', sources: [] },
    { id: 'b', text: 'DVT 改到 8 月 5 日', when: '2026-05-08', kind: '', sources: [] },
  ] }
  it('引用这条 = 最新那条带出处；补进来 = 全部带出处；已引用看正文', () => {
    expect(citeText(rel)).toBe('DVT 改到 8 月 5 日 [b]')
    expect(fillInText(rel)).toBe('DVT 6 月 3 日 [a]\nDVT 改到 8 月 5 日 [b]')
    expect(alreadyCited(rel, '正文 [b] 引过')).toBe(true)
    expect(alreadyCited(rel, '正文只引了 [a]')).toBe(false)
  })
  it('忽略记在本机、两张卡共用一份名单、发事件让另一张卡跟着灭', () => {
    const seen: string[] = []
    window.addEventListener('relation-ignored', (e) => seen.push((e as CustomEvent<string>).detail))
    ignoreRelation(relationKey(rel))
    expect(ignoredSet().has('conflict:a,b')).toBe(true)
    expect(seen).toEqual(['conflict:a,b'])
  })
  it('后端没起来：「标不上」说人话，不再是英文 Failed to fetch（P3 遗留 ？）', async () => {
    const toasts: string[] = []
    const toastMod = await import('../../toast')
    vi.spyOn(toastMod, 'toast').mockImplementation((m: string) => { toasts.push(m) })
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))))
    expect(await supersedeRelation(rel)).toBe(false)
    expect(toasts[0]).toMatch(/^标不上：连不上应用后台/)
    expect(toasts[0]).not.toContain('Failed to fetch')
    vi.unstubAllGlobals()
  })
})

describe('跑着的时候有「停止」（P3 遗留 ❌×2 + ？）', () => {
  const noop = () => {}
  it('生成骨架：转圈时按钮变「停止」，不再是一个禁用的转圈', () => {
    const busy = renderToStaticMarkup(createElement(SkeletonPanel, { spine: '', beats: [], beatCoverage: null, loading: true, onRun: noop, onStop: noop }))
    expect(busy).toContain('停止')
    expect(busy).not.toContain('disabled')
    const idle = renderToStaticMarkup(createElement(SkeletonPanel, { spine: '', beats: [], beatCoverage: null, loading: false, onRun: noop, onStop: noop }))
    expect(idle).toContain('生成骨架')
    expect(idle).not.toContain('停止')
  })
  it('智能排版：跑着时工具栏那个钮变「停止」', () => {
    const ref = { current: null }
    const busy = renderToStaticMarkup(createElement(MarkdownToolbar, { viewRef: ref, onRestructure: noop, onStopRestructure: noop, restructuring: true }))
    expect(busy).toContain('停止')
    expect(busy).not.toContain('智能排版')
    const idle = renderToStaticMarkup(createElement(MarkdownToolbar, { viewRef: ref, onRestructure: noop, onStopRestructure: noop, restructuring: false }))
    expect(idle).toContain('智能排版')
  })
})
