// @vitest-environment jsdom
/**
 * P12（产品就绪计划 §2 C2，`docs/TRACELOG-product.md` P12 节）：agent-native 再落地两条，前端管得着的部分。
 *
 *   完成标准可检查（`util/doneChecks`，agent-native-editor §3.1）：「完成标准」一句拆成几条；字数 / 每条有日期 /
 *     有出处 / 各有一节 / 结论在前 代码当场判并说清为什么；判不了的是「要你判」的勾，勾过的记在 intent.checked
 *   目录 = 计划（`util/sectionStatus`，§3.5）：每一节从正文算出「空 / 草稿 / 有依据」和用了几条材料；
 *     骨架节拍的「已写 / 待补」拆成状态标（跟后端 skeleton.py::split_beat_label 同一批写法，多一道「后面得跟标点」）
 *   界面：右栏不再有单独的「目录」页签，「计划」页签 = 完成标准 + 目录（带状态）+ 骨架 + 执行；
 *     标题下「完成标准」后面挂 n/m 角标；PlanChecks 的勾是 <input type=checkbox>（键盘能按）
 */
import { describe, expect, it } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import appSrc from '../../App.tsx?raw'

import { checkDone, checkDoneItem, doneSummary, splitDone, units } from '../../util/doneChecks'
import { sectionStatuses, sectionSummary, splitBeatLabel, materialsText } from '../../util/sectionStatus'
import { parseHeadings } from '../../components/DocumentOutline'
import { EMPTY_INTENT, resolveIntent } from '../../util/docIntent'
import PlanChecks from '../../components/PlanChecks'
import DocIntentRow from '../../components/DocIntentRow'
import SkeletonPanel from '../../components/SkeletonPanel'

const 周报 = [
  '# 第 37 周周报', '',
  '## 进展', '',
  '- 9 月 15 日 DVT 测试报告补齐 [terrence-1872-5F8]',
  '- 众筹页面上线（9/16）[terrence-1901-A1B]',
  '- 电池方案定 380mAh',
  '',
  '## 卡点', '',
  '采购还没下单，等结构评审。',
].join('\n')

describe('完成标准可检查：拆条（P12 §3.1）', () => {
  it('分号 / 句号 / 换行拆，逗号不拆（「有日期、有依据」是一条）', () => {
    expect(splitDone('每条进展有日期、有依据；卡住的说清要什么。≤ 800 字')).toEqual(['每条进展有日期、有依据', '卡住的说清要什么', '≤ 800 字'])
    expect(splitDone('')).toEqual([])
    expect(splitDone('；；')).toEqual([])
  })
  it('「每条」的单位：有列表按列表项，没有按 ≥20 字的段落，标题和围栏不算', () => {
    expect(units(周报)).toEqual({ kind: 'item', texts: ['9 月 15 日 DVT 测试报告补齐 [terrence-1872-5F8]', '众筹页面上线（9/16）[terrence-1901-A1B]', '电池方案定 380mAh'] })
    const u = units('## 标题\n\n这是一段有二十个字以上的正文，用来当单位。\n\n```\n# 不是标题\n- 不是条目\n```\n短')
    expect(u.kind).toBe('paragraph')
    expect(u.texts).toEqual(['这是一段有二十个字以上的正文，用来当单位。'])
  })
})

