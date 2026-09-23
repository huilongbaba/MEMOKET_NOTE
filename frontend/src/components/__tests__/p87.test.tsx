// @vitest-environment jsdom
/**
 * P87 B（第 812 轮）：**`components/` 底下那批「纯函数」——先量，量完发现该写的不是 13 份。**
 *
 * ── 开工先量，P85 ② 那句话的形状也要改 ────────────────────────────────────
 * P85 留给下一批的第 ② 条写着：
 *
 *     「`components/` 今天只有 1 份测试 / 70 个源文件，**13 个「有纯函数导出」的文件
 *       是最便宜的下一批**（不用真 React）」
 *
 * 这一批开工先把这句话量了一遍，三个数**都得改**：
 *
 *  - **不是 13 个文件 / 35 个导出，是 14 个 / 37 个。** P85 那一遍扫的是
 *    `^export (function|const) [a-z]`，**漏了 `export async function`**
 *    （`MemoryPanel.landImportInTray` / `TraceCard.lookup` 正好两条，35 + 2 = 37）。
 *    ——**「台账上的数」和「源码里的数」是两把尺**，这一条又实拍了一次。
 *  - **「不用真 React」也不全对**：这 14 个里 `iconDom.mountIcon` 非得有真 React 根
 *    （它自己就是「在手写 DOM 里挂一个 React 图标」那件事），算不得纯函数。
 *  - **最要紧的一条：这 37 个导出里 33 个早就被测试 import 了**，全在
 *    `src/editor/__tests__/` 底下。**「`components/` 底下没有测试」≠「这些函数没人测」**
 *    ——文件在哪个目录和这段代码有没有人看着，是两件事。
 *    （P85 问题 #1 的同款：「做不到」和「没人做过」在结论那一栏长得一模一样；
 *    这一批是反过来的那一面：「没在这儿测」看着像「没测」。）
 *
 * ⇒ 所以这一批**不按文件数凑**，按**「今天真没人看着的那一刀」**挑。
 *
 * ── 挑法：先砍 15 刀，看哪几刀今天整套 vitest 都不红 ──────────────────────
 * 15 刀全落在 `src/components/` 的用户可见文案 / 判据上，一刀一个「用户那儿长什么样」。
 * **11 刀当场红**（`saySize` / `sayKeep` / `tidyMenu` / `selectableItem` / `skillsLine` /
 * `sayNoDesc` / `emptyVerifyLine` / `wipeLines` 的另外两刀…都有人看着）。
 * **5 刀活了下来**，全压在两个函数上：
 *
 *  | 刀 | 用户那儿长什么样 | 今天谁看着 |
 *  |---|---|---|
 *  | W1 `wipeLines` 段数 / 有描述数对调 | 「6 段，其中 4 段有描述」→「4 段，其中 6 段有描述」 | **没人** |
 *  | W2 `wipeLines` 最早那天的兜底没了 | 「最早 —」→「最早 」 | **没人** |
 *  | W3 `wipeLines` 缩略图那行看的是日报的数 | 有日报没缩略图时说「0 张缩略图」 | **没人** |
 *  | P1 `paragraphAt` 标题正则 `{1,6}` → `{1,7}` | 七个井号那行被当成标题 | **没人** |
 *  | P2 `paragraphAt` 往上找不在标题处停 | **「按光标这段」把上面那个标题也算进这一段** | **没人** |
 *
 * W1 活下来的原因是**测试数据比判据窄**（P83 那一课）：`p21.test.ts` 那条用例摆的是
 * `segments: 295 / described: 143`，判据写的是 `expect(lines.join('\n')).toContain('295 段')`
 * ——两个数对调之后那一行变成「143 段，其中 295 段有描述」，`toContain('295 段')`
 * **照样过**。判据只认得出「295 这个数在」，认不出**它站在哪一格**。
 *
 * P1 / P2 活下来的原因**一模一样**：`paragraphAt.test.ts` 的那份文档是
 * `['# 标题', '', '第一段第一行', …]`——标题后面**有一个空行**，
 * 于是「往上走到空行停」先一步生效，「往上走到标题停」那两行**从来没被走到过**。
 * **一份没有空行的文档**（标题下面直接就是正文）才分得开这两条判据。
 *
 * ── 外加三个**一条测试都没有**的导出 ──────────────────────────────────────
 * 37 个导出里，`applyRevision` 虽然没进过 vitest，但 `scripts/check-revision-parity.mts`
 * 拿 `shared/revision-cases.json` 跟后端对拍着它（**又一把尺**，所以这一批不碰它）。
 * 真正一处都没有的是这三个，全是用户看得见的东西：
 *
 *  - `MemoryPanel.landImportInTray` —— 今天只有 `p15.test.ts` 的一条**源码 grep**
 *    （数 `landImportInTray(r.job_id, trayNoteId)` 出现 5 次）。
 *    **「文件里有这个串」≠「这段代码还在跑」**——它四条分支、两句不同的 toast，一条都没跑过。
 *  - `TraceCard.lookup` —— ⌥ 悬停那张卡上「你停的是哪个词」是它挑的。
 *  - `iconDom.mountIcon` —— 第 741 轮用户原话「/ 里的功能呢，怎么没有图标了，显得好空」那一处。
 *
 * ⚠️ 判据一律**只读那一格自己**，不搜整页 / 整份日志（P85 那一课）。
 */
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { JourneyRetention } from '../../api'
import { sayKeep, saySize, wipeLines } from '../JourneyRetentionPanel'
import { paragraphAt } from '../MarkdownEditor'
import { getSnapshot as toastSnapshot } from '../../toast'

