import { describe, expect, it } from 'vitest'
import type { TreeRow } from '../../api'
import { buildCrumbs } from '../../util/crumbs'

const row = (note_id: string, parent_note_id: string, title: string): TreeRow => ({
  id: 'b-' + note_id, note_id, parent_note_id, position: 0, is_expanded: false, title, preview: '',
  cite_count: 0, ingested_at: '', pinned: false, updated_at: '', child_count: 0, branch_count: 1, fact_count: 0,
} as TreeRow)
const isVirtual = (id: string) => id === 'kb' || id.startsWith('kb:') || id.startsWith('app:')
const noTab = () => undefined

describe('buildCrumbs', () => {
  const rows = [row('a', 'root', '项目'), row('b', 'a', '会议'), row('kb', 'root', '知识库'), row('kb:topics', 'kb', '主题'),
    row('kb:topic:work', 'kb:topics', 'work'), row('kb:facts?topic=work', 'kb:topic:work', '还有 5734 条 · 去事实表看')]
  it('真笔记：沿树往上到根', () => {
    expect(buildCrumbs('b', rows, noTab, isVirtual).map((r) => r.title)).toEqual(['项目', '会议'])
  })
  it('从尾巴行进来的事实表：末尾用页面名', () => {
    expect(buildCrumbs('kb:facts?topic=work', rows, noTab, isVirtual).map((r) => r.title)).toEqual(['知识库', '主题', 'work', '事实表 · work'])
  })
  it('树上没有的懒加载节点：按 id 形状拼父链，名字用标签的', () => {
    expect(buildCrumbs('kb:entity:acme', rows, (id) => (id === 'kb:entity:acme' ? 'Acme' : undefined), isVirtual).map((r) => r.title))
      .toEqual(['知识库', '实体', 'Acme'])
  })
  it('app:* 不冠知识库；知识库根不重复；什么都没开就空', () => {
    expect(buildCrumbs('app:trash', [], noTab, isVirtual).map((r) => r.title)).toEqual(['最近删除'])
    expect(buildCrumbs('kb', [], noTab, isVirtual).map((r) => r.title)).toEqual(['知识库'])
    expect(buildCrumbs(null, rows, noTab, isVirtual)).toEqual([])
  })
})
