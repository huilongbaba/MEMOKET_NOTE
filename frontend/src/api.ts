/** 后端 API 封装。用户身份走 X-User-Id 头，原型阶段不做认证。 */

export type Note = {
  id: string
  user_id: string
  title: string
  content: string
  pinned: boolean
  folder_id: string | null
  created_at: string
  updated_at: string
}

export type Folder = {
  id: string
  user_id: string
  name: string
  created_at: string
}

export type Fact = {
  id: string
  text: string
  when: string
  kind: string
  sources: string[]
}

export type Revision = {
  id: string
  op: 'insert' | 'delete' | 'replace' | 'insert_before'
  anchor: string
  text: string
  reason: string
  sources: string[]
}

const USER_KEY = 'memoket-note-user'

export function getUser(): string {
  let u = localStorage.getItem(USER_KEY)
  if (!u) {
    u = 'user-' + Math.random().toString(36).slice(2, 8)
    localStorage.setItem(USER_KEY, u)
  }
  return u
}

export function setUser(u: string) {
  localStorage.setItem(USER_KEY, u.trim() || 'default')
}

function headers(extra: Record<string, string> = {}) {
  return { 'X-User-Id': getUser(), ...extra }
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

// ---------------------------------------------------------------- 笔记

export const listNotes = (q = '') =>
  fetch(`/api/notes${q ? `?q=${encodeURIComponent(q)}` : ''}`, { headers: headers() }).then(json<Note[]>)

export const getNote = (id: string) =>
  fetch(`/api/notes/${id}`, { headers: headers() }).then(json<Note>)

export const createNote = (title: string, content: string, folder_id: string | null = null) =>
  fetch('/api/notes', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ title, content, folder_id }),
  }).then(json<Note>)

export const saveNote = (id: string, title: string, content: string) =>
  fetch(`/api/notes/${id}`, {
    method: 'PUT',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ title, content }),
  }).then(json<Note>)

export const deleteNote = (id: string) =>
  fetch(`/api/notes/${id}`, { method: 'DELETE', headers: headers() }).then(json)

export const togglePin = (id: string) =>
  fetch(`/api/notes/${id}/pin`, { method: 'POST', headers: headers() }).then(json<Note>)

export const moveNoteToFolder = (id: string, folder_id: string | null) =>
  fetch(`/api/notes/${id}/folder`, {
    method: 'PUT',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ folder_id }),
  }).then(json<Note>)

// ---------------------------------------------------------------- 文件夹

export const listFolders = () =>
  fetch('/api/folders', { headers: headers() }).then(json<Folder[]>)

export const createFolder = (name: string) =>
  fetch('/api/folders', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ name }),
  }).then(json<Folder>)

export const renameFolder = (id: string, name: string) =>
  fetch(`/api/folders/${id}`, {
    method: 'PUT',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ name }),
  }).then(json<Folder>)

export const deleteFolder = (id: string) =>
  fetch(`/api/folders/${id}`, { method: 'DELETE', headers: headers() }).then(json)

// ---------------------------------------------------------------- 个人偏好
//
// 独立于知识库：不走 LLM 抽取，用户直接维护，写作三件套生成时会读取。

export type ProfileEntry = { id: string; user_id: string; text: string; created_at: string }

export const listProfile = () =>
  fetch('/api/profile', { headers: headers() }).then(json<ProfileEntry[]>)

export const addProfileEntry = (text: string) =>
  fetch('/api/profile', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ text }),
  }).then(json<ProfileEntry>)

export const deleteProfileEntry = (id: string) =>
  fetch(`/api/profile/${id}`, { method: 'DELETE', headers: headers() }).then(json)

// ---------------------------------------------------------------- 写作

export const genSkeleton = (title: string, content: string) =>
  fetch('/api/skeleton', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ title, content }),
  }).then(json<{ spine: string; beats: string[]; took_ms: number }>)

export const genRevisions = (content: string, spine: string, beats: string[]) =>
  fetch('/api/edit', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ content, spine, beats }),
  }).then(json<{ revisions: Revision[]; took_ms: number }>)

// ---------------------------------------------------------------- 选中文本操作
//
// 右键选中一段文本触发。都产出跟 genRevisions 同一个 Revision 形状的结果，
// 复用同一套接受/拒绝 UI。

