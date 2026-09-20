/**
 * P31 走查（第二次打包版从头用一遍，P18–P29 十二批之后）当批修的四条——
 * 每条对着实拍的现象钉一个闸：
 *   #1 勾过的完成标准，关掉重开就没了（意图还是预填那份时，`resolveIntent` 把 `checked` 丢掉）
 *   #2 改动条（「改了 N 处 … 按层处置」）右半截被浮动按钮盖住（内联 margin 压过让位规则）
 *   #3 屏幕活动：没在记录，却说「今天刚开始记，攒够一段就会出现在这儿」
 *   #4 「只撤这一轮」撤不动时，提示里是一对空引号「」（纯空行那一处 snippet 为空）
 *
 * 判的是**用户看得见的东西**（角标还在不在、条露不露得出来、那句话说得对不对），不是代码长什么样；
 * 只有 CSS / JSX 这种跑不起来的，才退而求其次钉源码。
 */
import { describe, expect, it } from 'vitest'
import { resolveIntent, prefillIntent } from '../../util/docIntent'
import { checkDone, doneSummary } from '../../util/doneChecks'
import { undoRound, conflictLead } from '../undoRound'
import appSrc from '../../App.tsx?raw'
import journeySrc from '../../components/JourneyPage.tsx?raw'
import undoRoundSrc from '../undoRound.ts?raw'
// @ts-expect-error vitest 跑在 node 上；前端 tsconfig 没带 node 类型（styles.css 走 vite 的 css 管道，`?raw` 拿到空串，只能读文件）
import { readFileSync } from 'node:fs'
// @ts-expect-error 同上：node 的类型不在前端 tsconfig 里
import { fileURLToPath } from 'node:url'

const cssPath = fileURLToPath(new URL('../../styles.css', import.meta.url))
const css: string = readFileSync(cssPath, 'utf8')

