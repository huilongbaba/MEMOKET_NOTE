// @vitest-environment jsdom
import { EditorState } from '@codemirror/state'
import { describe, expect, it } from 'vitest'

import { closeSlash, filtered, slashField } from '../slashMenu'

/**
 * P49 ③：**按 Esc 关掉 `/` 菜单之后，正文里留着的那个 `/` 是不是缺陷。**
 *
 * P44 #6 / P47 #1 连着三批把它记成「照旧」，P47 的原话是「可能不是缺陷，但污染量程」。
 * 这一批**先判再改**，判下来是——**不是缺陷，一个字都不改**。三条理由：
 *
 * 1. **Esc 的意思是「关掉这个菜单」，不是「撤掉我刚打的字」。** 撤字有 ⌘Z，
 *    它是一条用户自己按的、可预期的路；让一个关闭动作顺手删掉文档里的字符，
 *    正是这条线一路在修的那个形状（「不许静悄悄替他做决定」，P39 / P41 #5 ② / P46 #3）。
 * 2. **用户真的要打一个字面的 `/` 时，这是唯一的出路。** 这个仓自己就把
 *    「字面的斜杠」当真事对待过：`slashTypedAt` 只在行首 / 空白之后才认，
 *    「A/B 测试」「他/她」压根不弹菜单。而行首那个 `/`（「/ 表示根目录」「3/12」）
 *    只能靠「弹出来再关掉」写出来——Esc 删字等于把它变成打不出来的字符。
 * 3. **外部依据（查过的那一侧）**：Obsidian 官方帮助写的是
 *    “To exit the Slash command search without invoking a command, press `Esc`
 *    or the `Space` key.”，而论坛里「怎么打一个字面斜杠」的答案正是「打空格」
 *    ——**退出之后那个 `/` 留着**，否则这条办法不成立。
 *    （Notion 官方帮助对 Esc 一个字都没写，所以**不拿 Notion 当依据**，不冒充查过。）
 *
 * 这个仓里已经有同一条规则的另一半：`/` 后面打了空格又匹配不上任何东西时，
 * 菜单自己关掉、`/` 留着（`slashField` 那一行）。Esc 跟它是同一件事的两个按键，
 * **两边行为一致**才是对的。
 *
 * 所以这一批对 `/` 的处置是：**代码零改动**，走查脚本收尾把那一行删掉
 * （它污染的是量程，不是产品）；这几条闸把「留着」这个决定钉住，
 * 免得下一批有人把它当 bug「修」掉。
 */
describe('P49 ③：Esc 关掉 / 菜单之后，那个 / 留在正文里（这是对的）', () => {
  const state = (doc: string) => EditorState.create({ doc, extensions: [slashField] })

  /** 在行首打一个 `/`：菜单开了，文档里就是那一个 `/`。 */
  const typeSlash = () => {
    const tr = state('').update({ changes: { from: 0, insert: '/' }, selection: { anchor: 1 } })
    return tr.state
  }

  it('打 / 会开菜单，而且 / 真的在文档里', () => {
    const s = typeSlash()
    expect(s.field(slashField)).toEqual({ from: 0, query: '', active: 0 })
    expect(s.doc.toString()).toBe('/')
  })

  it('Esc 那一下只关菜单：文档一个字节都不动', () => {
    const opened = typeSlash()
    const closed = opened.update({ effects: closeSlash.of(null) }).state
    expect(closed.field(slashField)).toBeNull()      // 菜单关了
    expect(closed.doc.toString()).toBe('/')          // 字还在——**这是有意的**
    expect(closed.doc.length).toBe(opened.doc.length)
  })

  it('打了字再 Esc，打的那几个字也照样留着（Esc 不是撤销）', () => {
    let s = typeSlash()
    s = s.update({ changes: { from: 1, insert: '标题' }, selection: { anchor: 3 } }).state
    expect(s.field(slashField)?.query).toBe('标题')
    s = s.update({ effects: closeSlash.of(null) }).state
    expect(s.field(slashField)).toBeNull()
    expect(s.doc.toString()).toBe('/标题')
  })

  it('空格那条出路跟 Esc 一致：菜单关掉、/ 留着', () => {
    // 「打了空格还没匹配上任何东西 = 用户只是在写一个普通的斜杠」——slashField 自己那一行
    let s = typeSlash()
    s = s.update({ changes: { from: 1, insert: 'zz ' }, selection: { anchor: 4 } }).state
    expect(filtered('zz ')).toEqual([])              // 反例真的落在那条分支上
    expect(s.field(slashField)).toBeNull()
    expect(s.doc.toString()).toBe('/zz ')
  })

  it('「A/B 测试」那种根本不弹菜单——字面斜杠是被当真的场景', () => {
    let s = state('A')
    s = s.update({ changes: { from: 1, insert: '/' }, selection: { anchor: 2 } }).state
    expect(s.field(slashField)).toBeNull()
    expect(s.doc.toString()).toBe('A/')
  })
})
