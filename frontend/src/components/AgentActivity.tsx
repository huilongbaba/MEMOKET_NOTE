import { useState } from 'react'
import type { NoteHarnessToolCall } from '../api'
import Icon from './Icon'
import { dimLabel, checkLabel } from '../editor/dimLabel'
import type { CheckHit } from '../editor/agentRound'

/** 一轮里 agent 干了什么。按轮聚合而不是按事件平铺——用户关心的是
 * "这一轮它查了什么、改了什么、打了几分、然后决定下一轮怎么跑"这条
 * 因果链，事件流水账反而看不出所以然。 */
export type AgentRound = {
  round: number
  /** 跳过续写、只做重复清理的轮次。这类轮次不会有续写增量，
   * 标出来免得用户以为卡住了。 */
  cleanupOnly: boolean
  revisions: number
  toolCalls: NoteHarnessToolCall[]
  toolTruncated: boolean
  scores: Record<string, { level: number; note: string }>
  status: string
  weakest: string | null
  /** 这一轮结束后策略控制器做的调整。空数组 = 没调整（一切正常）。 */
  policyReasons: string[]
  /** 第 0 轮（开跑前按历史记录定的初始策略）可能只带部分字段，所以都是可选的 */
  policy: Partial<{ tool_iters: number; continue_temperature: number;
                    max_revisions: number; require_verification: boolean }> | null
  errors: string[]
  /** 被防线丢弃的修订及原因。跟 errors 分开：这是防线正常起作用，
   * 混在报错里会让界面变成一片红。 */
  dropped: string[]
  /** 代码判据（不是模型）当场判这一轮不合格。命中时这一轮**不会**再花一次
   * 模型调用去打分——所以要标出来，否则用户看到一个 0 分却不知道是谁判的。
   *
   * **一轮可以命中好几条**（连着卡住被放行的那几条 + 最后短路的那一条），
   * 原来这里是单数、后到的把先到的盖掉：判据真的命中了，界面上却看不见——
   * 跟「建了判据不等于用了判据」是同一个形状。 */
  checkHits?: CheckHit[]
  /** 这个模式一共有几条代码判据。没有分母的话，「这一轮全过了」跟
   * 「判据根本没跑」在界面上长得一模一样。 */
  checksTotal?: number
  /** 上一轮诊断出了什么、它这一轮去了哪儿（后端计划 12.1）。 */
  steer?: string
  steerDim?: string
  steerMaterial?: boolean
  /** `undefined` = 这一轮没有检索规划这一步（打磨 / 只清理）。 */
  steerInPlan?: boolean | null
  /** 这一轮有几发工具调用被深度门丢掉（第 2 轮起只放行深挖类工具）。 */
  depthDropped?: number
  depthDroppedAll?: boolean
  /** 进 prompt 前被相关性筛剔掉的材料（P8 问题 5）：从上千条的主题里抽样回来、跟这篇零重合的。 */
  factsIrrelevant?: number
  /** true = 真的从材料里拿掉了（开关 RELEVANCE_FILTER 开着）；false = 只标出来，还在 prompt 里（P8 退回后的默认）。 */
  irrelevantDropped?: boolean
  irrelevantSample?: string[]
  /** 引用覆盖（P30 #1，**这次跑累计**）：`citeLocated` = 写出来的字里有几句能逐字
   * 定位到材料（本来就该贴编号），`citeMarked` = 其中贴了的，`citeMatched` = 贴对的。
   * **`citeLocated === 0` 是「答不了」不是 0%**，两种措辞分开（见 `citeCoverLine`）。 */
  citeLocated?: number
  citeMarked?: number
  citeMatched?: number
  /** 打分器判词引了正文里没有的「原文」、被摘掉不计分的那几维（P11 #5；P5「अ」、P8「من」「մե」那种）。 */
  judgeHallucinated?: { dimension: string; quotes: string[]; note: string }[]
  /** 当前阶段（retrieval/edit/write/evaluate）和它的人话标签 */
  phase?: string
  phaseLabel?: string
  /** 每个阶段的实时输出，按阶段分开存。thinking 是模型的思考过程。 */
  phaseText?: Record<string, { thinking: string; output: string }>
  /** 这一轮流式写出来的正文。两段式之后编辑器有几十秒完全不动（检索规划
   * 是非流式的），面板里实时显示写出来的字，比一行干等的状态文案有用。 */
  streamed?: string
  /** 这次跑带了哪些技能（第一轮开跑就有）：按范围自动带上的、留给模型按需加载的（P1-1b） */
  skills?: { scope: string; injected: string[]; menu: string[] }
}

