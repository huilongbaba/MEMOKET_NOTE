// @vitest-environment jsdom
/**
 * P93 A（第 816 轮）：**「不许留白」立一条通用闸**——收 P91 留的第 ② 条。
 *
 * ── P91 自己留下的那句话 ──────────────────────────────────────────────────
 *   > `memory` / `slides` 靠 `body` 自己兜底，不走 `hasContent`，
 *   > 所以「**`alwaysShown` 的页签都不许留白**」这件事**今天没有一条通用的闸**，
 *   > 有的只是 `plan` 这一格的三条断言（判据宁可窄的代价，照实记）。
 *
 * P91 窄在一格是对的（它在修一处**实拍到的**空白）。代价在这儿：
 * **再加一个 `alwaysShown` 的页签、而它的 `body` 在某一档画不出东西，
 * 今天没有任何东西会红**——`plan` 那三条断言里写死着 `plan`。
 *
 * ── 开工先量：右栏 6 格「空的时候屏幕上是什么」（**不是只读源码**）────────
 * 源码侧（`parseRightPaneTabs`，这一批新写的解析器）解出来是这样：
 *
 *     id          alwaysShown  hasContent  emptyHint  badge  body 的 falsy 分支
 *     memory      ✔            —           —          —      「打开一篇笔记后，这里会跟着你写的内容浮现相关记忆。」
 *     slides      ✔            —           —          ✔      —（是 `<SlidesPanel/>`，得挂起来才知道）
 *     changes     —            ✔           —          ✔      —
 *     plan        ✔            ✔           ✔          ✔      —（走 `RightPane` 那条 `emptyHint`）
 *     revisions   —            ✔           ✔          ✔      —
 *     trace       —            ✔           —          ✔      —（干脆是 `null`）
 *
 * 渲染侧（这份文件底下那几条，**真 `createRoot`**）逐格挂了一遍，屏幕上是：
 *
 *   · `memory`    × 没开笔记 → 「打开一篇笔记后，这里会跟着你写的内容浮现相关记忆。」
 *   · `slides`    × 只有 front-matter（`isSlides` 真、`slidePages` 0 页）
 *                  → 「这篇还不是幻灯片。在「⋯ → 做成幻灯片」里生成一份。」（`SlidesPanel` 自己兜的）
 *   · `plan`      × 虚拟页 → `PLAN_EMPTY_HINT`（P91 A 接上的那条 `emptyHint`）
 *   · `changes` / `revisions` / `trace` × 空 → **整个页签不在条上**（P12：右栏页签只能减不能加）
 *
 * ── 判据宁可窄：判的是「**有字**」，不是「必须走 `emptyHint`」──────────────
 * 右栏今天有**两条**不留白的路，**两条都算说话**：
 *   ① `RightPane` 那条（`alwaysShown && hasContent === false` ⇒ 摆 `emptyHint`）；
 *   ② `body` 自己兜（falsy 分支摆一句 / `body` 里的组件自己兜）。
 * 逼所有格都走 ① = 把 P91 判过「不该动」的两格改掉，而且 `memory` 那句话是
 * **跟着「有没有开笔记」走**的，语义跟「这一项没内容」本来就不一样。
 * ⇒ **闸只问一件事：这一格空的时候，`.right-pane-body` 里有没有字。**
 *
 * ── 这份文件核什么 ────────────────────────────────────────────────────────
 *  ① **名单**：`App.tsx` 里 `alwaysShown` 的那几格，跟底下 `EMPTY_STATES` 的键
 *     **多集相等**。加一个 `alwaysShown` 的页签而不在这儿登记 ⇒ 当场红、**点名到那一格**。
 *     这一条才是「通用」的那一半：P91 那三条断言里写死着 `plan`，新加一格不会惊动它。
 *  ② **逐格真挂一次**：每一格按它**真会空的那一档**搭出 `PaneTab`（用的是真模块：
 *     `planTabContent` / `PLAN_EMPTY_HINT` / 真 `<SlidesPanel/>` / 从 `App.tsx` 解出来的
 *     那句 falsy 分支），挂进**真 `RightPane`**，`.right-pane-body` 里必须有字。
 *  ③ **两头对齐**：每一格登记的「靠哪条路说话」得跟源码解出来的字段对得上
 *     （登记走 `emptyHint` 而源码里没挂 `emptyHint` ⇒ 红）。
 *  ④ **反面**：没有 `alwaysShown` 的三格，空了**整个页签不出现**——真渲染核一次，
 *     那是 P12 定的「空得对」，不是留白。
 *  ⑤ **解析器自己的例 / 反例**：`stripComments` / `parseRightPaneTabs` 各一组。
 *     （P85 第 ⑦ 刀那一课：闸自己那一半没人看着，刀砍在它身上不红。）
 *
 * ── 它答不了什么 ──────────────────────────────────────────────────────────
 *  - **那句话写得好不好 / 说得对不对**：一条都答不了。只管「有没有字」。
 *  - **`body` 在**别的**档会不会空**：答不了。每一格只挂了**它真会空的那一档**
 *    （`EMPTY_STATES[*].when` 逐条写着是哪一档）。比如 `memory` 在「开着一篇空笔记」
 *    那一档靠的是 `TrayPanel` / `RelatedMemory` 各自的表头，**那两个组件要网络**，
 *    这份 jsdom 的闸挂不动——那一档在**真壳上**量（P93 B，`steps/panes93.mjs`）。
 *  - **`tabs={[…]}` 之外**：右栏还有别的入口的话，这条闸看不见。
 *  - **那一格的 `hasContent` 喂对了没有**：答不了。第 ② 条挂的是**这份文件自己搭的**
 *    `PaneTab`（用真模块搭，但毕竟不是 `App.tsx` 那一行）。「`App.tsx` 真的把
 *    `planTabContent` 接在 `badge` / `hasContent` 两处」是 **P91 A ③** 那四条在盯，
 *    两份文件分工，别在这儿再抄一遍（抄一份就是两把尺）。
 *
 * ── 砍刀实拍：**它红的时候点名到哪一格**（P93 A，四真一对照）────────────
 *   · `SlidesPanel` 那句兜底 → `return null`  ⇒ ② 红，逐字写着**「幻灯片」这一格是一片留白**
 *   · `memory` 的 falsy 分支 → `: null`       ⇒ ②③④ 四条红，写着**「记忆」这一格是一片留白**
 *   · `revisions` 加上 `alwaysShown: true`    ⇒ ① 红，**点名 `revisions`**（「没在 EMPTY_STATES 里登记」）
 *   · `plan` 的 `emptyHint:` 整行摘掉         ⇒ **③ 红、② 不红**，而 ② **不红是对的**：
 *     `RightPane` 还会摆那句通用的「这篇还没有这一项的内容。」——**那也算说话了**。
 *     这一刀正好照出这条闸的射程：它判「有没有字」，不判「那句话是不是那一句」。
 *   · 对照刀（只加一行注释）⇒ 17 条全绿。
 *   （另有一刀不算数并重切：`if (!pages.length)` → `if (false)` 之后 `SlidesPanel`
 *    落进主分支、画出「0 页　·　点一页跳到正文」——**那不是留白**，
 *    **反例没真的落在被测分支里**，重切成 `return null` 才算。）
 */
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import appSrc from '../../App.tsx?raw'
import RightPane, { RIGHT_TAB_KEY, type PaneTab } from '../RightPane'
import SlidesPanel from '../SlidesPanel'
import { PLAN_EMPTY_HINT, planTabContent } from '../../util/planTab'
import { isSlides, slidePages } from '../../util/slidePages'
import { parseRightPaneTabs, stripComments, type TabFacts } from '../../util/rightPaneTabs'

