// @vitest-environment jsdom
/**
 * P101（第 819 轮）：**轮次卡读回来**（A，收 P99 B 判②）+ **`guarded` 那一刀的误伤**（B，收 P99 B 判④）。
 *
 * ── A：P99 量清楚、判好形状的那件事 ────────────────────────────────────────
 *   > `harness_rounds` **早就逐轮记着骨架**（round / scores / status / weakest /
 *   > content_len / tool_calls / fired_checks / cite_*），而且 `record_harness_round`
 *   > **自己按 key 修剪到最近 400 行**。实测那一篇 **6 runs / 12 rounds**，
 *   > 界面重开之后 **0 张卡**——**前端一行都没读，也没有那条 API。**
 *   > **判**：不新开表、不把卡整个落库；该补的是**「读回来那条路」**；
 *   > **缺的明细在卡上照实标**。
 *
 * 「缺的明细照实标」**是判据的一部分**，所以这份文件里它占的条数最多：
 * 重建出来的卡**不许假装它有「本轮写出的正文」**，也不许拿库里两个别的数
 * （`revisions_proposed` / `revisions_dropped`）凑出卡上那个 `修订 N 处`
 * （那是 `revisions_applied`，**另一个数**）。
 *
 * ── B：P99 判④那句「判据现成：切走 1 / 不切走 2」──────────────────────────
 * `writeRounds` / `patchRound` 本来就按 noteId 写，被 `currentRef` 一刀切拦住是误伤。
 * **源码那一侧**由 `scripts/check-harness-guard.mts` 判（它读 `App.tsx` 原文）；
 * 这儿判的是**那张表自己**的语义（`guardBlocks` 的正例 / 反例 / 兜底）。
 *
 * ── 这份文件**答不了**什么（别含糊过去）──────────────────────────────────
 *  · **真壳上关掉重开之后屏幕上是什么**：答不了。那是走查里 `steps/rounds101.mjs`
 *    的事（改前 0 张卡 / 改后几张，同一个探针两趟）。
 *  · **那条 API 真的只读**：答不了，那在后端（`backend/tests/test_p101.py`
 *    调完前后三张表指纹逐字相同，而且先喂了一个真会写的反例）。
 *  · **切走那几秒真的留住了没有**：答不了，只有真壳上跑一趟才答得了
 *    （走查 `rounds99 --mode away`：**2 → 2**，P99 那一趟是 2 → 1）。
 */
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import AgentActivity, { type AgentRound } from '../AgentActivity'
import { HARNESS_GUARD, guardBlocks, guardedKeys } from '../../util/harnessGuard'
import {
  citeOrUndefined, mergeRestored, parseFiredChecks, restoredFactsLine, restoredRounds,
  type NoteRoundsPayload, type RestoredRoundRow,
} from '../../util/roundsRestore'

// ═══════════════ 夹具 ═══════════════

const row = (n: number, over: Partial<RestoredRoundRow> = {}): RestoredRoundRow => ({
  round: n,
  scores: { coverage: 2, non_repetition: 1 },
  status: 'continue',
  weakest: 'non_repetition',
  contentLen: 446,
  toolCalls: 3,
  repeatCalls: 0,
  revisionsProposed: 4,
  revisionsDropped: 1,
  depthDropped: 0,
  factsNew: 7,
  factsTotal: 21,
  citeLocated: -1,
  citeMarked: -1,
  citeMatched: -1,
  firedChecks: '',
  at: '2026-09-22T03:04:05+00:00',
  ...over,
})

const payload = (over: Partial<NoteRoundsPayload> = {}): NoteRoundsPayload => ({
  runId: 'run-1',
  at: '2026-09-22T03:04:05+00:00',
  status: 'complete',
  stopped: '',
  rounds: [row(1), row(2)],
  reason: 'ok',
  runsTotal: 6,
  roundsTotal: 12,
  missing: ['本轮写出的正文', '工具调用逐条', '技能名单', '打分器的判词'],
  ...over,
})

