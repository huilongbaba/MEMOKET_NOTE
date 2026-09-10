/**
 * 大纲导航面板的标题解析。
 *
 * 围栏代码块里的 `# 注释` 不是标题——Python 和 Shell 的注释正好长这样。
 * 不排除的话面板里会冒出「读取退货工单」这种条目，点一下光标跳进代码块
 * 中间。后端 `app/editor/outline.py` 踩的是同一个坑，而且后果更重：那边
 * 会把带代码块的普通笔记误判成大纲，结构冻死、修订改不动任何标题。
 */
import { describe, expect, it } from 'vitest'

import { parseHeadings } from '../../components/DocumentOutline'

const 带代码的笔记 = [
  '## 背景', '', '一段正文。', '',
  '## 脚本', '',
  '```python',
  '# 读取退货工单',
  'import pandas as pd',
  '# 按原因分组统计',
  'df.groupby("reason").size()',
  '```', '',
  '## 结论', '', '收个尾。', '',
].join('\n')

describe('parseHeadings', () => {
  it('代码块里的注释不算标题', () => {
    expect(parseHeadings(带代码的笔记).map((h) => h.text))
      .toEqual(['背景', '脚本', '结论'])
  })

  it('真标题的层级和位置都对', () => {
    const hs = parseHeadings('# 一级\n\n正文\n\n### 三级\n')
    expect(hs.map((h) => h.level)).toEqual([1, 3])
    expect(hs[1].pos).toBe('# 一级\n\n正文\n\n'.length)
  })

  it('围栏没闭合时后面一律当代码', () => {
    expect(parseHeadings('## 真标题\n\n```\n# 看着像标题\n').map((h) => h.text))
      .toEqual(['真标题'])
  })

  it('波浪线围栏也算', () => {
    expect(parseHeadings('## 真标题\n\n~~~\n# 不是标题\n~~~\n').map((h) => h.text))
      .toEqual(['真标题'])
  })

  it('没有代码块时照常工作', () => {
    expect(parseHeadings('# 甲\n## 乙\n### 丙').map((h) => h.text))
      .toEqual(['甲', '乙', '丙'])
  })
})