/** 「技能」那一行的文案。抽成纯函数是让闸够得着：这是用户判断「Skill 到底加载了没有」的唯一依据。 */
export function skillsLine(s: { injected: string[]; menu: string[] }): string {
  const a = s.injected.length ? `按范围自动带上 ${s.injected.length} 条：${s.injected.join('、')}` : '这个范围没有配技能，一条都没带'
  const b = s.menu.length ? `；另有 ${s.menu.length} 条没配范围，留给模型按需加载` : ''
  return `技能：${a}${b}`
}

/** 「引用覆盖」那一行的文案（P30 #1）。抽成纯函数是让闸够得着，
 * 而**要守的就是那两句话不许混成一句**：
 *
 * · `located === 0` —— 这次跑写的东西里**没有一句**在材料里找得到逐字出处。
 *   这不是「贴得很差」，是**这一格答不了**。实测（四批 20 跑）这是常态：
 *   终稿 623 句里只有 52 句可引，而整篇英文、材料跟正文零逐字重合的
 *   `a941efecd390` 四批里三批都是 0。把它显示成「0%」就是在告诉用户
 *   「AI 一个出处都没给」，而真相是「没有出处可给」——被换掉的那个旧指标
 *   （「这次跑写进终稿的引用处数」）坏就坏在这两件事在它那儿是同一个 0。
 * · `located > 0` —— 分子分母都报出来，**不报百分比**：分母常常只有个位数，
 *   一句话就能把比值从 0% 拉到 20%，一个百分号会让它看起来比实际精确。 */
export function citeCoverLine(located: number, marked: number, matched: number): string {
  if (located <= 0) return '这次写的内容在材料里找不到逐字出处，所以没有可直接引的编号'
  const wrong = marked - matched
  const tail = marked === 0 ? '，一句都没贴'
    : wrong > 0 ? `，其中 ${matched} 句贴的编号对得上、${wrong} 句对不上`
      : ''
  return `有出处可引的 ${located} 句里贴了 ${marked} 句${tail}`
}

type Props = {
  rounds: AgentRound[]
  status: string
  running: boolean
}

const LEVEL_COLOR: Record<number, string> = { 0: 'var(--del)', 1: 'var(--warn)', 2: 'var(--ins)' }
const LEVEL_LABEL: Record<number, string> = { 0: '不足', 1: '部分', 2: '达标' }

/** 维度的中文名。后端用英文 key 是因为 writer_harness 是要开源出去的独立包，
 * 不带任何中文领域词汇；中文只在展示层出现。 */

const PHASE_LABEL: Record<string, string> = {
  retrieval: '① 判断要不要查知识库',
  edit: '② 通读全文找问题',
  write: '③ 写正文',
  evaluate: '④ 打分',
}

const TOOL_LABEL: Record<string, string> = {
  search_memory: '关键词检索',
  list_topics: '看知识库有哪些主题',
  list_entities: '看有哪些人/产品',
  filter_facts: '按主题精确取',
  facts_in_range: '按时间范围取',
  fact_sources: '回溯到原始对话',
  search_session_context: '回到原始对话里追问',
}

