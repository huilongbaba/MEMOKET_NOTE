// @vitest-environment jsdom
/**
 * P46（`docs/TRACELOG-product.md` P46 节）：P43 / P44 留下的前端两条。
 *
 * · **#1（P44 问题 #3）** 证据被砍光时前端兜底退回**更碎的串**。
 *   P44 的两条显示过滤让 9 / 765 条查询的证据列表空掉，`evidenceLine` 退回
 *   `display_terms`，摆出来的是「矿山行业最重要、**希望通过智能化能**、矿区工作环境恶劣」——
 *   **比被砍掉的那个碎片还长**（`display_terms` 会往后接到汉字串的尽头）。
 *   后端已经判出「这些串都不合格」，前端不该拿一份**没判过**的去顶。
 *   修法：`[]`（判过了、一条都摆不出来）和 `null` / `undefined`（没判成）**分开**，
 *   前者如实说一句，后者照旧退回 `terms`。
 *
 * · **#4（P43 留给下一批 ③ / P41 留的第 4 条）** 「说的是你选中的这一段」那两行**点不了**。
 *   P43 #5 把这一行抄到了「脉络」上，两块卡都报了户口，但用户看完还得自己回正文找。
 *   修法：`passageLine` 判「这一段在正文第几行」，**唯一命中才给跳**（跟
 *   `changeLayers.relocate` 同一条规矩），跳本身复用 P12 的 `jumpToLine`。
 *   跳不回去时调用方不给 `onJump`——**一个点了没反应的链接比不能点更糟**。
 */
import { describe, expect, it } from 'vitest'
import appSrc from '../../App.tsx?raw'
import memSrc from '../../components/RelatedMemory.tsx?raw'
import verifySrc from '../../components/VerifyPanel.tsx?raw'
import { NO_EVIDENCE_LINE, evidenceLine } from '../../util/recallContext'
import { passageLine, verifyScopeLine } from '../../components/VerifyPanel'

describe('P46 #1 证据被砍光时不许退回更碎的串', () => {
  it('判过了、一条都摆不出来：如实说一句，**不摆 terms**', () => {
    // 这几个 `terms` 就是 P44 实拍那一行（`empty44.txt`）
    const terms = ['矿山行业最重要', '希望通过智能化能', '矿区工作环境恶劣']
    const line = evidenceLine('cursor', [], terms)
    expect(line).toBe('按光标这段找的，' + NO_EVIDENCE_LINE)
    for (const t of terms) expect(line).not.toContain(t)
  })

  it('没判成（老后端 / 判据自己抛了）：照旧退回原来那句', () => {
    const terms = ['众筹', '上线']
    expect(evidenceLine('tail', undefined, terms)).toBe('按正文末尾找的，命中：众筹、上线')
    expect(evidenceLine('tail', null, terms)).toBe('按正文末尾找的，命中：众筹、上线')
  })

  it('**`[]` 和 `null` 必须走出不同的两句**——压成一档就是 P44 问题 #3 本身', () => {
    const terms = ['希望通过智能化能']
    expect(evidenceLine('cursor', [], terms)).not.toBe(evidenceLine('cursor', null, terms))
  })

  it('有证据时一个字没变（P32 A5 那一行照旧）', () => {
    expect(evidenceLine('cursor', [
      { term: 'kol', why: 'vocab', units: 30 },
      { term: '电池容量', why: 'span', units: 6 },
    ], ['kol'])).toBe(
      '按光标这段找的，命中：kol（知识库里的词条 · 库里 30 条提到）、电池容量（整段原话对上 · 库里 6 条提到）')
  })

  it('接线洞：面板真的把 `null` 传下去了，不是 `?? []` 压成空数组', () => {
    expect(memSrc).toMatch(/useState<RecallEvidence\[\] \| null>\(null\)/)
    expect(memSrc).toMatch(/setEvidence\(r\.evidence \?\? null\)/)
    expect(memSrc).not.toMatch(/setEvidence\(r\.evidence \?\? \[\]\)/)
    // 查询太短那一档清空时也得回 `null`（那时候确实没人判过）
    expect(memSrc).toMatch(/setEvidence\(null\); setWhyEmpty/)
  })
})