// ── api / tray 这两层摆成可控的，让 `landImportInTray` / `lookup` 真跑得起来 ──
/** 这一趟 `jobStatus()` 该回什么。 */
let jobItems: { status: string; note_id?: string; filename: string }[] = []
/** 这一趟 `getNote()` 该回什么（按 id）。 */
let notes: Record<string, { title: string; content: string } | null> = {}
/** 这一趟 `recall()` 每个串该回几条事实。没写的一律 0 条。 */
let recallFacts: Record<string, number> = {}
/** `recall()` 被问过哪几个串，按顺序。 */
let recallAsked: string[] = []
/** `landNotesInTray()` 收到了什么、回了几篇。 */
let landed: { trayNoteId: string; notes: { id: string; title: string; content: string }[] }[] = []
let landReturns = 0

vi.mock('../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../api')
  return {
    ...actual,
    jobStatus: () => Promise.resolve({ items: jobItems }),
    getNote: (id: string) => (notes[id] === null
      ? Promise.reject(new Error('没了'))
      : Promise.resolve({ id, ...(notes[id] ?? { title: '', content: '' }) })),
    recall: (q: string) => {
      recallAsked.push(q)
      const n = recallFacts[q] ?? 0
      return Promise.resolve({
        facts: Array.from({ length: n }, (_, i) => ({ id: `${q}-${i}`, text: `${q} 第 ${i} 条`, when: '2026-07-01', kind: '' })),
        terms: [q], took_ms: 1, why_empty: '' as const, kb_empty: false,
      })
    },
  }
})

vi.mock('../../util/tray', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../util/tray')
  return {
    ...actual,
    landNotesInTray: (trayNoteId: string, ns: { id: string; title: string; content: string }[]) => {
      landed.push({ trayNoteId, notes: ns })
      return Promise.resolve(landReturns)
    },
  }
})

const { landImportInTray } = await import('../MemoryPanel')
const { lookup } = await import('../TraceCard')
const { mountIcon } = await import('../iconDom')

/** `toast()` 这一格里新添的那几条（读的是真 store，不是 spy）。 */
function newToasts(from: number): string[] {
  return toastSnapshot().slice(from).map((t) => t.message)
}

beforeEach(() => {
  jobItems = []; notes = {}; recallFacts = {}; recallAsked = []; landed = []; landReturns = 0
  localStorage.clear()
})
afterEach(() => { document.body.innerHTML = '' })

