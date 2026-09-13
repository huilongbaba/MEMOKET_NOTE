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
    expect(clipTitle('APP定义：先锚定范围，避免后续招聘和排期漂移')).toBe('APP定义：先锚定范围')   // 冒号太靠前跳过，逗号够远
    expect(clipTitle('我们产品当前遇到的挑战：四项核心挑战归纳为验证框架')).toBe('我们产品当前遇到的挑战')
    expect(clipTitle('x'.repeat(80))).toHaveLength(60)
  })
  it('整篇缩进的笔记：首行前的空格和 # 都剥掉', () => {
    expect(displayTitle({ title: '', content: '    # 创业一年回顾\n    ## 时间线' })).toBe('创业一年回顾')
  })
  it('全空是未命名', () => {
    expect(displayTitle({ title: 'Untitled', content: '   \n  ' })).toBe('未命名')
  })
})
