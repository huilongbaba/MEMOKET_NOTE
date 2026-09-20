import { describe, expect, it } from 'vitest'
import agentActivitySrc from '../../components/AgentActivity.tsx?raw'
// @ts-expect-error vitest 跑在 node 上；前端 tsconfig 没带 node 类型（styles.css 走 vite 的 css 管道，`?raw` 在 vitest 里拿到空串，只能读文件）
import { readFileSync } from 'node:fs'
// @ts-expect-error 同上：node 的类型不在前端 tsconfig 里
import { fileURLToPath } from 'node:url'
import { consumeHarnessStream } from '../../api'
import { checkHitKind, withCheckHit, type CheckHit } from '../agentRound'

/** P58 走查 #1：轮次卡片上那句「这一轮没再花模型调用去打分」只分了两档
 * （`stuck_rounds` / 其余），于是**放行轮掉进了「没打分」那一句**——
 * 而放行的全部目的就是让打分器跑起来。`judge_floor`（P24 加的）一直是这样，
 * P58 的 `advisory` 又会往这一档里再加一批。字面反了的一句话比不说更糟
 * （跟 P35 走查 #7 停机那条写着「照常打分」是同一个形状，只是在另一支上）。 */

const hit = (o: Partial<CheckHit> = {}): CheckHit =>
  ({ check: 'citations_present', ran: 11, dimension: 'factual_grounding', note: '没有出处', ...o })

describe('checkHitKind：四档互斥、穷尽（P58 走查 #1）', () => {
  it('真短路：这一轮确实没打分', () => {
    expect(checkHitKind(hit())).toBe('shortCircuit')
  })

  it('advisory：报了但照常打分', () => {
    expect(checkHitKind(hit({ advisory: true }))).toBe('released')
  })

  it('judge_floor 放行：报了但照常打分——**P58 之前这一档被说成没打分**', () => {
    expect(checkHitKind(hit({ judge_floor: 2 }))).toBe('released')
  })

  it('卡死放行：自己那一句（连着 N 轮改不动）', () => {
    expect(checkHitKind(hit({ stuck_rounds: 3 }))).toBe('stuck')
  })

  it('收工通知：`stopped` 压过一切——它不是「这一轮」的事', () => {
    expect(checkHitKind(hit({ stopped: true, stuck_rounds: 3 }))).toBe('stopped')
    expect(checkHitKind(hit({ stopped: true, advisory: true }))).toBe('stopped')
  })

  it('反向闸：advisory=false / judge_floor=0 不许被当成放行', () => {
    expect(checkHitKind(hit({ advisory: false }))).toBe('shortCircuit')
    expect(checkHitKind(hit({ judge_floor: 0 }))).toBe('shortCircuit')
  })
})

describe('接线洞：advisory 从 SSE 一路到卡片（P58 A）', () => {
  it('事件层不许把 advisory / judge_floor 吃掉', async () => {
    const hits: CheckHit[] = []
    const sse = (frames: { event: string; data: unknown }[]) =>
      new Response(frames.map((f) => `event: ${f.event}\ndata: ${JSON.stringify(f.data)}\n\n`).join(''),
                   { headers: { 'Content-Type': 'text/event-stream' } })
    await consumeHarnessStream(sse([
      { event: 'STEP_STARTED', data: { step: 1, label: '第一轮' } },
      { event: 'CUSTOM', data: { name: 'check_hit', value: {
        round: 1, check: 'citations_present', ran: 11, dimension: 'factual_grounding',
        note: '编号补不出来，别去凑。', advisory: true } } },
      { event: 'CUSTOM', data: { name: 'check_hit', value: {
        round: 1, check: 'no_placeholder', ran: 3, dimension: 'factual_grounding',
        note: '有占位句', judge_floor: 2 } } },
      { event: 'RUN_FINISHED', data: { reason: 'complete' } },
    ]), { onCheckHit: (d) => hits.push(d) })

    expect(hits.map((h) => h.advisory)).toEqual([true, undefined])
    expect(hits.map((h) => h.judge_floor)).toEqual([undefined, 2])
    expect(hits.map(checkHitKind)).toEqual(['released', 'released'])
  })

  it('两条都攒在同一轮的卡片上，后到的不许盖掉先到的', () => {
    let round: { checkHits?: CheckHit[] } = {}
    round = withCheckHit(round, hit({ advisory: true }))
    round = withCheckHit(round, hit({ check: 'no_placeholder' }))
    expect(round.checkHits?.map(checkHitKind)).toEqual(['released', 'shortCircuit'])
  })
})

