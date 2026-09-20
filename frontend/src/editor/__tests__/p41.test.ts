/** P41（`docs/TRACELOG-product.md` P41 节）：P40 走查那几条的前端半边 + P39 的两条遗留。
 *
 * · **#1** 「来龙去脉」空手而归时，后端已经不说假话了（`tests/test_p41.py`）；
 *   前端补的是它答不了的那半句——**那几条在哪儿能看到**。
 * · **#3** 「校验结果」卡在右栏顶上不走。查清楚了**不是 P17 #5 的回归**：
 *   那条闸（换篇就清）今天还在、还绿；P40 拍到的是它从来没覆盖的另外两种——
 *   换**右栏页签**、把光标移到别的段。这块卡挂在 `RightPane` **外面**，页签体系根本管不着它。
 *   改法取的是 P40 给的第二条（「在卡上写清说的是哪一段」）：**不是「换段就清」**——
 *   用户看完校验下一步多半就是点进正文去改那一段，一动光标结果就没了，等于逼他先背下来。
 * · **#4** 900px 下那把尺子。查清楚了是**尺子变了，不是布局退了**：
 *   `.floating-buttons` 是 `height: 0`（按钮靠 `overflow: visible` 悬在外面），
 *   拿它的 `getBoundingClientRect().bottom` 当「按钮底」量到的是**它自己的顶边**——
 *   一个恒为「没压住」的判据。下面把这件事钉住，别再有人拿它当尺子。
 * · **#5** P39 的 ① `content_tag` 只认「变没变」、② 冲突只有一句 toast。
 * · **#6** 「全部接受」之后前端得**当场**去烧库里那几层（接线洞）。
 */
import { describe, expect, it } from 'vitest'

import appSrc from '../../App.tsx?raw'
// @ts-expect-error vitest 跑在 node 上；前端 tsconfig 没带 node 类型（styles.css 走 vite 的 css 管道，`?raw` 拿到空串，只能读文件）
import { readFileSync } from 'node:fs'
// @ts-expect-error 同上：node 的类型不在前端 tsconfig 里
import { fileURLToPath } from 'node:url'
import panelSrc from '../../components/ChangeLayersPanel.tsx?raw'
import { traceRecallHint } from '../../util/recallContext'
import { verifyScopeLine } from '../../components/VerifyPanel'
import { appendedTo, contentTag, restoreLayers, type SavedLayer } from '../../util/changeLayers'

const cssSrc: string = readFileSync(fileURLToPath(new URL('../../styles.css', import.meta.url)), 'utf8')

describe('P41 #1 「来龙去脉」空手而归时说清那几条在哪儿', () => {
  it('KITE 没串出来、而词法召回真的有数：说那几条在「记忆」里看得到', () => {
    const line = traceRecallHint(0, 6)
    expect(line).toContain('6 条')
    expect(line).toContain('记忆')
  })

  it('**判据窄**：串出东西了不说、召回是 0 不说、老后端没这一格也不说', () => {
    expect(traceRecallHint(3, 6)).toBe('')      // 下面就列着那几条，多这一句是废话
    expect(traceRecallHint(0, 0)).toBe('')      // 真的一条都没有——那句「知识库里没有」是对的
    expect(traceRecallHint(0, null)).toBe('')
    expect(traceRecallHint(0, undefined)).toBe('')
  })

  it('接线洞：App 真的把这一格传下去、也真的把它画出来', () => {
    expect(appSrc).toContain('recalled: r.recalled ?? null')
    expect(appSrc).toContain('traceRecallHint(trace.facts.length, trace.recalled)')
  })
})

describe('P41 #3 「校验结果」得说清自己在说哪一段', () => {
  it('卡上写出那一段的原话', () => {
    const line = verifyScopeLine('3月12号上线，众筹页面的文案定稿了。')
    expect(line).toContain('说的是你选中的这一段')
    expect(line).toContain('3月12号上线')
  })

  it('长段落只摘一小截，右栏塞不下一整段', () => {
    const line = verifyScopeLine('甲'.repeat(200))
    expect(line).toContain('…')
    expect(line.length).toBeLessThan(80)
  })

  it('这一段已经不在正文里了要说出来——**代码判得准的才说**', () => {
    expect(verifyScopeLine('一段话', true)).toContain('正文后来改过')
    expect(verifyScopeLine('一段话', false)).not.toContain('正文后来改过')
  })

  it('没有选区就一个字都不多说', () => {
    expect(verifyScopeLine('')).toBe('')
    expect(verifyScopeLine('   \n ')).toBe('')
  })

  it('接线洞：App 存下了当时的选区，并且「还在不在正文里」是按现在的正文判的', () => {
    expect(appSrc).toContain('setVerifyResult({ ...r, passage: selection })')
    expect(appSrc).toContain('gone={!!verifyResult.passage && !content.includes(verifyResult.passage)}')
  })

  it('P17 #5 那条闸没动：换篇照样清（这一批查清楚了它不是回归）', () => {
    expect(appSrc).toMatch(/useEffect\(\(\) => \{ setVerifyResult\(null\) \}, \[current\?\.id\]\)/)
  })
})

