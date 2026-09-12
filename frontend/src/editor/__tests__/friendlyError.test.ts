import { describe, expect, it } from 'vitest'
import { friendlyError, isLlmUnreachable } from '../../util/friendlyError'

describe('friendlyError', () => {
  it('连接类错误指向设置页', () => {
    expect(friendlyError(new Error('All connection attempts failed'))).toContain('设置')
    expect(friendlyError('TypeError: Failed to fetch')).toContain('模型连不上')
    expect(isLlmUnreachable(new Error('500 Internal Server Error'))).toBe(true)
  })
  it('其它错误原样保留，去掉 Error: 前缀', () => {
    expect(friendlyError(new Error('锚点找不到'))).toBe('锚点找不到')
    expect(friendlyError('Error: 422 validation')).toBe('422 validation')
    expect(isLlmUnreachable('锚点找不到')).toBe(false)
  })
})
