/**
 * P32：
 *   #2 块产出形状不对就不落正文（P31 #7）
 *   #3 空库新用户的右栏图例折成一句（P31 #8）
 *   A5 「为什么给我看这条」里那半句「这个词凭什么算证据」
 */
import { describe, expect, it } from 'vitest'
import { blockShapeProblem, looksLikeJson, shapeOf } from '../blockShape'
import { evidenceLine, evidenceWhy } from '../../util/recallContext'
import { KB_EMPTY_NOTE } from '../marginMemory'

import appSrc from '../../App.tsx?raw'
import memSrc from '../../components/RelatedMemory.tsx?raw'
import runSrc from '../runningBlocks.ts?raw'

// P31 #7 实拍到的那一串（假模型 `ok` 档回的就是它，真模型答不合形状时长一个样）
const P31_JSON = '{"text": "（假模型改写）这一段由假模型返回。", "reason": "假模型"}'

describe('P32 #2 形状不对不落正文', () => {
  it('整串 JSON 拦下来，给一句人话', () => {
    const say = blockShapeProblem('chart', P31_JSON)
    expect(say).toMatch(/JSON/)
    expect(say).toMatch(/没有落进正文/)
    expect(say).toMatch(/重试/)
    // 那句话是**纯文本**摆在占位块上，别写 markdown 粗体（第一版实拍原样露出 `**`）
    expect(say).not.toMatch(/\*\*/)
  })

  it('判据宁可窄：像 JSON 但 parse 不了的正常句子不拦', () => {
    // **两头都撞上**才是真正要挡的那种误伤：`{` 开头、`}` 结尾，但根本 parse 不了。
    // 只看开头那个花括号的话，这一句会被当成 JSON 拦下来（突变验钉着这一条）。
    const braces = '{产品名} 的定价还没定，先看 {留存}'
    expect(looksLikeJson(braces)).toBe(false)
    expect(blockShapeProblem('prompt', braces)).toBe('')
    expect(looksLikeJson('{产品名} 的定价还没定')).toBe(false)
    expect(blockShapeProblem('prompt', '{产品名} 的定价还没定')).toBe('')
    expect(blockShapeProblem('prompt', '这是一段正常的正文。')).toBe('')
    // 裹了一层围栏的 JSON 照样算 JSON
    expect(looksLikeJson('```json\n{"a":1}\n```')).toBe(true)
    // 数组也是
    expect(looksLikeJson('[{"a":1}]')).toBe(true)
  })

  it('该是表格的没有一行 `|` 就拦；有就放行', () => {
    expect(blockShapeProblem('table', '这是一段说明，不是表格。')).toMatch(/表格/)
    expect(blockShapeProblem('table', '| 名称 | 数量 |\n| --- | --- |\n| A | 1 |')).toBe('')
  })

  it('数据可视化要一张图：围栏或图片都算', () => {
    expect(blockShapeProblem('eda', '我建议画一张柱状图。')).toMatch(/图/)
    expect(blockShapeProblem('eda', '```mermaid\npie title x\n```')).toBe('')
    expect(blockShapeProblem('eda', '![图](/api/assets/a.png)')).toBe('')
  })

  it('智能插图只过 JSON 这一档——它的产出形状本来就不唯一（图表 / 文生图 / 说明）', () => {
    expect(shapeOf('chart')).toBe('markdown')
    expect(blockShapeProblem('chart', '这一版的对比可以这样看：先看留存再看时长。')).toBe('')
    // `/` 菜单新加一项时默认落在 markdown，不会静默开出一道新闸
    expect(shapeOf('某个还没有的新模式')).toBe('markdown')
  })

  it('空产出不归这条管（另有「没有产出内容」那条路）', () => {
    expect(blockShapeProblem('table', '   ')).toBe('')
  })

  it('接线：runBlock 在落正文**之前**问形状，拦下来就不 dispatch changes', () => {
    const i = appSrc.indexOf('const badShape = blockShapeProblem(item.key, text)')
    const j = appSrc.indexOf('v.dispatch({ changes: { from: at, insert: textToLand(')
    expect(i).toBeGreaterThan(0)
    expect(j).toBeGreaterThan(i)          // 校验在落地之前
    expect(appSrc).toMatch(/patchRun\.of\(\{ id, error: badShape, expanded: true, retry: true \}\)/)
  })

  it('接线：占位块上真的有一个「重试」按钮，且只在 retry + error 时出现', () => {
    expect(runSrc).toMatch(/if \(r\.retry && r\.error\)/)
    expect(runSrc).toMatch(/again\.textContent = '重试'/)
    expect(appSrc).toMatch(/onRetryRun=\{retryRun\}/)
    expect(appSrc).toMatch(/retryArgs\.current\.set\(id, \{ item, prompt \}\)/)
  })
})