describe('P41 #4 「浮动按钮压没压住首行」那把尺子', () => {
  it('`.floating-buttons` 是 height:0 —— 拿它的 rect 当按钮底量的是它自己的顶边', () => {
    const block = cssSrc.slice(cssSrc.indexOf('.floating-buttons {'))
    expect(block.slice(0, 400)).toMatch(/height:\s*0/)
  })

  it('真正有高度的是 `.fb-btn`，量重叠只能量它', () => {
    const block = cssSrc.slice(cssSrc.indexOf('.fb-btn {'))
    expect(block.slice(0, 400)).toMatch(/height:\s*28px/)
  })

  it('这件事写在样式表里，下一个量它的人读得到', () => {
    expect(cssSrc).toContain('量重叠要量 `.fb-btn`')
  })
})

// ---------------------------------------------------------------- #5 P39 ①②

const HUNK = (over: Partial<SavedLayer['hunks'][number]> = {}) => ({
  k: 0, from: 0, to: 0, del: '', ins: '', state: 'pending' as const, before: '', after: '', ...over,
})

function layerOf(doc: string, over: Partial<SavedLayer> = {}): SavedLayer {
  return {
    id: 'L1', label: '智能续写', source: 'round', seq: 0, state: 'on',
    at: '2026-09-20T02:00:00.000Z', content_tag: contentTag(doc), hunks: [], ...over,
  }
}

describe('P41 #5 ① 末尾追加不该让整层作废', () => {
  it('存下来那一版是现在这一版的前缀 = 只在末尾添过东西', () => {
    const before = '第一段。\n\n第二段。'
    expect(appendedTo(contentTag(before), before + '\n\n第三段（智能续写写的）。')).toBe(true)
    expect(appendedTo(contentTag(before), before)).toBe(true)
  })

  it('**判据窄**：开头插、中间改、变短了都不算', () => {
    const before = '第一段。\n\n第二段。'
    expect(appendedTo(contentTag(before), '插在最前面。' + before)).toBe(false)
    expect(appendedTo(contentTag(before), '第一段！\n\n第二段。以及更多')).toBe(false)
    expect(appendedTo(contentTag(before), '第一')).toBe(false)
    expect(appendedTo('', '随便什么')).toBe(false)
    expect(appendedTo('乱七八糟', '随便什么')).toBe(false)
  })

  it('用户看得见的前后对比：追加的那一段里重了一句，原来那一处就整个丢了', () => {
    // 智能续写在末尾又写了一遍「甲说改好了。」——**前面那一处的坐标一个字都没漂**，
    // 可 `content_tag` 只认「变没变」，于是整层逐处按文字重新定位：
    // 「甲说 + 改好了 + 。」在正文里现在有两处，`relocate` 判「多处命中」= 冲突，
    // 缩短前后文（24 → 12 → 6 → 0）一级一级下去照样两处——**那一处不放回去，用户少一处**。
    const saved0 = '甲说改好了。'
    const idx = saved0.indexOf('改好了')
    const layer = layerOf(saved0, {
      hunks: [HUNK({ from: idx, to: idx + 3, del: '没改', ins: '改好了',
                     before: saved0.slice(0, idx), after: saved0.slice(idx + 3) })],
    })
    const doc = saved0 + '\n\n甲说改好了。'

    // 修之后：认出「只在末尾添过东西」，按坐标精确放回
    const now = restoreLayers([layer], doc)
    expect(now.conflicts).toEqual([])
    expect(now.hunks).toHaveLength(1)
    expect(now.hunks[0].from).toBe(idx)
    expect(now.stuck).toEqual([])

    // 修之前那条路（tag 不等就整层重新定位）长什么样：同一处**放不回去**
    const stale = restoreLayers([{ ...layer, content_tag: contentTag('另一份正文') }], doc)
    expect(stale.hunks).toEqual([])
    expect(stale.conflicts).toHaveLength(1)
  })

  it('真的被改过的正文照旧走重新定位——这一刀不许放宽到「变了也当没变」', () => {
    const saved0 = '甲说没改。'
    const layer = layerOf(saved0, {
      hunks: [HUNK({ from: 2, to: 4, del: '改过', ins: '没改', before: '甲说', after: '。' })],
    })
    const moved = '开头插了一句。甲说没改。'
    const r = restoreLayers([layer], moved)
    expect(r.hunks).toHaveLength(1)
    expect(r.hunks[0].from).toBe(moved.indexOf('没改'))   // 重新定位到了新位置，不是旧坐标 2
  })
})