// ═══════════════════════════════════════════════════════════════════════════
// ① `wipeLines`：删之前摊开的那几行（走查第 ⑧ 步逐字读的就是它）
// ═══════════════════════════════════════════════════════════════════════════
describe('P87 ①：「全部删掉」摊开的那几行（`JourneyRetentionPanel.wipeLines`）', () => {
  /** ⑧ 那个夹具钉死的形状（P85 C②：`journey_fixture.EXPECT_SYNTHETIC`）。
   *  **段数 6 / 有描述 4 是两个不同的数**——这是下面那条判据分得开的前提。
   *
   *  ⚠️ `bytes` 这一格填的是 `bytes_norm`（**4198**），所以下面钉的是「一共 4 KB」；
   *  而 P87 走查在真壳上读回来的那一行是「一共 **5** KB」（真字节 5066）。
   *  **两个数不矛盾**：屏幕上那一行读的是真字节数，而真字节数跟 udd 路径长度有关
   *  （P85 问题 #4：`segments.json` 里 7 个绝对路径，目的地每长一个字符整棵树多 7 字节）。
   *  这条测试钉的是**这一行怎么拼**，不是「这台机器上有多少字节」——
   *  后者跟着环境走，是 C① 那份跨批 diff 的活。 */
  const FIXTURE: JourneyRetention = {
    segment_days: 30, thumb_days: 3, frame_days: 3, segment_choices: [0, 3, 30], thumb_choices: [0, 3],
    days: 3, segments: 6, described: 4, thumbs: 6, reports: 1, bytes: 4198, oldest: '2026-09-19',
  }

  it('W1 段数和「有描述」数各站各的格 —— 对调了当场红（`toContain` 分不开，所以钉整行）', () => {
    const lines = wipeLines(FIXTURE)
    // **钉的是那一行逐字**，不是「那几个数出现过」：
    // `toContain('6 段')` 在「4 段，其中 6 段有描述」上照样过（W1 那一刀就是这么活下来的）。
    expect(lines[1]).toBe('6 段，其中 4 段有描述')
    // 反过来那句**一个字都不许出现**
    expect(lines.join('\n')).not.toContain('4 段，其中 6 段有描述')
    // ⚠️ 这条判据要成立，**测试数据里那两个数必须不一样**（P83 那一课）：
    expect(FIXTURE.segments).not.toBe(FIXTURE.described)
    // 「有描述的」不可能比「总共的」还多——这一条是那句话读起来对不对的地面真相
    expect(FIXTURE.described).toBeLessThanOrEqual(FIXTURE.segments)
  })

  it('W1 续：换一组数（段 9 / 有描述 2）仍然各站各的格 —— 判的不是那两个具体的数', () => {
    const r: JourneyRetention = { ...FIXTURE, segments: 9, described: 2 }
    expect(wipeLines(r)[1]).toBe('9 段，其中 2 段有描述')
  })

  it('W2 一条记录都没有时「最早」有兜底，不许留一截空白', () => {
    const r: JourneyRetention = { ...FIXTURE, days: 0, oldest: '' }
    expect(wipeLines(r)[0]).toBe('0 天的记录（最早 —）')
    // 空串直接拼进去会变成「最早 ）」——一句话读起来像坏了，跟 P35 #7 那对空括号同一个形状
    expect(wipeLines(r)[0]).not.toContain('最早 ）')
  })

  it('W3 缩略图那行看的是缩略图的数，日报那行看的是日报的数 —— 两个条件不许串', () => {
    // 有日报、**没有**缩略图：那一行整个不许出现（说「0 张缩略图」是在说假话）
    const onlyReports: JourneyRetention = { ...FIXTURE, thumbs: 0, reports: 2 }
    const a = wipeLines(onlyReports)
    expect(a.join('\n')).not.toContain('缩略图')
    expect(a.join('\n')).toContain('2 份写好的日报')
    // 有缩略图、**没有**日报：反过来那一半
    const onlyThumbs: JourneyRetention = { ...FIXTURE, thumbs: 7, reports: 0 }
    const b = wipeLines(onlyThumbs)
    expect(b.join('\n')).toContain('7 张缩略图')
    expect(b.join('\n')).not.toContain('日报')
    // ⚠️ 这一条也要「分得开」：两个数不一样，串了条件当场看得出来
    expect(onlyReports.reports).not.toBe(onlyReports.thumbs)
  })

  it('那几行的顺序也钉死 —— 摊开来第一眼读到的是「几天」不是「多大」', () => {
    expect(wipeLines(FIXTURE)).toEqual([
      '3 天的记录（最早 2026-09-19）',
      '6 段，其中 4 段有描述',
      '6 张缩略图，连同还没删的原始截图',
      '1 份写好的日报',
      '这些描述抽进知识库的那些记忆',
      '一共 4 KB',
    ])
    // 体量那一格走的是 `saySize`（4198 字节 → 「4 KB」），不是裸字节数
    expect(saySize(4198)).toBe('4 KB')
    // `sayKeep` 那一格顺带核一眼：0 = 一直留着，**是一个选项不是默认**
    expect(sayKeep(0)).toBe('一直留着')
  })
})

