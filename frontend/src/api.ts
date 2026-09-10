/** 后端 API 封装。用户身份走 X-User-Id 头，原型阶段不做认证。 */

export type Note = {
  id: string
  user_id: string
  title: string
  content: string
  pinned: boolean
  folder_id: string | null
  /** 写作骨架跟着笔记走。之前只活在前端内存里，换一篇/刷新/无限续写自动
   * 跟随切页就没了——而 harness 每轮都拿它当主线依据。 */
  spine: string
  beats: string[]
  created_at: string
  updated_at: string
}

/** 树上的一个节点 = 一条 branch + 那篇笔记的显示信息。
 *
 * **没有 Folder 这个类型了。** 照 Trilium：文件夹不是一种东西，任何有子节点
 * 的笔记就是文件夹。所以「新建文件夹」= 新建笔记，「改文件夹名」= 改标题，
 * 「删文件夹」= 删笔记（连子树）。 */
export type TreeRow = {
  id: string                 // branch id
  note_id: string
  parent_note_id: string     // ROOT_ID = 挂在树根
  position: number
  is_expanded: boolean
  title: string
  /** 正文开头。标题为空或还是占位符时，树上拿它当显示名。 */
  preview: string
  pinned: boolean
  updated_at: string
  child_count: number
  /** 这篇引用了几条事实。树上画角标——一眼看出哪些笔记「有据可依」、
   *  哪些还只是草稿。见 docs/kb-fusion-design.md。 */
  cite_count: number
  /** 什么时候被摄入进知识库的。空 = 没摄入过。 */
  ingested_at: string
  /** 这篇笔记一共有几条 branch。>1 就是克隆，树上要标出来——用户得知道
   *  改这一处会让别处跟着变。 */
  branch_count: number
}

export const ROOT_ID = 'root'

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
  /** 结尾标记。锚点契约改成「短标记定位」之后，要动的是
   * anchor 开头 → anchor_end 结尾这一整段——模型不用把整段原文抄一遍。 */
  anchor_end?: string
  text: string
  reason: string
  sources: string[]
}

const USER_KEY = 'memoket-note-user'

export function getUser(): string {
  // `?user=xxx` 优先，并且记下来。桌面版靠它开到指定身份（`electron . --user=`），
  // 网页版靠它做「用另一个身份打开这个链接」——不然新环境永远拿到一个随机
  // 用户，看到的是一个空库，很容易误判成「数据没了」。
  const fromUrl = new URLSearchParams(location.search).get('user')?.trim()
  if (fromUrl) {
    localStorage.setItem(USER_KEY, fromUrl)
    return fromUrl
  }
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

export const createNote = (title: string, content: string, parent_note_id: string = ROOT_ID) =>
  fetch('/api/notes', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ title, content, parent_note_id }),
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

// ---------------------------------------------------------------- 笔记树
//
// 操作的主语是 **branch**（哪篇笔记 · 在哪个父节点下），不是笔记：一篇笔记
// 可以同时长在好几个位置，说「移动这篇笔记」是没有指向的。

/** 整棵树一次拿全。按需一层层拿的话，「展开一个节点」就变成一次网络往返，
 *  树用起来会一顿一顿的。 */
export const getTree = () =>
  fetch('/api/tree', { headers: headers() }).then(json<TreeRow[]>)

/** 把一篇已有的笔记挂到另一个位置 = **克隆**。不是复制：两处是同一篇，
 *  改一处处处都变。 */
export const cloneNoteTo = (note_id: string, parent_note_id: string) =>
  fetch('/api/tree/branches', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ note_id, parent_note_id }),
  }).then(json<TreeRow>)

/** 摘掉一条 branch——只是「不在这个位置显示了」，笔记本身还在别处。
 *  最后一条摘不掉（后端回 400）：那不是删除，是丢失。 */
export const detachBranch = (note_id: string, parent_note_id: string) =>
  fetch(`/api/tree/branches?note_id=${encodeURIComponent(note_id)}`
        + `&parent_note_id=${encodeURIComponent(parent_note_id)}`,
        { method: 'DELETE', headers: headers() }).then(json)

