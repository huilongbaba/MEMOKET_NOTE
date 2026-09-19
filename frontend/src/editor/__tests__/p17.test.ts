/**
 * P17 走查（打包版从头用一遍）当批修的几条——每条对着实拍的现象钉一个闸：
 *   #2 `/` 输入框：点外面 / Esc 都关；再选一项要重挂（不然字打进正文）
 *   #3 右键「自定义提示」→「全部撤回」把原来选中的字弄丢（diff 基准补回选区）+ 行内替换不补空行
 *   #4 浮动按钮盖住紧跟其后的改动条 / 出处条
 *   #5 「校验结果」跟着到下一篇
 *   #8 知识库空着时图例要说不画点
 *   #9 右栏页签重开退回默认
 *   #13 固定端口被占先试相邻的，别直接随机（localStorage 每次清零）
 */
import { describe, expect, it } from 'vitest'
import { diffBaseForBlock, textToLand } from '../blockLanding'
import { KB_EMPTY_DOTS_NOTE } from '../marginMemory'
import appSrc from '../../App.tsx?raw'
import promptSrc from '../../components/SlashPrompt.tsx?raw'
import paneSrc from '../../components/RightPane.tsx?raw'
import memSrc from '../../components/RelatedMemory.tsx?raw'
// @ts-expect-error vitest 跑在 node 上；前端 tsconfig 没带 node 类型（styles.css 走 vite 的 css 管道，`?raw` 拿到空串，只能读文件）
import { readFileSync } from 'node:fs'
// @ts-expect-error 同上：node 的类型不在前端 tsconfig 里
import { fileURLToPath } from 'node:url'
import backendSrc from '../../../../desktop/src/backend.ts?raw'

describe('P17 #3 自定义提示的 diff 基准（blockLanding）', () => {
  const doc = '本季度营收 1200 万，其中 700 万、软件 500 万。'   // 开跑时「硬件」已经被清掉
  const at = '本季度营收 1200 万，其中'.length
  it('custom：把清掉的选区补回原位，「全部撤回」才回得到「其中硬件 700 万」', () => {
    expect(diffBaseForBlock(doc, at, 'custom', '硬件')).toBe('本季度营收 1200 万，其中硬件 700 万、软件 500 万。')
  })
  it('插入类（prompt / chart / table…）基准就是当前正文，一个字不动', () => {
    for (const k of ['prompt', 'chart', 'table', 'tray', 'analysis']) expect(diffBaseForBlock(doc, at, k, '硬件')).toBe(doc)
  })
  it('custom 但选区是空串：不补', () => { expect(diffBaseForBlock(doc, at, 'custom', '')).toBe(doc) })
  it('at 越界钳到 [0, len]', () => {
    expect(diffBaseForBlock('abc', 99, 'custom', 'X')).toBe('abcX')
    expect(diffBaseForBlock('abc', -5, 'custom', 'X')).toBe('Xabc')
  })
  it('落地的字：插入类补一个空行隔开下文，custom 原样落回句子里（不把句子截成两行）', () => {
    expect(textToLand('prompt', '一段')).toBe('一段\n\n')
    expect(textToLand('custom', '一段')).toBe('一段')
  })
  it('App.tsx 的 runBlock 用的就是这两个函数（不是自己再算一遍）', () => {
    expect(appSrc).toMatch(/const b2 = diffBaseForBlock\(v\.state\.doc\.toString\(\), at, item\.key, selection\)/)
    expect(appSrc).toMatch(/insert: textToLand\(item\.key, text\)/)
    expect(appSrc).not.toMatch(/insert: text \+ '\\n\\n' \}, effects: endRun/)
  })
})

