// @vitest-environment jsdom
/**
 * 行内出处的识别：哪些 `[...]` 算引用，哪些不算。
 *
 * 认错的代价是双向的：认少了，用户看不到出处（判据 2 白做）；认多了，
 * 正文里普通的方括号会变成一堆点不开的假链接，而且每个都会去打一次网络。
 */
import { markdown } from '@codemirror/lang-markdown'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { describe, expect, it, vi } from 'vitest'
import { citeChipLabel, factCite } from '../factCite'

/** 跟 factCite.ts 里那条保持一致——形状写死是为了不把普通方括号误标。 */
const CITE = /\[([A-Za-z][A-Za-z0-9_-]*-\d+-[0-9A-Fa-f]+)\]/g

function ids(text: string): string[] {
  CITE.lastIndex = 0
  return [...text.matchAll(CITE)].map((m) => m[1])
}

describe('出处标记的形状', () => {
  it('认出真实的 fact id', () => {
    // 真实形状取自 KITE：<用户>-<数字>-<十六进制>
    expect(ids('据 [terrence-1872-5F8] 所述')).toEqual(['terrence-1872-5F8'])
    expect(ids('[terrence-1439-0F3] 和 [terrence-1814-27F1]'))
      .toEqual(['terrence-1439-0F3', 'terrence-1814-27F1'])
  })

  it('带连字符的用户名也认', () => {
    expect(ids('[terrence-rewrite-12-AB]')).toEqual(['terrence-rewrite-12-AB'])
  })

  it('普通方括号不算引用', () => {
    // 认多了的代价：正文里每个方括号都变成点不开的假链接，还各打一次网络
    expect(ids('这是 [一个注释] 和 [TODO] 还有 [1]')).toEqual([])
    expect(ids('markdown 链接 [标题](http://x)')).toEqual([])
  })

  it('缺了任何一段都不算', () => {
    expect(ids('[terrence-1872]')).toEqual([])      // 少十六进制那段
    expect(ids('[terrence-5F8]')).toEqual([])       // 少数字那段
    // 只有两段也不算：真实 fact id 是三段（用户-数字-十六进制）。少一段就
    // 放行的话，`[2026-06]` 这种日期会被当成出处。
    expect(ids('[1872-5F8]')).toEqual([])
    expect(ids('会议在 [2026-06] 举行')).toEqual([])
  })

  it('一行里出现多次都要认', () => {
    const line = '甲[a-1-A]乙[b-2-B]丙[c-3-C]'
    expect(ids(line)).toHaveLength(3)
  })
})


it('方括号里的日期不是引用（01 是合法十六进制，旧正则会误认）', () => {
  expect(ids('[2026-01-01] 开会，见 [terrence-1872-5F8]')).toEqual(['terrence-1872-5F8'])
})

function editor(doc: string, cursor = doc.length) {
  const parent = document.createElement('div')
  document.body.appendChild(parent)
  return new EditorView({
    parent,
    state: EditorState.create({
      doc,
      selection: { anchor: cursor },
      extensions: [markdown(), factCite(() => Promise.resolve(null))],
    }),
  })
}

describe('出处在编辑器里的呈现', () => {
  it('隐藏机器主键但保留底层文本，光标进入时可编辑原文', () => {
    const raw = '[terrence-390-29F]'
    const view = editor(`结论来自 ${raw}。`)
    expect(citeChipLabel('terrence-390-29F')).toBe('来源 · 29F')
    expect(view.dom.querySelector('.cm-fact-cite-chip')?.textContent).toBe('来源 · 29F')
    expect(view.state.doc.toString()).toContain(raw)
    expect(view.dom.textContent).not.toContain('terrence-390-29F')

    const from = view.state.doc.toString().indexOf(raw)
    view.dispatch({ selection: { anchor: from + 2 } })
    expect(view.dom.querySelector('.cm-fact-cite-chip')).toBeNull()
    expect(view.dom.textContent).toContain(raw)
    view.destroy()
  })

  it('点来源标签打开对应事实，而不是把机器编号塞进交互文案', () => {
    const view = editor('结论 [terrence-390-29F]。')
    const opened = vi.fn()
    window.addEventListener('open-virtual', opened)
    view.dom.querySelector<HTMLElement>('.cm-fact-cite-chip')
      ?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    expect(opened).toHaveBeenCalledTimes(1)
    expect((opened.mock.calls[0][0] as CustomEvent).detail).toBe('kb:fact:terrence-390-29F')
    window.removeEventListener('open-virtual', opened)
    view.destroy()
  })

  it('代码里的同形文本不变成来源标签', () => {
    const view = editor('`[terrence-390-29F]`\n\n正文 [terrence-391-2A]。')
    expect(view.dom.querySelectorAll('.cm-fact-cite-chip')).toHaveLength(1)
    expect(view.dom.querySelector('.cm-fact-cite-chip')?.textContent).toBe('来源 · 2A')
    view.destroy()
  })
})
