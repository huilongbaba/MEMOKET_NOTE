/**
 * P35（第三次全流程走查 + `edge-cases` 第十列补完）：
 *   #1 右键 重写 / 润色 / 扩展上下文：换进正文的那段字**本身是一串 JSON** 就不落正文
 *   #6 轮次卡片：相邻的同一条 ⚑ 判据，抬头只说一遍
 *   #7 收工那条 ⚑：维度为空不要那对空括号 + 别说「照常打分」（它已经停了）
 *   #8 空托盘那一块收成一句 + 一个 `<details>`
 */
import { describe, expect, it } from 'vitest'
import { badRevisionNote, looksLikeJson, revisionIsJson, splitBadRevisions } from '../blockShape'
import { groupCheckHits, dimParen } from '../../components/AgentActivity'
import { TRAY_EMPTY_LINE } from '../../components/TrayPanel'
import type { CheckHit } from '../agentRound'

import appSrc from '../../App.tsx?raw'
import agentSrc from '../../components/AgentActivity.tsx?raw'
import traySrc from '../../components/TrayPanel.tsx?raw'

// P35 实拍：模型把整个响应又塞进 `text` 里答回来（`p35-B-rewrite-jsontext-light`）
const DIRTY = '{"text": "（假模型改写）这一段由假模型返回。", "reason": "假模型"}'