/** 一张**活的**卡（这一趟跑出来的，带着明细）。 */
const live = (n: number): AgentRound => ({
  round: n, cleanupOnly: false, revisions: 3, toolCalls: [], toolTruncated: false,
  scores: { coverage: { level: 2, note: '写全了' } }, status: 'continue', weakest: 'coverage',
  policyReasons: [], policy: null, errors: [], dropped: [], streamed: '这一轮真写出来的字',
})

// ═══════════════ A①：重建出来的形状 ═══════════════

describe('A① 从库里重建：有的摆出来，没有的一个都不编', () => {
  it('两行轮次 → 两张卡，round 逐个对得上', () => {
    const rs = restoredRounds(payload())
    expect(rs.map((r) => r.round)).toEqual([1, 2])
  })

  it('每张卡都挂着 `restored` —— **这就是「照实标」那个记号**', () => {
    for (const r of restoredRounds(payload())) expect(r.restored).toBeTruthy()
  })

  it('**「本轮写出的正文」一个字都没有**（库里就没存）', () => {
    for (const r of restoredRounds(payload())) expect(r.streamed).toBeUndefined()
  })

  it('工具调用**逐条**没有（只有一个次数，摆在 facts 那一行里）', () => {
    for (const r of restoredRounds(payload())) expect(r.toolCalls).toEqual([])
  })

  it('技能 / 策略理由 / 报错 / 丢弃 / 阶段输出 **一样都不编**', () => {
    for (const r of restoredRounds(payload())) {
      expect(r.skills).toBeUndefined()
      expect(r.policyReasons).toEqual([])
      expect(r.policy).toBeNull()
      expect(r.errors).toEqual([])
      expect(r.dropped).toEqual([])
      expect(r.phaseText).toBeUndefined()
      expect(r.steer).toBeUndefined()
    }
  })

  it('档位是真的，**判词是空串**（库里存的是 `{维度: 档位}`）', () => {
    const r = restoredRounds(payload())[0]
    expect(r.scores.coverage.level).toBe(2)
    expect(r.scores.coverage.note).toBe('')
    expect(r.weakest).toBe('non_repetition')
  })

  it('`revisions` **不拿库里那两个数凑**：卡上那个是 `applied`，库里是 `proposed`/`dropped`', () => {
    const r = restoredRounds(payload())[0]
    expect(r.revisions).toBe(0)                       // 不摆（渲染那一侧整条不出现）
    expect(r.restored!.facts).toContain('提出修订 4 处')  // 真实的那两个数用自己的名字
    expect(r.restored!.facts).toContain('丢弃 1 处')
  })

  it('`missing` 逐条带到卡上（照实标的那几样）', () => {
    expect(restoredRounds(payload())[0].restored!.missing).toContain('本轮写出的正文')
    expect(restoredRounds(payload())[0].restored!.missing).toContain('打分器的判词')
  })
})

// ═══════════════ A②：三档「读不到」分得开 ═══════════════

describe('A② 「选不到 ≠ 没有」：三档分得开', () => {
  it('`reason=no_rounds` ⇒ 空（这一篇真没跑过）', () => {
    expect(restoredRounds(payload({ reason: 'no_rounds', rounds: [] }))).toEqual([])
  })
  it('`reason=no_run_id` ⇒ 空，**而且它不是「没跑过」**（回包里 roundsTotal 还在）', () => {
    const p = payload({ reason: 'no_run_id', rounds: [], roundsTotal: 12 })
    expect(restoredRounds(p)).toEqual([])
    expect(p.roundsTotal).toBe(12)
  })
  it('`null` / `undefined` ⇒ 空，不抛', () => {
    expect(restoredRounds(null)).toEqual([])
    expect(restoredRounds(undefined)).toEqual([])
  })
  it('`reason=ok` 但一轮都没有 ⇒ 空', () => {
    expect(restoredRounds(payload({ rounds: [] }))).toEqual([])
  })
})

// ═══════════════ A③：`cite_*` 的 -1 和 0 不许长成同一个数 ═══════════════