export const rewriteSelection = (
  content: string, selection: string, intent: 'rewrite' | 'polish', spine: string, beats: string[],
) =>
  fetch('/api/rewrite', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ content, selection, intent, spine, beats }),
  }).then(json<{ revisions: Revision[]; took_ms: number }>)

export const expandSelection = (content: string, selection: string) =>
  fetch('/api/expand', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ content, selection }),
  }).then(json<{ revisions: Revision[]; took_ms: number }>)

export type VerifyFinding = {
  verdict: '矛盾' | '支持' | '无法判断'
  reason: string
  fact_id: string
  fact_text: string
  sources: string[]
}

export const verifySelection = (content: string, selection: string) =>
  fetch('/api/verify', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ content, selection }),
  }).then(json<{ findings: VerifyFinding[]; took_ms: number }>)

export type TapMeta = {
  facts: number; recall_ms: number; grounded: boolean
  sources: string[]; fact_ids: string[]
}

/** magic tap：SSE 流式续写。onMeta 先到（检索结果），onDelta 逐块到达。 */
export async function magicTap(
  content: string,
  spine: string,
  beats: string[],
  onMeta: (m: TapMeta) => void,
  onDelta: (s: string) => void,
  signal?: AbortSignal,
) {
  const res = await fetch('/api/magic-tap', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ content, spine, beats }),
    signal,
  })
  if (!res.ok || !res.body) throw new Error(`magic-tap failed: ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let event = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    // SSE 以空行分帧，最后一段可能不完整，留在 buffer 里
    const frames = buf.split('\n\n')
    buf = frames.pop() ?? ''
    for (const frame of frames) {
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) {
          const raw = line.slice(5).trim()
          if (!raw) continue
          const payload = JSON.parse(raw)
          if (event === 'meta') onMeta(payload as TapMeta)
          else if (event === 'delta') onDelta(payload.text as string)
          else if (event === 'error') throw new Error(payload.detail)
        }
      }
    }
  }
}

// ---------------------------------------------------------------- 无限续写计划
//
// 文件夹级别的写作 harness，不是笔记级别的"点一下续写"——一个持久化的
// plan（目标 + 有序 section 列表），每个 section 落成一篇笔记，写完当前
// 所有 section 后会自动问一次"还有没有更多"，由此决定真正的停止时机，
// 不是轮数封顶。断线（点停止）只是暂停，plan 留在 active，下次 run() 从
// 断点接着写。

export type WritingSection = {
  id: string; plan_id: string; idx: number; title: string
  status: 'pending' | 'in_progress' | 'done'
  note_id: string; summary: string; created_at: string
}

export type WritingPlan = {
  id: string; user_id: string; folder_id: string; goal: string
  status: 'active' | 'done' | 'abandoned'
  doc_note_id: string; created_at: string; updated_at: string
}

export type WritingPlanOut = { plan: WritingPlan | null; sections: WritingSection[] }

export const getWritingPlan = (folderId: string) =>
  fetch(`/api/writing-plan?folder_id=${encodeURIComponent(folderId)}`, { headers: headers() })
    .then(json<WritingPlanOut>)

export const startWritingPlan = (folderId: string, goal: string) =>
  fetch('/api/writing-plan/start', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ folder_id: folderId, goal }),
  }).then(json<WritingPlanOut>)

export const abandonWritingPlan = (folderId: string) =>
  fetch(`/api/writing-plan/${folderId}/abandon`, { method: 'POST', headers: headers() }).then(json)

export type WritingPlanHandlers = {
  onPlanLoaded?: (plan: WritingPlan, sections: WritingSection[]) => void
  onSectionStart?: (d: { section_id: string; title: string; note_id: string; is_new_note: boolean; facts: number }) => void
  onDelta?: (noteId: string, text: string) => void
  onSectionDone?: (d: { section_id: string; summary: string; forced: boolean; blocked: boolean; blocked_reason: string | null }) => void
  onPlanExtended?: (sections: WritingSection[]) => void
  onPlanDone?: (plan: WritingPlan) => void
}

/** 跑 harness 主循环，SSE 流式返回；同一个 note_id 贯穿一个 section 的
 * 所有增量，一旦 section-start 换了 note_id，前端要自己切换当前打开的
 * 笔记去接着显示新内容。abort signal 断开 = 暂停，服务端下一轮循环检测到
 * 断开就停，plan 状态不变，之后可以再调一次继续。 */
export async function runWritingPlan(
  folderId: string,
  handlers: WritingPlanHandlers,
  signal?: AbortSignal,
) {
  const res = await fetch('/api/writing-plan/run', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ folder_id: folderId }),
    signal,
  })
  if (!res.ok || !res.body) throw new Error(`writing-plan run failed: ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let event = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const frames = buf.split('\n\n')
    buf = frames.pop() ?? ''
    for (const frame of frames) {
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) {
          const raw = line.slice(5).trim()
          if (!raw) continue
          const payload = JSON.parse(raw)
          if (event === 'plan-loaded') handlers.onPlanLoaded?.(payload.plan, payload.sections)
          else if (event === 'section-start') handlers.onSectionStart?.(payload)
          else if (event === 'delta') handlers.onDelta?.(payload.note_id, payload.text)
          else if (event === 'section-done') handlers.onSectionDone?.(payload)
          else if (event === 'plan-extended') handlers.onPlanExtended?.(payload.sections)
          else if (event === 'plan-done') handlers.onPlanDone?.(payload.plan)
          else if (event === 'error') throw new Error(payload.detail)
        }
      }
    }
  }
}