export const moveBranch = (
  note_id: string, from_parent_id: string, to_parent_id: string,
  position?: number,
) =>
  fetch('/api/tree/branches/move', {
    method: 'PATCH',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ note_id, from_parent_id, to_parent_id, position }),
  }).then(json)

/** 展开状态存在库里，不在前端内存里——刷新一次就全收起来的树，几十个节点
 *  之后就没法用了。 */
export const setBranchExpanded = (
  note_id: string, parent_note_id: string, expanded: boolean,
) =>
  fetch('/api/tree/branches/expanded', {
    method: 'PATCH',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ note_id, parent_note_id, expanded }),
  }).then(json)

/** 这篇笔记在树上的所有位置。克隆之后「它在哪」没有唯一答案——面包屑要显示
 *  的是用户当前从哪条路径点进来的，所以由调用方挑一条。 */
export const notePaths = (note_id: string) =>
  fetch(`/api/tree/paths/${note_id}`, { headers: headers() }).then(json<string[][]>)

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

// ---------------------------------------------------------------- 选中文本操作
//
// 右键选中一段文本触发。都产出同一个 Revision 形状的结果，
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

/** 一条 SSE 流拆成一帧一帧的 `{event, payload}`。
 *
 * 抽出来之前，这段「读 chunk → 按空行切帧 → 认 event:/data: → JSON.parse」
 * 在这个文件里有**五份拷贝**，而且已经不一致了：块生成那一份把事件名放在
 * 帧循环里面（对的），另外四份放在外面——一个只有 data: 的帧会沿用上一帧
 * 的事件名。后端目前总是成对发所以没炸过，但那是颗哑弹。只有块生成那一份
 * 会跳过解析不了的帧，另外四份会抛出去，把整条流掐断。
 *
 * 现在一处修好，五处都对：**事件名逐帧独立**，**解析不了的帧跳过**——为
 * 一帧坏数据放弃整次生成，代价是几十秒的工作量。
 */
export async function* sseFrames(
  res: Response,
): AsyncGenerator<{ event: string; payload: any }> {
  if (!res.body) throw new Error('no stream')
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    // SSE 以空行分帧，最后一段可能不完整，留在 buffer 里等下一个 chunk
    const frames = buf.split('\n\n')
    buf = frames.pop() ?? ''
    for (const frame of frames) {
      let event = ''
      let data = ''
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!data) continue
      let payload: any
      try { payload = JSON.parse(data) } catch { continue }
      yield { event, payload }
    }
  }
}


/** magic tap：SSE 流式续写。onMeta 先到（检索结果），onDelta 逐块到达。 */
export async function magicTap(
  content: string,
  spine: string,
  beats: string[],
  onMeta: (m: TapMeta) => void,
  onDelta: (s: string) => void,
  signal?: AbortSignal,
  /** 写完之后的确定性检查：检索到了多少条材料、正文里真的用上了几条。
   * 一条都没用上时 hint 会给一句诊断——magic tap 刻意不套完整的打分闭环
   * （它的定位是点一下几秒出一段），所以这里只提示，不打断也不重写。 */
  onGrounding?: (g: { facts: number; used: number; hint: string }) => void,
) {
  const res = await fetch('/api/magic-tap', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ content, spine, beats }),
    signal,
  })
  if (!res.ok || !res.body) throw new Error(`magic-tap failed: ${res.status}`)

  for await (const { event, payload } of sseFrames(res)) {
    if (event === 'meta') onMeta(payload as TapMeta)
    else if (event === 'delta') onDelta(payload.text as string)
    else if (event === 'grounding') onGrounding?.(payload)
    else if (event === 'error') throw new Error(payload.detail)
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

/** 放弃当前计划，好在同一个文件夹里换个目标重开。
 *  没有它的话，一个文件夹起过计划就再也换不掉——面板会一直显示那个旧目标。 */
export const abandonWritingPlan = (folderId: string) =>
  fetch(`/api/writing-plan/${folderId}/abandon`, { method: 'POST', headers: headers() })
    .then(json<{ abandoned: string }>)

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

  for await (const { event, payload } of sseFrames(res)) {
    if (event === 'plan-loaded') handlers.onPlanLoaded?.(payload.plan, payload.sections)
    else if (event === 'section-start') handlers.onSectionStart?.(payload)
    else if (event === 'delta') handlers.onDelta?.(payload.note_id, payload.text)
    else if (event === 'section-done') handlers.onSectionDone?.(payload)
    else if (event === 'plan-extended') handlers.onPlanExtended?.(payload.sections)
    else if (event === 'plan-done') handlers.onPlanDone?.(payload.plan)
    else if (event === 'error') throw new Error(payload.detail)
  }
}