describe('完成标准可检查：代码判得了的几类', () => {
  it('字数上限 / 下限：≤ 800 字、800 字以内、至少 300 字，说清现在几个字', () => {
    expect(checkDoneItem('≤ 800 字', 周报)).toMatchObject({ status: 'pass' })
    expect(checkDoneItem('不超过 10 字', 周报)).toMatchObject({ status: 'fail' })
    expect(checkDoneItem('不超过 10 字', 周报)!.why).toMatch(/超出 \d+ 字/)
    expect(checkDoneItem('10 字以内', 周报)!.status).toBe('fail')
    expect(checkDoneItem('至少 300 字', 周报)).toMatchObject({ status: 'fail' })
    expect(checkDoneItem('至少 300 字', 周报)!.why).toMatch(/还差 \d+ 字/)
    expect(checkDoneItem('至少 10 字', 周报)!.status).toBe('pass')
  })
  it('每条进展有日期：3 条里 1 条没有 → 没过，说「3 条里 1 条没有日期」', () => {
    const r = checkDoneItem('每条进展有日期', 周报)!
    expect(r.status).toBe('fail')
    expect(r.why).toBe('3 条里 1 条没有日期')
  })
  it('有依据 / 出处：引用 [id]、note:// 链接、http 链接都算；「数字有出处」只看含数字的条', () => {
    const r = checkDoneItem('每条进展有日期、有依据', 周报)!
    expect(r.status).toBe('fail')
    expect(r.why).toBe('3 条里 1 条没有日期；3 条里 1 条没有出处')
    const ok = checkDoneItem('每个论断有依据（引用或出处）', '- 一条 [terrence-1-A]\n- 两条 [笔记](note://0eecee3d7b94)\n- 三条 https://x.y/z')!
    expect(ok).toEqual({ status: 'pass', why: '3 条都有出处' })
    expect(checkDoneItem('数字有出处', '- 没数字的一条\n- 有 12 个 [terrence-1-A]')!).toEqual({ status: 'pass', why: '1 条都有出处' })
    expect(checkDoneItem('每个结论有事实支撑', '')!).toEqual({ status: 'fail', why: '正文里还没有条目' })
  })
  it('「范围、里程碑、风险各有一节」：看 # 标题里有没有这几个词，缺的点名', () => {
    expect(checkDoneItem('范围、里程碑、风险各有一节', '## 范围\n\n## 风险\n')).toEqual({ status: 'fail', why: '标题里没有：里程碑' })
    expect(checkDoneItem('范围、里程碑、风险各有一节', '## 范围\n## 里程碑\n## 风险与对策\n')).toEqual({ status: 'pass', why: '3 节都有' })
  })
  it('结论在前 / 写下来就算完', () => {
    expect(checkDoneItem('结论在前', '## 结论\n\n先说结论。')!.status).toBe('pass')
    expect(checkDoneItem('结论在前', '## 背景\n\n先讲一大段背景。')!.status).toBe('fail')
    expect(checkDoneItem('写下来就算完', '')!.status).toBe('fail')
    expect(checkDoneItem('写下来就算完', '今天很好。')!.status).toBe('pass')
  })
  it('代码判不了的回 null → checkDone 里是 manual，勾过的算过；doneSummary 只把 pass 和勾过的 manual 算过', () => {
    expect(checkDoneItem('卡住的说清要什么', 周报)).toBeNull()
    const items = checkDone('每条进展有日期；卡住的说清要什么；≤ 800 字', 周报, ['卡住的说清要什么'])
    expect(items.map((i) => i.status)).toEqual(['fail', 'manual', 'pass'])
    expect(items[1].checked).toBe(true)
    expect(doneSummary(items)).toEqual({ ok: 2, total: 3, failing: 1 })
    expect(doneSummary(checkDone('每条进展有日期；卡住的说清要什么', 周报))).toEqual({ ok: 0, total: 2, failing: 1 })
  })
  it('勾过的条目跟着意图走：resolveIntent 保留 user 意图里的 checked，预填的没有', () => {
    const stored = { ...EMPTY_INTENT, done: 'a；b', source: 'user' as const, checked: ['b'] }
    expect(resolveIntent(stored, '随便').checked).toEqual(['b'])
    expect(resolveIntent(null, '第 37 周周报').checked ?? []).toEqual([])
  })
})