// ═══════════════════════════════════════════════════════════════════════════
// ② `paragraphAt`：「按光标这段」是哪一段（P80 / P83 的记忆卡都锚在它身上）
// ═══════════════════════════════════════════════════════════════════════════
describe('P87 ②：按光标那一段的边界（`MarkdownEditor.paragraphAt`）', () => {
  /** 最小的 CM6 `Text` 替身：`paragraphAt` 的入参就是这三样（行号从 1 起）。
   *  **不拉真 `@codemirror/state`**：那样就变成在测 CM6，而这一条要测的是边界怎么划。 */
  const doc = (lines: string[]) => ({
    lines: lines.length,
    line: (n: number) => ({ text: lines[n - 1] ?? '' }),
    lineAt: (pos: number) => {
      // pos 按「第几行」给（1 起），够用且读起来不用数字符
      const n = Math.min(Math.max(pos, 1), lines.length)
      return { number: n, text: lines[n - 1] ?? '' }
    },
  })

  it('P2 标题下面**紧挨着**正文（中间没有空行）时，这一段不许把标题吃进去', () => {
    // ⚠️ 这份文档正是今天那条测试没有的形状：`paragraphAt.test.ts` 的标题后面有一个空行，
    // 于是「走到空行停」先生效，「走到标题停」那两行**从来没被走到过**。
    const d = doc(['## 众筹定价', '定价 199 是按三档算下来的。', '第二行也在这一段里。', '', '下一段。'])
    expect(paragraphAt(d, 2)).toBe('定价 199 是按三档算下来的。\n第二行也在这一段里。')
    // 标题一个字都不许在里头——它进来，「按光标这段找的」查的就是另一段话了
    expect(paragraphAt(d, 2)).not.toContain('众筹定价')
    expect(paragraphAt(d, 3)).toBe('定价 199 是按三档算下来的。\n第二行也在这一段里。')
  })

  it('P2 续：正文**后面**紧跟着下一个标题时，往下也在标题处停', () => {
    const d = doc(['正文第一行。', '正文第二行。', '## 下一个标题', '底下那一段。'])
    expect(paragraphAt(d, 1)).toBe('正文第一行。\n正文第二行。')
    expect(paragraphAt(d, 1)).not.toContain('下一个标题')
    // 光标落在标题上：标题自己单独算一段
    expect(paragraphAt(d, 3)).toBe('## 下一个标题')
    // 标题底下那一段也不许把标题吃进去
    expect(paragraphAt(d, 4)).toBe('底下那一段。')
  })

  it('P1 井号最多认到六个 —— 第七个开始就是正文，不是标题', () => {
    // markdown 里 `####### x` 不是标题，是一行普通正文。放宽到 `{1,7}` 会让它
    // 变成一道假的段落边界，把本来在一段里的两行劈开。
    const d = doc(['####### 七个井号这一行是正文', '紧跟着的这一行跟它同一段'])
    expect(paragraphAt(d, 1)).toBe('####### 七个井号这一行是正文\n紧跟着的这一行跟它同一段')
    // 六个井号是货真价实的标题，自己一段
    const six = doc(['###### 六个井号是标题', '底下这一行是另一段'])
    expect(paragraphAt(six, 1)).toBe('###### 六个井号是标题')
    expect(paragraphAt(six, 2)).toBe('底下这一行是另一段')
  })

  it('井号后面不带空格的不算标题（`#标签` 那种）', () => {
    const d = doc(['#众筹 这一行是正文', '跟它同一段'])
    expect(paragraphAt(d, 1)).toBe('#众筹 这一行是正文\n跟它同一段')
  })

  it('空行给空串；文档头尾不越界', () => {
    const d = doc(['第一段', '', '第二段'])
    expect(paragraphAt(d, 2)).toBe('')
    expect(paragraphAt(d, 1)).toBe('第一段')
    expect(paragraphAt(d, 3)).toBe('第二段')
  })
})

