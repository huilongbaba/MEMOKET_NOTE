// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { runWritingPlan } from '../../api'

function fakeFetch(frames: string) {
  const enc = new TextEncoder()
  const body = new ReadableStream({ start(c) { c.enqueue(enc.encode(frames)); c.close() } })
  ;(globalThis as any).fetch = async () => new Response(body, { status: 200 })
}

const sse = (event: string, data: object) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`

describe('runWritingPlan 认 AG-UI 事件', () => {
  it('section 内的 TEXT_MESSAGE_CONTENT / STEP_FINISHED 带上当前 note_id 送到 handler', async () => {
    fakeFetch(
      sse('section-start', { section_id: 's1', title: '甲', note_id: 'n1', is_new_note: true, facts: 0 })
      + sse('TEXT_MESSAGE_START', { messageId: 'r1' })
      + sse('TEXT_MESSAGE_CONTENT', { messageId: 'r1', delta: '你好' })
      + sse('TEXT_MESSAGE_CONTENT', { messageId: 'r1', delta: '世界' })
      + sse('STEP_FINISHED', { step: 1, content: '你好世界。' })
      + sse('RUN_FINISHED', { reason: 'complete', content: '你好世界。' })
      + sse('section-done', { section_id: 's1', summary: '', forced: false, blocked: false, blocked_reason: null })
      + sse('done', {}),
    )
    const deltas: [string, string][] = []
    const synced: [string, string][] = []
    await runWritingPlan('p', {
      onDelta: (id, t) => deltas.push([id, t]),
      onNoteContent: (id, c) => synced.push([id, c]),
    })
    expect(deltas).toEqual([['n1', '你好'], ['n1', '世界']])
    expect(synced).toEqual([['n1', '你好世界。'], ['n1', '你好世界。']])
  })
})
