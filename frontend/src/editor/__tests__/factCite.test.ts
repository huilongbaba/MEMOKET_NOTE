/**
 * 行内出处的识别：哪些 `[...]` 算引用，哪些不算。
 *
 * 认错的代价是双向的：认少了，用户看不到出处（判据 2 白做）；认多了，
 * 正文里普通的方括号会变成一堆点不开的假链接，而且每个都会去打一次网络。
 */
import { describe, expect, it } from 'vitest'

/** 跟 factCite.ts 里那条保持一致——形状写死是为了不把普通方括号误标。 */
const CITE = /\[([A-Za-z][A-Za-z0-9_-]*-\d+-[0-9A-Fa-f]+)\]/g

function ids(text: string): string[] {
  CITE.lastIndex = 0
  return [...text.matchAll(CITE)].map((m) => m[1])
}

describe('出处标记的形状', () => {
  it('认出真实的 fact id', () => {
    // 真实形状取自 KITE：<用户>-<数字>-<十六进制>
    expect(ids('据 [terrence-1872-5F8] 所述')).toEqual(['terrence-1872-5F8'])
    expect(ids('[terrence-1439-0F3] 和 [terrence-1814-27F1]'))
      .toEqual(['terrence-1439-0F3', 'terrence-1814-27F1'])
  })

  it('带连字符的用户名也认', () => {
    expect(ids('[terrence-rewrite-12-AB]')).toEqual(['terrence-rewrite-12-AB'])
  })

  it('普通方括号不算引用', () => {
    // 认多了的代价：正文里每个方括号都变成点不开的假链接，还各打一次网络
    expect(ids('这是 [一个注释] 和 [TODO] 还有 [1]')).toEqual([])
    expect(ids('markdown 链接 [标题](http://x)')).toEqual([])
  })

  it('缺了任何一段都不算', () => {
    expect(ids('[terrence-1872]')).toEqual([])      // 少十六进制那段
    expect(ids('[terrence-5F8]')).toEqual([])       // 少数字那段
    // 只有两段也不算：真实 fact id 是三段（用户-数字-十六进制）。少一段就
    // 放行的话，`[2026-06]` 这种日期会被当成出处。
    expect(ids('[1872-5F8]')).toEqual([])
    expect(ids('会议在 [2026-06] 举行')).toEqual([])
  })

  it('一行里出现多次都要认', () => {
    const line = '甲[a-1-A]乙[b-2-B]丙[c-3-C]'
    expect(ids(line)).toHaveLength(3)
  })
})


it('方括号里的日期不是引用（01 是合法十六进制，旧正则会误认）', () => {
  expect(ids('[2026-01-01] 开会，见 [terrence-1872-5F8]')).toEqual(['terrence-1872-5F8'])
})