// ═══════════════════════════════════════════════════════════════════════════
// ③ `landImportInTray`：导入跑完那几篇进不进托盘（今天只有一条源码 grep）
// ═══════════════════════════════════════════════════════════════════════════
describe('P87 ③：导入落托盘的四条分支（`MemoryPanel.landImportInTray`）', () => {
  it('开关关掉时**一篇都不动、一句话都不说** —— 不是「悄悄照进不误」', async () => {
    localStorage.setItem('memoket.tray.default', '0')
    jobItems = [{ status: 'done', note_id: 'n1', filename: 'a.md' }]
    const before = toastSnapshot().length
    expect(await landImportInTray('job1', 'tray1')).toBe(0)
    expect(landed).toEqual([])
    expect(newToasts(before)).toEqual([])
  })

  it('一篇都没落成时也不说话 —— 「导入了 0 篇」是句废话', async () => {
    jobItems = [{ status: 'failed', note_id: '', filename: 'a.md' },
                { status: 'done', note_id: '', filename: 'b.md' }]
    const before = toastSnapshot().length
    expect(await landImportInTray('job1', 'tray1')).toBe(0)
    expect(landed).toEqual([])
    expect(newToasts(before)).toEqual([])
  })

  it('落成了、但没有打开着的笔记 —— **说清楚它没进托盘**，并且告诉用户下次怎么办', async () => {
    jobItems = [{ status: 'done', note_id: 'n1', filename: 'a.md' },
                { status: 'done', note_id: 'n2', filename: 'b.md' }]
    const before = toastSnapshot().length
    expect(await landImportInTray('job1', '')).toBe(0)
    expect(landed).toEqual([])          // **一次 PUT 都没发**
    const msgs = newToasts(before)
    expect(msgs).toHaveLength(1)
    expect(msgs[0]).toBe('导入了 2 篇；当前没有打开的笔记，因此没有加入本篇材料')
    // ⚠️ 这一档**不许**说成功那句
    expect(msgs[0]).not.toContain('已加入本篇材料')
  })

  it('落成了、有目标笔记 —— 进托盘、标题用笔记自己的、并且说一句', async () => {
    jobItems = [{ status: 'done', note_id: 'n1', filename: 'a.md' },
                { status: 'done', note_id: 'n2', filename: 'b.md' }]
    notes = { n1: { title: '众筹定价', content: '正文一' }, n2: { title: '排期', content: '正文二' } }
    landReturns = 2
    const before = toastSnapshot().length
    expect(await landImportInTray('job1', 'tray1')).toBe(2)
    expect(landed).toHaveLength(1)
    expect(landed[0].trayNoteId).toBe('tray1')
    expect(landed[0].notes).toEqual([
      { id: 'n1', title: '众筹定价', content: '正文一' },
      { id: 'n2', title: '排期', content: '正文二' },
    ])
    const msgs = newToasts(before)
    expect(msgs).toEqual(['导入的 2 篇已加入本篇材料；AI 写这篇时会优先参考'])
  })

  it('笔记拉不回来 / 没有标题时，退回文件名**并且去掉扩展名** —— 托盘里不摆「a.md」', async () => {
    jobItems = [{ status: 'done', note_id: 'n1', filename: '2026 众筹计划.md' },
                { status: 'done', note_id: 'n2', filename: '排期表.docx' }]
    notes = { n1: null, n2: { title: '', content: '有正文没标题' } }   // n1 整个拉不回来
    landReturns = 2
    await landImportInTray('job1', 'tray1')
    expect(landed[0].notes.map((n) => n.title)).toEqual(['2026 众筹计划', '排期表'])
    // 拉不回来那篇正文是空串，不是 `undefined`（拼进托盘会变成字面量 "undefined"）
    expect(landed[0].notes[0].content).toBe('')
  })

  it('`landNotesInTray` 回 0（一篇都没真的落进去）时不许说「已进托盘」', async () => {
    jobItems = [{ status: 'done', note_id: 'n1', filename: 'a.md' }]
    notes = { n1: { title: 'A', content: 'x' } }
    landReturns = 0
    const before = toastSnapshot().length
    expect(await landImportInTray('job1', 'tray1')).toBe(0)
    expect(newToasts(before)).toEqual([])
  })
})

