import { describe, expect, it } from 'vitest'
import { factsLabel, isKbVirtual, isKnownVirtual, previewLine, syncVirtualTab, VIRTUAL_LABELS } from '../../util/virtual'

describe('virtual 页的纯规则', () => {
  it('factsLabel：带筛选的事实表叫「事实表 · 值」', () => {
    expect(factsLabel('kb:facts')).toBe('事实表')
    expect(factsLabel('kb:facts?topic=work')).toBe('事实表 · work')
    expect(factsLabel('kb:facts?kind=plan&who=speaker%20b')).toBe('事实表 · plan · speaker b')
    expect(factsLabel('kb:topic:work')).toBeUndefined()
  })
  it('isKnownVirtual：固定页 / 知识库节点 / 带查询串的事实表 / app:*', () => {
    for (const id of Object.keys(VIRTUAL_LABELS)) expect(isKnownVirtual(id)).toBe(true)
    for (const id of ['kb:topic:work', 'kb:entity:acme', 'kb:facts?topic=work', 'kb:material:u1', 'app:trash']) expect(isKnownVirtual(id)).toBe(true)
    for (const id of ['kb:overview', 'kb:nope:x', 'note:123', '']) expect(isKnownVirtual(id)).toBe(false)
  })
  it('知识库内部只复用一个工作区标签，普通虚拟页仍各自开标签', () => {
    const old = [
      { id: 'note', noteId: 'n1', title: '笔记' },
      { id: 'kb-a', noteId: 'kb', title: '知识库' },
      { id: 'kb-b', noteId: 'kb:fact:f1', title: '旧事实' },
      { id: 'settings', noteId: 'app:settings', title: '设置' },
    ]
    const moved = syncVirtualTab(old, { id: 'new', noteId: 'kb:graph', title: '主题地图' }, 'kb-b')
    expect(moved.filter((t) => isKbVirtual(t.noteId))).toEqual([
      { id: 'kb-b', noteId: 'kb:graph', title: '主题地图' },
    ])
    expect(moved.map((t) => t.id)).toEqual(['note', 'kb-b', 'settings'])

    const withImport = syncVirtualTab(moved, { id: 'import', noteId: 'app:import', title: '导入' }, 'kb-b')
    expect(withImport.map((t) => t.noteId)).toEqual(['n1', 'kb:graph', 'app:settings', 'app:import'])
  })
  it('previewLine：跳过跟标题一样的首行、剥记号、整篇缩进也剥；照后端 _first_body_line', () => {
    expect(previewLine('# 会议纪要 10\n- 第一条', '会议纪要 10')).toBe('第一条')
    // 没标题：显示名就是首行「时间线」，预览给下一行正文
    expect(previewLine('    ## 时间线\n正文', '')).toBe('正文')
    // 图片行 / 代码围栏不算，正文优先于小标题，一行正文都没有才退回小标题
    expect(previewLine('# 题\n![图](/api/assets/a.png)\n```\ncode\n```\n## 小标题\n**重点**句子', '题')).toBe('重点句子')
    expect(previewLine('# 题\n## 只有小标题', '题')).toBe('只有小标题')
    expect(previewLine('', '')).toBe('')
  })
})
