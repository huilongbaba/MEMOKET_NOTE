/**
 * P37（P35 留下的三个 ❌ + 两条遗留）的前端那一半：
 *   #2 「校验」空手而归的三种来历，各说各的（`emptyVerifyLine`）
 *   #3 「来龙去脉」那句 502 不许再带「打开设置」（`friendlyError` / `isLlmUnreachable`）
 *   #4 「扩展上下文」不许替模型说「认为不需要补充上下文」（`unparsedEditNote`）
 *   #5 待处置的改动层关掉就没了 —— 至少先说一句
 *   #1 那条判据在后端（`harness/checks/shape.py`），这里只钉「前端的判法跟它是同一条」
 *
 * 每条断言的量程写在 it 的描述或注释里。**每条修法都配一条「真的接上了」的断言**
 * ——函数对了但没接上，纯函数层的单测一条都抓不住（P32 / P34 / P36 各栽过一次）。
 */
import { describe, expect, it } from 'vitest'
import { looksLikeJson, unparsedEditNote } from '../blockShape'
import { emptyVerifyLine } from '../../components/VerifyPanel'
import { friendlyError, isLlmUnreachable } from '../../util/friendlyError'

import appSrc from '../../App.tsx?raw'
import verifySrc from '../../components/VerifyPanel.tsx?raw'
import layersSrc from '../../components/ChangeLayersPanel.tsx?raw'
import dimLabelSrc from '../dimLabel.ts?raw'

// 后端 `routers/memory.trace` 那句 502 的**逐字原文**。改一个字这里就得跟着改，
// 那正是这条闸要的：两边是一句话，不是两句凑巧像的话。
const TRACE_502 = '502 模型答的不是这个动作要的格式（不是没应答，供应商是通的）——换个模型，或者再试一次'

describe('P37 #2 「校验」空手而归的三种来历，各说各的', () => {
  it('查到了 N 条、模型没按格式答 —— 不许说「知识库里没有相关信息」', () => {
    // P35 实拍就是这一格：terrence 20417 条事实，词法召回真的回了 1 条，
    // 模型答得不合形状，而界面说「知识库里没有相关信息」——说的是假话。
    const say = emptyVerifyLine(1, true)
    expect(say).toContain('没按要求的格式')
    expect(say).toContain('1 条')
    expect(say).not.toContain('知识库里没有相关信息')
  })

  it('一条都没查到 —— 原来那句话在这一档才是对的', () => {
    expect(emptyVerifyLine(0, false)).toContain('知识库里没有相关信息')
  })

  it('查到了 N 条、模型按格式答了但没话说 —— 第三句，也不是「没有记录」', () => {
    const say = emptyVerifyLine(3, false)
    expect(say).toContain('3 条')
    expect(say).not.toContain('知识库里没有相关信息')
    expect(say).not.toContain('没按要求的格式')
  })

  it('三档说的是三句不一样的话（不然分开就没有意义）', () => {
    const three = new Set([emptyVerifyLine(1, true), emptyVerifyLine(0, false), emptyVerifyLine(3, false)])
    expect(three.size).toBe(3)
  })

  it('unparsed 但一条也没查到：不许冒出「0 条相关记录」这种话', () => {
    expect(emptyVerifyLine(0, true)).not.toMatch(/0 条/)
  })

  it('接线：面板那句话真的走 emptyVerifyLine，不是又写死了一句', () => {
    // 量程：把 `{emptyVerifyLine(checked, unparsed)}` 改回那句写死的中文，这条红。
    expect(verifySrc).toContain('{emptyVerifyLine(checked, unparsed)}')
    // 写死那句只许待在 `emptyVerifyLine` 那个纯函数里（和模块头那段「原来说的是什么」的
    // 引文里），**组件的 JSX 里一次都不许再出现**——不然分三档就白分了。
    const jsx = verifySrc.slice(verifySrc.indexOf('export default function VerifyPanel'))
    expect(jsx).not.toContain('没有找到能支持或反驳这段内容的记录')
  })

  it('接线：App 把整个回包传下去，checked / unparsed 一格都没丢在半路', () => {
    // 量程：把 `<VerifyPanel ... checked=...>` 那一行删掉，这条红。
    // P41 #3 起这一格还多带一个 `passage`（卡上要写清「说的是哪一段」）——
    // **守的性质一个字没变**：整个回包原样传下去，`checked` / `unparsed` 不许丢在半路。
    expect(appSrc).toMatch(/setVerifyResult\(\{ \.\.\.r, passage: selection \}\)/)
    expect(appSrc).toContain('checked={verifyResult.checked ?? 0}')
    expect(appSrc).toContain('unparsed={verifyResult.unparsed ?? false}')
    // 老的那条路（只留 findings）不许再有
    expect(appSrc).not.toContain('setVerifyFindings')
  })
})

