// @vitest-environment jsdom
/**
 * P1（产品就绪计划 §3，用户第 768 轮点名的六条）里前端管得着的四条：
 *
 *   1b  轮次卡片上「技能：…」那一行——用户判断「Skill 到底加载了没有」的唯一依据
 *   1d  页边圆点：不封顶、分批；悬停那句话把规则说全
 *   2-B1 / 2-B2  `/` 块生成的临界条件（空指令 / 空选区 / 超长 / 空白笔记）——前端不发请求
 *   3   正文永远 `--fg`：列表项、引用块的文字不能再是 muted；记号（- / 1. / >）才淡
 *
 * 另有一条顺手抓到的：记忆范围 'screen' 读回来变 'all'。
 */
import { describe, expect, it } from 'vitest'
import { EditorState } from '@codemirror/state'
import { markdown } from '@codemirror/lang-markdown'
import { syntaxTree } from '@codemirror/language'
import { tags } from '@lezer/highlight'

import { MARKDOWN_HIGHLIGHT_SPEC, MARK_NODES } from '../theme'
import { blockPrecondition, MAX_PROMPT_CHARS, SLASH_ITEMS } from '../slashMenu'
import { chunked, MARGIN_BATCH, marginParagraphs, markTitle, RELATION_LABEL } from '../marginMemory'
import { skillsLine } from '../../components/AgentActivity'
import { memoryScope, MEMORY_SCOPE_KEY, SCOPE_LABEL } from '../../api'

// ------------------------------------------------------------------ 3 灰色字

describe('正文永远 --fg（P1-3）', () => {
  it('列表和引用块的文字不设颜色——它们是正文，lezer 的 /... 会把颜色传给整段', () => {
    const list = MARKDOWN_HIGHLIGHT_SPEC.find((r) => r.tag === tags.list)
    const quote = MARKDOWN_HIGHLIGHT_SPEC.find((r) => r.tag === tags.quote)
    expect(list && 'color' in list).toBe(false)
    expect(quote && 'color' in quote).toBe(false)
    // 整张表里只有 url（`[文字](地址)` 的地址，是标记）允许 muted
    const muted = MARKDOWN_HIGHLIGHT_SPEC.filter((r) => 'color' in r && String((r as { color?: string }).color).includes('muted'))
    expect(muted.map((r) => r.tag)).toEqual([tags.url])
  })
  it('lezer 确实把 BulletList / Blockquote 的 tag 传给了后代——这就是原来整段变灰的机制', () => {
    const state = EditorState.create({ doc: '- 列表里的正文\n\n> 引用里的正文\n', extensions: [markdown()] })
    const names: string[] = []
    syntaxTree(state).iterate({ enter: (n) => { names.push(n.name) } })
    expect(names).toContain('BulletList'); expect(names).toContain('ListMark')
    expect(names).toContain('Blockquote'); expect(names).toContain('QuoteMark')
  })
  it('列表记号跟 # ** > 一样走 .cm-syntax-mark 淡显', () => {
    expect(MARK_NODES.has('ListMark')).toBe(true)
    expect(MARK_NODES.has('QuoteMark')).toBe(true)
  })
})

// ------------------------------------------------------------------ 2-B1 / 2-B2 临界条件

