/** `/` 唤起的插入菜单（magic key）。
 *
 * 在行首或空白之后打 `/` 就弹出来，继续打字过滤，↑↓ 选、Enter 确认、Esc 关。
 *
 * **为什么用 CM6 的 tooltip 而不是自己算浮层坐标**：位置要跟着那个 `/` 走，
 * 换行、折行、滚动、缩放都不能跑偏。tooltip 已经把这些都处理好了，自己算
 * 一遍只会在边界上出错（这一点在 roundDiff 的接受/撤回工具条上已经踩过：
 * 第一版靠 CSS 相邻选择器，被 CM6 插在 widget 两侧的 cm-widgetBuffer 破坏，
 * 按钮一个都没出来）。
 */
import { StateEffect, StateField } from '@codemirror/state'
import { EditorView, showTooltip, type Tooltip } from '@codemirror/view'

import {
  heading1Cmd, heading2Cmd, heading3Cmd, quoteCmd,
  bulletListCmd, orderedListCmd, taskListCmd, codeBlockCmd, mermaidCmd, tableCmd,
} from './markdownCommands'

export type SlashItem = {
  key: string
  label: string
  hint: string
  /** boxicons 类名，如 `bx-pen` */
  icon: string
  /** 需要用户再输入一段提示词的（智能分析、按提示词写…） */
  needsPrompt?: boolean
  placeholder?: string
  /** 分组标题。同一组连着排，组变了就插一行小标题。 */
  group: string
  /** 排版类的就地执行：一个 CM6 命令，不走网络、不经 React。
   *  （ 里这批返回 void，不是 CM6 的 Command 签名——
   *  它们是给按钮直接调的，没有「没轮到我」这一说。） */
  cmd?: (view: EditorView) => void
}

/** 菜单项。分两组：先「让 AI 干活」（这个应用的主张），再「排版」。
 *
 * **排版这一组是第 705 轮补的，补的是我自己捅的窟窿**：上一轮把常驻的
 * Markdown 工具条收起来了，理由之一写的是「`/` 斜杠菜单还在」——
 * 结果实拍一看，这个菜单里**一条排版命令都没有**。
 * 原来的注释说「纯插入的在顶部工具栏里」，那条理由随着工具条收起就不成立了：
 * **一个入口的存在理由依赖另一个入口，动了那个就得回来改这个。**
 *
 * 只放**块级**的。加粗 / 斜体是行内的，`/` 在空位置唤起，选不中任何文字，
 * 放进来点了等于什么都没发生（它们在选中弹出的菜单和 ⌘B / ⌘I 里）。 */
export const SLASH_ITEMS: SlashItem[] = [
  { group: 'AI', key: 'prompt', icon: 'bx-pen', label: '用 AI 写', hint: '描述你想写什么，会结合上下文和你的知识库',
    needsPrompt: true, placeholder: '例如：把上面几段总结成三条结论' },
  { group: 'AI', key: 'chart', icon: 'bx-image-add', label: '智能插图', hint: '数据用图表、概念用文生图，自动判断' },
  { group: 'AI', key: 'table', icon: 'bx-table', label: '智能表格', hint: '把上下文整理成表格',
    needsPrompt: true, placeholder: '想整理成什么表？留空则自动判断' },
  { group: 'AI', key: 'table-image', icon: 'bx-image-alt', label: '图片转表格', hint: '传一张图，识别里面的表格' },
  { group: 'AI', key: 'eda', icon: 'bx-bar-chart-alt-2', label: '数据可视化', hint: '把笔记里的表格画成图：分布、占比、对比' },
  { group: 'AI', key: 'analysis', icon: 'bx-calculator', label: '智能数据分析', hint: '问一个数据问题，用工具算出来再回答',
    needsPrompt: true, placeholder: '例如：哪个渠道的单位曝光收入最高？' },
  { group: 'AI', key: 'voice', icon: 'bx-microphone', label: '语音输入', hint: '录一段话，转写成文字插进来' },
  { group: 'AI', key: 'audio', icon: 'bx-headphone', label: '插入音频', hint: '插入音频并自动转写出文字稿' },

  { group: '排版', key: 'h1', icon: 'bx-heading', label: '一级标题', hint: '# 开头', cmd: heading1Cmd },
  { group: '排版', key: 'h2', icon: 'bx-heading', label: '二级标题', hint: '## 开头', cmd: heading2Cmd },
  { group: '排版', key: 'h3', icon: 'bx-heading', label: '三级标题', hint: '### 开头', cmd: heading3Cmd },
  { group: '排版', key: 'ul', icon: 'bx-list-ul', label: '无序列表', hint: '- 开头', cmd: bulletListCmd },
  { group: '排版', key: 'ol', icon: 'bx-list-ol', label: '有序列表', hint: '1. 开头', cmd: orderedListCmd },
  { group: '排版', key: 'todo', icon: 'bx-list-check', label: '任务列表', hint: '- [ ] 开头，能勾', cmd: taskListCmd },
  { group: '排版', key: 'quote', icon: 'bxs-quote-left', label: '引用', hint: '> 开头', cmd: quoteCmd },
  { group: '排版', key: 'code', icon: 'bx-code-block', label: '代码块', hint: '三个反引号围起来', cmd: codeBlockCmd },
  { group: '排版', key: 'grid', icon: 'bx-table', label: '空表格', hint: '插入一个 3 列的空表格', cmd: tableCmd },
  { group: '排版', key: 'flow', icon: 'bx-network-chart', label: '流程图', hint: '插入一个 mermaid 模板', cmd: mermaidCmd },
]

