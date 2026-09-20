// @vitest-environment jsdom
/**
 * P16（产品就绪计划 §2 C2，`docs/TRACELOG-product.md` P16 节）：agent-native 剩下两条，前端管得着的部分。
 *
 *   改动的分层历史（`util/runRounds` + `editor/undoRound`，agent-native-editor §3.2 / 痛点 8）：后端每轮开始前存一版
 *     （reason='round'）、收尾一版（run_end）；这里按 run_id 组回轮次（第 N 轮的「之后」= 同一次跑里紧跟着的下一行），
 *     「只撤这一轮」= 前后两版 diff 反向应用到现在的正文，对不上的说清楚
 *   ⌥ 悬停来龙去脉贴词边（`editor/altHover` + `util/traceCard`，§3.3 场景 B / 痛点 11、12）：词怎么切、卡上写什么、
 *     没结果说「知识库里没有」；键盘 ⌥↩ 同一条路
 *   界面：「改动」页签有烧过的跑时也留着；每轮两个按钮；历史面板同一次跑折成一组；快捷键表里查得到
 */
import { describe, expect, it } from 'vitest'
import { createElement, createRef } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { EditorState } from '@codemirror/state'
import type { EditorView } from '@codemirror/view'
import appSrc from '../../App.tsx?raw'
import editorSrc from '../../components/MarkdownEditor.tsx?raw'
import shortcutsSrc from '../../shortcuts.ts?raw'

import { groupRuns, historyGroups, revisionLabel, runTitle } from '../../util/runRounds'
import { undoRound } from '../undoRound'
import { candidates, emptyReason, summarizeTrace } from '../../util/traceCard'
import { phraseAt, phraseAtPos, HOVER_MS } from '../altHover'
import ChangeLayersPanel from '../../components/ChangeLayersPanel'
import type { Fact, NoteRevision } from '../../api'

const rev = (id: string, reason: string, round_no: number, run_id: string, at: string, chars = 100): NoteRevision =>
  ({ id, note_id: 'n', title: 't', reason, round_no, run_id, created_at: at, chars })

// /revisions 的顺序：新的在前
const REVS: NoteRevision[] = [
  rev('e', 'run_end', 3, 'runA', '2026-09-19T10:03:00', 400),
  rev('r3', 'round', 3, 'runA', '2026-09-19T10:02:00', 300),
  rev('r2', 'round', 2, 'runA', '2026-09-19T10:01:00', 200),
  rev('r1', 'round', 1, 'runA', '2026-09-19T10:00:00', 100),
  rev('m', 'manual', 0, '', '2026-09-19T09:00:00', 90),
  rev('a', 'auto', 0, '', '2026-09-18T09:00:00', 80),
]

describe('分层历史：按跑组回轮次（P16 §3.2）', () => {
  it('第 N 轮的「之前」是它自己那一行，「之后」是紧跟着的下一行；最后一轮的之后是 run_end', () => {
    const [run] = groupRuns(REVS)
    expect(run.run_id).toBe('runA')
    expect(run.rounds.map((r) => [r.round_no, r.before.id, r.after?.id])).toEqual([[1, 'r1', 'r2'], [2, 'r2', 'r3'], [3, 'r3', 'e']])
    expect(run.finished).toBe(true)
    expect(runTitle(run)).toBe('智能续写 · 3 轮 · +300 字')
  })
  it('没收尾的跑：最后一轮没有「之后」', () => {
    const [run] = groupRuns(REVS.filter((r) => r.id !== 'e'))
    expect(run.finished).toBe(false)
    expect(run.rounds[2].after).toBeNull()
    expect(runTitle(run)).toContain('还没收尾')
  })
  it('跟跑无关的版本不算；两次跑各成一组、新的在前', () => {
    const more = [rev('bE', 'run_end', 1, 'runB', '2026-09-19T11:01:00'), rev('b1', 'round', 1, 'runB', '2026-09-19T11:00:00'), ...REVS]
    expect(groupRuns(more).map((r) => r.run_id)).toEqual(['runB', 'runA'])
    expect(groupRuns(REVS.filter((r) => !r.run_id))).toEqual([])
  })
  it('历史面板：同一次跑折成一组，放在它最新那一行的位置，其余照旧', () => {
    expect(historyGroups(REVS).map((g) => (g.kind === 'run' ? `run:${g.run_id}×${g.revs.length}` : g.rev.id))).toEqual(['run:runA×4', 'm', 'a'])
    expect(revisionLabel({ reason: 'round', round_no: 2 })).toBe('第 2 轮之前')
    expect(revisionLabel({ reason: 'run_end', round_no: 3 })).toBe('跑完（第 3 轮之后）')
    expect(revisionLabel({ reason: 'harness', round_no: 0 })).toBe('AI 交稿')
  })
})