/** 诊断原话是 `dim: note` 的形状（后端 `loop._steer`），维度名已经单独显示
 * 过一次，这里去掉前缀免得同一个词在一行里出现两遍。 */
export function stripDim(steer: string): string {
  const at = steer.indexOf(': ')
  return at > 0 ? steer.slice(at + 2) : steer
}

// ---------------------------------------------- 同一句诊断只说一遍（P33 #1）---
//
// **P31 走查 #5 看见的是一堵墙**：同一轮的卡片上「最弱是「事实依据」：…」整段、
// 「⚑ 代码判据 … 判了事实依据不合格。…」再整段，下一张卡开头「上一轮诊断：…」
// 又整段——那段本身就有一两百字，三遍下来右栏被它占满，真正要看的
// 「这一轮写了什么」被推到最底下。
//
// **三处各自的来源（读后端钉死的，不是猜的）**：
//   A 「最弱是 X：…」    = `st.ev.scores[weakest].note`，走 `evaluate` 事件。
//   B 「⚑ 代码判据 …」   = `check_hit.note` = `Verdict.message`，走 `check_hit` 事件。
//   C 「上一轮诊断：…」  = `State.steer` = `bag[focus] + ": " + bag[focus_note]`，
//      走**下一轮**的 `round_start` 事件；而 `loop.py:157-158` 那两行写的正是
//      **这一轮** `st.ev` 的 `weakest` 和 `_weak_note(st)` —— 逐字就是 A。
//
// 于是两条等式是**结构性的**，不是统计出来的：
//   · `C(第 N+1 轮) ≡ A(第 N 轮)` —— `loop.py` 那两行无条件写；
//   · `A ≡ B`（判据短路轮）—— `middleware/checks.py` 短路那一支伪造
//     `Evaluation(scores={verdict.dimension: DimensionScore(level=0, note=verdict.message)})`，
//     打分器根本没跑，「最弱那一维的诊断」就是判据那句话。
//
// **先量（真库 `harness_rounds` 489 行，`p33/m1_wall.py`）**：
//   · 有 A 的轮 **429**，其中判据短路轮（A ≡ B）**261 = 60.8%**；
//   · 会显示 C 的卡片 **311**，C ≡ 上一张卡的 A **311 = 100.0%**；
//   · 三处同一句（上一轮是短路轮）**191 = 61.4%**。
//
// **合并规则**：逐字一样就只显示一次、并标明另一处在哪儿（「这一轮就是照它改的」/
// 「判词就是下面那条判据」）；**不一样才分开列**，一个字都不折。
// 被折起来的那一份原话进 `title`，不是删掉。
// 比法**只归一化空白**，不做任何近似匹配——§21：判据宁可窄一点，
// 折错的代价是「用户以为两处说的是同一句、其实不是」，那比多读一遍严重得多。

function normDiag(s: string | undefined): string {
  return (s ?? '').replace(/\s+/g, ' ').trim()
}

/** 两处诊断是不是逐字同一句（空白归一化之后）。空串永远算「不一样」。 */
export function sameDiag(a: string | undefined, b: string | undefined): boolean {
  const x = normDiag(a)
  return x !== '' && x === normDiag(b)
}

/** 这一轮的「最弱是 X：…」就是同一张卡上那条 ⚑ 判据的判词（= 判据短路轮）。 */
export function weakestEchoedByCheck(r: AgentRound): boolean {
  const note = r.weakest ? r.scores?.[r.weakest]?.note : ''
  return (r.checkHits ?? []).some((h) => h.dimension === r.weakest && sameDiag(h.note, note))
}

/** 这一张卡的「上一轮诊断」就是上一张卡的「最弱是」那一段。
 *
 * **`steerDim` 也要对上**：`State.steer` 的维度名和 `weakest` 是同一个字段抄来的，
 * 对不上就说明中间还有一轮（或者诊断换了载体），这时候「就是上面那句」是句假话。 */