// ---------------------------------------------------------------- 记忆

export const recall = (query: string, limit = 8) =>
  fetch('/api/memory/recall', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ query, limit }),
  }).then(json<{ facts: Fact[]; took_ms: number; terms: string[] }>)

/** 「来龙去脉」：给一段正文，回它涉及的事情按时间怎么演进的。
 *
 * **没有自由提问的接口了。** 问题由后端拼，用户一个字都不写——判据 1：
 * 界面上出现聊天输入框，就是我们没把意图封装好。原来那个 /api/memory/ask
 * 还在（这条建在它上面），但不再有对外入口。 */
/** 一条事实 + 它的原话，给行内出处浮层。 */
export type FactPeek = {
  id: string; text: string; when: string; kind: string; sources: string[]
}

/** 按 id 取一条事实。**找不到会 404**——一条指向不存在事实的引用是个真问题
 *  （模型编的、或者知识库重建过），浮层要把它说出来而不是显示成普通文字。 */
export const factPeek = (id: string) =>
  fetch(`/api/memory/facts/${encodeURIComponent(id)}`, { headers: headers() })
    .then((r) => (r.ok ? (r.json() as Promise<FactPeek>) : null))

/** 引用了某条事实的笔记。右栏「反向链接」用。 */
export type CitingNote = { id: string; title: string; updated_at: string }

/** **哪些笔记引用了这条事实。** 反查——整个「笔记 × 知识库」融合的关键。
 *  回答的是「这条事实还活着吗、改了它会影响谁」。对标 Trilium 的 Backlinks。 */
export const notesCiting = (factId: string) =>
  fetch(`/api/memory/facts/${encodeURIComponent(factId)}/citing`,
        { headers: headers() }).then(json<CitingNote[]>)

export type TraceOut = { answer: string; facts: Fact[]; took_ms: number }

export const traceMemory = (passage: string, limit = 10) =>
  fetch('/api/memory/trace', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ passage, limit }),
  }).then(json<TraceOut>)

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

/** 主题簇：细主题上面加的一层粗视图。
 *
 *  细主题让问答准，也正是让写作重复的原因——一节的材料摊在六个兄弟主题里。
 *  实测这个库 196 个主题、中位 10 条事实、51% ≤10 条；聚类之后中位 18。
 *  `merged=false` 的簇就是一个本来就够大的主题，没被并过。 */
export type TopicCluster = {
  key: string; label: string; topics: string[]; facts: number; merged: boolean
}

export const listClusters = () =>
  fetch('/api/kb/clusters', { headers: headers() })
    .then(json<{ clusters: TopicCluster[]; topics: number }>)

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

/** `source_id`：摄入的是哪篇笔记。**摄笔记时必须传**——后端据此在摄入完成
 *  后给那篇打上「已入库」标记，树上才看得见 ⇡；同时 KITE 用它拼稳定的
 *  session_id，同一篇重复摄入不会重复入库。 */
export const ingestText = (content: string, title = '', source = 'doc', source_id = '') =>
  fetch('/api/ingest/text', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ content, title, source, source_id }),
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
  // cancelling：收到取消但后台还没停干净（可能卡在一次 LLM 调用或 KITE 写锁里），
  // 这段时间要如实显示「正在停止…」，不能还写着「处理中」——否则跟没点一样。
  status: 'queued' | 'running' | 'cancelling' | 'done' | 'error' | 'cancelled'
  facts: number
  detail: string
  items: IngestItem[]
}