describe('面板真的用上了这个分档（不是建了函数不用）', () => {
  // §21「建了判据不等于用了判据」：上面那些全绿、而 AgentActivity 还在写
  // `h.stuck_rounds ? … : …` 的话，用户看到的仍然是那句假话。
  const src = agentActivitySrc

  it('AgentActivity 按 checkHitKind 分档，不再按 stuck_rounds 三元', () => {
    expect(src).toContain("checkHitKind(h) === 'released'")
    expect(src).not.toMatch(/\{h\.stuck_rounds \? \(/)
  })

  it('released 那一档说的是「照常打分」，而「没打分」那句只归真短路那一档', () => {
    const released = src.slice(src.indexOf("checkHitKind(h) === 'released'"),
                               src.indexOf('代码判据 <b>{checkLabel(h.check)}</b> 判了'))
    expect(released).toContain('照常打分')
    // **注释里提它不算**：这个文件里有两处注释引着那句话（P35 的实拍、P58 这条改动
    // 自己的说明）。量的是**渲染出来的字**，所以先把 JSX 注释块剥掉。
    const rendered = (s: string) => s.replace(/\{\/\*[\s\S]*?\*\/\}/g, '').replace(/^\/\/.*$/gm, '')
    expect(rendered(released)).not.toContain('这一轮没再花模型调用去打分')
    // 反向：真短路那一档得**还留着**这句话（删了就成了「哪一档都没说清」）
    expect(rendered(src.slice(src.indexOf('代码判据 <b>{checkLabel(h.check)}</b> 判了'))))
      .toContain('这一轮没再花模型调用去打分')
  })
})

// ============ P58 走查 #3：后端拼进来的换行，在壳上得真的换行 ============
//
// 实拍 `p58-b7-2-ro-toast-light.png`：把一天的目录 chmod 500 再按「删掉这一天」，
// 后端 `journey.delete_day` 抛的是「抬头一行 + 5 行 `名字：原因`」（P56 ④ 收的那一版，
// `\n` 拼的），**而 toast 上它是一整坨**——`.toast` 没有 `white-space`，
// 5 行折成一段「thumbs：Permission denied report.json：Permission denied …」。
// P56 量的是**拼出来的串**（正文行里绝对路径 7 → 0，那个数是对的），
// 没量**看到的那一屏**。两件事各有各的闸，这就是后一件那条。

describe('toast 里的换行（P58 走查 #3）', () => {
  const css: string = readFileSync(
    fileURLToPath(new URL('../../styles.css', import.meta.url)), 'utf8')
  const block = css.slice(css.indexOf('.toast {'), css.indexOf('.toast.error'))

  it('`.toast` 声明了 white-space: pre-line', () => {
    expect(block).toMatch(/white-space:\s*pre-line/)
  })

  it('不是 `pre` / `nowrap`——那两个会让长行撑破 360px 的 toaster', () => {
    expect(block).not.toMatch(/white-space:\s*(pre|nowrap)\s*;/)
  })

  it('反例：后端那条消息真的带着换行（不然这条闸管的是个不存在的局面）', () => {
    // 拼法逐字照 `backend/app/routers/journey.py` 的 `delete_day`
    const msg = '这一天没删干净，/x/y 下面这 2 个删不掉：\n'
      + ['a：Permission denied', 'b：Directory not empty'].join('\n')
    expect(msg.split('\n')).toHaveLength(3)
  })
})