export type SlashState = {
  /** `/` 本身的位置。菜单锚在这里，确认时从这里开始替换掉已输入的过滤词。 */
  from: number
  /** 用户在 `/` 后面打的过滤词 */
  query: string
  active: number
}

export const openSlash = StateEffect.define<number>()
export const closeSlash = StateEffect.define<null>()
export const moveSlash = StateEffect.define<number>()

/** 交给 React 去执行选中的动作。菜单本身不碰网络、不碰上传—— CM6 扩展里
 * 只管「选了哪一项、`/` 从哪到哪」，具体做什么由上层决定。 */
export type SlashRunner = (item: SlashItem, from: number, to: number) => void

export function filtered(query: string): SlashItem[] {
  const q = query.trim().toLowerCase()
  if (!q) return SLASH_ITEMS
  return SLASH_ITEMS.filter((i) =>
    i.label.toLowerCase().includes(q) || i.key.includes(q) || i.hint.toLowerCase().includes(q))
}

/** 这次改动是不是「在行首或空白之后打了一个 /」。是的话返回那个 `/` 的位置。
 *
 * **判定放在 field 自己的 update 里**，不用 updateListener：那是视图层扩展，
 * 纯 EditorState 里根本不跑（第一版就是这么写的，构建通过、类型通过、菜单
 * 一次都没弹出来），而且在 updateListener 里同步 dispatch 也是 CM6 不推荐的
 * 做法。放在 field 里既不需要视图，也顺带变得可测。 */
function slashTypedAt(tr: { changes: { iterChanges: (f: (fA: number, tA: number, fB: number, tB: number, ins: { toString(): string }) => void) => void }; state: { sliceDoc: (a: number, b: number) => string } }): number {
  let at = -1
  tr.changes.iterChanges((_fA, _tA, _fB, tB, ins) => {
    if (ins.toString() !== '/') return
    const before = tB > 1 ? tr.state.sliceDoc(tB - 2, tB - 1) : ''
    // 行首（前面没字符）或者空白之后才算——「A/B 测试」「他/她」不该弹菜单
    if (before === '' || /\s/.test(before)) at = tB - 1
  })
  return at
}

export const slashField = StateField.define<SlashState | null>({
  create: () => null,
  update(v, tr) {
    for (const e of tr.effects) {
      if (e.is(openSlash)) return { from: e.value, query: '', active: 0 }
      if (e.is(closeSlash)) return null
      if (e.is(moveSlash) && v) {
        const n = filtered(v.query).length || 1
        return { ...v, active: (v.active + e.value + n) % n }
      }
    }
    if (!v) {
      if (!tr.docChanged) return null
      const at = slashTypedAt(tr)
      return at >= 0 ? { from: at, query: '', active: 0 } : null
    }
    let from = v.from
    if (tr.docChanged) from = tr.changes.mapPos(from, -1)
    const head = tr.state.selection.main.head
    // 光标退到 `/` 前面、或者跑到别的地方去了，就关掉
    if (head <= from || head > from + 40) return null
    const query = tr.state.sliceDoc(from + 1, head)
    // 打了空格还没匹配上任何东西 = 用户只是在写一个普通的斜杠
    if (/\s/.test(query) && filtered(query).length === 0) return null
    return { ...v, query, active: Math.min(v.active, Math.max(0, filtered(query).length - 1)) }
  },
})