export function steerEchoedByPrev(r: AgentRound, prev?: AgentRound): boolean {
  if (!r.steer || !prev) return false
  const prevNote = prev.weakest ? prev.scores?.[prev.weakest]?.note : ''
  return !!r.steerDim && r.steerDim === prev.weakest && sameDiag(stripDim(r.steer), prevNote)
}

// ------------------------------- ⚑ 那一摞：同一句判据抬头只说一遍（P35 走查 #6）---
//
// P33 把 A / B / C 三处诊断合了，**⚑ 与 ⚑ 之间没合**。P35 实拍（`p35-6a-old-rounds-light`）：
// 一次三轮的智能续写，右栏 3396 字里
// 「代码判据 你定的完成标准 判了事实依据不合格（19 条里的第 14 条），这一轮没再花模型调用去打分。」
// 这一句 **45 字的抬头印了 5 遍**（第 2 轮两遍、第 3 轮两遍相邻 + 第 1 轮一遍），
// 占掉 225 字 ≈ 6.6%，而真正不一样的只有后面那半句。
//
// **只合相邻的、抬头逐字相同的**（同一条判据 + 同一维 + 同一个「第几条」，
// 且两条都不是「卡住放行」/「收工」那种特例）——
// 不跨位置抓取、不做近似匹配：§21 判据宁可窄，合错了等于告诉用户
// 「这两条是同一条判据判的」，而那可能是句假话。

export type CheckHitGroup = { head: CheckHit; notes: string[] }

function hitKey(h: CheckHit): string | null {
  if (h.stuck_rounds || h.stopped) return null     // 这两种各自只会出现一条，不参与合并
  return `${h.check ?? ''} ${h.dimension ?? ''} ${h.ran ?? ''}`
}

/** 相邻且抬头一样的 ⚑ 并成一条：抬头说一次，判词逐条列。 */
export function groupCheckHits(hits: CheckHit[]): CheckHitGroup[] {
  const out: CheckHitGroup[] = []
  for (const h of hits) {
    const k = hitKey(h)
    const last = out[out.length - 1]
    if (k !== null && last && hitKey(last.head) === k) { last.notes.push(h.note); continue }
    out.push({ head: h, notes: [h.note] })
  }
  return out
}

/** 判据抬头里那个括号。**维度为空就连括号一起不要**——后端的收工通知
 * （`middleware/checks.after_run`）发的是 `dimension: ""`，原来照直拼出
 * 「你定的完成标准**（）**已经连着 3 轮…」，看着像程序出错（P35 走查 #7，
 * 跟 P31 #4 那对空引号是同一个形状）。 */
export function dimParen(dim: string | undefined): string {
  const s = dimLabel(dim || '')
  return s ? `（${s}）` : ''
}

/** 0/1/2 三档画成三格信号条——比纯数字更容易一眼扫过一排维度看出哪个塌了。 */
function LevelBars({ level }: { level: number }) {
  return (
    <span style={{ display: 'inline-flex', gap: 2, alignItems: 'flex-end', height: 11 }}>
      {[1, 2, 3].map((i) => (
        <i
          key={i}
          style={{
            display: 'block',
            width: 3,
            height: `${i * 33}%`,
            background: i <= level + 1 ? LEVEL_COLOR[level] : 'var(--line)',
          }}
        />
      ))}
    </span>
  )
}