describe('A③ `cite_*`：`-1`（没走到那一步）和 `0`（一句可引的都没有）分开', () => {
  it('`-1` → `undefined`（那一格整条不渲染）', () => {
    expect(citeOrUndefined(-1)).toBeUndefined()
    expect(restoredRounds(payload())[0].citeLocated).toBeUndefined()
  })
  it('`0` → `0`（**要显示的那一档**：「没有可直接引的编号」）', () => {
    expect(citeOrUndefined(0)).toBe(0)
    const rs = restoredRounds(payload({ rounds: [row(1, { citeLocated: 0, citeMarked: 0, citeMatched: 0 })] }))
    expect(rs[0].citeLocated).toBe(0)
  })
  it('正数原样带过来', () => {
    const rs = restoredRounds(payload({ rounds: [row(1, { citeLocated: 5, citeMarked: 3, citeMatched: 2 })] }))
    expect([rs[0].citeLocated, rs[0].citeMarked, rs[0].citeMatched]).toEqual([5, 3, 2])
  })
})

// ═══════════════ A④：`facts` 那一行 / `fired_checks` ═══════════════

describe('A④ 库里**有**的那几个数：`0 次` 和「没记」在这一行上是两回事', () => {
  it('零的那几样整条不写（不摆一串 `查了 0 次`）', () => {
    const s = restoredFactsLine(row(1, { toolCalls: 0, revisionsProposed: 0, depthDropped: 0, factsTotal: 0 }))
    expect(s).toBe('这一轮结束时正文 446 字')
  })
  it('非零的逐样摆出来', () => {
    const s = restoredFactsLine(row(1, { toolCalls: 3, repeatCalls: 1, depthDropped: 2 }))
    expect(s).toContain('agent 查了 3 次')
    expect(s).toContain('其中 1 次重复')
    expect(s).toContain('2 发检索被深度门丢掉')
    expect(s).toContain('材料 21 条')
  })
  it('`fired_checks`：解得出就是名单，**解不出当空、不抛**', () => {
    expect(parseFiredChecks('["citations_exist","no_placeholder"]')).toEqual(['citations_exist', 'no_placeholder'])
    expect(parseFiredChecks('')).toEqual([])
    expect(parseFiredChecks('{不是 JSON')).toEqual([])
    expect(parseFiredChecks('{"a":1}')).toEqual([])
    expect(parseFiredChecks('[1,2,"x"]')).toEqual(['x'])
  })
})

// ═══════════════ A⑤：**骨架不许盖住全量** ═══════════════

describe('A⑤ `mergeRestored`：活的卡一张都不许被盖住', () => {
  it('内存里已经有卡 ⇒ **原样返回那一份，连引用都不换**', () => {
    const cur = [live(1), live(2)]
    expect(mergeRestored(cur, restoredRounds(payload()))).toBe(cur)
  })
  it('内存里是空的 ⇒ 摆读回来的那一叠', () => {
    const r = restoredRounds(payload())
    expect(mergeRestored([], r)).toBe(r)
  })
  it('两边都空 ⇒ 还是那个空的（不造新数组）', () => {
    const cur: AgentRound[] = []
    expect(mergeRestored(cur, [])).toBe(cur)
  })
})

// ═══════════════ A⑥：真挂一次，看屏幕上那几个字 ═══════════════