const FACTS: TabFacts[] = parseRightPaneTabs(appSrc)
const facts = (id: string): TabFacts => {
  const f = FACTS.find((x) => x.id === id)
  if (!f) throw new Error(`\`App.tsx\` 的右栏里解不出「${id}」这一格——先去读 App.tsx，别改这份闸`)
  return f
}

/** 只有 front-matter 的幻灯片：`isSlides` 为真（所以这一格**真的会进数组**），
 *  而 `slidePages` 一页都切不出来 ⇒ `SlidesPanel` 走它自己那条兜底。
 *  **反例得真的落在被测分支里**，所以下面有两条断言先钉住这件事。 */
const SLIDES_EMPTY = '---\nslides: true\n---\n'

/** 这一格「空」是哪一档、靠什么说话、空的时候那个 `PaneTab` 长什么样。
 *
 *  **键必须跟 `App.tsx` 里 `alwaysShown` 的那几格多集相等**（第 ① 条核这件事）。 */
type Speaks = 'emptyHint' | 'body-fallback' | 'body-component'
const EMPTY_STATES: Record<string, { when: string; speaks: Speaks; tab: (f: TabFacts) => PaneTab }> = {
  memory: {
    when: '没开着笔记（虚拟页 / 刚进来）⇒ `body` 那个三元走 falsy 分支',
    speaks: 'body-fallback',
    // 那句话**从 `App.tsx` 解出来**，不在这儿抄第二份：抄一份就是两把尺，
    // 而两把尺迟早飘开（P43 #1 那一课）。falsy 分支被删 / 换成 `null` ⇒
    // `bodyFallbackText` 变 `null` ⇒ 下面那条当场红。
    tab: (f) => ({ id: 'memory', title: f.title, alwaysShown: true,
                   body: <p className="muted">{f.bodyFallbackText}</p> }),
  },
  slides: {
    when: '只有 front-matter：`isSlides` 真（这一格进得了数组）而 0 页 ⇒ `SlidesPanel` 自己兜底',
    speaks: 'body-component',
    // **真组件**，不是复述它那句话：`SlidesPanel` 里那条 `if (!pages.length)` 被删掉
    // ⇒ 这一格挂出来是空的 ⇒ 当场红。这是三格里最实的一条。
    tab: (f) => ({ id: 'slides', title: f.title, alwaysShown: true,
                   badge: slidePages(SLIDES_EMPTY).length || undefined,
                   body: <SlidesPanel content={SLIDES_EMPTY} viewRef={{ current: null }} /> }),
  },
  plan: {
    when: '虚拟页、没 harness 在跑 ⇒ `planTabContent().has` 为 false ⇒ `RightPane` 摆 `emptyHint`',
    speaks: 'emptyHint',
    // 三样都从真模块出（P91 A 那一刀的形状）：`hasContent` / `badge` / `emptyHint`。
    // `body` 摆的是**旧洞的形状**（四个 falsy ⇒ 一个节点都不画），
    // 所以这一条真的在核「`emptyHint` 顶上来了」，而不是「`body` 碰巧有字」。
    tab: (f) => {
      const p = planTabContent({ hasNote: false, running: false, rounds: 2, beats: 5 })
      return { id: 'plan', title: f.title, alwaysShown: true, hasContent: p.has,
               badge: p.badge || undefined, emptyHint: PLAN_EMPTY_HINT,
               body: <div className="stack">{[false, false, false, false]}</div> }
    },
  },
}

