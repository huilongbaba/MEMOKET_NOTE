import { describe, expect, it } from 'vitest'
import { disambiguate } from '../noteLinkCompletion'

describe('[[ 补全的重名区分', () => {
  it('不重名只给日期，重名补正文首句', () => {
    const hits = [
      { title: '创业一年回顾', content: '# 创业一年回顾\n\n## 时间线\n\n- **4月16日EVT**：主机 4 台', updated_at: '2026-09-10T00:00:00Z' },
      { title: '创业一年回顾', content: '创业一年回顾\n\n这一年最大的教训是先卖再做。', updated_at: '2026-09-07T00:00:00Z' },
      { title: '创业反思', content: '随便', updated_at: '2026-09-02T00:00:00Z' },
    ]
    const d = disambiguate(hits)
    expect(d[2]).not.toContain('·')
    expect(d[0]).toMatch(/· 4月16日EVT：主机 4 台$/)
    expect(d[1]).toMatch(/· 这一年最大的教训是先卖再做。$/)
  })
  it('正文只有标题时退回日期', () => {
    const hits = [
      { title: 'A', content: '# A', updated_at: '2026-09-10T00:00:00Z' },
      { title: 'A', content: '', updated_at: '2026-09-09T00:00:00Z' },
    ]
    expect(disambiguate(hits).every((x) => !x.includes('·'))).toBe(true)
  })
})
