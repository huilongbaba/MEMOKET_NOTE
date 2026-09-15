import { EditorView } from '@codemirror/view'
import type { RefObject } from 'react'

import { slidePages } from '../util/slidePages'

/**
 * 幻灯片预览（痛点 6，docs/slides-plan.md）。
 *
 * **纯 CSS 画 16:9 的缩略图，不引 Marp**——那是 600KB+ 的依赖，只为预览不值。
 * 这里要回答的问题只有三个：几页、每页讲什么、**哪一页没有依据**。最后一个
 * 是这个产品跟通用 PPT 工具的根本差别，所以它是唯一一个用颜色标出来的东西。
 *
 * 点一页跳到正文里那一页的位置：幻灯片就是一篇 markdown 笔记，改一页就是
 * 改一段字——不做「在预览里编辑」那套（两份内容的同步没有好答案）。
 */
export default function SlidesPanel({ content, viewRef }: {
  content: string
  viewRef: RefObject<EditorView | null>
}) {
  const pages = slidePages(content)
  if (!pages.length) {
    return <p className="muted" style={{ fontSize: 'var(--t-sm)' }}>这篇还不是幻灯片。在「⋯ → 做成幻灯片」里生成一份。</p>
  }
  const bare = pages.filter((p) => !p.cited).length

  const goto = (at: number) => {
    const v = viewRef.current
    if (!v) return
    const pos = Math.min(at, v.state.doc.length)
    v.dispatch({ selection: { anchor: pos }, effects: EditorView.scrollIntoView(pos, { y: 'start' }) })
    v.focus()
  }

  return (
    <div>
      <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: '0 0 8px' }}>
        {pages.length} 页
        {bare > 0 && <>　·　<b className="warnish">{bare} 页没有依据</b></>}
        　·　点一页跳到正文
      </p>
      <div className="slide-grid">
        {pages.map((p, i) => (
          <button key={i} className={'slide-thumb' + (p.cited ? '' : ' bare')} onClick={() => goto(p.at)}
                  title={p.cited ? '这一页带着引用编号' : '这一页没有任何依据'}>
            <span className="slide-no">{i + 1}</span>
            <b>{p.title || '（没有标题）'}</b>
            <span className="slide-body">{p.body.replace(/^[-*+]\s+/gm, '· ').slice(0, 120)}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