/** 真挂一次，回 `.right-pane-body`（**不是整页**：条上的页签名也是字）。 */
async function mount(tabs: PaneTab[], active?: string) {
  if (active) localStorage.setItem(RIGHT_TAB_KEY, active)
  const el = document.createElement('div')
  document.body.append(el)
  const root = createRoot(el)
  await act(async () => { root.render(<RightPane tabs={tabs} defaultTab={tabs[0]?.id ?? ''} />) })
  const body = el.querySelector('.right-pane-body')
  if (!body) throw new Error('右栏内容区整个没渲染出来——先看 RightPane 是不是抛了，而不是改判据')
  return { el, body: body as HTMLElement }
}

/** 条上现在摆着哪几个页签（逐字，连角标）。 */
const tabNames = (el: HTMLElement) => [...el.querySelectorAll('.pane-tab')].map((b) => b.textContent ?? '')

/** 「屏幕上有字」怎么算。**判据宁可窄**：不看它说了什么，只看
 *  ① 去掉空白之后还剩东西；② 剩的不是一两个标点（`·` / `…` 糊弄不过去）。 */
const CJK = /[一-鿿]/
const MIN_WORDS = 8
const speaksUp = (s: string) => {
  const t = (s ?? '').replace(/\s+/g, '').trim()
  return t.length >= MIN_WORDS && CJK.test(t)
}

