// @vitest-environment jsdom
/**
 * P83 A（第 809 轮）：**底下那 5 张记忆卡也分一分**。
 *
 * P80 查明并改掉的是**那一行**：右栏「按光标这段找的，命中：…」里的词，
 * 有些是 `RECALL_CONTEXT_BEFORE = 200` 把**前一段**拼进查询带回来的，
 * 屏幕上现在会当场说「前一段带进来的」。
 *
 * **但它只改了那一行。** 底下那几张记忆卡还是混着的：哪几张是因为「光标这一段」
 * 捞回来的、哪几张是因为「前一段」捞回来的，用户一点提示都没有——
 * 而卡才是他会点下去插进正文的东西。
 *
 * ── 先量再改（`backend/scripts/card_origin_ruler.py`，真语料 `KITE_DATA_DIR`）──
 *
 *     cursor 727 条 / 真摆出卡的 312 条 / 卡 964 张
 *     其中会被盖上「前一段带进来的」**133 张**
 *     有戳的查询 62 条 = **混着 29 条** + 整屏 5 张全是前一段的 **33 条**
 *
 * 133/964 不是可以忽略的零头，**33 条整屏全是前一段的**更是最坏的那一档：
 * 标签写着「按光标这段找的」，底下一张都不是。⇒ **判「改」**。
 *
 * ── 判据（照抄 P80 立的形状，两条都成立才标）──────────────────────────
 *   ① 这张卡里**一个「光标这段里的命中词」都没有**（**一票否决**，不是多数决）；
 *   ② 这张卡里**至少有一个「前一段带进来的命中词」**（`termFromBefore` 那两条）。
 *
 * **召回和 `out[:8]` 一个字没动**（P80 划的那条边界，这一批沿用）——
 * 变的只有「怎么说」，不是「捞什么」。
 */
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import { cardFromBefore, evidencePool, FROM_BEFORE_NOTE, recallQuery } from '../../util/recallContext'

type Ev = { term: string; why: string; units: number }
type R = { facts: { id: string; text: string; when: string }[]; terms: string[]; evidence: Ev[] | null; why_empty: '' }

/** 形状照着真壳上那一趟造：**前一段词多，光标这段一个都不沾。** */
const BEFORE = '公司大模型平台已经能够适配业界 60 多个主流大模型，用更简单、更高效的方式帮客户做出创新应用，'
  + '比如金融行业的智能客服、智能风控，医疗行业的智能诊断。'
const HERE = '智影相机让游客上传本人照片，一键生成唐风、文物穿越风格的大片，在多家博物馆落地。'
const DOC = `# 标题\n\n${BEFORE}\n\n${HERE}\n`
const EV: Ev[] = [
  { term: '主流', why: 'pair', units: 1 },
  { term: '更简单', why: 'pair', units: 3 },
  { term: '智能风', why: 'pair', units: 1 },
  { term: '智影相机', why: 'vocab', units: 2 },
  // **两头都没有的那种**（后端在**拼好的查询**上切出来的碎词，跨过了两段的接缝）。
  // ⚠️ 这一条是**第 ② 刀逼出来的**：第一版四张卡里没有它，于是把判据②放宽成
  // 「只要不在这一段里就盖」**一刀砍下去测试全绿**——四张卡分不开那两条判据。
  // **测试数据比判据窄，也是「判据比产品窄」的一张脸。**
  { term: '诊断智影', why: 'pair', units: 1 },
]
/** 五张卡，**一屏里五种情形各一张**（真库量到的 29 条「混着」就是这个样子）。 */
const FACTS = [
  { id: 'f1', text: '三季度把主流大模型的适配名单又过了一遍', when: '2026-07-01' },   // 只沾前一段的词 → 该标
  { id: 'f2', text: '关于智影相机的季度汇报要点已经交上去了', when: '2026-07-02' },   // 沾光标这段的词 → 一票否决
  { id: 'f3', text: '智能风控那次评审顺带聊到智影相机的排期', when: '2026-07-03' },   // 两边都沾 → 一票否决
  { id: 'f4', text: '仓库盘点单据的归档规则去年就定下来了', when: '2026-07-04' },     // 一个词都不沾 → 不标
  { id: 'f5', text: '诊断智影这个说法是接缝上切出来的碎词', when: '2026-07-05' },     // 两头都没有 → **不标**
]

