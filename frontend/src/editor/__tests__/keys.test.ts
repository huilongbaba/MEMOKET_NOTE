import { describe, expect, it } from 'vitest'
import { fmtShortcut } from '../../util/keys'

describe('fmtShortcut', () => {
  it('mac 原样，其它平台翻成 Ctrl/Alt/Shift', () => {
    expect(fmtShortcut('⌘K / ⌘J', true)).toBe('⌘K / ⌘J')
    expect(fmtShortcut('⌘K / ⌘J', false)).toBe('Ctrl+K / Ctrl+J')
    expect(fmtShortcut('⇧⌘T', false)).toBe('Shift+Ctrl+T')
    expect(fmtShortcut('⌥点击', false)).toBe('Alt+点击')
    expect(fmtShortcut('⌫', false)).toBe('Del')
  })
})
