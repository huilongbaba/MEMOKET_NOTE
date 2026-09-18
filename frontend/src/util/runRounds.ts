/**
 * 改动的分层历史（P16，agent-native-editor §3.2 / 痛点 8「改了三轮，想留第一轮、丢第三轮」）。
 *
 * 烧进正文之后层就没了——但后端每轮开始前存了一版（`note_revisions.reason='round'`，带 `run_id` / `round_no`），
 * 收尾时再存一版（`run_end`）。这里把历史列表（新的在前，跟 `/revisions` 一样）按跑组回轮次：
 * 第 N 轮的「之前」= 它自己那一行，「之后」= 同一次跑里紧跟着它的下一行（第 N+1 轮的 round 行，或 run_end）。
 * 纯函数，UI 在 `ChangeLayersPanel` / `RevisionHistoryPanel`。
 */
import type { NoteRevision } from '../api'

export type RunRound = { round_no: number; before: NoteRevision; after: NoteRevision | null }
export type RunHistory = {
  run_id: string
  /** 第一轮开始的时间 */
  at: string
  rounds: RunRound[]
  /** 收尾那一行到了没有（跑完 / 暂停）：没到的跑最后一轮只有「之前」，撤不了那一轮 */
  finished: boolean
}

/** 按跑分组、新的跑在前；同一次跑里轮次正序。没有轮次行（只有 harness 交稿行）的跑不算。 */
export function groupRuns(revs: NoteRevision[]): RunHistory[] {
  const byRun = new Map<string, NoteRevision[]>()
  // 列表是新的在前；同一次跑里要按时间正序，倒着走一遍（同秒的靠列表里 rowid 的序已经排好）
  for (let i = revs.length - 1; i >= 0; i--) {
    const r = revs[i]
    if (!r.run_id) continue
    const list = byRun.get(r.run_id) ?? []
    list.push(r)
    byRun.set(r.run_id, list)
  }
  const out: RunHistory[] = []
  for (const [run_id, list] of byRun) {
    const rounds: RunRound[] = []
    list.forEach((r, i) => {
      if (r.reason !== 'round') return
      rounds.push({ round_no: r.round_no, before: r, after: list[i + 1] ?? null })
    })
    if (!rounds.length) continue
    out.push({ run_id, at: rounds[0].before.created_at, rounds,
               finished: list.some((r) => r.reason === 'run_end' || r.reason === 'harness') })
  }
  out.sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0))
  return out
}

export type HistoryItem =
  | { kind: 'rev'; rev: NoteRevision }
  | { kind: 'run'; run_id: string; revs: NoteRevision[] }

/** 历史面板用：同一次跑的行折成一组（放在它最新那一行的位置），其余行照旧；顺序仍是新的在前。 */
export function historyGroups(revs: NoteRevision[]): HistoryItem[] {
  const out: HistoryItem[] = []
  const seen = new Set<string>()
  for (const r of revs) {
    if (!r.run_id) { out.push({ kind: 'rev', rev: r }); continue }
    if (seen.has(r.run_id)) continue
    seen.add(r.run_id)
    out.push({ kind: 'run', run_id: r.run_id, revs: revs.filter((x) => x.run_id === r.run_id) })
  }
  return out
}

/** 一行历史的「为什么留这一版」，给人看的。 */
export function revisionLabel(r: Pick<NoteRevision, 'reason' | 'round_no'>): string {
  switch (r.reason) {
    case 'auto': return '自动'
    case 'manual': return '手动'
    case 'before_restore': return '恢复前'
    case 'harness': return 'AI 交稿'
    case 'round': return `第 ${r.round_no} 轮之前`
    case 'run_end': return `跑完（第 ${r.round_no} 轮之后）`
    default: return r.reason
  }
}

/** 一次跑的标题：几轮、最后一轮写到多少字。 */
export function runTitle(run: RunHistory): string {
  const n = run.rounds.length
  const end = run.rounds[n - 1].after?.chars
  const delta = end != null ? end - run.rounds[0].before.chars : null
  const tail = delta == null ? '' : ` · ${delta >= 0 ? '+' : ''}${delta} 字`
  return `智能续写 · ${n} 轮${tail}${run.finished ? '' : ' · 还没收尾'}`
}
