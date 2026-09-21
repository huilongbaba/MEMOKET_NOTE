/** 右栏「计划」页签这一次**会不会画出东西**，以及角标该写几（P91 A）。
 *
 * ── 这条函数是为了补一个实拍到的洞 ────────────────────────────────────────
 * P89 用跨批逐行 diff 照出来一处**产品的旧洞**（不是回退，源码跟 P87 逐字节相同）：
 * 在**虚拟页**（屏幕活动 / 知识库 / 设置…）上点开「计划」页签，右栏是**一片纯空白**
 * ——而 `RightPane` 自己的类型注释上逐字写着
 *
 *     /** hasContent 为 false 时内容区说一句为什么是空的，别留白。 *\/
 *
 * 洞的形状是**那条路够不着**：`RightPane` 只在 `hasContent === false` 时才说那句话，
 * 而「计划」是 `alwaysShown: true` 且**从不设 `hasContent`**。P91 开工量了一遍，
 * 右栏 6 个页签里**没有任何一个**同时满足 `alwaysShown === true && hasContent === false`
 * ——**`emptyHint` 今天一条都走不到**（`revisions` 上那句「这篇还没有待处置的修订。」
 * 是写了却够不着的：它没有 `alwaysShown`，`hasContent` 为 false 时整个页签先被滤掉了）。
 *
 * ── 为什么角标也得从这儿出（P43 #1 的同一条理由）────────────────────────
 * 「改动」那一格早就判过一次同样的事：**页签出不出现，跟面板这一次会画出什么，
 * 算同一份判据**（`changesTabHasContent`）。「计划」这一格今天是**两把尺**：
 *
 *   · 角标： `agentRounds.length || (current ? beats.length : 0)`
 *   · 正文： 四块里每一块都要 `current`，只有执行记录那一块放宽成
 *            `(current || loading === 'note-harness' || harness?.running)`
 *
 * 于是虚拟页上角标拿**上一篇留下的 `agentRounds`** 数出一个「计划 2」，
 * 而正文那四块一块都画不出来。P89 的实拍截图 `p89-b4-old-wipe-light.png` 就是这一格：
 * 页签上高亮写着「计划 2」，底下**一个字都没有**。
 * **一个说有两件事的角标，配一片什么都不说的空白**——用户没法判断是没内容、
 * 是坏了、还是自己少做了什么。（`badge` 那一行原来的注释自己也写着
 * 「角标别拿旧骨架充数」，只是当时只把 `beats` 关掉了，`agentRounds` 留着。）
 *
 * ⇒ 这一条函数把三样并成一份判据：**画不画得出东西、角标写几、空了说哪句话**。
 *
 * ── 判据宁可窄 ────────────────────────────────────────────────────────────
 * `shows` 里的两项**逐字照抄**正文那两个条件，不多判也不少判：
 *   · `hasNote`  = `current` 不是 null（虚拟页上是 null）
 *   · `running`  = `loading === 'note-harness' || !!harness?.running`
 *     （**不含 `pausedRun`**：正文那一行的执行记录块也不看它，
 *       跟着 `busy` 走的只是四块的**排序**，不是画不画）
 *
 * **不动别的页签。** 同一趟量下来「记忆」和「幻灯片」这两个 `alwaysShown` 的页签
 * 各自在 `body` 里自己兜了底（「打开一篇笔记后，这里会跟着你写的内容浮现相关记忆。」/
 * 「这篇还不是幻灯片。…」），**它们本来就在说话，不该动**；
 * 「改动」/「修订」/「脉络」没有 `alwaysShown`，空的时候整个页签不出现
 * ——那是 P12 定的「右栏页签只能减不能加」，**空得对，也不该让它们说话**。
 */
export type PlanTabIn = {
  /** 现在开着一篇真笔记吗（虚拟页上是 false）。 */
  hasNote: boolean
  /** 这一刻有没有 harness 在跑（`loading === 'note-harness' || harness?.running`）。 */
  running: boolean
  /** 这一次跑的轮次卡有几张（`agentRounds.length`）。 */
  rounds: number
  /** 这一篇的骨架有几拍（`beats.length`）。 */
  beats: number
}

export type PlanTabOut = {
  /** 这一次正文那四块里**至少有一块画得出来**吗。false ⇒ `RightPane` 摆 `emptyHint`。 */
  has: boolean
  /** 页签角标写几。**0 表示不摆角标**（`App.tsx` 那一行把 0 转成 `undefined`）。 */
  badge: number
}

/** 「计划」页签那一格空了时说的那句话。
 *
 * 跟「记忆」那一格的兜底句**同一个句式**（「打开一篇笔记后，这里会…」），
 * 因为用户在虚拟页上左右切页签时，看到的就该是同一种解释，而不是两种腔调。 */
export const PLAN_EMPTY_HINT = '打开一篇笔记后，这里会摆出它的完成标准、目录、写作骨架和每一轮执行。'

export function planTabContent(x: PlanTabIn): PlanTabOut {
  // 执行记录那一块的条件，逐字照抄 `App.tsx` 里那一行。
  const activity = x.hasNote || x.running
  // 完成标准 / 目录 / 骨架三块都要 `current`；`目录` 那一块哪怕正文是空的也会画出
  // 一行 `<h2>目录</h2>`，所以「开着一篇笔记」本身就足以让这一格有东西。
  const has = x.hasNote || activity
  // 角标跟着**这一次真画得出来的那几块**走：执行记录画不出来时，上一篇留下的
  // `rounds` 一个都不算；骨架那几拍照旧只在开着笔记时算（原来那一行就是这么写的）。
  const badge = (activity ? x.rounds : 0) || (x.hasNote ? x.beats : 0)
  return { has, badge }
}
