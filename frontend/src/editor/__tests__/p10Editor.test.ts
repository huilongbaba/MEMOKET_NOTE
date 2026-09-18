// @vitest-environment jsdom
/**
 * P10（产品就绪计划 §2 C3 编辑器基本功 + 三个小毛病，`docs/TRACELOG-product.md` P10 节）：
 *
 *   C3-1 快捷键：空的列表项 / 任务项 / 引用行上 Enter 一次退出（`editor/listExit`）；⌘/ 不再被 App 的 toggle 抵消
 *   C3-2 撤销：续写那一段是一个撤销单位（`editor/undoUnit`），流式停顿 >500ms 也是一次 ⌘Z——P13 #5 起跟智能续写
 *        同一套 `aiSyncSpec`（只读时落地的每一片并进同一条），P10 的 `sealAsOneUndo` 删了
 *   C3-3 粘贴：HTML → markdown（`editor/htmlPaste`），VS Code 那种只有 span 的 HTML 不转
 *   C3-5 长文：圆点按段落文本缓存（`marginMemory.splitCached`），改一段只问一段
 *   小毛病：关系卡的边界是正文栏（`util/cardPlacement`）；缺依据的灰点改空心圈——样式在 `scripts/check-margin-dots.mts` 钉着（vitest 读不到 .css）
 */
import { describe, expect, it } from 'vitest'
import { EditorState, Transaction } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { history, undo, redo } from '@codemirror/commands'
import { markdown } from '@codemirror/lang-markdown'
import { GFM } from '@lezer/markdown'

import { EMPTY_ITEM, exitEmptyItem } from '../listExit'
import { aiSyncSpec } from '../undoUnit'
import { htmlToMarkdown, shouldConvertHtml } from '../htmlPaste'
import { splitCached, type MarginVerdict } from '../marginMemory'
import { placeCard } from '../../util/cardPlacement'
import appSrc from '../../App.tsx?raw'

function mkView(doc: string, cursor = doc.length): EditorView {
  const parent = document.createElement('div')
  document.body.appendChild(parent)
  return new EditorView({ state: EditorState.create({ doc, selection: { anchor: cursor }, extensions: [history(), markdown({ extensions: [GFM] })] }), parent })
}

describe('C3-1 空项 Enter 一次退出（listExit）', () => {
  it.each([
    ['- ', ''], ['* ', ''], ['1. ', ''], ['1) ', ''], ['- [ ] ', ''], ['- [x] ', ''], ['> ', ''],
    ['  - ', '- '],                    // 嵌套的先退一级
    ['    1. ', '  1. '],
  ])('%j → %j', (line, want) => {
    const v = mkView(`第一行\n${line}`)
    expect(exitEmptyItem(v)).toBe(true)
    expect(v.state.doc.toString()).toBe(`第一行\n${want}`)
    expect(v.state.selection.main.head).toBe(v.state.doc.length)
    v.destroy()
  })
  it('不空的项 / 光标不在行尾 / 有选区：不管，交给 lang-markdown 续项', () => {
    for (const [doc, cursor] of [['- 项目', 4], ['- 项目', 2], ['- ', 1], ['普通一行', 4]] as [string, number][]) {
      const v = mkView(doc, cursor)
      expect(exitEmptyItem(v)).toBe(false)
      expect(v.state.doc.toString()).toBe(doc)
      v.destroy()
    }
    expect(EMPTY_ITEM.test('- 项目')).toBe(false)
    expect(EMPTY_ITEM.test('-项目')).toBe(false)
  })
})

describe('C3-2 续写是一个撤销单位（undoUnit，P13 #5 起跟智能续写同一套 aiSyncSpec）', () => {
  it('四片隔 >500ms 流进来（只读时落地、带 aiSyncSpec）→ 一次 undo 全撤、redo 全回，用户自己的字不动', () => {
    const v = mkView('用户写的。')
    let t = 1000
    const land = (piece: string, fresh: boolean) => {
      const spec = aiSyncSpec(fresh)
      v.dispatch({ changes: { from: v.state.doc.length, insert: piece }, userEvent: spec.userEvent, annotations: [...(spec.annotations as never[] ?? []), Transaction.time.of(t)] })
    }
    land('第一片', true)
    for (const piece of ['第二片', '第三片', '第四片']) { t += 900; land(piece, false) }
    const full = '第一片第二片第三片第四片'
    expect(v.state.doc.toString()).toBe('用户写的。' + full)
    undo(v)
    expect(v.state.doc.toString()).toBe('用户写的。')
    redo(v)
    expect(v.state.doc.toString()).toBe('用户写的。' + full)
    v.destroy()
  })
  it('修前的形状：片段按默认记历史，⌘Z 一次只撤最后一片——钉住为什么要 compose 并组', () => {
    const v = mkView('用户写的。')
    let t = 1000
    for (const piece of ['第一片', '第二片', '第三片', '第四片']) { t += 900; v.dispatch({ changes: { from: v.state.doc.length, insert: piece }, annotations: Transaction.time.of(t) }) }
    undo(v)
    expect(v.state.doc.toString()).toBe('用户写的。第一片第二片第三片')
    v.destroy()
  })
})

