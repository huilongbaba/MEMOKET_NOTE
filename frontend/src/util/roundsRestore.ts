/** 关掉重开之后，**把轮次卡的骨架从库里读回来**（P101 A，收 P99 B 判②）。
 *
 * ── P99 量清楚的那件事 ────────────────────────────────────────────────────
 * > `harness_rounds` **早就逐轮记着骨架**（`round` / `scores` / `status` / `weakest` /
 * > `content_len` / `tool_calls` / `fired_checks` / `cite_*`），而且
 * > `record_harness_round` **自己按 key 修剪到最近 400 行**。实测那一篇
 * > **6 次跑 / 12 行轮次**，界面重开之后 **0 张卡**——**前端一行都没读，也没有那条 API。**
 *
 * 判下来的是：**不新开表、不把卡整个落库**；该补的是**「读回来那条路」**
 * ——只读 API（`GET /api/notes/<id>/rounds`）+ 前端重建骨架，**零迁移 / 零新表 / 零体积增长**。
 *
 * ── **「缺的明细照实标」是判据的一部分，不是文案** ─────────────────────────
 * 重建出来的卡**不许假装它有「本轮写出的正文」**。这份模块因此做三件事：
 *
 *  ① 给每张重建出来的卡挂一个 `restored`（**这张卡是读回来的**），
 *     `AgentActivity` 在卡顶上摆一条虚线横条，逐条写着**库里没有哪几样**；
 *  ② **库里没有的字段一个都不填**——`streamed` / `toolCalls`（逐条）/ `skills` /
 *     `policyReasons` / `errors` / `dropped` / `phaseText` / `steer` 全部留空，
 *     于是那几块**在卡上根本不出现**（不是出现一个空壳）；
 *  ③ **打分器那句判词**库里没有 ⇒ `scores[dim].note` 一律是 `''`。
 *     `AgentActivity` 里「最弱是「X」：判词」那一段的条件正是 `r.scores[r.weakest]?.note`，
 *     空串 ⇒ 那一段不渲染。**宁可少摆，也别把骨架冒充成全量**
 *     （**「读回的是这一段 ≠ 右栏摆的是这一段」**）。
 *
 * ── 库里**有**、而且是真的那几样（重建出来摆得理直气壮）────────────────────
 * 每一维的**档位**（`scores`）/ 这一轮的 `status` / 最弱是哪一维 /
 * 这一轮结束时正文多少字 / agent 查了几次 / 提出和丢弃了几处修订 /
 * 深度门丢了几发 / 材料新增和总数 / 引用覆盖三列 / 哪几条判据命中。
 *
 * ── 它答不了 / 没管什么 ───────────────────────────────────────────────────
 *  · **只读最近那一次跑**：库里那一篇可能有几十次跑（P99 实拍 6 次），
 *    右栏本来摆的就是「最近这一次」那几张。要看更早的是另一件事（没做）。
 *  · **`run_id` 空的那几行读不回来**：那是没挂 `Ledger` 的老跑法，
 *    按 run 分不开（后端回 `reason='no_run_id'`）。**那不是「这一篇没跑过」**。
 *  · **重建不覆盖活的卡**：这一趟内存里已经有卡（刚跑完 / 跑着切走再切回）⇒
 *    **一个字都不动**。活的那份带着明细，读回来的是骨架，**骨架不许盖住全量**。
 */
import type { AgentRound, RestoredMark } from '../components/AgentActivity'

/** 后端 `GET /api/notes/<id>/rounds` 回的那一轮（`schemas.RestoredRound`）。 */
export type RestoredRoundRow = {
  round: number
  scores: Record<string, number>
  status: string
  weakest: string
  contentLen: number
  toolCalls: number
  repeatCalls: number
  revisionsProposed: number
  revisionsDropped: number
  depthDropped: number
  factsNew: number
  factsTotal: number
  citeLocated: number
  citeMarked: number
  citeMatched: number
  firedChecks: string
  at: string
}

/** 整个回包（`schemas.NoteRoundsOut`）。 */
export type NoteRoundsPayload = {
  runId: string
  at: string
  status: string
  stopped: string
  rounds: RestoredRoundRow[]
  reason: string
  runsTotal: number
  roundsTotal: number
  missing: string[]
}

