import { describe, expect, it } from 'vitest'
import { consumeHarnessStream } from '../../api'
import { withCheckHit } from '../agentRound'

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

describe('批 23 新加的两条 CUSTOM', () => {
  it('成本上限：数字一路传到面板，而且后面那条 done 的 reason 是 cost_cap', async () => {
    const costs: { tokens: number; cap: number; detail: string }[] = []
    let reason = ''
    await consumeHarnessStream(sse([
      { event: 'STEP_STARTED', data: { step: 2, label: '第二轮' } },
      { event: 'CUSTOM', data: { name: 'cost', value: { round: 2, tokens: 520000, cap: 500000, calls: 31, detail: '到了单次跑的上限' } } },
      { event: 'RUN_FINISHED', data: { reason: 'cost_cap', content: '最好那一轮' } },
    ]), { onCost: (d) => costs.push(d), onDone: (r) => { reason = r } })

    // **不是静默截断**：事件说花了多少，done 的 reason 说因此停了，两半都得到。
    expect(costs).toHaveLength(1)
    expect(costs[0].tokens).toBe(520000)
    expect(reason).toBe('cost_cap')
  })

  it('比上一次跑差：报一句，正文不动（只报不回滚）', async () => {
    const worse: { met: number; last_met: number; detail: string }[] = []
    await consumeHarnessStream(sse([
      { event: 'CUSTOM', data: { name: 'cross_run', value: { met: 2, last_met: 3, mean: 1.6, last_mean: 2, dimensions: ['non_repetition'], detail: '这次跑完比上一次差' } } },
      { event: 'RUN_FINISHED', data: { reason: 'complete' } },
    ]), { onCrossRun: (d) => worse.push(d) })

    expect(worse).toHaveLength(1)
    expect([worse[0].last_met, worse[0].met]).toEqual([3, 2])
  })
})

describe('批 24：「这一轮为什么这么跑」的两样（计划 12.1）', () => {
  it('轮次载荷里的 steer 一路到面板，而且「没有检索规划这一步」不能退化成 false', async () => {
    const seen: { round: number; steer?: string; in_plan?: boolean | null }[] = []
    await consumeHarnessStream(sse([
      { event: 'CUSTOM', data: { name: 'round_summary', value: {
        round: 2, max_rounds: 8, revisions_applied: 0,
        steer: 'non_repetition: 同一件事说了两遍', steer_dim: 'non_repetition',
        steer_material: false, steer_in_plan: false, checks_total: 14 } } },
      // 打磨轮压根没有检索规划这一步：后端给的是 null，不是 false
      { event: 'CUSTOM', data: { name: 'round_summary', value: {
        round: 3, max_rounds: 8, revisions_applied: 0,
        steer: 'coherence: 标题层级乱了', steer_dim: 'coherence',
        steer_material: false, steer_in_plan: null, checks_total: 14 } } },
      { event: 'RUN_FINISHED', data: { reason: 'complete' } },
    ]), { onRoundStart: (d) => seen.push({ round: d.round, steer: d.steer, in_plan: d.steer_in_plan }) })

    expect(seen.map((s) => s.round)).toEqual([2, 3])
    expect(seen[0].steer).toContain('同一件事说了两遍')
    // **`false` 和 `null` 不是一回事**：前者是「有这一步但诊断没进去」，
    // 后者是「这一轮压根没有这一步」。混成一个值，面板只能瞎说一句。
    expect(seen[0].in_plan).toBe(false)
    expect(seen[1].in_plan).toBeNull()
  })

  it('一轮里命中好几条判据时，每一条都到得了面板（原来后到的把先到的盖掉）', async () => {
    const hits: { check?: string; ran?: number; stuck_rounds?: number }[] = []
    await consumeHarnessStream(sse([
      { event: 'CUSTOM', data: { name: 'round_summary', value: { round: 4, max_rounds: 8, revisions_applied: 0, checks_total: 14 } } },
      // 先到的是「连着卡满、这一轮放行」的那条，最后才是真正短路的那条
      { event: 'CUSTOM', data: { name: 'check_hit', value: { round: 4, check: 'no_placeholder', ran: 1, dimension: 'factual_grounding', note: '有占位句', stuck_rounds: 3 } } },
      { event: 'CUSTOM', data: { name: 'check_hit', value: { round: 4, check: 'citations_exist', ran: 5, dimension: 'factual_grounding', note: '引用是编的' } } },
      { event: 'RUN_FINISHED', data: { reason: 'complete' } },
    ]), { onCheckHit: (d) => hits.push(d) })

    // 两条判据落在**同一个维度**上——光有 dimension 答不了「哪条判据命中了」
    expect(hits.map((h) => h.check)).toEqual(['no_placeholder', 'citations_exist'])
    expect(hits.map((h) => h.ran)).toEqual([1, 5])
  })
})

describe('批 24：一轮里的判据命中要攒起来（计划 12.1）', () => {
  it('后到的不许把先到的盖掉', () => {
    const stuck = { check: 'no_placeholder', ran: 1, dimension: 'factual_grounding', note: '有占位句', stuck_rounds: 3 }
    const short = { check: 'citations_exist', ran: 5, dimension: 'factual_grounding', note: '引用是编的' }
    // 连着卡满被放行的那条先到，真正短路的那条后到——两条都得留下
    const r1 = withCheckHit({} as { checkHits?: typeof stuck[] }, stuck)
    const r2 = withCheckHit(r1, short)
    expect(r2.checkHits?.map((h) => h.check)).toEqual(['no_placeholder', 'citations_exist'])
    // 原来的轮次对象不许被就地改（setState 要的是新对象）
    expect(r1.checkHits).toHaveLength(1)
  })
})