// 假模型那三轮的形状：第 2 轮改了第 1 轮写的句子、删了半句、再写一段；第 3 轮只追加
const v0 = '正文。'
const v1 = v0 + '\n\n第1轮写的第一句。\n\n第1轮多余的半句。'
const v2 = v0 + '\n\n第1轮改过的第一句。\n\n第2轮写的第一句。'
const v3 = v2 + '\n\n第3轮写的第一句。'

describe('只撤这一轮（editor/undoRound，痛点 8）', () => {
  it('撤最后一轮：正文精确回到它之前', () => {
    const r = undoRound(v2, v3, v3)
    expect(r.text).toBe(v2)
    expect([r.undone, r.total, r.conflicts]).toEqual([1, 1, []])
  })
  it('撤中间那轮：它改的还原，后面那轮留着', () => {
    const r = undoRound(v1, v2, v3)
    expect(r.text).toBe(v1 + '\n\n第3轮写的第一句。')
    expect(r.conflicts).toEqual([])
    expect(r.undone).toBe(r.total)
  })
  it('第 1 轮写的被第 2 轮改过了：找不到就说清楚，正文不动', () => {
    const r = undoRound(v0, v1, v3)
    expect(r.text).toBe(v3)
    expect(r.undone).toBe(0)
    expect(r.conflicts.length).toBeGreaterThan(0)
    expect(r.conflicts[0]).toMatch(/找不到了/)
  })
  it('用户在那一轮写的段里改了几个字：整段找不到就不猜，报冲突（宁可留着让用户自己删）', () => {
    const edited = v3.replace('第3轮写的第一句。', '第3轮写的第一句（我补了一句）。')
    const r = undoRound(v2, v3, edited)
    expect([r.undone, r.conflicts.length, r.total]).toEqual([0, 1, 1])
    expect(r.text).toBe(edited)
  })
  it('用户改的是那一轮**前面**的正文（24 字以内）：上下文缩短到 12 字还能定位，撤得掉', () => {
    const base = '一二三四五六七八九十甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉'          // 30 字
    const after = base + '\n\n第3轮写的第一句。'
    const touched = base.slice(0, 8) + '玖' + base.slice(9)                                 // 改了倒数第 22 个字：24 字上下文对不上，12 字对得上
    const r = undoRound(base, after, touched + '\n\n第3轮写的第一句。')
    expect(r.text).toBe(touched)
    expect([r.undone, r.conflicts]).toEqual([1, []])
  })
  it('同一段在现在的正文里出现了两次：不知道撤哪一处，报冲突', () => {
    const r = undoRound('甲', '甲X', '甲X甲X')
    expect(r.undone).toBe(0)
    expect(r.conflicts[0]).toMatch(/不止一处/)
  })
  it('纯删除也能补回来（靠前后文定位）', () => {
    const before = '一二三四五六七八九十。删掉的这句。甲乙丙丁戊己庚辛。'
    const after = '一二三四五六七八九十。甲乙丙丁戊己庚辛。'
    const r = undoRound(before, after, after + '\n\n后面又写了一段。')
    expect(r.text).toBe(before + '\n\n后面又写了一段。')
  })
})

const f = (id: string, when: string, text = id): Fact => ({ id, text, when, kind: 'fact', sources: [] })

describe('⌥ 悬停卡的内容（util/traceCard，§3.3 场景 B）', () => {
  it('按日期排：第一次 / 最近 / 相关两条（按召回顺序）', () => {
    const s = summarizeTrace([f('c', '2026-03-10'), f('a', '2026-02-24'), f('d', '2026-04-10'), f('b', '2026-03-01'), f('e', '')])
    expect([s.first?.id, s.last?.id, s.related.map((x) => x.id), s.count]).toEqual(['a', 'd', ['c', 'b'], 5])
  })
  it('只有一条：没有「最近」；没有日期的也能当相关', () => {
    const s = summarizeTrace([f('a', '2026-02-24')])
    expect([s.first?.id, s.last, s.related]).toEqual(['a', null, []])
    const t = summarizeTrace([f('x', ''), f('y', '')])
    expect([t.first, t.last, t.related.map((x) => x.id)]).toEqual([null, null, ['x', 'y']])
  })
  it('没结果时说清为什么，不留空白', () => {
    expect(emptyReason('众筹')).toBe('知识库里没有「众筹」。')
    expect(emptyReason('的', 'no_terms')).toMatch(/太短或太泛/)
    expect(emptyReason('众筹', 'weak', true)).toMatch(/知识库还是空的/)
  })
})

