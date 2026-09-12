import { describe, expect, it } from 'vitest'
import { micError } from '../../util/micError'

function err(name: string, message = 'x') {
  const e = new Error(message)
  e.name = name
  return e
}

describe('micError', () => {
  it('系统拒绝 → 指向系统设置', () => {
    expect(micError(err('NotAllowedError'))).toContain('系统设置')
  })
  it('没设备 / 被占用各有一句', () => {
    expect(micError(err('NotFoundError'))).toContain('没找到')
    expect(micError(err('NotReadableError'))).toContain('占用')
  })
  it('其它错误走 friendlyError 并保留原信息', () => {
    expect(micError(new Error('weird thing'))).toBe('打不开麦克风：weird thing')
    expect(micError(null)).toContain('打不开麦克风')
  })
})
