/**
 * P33 #1：轮次卡片上同一段诊断重复三遍（P31 走查问题 #5）。
 *
 * 要守住的性质**只有两条**，但它们正好是反方向的一对：
 *   ① 逐字一样的两处，只许说一遍（不然右栏是一堵墙）；
 *   ② 不一样的两处，**一个字都不许折**（折了就是在告诉用户
 *      「那两句是同一句」，而那是句假话——比多读一遍严重得多）。
 *
 * 真库量出来的分母（`p33/m1_wall.py`，`harness_rounds` 489 行）：
 *   · 有「最弱是」那一段的轮 **429**，其中判据短路轮（A ≡ B）**261 = 60.8%**；
 *   · 会显示「上一轮诊断」的卡片 **311**，C ≡ 上一张卡的 A **311 = 100.0%**；
 *   · 三处同一句 **191 = 61.4%**。
 */
import { describe, expect, it } from 'vitest'

import actSrc from '../../components/AgentActivity.tsx?raw'
import {
  sameDiag, stripDim, steerEchoedByPrev, weakestEchoedByCheck,
  type AgentRound,
} from '../../components/AgentActivity'

// P22 `e78306202d78` r3 那条 `citations_present` 的判词，逐字（198 字——
// 「一堵墙」说的就是这一段乘以三）。
const NOTE = '这一轮写了 439 字，手上有 15 条材料，正文里一个 [事实编号] 都没有'
  + '（引托盘里的笔记时用它开头的 [标题](note://id) 也算）。'
  + '而这 439 字里**没有一句**能在材料里找到逐字的出处（日期、数量、原话都对不上），'
  + '所以编号补不出来，别去凑。要做的是另一件：**把这一段改写成材料里真有的那几条**'
  + '（把编号和它说的事一起搬进来），对不上材料的判断就收住别再往下铺。'

function round(over: Partial<AgentRound> = {}): AgentRound {
  return {
    round: 1, cleanupOnly: false, revisions: 0, toolCalls: [], toolTruncated: false,
    scores: {}, status: '', weakest: null, policyReasons: [], policy: null,
    errors: [], dropped: [], ...over,
  }
}

/** 判据短路轮：`middleware/checks.py` 伪造单维 0 分，`note` 就是 `Verdict.message`。 */
function shortCircuit(): AgentRound {
  return round({
    round: 2,
    weakest: 'factual_grounding',
    scores: { factual_grounding: { level: 0, note: NOTE } },
    checkHits: [{ check: 'citations_present', dimension: 'factual_grounding', note: NOTE, ran: 12 }],
    checksTotal: 17,
  })
}

describe('sameDiag：逐字比，只归一化空白（P33 #1）', () => {
  it('一样就是一样', () => {
    expect(sameDiag(NOTE, NOTE)).toBe(true)
    expect(sameDiag('  a  b \n c ', 'a b c')).toBe(true)
  })

  it('空串永远算不一样——空跟空对上会把「这一轮没诊断」折成「跟上面一样」', () => {
    expect(sameDiag('', '')).toBe(false)
    expect(sameDiag(undefined, undefined)).toBe(false)
    expect(sameDiag('   ', '')).toBe(false)
  })

  it('差一个字就分开列（判据宁可窄一点）', () => {
    expect(sameDiag(NOTE, NOTE + '。')).toBe(false)
    expect(sameDiag(NOTE, NOTE.slice(0, -1))).toBe(false)
  })
})

