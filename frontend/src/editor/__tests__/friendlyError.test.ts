import { describe, expect, it } from 'vitest'
import { friendlyError } from '../../util/friendlyError'

describe('friendlyError', () => {
  it('4xx 带人话时只留人话，连接类错误指向设置', () => {
    expect(friendlyError(new Error('400 模型地址要以 http:// 或 https:// 开头'))).toBe('模型地址要以 http:// 或 https:// 开头')
    expect(friendlyError(new Error('404 note not found'))).toBe('note not found')
    expect(friendlyError(new Error('Error: All connection attempts failed'))).toMatch(/^模型连不上/)
    expect(friendlyError(new Error('401 Unauthorized'))).toMatch(/API key/)
    expect(friendlyError(new Error('500 Internal Server Error'))).toMatch(/^后端处理出错/)
    expect(friendlyError('')).toBe('未知错误')
  })
})