let evidence: Ev[] | null = EV
vi.mock('../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../api')
  return {
    ...actual,
    memoryRelations: () => Promise.resolve({ relations: [] }),
    recall: (): Promise<R> => Promise.resolve({
      facts: FACTS, terms: EV.map((e) => e.term), evidence, why_empty: '',
    }),
  }
})
const { default: RelatedMemory } = await import('../../components/RelatedMemory')

const CTX = () => ({ paragraph: HERE, before: recallQuery(DOC, HERE).before })

/** 屏幕上那几张卡：[头几个字, 有没有被盖戳]。 */
function cardMarks(host: HTMLElement): [string, boolean][] {
  return [...host.querySelectorAll('.memory-card')].map((c) => [
    (c.firstElementChild?.textContent ?? '').slice(0, 12),
    !!c.querySelector('.mem-card-from-before'),
  ])
}

describe('P83 A：底下那几张卡自己说得出「我是前一段带回来的」', () => {
  it('① 两条都成立才标：只沾前一段的词那张标上，其余三张一张都不标', () => {
    const { paragraph, before } = CTX()
    const pool = evidencePool(EV, [])
    expect(FACTS.map((f) => cardFromBefore(f.text, pool, paragraph, before)))
      .toEqual([true, false, false, false, false])
  })

  it('①b 第 ② 条不是「不在这一段里」：两头都没有的碎词**不算**前一段带回来的', () => {
    const { paragraph, before } = CTX()
    const pool = evidencePool(EV, [])
    // `诊断智影` 跨在两段的接缝上——**光标这段里没有，前一段那一截里也没有**。
    // 判据②要的是「确实在前一段里」，不是「不在这一段里」。**这两句话不一样。**
    expect(before.includes('诊断智影')).toBe(false)
    expect(HERE.includes('诊断智影')).toBe(false)
    expect(cardFromBefore('诊断智影这个说法是接缝上切出来的碎词', pool, paragraph, before)).toBe(false)
  })

  it('② 一票否决不是多数决：卡里沾着一个光标这段的词就不许盖', () => {
    const { paragraph, before } = CTX()
    const pool = evidencePool(EV, [])
    // f3 里有三个前一段的词的其中一个（智能风）**和**一个光标这段的词（智影相机）
    expect(cardFromBefore('智能风控和智能诊断都提了，另外智影相机也提了', pool, paragraph, before)).toBe(false)
    // 把那个光标这段的词拿掉，同一张卡当场就该标上——**差别只在那一个词**
    expect(cardFromBefore('智能风控和智能诊断都提了', pool, paragraph, before)).toBe(true)
  })

  it('③ 落差只让它少说：两头都不沾、没有前一段、空文本，一律不标', () => {
    const { paragraph, before } = CTX()
    const pool = evidencePool(EV, [])
    expect(cardFromBefore('仓库盘点单据的归档规则', pool, paragraph, before)).toBe(false)
    expect(cardFromBefore('三季度把主流大模型的适配名单又过了一遍', pool, paragraph, '')).toBe(false)
    expect(cardFromBefore('', pool, paragraph, before)).toBe(false)
    expect(cardFromBefore('三季度把主流大模型的适配名单又过了一遍', [], paragraph, before)).toBe(false)
  })

  it('④ 拿哪几个词去判：三档跟那一行同进同退', () => {
    expect(evidencePool(EV, ['甲', '乙'])).toEqual(['主流', '更简单', '智能风', '智影相机', '诊断智影'])
    // `[]` = 后端判过了、一条都摆不出来 → **一个词都不许拿**（P44 问题 #3 那条路）
    expect(evidencePool([], ['主流', '甲'])).toEqual([])
    // 没这一格（老后端 / 判据自己抛了）= 没人判过 → 退回 `terms` 是对的
    expect(evidencePool(null, ['主流', '甲'])).toEqual(['主流', '甲'])
    expect(evidencePool(undefined, ['主流'])).toEqual(['主流'])
  })

  it('⑤ 接线洞：面板上真的盖下去了，而且一屏里只盖该盖的那一张', async () => {
    evidence = EV
    vi.useFakeTimers()
    const host = document.createElement('div')
    document.body.appendChild(host)
    const root = createRoot(host)
    act(() => { root.render(<RelatedMemory content={DOC} paragraph={HERE} onInsert={() => {}} />) })
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    vi.useRealTimers()
    // 改之前这一列是 **5 个 false**：卡混着摆，用户一点提示都没有
    expect(cardMarks(host)).toEqual([
      ['三季度把主流大模型的适配', true],
      ['关于智影相机的季度汇报要', false],
      ['智能风控那次评审顺带聊到', false],
      ['仓库盘点单据的归档规则去', false],
      ['诊断智影这个说法是接缝上', false],
    ])
    expect(host.querySelectorAll('.mem-card-from-before').length).toBe(1)
    expect(host.querySelector('.mem-card-from-before')?.textContent).toBe(FROM_BEFORE_NOTE)
    // 上面那一行（P80 改的）**一处没回退**：三个前一段的词照样标着，光标这段那个不标
    const termsLine = host.querySelector('.mem-terms')?.textContent ?? ''
    expect((termsLine.match(new RegExp(FROM_BEFORE_NOTE, 'g')) ?? []).length).toBe(3)
  })

  it('⑥ 对照刀：后端判过了、一条证据都摆不出来（`[]`）时，一张卡都不许盖', async () => {
    evidence = []
    vi.useFakeTimers()
    const host = document.createElement('div')
    document.body.appendChild(host)
    const root = createRoot(host)
    act(() => { root.render(<RelatedMemory content={DOC} paragraph={HERE} onInsert={() => {}} />) })
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    vi.useRealTimers()
    evidence = EV
    expect(host.querySelectorAll('.memory-card').length).toBe(5)
    expect(host.querySelectorAll('.mem-card-from-before').length).toBe(0)
  })

  it('⑦ 接线洞：盖的是**发那一问时**的两段，不是渲染这一刻的', async () => {
    evidence = EV
    vi.useFakeTimers()
    const host = document.createElement('div')
    document.body.appendChild(host)
    const root = createRoot(host)
    const draw = (para: string) => act(() => {
      root.render(<RelatedMemory content={DOC} paragraph={para} onInsert={() => {}} />)
    })
    draw(HERE)
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    expect(host.querySelectorAll('.mem-card-from-before').length).toBe(1)
    // 光标挪回**前一段**（那一段自己没有「前一段」，`before` 是空的）。
    // 答案还是刚才那一份，戳**必须还按问的时候那两段算**——拿新光标段去标旧结果
    // 就是 P17 #2「A 篇的校验结果挂在 B 篇上」换个地方重演。
    draw(BEFORE)
    await act(async () => { await vi.advanceTimersByTimeAsync(100) })
    vi.useRealTimers()
    expect(host.querySelectorAll('.mem-card-from-before').length).toBe(1)
  })

  it('⑧ 对照：末尾档（光标不在正文里）没有「前一段」这回事，一张都不盖', () => {
    const q = recallQuery(DOC, '')
    expect(q.mode).toBe('tail')
    expect(q.before).toBe('')
    expect(cardFromBefore('三季度把主流大模型的适配名单又过了一遍', evidencePool(EV, []), '', q.before)).toBe(false)
  })
})