describe('P35 #1 右键动作换进正文的那段字过一道形状闸', () => {
  it('整串 JSON 的那条不落正文，正常的那条照落', () => {
    const { keep, bad } = splitBadRevisions([
      { text: '这周把众筹页面的文案定稿了。' },
      { text: DIRTY },
    ])
    expect(keep).toHaveLength(1)
    expect(bad).toHaveLength(1)
    expect(bad[0].text).toBe(DIRTY)
  })

  it('判据只有 JSON 这一档——块生成那三条一条都没搬过来', () => {
    // 「帮我把这段改成一张表」是右键的**正当产出**，`shapeOf('table')` 那一条
    // 要是搬过来，它会被判死。这里钉住：没有表格行照样放行。
    expect(revisionIsJson('先看留存，再定价。')).toBe(false)
    expect(revisionIsJson('| 档位 | 价格 |\n| --- | --- |')).toBe(false)
    expect(revisionIsJson('')).toBe(false)
    // 判据跟块生成那条**逐字同一条**，不是第二套算法
    expect(revisionIsJson(DIRTY)).toBe(looksLikeJson(DIRTY))
  })

  it('判据宁可窄：像 JSON 但 parse 不了的正常句子不拦', () => {
    // 两头都撞上、中间 parse 不了——P32 突变验逼出来的那个反例，这里一样要放行
    expect(revisionIsJson('{产品名} 的定价还没定，先看 {留存}')).toBe(false)
  })

  it('那句人话说清「拦了几处」「正文没动」，且不带 markdown 粗体', () => {
    const say = badRevisionNote('重写', 2)
    expect(say).toMatch(/重写/)
    expect(say).toMatch(/2 处/)
    expect(say).toMatch(/正文一个字没动/)
    expect(say).not.toMatch(/\*\*/)      // 走 toast，是纯文本（P32 第一版栽过一次）
  })

  it('接线：三个动作都走 landRevisions，没有一条绕过闸直接 applyAsDiff', () => {
    // `applyAsDiff` 只许在 `landRevisions` 里被调一次（外加它自己的定义那一行）
    const calls = appSrc.match(/applyAsDiff\(/g) ?? []
    expect(calls.length).toBe(2)                       // 定义 1 + landRevisions 里 1
    expect(appSrc).toContain('landRevisions(r.revisions')
    expect(appSrc).toContain('splitBadRevisions')
  })
})

describe('P35 #6 相邻的同一条 ⚑ 判据，抬头只说一遍', () => {
  const hit = (over: Partial<CheckHit> = {}): CheckHit =>
    ({ check: 'done_criteria', ran: 14, dimension: 'factual_grounding', note: 'x', ...over })

  it('抬头一样的相邻两条并成一条，判词都留着', () => {
    const g = groupCheckHits([hit({ note: 'A' }), hit({ note: 'B' })])
    expect(g).toHaveLength(1)
    expect(g[0].notes).toEqual(['A', 'B'])
  })

  it('P35 实拍那一轮：4 条 ⚑ → 3 条抬头', () => {
    // 第 3 轮实拍的顺序（`p35/rounds-old.txt`）：不重复 / 占位符 / 完成标准 ×2
    const g = groupCheckHits([
      hit({ check: 'no_echoed_text', ran: 3, note: '两段几乎是同一段' }),
      hit({ check: 'no_placeholder', ran: 6, note: '有占位句代替了内容' }),
      hit({ note: '在还没有日期的那 1 处行尾贴了「（日期待补）」' }),
      hit({ note: '你定的完成标准还没满足' }),
    ])
    expect(g).toHaveLength(3)
    expect(g[2].notes).toHaveLength(2)
  })

  it('判据宁可窄：判据名 / 维度 / 第几条有一样对不上就不合', () => {
    expect(groupCheckHits([hit(), hit({ check: 'no_placeholder' })])).toHaveLength(2)
    expect(groupCheckHits([hit(), hit({ dimension: 'coherence' })])).toHaveLength(2)
    expect(groupCheckHits([hit(), hit({ ran: 15 })])).toHaveLength(2)
  })

  it('只合**相邻**的：中间隔了一条别的就不合（不跨位置抓取、不重排）', () => {
    const g = groupCheckHits([hit({ note: 'A' }), hit({ check: 'no_placeholder', note: 'C' }), hit({ note: 'B' })])
    expect(g.map((x) => x.notes)).toEqual([['A'], ['C'], ['B']])
  })

  it('「卡住放行」和「收工」那两种各自单列，永不并进别人', () => {
    const g = groupCheckHits([hit({ stuck_rounds: 3 }), hit({ stuck_rounds: 3 }), hit({ stopped: true, stuck_rounds: 3 })])
    expect(g).toHaveLength(3)
  })
})

describe('P35 #7 收工那条 ⚑ 的空括号和措辞', () => {
  it('维度为空时连括号一起不要', () => {
    // 后端 `middleware/checks.after_run` 发的就是 `dimension: ""`，
    // 原来照直拼出「你定的完成标准（）已经连着 3 轮…」
    expect(dimParen('')).toBe('')
    expect(dimParen(undefined)).toBe('')
    expect(dimParen('factual_grounding')).toBe('（事实依据）')
  })

  it('收工那条不许再说「照常打分」——它已经停了', () => {
    expect(agentSrc).toContain("h.stopped ? '这一次不再往下写了。' : '这一轮不再拦，照常打分。'")
    // 空括号那一处必须走 dimParen，不许再有裸的「（{dimLabel(h.dimension)}）」
    expect(agentSrc).not.toContain('（{dimLabel(h.dimension)}）')
  })

  it('`stopped` 真的一路传到面板（类型上有这一格）', () => {
    const h: CheckHit = { dimension: '', note: 'x', stuck_rounds: 3, stopped: true }
    expect(h.stopped).toBe(true)
  })
})

describe('P35 #8 空托盘收成一句 + 折起来的说明', () => {
  it('那一句同时说掉「是空的」和「东西从哪来」', () => {
    expect(TRAY_EMPTY_LINE).toMatch(/空的/)
    expect(TRAY_EMPTY_LINE).toMatch(/放进托盘/)
    expect(TRAY_EMPTY_LINE).toMatch(/摊到这篇桌上/)
    expect(TRAY_EMPTY_LINE.length).toBeLessThan(60)      // 一句话，不是一段
  })

  it('规则是**折起来**不是删掉：空的那一支里有 details，展开还看得到那三条规矩', () => {
    expect(traySrc).toContain('tray-why')
    expect(traySrc).toContain('<summary>摊上来的材料有什么用、怎么摊</summary>')
    expect(traySrc).toContain('排最前、不被筛掉、不会滚出窗口')
  })

  it('有材料的时候还是原来那一段（这一刀只砍空托盘那一档）', () => {
    expect(traySrc).toContain('items.length > 0 ? (')
    expect(traySrc).toContain('className="muted tray-hint"')
  })
})
