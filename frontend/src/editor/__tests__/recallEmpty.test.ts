import { describe, expect, it, vi } from 'vitest'

/**
 * 「知识库是空的」和「这一次没查到」必须说成两件事。
 *
 * 第 677 轮实拍：一个还没导过任何东西的新用户在正文里打 `@样机`，看到的是
 * 「知识库里没找到跟"样机"相关的记录」——听起来像是这个词不对，于是他会换词
 * 再试，试多少次都是空。（写作闭环里的同一个坑在第 676 轮修过。）
 */
const recall = vi.fn()
vi.mock('../../api', () => ({ recall: (q: string, n: number) => recall(q, n) }))

const { recallSource } = await import('../recallCompletion')

function ctx(text: string) {
  return {
    aborted: false,
    matchBefore: (re: RegExp) => {
      const m = re.exec(text)
      return m ? { from: text.length - m[0].length, to: text.length, text: m[0] } : null
    },
  } as never
}

describe('@ 引用查不到时说什么', () => {
  it('库是空的：劝去导入，不劝换说法', async () => {
    recall.mockResolvedValue({ facts: [], took_ms: 1, terms: [], kb_empty: true })
    const r = await recallSource(ctx('写到这里 @样机'))
    expect(r!.options[0].label).toContain('知识库还是空的')
    expect(r!.options[0].label).toContain('导入')
    expect(r!.options[0].label).not.toContain('样机')
  })

  it('库里有东西、只是这次没命中：照旧说没找到那个词', async () => {
    recall.mockResolvedValue({ facts: [], took_ms: 1, terms: [], kb_empty: false })
    const r = await recallSource(ctx('写到这里 @样机'))
    expect(r!.options[0].label).toContain('样机')
    expect(r!.options[0].label).not.toContain('空的')
  })

  it('后端没给这个字段（旧版）时按「没找到」走，不乱说库是空的', async () => {
    recall.mockResolvedValue({ facts: [], took_ms: 1, terms: [] })
    const r = await recallSource(ctx('写到这里 @样机'))
    expect(r!.options[0].label).toContain('样机')
  })

  it('查到了就正常给候选', async () => {
    recall.mockResolvedValue({
      facts: [{ id: 'f1', text: '样机的续航实测 11 小时。', when: '2026-03-04', sources: [] }],
      took_ms: 1, terms: [], kb_empty: false,
    })
    const r = await recallSource(ctx('写到这里 @样机'))
    expect(r!.options).toHaveLength(1)
    expect(r!.options[0].label).toContain('续航')
  })
})