describe('⌥ 悬停：词怎么切（editor/altHover）', () => {
  it('中文按分词器切词，不是整句；词典里没有的词（众筹 → 众 | 筹）把相邻单字连成串、带上停的是哪个字', () => {
    const line = '版本时间要服从众筹等外部节点；3月12号上线 EVT 大节点。'
    expect(phraseAt(line, line.indexOf('服从'))).toEqual({ from: 5, to: 7, text: '服从' })          // 词典认识：就是这个词
    const at = line.indexOf('众筹')
    // 众 / 筹 / 等 各是单字段，「外部」是词 → 串到「等」为止；focus 记的是鼠标停的字
    expect(phraseAt(line, at)).toEqual({ from: at, to: at + 3, text: '众筹等', focus: 0 })
    expect(phraseAt(line, at + 1)).toEqual({ from: at, to: at + 3, text: '众筹等', focus: 1 })
    expect(phraseAt(line, line.indexOf('EVT') + 1)?.text).toBe('EVT')
    expect(phraseAt(line, line.indexOf('；'))).toBeNull()               // 标点上没有词
    expect(phraseAt(line, line.indexOf(' '))).toBeNull()                // 空白上没有词
    expect(phraseAt(line, line.length)).toBeNull()
    expect(phraseAt('甲乙丙丁戊己庚辛壬癸', 4)?.text.length).toBe(6)     // 单字串封顶 MAX_RUN
  })
  it('单字串交给知识库认：盖住那个字的两字窗口（左、右）先查，整串最后（candidates）', () => {
    expect(candidates('众筹等', 0)).toEqual(['众筹', '众筹等'])
    expect(candidates('众筹等', 1)).toEqual(['众筹', '筹等', '众筹等'])
    expect(candidates('众筹等', 2)).toEqual(['筹等', '众筹等'])
    expect(candidates('众筹', 1)).toEqual(['众筹'])                     // 整串就是两字：只查一次
    expect(candidates('众', 0)).toEqual(['众'])
  })
  it('文档位置：选区优先；光标停在词尾也算这个词', () => {
    const doc = '第一行 服从 页面\n第二行'
    const mk = (anchor: number, head = anchor) => ({ state: EditorState.create({ doc, selection: { anchor, head } }) }) as unknown as EditorView
    expect(phraseAtPos(mk(4), 4)?.text).toBe('服从')
    expect(phraseAtPos(mk(6), 6)?.text).toBe('服从')                    // 词尾
    expect(phraseAtPos(mk(4, 9), 5)?.text).toBe('服从 页面')             // 选区
    expect(phraseAtPos(mk(4, 9), 10)?.text).toBe('第二')                // 选区外照样按词（第二 | 行）
    expect(phraseAtPos(mk(0, 12), 5)?.text).toBe('服从')                // 跨行的选区不算，退回光标处的词
  })
  it('门槛 400ms；快捷键表里查得到 ⌥悬停 / ⌥↩；编辑器接了、App 画卡', () => {
    expect(HOVER_MS).toBe(400)
    expect(shortcutsSrc).toContain("keys: '⌥悬停 / ⌥↩'")
    expect(editorSrc).toContain('altHover((phrase, anchor, reason, range)')
    expect(appSrc).toContain('onAltHover={(phrase, anchor, reason, range)')
    expect(appSrc).toContain('<TraceCard card={traceCard}')
  })
})

describe('界面：烧之后「改动」页签还在、每轮两个按钮', () => {
  it('ChangeLayersPanel：没有活着的层也列烧过的轮次；没收尾的轮「只撤」禁用并说为什么', () => {
    const runs = groupRuns(REVS.filter((r) => r.id !== 'e'))
    const html = renderToStaticMarkup(createElement(ChangeLayersPanel, { viewRef: createRef<EditorView | null>(), tick: 0, runs }))
    expect(html).toContain('现在没有待处置的改动')
    expect(html.match(/class="card run-round"/g)?.length).toBe(3)
    expect(html).toContain('第 3 轮')
    expect(html.match(/>只撤这一轮</g)?.length).toBe(3)
    expect(html.match(/>回到这轮之前</g)?.length).toBe(3)
    expect(html).toContain('这一轮还没收尾，没有「之后」可比')
    // 第 3 轮没有「之后」：它的「只撤这一轮」是禁用的（并说了为什么），前两轮的不禁用；「回到这轮之前」三个都能按
    expect(html.match(/<button[^>]*disabled=""[^>]*>只撤这一轮<\/button>/g)?.length).toBe(1)
    expect(html.match(/<button[^>]*disabled=""[^>]*>回到这轮之前<\/button>/g)).toBeNull()
  })
  it('App：有烧过的跑时「改动」页签留着（hasContent 不只看 pendingDiff）', () => {
    // P43 #1 起这一格收进了 `changesTabHasContent`（页签的判据要跟面板画什么是同一份）。
    // **守的性质一个字没变**：`runs` 那一格还在里面，有烧过的跑时页签照样留着。
    const at = appSrc.indexOf("{ id: 'changes', title: '改动'")
    expect(at).toBeGreaterThan(0)
    const block = appSrc.slice(at, at + 700)
    expect(block).toContain('hasContent: changesTabHasContent({')
    expect(block).toContain('runs: runs.length')
    expect(appSrc).toContain('onRestoreBefore={(r) => void restoreBeforeRound(r)} onUndoRound={(r) => void undoRoundOnly(r)}')
  })
})