export const jobStatus = (jobId: string) =>
  fetch(`/api/ingest/jobs/${jobId}`, { headers: headers() }).then(json<JobOut>)

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
    for await (const { event, payload } of sseFrames(res)) {
      if (event === 'progress') onProgress(payload as JobOut)
      else if (event === 'end') onEnd()
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

/** 一个 skill 是盘上一个标准的 `SKILL.md` 目录，不是数据库里一行。
 *  `id` 就是目录名（slug）——前端一直按 id 寻址，含义变了、用法没变。
 *  `source` 区分内置 / 自己写的 / 第三方装的；装进来的默认是关的。 */
export type Skill = {
  id: string; slug: string; name: string; description: string
  scopes: string[]; content: string; enabled: boolean
  idx: number; builtin: boolean
  source: 'builtin' | 'user' | 'imported'; sandbox: 'none' | 'compute' | 'files'
}

export type SkillIn = {
  name: string; slug?: string; description: string
  scopes: string[]; content: string; enabled: boolean
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

export type NoteHarnessRevision = {
  op: string; anchor: string; anchor_end?: string
  text: string; reason: string; sources: string[]
}

export type NoteHarnessDimensionScore = { level: number; note: string }

export type NoteHarnessToolCall = { tool: string; args: Record<string, unknown>; result: string }

export type NoteHarnessHandlers = {
  onSkeleton?: (spine: string, beats: string[]) => void
  onRoundStart?: (d: { round: number; max_rounds: number; revisions_applied: number; skipped_continue?: boolean; facts?: number; sources?: string[] }) => void
  onRevision?: (r: NoteHarnessRevision) => void
  onDelta?: (text: string) => void
  onRoundEnd?: (round: number) => void
  onEvaluate?: (d: { scores: Record<string, NoteHarnessDimensionScore>; status: string; weakest: string | null }) => void
  /** `reason` 是 awaiting_review 时带 `runId`：这一轮停下来等你逐条处置，
   *  处置完把留下来的正文用 resumeHarness(runId, content) 送回去接着跑。 */
  onDone?: (reason: string, blockedReason?: string, runId?: string) => void
  onError?: (detail: string) => void
  /** 当前阶段（retrieval/edit/write/evaluate）和它的人话标签 */
  onPhase?: (d: { round: number; phase: string; label: string }) => void
  /** 阶段内的实时输出。kind=thinking 是模型的思考过程，output 是它写出来的东西。 */
  onPhaseDelta?: (d: { round: number; phase: string; kind: string; text: string }) => void
  /** agent 自己决定调了哪些工具 */
  onToolCalls?: (d: { round: number; iters: number; truncated: boolean; calls: NoteHarnessToolCall[] }) => void
  /** 策略控制器根据上一轮反馈调整了下一轮的跑法 */
  onPolicy?: (d: { round: number; policy: Partial<{ tool_iters: number; continue_temperature: number; max_revisions: number; require_verification: boolean }>; reasons: string[] }) => void
  /** 一条修订被防线丢弃了。**不是错误**——同义重写、锚点有歧义、会切出破字、
   * 会动到用户自己写的标题，这四类都是防线正常起作用，一轮能丢好几条。
   * 用 onError 渲染的话界面会变成一片红。 */
  onDropped?: (detail: string) => void
  /** 代码判据当场判这一轮不合格。命中时跳过模型打分，分数就是这条判据给的。 */
  onCheckHit?: (d: { dimension: string; note: string }) => void
  /** 某条 middleware 抛异常了。循环会继续跑（这是能力分包的隔离好处），
   * 但**不能是静默的**——这一轮少了那个能力，用户得知道。 */
  onWarning?: (d: { middleware: string; hook: string; error: string }) => void
  /** 骨架被重规划了。目标被改了，用户必须看得见改成了什么——后端在这之后
   * 还会重发一次 skeleton 事件让骨架面板跟着更新。 */
  onReplan?: (d: { round: number; why: string; changes: string[]; beats: string[] }) => void
}

export async function runNoteHarness(
  noteId: string,
  content: string,
  spine: string,
  beats: string[],
  handlers: NoteHarnessHandlers,
  signal?: AbortSignal,
  /** write = 边修边续写；polish = **只修不写**，专门理顺已有内容。
   * 打磨模式下后端还会摘掉 beat_coverage / material_use 两个维度——那两条衡量
   * 的是「写了多少」，而打磨被明确禁止写，拿它们打分闭环永远收敛不了。 */
  mode: 'write' | 'polish' = 'write',
  /** 每轮写完停下来等你逐条接受/拒绝。关着的时候是原来的行为：一口气跑完
   *  再处置——而那意味着你在编辑器里的处置会被下一轮盖掉。 */
  reviewEachRound = false,
) {
  const res = await fetch('/api/note-harness/run', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      note_id: noteId, content, spine, beats, max_rounds: 20, mode,
      review_each_round: reviewEachRound,
    }),
    signal,
  })
  if (!res.ok || !res.body) throw new Error(`note-harness run failed: ${res.status}`)
  return consumeHarnessStream(res, handlers)
}

