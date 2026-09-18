// @vitest-environment jsdom
/**
 * P9（产品就绪计划 §2 C2 + B 线遗留，`docs/TRACELOG-product.md` P9 节）：前端管得着的几条。
 *
 *   文档意图（`util/docIntent`，agent-native-editor §3.1）：按标题预填（零模型）、用户改过就不覆盖、
 *     拼成一句随 AI 动作带给后端（格式跟后端 `editor/intent.as_text` 一样）；标题下那一行 `DocIntentRow`
 *   边缘记忆（`editor/marginMemory`，§3.3）：光标所在段的段首行、点的身份、哪两种关系自己贴到行边上
 *   关系卡动作一份两处（`util/relationActions`）：后端没起来时 toast 说人话，不再是英文 `Failed to fetch`
 *   生成骨架 / 智能排版跑着时有「停止」（P3 遗留 ❌×2）；录音钮转写中有「停止」
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { Text } from '@codemirror/state'

import { EMPTY_INTENT, intentText, isEmptyIntent, prefillIntent, resolveIntent, INTENT_FIELD_MAX } from '../../util/docIntent'
import { AUTO_SHOW, markKey, paragraphStartLine, type MarginMark } from '../marginMemory'
import { alreadyCited, citeText, fillInText, ignoreRelation, ignoredSet, relationKey, supersedeRelation } from '../../util/relationActions'
import DocIntentRow from '../../components/DocIntentRow'
import SkeletonPanel from '../../components/SkeletonPanel'
import MarkdownToolbar from '../../components/MarkdownToolbar'

describe('文档意图：预填 / 校准 / 拼句（P9 §3.1）', () => {
  it('按标题预填：周报 / 复盘 / 会议 / 方案 / 调研 / 日记各一套，都标 prefill', () => {
    const w = prefillIntent('第 37 周周报')
    expect(w.source).toBe('prefill')
    expect(w.goal).toContain('第 37 周周报')
    expect(w.reader).toContain('老板')
    expect(w.done).toContain('日期')
    expect(prefillIntent('创业反思').goal).toContain('发生了什么')
    expect(prefillIntent('周一例会').done).toContain('负责人')
    expect(prefillIntent('APP 需求 PRD').reader).toContain('执行团队')
    expect(prefillIntent('竞品调研').done).toContain('出处')
    expect(prefillIntent('日记').reader).toBe('自己')
  })
  it('匹配不上的标题给一个中性的；空标题 / 占位标题不猜', () => {
    const g = prefillIntent('plaud的优势分析')     // 「分析」命中调研那条
    expect(g.source).toBe('prefill')
    const n = prefillIntent('hi')
    expect(n.goal).toContain('「hi」')
    expect(n.done).toContain('依据')
    expect(isEmptyIntent(prefillIntent(''))).toBe(true)
    expect(isEmptyIntent(prefillIntent('未命名'))).toBe(true)
  })
  it('标题末尾的冒号不进目标；超长封顶', () => {
    expect(prefillIntent('公司汇报：').goal.startsWith('公司汇报：这段')).toBe(true)
    expect(prefillIntent('x'.repeat(400)).goal.length).toBeLessThanOrEqual(INTENT_FIELD_MAX)
  })
  it('用户改过的（source=user）永远不被标题覆盖；预填的跟标题重推', () => {
    const mine = { goal: '我的目标', reader: '我', done: '写完', source: 'user' as const }
    expect(resolveIntent(mine, '第 37 周周报')).toEqual(mine)
    const pre = prefillIntent('创业反思')
    expect(resolveIntent(pre, '第 37 周周报').reader).toContain('老板')
    // 接口直接写进来、没标来源但填了字的，也算他的
    expect(resolveIntent({ ...EMPTY_INTENT, goal: 'x' }, '日记').source).toBe('user')
    expect(resolveIntent(null, '日记').source).toBe('prefill')
  })
  it('拼成一句：只列填了的，「目标：…；读者：…；完成标准：…」', () => {
    expect(intentText({ goal: '本周汇报', reader: '', done: '每条有日期', source: 'user' })).toBe('目标：本周汇报；完成标准：每条有日期')
    expect(intentText(EMPTY_INTENT)).toBe('')
    expect(intentText(null)).toBe('')
  })
  it('标题下那一行：三个字段就地可改，预填的带「预填」标', () => {
    const html = renderToStaticMarkup(createElement(DocIntentRow, { intent: prefillIntent('创业反思'), onChange: () => {} }))
    expect(html).toContain('这篇要干什么')
    expect(html).toContain('aria-label="目标"')
    expect(html).toContain('aria-label="读者"')
    expect(html).toContain('aria-label="完成标准"')
    expect(html).toContain('预填')
    const mine = renderToStaticMarkup(createElement(DocIntentRow, { intent: { goal: 'g', reader: 'r', done: 'd', source: 'user' }, onChange: () => {} }))
    expect(mine).not.toContain('>预填<')
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