describe('P31 #1 勾过的完成标准要活过一次重开', () => {
  // 实拍那一篇：标题「周报 9-20」，意图从没被改过（source=prefill），勾了「卡住的说清要什么」
  const title = '周报 9-20'
  const stored = { ...prefillIntent(title), checked: ['卡住的说清要什么'] }

  it('意图还是预填的那份：重开之后 checked 还在', () => {
    expect(resolveIntent(stored, title).checked).toEqual(['卡住的说清要什么'])
  })

  it('角标不再退回 0/2——这是用户唯一看得见的那个数', () => {
    const after = resolveIntent(stored, title)
    // 正文一段都没有，代码判的那条必然不过；手勾的那条要算进去
    const sum = doneSummary(checkDone(after.done, '', after.checked ?? []))
    expect(sum.ok).toBe(1)
    expect(sum.total).toBe(2)
  })

  it('用户改过意图（source=user）那一支照旧原样带回', () => {
    const mine = { goal: 'g', reader: 'r', done: '甲；乙', source: 'user' as const, checked: ['乙'] }
    expect(resolveIntent(mine, title)).toEqual(mine)
  })

  it('标题换了、判据跟着换：对不上的勾作废，不留幽灵勾', () => {
    // 「周报」→「会议纪要」，完成标准整句都不一样了
    const after = resolveIntent(stored, '9-20 会议纪要')
    expect(after.done).toBe(prefillIntent('9-20 会议纪要').done)
    expect(after.checked ?? []).toEqual([])
  })

  it('库里没有 checked / 是空数组：跟原来一样，不平白多一个字段', () => {
    expect(resolveIntent(prefillIntent(title), title).checked).toBeUndefined()
    expect(resolveIntent({ ...prefillIntent(title), checked: [] }, title).checked).toBeUndefined()
  })

  it('空串不会当成「命中」（done.includes("") 恒真）', () => {
    const after = resolveIntent({ ...prefillIntent(title), checked: [''] }, title)
    expect(after.checked ?? []).toEqual([])
  })

  it('「跟着标题重推」那个 effect 传的是现在这份意图，不是 null', () => {
    // 这个 effect 也挂在 current?.id 上，每开一篇都会在「从库里读」之后再跑一次；
    // 传 null = 拿干净的预填把刚读出来的盖掉，checked 又没了（P31 实拍：改完 resolveIntent
    // 还是 0/2，就是栽在这一行）。
    // P43 #2 起第二个实参从 `title`（标题框那一格）换成了 `shownTitle`
    // （= `displayTitle({ title, content })`，界面上到处显示的那个名字）。
    // **这一条守的性质一个字没变**：传下去的第一个实参还是 `i`（现在这份意图），不是 `null`。
    expect(appSrc).toContain("setIntent((i) => (i.source === 'user' ? i : resolveIntent(i, shownTitle)))")
    // 全文里 `resolveIntent(null, …)` 只许有一处：`useState` 的初值（那会儿真的什么都没有）
    expect(appSrc.match(/resolveIntent\(null,/g) ?? []).toHaveLength(1)
    expect(appSrc).not.toContain('resolveIntent(null, title)')
  })
})

describe('P31 #2 改动条要从浮动按钮底下露出来', () => {
  it('JSX 里不再写死上边距（内联 style 会压过 styles.css 的让位规则）', () => {
    const i = appSrc.indexOf('pending-diff-bar')
    expect(i).toBeGreaterThan(0)
    // 那个 <div> 的 style={{...}} 里不能再出现 margin / marginTop
    const chunk = appSrc.slice(i, i + 400)
    expect(chunk).not.toMatch(/margin(Top)?:/)
  })
  it('styles.css 给它留了位，且紧跟浮动按钮时让到 --s-8（按钮 28px 高、sticky 不占高度）', () => {
    expect(css).toContain('.note-body > .floating-buttons + .pending-diff-bar { margin-top: var(--s-8); }')
    expect(css).toMatch(/\.pending-diff-bar \{ margin: var\(--s-2\)/)
  })
})

describe('P31 #3 屏幕活动：没在记录就别说「今天刚开始记」', () => {
  it('「今天刚开始记」只在 state === running 时说', () => {
    // 文件开头的注释里也提过这句话，要的是 JSX 里真正渲染的那一处（最后一次出现）
    const i = journeySrc.lastIndexOf('今天刚开始记')
    expect(i).toBeGreaterThan(0)
    expect(journeySrc.slice(Math.max(0, i - 120), i)).toContain("state === 'running'")
  })
  it('没在记录 / 暂停各有自己那句，并且都指出下一步怎么办', () => {
    expect(journeySrc).toContain('现在没在记录，点右上角「开始记录」才会开始攒')
    expect(journeySrc).toContain('现在是暂停着的，「继续记录」之后才会接着记')
  })
})

describe('P31 #4 撤不动时不能甩一对空引号', () => {
  it('纯空行 / 纯换行那一处：不再是「」，改说是第几处', () => {
    // 实拍那几处就是这个样子：第 2 轮已经撤过一次，剩下的 hunk 全是段落间的空行
    for (const blank of ['\n\n', '\n', '   ', '\t', '\n \n']) {
      expect(conflictLead(blank, 2)).toBe('第 2 处（只有空行、没有可引的原文）')
      expect(conflictLead(blank, 2)).not.toContain('「」')
    }
  })
  it('有原文的照旧引原文，并且照旧截到 24 字', () => {
    expect(conflictLead('第1轮假模型写的第一句', 1)).toBe('「第1轮假模型写的第一句」')
    expect(conflictLead('一'.repeat(40), 1)).toBe('「' + '一'.repeat(24) + '…」')
  })
  it('原文里的换行折成空格之后仍有字：引它，不当成空', () => {
    expect(conflictLead('上面一句\n下面一句', 3)).toBe('「上面一句 下面一句」')
  })
  it('两处 push 冲突的地方都走 conflictLead（不再手写「${snippet(...)}」）', () => {
    expect(undoRoundSrc).not.toMatch(/conflicts\.push\(`「\$\{snippet/)
    expect((undoRoundSrc.match(/conflictLead\(/g) ?? []).length).toBe(2)   // 两处 conflicts.push
  })
  it('撤得动的时候一条冲突都不该有（别把这条修成到处报错）', () => {
    const r = undoRound('原来这句。', '原来这句。新写的一段。', '原来这句。新写的一段。', [])
    expect(r.undone).toBe(1)
    expect(r.conflicts).toEqual([])
    expect(r.text).toBe('原来这句。')
  })
})