describe('P17 #2 `/` 输入框的关法', () => {
  it('SlashPrompt 监听 document 的 capture mousedown（点外面关）和 Escape（在正文里按也关），跑起来时不关', () => {
    expect(promptSrc).toMatch(/document\.addEventListener\('mousedown', onDocMouseDown, true\)/)
    expect(promptSrc).toMatch(/document\.addEventListener\('keydown', onDocKeyDown\)/)
    expect(promptSrc).toMatch(/if \(busy\) return/)
    expect(promptSrc).toMatch(/if \(e\.button === 2\) return/)
    expect(promptSrc).toMatch(/box\.current && !box\.current\.contains\(e\.target as Node\)\) onCancel\(\)/)
  })
  it('App.tsx 给 <SlashPrompt> 按「哪项 + 在哪」加了 key：再选一项是重挂，输入框重新拿焦点', () => {
    expect(appSrc).toMatch(/<SlashPrompt\s+key=\{`\$\{slash\.item\.key\}:\$\{slash\.from\}:\$\{slash\.to\}`\}/)
  })
})

// styles.css 走 vite 的 css 管道，`?raw` 在 vitest 里拿到空串——直接读文件
const css = readFileSync(fileURLToPath(new URL('../../styles.css', import.meta.url)), 'utf8')

describe('P17 #4 浮动按钮 vs 紧跟其后的条', () => {
  it('非编辑器的第一个兄弟让到 --s-8（34px ≥ 按钮 28px）；编辑器照旧 --s-7', () => {
    expect(css).toMatch(/\.note-body > \.floating-buttons \+ :not\(\.md-editor\) \{ margin-top: var\(--s-8\); \}/)
    expect(css).toMatch(/\.note-body > \.floating-buttons \+ \* \{ margin-top: var\(--s-7\); \}/)
  })
})

describe('P17 #5 校验结果 / 改动层消息不跟篇', () => {
  it('换篇（current.id 变）就清 verifyFindings', () => {
    expect(appSrc).toMatch(/useEffect\(\(\) => \{ setVerifyFindings\(null\) \}, \[current\?\.id\]\)/)
  })
  it('换篇也清 roundDiff：那是发给编辑器的一次性「加层」消息，编辑器重挂时不能再按旧坐标加一遍', () => {
    expect(appSrc).toMatch(/useEffect\(\(\) => \{ setRoundDiff\(null\) \}, \[current\?\.id\]\)/)
  })
})

describe('P17 #8 空库图例', () => {
  it('图例在 kbEmpty 时多一句「不画圆点」，且那句话说了什么时候开始判', () => {
    expect(KB_EMPTY_DOTS_NOTE).toMatch(/不画圆点/)
    expect(KB_EMPTY_DOTS_NOTE).toMatch(/第一条记录/)
    expect(memSrc).toMatch(/\{kbEmpty && <><br \/>\{KB_EMPTY_DOTS_NOTE\}<\/>\}/)
  })
})

describe('P17 #9 右栏页签记住', () => {
  it('RightPane 用 localStorage（memoket.rightTab）记上次的页签，读写都 try/catch', () => {
    expect(paneSrc).toMatch(/RIGHT_TAB_KEY = 'memoket\.rightTab'/)
    expect(paneSrc).toMatch(/localStorage\.getItem\(RIGHT_TAB_KEY\)/)
    expect(paneSrc).toMatch(/localStorage\.setItem\(RIGHT_TAB_KEY, id\)/)
    // 记的那个页签这次没内容：退回第一个，不能空白
    expect(paneSrc).toMatch(/shown\.find\(\(t\) => t\.id === active\) \?\? shown\[0\]/)
  })
})

describe('P17 #13 固定端口被占', () => {
  it('backend.ts 先试 preferred+1…+8，再退随机', () => {
    expect(backendSrc).toMatch(/for \(let k = 1; k <= 8; k\+\+\)/)
    expect(backendSrc).toMatch(/listenFree\(preferred \+ k\)/)
    expect(backendSrc.indexOf('listenFree(preferred + k)')).toBeLessThan(backendSrc.indexOf('listenFree(0)'))
  })
})
