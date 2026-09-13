import { describe, expect, it } from 'vitest'
import { clipTitle, displayTitle } from '../../util/displayTitle'

describe('displayTitle', () => {
  it('真标题原样', () => {
    expect(displayTitle({ title: '周会纪要', content: '别的' })).toBe('周会纪要')
  })
  it('占位标题退回正文首行，去掉 # 前缀', () => {
    expect(displayTitle({ title: '未命名', content: '# 创业一年回顾\n正文' })).toBe('创业一年回顾')
    expect(displayTitle({ title: '', content: '\n\n第一句。第二句' })).toBe('第一句')
  })
  it('首行当标题截到第一个句读', () => {
    expect(clipTitle('今天跟供应商确认了 PCBA 样品的交期，4 月 10 日拿到手板之后再定下一步')).toBe('今天跟供应商确认了 PCBA 样品的交期')
    expect(clipTitle('好的，那就这么定了')).toBe('好的，那就这么定了')     // 句读太靠前不截
    expect(clipTitle('x'.repeat(80))).toHaveLength(60)
  })
  it('全空是未命名', () => {
    expect(displayTitle({ title: 'Untitled', content: '   \n  ' })).toBe('未命名')
  })
})
