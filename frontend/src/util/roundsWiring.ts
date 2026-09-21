/** 轮次卡**在 `App.tsx` 里接成什么样**：一处一处解出来（P95 A）。
 *
 * ── 为什么要这份东西 ──────────────────────────────────────────────────────
 * P93 实拍到的洞是：A 篇跑完 2 轮，⌘K 新建一篇**空**笔记，右栏「计划」写着
 * `计划 2`、底下摆着 **A 篇那两轮的执行记录**。P93 自己写着
 * **「P93 A 那条通用闸抓不到它——那一格『有字』，只不过字是别人的」**。
 *
 * 「有没有字」是 P93 那条闸的判据，**「是不是这一篇的字」得另立一条**。
 * 而「是不是这一篇的」这件事，**在渲染那一侧证不完**：
 * 一份测试可以自己搭一个 `PaneTab`、自己喂一份 rounds，证明
 * 「喂 B 的就画 B 的」——但它证不了 **`App.tsx` 真的喂的是当前这篇的**。
 * 那一半只有**读 `App.tsx` 自己**才答得了，就是这份模块。
 *
 * ── 它判的那件事，一句话 ──────────────────────────────────────────────────
 * **屏幕上那份轮次卡是按 note id 取的，而每一次写入都点名了是写给哪一篇。**
 * 拆成五问（`wiringComplaints` 逐条回答，每条都**点名到那一行的原文**）：
 *
 *  ① `agentRounds` **不是**一个全 App 一份的 `useState`
 *     （`const [agentRounds, setAgentRounds] = useState…` ⇒ 当场红，那正是旧形状）；
 *  ② 它是 `roundsFor(<表>, <当前这篇>)` 取出来的，而「当前这篇」那个实参里**真的带着
 *     `current`**（`roundsFor(m, 'note-1')` 这种钉死的 ⇒ 红）；
 *  ③ 每一处写入（`writeRounds(` / `patchRound(`）的**第一个实参是个变量**，
 *     不是字面量、不是 `current?.id`——写入属于**发起这次跑的那一篇**，
 *     而不是「现在显示的那篇」（那两件事在切走之后正好不一样）；
 *  ④ 喂给 `planTabContent` 的 `rounds:` 和 `<AgentActivity rounds={…}>` 两处
 *     用的都是 ① 解出来的那个名字——两处只要有一处绕过去，右栏又会是两把尺；
 *  ⑤ 直接动那张表的地方**正好 1 处**（`writeRounds` 自己）——多一处就是有人
 *     绕过了那道口子，**洞会以另一个写法长回来**（P92/P93 合并那一课）。
 *
 * ── 它答不了什么（**别含糊过去**）────────────────────────────────────────
 *  · **`roundsFor` / `writeRoundsIn` 干得对不对**：一条都答不了。它是个正则解析器，
 *    读的是形状。那两条的语义由 `components/__tests__/p95.test.tsx` 里**真挂一次**去核。
 *  · **切走的那几秒事件丢不丢**：答不了，也不该它答（`App.tsx` 那个 `guarded` 包装
 *    在 HEAD 上就那么拦，P95 一个字没动）。
 *  · **`App.tsx` 之外**：答不了。右栏还有别的入口的话它看不见。
 *  · **名字**：它认 `roundsFor` / `writeRounds` / `patchRound` 这几个名字。改名 ⇒ 它红。
 *    **那是故意的**——改名的人正该来读一遍这份判据。
 */

/** 摘掉块注释和行注释。**判之前先摘**——`App.tsx` 里那几段注释里就写着
 *  `agentRounds` / `setAgentRounds` 这些词（P91 / P93 留下的那几大段就是）。
 *  `([^:])//` 那一支是为了别把 `http://` 当成注释开头（跟 `rightPaneTabs.ts` 同一条）。 */