describe('P46 #4 「说的是你选中的这一段」那两行能跳回去', () => {
  const body = '第一段。\n\n这周把众筹页面的文案定稿了，3月12号上线。\n\n第三段。'

  it('在正文里不多不少一处：回它的行号（1 起，跟 CodeMirror 的 `doc.line(n)` 对齐）', () => {
    expect(passageLine(body, '第一段。')).toBe(1)
    expect(passageLine(body, '这周把众筹页面的文案定稿了，3月12号上线。')).toBe(3)
    expect(passageLine(body, '第三段。')).toBe(5)
  })

  it('**一处都没有就不跳**（后来改过 / 删了，= `verifyScopeLine` 的 `gone` 那一档）', () => {
    expect(passageLine(body, '这一段早就被删了')).toBeNull()
    // 那一档卡上照旧多说一句，两边说的是同一件事
    expect(verifyScopeLine('这一段早就被删了', true)).toContain('正文后来改过')
  })

  it('**出现两次以上也不跳**——跳到第一处就是替用户猜他指的是哪一处', () => {
    const twice = '同一句话。\n\n中间。\n\n同一句话。'
    expect(passageLine(twice, '同一句话。')).toBeNull()
  })

  it('空的、没正文：不跳，也不抛', () => {
    expect(passageLine(body, '')).toBeNull()
    expect(passageLine(body, '   ')).toBeNull()
    expect(passageLine('', '第一段。')).toBeNull()
  })

  it('接线洞：两块卡用的是**同一个** `jumpToPassage`，而且它接的是 P12 的 `jumpToLine`', () => {
    expect(appSrc).toContain('import VerifyPanel, { passageLine, verifyScopeLine }')
    expect(appSrc).toMatch(/const jumpToPassage = useCallback\(/)
    expect(appSrc).toMatch(/passageLine\(content, passage \?\? ''\)/)
    expect(appSrc).toMatch(/line === null \? undefined : \(\) => jumpToLine\(line\)/)
    // 「校验结果」那块
    expect(appSrc).toContain('onJump={jumpToPassage(verifyResult.passage)}')
    // 「脉络」那块：守门那一行也钉（P43 突变验 #12 第一版就是砍空在这儿）
    const at = appSrc.indexOf("id: 'trace', title: '脉络'")
    expect(at).toBeGreaterThan(0)
    const block = appSrc.slice(at, at + 1600)
    expect(block).toContain('{jumpToPassage(trace.passage)')
    expect(block).toContain('clickable(jumpToPassage(trace.passage)!)')
  })

  it('接线洞：`VerifyPanel` 里那一行真的挂上了 `onJump`，而且没给就不是按钮', () => {
    expect(verifySrc).toContain('{...clickable(onJump)}')
    expect(verifySrc).toMatch(/onJump\s*\n?\s*\? <span className="scope-jump"/)
    // 判据在 `passageLine` 里，`verifyScopeLine` 那句话一个字没动
    expect(verifyScopeLine('一段话')).toBe('说的是你选中的这一段：「一段话」')
  })
})

describe('P46 #5 标题编辑不会触发写作任务生成', () => {
  it('旧的标题防抖和重推链路已移除', () => {
    expect(appSrc).not.toContain('INTENT_PREFILL_IDLE_MS')
    expect(appSrc).not.toContain('settledTitle')
    expect(appSrc).not.toContain('resolveIntent(i, shownTitle)')
  })

  it('任务只在打开笔记和用户保存时变化', () => {
    expect(appSrc).toContain('setIntent(resolveIntent(n.intent, d.title))')
    expect(appSrc).toContain('const saveIntent = useCallback')
  })
})
