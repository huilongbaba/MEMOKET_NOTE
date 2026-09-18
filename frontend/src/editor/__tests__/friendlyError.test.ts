import { describe, expect, it } from 'vitest'
import { friendlyError, isLlmUnreachable } from '../../util/friendlyError'

describe('friendlyError', () => {
  it('连接类错误指向设置页', () => {
    expect(friendlyError(new Error('All connection attempts failed'))).toContain('设置')
    // P3：浏览器连不上后端 ≠ 后端连不上模型——这一句不再指去设置页
    expect(friendlyError('TypeError: Failed to fetch')).toContain('连不上应用后台')
    expect(isLlmUnreachable(new Error('500 Internal Server Error'))).toBe(true)
  })
  it('其它错误原样保留，去掉 Error: 前缀', () => {
    expect(friendlyError(new Error('锚点找不到'))).toBe('锚点找不到')
    expect(friendlyError('Error: 422 validation')).toBe('validation')   // 第 253 轮起 4xx 状态码不给用户看
    expect(isLlmUnreachable('锚点找不到')).toBe(false)
  })
})

describe('friendlyError（第 253 轮）', () => {
  it('4xx 带人话时只留人话', () => {
    expect(friendlyError(new Error('400 模型地址要以 http:// 或 https:// 开头'))).toBe('模型地址要以 http:// 或 https:// 开头')
    expect(friendlyError(new Error('404 note not found'))).toBe('note not found')
    expect(friendlyError('')).toBe('未知错误')
  })
})