// ---------------------------------------------------------------- 记忆

export const recall = (query: string, limit = 8) =>
  fetch('/api/memory/recall', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ query, limit }),
  }).then(json<{ facts: Fact[]; took_ms: number; terms: string[] }>)

export const ask = (question: string) =>
  fetch('/api/memory/ask', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ question }),
  }).then(json<{ answer: string; facts: Fact[]; took_ms: number }>)

export type MemoryStats = {
  facts: number; topics: number; entities: number; units: number; lines: number
  speakers: string[]; start_date: string | null; end_date: string | null; codebook: string
}

export type Digest = {
  summary: string; fact_count: number; date_from: string; date_to: string; took_ms: number
}

export const digest = (days = 7) =>
  fetch('/api/digest', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ days }),
  }).then(json<Digest>)

export const memoryStats = () =>
  fetch('/api/memory/stats', { headers: headers() }).then(json<MemoryStats>)

// ---------------------------------------------------------------- 知识库可视化

export type TopicNode = {
  code: string; parents: string[]; status: string; aliases: string[]; fact_count: number
}
export type EntityNode = {
  code: string; name: string; type: string; aliases: string[]
  relations: [string, string][]; fact_count: number
}
export type TopicEntityLink = { topic: string; entity: string; weight: number }
export type FactDetail = {
  id: string; text: string; when: string; kind: string; who: string; conf: string
  topics: string[]; entities: string[]; unit: string
}
export type FactsPage = { facts: FactDetail[]; total: number; limit: number; offset: number }
export type SourceLine = { id: string; unit: string; date: string; who: string; text: string }
export type TimelineBucket = { date: string; units: number; facts: number }

export const memoryTopics = () =>
  fetch('/api/memory/topics', { headers: headers() }).then(json<TopicNode[]>)

export const createTopic = (code: string, parent = '', aliases: string[] = []) =>
  fetch('/api/memory/topics', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ code, parent, aliases }),
  }).then(json<TopicNode>)

export const memoryEntities = () =>
  fetch('/api/memory/entities', { headers: headers() }).then(json<EntityNode[]>)

export const topicEntityLinks = () =>
  fetch('/api/memory/topic-entity-links', { headers: headers() }).then(json<TopicEntityLink[]>)

export type FactsFilter = {
  kind?: string; who?: string; topic?: string; entity?: string; conf_min?: string
  limit?: number; offset?: number
}

export const memoryFacts = (filter: FactsFilter = {}) => {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(filter)) {
    if (v !== undefined && v !== '') q.set(k, String(v))
  }
  return fetch(`/api/memory/facts?${q}`, { headers: headers() }).then(json<FactsPage>)
}

export const factSources = (factId: string) =>
  fetch(`/api/memory/facts/${factId}/sources`, { headers: headers() }).then(json<SourceLine[]>)

export const memoryTimeline = () =>
  fetch('/api/memory/timeline', { headers: headers() }).then(json<{ buckets: TimelineBucket[] }>)

