/**
 * 大纲导航面板的标题解析。
 *
 * 围栏代码块里的 `# 注释` 不是标题——Python 和 Shell 的注释正好长这样。
 * 不排除的话面板里会冒出「读取退货工单」这种条目，点一下光标跳进代码块
 * 中间。后端 `app/editor/outline.py` 踩的是同一个坑，而且后果更重：那边
 * 会把带代码块的普通笔记误判成大纲，结构冻死、修订改不动任何标题。
 */
import { describe, expect, it } from 'vitest'

import { parseFallbackAnchors, parseHeadings } from '../../components/DocumentOutline'

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

  // —— P25（P22 #9）：真库 `92d07b760f1e` L23 一行里夹了第二个标题标记
  it('一行里夹着第二个标题标记 → 截断，只留外层那一句', () => {
    const hs = parseHeadings('## 我们该如何克服挑战：### 如何克服挑战：\n')
    expect(hs.map((h) => h.text)).toEqual(['我们该如何克服挑战：'])
    expect(hs[0].level).toBe(2)
    expect(hs[0].pos).toBe(0)
  })
  it('真标题里的 # 不算夹标记（C# / 问题 #3）', () => {
    expect(parseHeadings('## 关于 C# 的笔记\n### 问题 #3 复盘\n').map((h) => h.text))
      .toEqual(['关于 C# 的笔记', '问题 #3 复盘'])
  })
})

// —— P7（P4 #3）：没有 `#` 标题时的退路 ————————————————————————
const 展厅讲解词 = [
  '公司汇报：', '',
  '去年公司稳健发展，营收几乎与2020年的巅峰持平。其中主力是 ICT 基础设施和终端。', '',
  '算力底座：', '',
  '首屏：在计算产业，大家讨论最多的是超节点，华为的 950 超节点用全光互联。', '',
  '案例：', '',
  '2025 年昇腾在国内的新增市场份额达到六成。', '',
  '英伟达对比：', '',
  '单芯片能力非常强大，且 CUDA 生态很成熟。', '',
].join('\n')

describe('parseFallbackAnchors', () => {
  it('短行 + 冒号结尾 ≥ 3 个 → 当伪标题，去掉冒号，位置对', () => {
    const r = parseFallbackAnchors(展厅讲解词)
    expect(r.how).toBe('short')
    expect(r.items.map((h) => h.text)).toEqual(['公司汇报', '算力底座', '案例', '英伟达对比'])
    expect(r.items[1].pos).toBe(展厅讲解词.indexOf('算力底座：'))
  })
  // —— P25（P22 #9）：N1 里「智慧教育」「智慧医疗」「鲲鹏」这种**不带冒号**的短行也是一节
  it('不带冒号的短行也算伪标题；带句号的、列表项、编号条不算', () => {
    const 笔记 = [
      '公司汇报：', '', '一段正文，够长了，随便写点什么凑数。', '',
      '智慧教育', '', '宁夏大学的教室里装了智能助教，能自动生成课后练习。', '',
      '鲲鹏', '', '服务器主板由 OEM 伙伴组装，华为只做主板。', '',
      '山东东营 HG14 海上光伏', '', '全球最大开放式海上光伏项目。', '',
      '双方共建 AI 场景。', '',
      '- 72-1024 卡区间', '',
      '（2） 翻译准确率显著', '',
    ].join('\n')
    const r = parseFallbackAnchors(笔记)
    expect(r.how).toBe('short')
    expect(r.items.map((h) => h.text)).toEqual(['公司汇报', '智慧教育', '鲲鹏', '山东东营 HG14 海上光伏'])
  })
  it('没有冒号短行 → 按段落列、每段取首句', () => {
    const r = parseFallbackAnchors('第一段讲的是卖房中介的对比。后面还有很多。\n\n第二段讲三类信息：事实、推测、冲突的判断，要分开。\n')
    expect(r.how).toBe('paragraph')
    expect(r.items.map((h) => h.text)).toEqual(['第一段讲的是卖房中介的对比…', '第二段讲三类信息：事实、推测、冲突的判断，要分开…'])
  })
  it('段落前的列表符 / 编号剥掉', () => {
    const r = parseFallbackAnchors('- 第一条内容够长了吧这一段肯定够二十个字了，再补几个字\n\n3. 第三条也够长了这一段要二十个字才行，再补几个字\n')
    expect(r.items.map((h) => h.text)[0].startsWith('第一条')).toBe(true)
    expect(r.items.map((h) => h.text)[1].startsWith('第三条')).toBe(true)
  })
  it('代码块里的行不算段落', () => {
    const r = parseFallbackAnchors('```\n# 看着像标题：\nx = 1\n```\n\n一段正文，够二十个字了吧应该是够了，再补几个字。\n\n再来一段正文，同样够二十个字了吧，再补几个字。\n')
    expect(r.how).toBe('paragraph')
    expect(r.items.every((h) => !h.text.includes('看着像'))).toBe(true)
  })
  it('太短的笔记 → none', () => {
    expect(parseFallbackAnchors('一句话。').how).toBe('none')
  })
})
