// @vitest-environment jsdom
/**
 * P80 A（第 808 轮）：**右栏摆的是不是这一段的**。
 *
 * P78 在真打好的壳上拍到：一篇塞五段，光标依次落在各段，
 * **第 2 段的「命中：」那一行跟第 1 段逐字相同**，记的是「根因没查清」。
 * P79 顺手否掉了 P78 猜的那条（「产品窗口约 200 字、离线 300 字，两头不是同一条查询」
 * ——`recall_ruler --window` 证伪，765 条里产品产不出来的只有 1 条）。
 *
 * 这一批在**真壳上把 P78 那五段逐字重跑了一遍**（`p80-R0-out8-prefix`，
 * 量具那一行加宽成整行读 `.mem-terms`、带「按…找的」前缀）：
 *
 *     第 1 段  按光标这段找的，命中：主流（… 1 条）、更简单（… 3 条）、智能风（… 1 条）
 *     第 2 段  **逐字相同的一行**（前缀也是「按光标这段找的」，不是退回了末尾档）
 *
 * 而第 2 段的原文是「智影相机（AI 旅拍）… 唐风、文物穿越…」——**那三个词一个都不在里面**。
 *
 * **根因是查询的组成，不是刷新**：`recallQuery` 特意把**前一段（约 200 字）**拼进查询
 * （P4 #7：短段落光靠自己查不出东西）。第 1 段有 300 字，窗口截到的正是它的尾巴
 * （`…60 多个主流大模型，用更简单、更高效…智能风控…`），那一截**把三个词全带进了
 * 第 2 段的查询**。同一块面板的图例里其实写着实话（「按光标所在段（**带前一段、约 200 字**）
 * 召回」）——**同一屏上两句话自相矛盾**（P40 那次「校验」和「来龙去脉」互相打架同形）。
 *
 * ⇒ 改的只有**那一行的说法**（⑥⑦⑧）：前一段带进来的词当场点出来。
 *   召回本身、`out[:8]` **一个字没动**（判据宁可窄）。
 *
 * 顺带查清的两条，**都是产品，但都不是 P78 那一趟看到的**（③④）：
 *   ③ 这一问**失败**了（`.catch(() => {})` 把错吞了）→ 上一段的答案原样留在屏幕上；
 *   ④ 两问**乱序**回来 → 后到的那一问把答案盖回上一段的，而且不会自己修回来。
 *   （这两条在真壳上一次都没触发：`.mem-failed` 五段全 false。**它们是另一条路。**）
 *
 * ① ② 是**对照**：查询逐段不同、一问一答全成功时逐段都对——所以不是「组件不刷新」。
 *
 * 「量具的错」那一半也有账：`steps/recall74.mjs` 原来那条正则
 * `/命中[：:][^\n]{0,200}/` **把「按光标这段找的 / 按正文末尾找的」这个前缀扔掉了**，
 * 而那正是这一行自称属于哪一段的唯一标签——**判据比产品窄**的又一张脸。
 * 加宽之后才敢说「前缀两次都是『按光标这段找的』，不是退回了末尾档」。
 */
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import { evidenceLine, FROM_BEFORE_NOTE, recallQuery, termFromBefore } from '../../util/recallContext'
import { RECALL_FAILED_NOTE } from '../marginMemory'

type R = { facts: { id: string; text: string; when: string }[]; terms: string[]; evidence: null; why_empty: '' }

let mode: 'ok' | 'reject' | 'hold' = 'ok'
const held: { q: string; resolve: (v: R) => void }[] = []

/** 假后端：`terms` = 查询里出现过的**标记词**。摆出来的词来自哪一段，看得见。 */
const MARK = ['甲甲甲', '乙乙乙', '丙丙丙', '丁丁丁', '戊戊戊']
const mk = (q: string): R => ({
  facts: [{ id: 'f1', text: '库里那条', when: '2026-09-01' }],
  terms: MARK.filter((m) => q.includes(m)),
  evidence: null,
  why_empty: '',
})

vi.mock('../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../api')
  return {
    ...actual,
    memoryRelations: () => Promise.resolve({ relations: [] }),
    recall: (q: string) => {
      if (mode === 'reject') return Promise.reject(new Error('没答上'))
      if (mode === 'hold') return new Promise<R>((resolve) => held.push({ q, resolve }))
      return Promise.resolve(mk(q))
    },
  }
})

const { default: RelatedMemory } = await import('../../components/RelatedMemory')

/** 五段，各带一个只属于自己的标记词，长度跟 P78 那一趟同量级。 */
const PARAS = MARK.map((m, i) =>
  `第${i + 1}段${m}讲的是一件独立的事情，` + '这里是一段足够长的正文用来把上下文窗口撑开，'.repeat(9))