// ═══════════════════════════════════════════════════════════════════════════
// ④ `lookup`：⌥ 悬停那张卡上「你停的是哪个词」
// ═══════════════════════════════════════════════════════════════════════════
describe('P87 ④：来龙去脉卡挑的是哪个词（`TraceCard.lookup`）', () => {
  it('分词器认得的整词：直接查它，只问一次', async () => {
    recallFacts = { 众筹定价: 3 }
    const got = await lookup('众筹定价', undefined)
    expect(got.phrase).toBe('众筹定价')
    expect(recallAsked).toEqual(['众筹定价'])
    expect(got.summary).toBeTruthy()
  })

  it('单字连成的串：两个两字窗口 + 整串一起问，**谁有记录用谁**', async () => {
    // 「众筹等」停在第 1 个字上 → 候选是 ['众筹', '筹等', '众筹等']
    recallFacts = { 众筹: 5, 筹等: 0, 众筹等: 0 }
    const got = await lookup('众筹等', 1)
    expect(recallAsked).toEqual(['众筹', '筹等', '众筹等'])   // 三次都是词法、并行
    expect(got.phrase).toBe('众筹')
  })

  it('哪个窗口记录多用哪个 —— 不是「取第一个」', async () => {
    recallFacts = { 甲乙: 1, 乙丙: 9, 甲乙丙: 0 }
    const got = await lookup('甲乙丙', 1)
    expect(got.phrase).toBe('乙丙')
  })

  it('两字窗口都空、整串有记录 → 才轮到整串', async () => {
    recallFacts = { 数据: 0, 据库: 0, 数据库: 4 }
    const got = await lookup('数据库', 1)
    expect(got.phrase).toBe('数据库')
  })

  it('三个都空 → 说**最左那个两字窗口**，不是整串（用户停的是一个词，不是一串字）', async () => {
    recallFacts = {}
    const got = await lookup('丁戊己', 1)
    expect(got.phrase).toBe('丁戊')
    expect(got.summary.count).toBe(0)
    expect(got.summary.first).toBeNull()
  })

  it('同一个词问第二次不再打后端（卡一收一开之间不许闪「查知识库…」）', async () => {
    recallFacts = { 缓存词: 2 }
    await lookup('缓存词', undefined)
    const asked = recallAsked.length
    const again = await lookup('缓存词', undefined)
    expect(recallAsked).toHaveLength(asked)     // 一次都没多问
    expect(again.phrase).toBe('缓存词')
  })

  it('同一个串、停在不同的字上是两回事（缓存的键带着落点）', async () => {
    recallFacts = { 庚辛: 1, 辛壬: 7, 庚辛壬: 0 }
    const a = await lookup('庚辛壬', 0)          // focus 0：只有右窗口 + 整串
    const b = await lookup('庚辛壬', 1)          // focus 1：左右两个窗口 + 整串
    expect(a.phrase).toBe('庚辛')
    expect(b.phrase).toBe('辛壬')
    expect(a.phrase).not.toBe(b.phrase)          // 缓存没把两次混成一次
  })
})

// ═══════════════════════════════════════════════════════════════════════════
// ⑤ `mountIcon`：手写 DOM 那两处的图标（第 741 轮「显得好空」）
// ═══════════════════════════════════════════════════════════════════════════
describe('P87 ⑤：手写 DOM 里的图标（`iconDom.mountIcon`）', () => {
  it('挂上去真的画出一个 svg —— 「显得好空」那次的地面真相', async () => {
    const el = document.createElement('span')
    document.body.append(el)
    let off = () => {}
    await act(async () => { off = mountIcon(el, 'bx-note') })
    const svg = el.querySelector('svg')
    expect(svg).not.toBeNull()
    // **「看到 ≠ 真在正文里」**：不光要有 `<svg>`，里头得有真字形（空的 svg 一样是空的）
    expect((svg as SVGElement).children.length).toBeGreaterThan(0)
    // CSS 那一大堆 `.bx { font-size: … }` 全按这个类名写的
    expect(svg?.getAttribute('class')).toContain('bx')
    // 尺寸跟着 font-size 走（`size="1em"`），不是写死的像素
    expect(svg?.getAttribute('width')).toBe('1em')
    await act(async () => { off(); await new Promise((r) => setTimeout(r, 0)) })
    expect(el.querySelector('svg')).toBeNull()      // 卸载函数真的收得干净，不漏根
  })

  it('名字不认识时什么都不画 —— 不留占位方块（第 713 轮）', async () => {
    const el = document.createElement('span')
    document.body.append(el)
    let off = () => {}
    await act(async () => { off = mountIcon(el, 'bx-这个名字不存在') })
    expect(el.querySelector('svg')).toBeNull()
    expect(el.textContent).toBe('')
    await act(async () => { off(); await new Promise((r) => setTimeout(r, 0)) })
  })
})