// ---------------------------------------------------------------- 入库

export const ingestText = (content: string, title = '', source = 'doc') =>
  fetch('/api/ingest/text', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ content, title, source }),
  }).then(json<{ job_id: string; status: string; detail: string }>)

export const ingestAudio = (file: Blob, filename = 'recording.webm', title = '') => {
  const fd = new FormData()
  fd.append('file', file, filename)
  fd.append('title', title)
  fd.append('language', 'auto')
  return fetch('/api/ingest/audio', { method: 'POST', headers: headers(), body: fd })
    .then(json<{ job_id: string; status: string; detail: string }>)
}

export const transcribeOnly = (file: Blob, filename = 'recording.webm') => {
  const fd = new FormData()
  fd.append('file', file, filename)
  fd.append('language', 'auto')
  return fetch('/api/ingest/transcribe', { method: 'POST', headers: headers(), body: fd })
    .then(json<{ text: string }>)
}

export type IngestItem = {
  id: string
  idx: number
  filename: string
  kind: string
  status: 'queued' | 'extracting' | 'transcribing' | 'chunking' | 'remembering'
    | 'done' | 'failed' | 'cancelled'
  facts: number
  detail: string
}

export type JobOut = {
  job_id: string
  status: 'queued' | 'running' | 'done' | 'error' | 'cancelled'
  facts: number
  detail: string
  items: IngestItem[]
}

export const jobStatus = (jobId: string) =>
  fetch(`/api/ingest/jobs/${jobId}`, { headers: headers() }).then(json<JobOut>)

export const listJobs = (limit = 20) =>
  fetch(`/api/ingest/jobs?limit=${limit}`, { headers: headers() }).then(json<JobOut[]>)

export const cancelJob = (jobId: string) =>
  fetch(`/api/ingest/jobs/${jobId}/cancel`, { method: 'POST', headers: headers() }).then(json)

/** 批量入库：PDF / DOCX / TXT / MD / 音频混着传，每个文件独立处理。 */
export const ingestBatch = (files: File[]) => {
  const fd = new FormData()
  for (const f of files) fd.append('files', f, f.name)
  fd.append('language', 'auto')
  return fetch('/api/ingest/batch', { method: 'POST', headers: headers(), body: fd })
    .then(json<JobOut>)
}

/** 订阅批量任务的进度流。onProgress 每次状态变化都会收到完整快照，任务到
 * 终态（done/error/cancelled）时 onEnd 被调用一次并自动关闭连接。 */
export function watchJob(
  jobId: string,
  onProgress: (j: JobOut) => void,
  onEnd: () => void,
  signal?: AbortSignal,
) {
  ;(async () => {
    const res = await fetch(`/api/ingest/jobs/${jobId}/events`, { headers: headers(), signal })
    if (!res.ok || !res.body) throw new Error(`events failed: ${res.status}`)
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let event = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const frames = buf.split('\n\n')
      buf = frames.pop() ?? ''
      for (const frame of frames) {
        for (const line of frame.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('data:')) {
            const raw = line.slice(5).trim()
            if (!raw) continue
            if (event === 'progress') onProgress(JSON.parse(raw) as JobOut)
            else if (event === 'end') onEnd()
          }
        }
      }
    }
  })().catch((err) => {
    if (signal?.aborted) return
    throw err
  })
}

export const health = () => fetch('/api/health').then(json<any>)

// ---------------------------------------------------------------- Skill 系统
//
// 把写作 prompt 系统"skill 化"：每条 skill 是一段额外叠加在某个生成调用点
// 基础 system prompt 之后的指令，可以开关、可以排序。新用户第一次拉取时
// 后端会自动种上几条从高分 Claude Skill 改写来的默认技能。

export type SkillScope = { value: string; label: string }

export type Skill = {
  id: string; user_id: string; name: string; description: string
  scopes: string[]; content: string; enabled: boolean
  idx: number; builtin: boolean; created_at: string; updated_at: string
}

export type SkillIn = {
  name: string; description: string; scopes: string[]; content: string; enabled: boolean
}

export const listSkillScopes = () =>
  fetch('/api/skills/scopes', { headers: headers() }).then(json<SkillScope[]>)

export const listSkills = () =>
  fetch('/api/skills', { headers: headers() }).then(json<Skill[]>)

