import { describe, expect, it } from 'vitest'
import { consumeHarnessStream } from '../../api'

/** 用户实拍：Agent 运行面板里「第 0 轮」排在「第 1 轮」下面——活动快照 / 工具结果事件不带轮次，
 * 之前一律记成第 0 轮。 */
function sse(frames: { event: string; data: unknown }[]): Response {
  const text = frames.map((f) => `event: ${f.event}\ndata: ${JSON.stringify(f.data)}\n\n`).join('')
  return new Response(text, { headers: { 'Content-Type': 'text/event-stream' } })
}

describe('harness 事件流的轮次归属', () => {
  it('快照和工具结果跟着最近一次 STEP_STARTED 的轮次', async () => {
    const phases: number[] = []; const tools: number[] = []
    await consumeHarnessStream(sse([
      { event: 'ACTIVITY_SNAPSHOT', data: { content: '开跑前' } },
      { event: 'STEP_STARTED', data: { step: 1, label: '第一轮' } },
      { event: 'ACTIVITY_SNAPSHOT', data: { content: '在写…' } },
      { event: 'TOOL_CALL_RESULT', data: { toolName: 'recall', args: {}, content: 'x' } },
      { event: 'STEP_STARTED', data: { step: 2, label: '第二轮' } },
      { event: 'ACTIVITY_SNAPSHOT', data: { content: '打分' } },
      { event: 'RUN_FINISHED', data: { reason: 'complete' } },
    ]), { onPhase: (d) => phases.push(d.round), onToolCalls: (d) => tools.push(d.round) })
    expect(phases).toEqual([0, 1, 1, 2, 2])
    expect(tools).toEqual([1])
  })
})

describe('判据卡满之后的那条 check_hit', () => {
  it('stuck_rounds 一路传到面板，不被事件层吃掉', async () => {
    const hits: { dimension: string; note: string; stuck_rounds?: number }[] = []
    await consumeHarnessStream(sse([
      { event: 'STEP_STARTED', data: { step: 1, label: '第一轮' } },
      { event: 'CUSTOM', data: { name: 'check_hit', value: { dimension: 'factual_grounding', note: '有占位句' } } },
      { event: 'STEP_STARTED', data: { step: 3, label: '第三轮' } },
      // 连着卡满之后后端不再短路，事件照发、多带一个 stuck_rounds
      { event: 'CUSTOM', data: { name: 'check_hit', value: { dimension: 'factual_grounding', note: '有占位句', stuck_rounds: 3 } } },
      { event: 'RUN_FINISHED', data: { reason: 'complete' } },
    ]), { onCheckHit: (d) => hits.push(d) })

    expect(hits.map((h) => h.stuck_rounds)).toEqual([undefined, 3])
    expect(hits[1].note).toBe('有占位句')
  })
})
