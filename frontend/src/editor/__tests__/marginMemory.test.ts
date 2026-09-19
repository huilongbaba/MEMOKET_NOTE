import { describe, expect, it } from 'vitest'
import { EditorState } from '@codemirror/state'
import { dotWorthy, marginField, noRecordNote, paragraphsWithLines, setMarginMarks } from '../marginMemory'

describe('边缘记忆', () => {
  it('段落切分给出段首行号', () => {
    expect(paragraphsWithLines('# 标题\n\n第一段\n第二行\n\n\n第二段\n')).toEqual([
      { text: '# 标题', line: 1 }, { text: '第一段\n第二行', line: 3 }, { text: '第二段', line: 7 },
    ])
  })
  it('行号跟着文档改动映射', () => {
    let s = EditorState.create({ doc: 'a\n\nb 420mAh\n', extensions: [marginField] })
    s = s.update({ effects: setMarginMarks.of([{ line: 3, relation: 'conflict', say: 'x' }]) }).state
    s = s.update({ changes: { from: 0, insert: '新的一行\n\n' } }).state
    expect(s.field(marginField)[0].line).toBe(5)
  })
  // —— P25 #4（P22 #8）：N1 一篇 136 个含数字段挂了 106 个灰点，其中 89 段是「库里连沾边的都没有」
  it('缺依据·库里连沾边的都没有 → 不画点；沾边但没带量 → 画', () => {
    expect(dotWorthy({ relation: 'unsupported', why: 'no_record' })).toBe(false)
    expect(dotWorthy({ relation: 'unsupported', why: 'no_value' })).toBe(true)
    // 后端没给 `why`（老版本 / 别的关系）一律照画——**不认得就别少画**
    expect(dotWorthy({ relation: 'unsupported' })).toBe(true)
    for (const r of ['conflict', 'continuation', 'corroborated', 'accumulation', 'merge'] as const) {
      expect(dotWorthy({ relation: r, why: 'no_record' })).toBe(true)
    }
  })
  it('折起来的那一档在面板上说清楚有多少段', () => {
    expect(noRecordNote(89)).toContain('89 段')
    expect(noRecordNote(89)).toContain('右栏会说')
  })
})
