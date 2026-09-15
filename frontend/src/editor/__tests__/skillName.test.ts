import { describe, expect, it } from 'vitest'

import { splitSkillName } from '../../util/skillName'

describe('skill 名字拆出处', () => {
  it('内置的那一批：括号摘出来，剩下的头短到不会被截', () => {
    for (const [raw, head, note] of [
      ['生成前确认范围（受 brainstorming 启发）', '生成前确认范围', '受 brainstorming 启发'],
      ['宁缺毋滥（受 discernment-nudge 的克制启发）', '宁缺毋滥', '受 discernment-nudge 的克制启发'],
      ['先想读者会追问什么（受 doc-coauthoring 的语境收集启发）', '先想读者会追问什么', '受 doc-coauthoring 的语境收集启发'],
    ] as const) {
      expect(splitSkillName(raw)).toEqual({ head, note })
      expect(head.length).toBeLessThanOrEqual(12)      // 卡片那一行放得下
    }
  })

  it('没有括号的名字原样不动', () => {
    expect(splitSkillName('我的写作习惯')).toEqual({ head: '我的写作习惯', note: '' })
    expect(splitSkillName('校验触发/跳过规则')).toEqual({ head: '校验触发/跳过规则', note: '' })
  })

  it('只摘结尾那一对，名字中间的括号留着', () => {
    expect(splitSkillName('引用（含脚注）的写法约定')).toEqual({ head: '引用（含脚注）的写法约定', note: '' })
  })

  it('半角括号和空括号', () => {
    expect(splitSkillName('Tone (Anthropic style)')).toEqual({ head: 'Tone', note: 'Anthropic style' })
    expect(splitSkillName('奇怪的名字（）')).toEqual({ head: '奇怪的名字（）', note: '' })
  })
})