/** `cite_*` 三列：**`-1` 是「这一轮压根没走到那一步」**，`0` 是「算过了、一句可引的都没有」。
 *
 *  `AgentActivity` 里那一格的条件是 `r.citeLocated !== undefined`
 *  （注释里写死了「`0` 是要显示的那一档，用真值判断会把它藏掉」），
 *  所以 `-1` 要变回 `undefined`，**不是变成 0**——两件事不许长成同一个数。 */
export const citeOrUndefined = (n: number): number | undefined => (n < 0 ? undefined : n)

/** 库里**有**的那几个数摆成一行。空着的不写（`0 次` 和「没记」在这一行上是两回事）。 */
export function restoredFactsLine(r: RestoredRoundRow): string {
  const bits: string[] = []
  bits.push(`这一轮结束时正文 ${r.contentLen} 字`)
  if (r.toolCalls > 0) bits.push(`agent 查了 ${r.toolCalls} 次${r.repeatCalls > 0 ? `（其中 ${r.repeatCalls} 次重复）` : ''}`)
  if (r.revisionsProposed > 0) bits.push(`提出修订 ${r.revisionsProposed} 处${r.revisionsDropped > 0 ? `、丢弃 ${r.revisionsDropped} 处` : ''}`)
  if (r.depthDropped > 0) bits.push(`${r.depthDropped} 发检索被深度门丢掉`)
  if (r.factsTotal > 0) bits.push(`材料 ${r.factsTotal} 条${r.factsNew > 0 ? `（这一轮新增 ${r.factsNew} 条）` : ''}`)
  return bits.join(' · ')
}

/** `fired_checks` 那一列（一串 JSON 数组）。**解不出来就当空**，不抛：
 *  这一列是分析用的，一行坏数据不该让整叠卡读不回来。 */
export function parseFiredChecks(s: string): string[] {
  if (!s) return []
  try {
    const v = JSON.parse(s)
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []
  } catch { return [] }
}

/** 这一轮那个「读回来的」记号（形状的唯一定义在 `AgentActivity.RestoredMark`）。 */
export function restoredMark(p: NoteRoundsPayload, r: RestoredRoundRow): RestoredMark {
  return {
    at: p.at || r.at,
    missing: p.missing ?? [],
    facts: restoredFactsLine(r),
    firedChecks: parseFiredChecks(r.firedChecks),
  }
}

/** 回包 → 一叠**骨架卡**。`reason !== 'ok'` / 一轮都没有 ⇒ 空数组。 */
export function restoredRounds(p: NoteRoundsPayload | null | undefined): AgentRound[] {
  if (!p || p.reason !== 'ok' || !p.rounds?.length) return []
  return p.rounds.map((r) => ({
    round: r.round,
    cleanupOnly: false,
    // **不填**：库里存的是 `revisions_proposed` / `revisions_dropped`，
    // 而卡上那个「修订 N 处」是 `revisions_applied`（onRoundStart 给的）。
    // 拿前两个减一下凑出后者是**编**的——两个数真实的名字摆在 `facts` 那一行里。
    revisions: 0,
    toolCalls: [],            // 逐条的调用参数 / 结果库里一个字都没有
    toolTruncated: false,
    // 档位是真的，**判词库里没有** ⇒ 空串。`AgentActivity` 的
    // 「最弱是「X」：判词」那一段条件是 `r.scores[r.weakest]?.note`，空串 ⇒ 不渲染。
    scores: Object.fromEntries(Object.entries(r.scores ?? {}).map(([k, lv]) => [k, { level: lv, note: '' }])),
    status: r.status,
    weakest: r.weakest || null,
    policyReasons: [],
    policy: null,
    errors: [],
    dropped: [],
    citeLocated: citeOrUndefined(r.citeLocated),
    citeMarked: citeOrUndefined(r.citeMarked),
    citeMatched: citeOrUndefined(r.citeMatched),
    restored: restoredMark(p, r),
  }))
}

/** 重建那一叠该不该往这一篇身上放。
 *
 *  **活的卡一张都不许被盖住**：这一趟跑过（或者跑着切走又切回）的那一份带着明细，
 *  读回来的只是骨架。`cur.length > 0` ⇒ 原样返回 `cur`（连引用都不换，
 *  免得 React 那边白重渲染一次）。 */
export function mergeRestored(cur: AgentRound[], restored: AgentRound[]): AgentRound[] {
  if (cur.length) return cur
  if (!restored.length) return cur
  return restored
}