beforeEach(() => { localStorage.clear() })
afterEach(() => { document.body.innerHTML = ''; localStorage.clear() })

describe('P93 A ①：名单——`alwaysShown` 的页签今天是哪几格（**通用的那一半**）', () => {
  it('右栏那一块解得出来，6 格逐字按源码顺序', () => {
    expect(FACTS.map((f) => f.id)).toEqual(['memory', 'slides', 'changes', 'plan', 'revisions', 'trace'])
    expect(FACTS.map((f) => f.title)).toEqual(['记忆', '幻灯片', '改动', '计划', '修订', '脉络'])
  })

  it('`alwaysShown` 的那几格，跟这份文件登记的**多集相等**（多一个 / 少一个都点名到那一格）', () => {
    const inSrc = FACTS.filter((f) => f.alwaysShown).map((f) => f.id).sort()
    const registered = Object.keys(EMPTY_STATES).sort()
    const missing = inSrc.filter((id) => !registered.includes(id))
    const extra = registered.filter((id) => !inSrc.includes(id))
    expect(missing, `这几格在 \`App.tsx\` 里写着 \`alwaysShown: true\`，`
      + `却没在 \`EMPTY_STATES\` 里登记「空的时候屏幕上是什么」：${missing.join(' / ')}。`
      + '**`alwaysShown` 的页签空了也留在条上**，点得进来——它必须有话说。'
      + '登记一条（那一档是什么、靠哪条路说话、空的时候那个 `PaneTab` 长什么样），'
      + '底下第 ② 条会真挂一次核它').toEqual([])
    expect(extra, `这几格在 \`EMPTY_STATES\` 里登记着，\`App.tsx\` 里却没有 \`alwaysShown\`：`
      + `${extra.join(' / ')}。要么那一格的 \`alwaysShown\` 被摘了（那它空了就整个不出现，`
      + '是另一件事，登记该删），要么这份闸在核一格已经不存在的东西').toEqual([])
    expect(inSrc).toEqual(['memory', 'plan', 'slides'])
  })
})

describe('P93 A ②：每一格空的时候，屏幕上真的有字（真 `createRoot` 挂 `RightPane`）', () => {
  for (const [id, spec] of Object.entries(EMPTY_STATES)) {
    it(`\`${id}\` × ${spec.when} → 有字`, async () => {
      const { el, body } = await mount([spec.tab(facts(id))], id)
      const shown = body.textContent ?? ''
      expect(tabNames(el).length, `\`${id}\` 这一格 \`alwaysShown\`，空了也该留在条上`).toBe(1)
      expect(speaksUp(shown),
        `**右栏「${facts(id).title}」这一格空的时候是一片留白**（${spec.when}）。`
        + `\`.right-pane-body\` 里读回来的是 ${JSON.stringify(shown.slice(0, 40))}。`
        + '`alwaysShown` 的页签空了也留在条上、点得进来，底下一个字都没有的话，'
        + '用户没法判断是没内容、是坏了、还是自己少做了什么（P89 实拍过一次，'
        + '`RightPane` 自己的注释上就写着「别留白」）。'
        + `这一格靠的是「${spec.speaks}」那条路，去看它是不是被摘了`).toBe(true)
    })
  }

  it('`memory` 说的就是 `App.tsx` 里那句（**一个字都没在这儿抄第二份**）', async () => {
    const { body } = await mount([EMPTY_STATES.memory.tab(facts('memory'))], 'memory')
    expect(facts('memory').bodyFallbackText).toBeTruthy()
    expect(body.textContent).toBe(facts('memory').bodyFallbackText)
  })

  it('`slides` 那个夹具**真的落在被测分支里**（`isSlides` 真、0 页），说话的是真 `SlidesPanel`', async () => {
    expect(isSlides(SLIDES_EMPTY), '夹具得让这一格真的进得了数组，否则核的是一格根本不存在的东西').toBe(true)
    expect(slidePages(SLIDES_EMPTY)).toHaveLength(0)
    const { el, body } = await mount([EMPTY_STATES.slides.tab(facts('slides'))], 'slides')
    expect(body.textContent).toContain('这篇还不是幻灯片')
    // 0 页时**不摆角标**：一个写着数的角标配一句「还不是幻灯片」又是两把尺（P91 A 那一课）
    expect(tabNames(el)).toEqual(['幻灯片'])
  })

  it('`plan` 摆出来的是 `PLAN_EMPTY_HINT`，而那份 `body` 一个节点都没画', async () => {
    const { el, body } = await mount([EMPTY_STATES.plan.tab(facts('plan'))], 'plan')
    expect(body.textContent).toBe(PLAN_EMPTY_HINT)
    expect(body.querySelector('.stack'), '`hasContent` 为 false 时 `body` 得整个不渲染').toBe(null)
    // 角标不再顶着上一篇的数（P91 A 那一刀）：rounds=2 喂进去，条上仍然只有「计划」
    expect(tabNames(el)).toEqual(['计划'])
  })
})

