/**
 * 岛上的智能体会话：Claude Code 在主进程里以无头方式跑
 * （`claude -p --output-format stream-json`），这里把它逐行吐出的 JSON 归一化成
 * AgentTurnEvent 广播给岛，渲染层不碰 CLI 的原始输出。一次只有一轮在进行，每轮
 * 一个子进程，`--resume` 接上同一个会话。会话索引与逐轮记录都在
 * userData/agent/ 下；智能体只能在其中的 workspace/ 里读写（工具规则按绝对路径限定），
 * 不带用户配置里的 MCP 连接器。拖进来的文件复制到 workspace/附件/，随下一句一起发。
 */
import { ipcMain } from 'electron'
import type { IpcMainInvokeEvent, WebContents } from 'electron'
import { spawn as nodeSpawn, type ChildProcess } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { closeSync, constants as fsConstants, copyFileSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, realpathSync, renameSync, statSync, unlinkSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import path from 'node:path'
import { StringDecoder } from 'node:string_decoder'
import type { AgentArtifact, AgentMessage, AgentModel, AgentSendInput, AgentSession, AgentStatus, AgentTurnEvent, CompanionActionResult, CompanionMutationResult } from './companion-types'

export type AgentBridgeOptions = {
  /** userData/agent：工作目录、会话索引与逐轮记录都在这下面。 */
  directory: string
  /** 每个 IPC 处理器先过这一关；不是岛的窗口就抛错。 */
  authorize(event: IpcMainInvokeEvent): void
  /** 把工作目录里的文件放进暂存箱：和拖入文件同一条路（复制进库）。 */
  shelve(paths: string[]): Promise<CompanionMutationResult>
  /** 要收到 `agent:event` 广播的窗口。 */
  targets(): WebContents[]
  log(line: string): void
  /** 直接指定可执行文件；不给就按常见位置找。 */
  executable?: string
  spawn?: typeof nodeSpawn
  /** 叠在 process.env 上；测试里用来隔离 PATH。 */
  env?: NodeJS.ProcessEnv
  home?: string
  /** PATH 之外的固定候选位置；默认是常见安装位置，测试里传空数组隔离这台机器。 */
  locations?: string[]
}
export type AgentBridge = { dispose(): void }
export type AgentSendResult = CompanionActionResult & { turnId?: string; sessionId?: string | null }

const MODELS: AgentModel[] = [{ id: '', label: '默认' }, { id: 'opus', label: 'Opus' }, { id: 'sonnet', label: 'Sonnet' }, { id: 'haiku', label: 'Haiku' }]
const SYSTEM_PROMPT = '你在 MEMOKET NOTE 桌面浮窗的会话里工作。回答用中文，简洁直接。只在当前工作目录里读写文件；需要产出文件时直接写到工作目录，并在回复里说明文件名。'
/** 读写类工具按工作目录的绝对路径限定（`//` 开头是 Claude Code 权限规则里的绝对路径）；Glob / Grep 只是找。 */
const SCOPED_TOOLS = ['Read', 'Write', 'Edit', 'MultiEdit']
const OPEN_TOOLS = ['Glob', 'Grep']
/** 岛上的会话不带用户配置里的 MCP 连接器：没授权的连接器会让回复里多出一段无关的说明。 */
const MCP_NONE = '{"mcpServers":{}}'
const DISALLOWED_TOOLS = ['Bash', 'WebFetch', 'WebSearch', 'NotebookEdit', 'Task', 'Agent', 'Workflow']
const NOT_FOUND = '没找到 Claude Code。安装并在终端登录后，这里就能直接对话。'
const NOT_LOGGED_IN = 'Claude Code 还没登录。在终端里运行 claude 登录后，再回来对话。'
const BUSY = '上一轮还在进行，先停止它。'
const IDLE = '没有正在进行的会话'
const STOPPED = '已停止'
const EXITED = '会话进程退出了，没有返回结果。'
const OUTSIDE = '只能把会话工作目录里的文件放进暂存箱。'
const MISSING = '文件已经不在了，没法放进暂存箱。'
const ATTACH_DIR = '附件'
const ATTACH_MAX_FILES = 20
const ATTACH_MAX_BYTES = 200 * 1024 * 1024
const ATTACH_INVALID = '无法读取这个文件的本机路径，请从 Finder 或文件管理器拖入。'
const ATTACH_TOO_MANY = `一次最多带上 ${ATTACH_MAX_FILES} 个文件。`
const ATTACH_NOT_FILE = '只能带上文件；文件夹先放进暂存箱。'
const ATTACH_TOO_BIG = '单个文件不能超过 200 MB。'
const ATTACH_MISSING = '文件已经不在了。'
const ATTACH_OUTSIDE = '附件不在会话工作目录里。'
const MAX_TEXT = 20_000
const MAX_TITLE = 40
const MAX_SESSIONS = 30
const VERSION_TIMEOUT_MS = 5000
const REPROBE_MS = 10_000
const KILL_GRACE_MS = 2000
const EXIT_GRACE_MS = 1000
const STDERR_KEEP = 4000
const STDERR_TAIL = 300
const MODEL_PATTERN = /^claude-[a-z0-9.-]{1,60}$/
const SESSION_PATTERN = /^[0-9a-f-]{8,64}$/i
const ANSI_PATTERN = /\u001b\[[0-9;?]*[ -/]*[@-~]/g

type Index = { v: 1; sessions: AgentSession[] }
type Transcript = { v: 1; messages: AgentMessage[] }
type Probe = { executable: string | null; version: string; available: boolean; reason: string; at: number }
type Json = { [key: string]: unknown }
type Turn = {
  id: string
  sessionId: string | null
  /** 用户选的模型（传给 --model 的值）；init 到了之后是 CLI 自报的模型名。 */
  model: string
  child: ChildProcess
  user: AgentMessage
  userPersisted: boolean
  text: string
  blocks: string[]
  artifacts: AgentArtifact[]
  artifactPaths: Set<string>
  buffer: string
  decoder: StringDecoder
  stderr: string
  spawnError: string
  concluded: boolean
  interrupted: boolean
  loggedUnparseable: boolean
  killTimer: ReturnType<typeof setTimeout> | null
}

const isObject = (value: unknown): value is Json => !!value && typeof value === 'object' && !Array.isArray(value)
const isIndex = (value: unknown): value is Index => isObject(value) && value.v === 1 && Array.isArray(value.sessions)
const isTranscript = (value: unknown): value is Transcript => isObject(value) && value.v === 1 && Array.isArray(value.messages)
const isSession = (value: unknown): value is AgentSession => isObject(value) && typeof value.id === 'string' && SESSION_PATTERN.test(value.id)
  && typeof value.title === 'string' && typeof value.updatedAt === 'string'
const isMessage = (value: unknown): value is AgentMessage => isObject(value) && typeof value.id === 'string' && (value.role === 'user' || value.role === 'assistant') && typeof value.text === 'string'
const describe = (error: unknown) => error instanceof Error ? error.message : String(error)
const isWithin = (root: string, target: string) => target === root || target.startsWith(root.endsWith(path.sep) ? root : root + path.sep)
const title = (text: string) => text.replace(/\s+/g, ' ').trim().slice(0, MAX_TITLE)

export function createAgentBridge(options: AgentBridgeOptions): AgentBridge {
  const spawn = options.spawn ?? nodeSpawn
  const home = options.home ?? homedir()
  const workspace = path.join(options.directory, 'workspace')
  const indexFile = path.join(options.directory, 'sessions.json')
  const transcriptFile = (sessionId: string) => path.join(options.directory, 'sessions', `${sessionId}.json`)
  const locations = options.locations ?? [
    path.join(home, '.npm-global', 'bin', 'claude'),
    '/opt/homebrew/bin/claude',
    '/usr/local/bin/claude',
    path.join(home, '.claude', 'local', 'claude'),
    path.join(home, '.local', 'bin', 'claude'),
  ]
  const handlers: string[] = []
  const children = new Set<ChildProcess>()
  const warned = new Set<string>()
  let probe: Promise<Probe> | null = null
  let probed: Probe | null = null
  let loggedIn: boolean | null = null
  let current: Turn | null = null
  let disposed = false

  const log = (line: string) => { try { options.log(`${line}\n`) } catch { /* 日志本身出错不影响会话。 */ } }
  const warnOnce = (key: string, line: string) => { if (!warned.has(key)) { warned.add(key); log(line) } }

  try { mkdirSync(workspace, { recursive: true, mode: 0o700 }) }
  catch (error) { log(`[agent] 工作目录建不出来：${describe(error)}`) }

  // ── 找可执行文件、问版本 ────────────────────────────────────────────────
  function mergedEnv(): NodeJS.ProcessEnv { return { ...process.env, ...options.env } }

  /** 从 Finder 启动的应用 PATH 很短，所以除了 PATH 还查几个常见安装位置。 */
  function findExecutable(): string | null {
    const env = mergedEnv()
    const candidates: string[] = []
    if (options.executable) candidates.push(options.executable)
    if (env.MEMOKET_CLAUDE_BIN) candidates.push(env.MEMOKET_CLAUDE_BIN)
    for (const entry of (env.PATH ?? '').split(path.delimiter)) if (entry) candidates.push(path.join(entry, 'claude'))
    candidates.push(...locations)
    for (const candidate of candidates) {
      try { if (statSync(candidate).isFile()) return candidate } catch { /* 下一个。 */ }
    }
    return null
  }

  /** 子进程的环境：去掉嵌套会话的标记（否则 CLI 会拒绝在另一个 Claude Code 里启动），把可执行文件所在目录补进 PATH。 */
  function childEnv(executable: string): NodeJS.ProcessEnv {
    const env = mergedEnv()
    delete env.CLAUDECODE
    delete env.CLAUDE_CODE_ENTRYPOINT
    const entries = [path.dirname(executable), ...(env.PATH ?? '').split(path.delimiter)].filter(Boolean)
    env.PATH = [...new Set(entries)].join(path.delimiter)
    return env
  }

  /** 进程收尾：正常是 'close'；万一只来了 'exit' / 'error'，宽限一秒后也算结束。 */
  function whenDone(child: ChildProcess, callback: () => void) {
    let done = false
    let timer: ReturnType<typeof setTimeout> | null = null
    const finish = () => { if (done) return; done = true; if (timer) clearTimeout(timer); callback() }
    const soon = () => { if (!done && !timer) { timer = setTimeout(finish, EXIT_GRACE_MS); timer.unref?.() } }
    child.on('close', finish)
    child.on('exit', soon)
    child.on('error', soon)
  }

  function readVersion(executable: string): Promise<string | null> {
    return new Promise(resolve => {
      let child: ChildProcess
      try { child = spawn(executable, ['--version'], { cwd: workspace, env: childEnv(executable), stdio: ['ignore', 'pipe', 'pipe'] }) }
      catch (error) { log(`[agent] 问不到版本（${executable}）：${describe(error)}`); resolve(null); return }
      let output = ''
      let settled = false
      const finish = (value: string | null) => { if (settled) return; settled = true; clearTimeout(timer); resolve(value) }
      const timer = setTimeout(() => {
        log(`[agent] ${executable} --version ${VERSION_TIMEOUT_MS / 1000} 秒没回应`)
        try { child.kill('SIGKILL') } catch { /* 已经退出了。 */ }
        finish(null)
      }, VERSION_TIMEOUT_MS)
      timer.unref?.()
      child.stdout?.on('data', chunk => { output += String(chunk) })
      child.stderr?.on('data', () => { /* 只要 stdout 的第一行。 */ })
      child.on('error', error => { log(`[agent] 问不到版本（${executable}）：${describe(error)}`); finish(null) })
      whenDone(child, () => { const line = output.trim().split(/\r?\n/)[0]?.trim() ?? ''; finish(line || null) })
    })
  }

  async function runProbe(): Promise<Probe> {
    const executable = findExecutable()
    if (!executable) return { executable: null, version: '', available: false, reason: NOT_FOUND, at: Date.now() }
    const version = await readVersion(executable)
    if (version === null) return { executable, version: '', available: false, reason: `找到了 Claude Code（${executable}），但它没有回应版本检查。`, at: Date.now() }
    log(`[agent] Claude Code ${version}：${executable}`)
    return { executable, version, available: true, reason: '', at: Date.now() }
  }

  /** 只问一次版本；没找到时隔一会儿再找，装好之后不用重启应用。 */
  function ready(): Promise<Probe> {
    if (probe && (!probed || probed.available || Date.now() - probed.at < REPROBE_MS)) return probe
    probed = null   // 重新找的这一会儿，后来的调用等同一个 probe，别并发地再问一遍版本
    probe = runProbe().then(result => { probed = result; return result })
    return probe
  }

  // ── 落盘：索引与逐轮记录，原子写，坏文件当空的 ──────────────────────────
  function readJson<T>(file: string, valid: (value: unknown) => value is T, empty: () => T): T {
    let raw: string
    try { raw = readFileSync(file, 'utf8') }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') warnOnce(file, `[agent] ${path.basename(file)} 读不了，当它是空的：${describe(error)}`)
      return empty()
    }
    try {
      const parsed: unknown = JSON.parse(raw)
      if (valid(parsed)) return parsed
    } catch { /* 下面统一处理。 */ }
    warnOnce(file, `[agent] ${path.basename(file)} 不是预期的格式，当它是空的`)
    return empty()
  }

  function writeJson(file: string, value: unknown) {
    mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 })
    const temporary = `${file}.${randomUUID()}.tmp`
    let descriptor: number | undefined
    try {
      descriptor = openSync(temporary, 'wx', 0o600)
      writeFileSync(descriptor, JSON.stringify(value, null, 2))
      fsyncSync(descriptor)
      closeSync(descriptor)
      descriptor = undefined
      renameSync(temporary, file)
    } finally {
      if (descriptor !== undefined) closeSync(descriptor)
      try { unlinkSync(temporary) } catch { /* 改名成功就没有临时文件了。 */ }
    }
  }

  function persist(file: string, value: unknown, what: string) {
    try { writeJson(file, value) }
    catch (error) { log(`[agent] ${what}保存失败：${describe(error)}`) }
  }

  const loadIndex = () => readJson(indexFile, isIndex, (): Index => ({ v: 1, sessions: [] })).sessions.filter(isSession)
  const saveIndex = (sessions: AgentSession[]) => persist(indexFile, { v: 1, sessions } satisfies Index, '会话索引')
  const loadTranscript = (sessionId: string) => readJson(transcriptFile(sessionId), isTranscript, (): Transcript => ({ v: 1, messages: [] })).messages.filter(isMessage)
  const saveTranscript = (sessionId: string, messages: AgentMessage[]) => persist(transcriptFile(sessionId), { v: 1, messages } satisfies Transcript, '会话记录')

  function appendMessage(sessionId: string, message: AgentMessage) {
    const messages = loadTranscript(sessionId)
    messages.push(message)
    saveTranscript(sessionId, messages)
  }

  function updateSession(sessionId: string, change: (session: AgentSession) => void, create?: () => AgentSession) {
    const sessions = loadIndex()
    let session = sessions.find(candidate => candidate.id === sessionId)
    if (!session) {
      if (!create) return
      session = create()
      sessions.push(session)
    }
    change(session)
    saveIndex(sessions)
  }

  /** 新会话在这一刻才有 id：建索引条目，把等着的那条用户消息写进记录。 */
  function adoptSession(turn: Turn, sessionId: string, model: string) {
    if (!turn.sessionId) turn.sessionId = sessionId
    else if (turn.sessionId !== sessionId) log(`[agent] 续上的会话 ${turn.sessionId} 被 CLI 报成了 ${sessionId}，记录仍按前者`)
    const now = new Date().toISOString()
    updateSession(turn.sessionId, session => { if (model) session.model = model }, () => ({ id: turn.sessionId!, title: title(turn.user.text) || '新会话', model, createdAt: now, updatedAt: now, turns: 0 }))
    if (!turn.userPersisted) { turn.userPersisted = true; appendMessage(turn.sessionId, turn.user) }
  }

  // ── 广播 ────────────────────────────────────────────────────────────────
  function broadcast(event: AgentTurnEvent) {
    if (disposed) return
    for (const contents of options.targets()) {
      try { if (!contents.isDestroyed()) contents.send('agent:event', event) }
      catch (error) { log(`[agent] 事件没发出去：${describe(error)}`) }
    }
  }

  // ── 一轮：读 CLI 的 JSON 行 ─────────────────────────────────────────────
  function handleChunk(turn: Turn, chunk: unknown) {
    turn.buffer += typeof chunk === 'string' ? chunk : turn.decoder.write(chunk as Buffer)
    let index: number
    while ((index = turn.buffer.indexOf('\n')) >= 0) {
      const line = turn.buffer.slice(0, index)
      turn.buffer = turn.buffer.slice(index + 1)
      handleLine(turn, line)
    }
  }

  function handleLine(turn: Turn, raw: string) {
    const line = raw.trim()
    if (!line || turn.concluded) return
    let record: unknown
    try { record = JSON.parse(line) }
    catch {
      if (!turn.loggedUnparseable) { turn.loggedUnparseable = true; log(`[agent] 读不懂 CLI 的一行输出：${line.slice(0, 200)}`) }
      return
    }
    if (!isObject(record)) return
    switch (record.type) {
      case 'system': if (record.subtype === 'init') handleInit(turn, record); break
      case 'stream_event': handleStream(turn, record.event); break
      case 'assistant': if (record.is_api_error_message !== true) handleAssistant(turn, record.message); break   // 接口报错那一行不是回复
      case 'result': handleResult(turn, record); break
      default: break
    }
  }

  function handleInit(turn: Turn, record: Json) {
    const sessionId = typeof record.session_id === 'string' && SESSION_PATTERN.test(record.session_id) ? record.session_id : null
    const model = typeof record.model === 'string' ? record.model : ''
    if (!sessionId) { log('[agent] init 里没有可用的会话编号'); return }
    adoptSession(turn, sessionId, model)
    if (model) turn.model = model
    broadcast({ type: 'session', turnId: turn.id, sessionId: turn.sessionId!, model: turn.model })
  }

  function pushText(turn: Turn, text: string) {
    if (!text) return
    turn.text += text
    broadcast({ type: 'delta', turnId: turn.id, text })
  }

  function handleStream(turn: Turn, event: unknown) {
    if (!isObject(event)) return
    if (event.type === 'content_block_delta') {
      const delta = event.delta
      if (isObject(delta) && delta.type === 'text_delta' && typeof delta.text === 'string') pushText(turn, delta.text)
    } else if (event.type === 'content_block_start') {
      // 工具调用前后各有一段正文：拼在一起时隔一个空行，别粘成一句。
      const block = event.content_block
      if (isObject(block) && block.type === 'text' && turn.text && !/\n$/.test(turn.text)) pushText(turn, '\n\n')
    }
  }

  function handleAssistant(turn: Turn, message: unknown) {
    if (!isObject(message) || !Array.isArray(message.content)) return
    for (const block of message.content) {
      if (!isObject(block)) continue
      if (block.type === 'text') { if (typeof block.text === 'string' && block.text) turn.blocks.push(block.text) }
      else if (block.type === 'tool_use' && typeof block.name === 'string') handleToolUse(turn, block.name, block.input)
    }
  }

  function handleToolUse(turn: Turn, tool: string, input: unknown) {
    const filePath = isObject(input) && typeof input.file_path === 'string' && input.file_path ? input.file_path : ''
    const resolved = filePath ? path.resolve(workspace, filePath) : ''
    const name = resolved ? path.basename(resolved) : ''
    if (tool === 'Write' || tool === 'Edit' || tool === 'MultiEdit') {
      broadcast({ type: 'activity', turnId: turn.id, tool, path: resolved || undefined, label: `正在写 ${name || '文件'}` })
      // 只有工作目录里的文件算产出；写到别处的只当活动提示，不进暂存候选。
      if (!resolved || !isWithin(workspace, resolved) || turn.artifactPaths.has(resolved)) return
      turn.artifactPaths.add(resolved)
      const artifact: AgentArtifact = { path: resolved, name, action: tool === 'Write' ? 'write' : 'edit' }
      turn.artifacts.push(artifact)
      broadcast({ type: 'artifact', turnId: turn.id, artifact })
    } else if (tool === 'Read') {
      broadcast({ type: 'activity', turnId: turn.id, tool, path: resolved || undefined, label: `正在读 ${name || '文件'}` })
    } else if (tool === 'Glob' || tool === 'Grep') {
      broadcast({ type: 'activity', turnId: turn.id, tool, label: '正在找…' })
    }
  }

  function handleResult(turn: Turn, record: Json) {
    const result = typeof record.result === 'string' ? record.result : ''
    if (record.is_error === true) {
      const message = result.trim() || '会话出错了。'
      const notLoggedIn = /not logged in|\/login/i.test(message)
      if (notLoggedIn) loggedIn = false
      conclude(turn, { error: message, notLoggedIn })
      return
    }
    if (!turn.sessionId) {
      // 没见到 init 却成功了：认 result 里的编号，别把这一轮丢掉。
      const sessionId = typeof record.session_id === 'string' && SESSION_PATTERN.test(record.session_id) ? record.session_id : null
      if (!sessionId) { conclude(turn, { error: '会话没有返回会话编号。' }); return }
      adoptSession(turn, sessionId, '')
    }
    const text = turn.text || turn.blocks.join('\n\n') || result
    const costUsd = typeof record.total_cost_usd === 'number' && Number.isFinite(record.total_cost_usd) ? record.total_cost_usd : undefined
    conclude(turn, { text, costUsd })
  }

  type Outcome = { text: string; costUsd?: number } | { error: string; notLoggedIn?: boolean }

  /** 一轮到此为止：落盘、更新索引、广播。之后子进程再说什么都不听了。 */
  function conclude(turn: Turn, outcome: Outcome) {
    if (turn.concluded) return
    turn.concluded = true
    if (turn.killTimer) { clearTimeout(turn.killTimer); turn.killTimer = null }
    if (current === turn) current = null
    const now = new Date().toISOString()
    if ('error' in outcome) {
      if (turn.sessionId) {
        const message: AgentMessage = { id: randomUUID(), role: 'assistant', text: turn.text || turn.blocks.join('\n\n'), at: now, error: outcome.error }
        if (turn.artifacts.length) message.artifacts = turn.artifacts
        appendMessage(turn.sessionId, message)
        updateSession(turn.sessionId, session => { session.updatedAt = now })
      }
      broadcast({ type: 'turn-error', turnId: turn.id, sessionId: turn.sessionId, message: outcome.error, notLoggedIn: outcome.notLoggedIn })
      return
    }
    loggedIn = true
    const message: AgentMessage = { id: randomUUID(), role: 'assistant', text: outcome.text, at: now }
    if (turn.artifacts.length) message.artifacts = turn.artifacts
    if (outcome.costUsd !== undefined) message.costUsd = outcome.costUsd
    appendMessage(turn.sessionId!, message)
    updateSession(turn.sessionId!, session => { session.turns += 1; session.updatedAt = now; if (turn.model) session.model = turn.model })
    broadcast({ type: 'turn-end', turnId: turn.id, sessionId: turn.sessionId!, message })
  }

  /** 进程结束：先把没换行的尾巴当最后一行读完，还没有结论就按退出原因收尾。 */
  function finalize(turn: Turn) {
    children.delete(turn.child)
    if (turn.buffer.trim() && !turn.concluded) { const rest = turn.buffer; turn.buffer = ''; handleLine(turn, rest) }
    if (turn.concluded) return
    if (turn.interrupted) { conclude(turn, { error: STOPPED }); return }
    if (turn.spawnError) { conclude(turn, { error: `会话进程没起来：${turn.spawnError}` }); return }
    const tail = turn.stderr.replace(ANSI_PATTERN, '').trim().slice(-STDERR_TAIL).trim()
    conclude(turn, { error: tail || EXITED })
  }

  // ── 对外：状态、会话、发送、打断、放入暂存箱 ─────────────────────────────
  async function status(): Promise<AgentStatus> {
    const state = await ready()
    const reason = !state.available ? state.reason : loggedIn === false ? NOT_LOGGED_IN : ''
    return { available: state.available, loggedIn, version: state.version, reason, cwd: workspace, models: MODELS.map(model => ({ ...model })), runningTurnId: current?.id ?? null }
  }

  function sessions(): AgentSession[] {
    return loadIndex().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).slice(0, MAX_SESSIONS)
  }

  function transcript(sessionId: unknown): AgentMessage[] {
    if (typeof sessionId !== 'string' || !SESSION_PATTERN.test(sessionId)) return []
    return loadTranscript(sessionId)
  }

  function parseSend(input: unknown): { ok: true; value: AgentSendInput } | { ok: false; error: string } {
    if (!isObject(input)) return { ok: false, error: '无效的会话输入。' }
    const { sessionId, text, model, attachments } = input
    if (typeof text !== 'string' || !text.trim()) return { ok: false, error: '先写点什么再发。' }
    if (text.length > MAX_TEXT) return { ok: false, error: `一次最多 ${MAX_TEXT} 字。` }
    if (typeof model !== 'string' || !(model === '' || MODELS.some(candidate => candidate.id === model) || MODEL_PATTERN.test(model))) return { ok: false, error: '无效的模型。' }
    if (sessionId !== null && (typeof sessionId !== 'string' || !SESSION_PATTERN.test(sessionId))) return { ok: false, error: '无效的会话。' }
    let files: string[] = []
    if (attachments !== undefined) {
      if (!Array.isArray(attachments) || attachments.length > ATTACH_MAX_FILES) return { ok: false, error: ATTACH_TOO_MANY }
      if (attachments.length) { try { files = validateInside(attachments, ATTACH_OUTSIDE) } catch (error) { return { ok: false, error: describe(error) } } }
    }
    return { ok: true, value: { sessionId, text, model, ...(files.length ? { attachments: files } : {}) } }
  }

  function cliArgs(input: AgentSendInput): string[] {
    return [
      '-p', '--output-format', 'stream-json', '--input-format', 'text', '--verbose', '--include-partial-messages',
      ...(input.model ? ['--model', input.model] : []),
      ...(input.sessionId ? ['--resume', input.sessionId] : []),
      '--permission-mode', 'acceptEdits',
      '--allowedTools', ...OPEN_TOOLS, ...SCOPED_TOOLS.map(tool => `${tool}(//${workspace.replace(/^[\\/]+/, '')}/**)`),
      '--disallowedTools', ...DISALLOWED_TOOLS,
      '--strict-mcp-config', '--mcp-config', MCP_NONE,
      '--setting-sources', 'user',
      '--append-system-prompt', SYSTEM_PROMPT,
    ]
  }

  async function send(raw: unknown): Promise<AgentSendResult> {
    const parsed = parseSend(raw)
    if (!parsed.ok) return parsed
    if (current) return { ok: false, error: BUSY }
    const state = await ready()
    if (disposed) return { ok: false, error: '会话已经关掉了。' }
    if (!state.available || !state.executable) return { ok: false, error: state.reason }
    if (current) return { ok: false, error: BUSY }
    const input = parsed.value
    const attached = (input.attachments ?? []).map(file => ({ path: file, name: path.basename(file), action: 'attach' as const }))
    const user: AgentMessage = { id: randomUUID(), role: 'user', text: input.text, at: new Date().toISOString(), ...(attached.length ? { artifacts: attached } : {}) }
    let child: ChildProcess
    try { child = spawn(state.executable, cliArgs(input), { cwd: workspace, env: childEnv(state.executable), stdio: ['pipe', 'pipe', 'pipe'] }) }
    catch (error) { return { ok: false, error: `会话进程没起来：${describe(error)}` } }
    const turn: Turn = {
      id: randomUUID(), sessionId: input.sessionId, model: input.model, child, user, userPersisted: false,
      text: '', blocks: [], artifacts: [], artifactPaths: new Set(), buffer: '', decoder: new StringDecoder('utf8'),
      stderr: '', spawnError: '', concluded: false, interrupted: false, loggedUnparseable: false, killTimer: null,
    }
    if (turn.sessionId) { turn.userPersisted = true; appendMessage(turn.sessionId, user) }
    current = turn
    children.add(child)
    child.stdout?.on('data', chunk => handleChunk(turn, chunk))
    child.stderr?.on('data', chunk => { turn.stderr = (turn.stderr + String(chunk)).slice(-STDERR_KEEP) })
    child.stdin?.on('error', error => log(`[agent] 提示词没写进去：${describe(error)}`))
    child.on('error', error => { turn.spawnError = describe(error) })
    whenDone(child, () => finalize(turn))
    broadcast({ type: 'turn-start', turnId: turn.id, sessionId: turn.sessionId, model: turn.model })
    try { child.stdin?.write(promptFor(input)); child.stdin?.end() }
    catch (error) { log(`[agent] 提示词没写进去：${describe(error)}`) }
    return { ok: true, turnId: turn.id, sessionId: turn.sessionId }
  }

  function interrupt(): CompanionActionResult {
    const turn = current
    if (!turn) return { ok: false, error: IDLE }
    turn.interrupted = true
    try { turn.child.kill('SIGTERM') } catch (error) { log(`[agent] 停不下来：${describe(error)}`) }
    if (!turn.concluded && !turn.killTimer) {
      turn.killTimer = setTimeout(() => { turn.killTimer = null; try { turn.child.kill('SIGKILL') } catch { /* 已经退出了。 */ } }, KILL_GRACE_MS)
      turn.killTimer.unref?.()
    }
    return { ok: true }
  }

  /** 只放行真的在工作目录里的文件：按 realpath 比，软链接和 `..` 都绕不过去。 */
  function validateInside(paths: unknown, outside: string): string[] {
    if (!Array.isArray(paths) || paths.length === 0) throw new Error(outside)
    let root: string
    try { root = realpathSync(workspace) } catch { throw new Error(outside) }
    for (const candidate of paths) {
      if (typeof candidate !== 'string' || !path.isAbsolute(candidate) || candidate.includes('\0')) throw new Error(outside)
      if (!isWithin(workspace, path.resolve(candidate))) throw new Error(outside)
      let real: string
      try { real = realpathSync(candidate) } catch { throw new Error(MISSING) }
      if (!isWithin(root, real)) throw new Error(outside)
    }
    return paths as string[]
  }
  const validateShelf = (paths: unknown) => validateInside(paths, OUTSIDE)

  /** 提示词：正文，加一段附件清单（都已经在工作目录里，Claude 直接 Read 就行）。 */
  function promptFor(input: AgentSendInput): string {
    if (!input.attachments?.length) return input.text
    return `${input.text}\n\n附件（已在工作目录里，可直接读取）：\n${input.attachments.map(file => `- ${file}`).join('\n')}`
  }

  /** 同名文件不覆盖：报价.pdf、报价-2.pdf、报价-3.pdf。 */
  function freeName(directory: string, name: string): string {
    const extension = path.extname(name)
    const stem = name.slice(0, name.length - extension.length) || name
    for (let n = 1; n < 1000; n++) {
      const candidate = path.join(directory, n === 1 ? name : `${stem}-${n}${extension}`)
      if (!existsSync(candidate)) return candidate
    }
    throw new Error('同名文件太多了。')
  }

  /** 把拖进来的文件复制进 workspace/附件/：只收普通文件，不收文件夹；原文件留在原处。 */
  function attach(raw: unknown): CompanionActionResult & { attachments?: AgentArtifact[] } {
    if (!Array.isArray(raw) || raw.length === 0) return { ok: false, error: ATTACH_INVALID }
    if (raw.length > ATTACH_MAX_FILES) return { ok: false, error: ATTACH_TOO_MANY }
    const directory = path.join(workspace, ATTACH_DIR)
    const attachments: AgentArtifact[] = []
    try {
      mkdirSync(directory, { recursive: true, mode: 0o700 })
      for (const candidate of raw) {
        if (typeof candidate !== 'string' || !path.isAbsolute(candidate) || candidate.includes('\0')) throw new Error(ATTACH_INVALID)
        let info: ReturnType<typeof statSync>
        try { info = statSync(candidate) } catch { throw new Error(ATTACH_MISSING) }
        if (!info.isFile()) throw new Error(ATTACH_NOT_FILE)
        if (info.size > ATTACH_MAX_BYTES) throw new Error(ATTACH_TOO_BIG)
        const destination = freeName(directory, path.basename(candidate))
        copyFileSync(candidate, destination, fsConstants.COPYFILE_EXCL)
        attachments.push({ path: destination, name: path.basename(destination), action: 'attach' })
      }
    } catch (error) {
      // 复制到一半出错：已经复制进来的仍然算带上了，别让用户重拖。
      return { ok: false, error: describe(error), ...(attachments.length ? { attachments } : {}) }
    }
    return { ok: true, attachments }
  }

  function markShelved(paths: string[]) {
    const shelved = new Set<string>()
    for (const candidate of paths) {
      shelved.add(path.resolve(candidate))
      try { shelved.add(realpathSync(candidate)) } catch { /* 刚刚还在；没了就只按原路径比。 */ }
    }
    for (const session of loadIndex()) {
      const messages = loadTranscript(session.id)
      let changed = false
      for (const message of messages) for (const artifact of message.artifacts ?? []) {
        if (!artifact.shelved && shelved.has(artifact.path)) { artifact.shelved = true; changed = true }
      }
      if (changed) saveTranscript(session.id, messages)
    }
  }

  async function shelve(paths: unknown): Promise<CompanionMutationResult> {
    const valid = validateShelf(paths)
    const result = await options.shelve(valid)
    if (result.ok) markShelved(valid)
    return result
  }

  // ── IPC ─────────────────────────────────────────────────────────────────
  function handle(channel: string, run: (args: unknown[]) => unknown) {
    const name = `agent:${channel}`
    // 先验身份再做事，而且要同步抛：不是岛的窗口连一个 Promise 都拿不到。
    ipcMain.handle(name, (event, ...args: unknown[]) => { options.authorize(event); return run(args) })
    handlers.push(name)
  }
  handle('status', () => status())
  handle('sessions', () => sessions())
  handle('transcript', ([sessionId]) => transcript(sessionId))
  handle('send', ([input]) => send(input))
  handle('interrupt', () => interrupt())
  handle('attach', ([paths]) => attach(paths))
  handle('shelve', ([paths]) => shelve(paths))

  return {
    dispose() {
      if (disposed) return
      disposed = true
      for (const channel of handlers) ipcMain.removeHandler(channel)
      handlers.length = 0
      if (current) { current.interrupted = true }
      for (const child of children) {
        try { child.kill('SIGTERM') } catch { /* 已经退出了。 */ }
        const timer = setTimeout(() => { try { child.kill('SIGKILL') } catch { /* 已经退出了。 */ } }, KILL_GRACE_MS)
        timer.unref?.()
      }
      children.clear()
      current = null
    },
  }
}
