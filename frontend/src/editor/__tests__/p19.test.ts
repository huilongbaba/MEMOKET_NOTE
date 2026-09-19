/** P19（`docs/TRACELOG-product.md` P19 节）：新装 app 第一天就能用。
 *
 *   #1 状态栏 / AI 按钮：没配过模型说「还没配模型」，别报一个用户没有的内网 IP；设置页有地址栏 + 「测一下」
 *   #3 悬停卡不许伸出正文栏（900px 那格）、挂在下面时把下一段推开
 *   #4 目录首句剥掉 markdown 语法（`[试菜单](note://9aab…)` → `试菜单`）
 *
 * 纯函数的那几条直接调；界面上的那几条钉源码（跟 p17 / p18 同一套做法）。
 */
import { describe, expect, it } from 'vitest'
import { healthMessage, llmGateMessage, NOT_CONFIGURED, NOT_CONFIGURED_HINT } from '../preconditions'
import { placeCard, seamPush } from '../../util/cardPlacement'
import { stripInline } from '../../components/DocumentOutline'
import settingsSrc from '../../components/SettingsPanel.tsx?raw'
import appSrc from '../../App.tsx?raw'

describe('P19 #1 没配过模型 ≠ 配了连不上', () => {
  it('出厂默认（configured=false）不报地址，只说「还没配模型」', () => {
    // P17 实拍 `p17-1-new-light`：第一天用户的状态栏是「⚠ LLM 不可达 (http://192.168.77.8:8080/v1)」
    const msg = healthMessage({ ok: false, configured: false, base_url: 'http://192.168.77.8:8080/v1' })
    expect(msg).toBe(NOT_CONFIGURED)
    expect(msg).not.toContain('192.168')
    expect(msg).not.toContain('http')
  })

  it('配过了连不上仍然报地址——那是用户改得动的东西', () => {
    const msg = healthMessage({ ok: false, configured: true, base_url: 'http://127.0.0.1:11434/v1' })
    expect(msg).toBe('LLM 不可达 (http://127.0.0.1:11434/v1)')
  })

  it('连得上就没有红字', () => {
    expect(healthMessage({ ok: true, configured: true, base_url: 'x' })).toBe('')
  })

  it('老后端不带 configured 字段时按老行为（报地址），不会误报「还没配」', () => {
    expect(healthMessage({ ok: false, base_url: 'http://x/v1' })).toBe('LLM 不可达 (http://x/v1)')
  })

  it('AI 按钮点下去那句话指向设置、说清要填什么', () => {
    const why = llmGateMessage(NOT_CONFIGURED)
    expect(why).toBe(NOT_CONFIGURED_HINT)
    expect(why).toContain('设置')
    expect(why).toContain('本地模型')
    expect(why).toContain('OpenAI 兼容')
    expect(why).not.toContain('192.168')
    // 配了连不上那档照旧带地址
    expect(llmGateMessage('LLM 不可达 (http://a/v1)')).toContain('http://a/v1')
    // 别的红字（后端不可达）不归它管
    expect(llmGateMessage('后端不可达')).toBe('')
  })

  it('App 的状态栏读的是 healthMessage，不是自己再拼一次地址', () => {
    expect(appSrc).toContain('setHealthMsg(healthMessage(')
    expect(appSrc).not.toContain("'LLM 不可达 (' + h.llm?.base_url")
  })
})

