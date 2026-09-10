/**
 * 分栏拖拽把手——Trilium 用 Split.js（`services/resizer.ts`），我们 8 行
 * pointermove 就够：宽 5px，默认透明，hover 才显形（theme-next/shell.css:161-168）。
 *
 * `side` 说的是「拖动改变的是哪一侧那栏的宽度」：左栏的把手在它右边，
 * 往右拖左栏变宽；右栏的把手在它左边，往右拖右栏变窄。
 */
import { useRef } from 'react'

export default function Gutter({ side, onResize, onResizeEnd }: {
  side: 'left' | 'right'
  onResize: (delta: number) => void
  onResizeEnd?: () => void
}) {
  const last = useRef(0)
  return (
    <div
      className="gutter"
      role="separator"
      aria-orientation="vertical"
      onPointerDown={(e) => {
        e.preventDefault()
        last.current = e.clientX
        const el = e.currentTarget
        el.setPointerCapture(e.pointerId)
        el.classList.add('dragging')
      }}
      onPointerMove={(e) => {
        if (!e.currentTarget.hasPointerCapture(e.pointerId)) return
        const dx = e.clientX - last.current
        last.current = e.clientX
        onResize(side === 'left' ? dx : -dx)
      }}
      onPointerUp={(e) => {
        e.currentTarget.releasePointerCapture(e.pointerId)
        e.currentTarget.classList.remove('dragging')
        onResizeEnd?.()
      }}
    />
  )
}
