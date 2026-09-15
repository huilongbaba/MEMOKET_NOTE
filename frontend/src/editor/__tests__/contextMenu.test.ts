import { describe, expect, it } from 'vitest'

import { selectableItem, tidyMenu, type MenuItem } from '../../components/ContextMenu'

/**
 * 右键菜单里「哪一项现在能点」这条判断，原来在两处各写了一遍
 * （`as any` 拼的），而回车那一处是**先问一句**才调 `onSelect`——
 * 靠调用处记得问。收成一个类型谓词之后编译器一起看着（第 709 轮）。
 */
describe('右键菜单：哪一项能点', () => {
  const sep: MenuItem = { kind: 'sep' }
  const head: MenuItem = { kind: 'header', label: '这一段' }
  const act: MenuItem = { label: '删除', onSelect: () => {} }
  const off: MenuItem = { label: '打磨', disabled: true, onSelect: () => {} }

  it('分隔线、小标题、禁用项都不能点', () => {
    expect(selectableItem(sep)).toBe(false)
    expect(selectableItem(head)).toBe(false)
    expect(selectableItem(off)).toBe(false)
    expect(selectableItem(undefined)).toBe(false)
  })

  it('普通项能点', () => {
    expect(selectableItem(act)).toBe(true)
  })
})

describe('右键菜单：分隔线收拾干净', () => {
  it('连着的分隔线并成一条', () => {
    const out = tidyMenu([{ label: 'a', onSelect: () => {} }, { kind: 'sep' }, { kind: 'sep' },
                          { label: 'b', onSelect: () => {} }])
    expect(out.filter((i) => i.kind === 'sep')).toHaveLength(1)
  })

  it('开头和结尾的分隔线都去掉', () => {
    const out = tidyMenu([{ kind: 'sep' }, { label: 'a', onSelect: () => {} }, { kind: 'sep' }])
    expect(out).toHaveLength(1)
  })

  it('全是分隔线就清空（不该剩一条孤线）', () => {
    expect(tidyMenu([{ kind: 'sep' }, { kind: 'sep' }])).toHaveLength(0)
  })
})