/** 处置完接着跑。`content` 是编辑器里逐条接受/拒绝之后的正文——用户的决定
 *  发生在编辑器里，后端拿一串 hunk id 再合并一遍等于同一个合并写两份实现。 */
export async function resumeHarness(
  runId: string,
  content: string,
  handlers: NoteHarnessHandlers,
  signal?: AbortSignal,
) {
  const res = await fetch(`/api/harness/${runId}/resume`, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ content }),
    signal,
  })
  if (!res.ok || !res.body) throw new Error(`resume failed: ${res.status}`)
  return consumeHarnessStream(res, handlers)
}

/** 用户看完决定不再往下写：存盘收尾，丢掉快照。 */
export const stopHarness = (runId: string, content: string) =>
  fetch(`/api/harness/${runId}/resume`, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ content, stop: true }),
  }).then(json<{ stopped: string; rounds: number }>)

export type PausedRun = {
  id: string; note_id: string; mode: string; round: number; created_at: string
}

/** 跑到一半在等我处置的运行。SSE 流断了之后这是唯一能找回它们的地方。 */
export const listPausedRuns = () =>
  fetch('/api/harness/paused', { headers: headers() }).then(json<PausedRun[]>)

/** 导出只是为了能测。它是这条 harness 前端这一半的全部解析逻辑——
 * 事件被悄悄丢掉、帧在 chunk 边界上被切坏，都在这里发生，而症状是
 * 「面板上少了点东西」，没人会当成 bug 报。 */