function ToolCallRow({ call }: { call: NoteHarnessToolCall }) {
  const [open, setOpen] = useState(false)
  // 检索词是模型自己想出来的，是判断"它有没有找对方向"的关键信息，
  // 所以放在收起状态也能看见的位置，结果原文才藏在展开里。
  const query = Object.entries(call.args)
    .filter(([k]) => k !== 'limit')
    .map(([, v]) => String(v))
    .join(' / ')
  const empty = call.result.startsWith('（')
  return (
    <li style={{ marginBottom: 4, fontSize: 'var(--t-sm)', lineHeight: 1.5 }}>
      <button
        onClick={() => setOpen((v) => !v)}
        title={open ? '收起结果' : '展开查到的原文'}
        style={{
          all: 'unset', cursor: 'pointer', display: 'flex', gap: 6,
          alignItems: 'baseline', width: '100%',
        }}
      >
        <span className="muted" style={{ width: 10, flexShrink: 0 }}>{open ? '▾' : '▸'}</span>
        <span style={{ color: 'var(--accent)', flexShrink: 0 }}>
          {TOOL_LABEL[call.tool] ?? call.tool}
        </span>
        <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {query || '（无参数）'}
        </span>
        {empty && <span className="muted" style={{ flexShrink: 0 }}>没查到</span>}
      </button>
      {open && (
        <pre
          style={{
            margin: '4px 0 6px 16px', padding: '6px 8px', fontSize: 'var(--t-xs)', lineHeight: 1.6,
            whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 200, overflowY: 'auto',
            background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 'var(--r-xs)',
          }}
        >
          {call.result}
        </pre>
      )}
    </li>
  )
}

/** agent 行为可视化：这一轮查了什么、改了几处、六个维度各打几分、
 * 然后策略控制器把下一轮的运行参数调成了什么、为什么。
 *
 * 之前这些信息只有一行状态文案（"第 2 轮：修订 3 处，续写中…"），
 * agent 自主检索和策略调整这两件事在界面上完全不可见——用户既看不到
 * 它凭什么说自己有依据，也看不到 runtime 为什么突然变慢/变快。 */