describe('C3-3 粘贴 HTML → markdown（htmlPaste）', () => {
  it('网页那种：标题 / 粗斜 / 链接 / 列表 / 段落', () => {
    const md = htmlToMarkdown('<meta charset="utf-8"><h2>季度目标</h2><p>这是 <strong>粗体</strong> 和 <em>斜体</em>，还有 <a href="https://example.com/x">一个链接</a>。</p><ul><li>第一条</li><li>第二条</li></ul><p>结尾一段</p>')
    expect(md).toBe('## 季度目标\n\n这是 **粗体** 和 *斜体*，还有 [一个链接](https://example.com/x)。\n\n- 第一条\n- 第二条\n\n结尾一段')
  })
  it('有序列表 start / 嵌套 / 任务框 / 引用 / 代码块 / 分隔线 / 删除线 / 行内代码 / 图片', () => {
    expect(htmlToMarkdown('<ol start="3"><li>三<ul><li>子项</li></ul></li><li>四</li></ol>')).toBe('3. 三\n  - 子项\n4. 四')
    expect(htmlToMarkdown('<ul><li><input type="checkbox" checked> 做完</li><li><input type="checkbox"> 没做</li></ul>')).toBe('- [x] 做完\n- [ ] 没做')
    expect(htmlToMarkdown('<blockquote><p>一句</p><p>两句</p></blockquote>')).toBe('> 一句\n>\n> 两句')
    expect(htmlToMarkdown('<pre><code class="language-py">print(1)\n</code></pre>')).toBe('```py\nprint(1)\n```')
    expect(htmlToMarkdown('<p>a</p><hr><p><s>删</s> <code>x</code> <img src="/a.png" alt="图"></p>')).toBe('a\n\n---\n\n~~删~~ `x` ![图](/a.png)')
  })
  it('表格 → GFM，格里的竖线转义', () => {
    expect(htmlToMarkdown('<table><tr><th>名</th><th>值</th></tr><tr><td>a|b</td><td>1</td></tr></table>'))
      .toBe('| 名 | 值 |\n| --- | --- |\n| a\\|b | 1 |')
  })
  it('Google Docs 的 <b style="font-weight:normal"> 不是粗体；链接文字就是地址的给裸地址', () => {
    expect(htmlToMarkdown('<b style="font-weight:normal"><p>正文</p></b>')).toBe('正文')
    expect(htmlToMarkdown('<p><a href="https://a.b/">https://a.b/</a></p>')).toBe('https://a.b/')
  })
  it('什么时候不转：没 html、只有 span 的代码编辑器 HTML、转出来跟 plain 只差空白', () => {
    expect(shouldConvertHtml('', 'x')).toBe(false)
    expect(shouldConvertHtml('<div style="color:#d4d4d4"><span style="color:#569cd6">const</span> x = 1</div>', 'const x = 1')).toBe(false)
    expect(shouldConvertHtml('<p>一段</p><p>两段</p>', '一段\n两段')).toBe(false)
    expect(shouldConvertHtml('<ul><li>a</li><li>b</li></ul>', '- a\n- b')).toBe(false)   // Typora 那种：plain 已经是 markdown，别转两遍
    expect(shouldConvertHtml('<p><b>粗</b>字</p>', '粗字')).toBe(true)
  })
})

describe('C3-5 圆点按段落文本缓存（splitCached）', () => {
  it('没变的段用缓存（带新行号），没见过的去问；判「没关系」的也缓存、不再问', () => {
    const cache = new Map<string, MarginVerdict>()
    cache.set('A 段 2024', { relation: 'unsupported', say: '缺依据' })
    cache.set('B 段 3月', null)
    const { hits, misses } = splitCached([{ text: 'A 段 2024', line: 7 }, { text: 'B 段 3月', line: 12 }, { text: 'C 新段 5 个', line: 20 }], cache)
    expect(hits).toEqual([{ relation: 'unsupported', say: '缺依据', line: 7 }])
    expect(misses).toEqual([{ text: 'C 新段 5 个', line: 20 }])
  })
})

describe('小毛病：关系卡的边界是正文栏（cardPlacement）', () => {
  const pane = { left: 300, top: 0, right: 1000, bottom: 900, width: 700, height: 900 }
  it('右边放得下就贴右边', () => {
    const p = placeCard({ left: 500, top: 200, right: 509, bottom: 209, width: 9, height: 9 }, pane, 160, 900)
    expect(p.side).toBe('right'); expect(p.left).toBe(519); expect(p.width).toBe(340)
  })
  it('放不下（P9 那种：圆点贴着右栏）就挂到这一行下面、右缘对齐栏的右缘，绝不伸出正文栏', () => {
    const p = placeCard({ left: 980, top: 200, right: 989, bottom: 209, width: 9, height: 9 }, pane, 160, 900)
    expect(p.side).toBe('below'); expect(p.top).toBe(215)
    expect(p.left + p.width).toBeLessThanOrEqual(pane.right - 8)
    expect(p.left).toBeGreaterThanOrEqual(pane.left + 8)
  })
  it('下面也放不下就挂上面；栏比卡窄就缩', () => {
    const p = placeCard({ left: 980, top: 850, right: 989, bottom: 859, width: 9, height: 9 }, pane, 160, 900)
    expect(p.side).toBe('above'); expect(p.top + 160).toBeLessThanOrEqual(850)
    const narrow = placeCard({ left: 560, top: 200, right: 569, bottom: 209, width: 9, height: 9 }, { ...pane, right: 600, width: 300 }, 160, 900)
    expect(narrow.width).toBe(284)
  })
})

describe('C3-1 ⌘/ 在编辑器里能打开快捷键表（App 的 toggle 让位给 CM 的 keymap）', () => {
  it('App 的 ⌘/ 分支先看 defaultPrevented；⌘数字切标签不吃 ⌥⌘1/2/3', () => {
    const app = appSrc
    const slash = /else if \(key === '\/'\) \{([^\n]*)\}/.exec(app)?.[1] ?? ''
    expect(slash).toMatch(/defaultPrevented/)
    expect(app).toMatch(/\/\^\[1-9\]\$\/\.test\(key\) && !e\.altKey/)
  })
})
