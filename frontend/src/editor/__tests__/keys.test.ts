import { describe, expect, it } from 'vitest'

import { fmtShortcut } from '../../util/keys'

/**
 * mac 的修饰符顺序是 ⌃⌥⇧⌘（Command 在最后），Windows 是 Ctrl+Alt+Shift
 * （Ctrl 在最前）——**两边的顺序是反的**。原来是逐个字符替换的，
 * `⇧⌘K` 直译成 `Shift+Ctrl+K`，Windows 用户看着别扭（第 706 轮）。
 */
describe('快捷键翻成 Windows 写法', () => {
  it('mac 上原样返回', () => {
    expect(fmtShortcut('⇧⌘K', true)).toBe('⇧⌘K')
  })

  it('修饰符要重排，不是直译', () => {
    expect(fmtShortcut('⇧⌘K', false)).toBe('Ctrl+Shift+K')
    expect(fmtShortcut('⌥⌘1', false)).toBe('Ctrl+Alt+1')
    // **这条是故意推翻上一版的**：原来断言的是 `Shift+Ctrl+T`（直译的结果）。
    expect(fmtShortcut('⇧⌘T', false)).toBe('Ctrl+Shift+T')
  })

  it('修饰符后面不一定是键名，也可能是「点击」这种词', () => {
    expect(fmtShortcut('⌥点击', false)).toBe('Alt+点击')
  })

  it('一行里好几个和弦，各翻各的', () => {
    expect(fmtShortcut('⌘B / ⌘I / ⇧⌘K', false)).toBe('Ctrl+B / Ctrl+I / Ctrl+Shift+K')
    expect(fmtShortcut('⌘1 … ⌘9', false)).toBe('Ctrl+1 … Ctrl+9')
  })

  it('⌃ 也是 Ctrl', () => {
    expect(fmtShortcut('⌃⇧Tab', false)).toBe('Ctrl+Shift+Tab')
  })

  it('没有修饰符的原样留着', () => {
    expect(fmtShortcut('F2', false)).toBe('F2')
    expect(fmtShortcut('[[', false)).toBe('[[')
  })

  it('⌫ / ↩ 换成词', () => {
    expect(fmtShortcut('⌫', false)).toBe('Del')
    expect(fmtShortcut('⇧↩', false)).toBe('Shift+Enter')
  })
})