describe('P32 #3 空库图例折成一句', () => {
  it('那一句既说了「不画圆点」也说了什么时候开始判（P17 #8 要的两件事一件没少）', () => {
    expect(KB_EMPTY_NOTE).toMatch(/不画圆点/)
    expect(KB_EMPTY_NOTE).toMatch(/第一条记录/)
  })
  it('空库那一支只出一句 + 一个「导入」入口，四段规则收进 details', () => {
    const empty = memSrc.slice(memSrc.indexOf('{kbEmpty ? ('), memSrc.indexOf('{KB_EMPTY_NOTE}') + 400)
    expect(empty).toMatch(/\{KB_EMPTY_NOTE\}/)
    expect(empty).toMatch(/app:import/)
    expect(empty).toMatch(/<details/)
    // 六种颜色那一排**不在**空库这一支里（信息量为零却占掉大半屏）
    expect(empty).not.toMatch(/RELATION_LABEL/)
  })
})

describe('P32 A5 为什么这个词算证据', () => {
  it('三种理由各说一句人话，带上库里有多少条提到它', () => {
    expect(evidenceWhy({ why: 'vocab', units: 30 })).toBe('知识库里的词条 · 库里 30 条提到')
    expect(evidenceWhy({ why: 'span', units: 0 })).toBe('整段原话对上')
    expect(evidenceWhy({ why: 'pair', units: 5 })).toMatch(/跟别的词一起/)
  })
  it('面板那一行把「命中什么」和「凭什么」一起说', () => {
    const line = evidenceLine('cursor', [
      { term: 'kol', why: 'vocab', units: 30 },
      { term: '电池容量', why: 'span', units: 6 },
    ], ['kol'])
    expect(line).toBe('按光标这段找的，命中：kol（知识库里的词条 · 库里 30 条提到）、电池容量（整段原话对上 · 库里 6 条提到）')
  })
  // **P46 #1 改了这两条喂进去的值，守的性质一个字没变**：「后端没给这一格」
  // 从 `[]` 改成 `undefined` / `null` 来表示（`[]` 现在专指「判过了，一条都摆不出来」）。
  // 这一条钉的一直是「**没人判过**的时候退回原来那句、不是空白」。
  it('后端没给 evidence（老版本 / 兜底）时退回原来那句，不是空白', () => {
    expect(evidenceLine('tail', undefined, ['众筹', '上线'])).toBe('按正文末尾找的，命中：众筹、上线')
    expect(evidenceLine('tail', null, ['众筹', '上线'])).toBe('按正文末尾找的，命中：众筹、上线')
    expect(evidenceLine('tail', undefined, [])).toBe('按正文末尾找的')
  })
  it('接线：面板真的在用 evidenceLine，而且 evidence 跟着每次召回更新', () => {
    expect(memSrc).toMatch(/\{evidenceLine\(mode, evidence, terms\)\}/)
    // `?? null` 而不是 `?? []`：压成 `[]` 就把「没判成」和「判过了、空的」并成一档（P46 #1）
    expect(memSrc).toMatch(/setEvidence\(r\.evidence \?\? null\)/)
  })
})
