/**
 * 树的铺平逻辑：谁该画出来、画在第几层、顺序怎么排。
 *
 * 这是树能不能用的地基。三条性质各自对应一个真实的坏法：
 *   · 只铺开展开着的节点——不然一棵深树一上来就把几百行全画出来
 *   · 收起的节点，它的子树整棵不画
 *   · **成环时不能爆栈**：后端有防线，但前端不该假设它没漏；递归遇到环是
 *     白屏，迭代加一个 seen 集合最多画重复，界面还活着
 */
import { describe, expect, it } from 'vitest'

import { flattenTreeForTest as flatten } from '../../components/NoteTree'
import type { TreeRow } from '../../api'

function row(note: string, parent: string, extra: Partial<TreeRow> = {}): TreeRow {
  return {
    id: `${parent}>${note}`, note_id: note, parent_note_id: parent,
    position: 0, is_expanded: false, title: note, preview: '',
    pinned: false, updated_at: "", child_count: 0, branch_count: 1,
    cite_count: 0, ingested_at: "",
    ...extra,
  }
}

describe('flatten', () => {
  it('只画树根下面的一层，收起的不展开', () => {
    const rows = [
      row('a', 'root', { child_count: 1 }),
      row('a1', 'a'),
    ]
    expect(flatten(rows).map((n) => n.note_id)).toEqual(['a'])
  })

  it('展开的节点把孩子画出来，并且层级加一', () => {
    const rows = [
      row('a', 'root', { child_count: 1, is_expanded: true }),
      row('a1', 'a'),
    ]
    const got = flatten(rows)
    expect(got.map((n) => n.note_id)).toEqual(['a', 'a1'])
    expect(got.map((n) => n.depth)).toEqual([0, 1])
  })

  it('同一层按 position 排，position 相同时按标题', () => {
    const rows = [
      row('b', 'root', { position: 1 }),
      row('a', 'root', { position: 0 }),
      row('c', 'root', { position: 0, title: 'aa' }),
    ]
    // position 都是 0 的两个按标题：'a' 在 'aa' 前面
    expect(flatten(rows).map((n) => n.note_id)).toEqual(['a', 'c', 'b'])
  })

  it('克隆：同一篇笔记在两个位置各画一行', () => {
    const rows = [
      row('p1', 'root', { child_count: 1, is_expanded: true }),
      row('p2', 'root', { child_count: 1, is_expanded: true, position: 1 }),
      row('shared', 'p1', { branch_count: 2 }),
      row('shared', 'p2', { branch_count: 2 }),
    ]
    const got = flatten(rows)
    expect(got.filter((n) => n.note_id === 'shared')).toHaveLength(2)
  })

  it('数据里成了环也不能爆栈', () => {
    // 后端 _would_cycle 挡着，但前端不该假设它没漏。递归遇到环是白屏。
    const rows = [
      row('a', 'root', { child_count: 1, is_expanded: true }),
      row('b', 'a', { child_count: 1, is_expanded: true }),
      row('a', 'b', { child_count: 1, is_expanded: true }),
    ]
    const got = flatten(rows)
    expect(got.length).toBeLessThan(20)
    expect(got.map((n) => n.note_id)).toContain('b')
  })

  it('孤儿节点不画——父节点不在树上，它就没有位置', () => {
    expect(flatten([row('x', '不存在的父节点')])).toEqual([])
  })
})
