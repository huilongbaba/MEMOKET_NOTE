/** 后端 API 封装。用户身份走 X-User-Id 头，原型阶段不做认证。 */

export type Note = {
  id: string
  user_id: string
  title: string
  content: string
  created_at: string
  updated_at: string
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
  op: 'insert' | 'delete' | 'replace'
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

export const listNotes = () =>
  fetch('/api/notes', { headers: headers() }).then(json<Note[]>)

export const createNote = (title: string, content: string) =>
  fetch('/api/notes', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ title, content }),
  }).then(json<Note>)

export const saveNote = (id: string, title: string, content: string) =>
  fetch(`/api/notes/${id}`, {
    method: 'PUT',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ title, content }),
  }).then(json<Note>)

export const deleteNote = (id: string) =>
  fetch(`/api/notes/${id}`, { method: 'DELETE', headers: headers() }).then(json)

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

export type TapMeta = { facts: number; recall_ms: number; grounded: boolean; sources: string[] }

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
