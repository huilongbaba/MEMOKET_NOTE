/** 把时间轴上**连着说同一件事**的段并成一块（只在显示层）。
 *
 * 第 750 轮把描述救活、751 轮把描述收短之后，读真实产出读出来的：用户连看了
 * 一个多小时 Firebase 崩溃数据，时间轴上摊成八行近似重复——
 *
 *     07:00–07:05  查看「查看Firebase用户行为数据」标签页中 PRD.md#70-81 …
 *     07:06–07:11  阅读 查看Firebase用户行为数据 页签中 PRD.md#70-81 …
 *     07:12–07:31  查看 PRD.md#70-81 的日本安卓手机崩溃信息 …
 *
 * 描述本身没错，**是时间轴的粒度不对**。
 *
 * **为什么并在这一层而不是采集层**：采集层并了就再也拆不开了，而这一页的
 * 全部意义是「我能核对、我能删」（daily-journey-plan §8.3）——每一段的截图
 * 凭据和删除入口都必须还在，所以块是可以展开的，底下还是原来那些行。
 */

/** 两句话像不像。二元组 Dice——**中文没有词边界**，按字切二元组对中文和
 *  夹在中间的英文标识符都成立，而且不用引任何依赖。 */
export function similar(a: string, b: string): number {
  const grams = (s: string) => {
    const t = s.toLowerCase().replace(/\s+/g, '')
    const out = new Set<string>()
    for (let i = 0; i + 1 < t.length; i++) out.add(t.slice(i, i + 2))
    return out
  }
  const A = grams(a), B = grams(b)
  if (!A.size || !B.size) return 0
  let hit = 0
  for (const g of A) if (B.has(g)) hit++
  return (2 * hit) / (A.size + B.size)
}

/** 并进同一块的门槛。**在真实产出上量出来的**（第 752 轮，今天 8 条描述）：
 *  真的是同一件事的相邻对是 .60 / .58 / .52 / .40 / .32，真换了事的是 .07 / .06。
 *  中间那道空档很宽，取 **.45**——按「误伤比漏报更贵」靠上取：
 *  宁可留下两行重复，也不要把两件不同的事并成一件（并错了用户根本看不出来）。 */
export const RUN_SIM = 0.45

/** 隔了这么久就不并了：中间那段空白本身是信息（吃饭、开会），
 *  并掉之后一块会横跨一个下午，而中间其实什么都没记。跟带上画空档同一个数。 */
export const RUN_GAP_MIN = 15

export type RunSeg = { start: string; end: string; app: string; desc: string }

export type Run<S extends RunSeg> = {
  segs: S[]
  start: string
  end: string
  app: string
  /** 这一块显示哪一句。**取最长的那条**：它们说的是同一件事，取信息最多的
   *  那一条（具体的文件名 / 报错往往只出现在其中一条里）。 */
  desc: string
}

export function groupRuns<S extends RunSeg>(segs: S[]): Run<S>[] {
  const runs: Run<S>[] = []
  for (const s of segs) {
    const cur = runs[runs.length - 1]
    const gapMin = cur ? (Date.parse(s.start) - Date.parse(cur.end)) / 60_000 : Infinity
    const lead = cur?.segs[0]
    // 跟**块首**比，不跟上一条比：一条一条往下传会飘——a 像 b、b 像 c，
    // 而 a 跟 c 已经是两件事了。
    const fits = !!cur && !!lead && cur.app === s.app && gapMin < RUN_GAP_MIN
      && (lead.desc.trim() || s.desc.trim()
          ? similar(lead.desc, s.desc) >= RUN_SIM
          : true)                       // 两条都还没描述 = 两行长得一模一样，并
    if (!fits) {
      runs.push({ segs: [s], start: s.start, end: s.end, app: s.app, desc: s.desc })
      continue
    }
    cur.segs.push(s)
    cur.end = s.end
    if (s.desc.trim().length > cur.desc.trim().length) cur.desc = s.desc
  }
  return runs
}