describe('目录 = 计划：每一节的状态（P12 §3.5）', () => {
  const 回顾 = ['创业一年回顾', '', '## 时间线', '', '### APP', '', '### 硬件', '', '## 反思', '', '现有记录能确认的变化 [terrence-1-A]，链到 [上篇](note://0eecee3d7b94)。', ''].join('\n')
  it('空 = 标题下面（含子节）一个字都没有；草稿 = 有字没出处；有依据 = 引了事实或链了笔记，并数出用了几条材料', () => {
    const s = sectionStatuses(回顾, parseHeadings(回顾))
    expect(s.map((x) => x.state)).toEqual(['empty', 'empty', 'empty', 'sourced'])
    expect(s[3]).toMatchObject({ cites: 1, links: 1 })
    expect(materialsText(s[3])).toBe('1 条出处 · 链 1 篇')
    expect(sectionSummary(s)).toEqual({ empty: 3, draft: 0, sourced: 1 })
    const draft = sectionStatuses('## 一\n\n写了字。\n\n## 二\n', parseHeadings('## 一\n\n写了字。\n\n## 二\n'))
    expect(draft.map((x) => x.state)).toEqual(['draft', 'empty'])
  })
  it('父节自己没字、子节有字 → 父节不算空', () => {
    const c = '## 父\n\n### 子\n\n子节有字。\n'
    expect(sectionStatuses(c, parseHeadings(c)).map((x) => x.state)).toEqual(['draft', 'draft'])
  })
  it('节拍的「已写 / 待补」拆成状态标：各种写法都认、带行号的带出来；「已写部分先建立…」是句子开头不是标签', () => {
    expect(splitBeatLabel('已写：以 5G 切换 2.4G 为变更起点')).toEqual({ status: 'written', text: '以 5G 切换 2.4G 为变更起点', line: null })
    expect(splitBeatLabel('已写（正文第 12 行起）：把 APP 的安装阻塞设为闸门')).toEqual({ status: 'written', text: '把 APP 的安装阻塞设为闸门', line: 12 })
    expect(splitBeatLabel('【待补】先补齐一年中关键决策的时间线')).toEqual({ status: 'missing', text: '先补齐一年中关键决策的时间线', line: null })
    expect(splitBeatLabel('尚缺：结尾')).toMatchObject({ status: 'missing', text: '结尾' })
    expect(splitBeatLabel('已写部分先建立产品定位不断收敛的过程')).toEqual({ status: null, text: '已写部分先建立产品定位不断收敛的过程', line: null })
    expect(splitBeatLabel('没标的一条')).toEqual({ status: null, text: '没标的一条', line: null })
  })
})

describe('界面：计划页签 + 角标 + 勾（P12）', () => {
  const app = appSrc
  it('右栏不再有单独的「目录」页签；「计划」页签里是 PlanChecks + 带状态的 DocumentOutline + 骨架', () => {
    expect(app).not.toMatch(/id: 'outline', title: '目录'/)
    expect(app).toMatch(/<PlanChecks key="checks"/)
    expect(app).toMatch(/<DocumentOutline content=\{content\} viewRef=\{editorViewRef\} withStatus \/>/)
    expect(app).toMatch(/onJumpLine=\{jumpToLine\}/)
  })
  it('PlanChecks：自动检查画 ✓ / ✗ 并说为什么；人工确认项明确说明作用；空的说去哪填', () => {
    const html = renderToStaticMarkup(createElement(PlanChecks, { done: '每条进展有日期；卡住的说清要什么', content: 周报, checked: [], onToggle: () => {} }))
    expect(html).toContain('plan-check-mark fail')
    expect(html).toContain('3 条里 1 条没有日期')
    expect(html).toContain('type="checkbox"')
    expect(html).toContain('需你确认')
    expect(html).toContain('AI 会按这条写；系统无法可靠验收，完成后请你确认')
    expect(html).toContain('0/2')
    const empty = renderToStaticMarkup(createElement(PlanChecks, { done: '', content: 周报, checked: [], onToggle: () => {}, onEdit: () => {} }))
    expect(empty).toContain('这是可选项')
    expect(empty).toContain('去填')
  })
  it('标题下「完成标准」后面挂 n/m 角标：没过的标 fail、全过标 ok；没有完成标准就不挂', () => {
    const row = (checks?: { ok: number; total: number; failing: number }, done = '每条进展有日期') =>
      renderToStaticMarkup(createElement(DocIntentRow, { intent: { ...EMPTY_INTENT, done, source: 'user' }, onChange: () => {}, checks, onOpenChecks: () => {} }))
    expect(row({ ok: 1, total: 3, failing: 1 })).toMatch(/doc-intent-check fail[^>]*>1\/3</)
    expect(row({ ok: 3, total: 3, failing: 0 })).toMatch(/doc-intent-check ok/)
    expect(row({ ok: 0, total: 0, failing: 0 }, '')).not.toContain('doc-intent-check')
    expect(row()).not.toContain('doc-intent-check')
  })
  it('骨架节拍：「已写 / 待补」变成状态标，带行号的是能点的按钮', () => {
    const html = renderToStaticMarkup(createElement(SkeletonPanel, {
      spine: 's', beats: ['已写（正文第 3 行起）：一', '待补：二', '没标的三'], beatCoverage: null, loading: false, onRun: () => {}, onJumpLine: () => {},
    }))
    expect(html).toMatch(/<button class="plan-state written"[^>]*>已写<\/button>/)
    expect(html).toMatch(/<span class="plan-state missing"[^>]*>待补<\/span>/)
    expect(html).toContain('没标的三')
    expect(html).not.toContain('已写（正文第')
  })
})