describe('P37 #3 「来龙去脉」那句 502：说清楚，但不许指去设置页', () => {
  it('后端翻好的中文原样给用户看（状态码不进界面）', () => {
    expect(friendlyError(new Error(TRACE_502))).toBe(TRACE_502.replace(/^502 /, ''))
  })

  it('不带「打开设置」——那是「连不上」那一档的出口', () => {
    // **这条是 P37 #3 的正题**：`isLlmUnreachable` 为 true 的话 `handleSelectionAction`
    // 就会挂上「打开设置」，而供应商明明是通的。
    // 量程：把后端那句改成以「后端处理出错」开头，这条红。
    expect(isLlmUnreachable(new Error(TRACE_502))).toBe(false)
  })

  it('真·连不上那一档照旧带「打开设置」（判据窄，没误伤到隔壁）', () => {
    expect(isLlmUnreachable(new Error('All connection attempts failed'))).toBe(true)
    expect(isLlmUnreachable(new Error('500 Internal Server Error'))).toBe(true)
  })

  it('接线：右键那条 catch 仍然按 isLlmUnreachable 决定挂不挂「打开设置」', () => {
    expect(appSrc).toContain("else if (isLlmUnreachable(e)) toastAction(`操作失败：${friendlyError(e)}`, '打开设置'")
  })
})

describe('P37 #4 「扩展上下文」不许替模型表态', () => {
  it('抽不出建议时说的是「没按格式答」，不是「模型认为不需要」', () => {
    const say = unparsedEditNote('扩展上下文')
    expect(say).toContain('没按要求的格式')
    expect(say).toContain('正文一个字没动')
    expect(say).not.toContain('认为不需要')
    expect(say).not.toMatch(/\*\*/)          // 走 toast，纯文本（P32 第一版栽过一次）
  })

  it('接线：三个动作都把 r.unparsed 传给 landRevisions', () => {
    // 量程：把任意一支末尾的 `, r.unparsed` 删掉，这条红。
    expect(appSrc).toContain("landRevisions(r.revisions, r.note, '扩展上下文', '模型认为不需要补充上下文。', r.unparsed)")
    expect(appSrc).toContain("'模型没有给出修改建议。', r.unparsed)")
  })

  it('接线：landRevisions 在 unparsed 那一档真的换了话，没有只多收一个没人读的参数', () => {
    // 量程：把 `unparsed ? unparsedEditNote(label) : emptyNote` 改回 `emptyNote`，这条红。
    expect(appSrc).toContain('unparsed ? unparsedEditNote(label) : emptyNote')
  })
})

describe('P37 #5 → P39：那句话现在说的是「留着」，因为它真的留着了', () => {
  // P37 那会儿层一行都不落库，所以两处各写了一句「关掉这个 app 就当接受了」——
  // **不许它静悄悄**。P39 把层落进了 `note_change_layers`，那句话就成了假话，
  // 于是两处都改成说真相。这两条钉的是**同一件事的两个方向**：界面上的话要跟
  // 库里的行为对得上（P37 #2 / #3 那两条「说假话」是同一个形状）。
  it('改动条上说的是「关掉再打开还挂在这儿」，不再是「就当接受了」', () => {
    expect(appSrc).toContain('关掉这个 app 再打开，这些改动还挂在这儿')
    expect(appSrc).not.toContain('关掉这个 app 就当接受了')
  })

  it('分层面板那一段也改了，而且说清了逐处按下去的那几下也留着', () => {
    expect(layersSrc).toContain('关掉这个 app 再打开，这几层和你逐处按下去的接受 / 撤回都还在')
    expect(layersSrc).not.toContain('不会留到下次打开')
  })
})

describe('P37 #1 后端那条判据的前端那一半', () => {
  it('前端的判法就是后端 `looks_like_json` 的孪生（两边逐字同一条）', () => {
    // 后端 `app/harness/checks/shape.py` 里那几条断言的同一组样本。
    expect(looksLikeJson('{"text": "x", "reason": "y"}')).toBe(true)
    expect(looksLikeJson('```json\n{"a": 1}\n```')).toBe(true)
    expect(looksLikeJson('[{"a": 1}]')).toBe(true)
    expect(looksLikeJson('{产品名} 的定价还没定，先看 {留存}')).toBe(false)
    expect(looksLikeJson('{"text": "没闭合')).toBe(false)
    expect(looksLikeJson('')).toBe(false)
  })

  it('接线：那条判据的名字在面板上有中文名，不会原样蹦出 output_not_json', () => {
    // 量程：把 `dimLabel.ts` 里那一行删掉，后端 `test_why_this_round` 和这条一起红。
    expect(dimLabelSrc).toContain('output_not_json:')
  })
})
