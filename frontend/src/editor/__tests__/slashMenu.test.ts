// @vitest-environment jsdom
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { describe, expect, it } from 'vitest'

import { BLOCK_MODES } from '../../api'
import { SLASH_ITEMS, filtered } from '../slashMenu'

/**
 * 第 704 轮把常驻的 Markdown 工具条收起来了，理由之一是「`/` 菜单还在」——
 * 而当时这个菜单里**一条排版命令都没有**（第 705 轮实拍才发现）。
 * 这组用例钉的就是这件事：**排版这一组必须真的能用**。
 */
describe('/ 菜单的排版组', () => {
  const layout = SLASH_ITEMS.filter((i) => i.group === '排版')

  it('存在，而且每一条都带一个能就地执行的命令', () => {
    expect(layout.length).toBeGreaterThanOrEqual(8)
    for (const it of layout) expect(typeof it.cmd).toBe('function')
  })

  it('AI 组一条 cmd 都没有（它们要走网络，得交给上层）', () => {
    for (const it of SLASH_ITEMS.filter((i) => i.group === 'AI')) expect(it.cmd).toBeUndefined()
  })

  it('每一条都有分组（渲染时靠它插小标题，漏了就串组）', () => {
    for (const it of SLASH_ITEMS) expect(it.group).toBeTruthy()
  })

  /** `App.onSlash` 的分流：needsPrompt → 弹输入框；table-image / audio → 选文件；
   *  voice → 录音；**其余直接当 BlockMode 发给后端**（一句不查的强转）。
   *  所以每一项都必须落在这几类里的某一类，否则就是「点了没反应」或者
   *  「发了个后端不认识的 mode」。 */
  it('每一项都有人接（不然就是点了没反应）', () => {
    const handled = new Set(['table-image', 'audio', 'voice'])
    for (const it of SLASH_ITEMS) {
      if (it.cmd || it.needsPrompt || handled.has(it.key)) continue
      expect(BLOCK_MODES as readonly string[]).toContain(it.key)
    }
  })

  it('打「列表」筛出三条列表命令，筛不出 AI 的', () => {
    const hit = filtered('列表')
    expect(hit.map((i) => i.key).sort()).toEqual(['ol', 'todo', 'ul'])
  })

  it('打「标题」筛出三级标题', () => {
    expect(filtered('标题').map((i) => i.key)).toEqual(['h1', 'h2', 'h3'])
  })

  /** 真跑一次命令：不是「有个函数」，是「跑完文档真的变了」。 */
  it('任务列表命令真的把当前行变成 - [ ]', () => {
    const view = new EditorView({ state: EditorState.create({ doc: '买电池' }) })
    view.dispatch({ selection: { anchor: 3 } })
    SLASH_ITEMS.find((i) => i.key === 'todo')!.cmd!(view)
    expect(view.state.doc.toString()).toBe('- [ ] 买电池')
    view.destroy()
  })

  it('二级标题命令真的加上 ## ', () => {
    const view = new EditorView({ state: EditorState.create({ doc: '硬件' }) })
    view.dispatch({ selection: { anchor: 2 } })
    SLASH_ITEMS.find((i) => i.key === 'h2')!.cmd!(view)
    expect(view.state.doc.toString()).toBe('## 硬件')
    view.destroy()
  })
})