describe('P19 #1 设置页：本地模型有地址栏，每一栏有「测一下」', () => {
  it('本地模型那一档有地址 / 模型名 / key 三个输入框', () => {
    // P17 #1 实拍 `p17-7-new-light-settings`：这一档被选中却一个输入框都没有
    expect(settingsSrc).toContain("aria-label=\"本地模型地址\"")
    expect(settingsSrc).toContain("aria-label=\"本地模型名\"")
    expect(settingsSrc).toContain("aria-label=\"本地模型 API key\"")
  })

  it('placeholder 是本机默认，不是哪台内网机器', () => {
    // **注释里的地址不算**：这一页的块注释里贴着 P17 实拍那句原话（`LLM 不可达 (http://192.168.77.8…)`），
    // 那是在说明修的是什么，不是界面上的字。`check-css-classes.mts` 那条教训（闸门被散文绊倒）同款。
    const code = settingsSrc.replace(/\/\*[^]*?\*\//g, ' ').replace(/^\s*\/\/.*$/gm, ' ')
    expect(code).toContain('127.0.0.1:11434')
    expect(code).not.toContain('192.168.')
  })

  it('OpenAI 兼容那一档三栏齐全', () => {
    for (const label of ['GPT API key', 'GPT 模型名', 'GPT API base URL']) {
      expect(settingsSrc).toContain(`aria-label="${label}"`)
    }
  })

  it('写作 / 看图 / 语音三处各有一个「测一下」，都真发请求', () => {
    const testers = settingsSrc.match(/<TestButton/g) ?? []
    expect(testers.length).toBeGreaterThanOrEqual(4)     // 本地 + OpenAI + 语音 + 看图
    for (const kind of ["kind: 'llm'", "kind: 'asr'", "kind: 'vision'"]) {
      expect(settingsSrc).toContain(kind)
    }
    expect(settingsSrc).toContain('api.testProvider(')
  })

  it('没配过模型时设置页顶上有一条明说', () => {
    expect(settingsSrc).toContain('!cfg.configured')
    expect(settingsSrc).toContain('还没配模型')
  })

  it('看图默认跟着写作模型走，勾掉才单独配', () => {
    expect(settingsSrc).toContain('跟着上面的写作模型走')
    expect(settingsSrc).toContain("aria-label=\"看图模型地址\"")
    // 勾着的时候保存的是空串 = 让后端回退
    expect(settingsSrc).toContain("vision_base_url: visionOwn ? visionBaseUrl.trim() : ''")
  })
})

describe('P19 #3 悬停卡不许伸出正文栏，挂下面时把下一段推开', () => {
  const pane = { left: 300, top: 0, right: 1000, bottom: 900, width: 700, height: 900 }

  it('900px 那格：圆点靠左时卡也不许探出栏左边（P17 #7 实拍伸出 16px）', () => {
    // `p17-11c-new-light-900-althover`：⌥ 卡 340 宽从正文栏左边伸出去
    const narrow = { left: 300, top: 0, right: 640, bottom: 900, width: 340, height: 900 }
    const p = placeCard({ left: 306, top: 200, right: 315, bottom: 209, width: 9, height: 9 }, narrow, 160, 900)
    expect(p.left).toBeGreaterThanOrEqual(narrow.left + 8)
    expect(p.left + p.width).toBeLessThanOrEqual(narrow.right - 8)
  })

  it('P10 立的三条规矩一条没变', () => {
    const right = placeCard({ left: 500, top: 200, right: 509, bottom: 209, width: 9, height: 9 }, pane, 160, 900)
    expect(right.side).toBe('right'); expect(right.left).toBe(519); expect(right.width).toBe(340)
    const below = placeCard({ left: 980, top: 200, right: 989, bottom: 209, width: 9, height: 9 }, pane, 160, 900)
    expect(below.side).toBe('below')
    expect(below.left + below.width).toBeLessThanOrEqual(pane.right - 8)
    expect(below.left).toBeGreaterThanOrEqual(pane.left + 8)
    const above = placeCard({ left: 980, top: 850, right: 989, bottom: 859, width: 9, height: 9 }, pane, 160, 900)
    expect(above.side).toBe('above')
  })

  it('挂在下面才推开下一段；贴右边 / 挂上面不推', () => {
    expect(seamPush('below', 160)).toBeGreaterThan(160)   // 卡高 + 两条缝
    expect(seamPush('right', 160)).toBe(0)
    expect(seamPush('above', 160)).toBe(0)
  })
})

describe('P19 #4 目录首句剥掉 markdown 语法', () => {
  it('只有一个笔记链接的段落列出来是标题，不是 note:// 那串 id', () => {
    // P17 #11 实拍 `p17-12-new-dark-plan`：「计划」目录里列的是 `[试菜单](note://9aab…)`
    expect(stripInline('[试菜单](note://9aab12cd34ef)')).toBe('试菜单')
  })

  it('强调 / 行内代码 / 删除线 / 图片 / wiki 链接都剥', () => {
    expect(stripInline('**要点**：先说结论')).toBe('要点：先说结论')
    expect(stripInline('用 `npm test` 跑一遍')).toBe('用 npm test 跑一遍')
    expect(stripInline('~~不做了~~ 改成这样')).toBe('不做了 改成这样')
    expect(stripInline('![架构图](a.png) 说明')).toBe('图：架构图 说明')
    expect(stripInline('[[试菜单]]')).toBe('试菜单')
    expect(stripInline('[[9aab|试菜单]]')).toBe('试菜单')
  })

  it('正常文字一个字不动（剥的是语法壳，不是内容）', () => {
    const plain = '本周完成了 3 个功能的联调，测试覆盖率提升到 82%'
    expect(stripInline(plain)).toBe(plain)
    // 乘号 / 孤立星号不该被当成斜体
    expect(stripInline('3 * 4 = 12')).toBe('3 * 4 = 12')
  })
})