const CONTENT = '# P80 多段走查\n\n' + PARAS.join('\n\n') + '\n'

const line = (host: HTMLElement) => host.querySelector('.mem-terms')?.textContent ?? null
const cards = (host: HTMLElement) => [...host.querySelectorAll('.memory-card')].length
const body = (host: HTMLElement) => host.textContent ?? ''

function panel() {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const root = createRoot(host)
  const draw = (para: string) => act(() => {
    root.render(<RelatedMemory content={CONTENT} paragraph={para} onInsert={() => {}} />)
  })
  return { host, draw }
}

describe('P80 A：光标换段时右栏摆的是这一段的', () => {
  it('① 对照：五段发出去的查询本来就各不相同（不是「共用一条查询」）', () => {
    const marks = PARAS.map((p) => MARK.filter((m) => recallQuery(CONTENT, p).query.includes(m)))
    expect(marks).toEqual([['甲甲甲'], ['乙乙乙'], ['丙丙丙'], ['丁丁丁'], ['戊戊戊']])
    // **前一段是有意带进查询的**（P4 #7），但它带的是上下文，不是标记词那一格
    expect(recallQuery(CONTENT, PARAS[0]).query.length).toBe(215)
    expect(recallQuery(CONTENT, PARAS[1]).query.length).toBe(414)
    expect(recallQuery(CONTENT, PARAS[1]).mode).toBe('cursor')
  })

  it('② 对照：一问一答全成功时，五段逐段都对', async () => {
    mode = 'ok'
    vi.useFakeTimers()
    const { host, draw } = panel()
    const got: (string | null)[] = []
    for (const p of PARAS) {
      draw(p)
      await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
      got.push(line(host))
    }
    vi.useRealTimers()
    expect(got).toEqual(MARK.map((m) => `按光标这段找的，命中：${m}`))
  })

  it('③ 这一问失败：不许把上一段的命中词和记忆卡留在屏幕上', async () => {
    vi.useFakeTimers()
    const { host, draw } = panel()
    mode = 'ok'
    draw(PARAS[0])
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    expect(line(host)).toBe('按光标这段找的，命中：甲甲甲')
    expect(cards(host)).toBe(1)

    mode = 'reject'
    draw(PARAS[1])
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    vi.useRealTimers()
    // 改之前这三条各是：`按光标这段找的，命中：甲甲甲` / 1 / false
    expect(line(host)).toBe(null)
    expect(cards(host)).toBe(0)
    expect(body(host)).toContain(RECALL_FAILED_NOTE)
    // **「没问成」和「问过了，没有」不是一句话**：没拿到回答时不许说知识库里没有
    expect(body(host)).not.toContain('知识库里暂时没有找到相关内容')
  })

  it('④ 两问乱序回来：后到的那一问不许把答案盖回上一段', async () => {
    mode = 'hold'; held.length = 0
    vi.useFakeTimers()
    const { host, draw } = panel()
    draw(PARAS[0])
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    draw(PARAS[1])
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    expect(held.length).toBe(2)

    await act(async () => { held[1].resolve(mk(held[1].q)); await Promise.resolve() })
    expect(line(host)).toBe('按光标这段找的，命中：乙乙乙')
    // 第 1 段那一问**后到**。改之前这一行当场退回「命中：甲甲甲」，而且不会自己修回来
    await act(async () => { held[0].resolve(mk(held[0].q)); await Promise.resolve() })
    vi.useRealTimers()
    expect(line(host)).toBe('按光标这段找的，命中：乙乙乙')
  })

  it('⑤ 失败之后还问得动：改一个字（依赖变了）就再问一次', async () => {
    vi.useFakeTimers()
    const { host, draw } = panel()
    mode = 'reject'
    draw(PARAS[1])
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    expect(body(host)).toContain(RECALL_FAILED_NOTE)
    mode = 'ok'
    // 光标挪到第 3 段再挪回来：**失败那一问不许把自己记成「问过了」**
    draw(PARAS[2])
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    draw(PARAS[1])
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    vi.useRealTimers()
    expect(line(host)).toBe('按光标这段找的，命中：乙乙乙')
  })
})

/** ── ⑥⑦⑧ 那一行说不说老实话（P80 A 真落下去的那一刀）─────────────────
 *
 *  形状照着真壳上那一趟造：**前一段长、词都在它身上；光标这段一个词都不沾。** */
const BEFORE = '公司大模型平台已经能够适配业界 60 多个主流大模型，用更简单、更高效的方式帮客户做出创新应用，'
  + '比如金融行业的智能客服、智能风控，医疗行业的智能诊断。'