describe('A⑥ 真挂 `AgentActivity`：用户看得出这是读回来的', () => {
  let host: HTMLDivElement
  beforeEach(() => { host = document.createElement('div'); document.body.appendChild(host) })
  afterEach(() => { host.remove() })

  const render = (rounds: AgentRound[]) => {
    const root = createRoot(host)
    act(() => { root.render(<AgentActivity rounds={rounds} status="" running={false} />) })
    const t = host.textContent ?? ''
    act(() => { root.unmount() })
    return t
  }

  it('读回来的卡上**白纸黑字**写着它是读回来的', () => {
    expect(render(restoredRounds(payload()))).toContain('这张卡是从库里读回来的骨架')
  })
  it('**逐条写着库里没有哪几样**', () => {
    const t = render(restoredRounds(payload()))
    expect(t).toContain('库里没有')
    expect(t).toContain('本轮写出的正文')
    expect(t).toContain('打分器的判词')
  })
  it('**不摆「本轮写出的正文」那一块**（那正是它没有的东西）', () => {
    const t = render(restoredRounds(payload()))
    expect(t).not.toContain('本轮写出的正文（')
  })
  it('**不摆「修订 N 处」**（那个数库里没有）', () => {
    expect(render(restoredRounds(payload()))).not.toContain('修订 0 处')
  })
  it('**不摆「最弱是「X」：判词」**（判词是空串）', () => {
    expect(render(restoredRounds(payload()))).not.toContain('最弱是')
  })
  it('**不摆「N 条代码判据全过」**（`checksTotal` 库里没有，摆出来就是编）', () => {
    expect(render(restoredRounds(payload()))).not.toContain('条代码判据全过')
  })
  it('库里**有**的那几个数真的摆在屏幕上', () => {
    const t = render(restoredRounds(payload()))
    expect(t).toContain('这一轮结束时正文 446 字')
    expect(t).toContain('agent 查了 3 次')
  })
  it('**活的卡上一个字都没多**（那条横条只属于读回来的）', () => {
    const t = render([live(1)])
    expect(t).not.toContain('这张卡是从库里读回来的骨架')
    expect(t).toContain('修订 3 处')
    expect(t).toContain('本轮写出的正文')
  })
  it('反例：把 `restored` 摘掉 ⇒ 那条横条当场没了（证明它是靠 `restored` 出现的）', () => {
    const rs = restoredRounds(payload()).map((r) => ({ ...r, restored: undefined }))
    expect(render(rs)).not.toContain('这张卡是从库里读回来的骨架')
  })
})

// ═══════════════ B：那一刀拦谁放谁 ═══════════════

describe('B `guarded` 那一刀：误伤治了没有', () => {
  it('22 条 handler 一条不少地归了档', () => {
    expect(Object.keys(HARNESS_GUARD)).toHaveLength(22)
  })
  // ⚠️ **这三个数 P103 动过**（11 / 10 / 1 → 12 / 7 / 3）：P103 A 把 `onSkeleton`
  //    挪进 `rounds`，B 把 `onCost` / `onCrossRun` 挪进 `self`。**照实改，不留旧数**
  //    ——留着的话这条会对着治好的代码红，而它红的理由跟对错无关。
  it('放行 12 条 / 照拦 7 条 / 自理 3 条（P103 之后）', () => {
    expect(guardedKeys('rounds')).toHaveLength(12)
    expect(guardedKeys('blocked')).toHaveLength(7)
    expect(guardedKeys('self')).toEqual(['onCost', 'onCrossRun', 'onDone'])
  })
  it('**P99 实拍那一条**（`onDelta` 的 `streamed`）从此不拦', () => {
    expect(guardBlocks('onDelta')).toBe(false)
  })
  it('动正文那几条**照旧拦**（放行就是「A 的内容写进 B」当场长回来）', () => {
    for (const k of ['onRevision', 'onInsertAt', 'onTextEnd', 'onRoundEnd', 'onScrub', 'onDedup']) {
      expect(guardBlocks(k), k).toBe(true)
    }
  })
  it('纯记账那几条一条不落地放行', () => {
    for (const k of ['onPhase', 'onPhaseDelta', 'onPolicy', 'onDropped', 'onSkills']) {
      expect(guardBlocks(k), k).toBe(false)
    }
  })
  it('表里没有的键 ⇒ **拦**（保守那一侧，不是静默放行）', () => {
    expect(guardBlocks('onSomethingNewNobodyFiled')).toBe(true)
  })
  it('每一条都写了「为什么」（至少 8 个字）', () => {
    for (const [k, v] of Object.entries(HARNESS_GUARD)) expect(v.why.length, k).toBeGreaterThanOrEqual(8)
  })
})
