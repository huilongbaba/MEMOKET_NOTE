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

export type SlashItem = {
  key: string
  label: string
  hint: string
  icon: string
  /** 需要用户再输入一段提示词的（智能分析、按提示词写…） */
  needsPrompt?: boolean
  placeholder?: string
}

/** 菜单项。顺序就是用户看到的顺序：先是要动脑子的，再是纯插入的。 */
/** 菜单项。**只放 AI 功能**——纯插入的（空表格、图片）在顶部工具栏里，
 * `/` 是"让 AI 干活"的入口，把两类混在一起会让这个菜单越长越难用。
 * 音频和语音留在这里，是因为它们插入之后都要**跑转写**，本身就是 AI 动作。 */
export const SLASH_ITEMS: SlashItem[] = [
  { key: 'prompt', icon: '✨', label: '用 AI 写', hint: '描述你想写什么，会结合上下文和你的知识库',
    needsPrompt: true, placeholder: '例如：把上面几段总结成三条结论' },
  { key: 'chart', icon: '📈', label: '智能插图', hint: '数据用图表、概念用文生图，自动判断' },
  { key: 'table', icon: '📋', label: '智能表格', hint: '把上下文整理成表格',
    needsPrompt: true, placeholder: '想整理成什么表？留空则自动判断' },
  { key: 'table-image', icon: '🖼', label: '图片转表格', hint: '传一张图，识别里面的表格' },
  { key: 'eda', icon: '📊', label: '数据可视化', hint: '把笔记里的表格画成图：分布、占比、对比' },
  { key: 'analysis', icon: '🧮', label: '智能数据分析', hint: '问一个数据问题，用工具算出来再回答',
    needsPrompt: true, placeholder: '例如：哪个渠道的单位曝光收入最高？' },
  { key: 'voice', icon: '🎙', label: '语音输入', hint: '录一段话，转写成文字插进来' },
  { key: 'audio', icon: '🎧', label: '插入音频', hint: '插入音频并自动转写出文字稿' },
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
  items.forEach((it, i) => {
    const row = document.createElement('div')
    row.className = 'slash-item' + (i === st.active ? ' active' : '')
    row.innerHTML = ''
    const icon = document.createElement('span')
    icon.className = 'slash-icon'
    icon.textContent = it.icon
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
      view.dispatch({ effects: closeSlash.of(null) })
      run(it, st.from, head)
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
        view.dispatch({ effects: closeSlash.of(null) })
        run(it, st.from, head)
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
