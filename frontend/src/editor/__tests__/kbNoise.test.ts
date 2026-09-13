import { describe, expect, it } from 'vitest'
import { isSpeakerTag } from '../../util/kbNoise'

describe('isSpeakerTag（跟后端 kb/who.is_speaker_tag 同一条正则）', () => {
  it('录音转写的说话人标签算伪实体', () => {
    for (const s of ['Speaker A', 'speaker_c', 'speaker-1', 'SPEAKER b', '说话人 1', '说话人2', '发言人 a', ' speaker a ']) expect(isSpeakerTag(s)).toBe(true)
  })
  it('真实体不算', () => {
    for (const s of ['Facebook', 'speaker phone', 'speakers', '说话人们', '', 'app']) expect(isSpeakerTag(s)).toBe(false)
  })
})