describe('P41 #5 ② 放不回来的那几层要有出路', () => {
  it('对不上的那几处**按层分好**回给调用方', () => {
    const saved0 = '甲说没改。'
    const layer = layerOf(saved0, {
      hunks: [HUNK({ from: 0, to: 3, del: '没了', ins: '正文里根本没有这一串',
                     before: '找不到的前文', after: '找不到的后文' })],
    })
    const r = restoreLayers([layer], '完全不一样的一篇正文。')
    expect(r.conflicts).toHaveLength(1)
    expect(r.stuck).toHaveLength(1)
    expect(r.stuck[0].id).toBe('L1')
    expect(r.stuck[0].label).toBe('智能续写')
    expect(r.stuck[0].why).toHaveLength(1)
  })

  it('一处都没对不上的层不进这个名单', () => {
    const doc = '甲说没改。'
    const r = restoreLayers([layerOf(doc, { hunks: [HUNK({ from: 2, to: 4, del: '改过', ins: '没改' })] })], doc)
    expect(r.stuck).toEqual([])
  })

  it('面板上两个出路都在，而且写清了正文一个字没动', () => {
    expect(panelSrc).toContain('重新算这一层')
    expect(panelSrc).toContain('丢掉这一层')
    expect(panelSrc).toContain('正文一个字没动')
  })

  it('上面摆着放不回来的层时，下面不许再说「现在没有待处置的改动」', () => {
    // 真渲染出来当场看见的（`scripts/_p41render.tsx`）：同一块面板上一句说有、一句说没有，
    // 就是这一批在别处修的那种「两块面板打架」。
    expect(panelSrc).toContain("stuck.length ? '除了上面那几层，没有别的待处置改动。' : '现在没有待处置的改动。'")
  })

  it('接线洞：App 真的把名单和两个回调接给了面板', () => {
    expect(appSrc).toContain('stuck={layerStuck}')
    expect(appSrc).toContain('onRecomputeStuck={recomputeStuckLayer}')
    expect(appSrc).toContain('onDropStuck={dropStuckLayer}')
  })

  it('放不回来的那几层**跟着落库一起走**——不然下一次冲库就把它们悄悄抹了', () => {
    // **在 `flushChangeLayers` 那个函数体里找**：整份源码里找的话，
    // 打开那篇时算基线的那一行也带着同一串，把这一刀砍空（突变验 #15 当场抓到的）。
    const flush = appSrc.slice(appSrc.indexOf('const flushChangeLayers ='))
    expect(flush.slice(0, 1400)).toContain('...layerStuckRef.current.map((s) => s.saved)')
  })

  it('「改动」这个页签在只剩放不回来的层时也得出现，不然出路摆在一个看不见的页签里', () => {
    // P43 #1 起这一格收进了 `changesTabHasContent`。**守的性质一个字没变**：
    // `stuck` 那一格还在里面，只剩放不回来的层时页签照样出现。
    const at = appSrc.indexOf("{ id: 'changes', title: '改动'")
    expect(at).toBeGreaterThan(0)
    const block = appSrc.slice(at, at + 700)
    expect(block).toContain('hasContent: changesTabHasContent({')
    expect(block).toContain('stuck: layerStuck.length')
  })
})

describe('P41 #6 「全部接受」之后当场烧掉库里那几层', () => {
  it('接线洞：`acceptAllDiff` 真的调了那条 API，而且带 keepalive', () => {
    const fn = appSrc.slice(appSrc.indexOf('function acceptAllDiff()'))
    expect(fn.slice(0, 700)).toContain('api.burnChangeLayers(id, true)')
  })

  it('烧的时候把放不回来的那几层一起了结——「全部接受」说的是全部', () => {
    const fn = appSrc.slice(appSrc.indexOf('function acceptAllDiff()'))
    expect(fn.slice(0, 700)).toContain('setLayerStuck([])')
  })
})