describe('P93 A ③：两头对齐——登记的那条路，跟源码里的字段对得上', () => {
  for (const [id, spec] of Object.entries(EMPTY_STATES)) {
    it(`\`${id}\` 登记的是「${spec.speaks}」`, () => {
      const f = facts(id)
      if (spec.speaks === 'emptyHint') {
        expect(f.setsHasContent, `\`${id}\` 登记走 \`RightPane\` 那条 \`emptyHint\`，`
          + '就必须设 `hasContent`——不设的话那条路**够不着**（P91 A 量过：够得着它的'
          + '只有 `alwaysShown === true && hasContent === false` 这一种组合）').toBe(true)
        expect(f.setsEmptyHint, `\`${id}\` 设了 \`hasContent\` 却没挂 \`emptyHint\`，`
          + '那摆出来的是 `RightPane` 那句通用的兜底话').toBe(true)
      }
      if (spec.speaks === 'body-fallback') {
        expect(f.bodyFallbackText, `\`${id}\` 登记靠 \`body\` 那个三元的 falsy 分支说话，`
          + '源码里却解不出那句话了（被删了？换成 `: null` 了？换成一个组件了？）。'
          + '换成组件的话登记该改成 `body-component` 并把那个组件真挂起来').toBeTruthy()
      }
      if (spec.speaks === 'body-component') {
        expect(f.setsHasContent, `\`${id}\` 登记靠 \`body\` 里那个组件自己兜底，`
          + '却又设了 `hasContent`——那 `RightPane` 会在它为 false 时**把 `body` 整个换掉**，'
          + '登记该改成 `emptyHint`').toBe(false)
      }
    })
  }
})

describe('P93 A ④：反面——没有 `alwaysShown` 的三格，空了整个页签不出现（P12，**空得对**）', () => {
  const others = () => FACTS.filter((f) => !f.alwaysShown)

  it('那三格逐字是 `changes` / `revisions` / `trace`，而且各自都设了 `hasContent`', () => {
    expect(others().map((f) => f.id)).toEqual(['changes', 'revisions', 'trace'])
    for (const f of others()) {
      expect(f.setsHasContent, `\`${f.id}\` 既没有 \`alwaysShown\` 也不设 \`hasContent\`——`
        + '那它**永远留在条上**，而空的时候 `body` 画什么没人管：'
        + '这正是「留白」的第三种形状').toBe(true)
    }
  })

  it('真渲染：`hasContent:false` 且没有 `alwaysShown` ⇒ 条上没有它，`emptyHint` 也轮不到', async () => {
    const { el, body } = await mount([
      EMPTY_STATES.memory.tab(facts('memory')),
      { id: 'revisions', title: '修订', hasContent: false, emptyHint: '这篇还没有待处置的修订。',
        body: <div>修订正文</div> },
    ], 'memory')
    expect(tabNames(el)).toEqual(['记忆'])
    expect(body.textContent).toBe(facts('memory').bodyFallbackText)
    // P91 留的第 ① 条：`revisions` 上那句话**今天仍然够不着**（这一批照旧判「不动」）
    expect(el.textContent).not.toContain('这篇还没有待处置的修订。')
  })
})

