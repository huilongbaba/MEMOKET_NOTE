/** P41 的「用户看得见的前后对比」：把两块真组件渲染成静态 HTML，读它上面**真出现的字**。
 *
 * 这一批没起打包壳（改的是后端那句话 + 两块面板的一段话和两个钮），
 * 但「面板上到底写了什么」不该靠读代码推理——P17 / P35 / P40 反复证明推理不算数。
 * `react-dom/server` 真渲染一遍，把 innerText 打出来，前后各跑一次。
 *
 *     npx tsx scripts/_p41render.tsx
 *
 * **这是量具，不是闸**：它不进 `npm test`（下划线开头，`check-*` 的命名也躲开了）。
 */
import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import ChangeLayersPanel from '../src/components/ChangeLayersPanel'
import VerifyPanel from '../src/components/VerifyPanel'

const text = (html: string) =>
  html.replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim()

const PASSAGE = '3月12号上线，众筹页面的文案定稿了，接下来要写验收标准。'

console.log('=== #3 「校验结果」·修之前（没有「说的是哪一段」那一行） ===')
console.log(text(renderToStaticMarkup(h(VerifyPanel, {
  findings: [], checked: 6, unparsed: true, onClose: () => {},
}))))

console.log('\n=== #3 「校验结果」·修之后（卡上写清说的是哪一段） ===')
console.log(text(renderToStaticMarkup(h(VerifyPanel, {
  findings: [], checked: 6, unparsed: true, passage: PASSAGE, onClose: () => {},
}))))

console.log('\n=== #3 「校验结果」·修之后（那一段已经不在正文里了） ===')
console.log(text(renderToStaticMarkup(h(VerifyPanel, {
  findings: [], checked: 6, unparsed: true, passage: PASSAGE, gone: true, onClose: () => {},
}))))

const viewRef = { current: null }
console.log('\n=== #5 ② 「改动」面板·修之前（放不回来的层只有一句 toast，面板上什么都没有） ===')
console.log(text(renderToStaticMarkup(h(ChangeLayersPanel, { viewRef, tick: 0 } as never))))

console.log('\n=== #5 ② 「改动」面板·修之后（每一层一张卡，两个出路） ===')
console.log(text(renderToStaticMarkup(h(ChangeLayersPanel, {
  viewRef, tick: 0,
  stuck: [{ id: 'L1', label: '智能续写', why: ['「先把叙事和体感分开看」', '「再决定这个动效」'] }],
  onRecomputeStuck: () => {}, onDropStuck: () => {},
} as never))))