export async function consumeHarnessStream(res: Response, handlers: NoteHarnessHandlers) {
  // AG-UI 标准事件。领域相关的东西走 CUSTOM 的 name 字段，所以这里是
  // 「九个标准分支 + 一个 CUSTOM 分支」，加一条 harness 不用改这儿。
  //
  // 后端一度用另一套自定义事件名，中间隔着一层翻译——那是三条 router 逐条
  // 迁移期间的过渡层。三条都切完之后前端换名字、后端删函数，一个 commit
  // 的事。
  for await (const { event, payload } of sseFrames(res)) {
    if (event === 'TEXT_MESSAGE_CONTENT') handlers.onDelta?.(payload.delta)
    else if (event === 'STEP_STARTED') handlers.onPhase?.({ round: payload.step, phase: '', label: payload.label })
    else if (event === 'STEP_FINISHED') handlers.onRoundEnd?.(payload.step)
    else if (event === 'ACTIVITY_SNAPSHOT') handlers.onPhase?.({ round: 0, phase: '', label: payload.content })
    else if (event === 'TOOL_CALL_RESULT') {
      handlers.onToolCalls?.({ round: 0, iters: 1, truncated: false,
        calls: [{ tool: payload.toolName, args: payload.args, result: payload.content }] })
    } else if (event === 'RUN_FINISHED') {
      handlers.onDone?.(payload.reason, payload.blocked_reason, payload.run_id)
    // **RUN_ERROR 不能 throw**：后端发它的场景都是可恢复的降级（某个工具查
    // 不到、某次调用超时），流还在继续。throw 会把整条 SSE 连接掐断，用户
    // 看到的是「跑到一半没了」。交给 onError 显示，让 harness 继续跑。
    } else if (event === 'RUN_ERROR') handlers.onError?.(payload.message)
    else if (event === 'CUSTOM') {
      const v = payload.value ?? {}
      if (payload.name === 'skeleton') handlers.onSkeleton?.(v.spine, v.beats)
      else if (payload.name === 'round_summary') handlers.onRoundStart?.(v)
      else if (payload.name === 'revision') handlers.onRevision?.(v)
      else if (payload.name === 'evaluate') handlers.onEvaluate?.(v)
      else if (payload.name === 'phase_delta') handlers.onPhaseDelta?.(v)
      else if (payload.name === 'policy') handlers.onPolicy?.(v)
      else if (payload.name === 'dropped') handlers.onDropped?.(v.detail)
      else if (payload.name === 'check_hit') handlers.onCheckHit?.(v)
      else if (payload.name === 'warning') handlers.onWarning?.(v)
      else if (payload.name === 'replan') handlers.onReplan?.(v)
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


// ---------------------------------------------------------------- 从别家笔记应用导入
//
// 跟 ingestBatch 分开是因为那条路拿不到原始日期、也不认识各家的私有语法——
// 一整个 vault 走那条路会被压成同一天，wiki 链接和 dataview 块会原样进知识库。
// 见 docs/import-from-other-note-apps.md。

/** 选整个 vault 时浏览器把相对路径放在 webkitRelativePath 里，要显式当文件名
 * 传上去，服务端靠它还原文件夹结构、并生成稳定 id（重跑就是增量同步）。 */
export const importFiles = (
  files: File[],
  source: 'obsidian' | 'evernote',
  to: 'both' | 'kb' | 'notes' = 'both',
) => {
  const fd = new FormData()
  for (const f of files) {
    fd.append('files', f, (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name)
  }
  fd.append('source', source)
  fd.append('to', to)
  return fetch('/api/import/files', { method: 'POST', headers: headers(), body: fd })
    .then(json<JobOut>)
}

export const importNotion = (token: string, to: 'both' | 'kb' | 'notes' = 'both') => {
  const fd = new FormData()
  fd.append('token', token)
  fd.append('to', to)
  return fetch('/api/import/notion', { method: 'POST', headers: headers(), body: fd })
    .then(json<JobOut>)
}

/** Apple Notes 没有公开 API，只能靠 AppleScript 在本机导出——而这个后端就跑在
 * 用户自己的 Mac 上，所以服务端能直接调 osascript。部署到远端时不可用，先问
 * available 再决定给不给按钮，别让用户点一个必然失败的东西。 */
export const appleAvailable = () =>
  fetch('/api/import/apple/available', { headers: headers() })
    .then(json<{ available: boolean; reason: string }>)

export const importApple = (to: 'both' | 'kb' | 'notes' = 'both') => {
  const fd = new FormData()
  fd.append('to', to)
  return fetch('/api/import/apple', { method: 'POST', headers: headers(), body: fd })
    .then(json<JobOut>)
}

// ---------------------------------------------------------------- 写作骨架

/** 骨架跟着笔记存。之前只活在前端内存里，`open()` 一进笔记就清空——换一篇、
 * 刷新页面、甚至无限续写开着「跟随」自动切到下一段，骨架就没了。 */
export const saveSkeleton = (noteId: string, spine: string, beats: string[]) =>
  fetch(`/api/notes/${noteId}/skeleton`, {
    method: 'PUT',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ spine, beats }),
  }).then(json<Note>)

// ---------------------------------------------------------------- `/` 唤起的块生成

/** 走跟写作 harness 同一套闭环：规划（调工具）→ 生成 → 打分 → 不达标带着诊断
 * 再来一轮。数字由 data 组工具算、图表语法由 chart 组工具拼——模型只决定算
 * 什么、画什么。custom 是右键「自定义提示」，作用域是选中的那段。 */
export type BlockMode = 'prompt' | 'chart' | 'table' | 'eda' | 'analysis' | 'custom'

export async function composeBlock(
  body: { note_id: string; title: string; content: string; cursor: number;
          mode: BlockMode; prompt: string; selection?: string },
  on: {
    onPhase?: (label: string) => void
    onTools?: (calls: NoteHarnessToolCall[]) => void
    onDelta?: (text: string) => void
    onEvaluate?: (status: string, scores: Record<string, NoteHarnessDimensionScore>) => void
    onError?: (detail: string) => void
  },
  signal?: AbortSignal,
): Promise<string> {
  const res = await fetch('/api/compose/block', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) throw new Error(await res.text().catch(() => res.statusText))
  let block = ''
  for await (const { event, payload } of sseFrames(res)) {
    const p = payload as Record<string, unknown>
    if (event === 'ACTIVITY_SNAPSHOT') on.onPhase?.(String(p.content ?? ''))
    else if (event === 'STEP_STARTED') on.onPhase?.(String(p.label ?? ''))
    else if (event === 'TOOL_CALL_RESULT') {
      on.onTools?.([{ tool: String(p.toolName ?? ''), args: p.args as Record<string, unknown>,
                      result: String(p.content ?? '') }] as NoteHarnessToolCall[])
    } else if (event === 'TEXT_MESSAGE_CONTENT') on.onDelta?.(String(p.delta ?? ''))
    else if (event === 'CUSTOM' && p.name === 'evaluate') {
      const v = (p.value ?? {}) as Record<string, unknown>
      on.onEvaluate?.(String(v.status ?? ''),
        v.scores as Record<string, NoteHarnessDimensionScore>)
    } else if (event === 'RUN_ERROR') on.onError?.(String(p.message ?? ''))
    else if (event === 'RUN_FINISHED') block = String(p.content ?? block)
  }
  return block
}

/** 智能排版：判断哪行该是标题、哪几行该是列表——规则算不出来的语义判断。
 *
 * **模型只输出「第几行改成什么结构」，一个字的原文都不输出**，原文由后端按行
 * 搬运（见 app/restructure.py）。所以"排版顺手改了内容"在结构上就不可能发生，
 * 不是靠提示词说「不要改内容」。 */
export const restructureNote = (noteId: string, title: string, content: string) =>
  fetch('/api/compose/restructure', {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ note_id: noteId, title, content }),
  }).then(json<{ changed: boolean; content: string; ops: number
                 skipped: string[]; detail: string }>)

// ---------------------------------------------------------------- 附件

/** 图片和音频存成文件，正文里只留短链接。**不内联成 data URI**：笔记正文存在
 * sqlite 里，一张手机拍的图 base64 之后两三兆，会跟着每一次自动保存、每一轮
 * harness 的上下文一起搬来搬去。 */
export const uploadAsset = (file: File) => {
  const fd = new FormData()
  fd.append('file', file, file.name)
  return fetch('/api/assets', { method: 'POST', headers: headers(), body: fd })
    .then(json<{ url: string; name: string; kind: 'image' | 'audio'; bytes: number }>)
}

/** 一张图 → markdown 表格。看图走**本地**那台带视觉的模型，图片不出内网。
 * 识别不出表格时 detected=false，前端如实说「没有检测到表格」——比硬塞一张
 * 空表进用户笔记好得多。 */
export const tableFromImage = (file: File) => {
  const fd = new FormData()
  fd.append('file', file, file.name)
  return fetch('/api/compose/table-from-image', { method: 'POST', headers: headers(), body: fd })
    .then(json<{ detected: boolean; table: string; raw: string }>)
}
