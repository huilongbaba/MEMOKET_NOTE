import { describe, expect, it } from 'vitest'

import { isSlides, slidePages } from '../../util/slidePages'

const MD = `---
marp: true
slides: true
---

# 创业一年回顾

年度结论必须回到验证证据。

---

## EVT 从 6 月挪到 8 月

- 结构件改了 [terrence-1-A1]

---

## 配件

- 没有依据的一页
`

describe('幻灯片分页', () => {
  it('front-matter 不算一页，标题和正文分得开', () => {
    const ps = slidePages(MD)
    expect(ps.map((p) => p.title)).toEqual(['创业一年回顾', 'EVT 从 6 月挪到 8 月', '配件'])
    expect(ps[0].body).toBe('年度结论必须回到验证证据。')
  })

  it('哪一页有依据要标出来——一页没有依据的幻灯片跟通用工具做出来的没区别', () => {
    expect(slidePages(MD).map((p) => p.cited)).toEqual([false, true, false])
  })

  it('代码块里的横线不算分页符', () => {
    const md = '# 一\n\n```yaml\na: 1\n---\nb: 2\n```\n\n---\n\n## 二\n'
    expect(slidePages(md)).toHaveLength(2)
  })

  it('每一页记得自己在正文里的位置——点一页要能跳过去', () => {
    const ps = slidePages(MD)
    for (const p of ps) expect(MD.slice(p.at)).toContain(p.title)
    expect(ps[1].at).toBeGreaterThan(ps[0].at)
  })

  it('认得出这是不是一篇幻灯片笔记', () => {
    expect(isSlides(MD)).toBe(true)
    expect(isSlides('# 普通笔记\n\n正文')).toBe(false)
    expect(isSlides('---\nfoo: 1\n---\n\n# 有 front-matter 但不是幻灯片')).toBe(false)
  })

  it('空的不炸', () => {
    expect(slidePages('')).toEqual([])
  })
})
