/** 每篇笔记看到哪儿了（光标 + 滚动）。跨重启保留——痛点 12 的动线不止「这一会儿去查个东西」，
 *  更常见的是「昨天写到一半，今天打开接着写」，落在文首同样要自己找回来（第 591 轮）。
 *
 *  只留最近 MAX 篇：这是便利不是数据，不值得为它无限增长；Map 的插入序天然是 LRU。 */
export type Spot = { head: number; top: number }

const MAX = 60
const key = (user: string) => 'memoket-note-spots:' + user

export function loadSpots(user: string): Map<string, Spot> {
  try {
    const raw = localStorage.getItem(key(user))
    const obj = raw ? (JSON.parse(raw) as Record<string, Spot>) : {}
    return new Map(Object.entries(obj).filter(([, v]) => v && typeof v.head === 'number'))
  } catch { return new Map() }
}

export function saveSpots(user: string, spots: Map<string, Spot>) {
  // 超了从最早的开始丢（Map 的插入序 = 最近一次 set 的顺序，rememberSpot 里先 delete 再 set）
  while (spots.size > MAX) spots.delete(spots.keys().next().value as string)
  try { localStorage.setItem(key(user), JSON.stringify(Object.fromEntries(spots))) } catch { /* 隐私模式写不了，不值得报错 */ }
}

/** 记一篇的位置：先删再插，让它排到 Map 末尾（LRU）。 */
export function putSpot(spots: Map<string, Spot>, id: string, spot: Spot) {
  spots.delete(id)
  spots.set(id, spot)
}
