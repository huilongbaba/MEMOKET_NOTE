/** 状态栏面包屑：当前笔记 / 虚拟页在树上的父链。从 App.tsx 挪出来（第 471 轮），纯函数好测。 */
import type { TreeRow } from '../api'
import { VIRTUAL_LABELS, factsLabel, virtualParentOf } from './virtual'

const syntheticRow = (x: string, title: string): TreeRow =>
  ({ id: x, note_id: x, parent_note_id: '', title, position: 0, is_expanded: false, preview: '', cite_count: 0, ingested_at: '',
     pinned: false, updated_at: '', child_count: 0, branch_count: 0, fact_count: 0 } as TreeRow)

/**
 * @param id 当前笔记 id 或虚拟页 id（null = 什么都没开）
 * @param rows 树上所有行（真笔记 + 知识库虚拟子树里已经下发的）
 * @param tabTitle 标签页上这个 id 叫什么（懒加载的虚拟页树上没有行，名字只有标签知道）
 * @param isVirtual 这个 id 是不是虚拟页
 */
export function buildCrumbs(id: string | null | undefined, rows: TreeRow[], tabTitle: (id: string) => string | undefined,
                            isVirtual: (id: string) => boolean): TreeRow[] {
  if (!id) return []
  const byNote = new Map<string, TreeRow>()
  for (const r of rows) if (!byNote.has(r.note_id)) byNote.set(r.note_id, r)
  const out: TreeRow[] = []
  let cur = byNote.get(id); let guard = 0
  while (cur && guard++ < 50) { out.unshift(cur); cur = byNote.get(cur.parent_note_id) }
  // 从树上尾巴行「还有 N 条 · 去事实表看」进来的事实表：面包屑末尾用页面的名字（跟标签一样「事实表 · work」），不是那句入口的话
  if (out.length && out[out.length - 1].note_id.startsWith('kb:facts')) {
    const last = out[out.length - 1]
    out[out.length - 1] = { ...last, title: factsLabel(last.note_id) ?? '事实表' }
  }
  // 懒加载的那几层（实体 / 某个主题下的事实…）不在 rows 里，之前状态栏就退回「23 篇笔记」
  // （第 207 轮实拍实体页）——按 id 的形状把父链拼出来，名字用标签页上的
  if (out.length === 0 && isVirtual(id)) {
    const parent = virtualParentOf(id)
    // app:* 那些页（最近删除 / 写作 Skill / 设置…）不在知识库下面，别给它们冠「知识库 /」
    // 知识库根本身（id === 'kb'）在 kbRows 到之前也走这条：别拼成「知识库知识库」（第 269 轮实拍）
    const chain = id.startsWith('app:') ? [id] : Array.from(new Set(['kb', ...(parent ? [parent] : []), id]))
    const leaf = tabTitle(id) ?? VIRTUAL_LABELS[id] ?? id.split(':').pop() ?? id
    return chain.map((x) => byNote.get(x) ?? syntheticRow(x, x === id ? leaf : (VIRTUAL_LABELS[x] ?? x)))
  }
  return out
}