describe('`/` 块生成的临界条件（P1-2-B1 / 2-B2）', () => {
  const custom = SLASH_ITEMS.find((i) => i.key === 'prompt')!   // 跟右键「自定义提示」同一套 needsPrompt
  const item = (key: string) => ({ ...(SLASH_ITEMS.find((i) => i.key === key) ?? custom), key })
  it('右键自定义：空指令 / 只有空格 → 不放行，且是那句给人看的话', () => {
    const c = { key: 'custom', needsPrompt: true }
    expect(blockPrecondition(c, '', '选中的一段', '正文')).toContain('先写一句')
    expect(blockPrecondition(c, ' \n\t', '选中的一段', '正文')).toContain('先写一句')
  })
  it('右键自定义：选区为空 → 不放行', () => {
    expect(blockPrecondition({ key: 'custom', needsPrompt: true }, '改口语', '  ', '正文')).toContain('没有选中')
  })
  it('超长指令 → 不放行，上限跟后端同一个数', () => {
    expect(MAX_PROMPT_CHARS).toBe(2000)
    expect(blockPrecondition({ key: 'custom', needsPrompt: true }, 'x'.repeat(2001), '一段', '正文')).toContain('太长')
    expect(blockPrecondition({ key: 'custom', needsPrompt: true }, 'x'.repeat(2000), '一段', '正文')).toBe('')
  })
  it('空白笔记上：插图 / 表格 / 可视化 / 分析都拦；「用 AI 写」有一条指令就够', () => {
    for (const k of ['chart', 'table', 'eda', 'analysis']) expect(blockPrecondition(item(k), '随便', '', '  \n')).toContain('笔记还是空的')
    expect(blockPrecondition(item('prompt'), '写一段开场白', '', '')).toBe('')
    expect(blockPrecondition(item('chart'), '', '', '一句正文')).toBe('')
  })
  it('智能表格允许留空——输入框上写着「留空则自动判断」', () => {
    const table = SLASH_ITEMS.find((i) => i.key === 'table')!
    expect(table.promptOptional).toBe(true)
    expect(blockPrecondition(table, '', '', '有表格的正文')).toBe('')
  })
  it('AI 组每一条在空白笔记上的行为都有定论（P3 临界条件表的种子）', () => {
    // 走块生成的四条拦；prompt 靠指令；其余三条（图片转表格 / 语音 / 插音频）不吃正文
    const ai = SLASH_ITEMS.filter((i) => i.group === 'AI')
    const verdict = Object.fromEntries(ai.map((i) => [i.key, blockPrecondition(i, i.needsPrompt && !i.promptOptional ? '有指令' : '', '', '') ? 'blocked' : 'allowed']))
    expect(verdict).toEqual({ prompt: 'allowed', chart: 'blocked', table: 'blocked', 'table-image': 'allowed', eda: 'blocked', analysis: 'blocked', voice: 'allowed', audio: 'allowed' })
  })
})

// ------------------------------------------------------------------ 1d 页边圆点

describe('页边圆点（P1-1d）', () => {
  const clean = (s: string) => s
  it('门槛跟后端同一条：≥8 字、含数字、不是标题；不封顶', () => {
    const many = Array.from({ length: 150 }, (_, i) => `第 ${i} 段，定金 199 元，写够八个字。`).join('\n\n')
    const paras = marginParagraphs(many + '\n\n# 标题 2026\n\n短 1\n\n没有数字的一段写够八个字。', clean)
    expect(paras.length).toBe(150)
    expect(chunked(paras, MARGIN_BATCH).map((c) => c.length)).toEqual([80, 70])
  })
  it('悬停那句话：一段 · 关系 · 人话 · 规则 · 还有别的', () => {
    const t = markTitle({ line: 12, relation: 'conflict', say: '跟知识库 5-8 的记录不一致', kinds: 2 })
    expect(t).toContain('这一段（第 12 行起）· 冲突')
    expect(t).toContain('每段一个')
    expect(t).toContain('含数字 / 日期')
    expect(t).toContain('另外 1 种关系')
    expect(markTitle({ line: 1, relation: 'corroborated', say: 'x' })).not.toContain('另外')
    expect(Object.keys(RELATION_LABEL).sort()).toEqual(['accumulation', 'conflict', 'continuation', 'corroborated', 'merge', 'unsupported'])
  })
})

// ------------------------------------------------------------------ 1b 技能那一行

describe('轮次卡片上的「技能」（P1-1b）', () => {
  it('带了几条、哪几条、还有几条留给模型', () => {
    expect(skillsLine({ injected: ['写作不走默认', '术语一致'], menu: [] })).toBe('技能：按范围自动带上 2 条：写作不走默认、术语一致')
    expect(skillsLine({ injected: [], menu: ['第三方 A'] })).toBe('技能：这个范围没有配技能，一条都没带；另有 1 条没配范围，留给模型按需加载')
  })
})

// ------------------------------------------------------------------ 顺手：记忆范围

describe('记忆范围（顺手抓到）', () => {
  it("'screen' 选了就是 'screen'，不再悄悄变回 'all'", () => {
    for (const k of Object.keys(SCOPE_LABEL)) {
      localStorage.setItem(MEMORY_SCOPE_KEY, k)
      expect(memoryScope()).toBe(k)
    }
    localStorage.setItem(MEMORY_SCOPE_KEY, 'bogus')
    expect(memoryScope()).toBe('all')
    localStorage.removeItem(MEMORY_SCOPE_KEY)
  })
})