export const createSkill = (body: SkillIn) =>
  fetch('/api/skills', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
  }).then(json<Skill>)

export const updateSkill = (id: string, body: SkillIn) =>
  fetch(`/api/skills/${id}`, {
    method: 'PUT',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
  }).then(json<Skill>)

export const toggleSkill = (id: string) =>
  fetch(`/api/skills/${id}/toggle`, { method: 'POST', headers: headers() }).then(json<Skill>)

export const deleteSkill = (id: string) =>
  fetch(`/api/skills/${id}`, { method: 'DELETE', headers: headers() }).then(json)

export const reorderSkills = (orderedIds: string[]) =>
  fetch('/api/skills/reorder', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ ordered_ids: orderedIds }),
  }).then(json)

/** 返回的是草稿（SkillIn 形状），不直接落库——调用方在编辑表单里展示，
 * 用户看过改过选好 scope 之后再调 createSkill 才真正保存。 */
export const generateSkill = (goal: string, scopeHint = '') =>
  fetch('/api/skills/generate', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ goal, scope_hint: scopeHint }),
  }).then(json<SkillIn>)

// ---------------------------------------------------------------- 单篇笔记 harness（智能续写）
//
// 跟无限续写（文件夹级）是同一个"harness"精神，范围收在一篇笔记内：自动
// 修订（不等人工点接受）+ 自动续写交替进行，直到内容相对结构节拍已经
// 完整才停，不是轮数封顶。

export type NoteHarnessRevision = { op: string; anchor: string; text: string; reason: string }

export type NoteHarnessDimensionScore = { level: number; note: string }

export type NoteHarnessHandlers = {
  onSkeleton?: (spine: string, beats: string[]) => void
  onRoundStart?: (d: { round: number; max_rounds: number; revisions_applied: number }) => void
  onRevision?: (r: NoteHarnessRevision) => void
  onDelta?: (text: string) => void
  onRoundEnd?: (round: number) => void
  onEvaluate?: (d: { scores: Record<string, NoteHarnessDimensionScore>; status: string; weakest: string | null }) => void
  onDone?: (reason: string, blockedReason?: string) => void
}

export async function runNoteHarness(
  noteId: string,
  content: string,
  spine: string,
  beats: string[],
  handlers: NoteHarnessHandlers,
  signal?: AbortSignal,
) {
  const res = await fetch('/api/note-harness/run', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ note_id: noteId, content, spine, beats, max_rounds: 20 }),
    signal,
  })
  if (!res.ok || !res.body) throw new Error(`note-harness run failed: ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let event = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const frames = buf.split('\n\n')
    buf = frames.pop() ?? ''
    for (const frame of frames) {
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) {
          const raw = line.slice(5).trim()
          if (!raw) continue
          const payload = JSON.parse(raw)
          if (event === 'skeleton') handlers.onSkeleton?.(payload.spine, payload.beats)
          else if (event === 'round-start') handlers.onRoundStart?.(payload)
          else if (event === 'revision') handlers.onRevision?.(payload)
          else if (event === 'delta') handlers.onDelta?.(payload.text)
          else if (event === 'round-end') handlers.onRoundEnd?.(payload.round)
          else if (event === 'evaluate') handlers.onEvaluate?.(payload)
          else if (event === 'done') handlers.onDone?.(payload.reason, payload.blocked_reason)
          else if (event === 'error') throw new Error(payload.detail)
        }
      }
    }
  }
}

// ---------------------------------------------------------------- LLM 供应商设置
//
// 全局设置，不分用户——本地模型还是 GPT，切了之后写作三件套/续写/知识库
// 抽取/实体去重全部跟着用新的供应商，不用重启后端。

export type ProviderConfig = {
  provider: 'local' | 'gpt'
  gpt_model: string
  gpt_base_url: string
  gpt_api_key_set: boolean
  gpt_api_key_preview: string
}

export const getProviderConfig = () =>
  fetch('/api/settings/provider', { headers: headers() }).then(json<ProviderConfig>)

export const setProviderConfig = (body: {
  provider: 'local' | 'gpt'
  gpt_api_key?: string
  gpt_model?: string
  gpt_base_url?: string
}) =>
  fetch('/api/settings/provider', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
  }).then(json<ProviderConfig>)
