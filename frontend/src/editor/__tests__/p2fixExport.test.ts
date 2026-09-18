// @vitest-environment jsdom
/**
 * P2-fix（产品就绪计划 A3）里前端管得着的几条（docs/_research/export-verification-P2.md §4）：
 *
 *   4  成功的 toast 带「打开」——后端回了 url 才带；副本那一行能点去对面
 *   6  `n=0` 不再一律说「没改过」：note_id 对不上是「没有匹配的笔记」，对方改过是「跳过了」
 *   16 失败提示去掉状态码前缀，带「复制」、多留一会儿
 */
import { describe, expect, it } from 'vitest'

import { exportErrorText, exportOutcome, remoteUrl } from '../../util/useExportBack'
import { getSnapshot, toastAction } from '../../toast'

describe('导回结果 → 用户看到的那一句（P2-fix 4 / 6）', () => {
  it('写了 1 篇、后端带 url：说 1 篇，带链接', () => {
    expect(exportOutcome({ created: 1, updated: 0, failed: [], url: 'https://x.feishu.cn/docx/abc' }))
      .toEqual({ kind: 'ok', text: '导回 1 篇', url: 'https://x.feishu.cn/docx/abc' })
    expect(exportOutcome({ written: 3, skipped: 2 }).text).toBe('导回 3 篇')
  })
  it('部分失败 / 部分冲突也说出来', () => {
    expect(exportOutcome({ created: 2, failed: ['a: x'] }).text).toBe('导回 2 篇，1 篇失败')
    expect(exportOutcome({ updated: 1, conflicts: ['b'] }).text).toBe('导回 1 篇，1 篇对方改过没动')
  })
  it('note_id 对不上：不撒谎说「没改过」', () => {
    const o = exportOutcome({ created: 0, updated: 0, failed: [], missing: ['deadbeef0000'] })
    expect(o.kind).toBe('missing')
    expect(o.text).toContain('没有匹配的笔记')
    expect(o.url).toBeUndefined()
  })
  it('对方改过、全部跳过：说清楚要勾「覆盖」', () => {
    const o = exportOutcome({ updated: 0, conflicts: ['A'] })
    expect(o.kind).toBe('conflict')
    expect(o.text).toContain('覆盖对方改过的')
  })
  it('真的没改过（skipped>0）才说「没改过」', () => {
    expect(exportOutcome({ written: 0, skipped: 1 }).text).toBe('没有需要写的：上次导回之后没改过')
    expect(exportOutcome({ written: 0, skipped: 0 }).text).toBe('没有可导的笔记')
  })
})

describe('副本那一行能点去哪（P2-fix 4）', () => {
  it('Notion / 飞书：remote_path 就是 URL', () => {
    expect(remoteUrl({ platform: 'feishu', remote_id: 'd', remote_path: 'https://x.feishu.cn/docx/d', exported_at: '' })).toBe('https://x.feishu.cn/docx/d')
    // 老记录（P2-fix 之前）remote_path 是空的：没有链接，不瞎拼
    expect(remoteUrl({ platform: 'feishu', remote_id: 'd', remote_path: '', exported_at: '' })).toBe('')
  })
  it('Obsidian：知道 vault 才拼 obsidian://，路径要编码', () => {
    expect(remoteUrl({ platform: 'obsidian', remote_id: 's', remote_path: 'Notes/公司汇报：.md', exported_at: '' }, '/Users/me/vault/'))
      .toBe('obsidian://open?path=' + encodeURIComponent('/Users/me/vault/Notes/公司汇报：.md'))
    expect(remoteUrl({ platform: 'obsidian', remote_id: 's', remote_path: 'a.md', exported_at: '' }, '')).toBe('')
  })
})

describe('失败提示（P2-fix 2 / 16）', () => {
  it('去掉后端 4xx 的状态码前缀，留那句人话', () => {
    expect(exportErrorText(new Error('400 飞书说 App Secret 不对（10014 app secret invalid）——开放平台 → 应用 → 凭证与基础信息')))
      .toBe('飞书说 App Secret 不对（10014 app secret invalid）——开放平台 → 应用 → 凭证与基础信息')
    expect(exportErrorText(new Error('Error: Failed to fetch'))).toBe('Failed to fetch')
    expect(exportErrorText('')).toBe('导回失败')
  })
  it('toastAction 能发红色的、带动作的 toast（导回失败用它带「复制」）', () => {
    toastAction('飞书拒绝了', '复制', () => {}, 15000, 'error')
    const t = getSnapshot().find((x) => x.message === '飞书拒绝了')
    expect(t?.kind).toBe('error')
    expect(t?.action?.label).toBe('复制')
  })
})