describe('P93 A ⑤：解析器自己的例 / 反例（闸那一半也得有人看着）', () => {
  const wrap = (inner: string) => `<RightPane\n  tabs={[\n${inner}\n  ] as PaneTab[]}\n/>`

  it('`stripComments`：注释里的 `alwaysShown` 不算', () => {
    expect(stripComments("const a = 'x' // alwaysShown: true")).not.toContain('alwaysShown')
    expect(stripComments('/* alwaysShown: true */ const a = 1')).not.toContain('alwaysShown')
    // `http://` 里那两根斜杠不是注释
    expect(stripComments("const u = 'http://a/b' // 说明")).toContain('http://a/b')
    expect(stripComments("{ id: 'x', title: 'X', alwaysShown: true }")).toContain('alwaysShown: true')
  })

  it('`parseRightPaneTabs`：四种形状各解一次', () => {
    const rows = parseRightPaneTabs(wrap([
      "    { id: 'a', title: '甲', alwaysShown: true, body: x ? <div>正文</div> : <p className=\"muted\">甲空了说这句</p> },",
      "    // { id: 'zz', title: '注释里的', alwaysShown: true, body: null },",
      "    { id: 'b', title: '乙', alwaysShown: true, badge: n || undefined, body: <Panel content={c} /> },",
      "    { id: 'c', title: '丙', hasContent: n > 0, emptyHint: '丙空了说这句', body: <div>丙</div> },",
      "    { id: 'd', title: '丁', hasContent: !!t, body: t ? <div>丁</div> : null },",
    ].join('\n')))
    expect(rows.map((r) => r.id)).toEqual(['a', 'b', 'c', 'd'])       // 注释里那格不算
    expect(rows[0].alwaysShown).toBe(true)
    expect(rows[0].bodyFallbackText).toBe('甲空了说这句')
    expect(rows[1].alwaysShown).toBe(true)
    expect(rows[1].bodyFallbackText, '`: <Panel/>` 不是写死的话——挂起来才知道画什么').toBe(null)
    expect(rows[1].setsBadge).toBe(true)
    expect(rows[2].alwaysShown).toBe(false)
    expect(rows[2].setsHasContent).toBe(true)
    expect(rows[2].setsEmptyHint).toBe(true)
    expect(rows[3].bodyFallbackText, '`: null` 就是真的什么都不画').toBe(null)
  })

  it('解不出来就**抛**，不许静默回空（「选不到 ≠ 没有」）', () => {
    expect(() => parseRightPaneTabs('const x = 1')).toThrow(/找不到 `<RightPane`/)
    expect(() => parseRightPaneTabs('<RightPane defaultTab="memory" />')).toThrow(/没有 `tabs=\{\[`/)
    expect(() => parseRightPaneTabs('<RightPane tabs={[')).toThrow(/收口/)
    expect(() => parseRightPaneTabs(wrap('    // 一格都没有'))).toThrow(/一格都没解出来/)
  })

  it('`speaksUp` 自己的例 / 反例：空白和一两个标点不算「有字」', () => {
    expect(speaksUp('')).toBe(false)
    expect(speaksUp('   \n  ')).toBe(false)
    expect(speaksUp('·')).toBe(false)
    expect(speaksUp('…………………………')).toBe(false)          // 够长但一个汉字都没有
    expect(speaksUp('这里空着')).toBe(false)                   // 4 字，不够 MIN_WORDS
    expect(speaksUp('打开一篇笔记后，这里会摆出它的完成标准。')).toBe(true)
    expect(speaksUp(PLAN_EMPTY_HINT)).toBe(true)
  })
})