/** 选中一项。
 *
 *  带 `cmd` 的（排版类）**就地执行**：先把 `/查询词` 删掉，再跑那个 CM6 命令。
 *  它们不碰网络、不需要 React 的任何状态，交给上层 runner 反而要把整套命令
 *  再传一遍。Enter 和鼠标两条路都走这里，免得两边行为不一致。 */
function pick(view: EditorView, it: SlashItem, from: number, to: number, run: SlashRunner) {
  view.dispatch({ effects: closeSlash.of(null) })
  if (it.cmd) {
    view.dispatch({ changes: { from, to, insert: '' }, selection: { anchor: from } })
    it.cmd(view)
    view.focus()
    return
  }
  run(it, from, to)
}

function menuDom(view: EditorView, st: SlashState, run: SlashRunner): HTMLElement {
  const wrap = document.createElement('div')
  wrap.className = 'slash-menu'
  const items = filtered(st.query)
  if (!items.length) {
    const empty = document.createElement('div')
    empty.className = 'slash-empty'
    empty.textContent = '没有匹配的功能'
    wrap.append(empty)
    return wrap
  }
  let lastGroup = ''
  items.forEach((it, i) => {
    // 组变了就插一行小标题。过滤之后只剩一组时也留着——它告诉用户
    // 「筛出来的是排版命令」，比省掉一行更有用。
    if (it.group !== lastGroup) {
      lastGroup = it.group
      const g = document.createElement('div')
      g.className = 'slash-group'
      g.textContent = it.group
      wrap.append(g)
    }
    const row = document.createElement('div')
    row.className = 'slash-item' + (i === st.active ? ' active' : '')
    row.innerHTML = ''
    // boxicons 名字（跟外壳其它图标一套），不再是 emoji
    const icon = document.createElement('i')
    icon.className = 'slash-icon bx ' + it.icon
    const text = document.createElement('span')
    const label = document.createElement('div')
    label.className = 'slash-label'
    label.textContent = it.label
    const hint = document.createElement('div')
    hint.className = 'slash-hint'
    hint.textContent = it.hint
    text.append(label, hint)
    row.append(icon, text)
    // mousedown 而不是 click：click 之前编辑器就会先丢掉选区和焦点
    row.addEventListener('mousedown', (e) => {
      e.preventDefault()
      e.stopPropagation()
      const head = view.state.selection.main.head
      pick(view, it, st.from, head, run)
    })
    wrap.append(row)
  })
  return wrap
}

export function slashMenu(run: SlashRunner) {
  const tip = showTooltip.compute([slashField], (state): Tooltip | null => {
    const st = state.field(slashField)
    if (!st) return null
    return {
      pos: st.from,
      above: false,
      arrow: false,
      create: (view) => ({ dom: menuDom(view, st, run) }),
    }
  })

  const keys = EditorView.domEventHandlers({
    keydown(e, view) {
      const st = view.state.field(slashField, false)
      if (!st) return false
      if (e.key === 'Escape') { view.dispatch({ effects: closeSlash.of(null) }); return true }
      if (e.key === 'ArrowDown') { view.dispatch({ effects: moveSlash.of(1) }); return true }
      if (e.key === 'ArrowUp') { view.dispatch({ effects: moveSlash.of(-1) }); return true }
      if (e.key === 'Enter' || e.key === 'Tab') {
        const items = filtered(st.query)
        const it = items[st.active]
        if (!it) return false
        e.preventDefault()
        const head = view.state.selection.main.head
        pick(view, it, st.from, head, run)
        return true
      }
      return false
    },
    // 点别处就关
    mousedown(_e, view) {
      if (view.state.field(slashField, false)) view.dispatch({ effects: closeSlash.of(null) })
      return false
    },
  })

  return [slashField, tip, keys]
}