describe('A ≡ B：最弱那一段就是同一张卡上的 ⚑ 判词（P33 #1）', () => {
  it('判据短路轮：折', () => {
    expect(weakestEchoedByCheck(shortCircuit())).toBe(true)
  })

  it('判据响了、但真打了分（卡死放行 / judge_floor）：**不折**', () => {
    // 这一档 `st.ev` 是打分器给的真分，六维俱全，判词跟判据那句话不是一回事。
    const r = shortCircuit()
    r.scores = {
      factual_grounding: { level: 0, note: '这几段的判断都没有对应的材料，读者没法核对。' },
      non_repetition: { level: 2, note: '没有重复。' },
    }
    expect(weakestEchoedByCheck(r)).toBe(false)
  })

  it('判词一样但维度不是同一维：不折', () => {
    const r = shortCircuit()
    r.checkHits = [{ check: 'no_repeated_lists', dimension: 'non_repetition', note: NOTE, ran: 14 }]
    expect(weakestEchoedByCheck(r)).toBe(false)
  })

  it('这一轮压根没有判据命中：不折', () => {
    const r = shortCircuit()
    r.checkHits = []
    expect(weakestEchoedByCheck(r)).toBe(false)
  })
})

describe('C ≡ 上一张卡的 A：「上一轮诊断」就是上面那句（P33 #1）', () => {
  // `State.steer` = `bag[focus] + ": " + bag[focus_note]`，而 `loop.py:157-158`
  // 写的正是上一轮 `st.ev` 的 `weakest` / `_weak_note(st)` —— 逐字就是 A。
  const prev = shortCircuit()
  const next = round({
    round: 3, steer: `factual_grounding: ${NOTE}`, steerDim: 'factual_grounding',
  })

  it('结构性恒等的那一档：折', () => {
    expect(steerEchoedByPrev(next, prev)).toBe(true)
  })

  it('没有上一张卡（第 1 轮）：不折', () => {
    expect(steerEchoedByPrev(next, undefined)).toBe(false)
  })

  it('上一张卡是「开跑前」那张（没有分、没有 weakest）：不折', () => {
    expect(steerEchoedByPrev(next, round({ round: 0 }))).toBe(false)
  })

  it('维度对不上就不折——「就是上面那句」在那种时候是句假话', () => {
    expect(steerEchoedByPrev({ ...next, steerDim: 'non_repetition' }, prev)).toBe(false)
  })

  it('诊断换过了（中间被修订改了措辞）：不折，全文照出', () => {
    expect(steerEchoedByPrev({ ...next, steer: 'factual_grounding: 换了一句别的话' }, prev))
      .toBe(false)
  })

  it('`steer` 是空的（打分器给了维度名却没给话）：不折', () => {
    expect(steerEchoedByPrev({ ...next, steer: '' }, prev)).toBe(false)
  })
})

describe('stripDim：维度名已经单独显示过一次，不许在同一行再出现', () => {
  it('切第一个 ": "', () => {
    expect(stripDim(`factual_grounding: ${NOTE}`)).toBe(NOTE)
  })

  it('判词自己带冒号也只切第一个', () => {
    expect(stripDim('non_repetition: 重复的是：那两段结尾')).toBe('重复的是：那两段结尾')
  })

  it('没有前缀就原样回', () => {
    expect(stripDim(NOTE)).toBe(NOTE)
  })
})

describe('源码钉：折起来的那一份原话不许丢（P33 #1）', () => {
  it('两处都把全文塞进 title', () => {
    // 「折」= 少显示一遍，不是「删掉一份」：鼠标停上去还要看得见原话。
    expect(actSrc).toContain('title={steerEchoedByPrev(r, sorted[i - 1]) ? stripDim(r.steer) : undefined}')
    expect(actSrc).toContain('title={weakestEchoedByCheck(r) ? r.scores[r.weakest].note : undefined}')
  })

  it('比的是排序之后的前一张卡，不是 `rounds` 里的前一项', () => {
    // 事件是分散到达的，`rounds` 数组的顺序按到达排——拿它的前一项去比
    // 「上一轮诊断」，比到的可能是第 0 轮那张。
    expect(actSrc).toContain('const sorted = [...rounds].sort((a, b) => a.round - b.round)')
    expect(actSrc).toContain('sorted.map((r, i) =>')
  })
})