const HERE = '智影相机让游客上传本人照片，一键生成唐风、文物穿越风格的大片，在多家博物馆落地。'
const DOC = `# 标题\n\n${BEFORE}\n\n${HERE}\n`
const EV = [
  { term: '主流', why: 'pair', units: 1 },
  { term: '更简单', why: 'pair', units: 3 },
  { term: '智能风', why: 'pair', units: 1 },
]

describe('P80 A：「按光标这段找的」这句话说不说老实', () => {
  it('⑥ recallQuery 把这一趟真拼进去的前一段交出来', () => {
    const q = recallQuery(DOC, HERE)
    expect(q.mode).toBe('cursor')
    expect(q.before).toContain('智能风控')
    expect(q.query).toContain('智影相机')
    // 光标不在正文里那一档没有前一段可言
    expect(recallQuery(DOC, '').before).toBe('')
    expect(recallQuery(DOC, '# 标题').before).toBe('')
  })

  it('⑦ 判据宁可窄：**两条都成立**才点名', () => {
    const q = recallQuery(DOC, HERE)
    expect(termFromBefore('主流', HERE, q.before)).toBe(true)
    // 在这一段里 → 不点名（哪怕前一段里也有）
    expect(termFromBefore('智影相机', HERE, q.before)).toBe(false)
    // 两头都没有（后端在拼好的查询上切出来的碎词）→ **不点名**，宁可少说一句
    expect(termFromBefore('莫须有', HERE, q.before)).toBe(false)
    // 没有前一段那一截 → 一个都不点名
    expect(termFromBefore('主流', HERE, '')).toBe(false)
  })

  it('⑧ 那一行：三个词全标上；不给 ctx 的老调用逐字不变', () => {
    const q = recallQuery(DOC, HERE)
    const ctx = { paragraph: HERE, before: q.before }
    const now = evidenceLine('cursor', EV, [], ctx)
    expect(now).toBe('按光标这段找的，命中：'
      + `主流（${FROM_BEFORE_NOTE} · 跟别的词一起才算 · 库里 1 条提到）、`
      + `更简单（${FROM_BEFORE_NOTE} · 跟别的词一起才算 · 库里 3 条提到）、`
      + `智能风（${FROM_BEFORE_NOTE} · 跟别的词一起才算 · 库里 1 条提到）`)
    // **老调用一个字都不动**（P46 / P32 那两份快照就是靠这一条不用改）
    expect(evidenceLine('cursor', EV, [])).toBe('按光标这段找的，命中：'
      + '主流（跟别的词一起才算 · 库里 1 条提到）、更简单（跟别的词一起才算 · 库里 3 条提到）、'
      + '智能风（跟别的词一起才算 · 库里 1 条提到）')
    // 光标这段自己的词**不许**被标上
    const own = evidenceLine('cursor', [{ term: '智影相机', why: 'vocab', units: 2 }], [], ctx)
    expect(own).not.toContain(FROM_BEFORE_NOTE)
    // `terms` 那一支（老后端 / 判据抛了）走同一把尺
    expect(evidenceLine('cursor', null, ['主流', '智影相机'], ctx))
      .toBe(`按光标这段找的，命中：主流（${FROM_BEFORE_NOTE}）、智影相机`)
    // 末尾档没有「前一段」这回事
    expect(evidenceLine('tail', EV, [], { paragraph: HERE, before: '' })).not.toContain(FROM_BEFORE_NOTE)
  })

  it('⑨ 接线洞单独一条：面板标的是**发那一问时**的两段，不是渲染这一刻的', async () => {
    mode = 'hold'; held.length = 0
    vi.useFakeTimers()
    const host = document.createElement('div')
    document.body.appendChild(host)
    const root = createRoot(host)
    const draw = (para: string) => act(() => {
      root.render(<RelatedMemory content={DOC} paragraph={para} onInsert={() => {}} />)
    })
    draw(HERE)
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    // 回答在飞的时候光标挪回了**前一段**；答案回来时要按「问的时候那两段」标
    await act(async () => {
      held[0].resolve({ facts: [{ id: 'f1', text: '库里那条', when: '' }],
                        terms: ['主流'], evidence: null, why_empty: '' })
      await Promise.resolve()
    })
    draw(BEFORE)
    await act(async () => { await vi.advanceTimersByTimeAsync(100) })
    vi.useRealTimers()
    expect(host.querySelector('.mem-terms')?.textContent)
      .toBe(`按光标这段找的，命中：主流（${FROM_BEFORE_NOTE}）`)
  })
})