export const stripComments = (s: string): string => s
  .replace(/\/\*[\s\S]*?\*\//g, ' ')
  .replace(/^[ \t]*\/\/.*$/gm, ' ')
  .replace(/([^:])\/\/.*$/gm, '$1')

export type RoundsWiring = {
  /** 屏幕上那份轮次卡叫什么名字（`const <这个名字> = roundsFor(…)`）。解不出来是 `null`。 */
  readName: string | null
  /** `roundsFor(` 的第二个实参逐字（「按哪一篇取」）。解不出来是 `null`。 */
  keyExpr: string | null
  /** 源码里还留着 `const [x, setX] = useState` 那种**全 App 一份**的轮次卡吗。 */
  globalState: string | null
  /** 每一处写入：函数名 + 第一个实参逐字。 */
  writes: { fn: string; firstArg: string }[]
  /** `planTabContent({ … rounds: <这里> … })` 每一处逐字。 */
  planRounds: string[]
  /** `<AgentActivity … rounds={<这里>}>` 逐字；解不出来是 `null`。 */
  activityRounds: string | null
  /** 直接动那张表的地方有几处（`setRoundsByNote(`）。**该正好 1 处**——
   *  就是 `writeRounds` 自己。多一处 = 有人绕过了「写入必须点名 note id」那道口子，
   *  **洞会以另一个写法长回来**（P92/P93 合并那一课）。 */
  rawSetters: number
}

/** `App.tsx` → 上面那张表。
 *
 *  **一处都解不出来就抛**（不是回一张空表）：空表和「解析器瞎了」在闸那一侧
 *  长得一模一样——**「选不到 ≠ 没有」**。 */
export function readRoundsWiring(appSrc: string): RoundsWiring {
  // **先把那两个函数自己的声明摘掉**：`function patchRound(noteId: string, …)`
  // 长得跟一次调用一模一样，不摘的话它会被当成「第一个实参是 `noteId: string`」
  // 的一处写入（第一版实测就是这样——**判据比产品宽的那一张脸**）。
  const s = stripComments(appSrc)
    .replace(/\bfunction\s+(writeRounds|patchRound)\s*\([^)]*\)/g, ' ')

  const read = /const\s+([A-Za-z_$][\w$]*)\s*=\s*roundsFor\(([^)]*)\)/.exec(s)
  const global = /const\s*\[\s*([A-Za-z_$][\w$]*)\s*,\s*set[A-Za-z_$][\w$]*\s*\]\s*=\s*useState<\s*AgentRound\[\]/.exec(s)
  const writes = [...s.matchAll(/\b(writeRounds|patchRound)\(\s*([^,]+?)\s*,/g)]
    .map((m) => ({ fn: m[1], firstArg: m[2].trim() }))
  const planRounds = [...s.matchAll(/planTabContent\(\{[\s\S]{0,400}?\brounds:\s*([^,}]+)/g)]
    .map((m) => m[1].trim())
  const activity = /<AgentActivity[\s\S]{0,400}?\brounds=\{([^}]+)\}/.exec(s)
  const rawSetters = (s.match(/\bsetRoundsByNote\(/g) ?? []).length

  if (!read && !global) {
    throw new Error('`App.tsx` 里既解不出 `const … = roundsFor(…)`，也解不出 `useState<AgentRound[]>`'
      + '——轮次卡整个换写法了。先去读 App.tsx，别改这份解析器')
  }
  if (planRounds.length === 0) {
    throw new Error('`App.tsx` 里解不出 `planTabContent({ … rounds: … })`——「计划」那一格换写法了')
  }
  return {
    readName: read?.[1] ?? null,
    keyExpr: read ? read[2].split(',').slice(1).join(',').trim() || null : null,
    globalState: global?.[1] ?? null,
    writes,
    planRounds,
    activityRounds: activity?.[1]?.trim() ?? null,
    rawSetters,
  }
}

/** 一个实参是「一个变量」而不是「钉死的一篇」吗。
 *
 *  **单拎出来是为了让它自己也有例 / 反例**（P85 第 ⑦ 刀那一课：
 *  内联在 `if` 里的判断，刀砍在它身上不红）。 */
export const isNoteIdVar = (arg: string): boolean =>
  /^[A-Za-z_$][\w$]*$/.test(arg) && !/^(current|note|notes)$/.test(arg)

/** 五问逐条回答。**回来的每一条都点名到那一行的原文**；空数组 = 五问都过。 */
export function wiringComplaints(w: RoundsWiring): string[] {
  const bad: string[] = []
  if (w.globalState) {
    bad.push(`轮次卡又变回全 App 一份了：\`const [${w.globalState}, set…] = useState<AgentRound[]>\``
      + '——换篇时它不会跟着换，右栏会摆上一篇的执行记录（P93 实拍「计划 2」）')
  }
  if (!w.readName) {
    bad.push('解不出 `const … = roundsFor(…)`：屏幕上那份轮次卡不是按 note id 取的')
  }
  if (!w.keyExpr || !/\bcurrent\b/.test(w.keyExpr)) {
    bad.push(`\`roundsFor(…)\` 的第二个实参是 \`${w.keyExpr ?? '(解不出)'}\`，里头没有 \`current\``
      + '——「按哪一篇取」得跟着现在开着的那篇走')
  }
  if (w.writes.length === 0) {
    bad.push('一处 `writeRounds(` / `patchRound(` 都解不出来——写入那一半换写法了')
  }
  for (const x of w.writes) {
    if (!isNoteIdVar(x.firstArg)) {
      bad.push(`\`${x.fn}(${x.firstArg}, …)\` 的第一个实参不是「发起这次跑的那一篇」的 id`
        + '——写入得点名写给哪一篇，不是「写给现在显示的那篇」')
    }
  }
  for (const r of w.planRounds) {
    if (w.readName && r !== `${w.readName}.length`) {
      bad.push(`\`planTabContent({ … rounds: ${r} … })\` 没用 \`${w.readName}.length\``
        + '——角标和正文又成了两把尺（P91 A 那一刀的形状）')
    }
  }
  if (w.rawSetters !== 1) {
    bad.push(`直接动那张表的地方有 ${w.rawSetters} 处（\`setRoundsByNote(\`），该正好 1 处`
      + '——多出来的那处绕过了「写入必须点名写给哪一篇」，一处就够把洞长回来')
  }
  if (w.readName && w.activityRounds !== w.readName) {
    bad.push(`\`<AgentActivity rounds={${w.activityRounds ?? '(解不出)'}}>\` 摆的不是 \`${w.readName}\``
      + '——右栏底下那叠卡绕过了「按 note id 取」那一步')
  }
  return bad
}
