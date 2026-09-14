// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { loadSpots, putSpot, saveSpots } from '../../util/spots'

describe('spots（每篇看到哪儿了）', () => {
  beforeEach(() => localStorage.clear())

  it('存了能读回来，按用户分开', () => {
    const m = new Map()
    putSpot(m, 'a', { head: 10, top: 200 })
    saveSpots('u1', m)
    expect(loadSpots('u1').get('a')).toEqual({ head: 10, top: 200 })
    expect(loadSpots('u2').size).toBe(0)
  })

  it('只留最近 60 篇，从最早的开始丢', () => {
    const m = new Map()
    for (let i = 0; i < 70; i++) putSpot(m, 'n' + i, { head: i, top: 0 })
    saveSpots('u1', m)
    const back = loadSpots('u1')
    expect(back.size).toBe(60)
    expect(back.has('n0')).toBe(false)
    expect(back.has('n69')).toBe(true)
  })

  it('再记一次会排到最后，不会被当成最早的丢掉', () => {
    const m = new Map()
    for (let i = 0; i < 60; i++) putSpot(m, 'n' + i, { head: i, top: 0 })
    putSpot(m, 'n0', { head: 999, top: 0 })      // 又看了一次最早那篇
    for (let i = 60; i < 65; i++) putSpot(m, 'n' + i, { head: i, top: 0 })
    saveSpots('u1', m)
    const back = loadSpots('u1')
    expect(back.get('n0')).toEqual({ head: 999, top: 0 })
    expect(back.has('n1')).toBe(false)           // 这篇才是最早的
  })

  it('存坏了 / 没存过都当没有', () => {
    localStorage.setItem('memoket-note-spots:u1', '{bad json')
    expect(loadSpots('u1').size).toBe(0)
    localStorage.setItem('memoket-note-spots:u1', '{"a":null,"b":{"head":3,"top":0}}')
    expect([...loadSpots('u1').keys()]).toEqual(['b'])
  })
})
