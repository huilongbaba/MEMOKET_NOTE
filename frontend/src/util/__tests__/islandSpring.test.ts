import { describe, expect, it } from 'vitest'
import { advanceIslandSpring, islandSpringSettled, ISLAND_RESPONSE } from '../useIslandMotion'

describe('critical island spring', () => {
  it('preserves position and velocity exactly at a retarget instant', () => {
    const moving = advanceIslandSpring({ position: 240, velocity: 0 }, 640, 0.12, ISLAND_RESPONSE.open)
    expect(moving.position).toBeGreaterThan(240)
    expect(moving.velocity).toBeGreaterThan(0)
    expect(advanceIslandSpring(moving, 240, 0, ISLAND_RESPONSE.close)).toEqual(moving)
    const after = advanceIslandSpring(moving, 240, 0.000001, ISLAND_RESPONSE.close)
    expect(after.position).toBeCloseTo(moving.position + moving.velocity * 0.000001, 6)
    expect(after.velocity).toBeGreaterThan(0)
  })

  it('gives the same trajectory at 30, 60 and 120 Hz as one analytical step', () => {
    const start = { position: 44, velocity: 140 }
    const exact = advanceIslandSpring(start, 460, 0.3, ISLAND_RESPONSE.open)
    for (const fps of [30, 60, 120]) {
      let axis = start
      for (let frame = 0; frame < fps * 0.3; frame++) axis = advanceIslandSpring(axis, 460, 1 / fps, ISLAND_RESPONSE.open)
      expect(axis.position).toBeCloseTo(exact.position, 8)
      expect(axis.velocity).toBeCloseTo(exact.velocity, 8)
    }
  })

  it('opens monotonically from rest and eventually settles with no forced duration', () => {
    let axis = { position: 240, velocity: 0 }
    for (let frame = 0; frame < 120; frame++) {
      const next = advanceIslandSpring(axis, 640, 1 / 120, ISLAND_RESPONSE.open)
      expect(next.position).toBeGreaterThanOrEqual(axis.position)
      expect(next.position).toBeLessThanOrEqual(640)
      axis = next
    }
    expect(islandSpringSettled(axis, 640)).toBe(true)
  })

  it('reverses smoothly and settles independently in width and height', () => {
    const width = advanceIslandSpring({ position: 240, velocity: 0 }, 640, 0.09, ISLAND_RESPONSE.open)
    const height = advanceIslandSpring({ position: 44, velocity: 0 }, 460, 0.09, ISLAND_RESPONSE.open)
    const closedWidth = advanceIslandSpring(width, 240, 0.8, ISLAND_RESPONSE.close)
    const closedHeight = advanceIslandSpring(height, 44, 0.8, ISLAND_RESPONSE.close)
    expect(islandSpringSettled(closedWidth, 240)).toBe(true)
    expect(islandSpringSettled(closedHeight, 44)).toBe(true)
    expect(islandSpringSettled({ position: 240.1, velocity: 4 }, 240)).toBe(false)
    expect(islandSpringSettled({ position: 240.5, velocity: 0 }, 240)).toBe(false)
  })
})
