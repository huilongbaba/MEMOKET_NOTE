/** 右栏那一排页签**在源码里长什么样**：一格一格解出来（P93 A）。
 *
 * ── 为什么要这份东西 ──────────────────────────────────────────────────────
 * P91 A 把「计划」那一格的纯空白补上了，但它自己在收尾里留了一条：
 *
 *   > `memory` / `slides` 靠 `body` 自己兜底，不走 `hasContent`，
 *   > 所以「**`alwaysShown` 的页签都不许留白**」这件事**今天没有一条通用的闸**，
 *   > 有的只是 `plan` 这一格的三条断言。
 *
 * 「窄」在 P91 那一批是对的（先修实拍到的那一格），但代价是：**再加一个
 * `alwaysShown` 的页签、而它的 `body` 在某一档画不出东西，今天没有任何东西会红。**
 * 这份模块是那条通用闸的**源码侧那一半**：把 `App.tsx` 里 `<RightPane tabs={[…]}>`
 * 那一整块解成一张表，让闸能问出「**今天有几格 `alwaysShown`、它们各自靠什么说话**」。
 *
 * ── 判据宁可窄：它判的是「有没有字」，不是「走不走 `emptyHint`」──────────
 * 右栏今天有**两条**不留白的路，两条都算说话：
 *
 *   · **`RightPane` 那条**：`alwaysShown && hasContent === false` ⇒ 摆 `emptyHint`
 *     （`plan` 走这条，P91 A 接上的）。
 *   · **`body` 自己兜**：`body` 那个三元的 falsy 分支自己摆一句
 *     （`memory`），或者 `body` 里那个组件自己兜底（`slides` → `SlidesPanel`）。
 *
 * 逼所有格都走第一条 = 把 P91 判过「不该动」的两格改掉，而且 `memory` 那句话
 * 是**跟着 `current` 走**的、不是「这一项没内容」，语义本来就不一样。
 * 所以这份表**只报事实**，「够不够格算说话」由闸那一侧按格判。
 *
 * ── 它答不了什么 ──────────────────────────────────────────────────────────
 * * **`body` 到底画不画得出东西**：一条都答不了。它是个**正则解析器**，
 *   读的是源码的形状，不是渲染结果。「这一格空的时候屏幕上有没有字」只有
 *   **真挂一次**才答得了——那是 `components/__tests__/p93.test.tsx` 干的活。
 * * **那句话写得好不好**：答不了。
 * * **`tabs={[…]}` 之外的页签**：答不了，它只解这一块。
 */

export type TabFacts = {
  id: string
  title: string
  /** 源码里写着 `alwaysShown: true` 吗。 */
  alwaysShown: boolean
  /** 这一格设了 `hasContent:` 这个字段吗（**不是它的值**——那是运行时才知道的）。 */
  setsHasContent: boolean
  /** 这一格挂了 `emptyHint:` 吗。 */
  setsEmptyHint: boolean
  /** 这一格挂了 `badge:` 吗。 */
  setsBadge: boolean
  /** `body:` 那个三元的 falsy 分支里那句**写死的话**；没有这条路就是 `null`。
   *
   *  只认「`: <小写标签 …>纯文字</小写标签>`」这一种形状——小写标签 = 真 DOM 元素，
   *  纯文字 = 中间不许有 `{}` / 嵌套标签。`: null` / `: <Foo/>` 一律回 `null`：
   *  **前者是真的什么都不画，后者画什么得去挂那个组件才知道**（那是闸那一侧的事）。 */
  bodyFallbackText: string | null
}

/** 摘掉块注释和行注释。**判之前先摘**——`App.tsx` 那几格的注释里就写着
 *  `alwaysShown` / `emptyHint` 这些词（P91 A 那一大段就是）。
 *  `([^:])//` 那一支是为了别把 `http://` 当成注释开头（跟
 *  `check-components-gate.mts` 的 `strip` 同一条）。 */
export const stripComments = (s: string): string => s
  .replace(/\/\*[\s\S]*?\*\//g, ' ')
  .replace(/^[ \t]*\/\/.*$/gm, ' ')
  .replace(/([^:])\/\/.*$/gm, '$1')

/** `App.tsx` 里 `<RightPane … tabs={[ … ] as PaneTab[]}>` 那一整块的原文。
 *  找不到就**抛**——静默回空字符串的话，底下那张表会是空的，而「一格都没有」
 *  跟「解析器瞎了」在闸那一侧长得一模一样（**「选不到 ≠ 没有」**）。 */
export function rightPaneTabsBlock(appSrc: string): string {
  const at = appSrc.indexOf('<RightPane')
  if (at < 0) throw new Error('App.tsx 里找不到 `<RightPane`——右栏整个挪走了？先去读 App.tsx，别改这份解析器')
  const from = appSrc.indexOf('tabs={[', at)
  if (from < 0) throw new Error('`<RightPane` 找到了，但后面没有 `tabs={[`——页签数组换写法了')
  const to = appSrc.indexOf('] as PaneTab[]}', from)
  if (to < 0 || to <= from) throw new Error('`tabs={[` 找到了，但没有收口的 `] as PaneTab[]}`')
  return appSrc.slice(from, to)
}

/** 那一整块 → 一格一条事实。**顺序照源码**。 */
export function parseRightPaneTabs(appSrc: string): TabFacts[] {
  const block = stripComments(rightPaneTabsBlock(appSrc))
  const heads = [...block.matchAll(/\{\s*id:\s*'([a-zA-Z][\w-]*)',\s*title:\s*'([^']+)'/g)]
  if (heads.length === 0) throw new Error('页签数组里一格都没解出来——`{ id: \'x\', title: \'y\'` 这个形状变了')
  return heads.map((h, i) => {
    const seg = block.slice(h.index!, i + 1 < heads.length ? heads[i + 1].index! : block.length)
    const bodyAt = seg.indexOf('body:')
    const body = bodyAt < 0 ? '' : seg.slice(bodyAt)
    const fall = /:\s*<([a-z][a-z0-9]*)\b[^>]*>([^<>{}]+)<\/\1>/.exec(body)
    const text = (fall?.[2] ?? '').trim()
    return {
      id: h[1],
      title: h[2],
      alwaysShown: /\balwaysShown:\s*true\b/.test(seg),
      setsHasContent: /\bhasContent:/.test(seg),
      setsEmptyHint: /\bemptyHint:/.test(seg),
      setsBadge: /\bbadge:/.test(seg),
      bodyFallbackText: text ? text : null,
    }
  })
}