export default function AgentActivity({ rounds, status, running }: Props) {
  if (!rounds.length && !status) return null
  const sorted = [...rounds].sort((a, b) => a.round - b.round)
  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
        <h2 style={{ margin: 0 }}>Agent 运行</h2>
        {running && <span className="spinner" />}
      </div>

      {status && (
        <p className="muted" style={{ margin: '6px 0 10px', fontSize: 'var(--t-sm)' }}>{status}</p>
      )}

      {/* 事件是分散到达的，卡片按到达顺序建会乱（第 1 轮的初始策略先到、第 0 轮的快照后到）——按轮次排。
          **排完的这份要留住**（P33 #1）：「上一轮诊断」要跟上一张卡比，
          比的对象必须是排序之后的前一张，不是 `rounds` 里的前一项。 */}
      {sorted.map((r, i) => (
        <div
          key={r.round}
          style={{
            marginBottom: 10, padding: '8px 10px', fontSize: 'var(--t-sm)',
            border: '1px solid var(--line)', borderRadius: 'var(--r-sm)', background: 'var(--panel)',
          }}
        >
          <div className="row" style={{ gap: 8, alignItems: 'baseline', marginBottom: 6 }}>
            <strong>{r.round === 0 ? '开跑前' : `第 ${r.round} 轮`}</strong>
            {r.cleanupOnly && (
              <span className="muted" title="上一轮评分说已写内容自身有毛病，这一轮只理顺不加新内容">
                只清理，不续写
              </span>
            )}
            <span className="muted">修订 {r.revisions} 处</span>
            {r.phaseLabel && (
              <span style={{ color: 'var(--accent)', marginLeft: 'auto' }}>
                {r.phaseLabel}
              </span>
            )}
          </div>

          {/* 「这一轮为什么这么跑」的第一样：上一轮诊断出了什么，以及这条
              诊断**这一轮去了哪儿**。面板此前只显示 `adjust()` 的结果
              （检索预算 / 温度），而真正决定这一轮去查什么的是这句话。 */}
          {r.steer && (
            <p className="muted" style={{ margin: '0 0 6px', lineHeight: 1.55 }}
               title={steerEchoedByPrev(r, sorted[i - 1]) ? stripDim(r.steer) : undefined}>
              上一轮诊断：{r.steerDim ? `「${dimLabel(r.steerDim)}」` : ''}
              {steerEchoedByPrev(r, sorted[i - 1])
                ? `——就是上面第 ${sorted[i - 1].round} 轮那张卡上那句，这一轮就是照它改的。`
                : stripDim(r.steer)}
              <br />
              {r.steerInPlan === true && '→ 这句话进了这一轮的检索计划。'}
              {r.steerInPlan === false && (r.steerMaterial
                ? '→ 这一轮的检索计划里没有它（策略控制器这一轮没为它生成方向）。'
                : '→ 不进检索计划：这一维再查十条事实也修不好，它走的是修订那条线。')}
              {r.steerInPlan == null && '→ 这一轮没有检索规划这一步（只清理 / 打磨）。'}
            </p>
          )}

          {/* 第二样的一半：模型发了调用、但整批被深度门丢掉。第 2 轮起只放行
              深挖类工具，纯关键词撒网会被整批丢掉——而这件事既不算「撞上限」
              也不进任何一个数，此前在界面上完全无声。 */}
          {!!r.depthDropped && (
            <div className="muted" style={{ marginBottom: 3 }}>
              有 {r.depthDropped} 发检索被「第 2 轮起只深挖」这条规则丢掉
              {r.depthDroppedAll && '（整批丢光，这一轮的工具循环就此收工）'}
            </div>
          )}

          {/* P8 问题 5：从上千条的主题里抽样回来、跟这篇零重合的材料。P8 退回后默认**只标不剔**
              （它们还在 prompt 里），开关 RELEVANCE_FILTER 打开才真的筛掉——两种措辞要分开，
              不然用户会以为材料已经没了。 */}
          {!!r.factsIrrelevant && (
            <div className="muted" style={{ marginBottom: 3 }}
                 title={(r.irrelevantSample ?? []).join('\n')}>
              {r.irrelevantDropped ? '筛掉' : '标出'} {r.factsIrrelevant} 条跟这篇无关的材料（从上千条的主题里抽样来的、跟正文零重合{r.irrelevantDropped ? '' : '；没剔，还在材料里'}）
              {(r.irrelevantSample ?? []).length > 0 && `：${(r.irrelevantSample ?? [])[0]}…`}
            </div>
          )}

          {/* 引用覆盖（P30 #1）。`!== undefined` 不是 `!!`：**0 是要显示的那一档**
              （「没有可直接引的编号」正是用户最需要知道的那句话），用真值判断会把它藏掉。 */}
          {r.citeLocated !== undefined && (
            <div className="muted" style={{ marginBottom: 3 }}>
              {citeCoverLine(r.citeLocated, r.citeMarked ?? 0, r.citeMatched ?? 0)}
            </div>
          )}

          {r.skills && (
            <div className="muted agent-skills" style={{ marginBottom: 3 }} title={'生效范围：' + r.skills.scope}>{skillsLine(r.skills)}</div>
          )}

          {(r.toolCalls ?? []).length > 0 && (
            <>
              <div className="muted" style={{ marginBottom: 3 }}>
                agent 自己决定查了 {(r.toolCalls ?? []).length} 次
                {r.toolTruncated && '（撞上限，还想继续查）'}
              </div>
              <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 6px' }}>
                {(r.toolCalls ?? []).map((c, i) => <ToolCallRow key={i} call={c} />)}
              </ul>
            </>
          )}

          {Object.keys(r.scores ?? {}).length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', margin: '4px 0 6px' }}>
              {Object.entries(r.scores).map(([dim, sc]) => (
                <span
                  key={dim}
                  title={`${LEVEL_LABEL[sc.level] ?? sc.level}：${sc.note}`}
                  style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}
                >
                  <LevelBars level={sc.level} />
                  <span style={{ color: sc.level < 2 ? LEVEL_COLOR[sc.level] : 'inherit' }}>
                    {dimLabel(dim)}
                  </span>
                </span>
              ))}
            </div>
          )}

          {/* 最弱维度的诊断原文——这句话现在也是喂回下一轮的东西，
              让用户看到它，才能理解下一轮为什么那么跑。
              **判据短路轮上它逐字就是下面那条 ⚑ 的判词**（P33 #1，真库 429 轮里 261 轮
              = 60.8%）：那一档只留一句指路，原话在下面那条判据里给全。 */}
          {r.weakest && r.scores[r.weakest]?.note && (
            <p className="muted" style={{ margin: '0 0 6px', lineHeight: 1.55 }}
               title={weakestEchoedByCheck(r) ? r.scores[r.weakest].note : undefined}>
              {weakestEchoedByCheck(r)
                ? `最弱是「${dimLabel(r.weakest)}」——这一轮没打分，判词就是下面那条 ⚑ 代码判据。`
                : `最弱是「${dimLabel(r.weakest)}」：${r.scores[r.weakest].note}`}
            </p>
          )}

          {/* 打分器点名了正文里没有的「原文」（P11 #5）：那一维这一轮不计分，说清楚为什么少了一维 */}
          {(r.judgeHallucinated ?? []).map((h) => (
            <p key={h.dimension} className="muted" style={{ margin: '0 0 6px', lineHeight: 1.55 }}
               title={h.note}>
              「{dimLabel(h.dimension)}」这一维没计分：打分器说正文里有「{h.quotes.join('」「')}」，正文里没有这几个字
            </p>
          ))}

          {(r.policyReasons ?? []).length > 0 && (
            <div
              style={{
                marginTop: 6, paddingTop: 6, borderTop: '1px dashed var(--line)',
              }}
            >
              <div className="muted" style={{ marginBottom: 3 }}>
                据此调整了下一轮的跑法
                {r.policy && (
                  <span>
                    　·　检索预算 {r.policy.tool_iters}
                    　·　续写温度 {r.policy.continue_temperature}
                    　·　修订额度 {r.policy.max_revisions}
                    {r.policy.require_verification && '　·　要求溯源核对'}
                  </span>
                )}
              </div>
              <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                {(r.policyReasons ?? []).map((reason, i) => (
                  <li key={i} style={{ display: 'flex', gap: 5, lineHeight: 1.55 }}>
                    <span style={{ color: 'var(--accent)', flexShrink: 0 }}>↻</span>
                    <span>{reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {r.phaseText && Object.entries(r.phaseText).map(([ph, txt]) => (
            <details key={ph} style={{ marginTop: 4 }}>
              <summary style={{ cursor: 'pointer', color: 'var(--muted)' }}>
                {PHASE_LABEL[ph] ?? ph}
                {r.phase === ph && <span style={{ color: 'var(--accent)' }}> · 进行中</span>}
                <span className="muted">
                  （思考 {(txt.thinking ?? '').length} 字 · 输出 {(txt.output ?? '').length} 字）
                </span>
              </summary>
              {txt.thinking && (
                <pre style={{
                  margin: '4px 0 0', padding: '6px 8px', fontSize: 'var(--t-xs)', lineHeight: 1.6,
                  whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 160,
                  overflowY: 'auto', background: 'var(--bg)', border: '1px dashed var(--line)',
                  borderRadius: 'var(--r-xs)', color: 'var(--muted)', fontStyle: 'italic',
                }}>{txt.thinking}</pre>
              )}
              {txt.output && (
                <pre style={{
                  margin: '4px 0 0', padding: '6px 8px', fontSize: 'var(--t-xs)', lineHeight: 1.6,
                  whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 200,
                  overflowY: 'auto', background: 'var(--bg)', border: '1px solid var(--line)',
                  borderRadius: 'var(--r-xs)',
                }}>{txt.output}</pre>
              )}
            </details>
          ))}

          {r.streamed && (
            <details open style={{ marginTop: 6 }}>
              <summary style={{ cursor: 'pointer', color: 'var(--muted)' }}>
                本轮写出的正文（{(r.streamed ?? '').length} 字）
              </summary>
              <pre style={{
                margin: '4px 0 0', padding: '6px 8px', fontSize: 'var(--t-xs)', lineHeight: 1.7,
                whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 260,
                overflowY: 'auto', background: 'var(--bg)', border: '1px solid var(--line)',
                borderRadius: 'var(--r-xs)',
              }}>{r.streamed}</pre>
            </details>
          )}

          {/* 代码判据这一轮的全貌：命中了哪几条（不是只留最后一条），
              以及分母——全过的时候也要说一句，否则「判据跑了而且都过了」
              跟「判据根本没接上」在界面上完全一样。 */}
          {groupCheckHits(r.checkHits ?? []).map(({ head: h, notes }, i) => (
            <p key={i} className="muted" style={{ margin: '4px 0 0', lineHeight: 1.55,
                                                  display: 'flex', gap: 5 }}>
              <span style={{ flexShrink: 0 }}>⚑</span>
              <span>
                {h.stuck_rounds ? (
                  <>
                    判据 <b>{checkLabel(h.check)}</b>{dimParen(h.dimension)}已经连着
                    {' '}{h.stuck_rounds} 轮原样卡在这里，改不动——
                    {/* 两条长得像、说的是相反的事：`stopped` 是**收工通知**
                        （`middleware/checks.after_run`，整个跑到此为止），
                        没有它的那条是「这一轮放行、照常打分」。原来共用后一句，
                        于是停机那条写着「照常打分」，跟它自己后半句
                        「停下，交最好的一轮」当场打架（P35 走查 #7）。 */}
                    {h.stopped ? '这一次不再往下写了。' : '这一轮不再拦，照常打分。'}{h.note}
                  </>
                ) : (
                  <>
                    代码判据 <b>{checkLabel(h.check)}</b> 判了{dimLabel(h.dimension)}不合格
                    {h.ran && r.checksTotal ? `（${r.checksTotal} 条里的第 ${h.ran} 条）` : ''}
                    ，这一轮没再花模型调用去打分。
                    {/* 相邻的同一条判据只说一次抬头，判词逐条列（P35 走查 #6）。
                        一条的时候形状跟原来一模一样，不多一个符号。 */}
                    {notes.length === 1 ? notes[0] : notes.map((n, j) => (
                      <span key={j} style={{ display: 'block', marginTop: 2 }}>· {n}</span>
                    ))}
                  </>
                )}
              </span>
            </p>
          ))}
          {!!r.checksTotal && !(r.checkHits ?? []).length
            && Object.keys(r.scores ?? {}).length > 0 && (
            <p className="muted" style={{ margin: '4px 0 0', lineHeight: 1.55 }}>
              {r.checksTotal} 条代码判据全过，这一轮的分是打分模型给的。
            </p>
          )}

          {(r.dropped ?? []).length > 0 && (
            <details style={{ marginTop: 4 }}>
              <summary style={{ cursor: 'pointer', color: 'var(--muted)' }}>
                丢弃了 {(r.dropped ?? []).length} 条修订
                <span className="muted">（防线拦下的，不是出错）</span>
              </summary>
              <ul style={{ listStyle: 'none', padding: 0, margin: '4px 0 0 6px' }}>
                {(r.dropped ?? []).map((d, i) => (
                  <li key={i} className="muted" style={{ display: 'flex', gap: 5, lineHeight: 1.55 }}>
                    <Icon n="bx-x" style={{ flexShrink: 0 }} />
                    <span>{d}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}

          {(r.errors ?? []).map((e, i) => (
            <p key={i} style={{ margin: '4px 0 0', color: 'var(--del)', lineHeight: 1.55 }}>
              {e}
            </p>
          ))}
        </div>
      ))}
    </div>
  )
}
