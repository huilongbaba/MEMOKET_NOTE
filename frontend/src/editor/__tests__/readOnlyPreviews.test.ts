// @vitest-environment jsdom
import { Compartment, EditorState, type StateField } from '@codemirror/state'
import type { DecorationSet } from '@codemirror/view'
import { markdown } from '@codemirror/lang-markdown'
import { GFM } from '@lezer/markdown'
import { describe, expect, it, vi } from 'vitest'
import { mermaidPreview } from '../mermaid'
import { tablePreview } from '../tablePreview'

vi.mock('mermaid', () => ({ default: {
  initialize: vi.fn(),
  parse: vi.fn(async () => true),
  render: vi.fn(async () => ({ svg: '<svg xmlns="http://www.w3.org/2000/svg"><text>Review diagram</text></svg>' })),
} }))

const cases = [
  { name: 'Mermaid', source: '```mermaid\ngraph TD\nA-->B\n```', field: mermaidPreview },
  { name: 'table', source: '| Item | Count |\n| --- | ---: |\n| Notes | 3 |', field: tablePreview },
]
type PreviewWidget = { toDOM(): HTMLElement; ignoreEvent(): boolean }
function widget(state: EditorState, field: StateField<DecorationSet>): PreviewWidget {
  let result: PreviewWidget | undefined
  state.field(field).between(0, state.doc.length, (_from, _to, decoration) => {
    if (decoration.spec.widget) result = decoration.spec.widget as PreviewWidget
  })
  expect(result).toBeDefined()
  return result!
}

describe('read-only Markdown block previews', () => {
  it.each(cases)('renders a first $name block even with the default selection at zero', async ({ name, source, field }) => {
    const state = EditorState.create({ doc: source, extensions: [markdown({ extensions: [GFM] }), field, EditorState.readOnly.of(true)] })
    expect(state.selection.main.head).toBe(0)
    // The source is replaced and the readable block is inserted.
    expect(state.field(field).size).toBe(2)
    const content = widget(state, field).toDOM()
    if (name === 'Mermaid') {
      await vi.waitFor(() => expect(content.querySelector('svg text')?.textContent).toBe('Review diagram'))
      expect(content.textContent).not.toContain('graph TD')
    } else {
      expect(content.querySelector('table')).not.toBeNull()
      expect([...content.querySelectorAll('td')].map(cell => cell.textContent)).toEqual(['Notes', '3'])
      expect(widget(state, field).ignoreEvent()).toBe(true)
    }
    const selected = state.update({ selection: { anchor: 0, head: source.length } }).state
    expect(selected.field(field).size).toBe(2)
  })

  it.each(cases)('keeps editable $name source visible inside the block and previews it outside', ({ name, source, field }) => {
    const doc = source + '\n\nFollowing paragraph'
    const state = EditorState.create({ doc, extensions: [markdown({ extensions: [GFM] }), field] })
    expect(state.field(field).size).toBe(0)
    const outside = state.update({ selection: { anchor: doc.length } }).state
    expect(outside.field(field).size).toBe(2)
    if (name === 'table') expect(widget(outside, field).ignoreEvent()).toBe(false)
    expect(outside.update({ selection: { anchor: 1 } }).state.field(field).size).toBe(0)
  })

  it.each(cases)('updates the $name preview when readOnly changes without editing the document or selection', ({ source, field }) => {
    const readOnly = new Compartment()
    let state = EditorState.create({ doc: source, extensions: [markdown({ extensions: [GFM] }), field, readOnly.of(EditorState.readOnly.of(false))] })
    expect(state.field(field).size).toBe(0)
    state = state.update({ effects: readOnly.reconfigure(EditorState.readOnly.of(true)) }).state
    expect(state.field(field).size).toBe(2)
    expect(state.selection.main.head).toBe(0)
    state = state.update({ effects: readOnly.reconfigure(EditorState.readOnly.of(false)) }).state
    expect(state.field(field).size).toBe(0)
  })
})
