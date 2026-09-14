/**
 * 树上撞名的那几行，各自该补一个什么后缀才分得开。
 *
 * 第 609 轮截图实拍：侧栏里四行都写着「创业一年回顾」——那是几篇没起标题的
 * 笔记按正文首行取的名（`displayTitle`），彼此长得一模一样。要分清是哪一篇
 * 只能一行行悬停去读 tooltip 里的日期。
 *
 * 两条分寸：
 *
 * · **只给真正撞名的那几行加后缀。** 树上大多数行不重名，统一挂个日期只会
 *   把标题挤窄、把眼睛的落点从名字上带走。撞了才标，没撞的一个字都不多。
 * · **挑刚好够分开的那个粒度。** 第一版只给日期，结果两篇同一天写的还是
 *   一模一样的「创业一年回顾 · 09-07」——等于没分。所以日期分不开就上到
 *   分钟；到分钟还分不开（真同时）就不标了，标了也没用。
 */
const dayOf = (iso: string) => iso.slice(5, 10)                  // MM-DD
const minuteOf = (iso: string) => iso.slice(5, 16).replace('T', ' ')

type Row = { key: string; title: string; at: string }

export function dupSuffixes(rows: Row[]): Map<string, string> {
  const byTitle = new Map<string, Row[]>()
  for (const r of rows) {
    const t = r.title.trim()
    if (!t) continue          // 一列「未命名」不该全挂上日期
    const list = byTitle.get(t)
    if (list) list.push(r)
    else byTitle.set(t, [r])
  }

  const out = new Map<string, string>()
  for (const list of byTitle.values()) {
    if (list.length < 2) continue
    const dated = list.filter((r) => r.at)
    if (dated.length < 2) continue
    const days = new Set(dated.map((r) => dayOf(r.at)))
    const label = days.size === dated.length ? dayOf : minuteOf
    const labels = dated.map((r) => label(r.at))
    if (new Set(labels).size < 2) continue     // 到分钟还分不开：标了也没用
    dated.forEach((r, i) => out.set(r.key, labels[i]))
  }
  return out
}
