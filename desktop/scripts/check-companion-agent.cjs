/** The island's agent bridge with the Claude Code process replaced by a scripted fake. Never spawns a real CLI. */
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const Module = require('node:module')
const { mkdtempSync, mkdirSync, writeFileSync, readFileSync, chmodSync, symlinkSync, rmSync, existsSync } = require('node:fs')
const { tmpdir } = require('node:os')
const path = require('node:path')
const { Writable } = require('node:stream')
const { test, after } = require('node:test')

const temporary = mkdtempSync(path.join(tmpdir(), 'memoket-companion-agent-'))
after(() => rmSync(temporary, { recursive: true, force: true }))
const handlers = new Map()
const electron = { ipcMain: { handle: (channel, callback) => handlers.set(channel, callback), removeHandler: channel => handlers.delete(channel) } }
const originalLoad = Module._load
Module._load = function (id, parent, isMain) { return id === 'electron' ? electron : originalLoad.call(this, id, parent, isMain) }
const { createAgentBridge } = require('../dist/agent.js')
Module._load = originalLoad

const executable = path.join(temporary, 'bin', 'claude')
mkdirSync(path.dirname(executable))
writeFileSync(executable, '#!/bin/sh\necho fixture\n')
chmodSync(executable, 0o755)
const VERSION = '2.1.278 (Claude Code)'
const SESSION = '11111111-2222-4333-8444-555555555555'
const init = (sessionId, model = 'claude-sonnet-4-5') => ({ type: 'system', subtype: 'init', cwd: '/workspace', session_id: sessionId, model, permissionMode: 'acceptEdits', tools: ['Read', 'Write'] })
const delta = (text) => ({ type: 'stream_event', event: { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text } }, session_id: SESSION })
const success = (result, extra = {}) => ({ type: 'result', subtype: 'success', is_error: false, result, session_id: SESSION, total_cost_usd: 0.0123, duration_ms: 74, num_turns: 1, permission_denials: [], ...extra })
const tick = () => new Promise(resolve => setImmediate(resolve))

class FakeChild extends EventEmitter {
  constructor(command, args, options) {
    super()
    this.command = command
    this.args = args
    this.options = options
    this.stdout = new EventEmitter()
    this.stderr = new EventEmitter()
    this.written = []
    this.ended = false
    this.stdin = new Writable({ write: (chunk, _encoding, callback) => { this.written.push(chunk.toString()); callback() } })
    this.stdin.on('finish', () => { this.ended = true })
    this.signals = []
    this.exited = false
  }
  kill(signal = 'SIGTERM') { this.signals.push(signal); this.exit(null, signal); return true }
  /** One JSON line from the CLI; `split` delivers it in two chunks to exercise the line buffer. */
  line(record, split = false) {
    const text = `${JSON.stringify(record)}\n`
    if (!split) { this.stdout.emit('data', Buffer.from(text)); return }
    const bytes = Buffer.from(text)
    const cut = Math.floor(bytes.length / 2)
    this.stdout.emit('data', bytes.subarray(0, cut))
    this.stdout.emit('data', bytes.subarray(cut))
  }
  exit(code, signal = null) {
    if (this.exited) return
    this.exited = true
    this.emit('exit', code, signal)
    this.emit('close', code, signal)
  }
}

function fixture(t, overrides = {}) {
  const directory = mkdtempSync(path.join(temporary, 'agent-'))
  const events = []
  const logs = []
  const shelved = []
  const children = []
  const contents = { destroyed: false, isDestroyed() { return this.destroyed }, send(channel, event) { assert.equal(channel, 'agent:event'); events.push(event) } }
  const spawn = (command, args, options) => {
    const child = new FakeChild(command, args, options)
    children.push(child)
    if (args[0] === '--version') setImmediate(() => { child.stdout.emit('data', Buffer.from(`${VERSION}\n`)); child.exit(0) })
    return child
  }
  handlers.clear()
  const bridge = createAgentBridge({
    directory,
    authorize: event => { if (!event || event.sender !== contents) throw new Error('不允许从这个窗口调用会话。') },
    shelve: async paths => { shelved.push(paths); return { ok: true, state: { surface: 'top', expanded: true, panel: 'clipboard', items: [], storageError: '' } } },
    targets: () => [contents],
    log: line => logs.push(line),
    executable,
    spawn,
    env: { PATH: '', MEMOKET_CLAUDE_BIN: '', CLAUDECODE: '1', CLAUDE_CODE_ENTRYPOINT: 'cli' },
    home: path.join(directory, 'home'),
    locations: [],
    ...overrides,
  })
  t.after(() => bridge.dispose())
  const invoke = (name, ...args) => Promise.resolve().then(() => handlers.get(`agent:${name}`)({ sender: contents }, ...args))
  const turnChild = () => children.filter(child => child.args[0] === '-p').at(-1)
  return { bridge, directory, workspace: path.join(directory, 'workspace'), events, logs, shelved, children, contents, invoke, turnChild }
}

test('without any executable the bridge reports unavailable with a plain reason and never spawns', async t => {
  const { invoke, children, workspace } = fixture(t, { executable: undefined })
  const status = await invoke('status')
  assert.equal(status.available, false)
  assert.equal(status.loggedIn, null)
  assert.equal(status.version, '')
  assert.match(status.reason, /没找到 Claude Code/)
  assert.equal(status.cwd, workspace)
  assert.ok(existsSync(workspace))
  assert.deepEqual(status.models.map(model => model.id), ['', 'opus', 'sonnet', 'haiku'])
  assert.equal(status.models[0].label, '默认')
  assert.equal(status.runningTurnId, null)
  assert.deepEqual(children, [])
  const send = await invoke('send', { sessionId: null, text: '你好', model: '' })
  assert.equal(send.ok, false)
  assert.match(send.error, /没找到 Claude Code/)
})

test('a discovered executable is asked for its version exactly once', async t => {
  const { invoke, children } = fixture(t)
  const first = await invoke('status')
  const second = await invoke('status')
  assert.equal(first.available, true)
  assert.equal(first.version, VERSION)
  assert.equal(first.reason, '')
  assert.equal(second.version, VERSION)
  assert.equal(children.length, 1)
  assert.equal(children[0].command, executable)
  assert.deepEqual(children[0].args, ['--version'])
})

test('MEMOKET_CLAUDE_BIN and PATH entries are searched before the fixed locations', async t => {
  const other = path.join(temporary, 'env-bin', 'claude')
  mkdirSync(path.dirname(other), { recursive: true })
  writeFileSync(other, '#!/bin/sh\n')
  const viaEnv = fixture(t, { executable: undefined, env: { PATH: '', MEMOKET_CLAUDE_BIN: other } })
  assert.equal((await viaEnv.invoke('status')).available, true)
  assert.equal(viaEnv.children[0].command, other)
  const viaPath = fixture(t, { executable: undefined, env: { PATH: `/nonexistent-fixture${path.delimiter}${path.dirname(other)}`, MEMOKET_CLAUDE_BIN: '' } })
  assert.equal((await viaPath.invoke('status')).available, true)
  assert.equal(viaPath.children[0].command, other)
  const viaLocation = fixture(t, { executable: undefined, env: { PATH: '', MEMOKET_CLAUDE_BIN: '' }, locations: ['/nonexistent-fixture/claude', other] })
  assert.equal((await viaLocation.invoke('status')).available, true)
  assert.equal(viaLocation.children[0].command, other)
})

test('a full turn streams deltas, activity and artifacts, then persists the session and resumes it', async t => {
  const f = fixture(t)
  const result = await f.invoke('send', { sessionId: null, text: '  写一份周报草稿，主题是本周的桌面浮窗改版，顺便列出下周要做的三件事，再附上一段给团队的话，语气轻松一点  ', model: 'sonnet' })
  assert.equal(result.ok, true)
  assert.match(result.turnId, /^[0-9a-f-]{36}$/)
  assert.equal(result.sessionId, null)
  assert.deepEqual(f.events, [{ type: 'turn-start', turnId: result.turnId, sessionId: null, model: 'sonnet' }])
  const child = f.turnChild()
  assert.equal(child.command, executable)
  assert.equal(child.written.join(''), '  写一份周报草稿，主题是本周的桌面浮窗改版，顺便列出下周要做的三件事，再附上一段给团队的话，语气轻松一点  ')
  await tick()
  assert.equal(child.ended, true)
  const args = child.args
  const after = flag => args[args.indexOf(flag) + 1]
  assert.equal(args[0], '-p')
  assert.equal(after('--output-format'), 'stream-json')
  assert.equal(after('--input-format'), 'text')
  assert.ok(args.includes('--verbose'))
  assert.ok(args.includes('--include-partial-messages'))
  assert.equal(after('--model'), 'sonnet')
  assert.ok(!args.includes('--resume'))
  assert.equal(after('--permission-mode'), 'acceptEdits')
  const scoped = tool => `${tool}(//${f.workspace.replace(/^\/+/, '')}/**)`
  assert.deepEqual(args.slice(args.indexOf('--allowedTools') + 1, args.indexOf('--disallowedTools')), ['Glob', 'Grep', scoped('Read'), scoped('Write'), scoped('Edit'), scoped('MultiEdit')], 'read/write tools are scoped to the workspace; only the search tools are open')
  assert.deepEqual(args.slice(args.indexOf('--disallowedTools') + 1, args.indexOf('--strict-mcp-config')), ['Bash', 'WebFetch', 'WebSearch', 'NotebookEdit', 'Task', 'Agent', 'Workflow'])
  assert.equal(after('--mcp-config'), '{"mcpServers":{}}', 'no MCP connectors from the user config')
  assert.equal(after('--setting-sources'), 'user')
  assert.match(after('--append-system-prompt'), /MEMOKET NOTE 桌面浮窗/)
  assert.equal(args.indexOf('--append-system-prompt'), args.length - 2)
  assert.equal(child.options.cwd, f.workspace)
  assert.equal(child.options.env.CLAUDECODE, undefined)
  assert.equal(child.options.env.CLAUDE_CODE_ENTRYPOINT, undefined)
  assert.ok(child.options.env.PATH.split(path.delimiter).includes(path.dirname(executable)))
  assert.equal((await f.invoke('status')).runningTurnId, result.turnId)
  assert.deepEqual(await f.invoke('sessions'), [])

  child.line(init(SESSION))
  assert.deepEqual(f.events.at(-1), { type: 'session', turnId: result.turnId, sessionId: SESSION, model: 'claude-sonnet-4-5' })
  const [session] = await f.invoke('sessions')
  assert.equal(session.id, SESSION)
  assert.equal(session.title, '写一份周报草稿，主题是本周的桌面浮窗改版，顺便列出下周要做的三件事，再附上一段给')
  assert.equal(session.title.length, 40)
  assert.equal(session.model, 'claude-sonnet-4-5')
  assert.equal(session.turns, 0)
  assert.equal((await f.invoke('transcript', SESSION)).length, 1)

  child.line({ type: 'stream_event', event: { type: 'message_start', message: { role: 'assistant', content: [] } }, session_id: SESSION })
  child.line({ type: 'stream_event', event: { type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } }, session_id: SESSION })
  child.line(delta('周报'))
  child.line(delta('写好了。'), true)
  child.line({ type: 'stream_event', event: { type: 'message_delta', delta: { stop_reason: 'tool_use' } }, session_id: SESSION })
  assert.deepEqual(f.events.filter(event => event.type === 'delta').map(event => event.text), ['周报', '写好了。'])

  const file = path.join(f.workspace, '周报.md')
  const outside = path.join(f.directory, 'outside.md')
  child.line({ type: 'assistant', message: { role: 'assistant', content: [
    { type: 'text', text: '周报写好了。' },
    { type: 'tool_use', id: 'toolu_1', name: 'Write', input: { file_path: file, content: '# 周报' } },
    { type: 'tool_use', id: 'toolu_2', name: 'Edit', input: { file_path: file, old_string: 'a', new_string: 'b' } },
    { type: 'tool_use', id: 'toolu_3', name: 'Write', input: { file_path: outside, content: 'nope' } },
    { type: 'tool_use', id: 'toolu_4', name: 'Read', input: { file_path: file } },
    { type: 'tool_use', id: 'toolu_5', name: 'Grep', input: { pattern: 'x' } },
  ] }, session_id: SESSION })
  child.line({ type: 'user', message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: 'toolu_1', content: 'ok' }] }, session_id: SESSION })
  const activity = f.events.filter(event => event.type === 'activity')
  assert.deepEqual(activity.map(event => [event.tool, event.label, event.path]), [
    ['Write', '正在写 周报.md', file], ['Edit', '正在写 周报.md', file], ['Write', '正在写 outside.md', outside], ['Read', '正在读 周报.md', file], ['Grep', '正在找…', undefined],
  ])
  const artifacts = f.events.filter(event => event.type === 'artifact')
  assert.deepEqual(artifacts, [{ type: 'artifact', turnId: result.turnId, artifact: { path: file, name: '周报.md', action: 'write' } }])

  child.line(success('周报写好了。'))
  const end = f.events.at(-1)
  assert.equal(end.type, 'turn-end')
  assert.equal(end.turnId, result.turnId)
  assert.equal(end.sessionId, SESSION)
  assert.equal(end.message.role, 'assistant')
  assert.equal(end.message.text, '周报写好了。')
  assert.deepEqual(end.message.artifacts, [{ path: file, name: '周报.md', action: 'write' }])
  assert.equal(end.message.costUsd, 0.0123)
  assert.equal(end.message.error, undefined)
  child.exit(1)
  assert.equal(f.events.at(-1).type, 'turn-end')
  const status = await f.invoke('status')
  assert.equal(status.runningTurnId, null)
  assert.equal(status.loggedIn, true)
  assert.equal(status.reason, '')
  const [updated] = await f.invoke('sessions')
  assert.equal(updated.turns, 1)
  assert.equal(updated.model, 'claude-sonnet-4-5')
  const transcript = await f.invoke('transcript', SESSION)
  assert.deepEqual(transcript.map(message => message.role), ['user', 'assistant'])
  assert.equal(transcript[0].text, '  写一份周报草稿，主题是本周的桌面浮窗改版，顺便列出下周要做的三件事，再附上一段给团队的话，语气轻松一点  ')
  assert.equal(transcript[1].text, '周报写好了。')
  assert.deepEqual(JSON.parse(readFileSync(path.join(f.directory, 'sessions.json'), 'utf8')).sessions.map(item => item.id), [SESSION])
  assert.equal(JSON.parse(readFileSync(path.join(f.directory, 'sessions', `${SESSION}.json`), 'utf8')).messages.length, 2)
  assert.deepEqual(await f.invoke('transcript', 'not a session id'), [])

  const second = await f.invoke('send', { sessionId: SESSION, text: '再加一段', model: '' })
  assert.equal(second.ok, true)
  assert.equal(second.sessionId, SESSION)
  const resumed = f.turnChild()
  assert.notEqual(resumed, child)
  assert.equal(resumed.args[resumed.args.indexOf('--resume') + 1], SESSION)
  assert.ok(!resumed.args.includes('--model'))
  assert.equal((await f.invoke('transcript', SESSION)).length, 3)
  resumed.line(init(SESSION))
  resumed.line({ type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text: '加好了。' }] }, session_id: SESSION })
  resumed.line(success('加好了。'))
  resumed.exit(0)
  assert.equal(f.events.at(-1).type, 'turn-end')
  assert.equal(f.events.at(-1).message.text, '加好了。')
  assert.equal(f.events.at(-1).message.artifacts, undefined)
  assert.equal((await f.invoke('sessions'))[0].turns, 2)
  assert.equal((await f.invoke('transcript', SESSION)).length, 4)
})

test('text between tool calls is separated and delta-less turns fall back to text blocks, then the result', async t => {
  const f = fixture(t)
  const first = await f.invoke('send', { sessionId: null, text: '两段', model: '' })
  let child = f.turnChild()
  child.line(init(SESSION))
  child.line({ type: 'stream_event', event: { type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } } })
  child.line(delta('先看看。'))
  child.line({ type: 'stream_event', event: { type: 'content_block_start', index: 1, content_block: { type: 'tool_use', id: 'toolu_1', name: 'Read', input: {} } } })
  child.line({ type: 'stream_event', event: { type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } } })
  child.line(delta('看完了。'))
  child.line(success('ignored'))
  child.exit(0)
  assert.equal(f.events.at(-1).type, 'turn-end')
  assert.equal(f.events.at(-1).turnId, first.turnId)
  assert.equal(f.events.at(-1).message.text, '先看看。\n\n看完了。')
  await f.invoke('send', { sessionId: SESSION, text: '只有整块', model: '' })
  child = f.turnChild()
  child.line(init(SESSION))
  child.line({ type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text: '整块回答' }] } })
  child.line(success('result text'))
  child.exit(0)
  assert.equal(f.events.at(-1).message.text, '整块回答')
  await f.invoke('send', { sessionId: SESSION, text: '只有结果', model: '' })
  child = f.turnChild()
  child.line(init(SESSION))
  child.line(success('只剩 result'))
  child.exit(0)
  assert.equal(f.events.at(-1).message.text, '只剩 result')
})

test('input validation rejects empty, oversized and malformed sends before spawning', async t => {
  const f = fixture(t)
  for (const [input, pattern] of [
    [null, /无效/], ['hi', /无效/],
    [{ sessionId: null, text: '   ', model: '' }, /先写点什么/],
    [{ sessionId: null, text: 'x'.repeat(20001), model: '' }, /20000/],
    [{ sessionId: null, text: 'hi', model: 'gpt-5' }, /模型/],
    [{ sessionId: null, text: 'hi', model: 'claude-opus-4-1; rm -rf /' }, /模型/],
    [{ sessionId: 'not-a-session-id!', text: 'hi', model: '' }, /会话/],
    [{ sessionId: undefined, text: 'hi', model: '' }, /会话/],
  ]) {
    const result = await f.invoke('send', input)
    assert.equal(result.ok, false)
    assert.match(result.error, pattern)
  }
  assert.deepEqual(f.children, [])
  const full = await f.invoke('send', { sessionId: null, text: 'x'.repeat(20000), model: 'claude-opus-4-1-20250805' })
  assert.equal(full.ok, true)
  assert.equal(f.turnChild().args[f.turnChild().args.indexOf('--model') + 1], 'claude-opus-4-1-20250805')
})

test('a not-logged-in result ends the turn with notLoggedIn and status reports it', async t => {
  const f = fixture(t)
  const result = await f.invoke('send', { sessionId: null, text: '你好', model: '' })
  const child = f.turnChild()
  child.line({ type: 'result', subtype: 'success', is_error: true, result: 'Not logged in · Please run /login', session_id: SESSION, total_cost_usd: 0, duration_ms: 3, num_turns: 0 })
  child.exit(1)
  assert.deepEqual(f.events.at(-1), { type: 'turn-error', turnId: result.turnId, sessionId: null, message: 'Not logged in · Please run /login', notLoggedIn: true })
  const status = await f.invoke('status')
  assert.equal(status.loggedIn, false)
  assert.equal(status.available, true)
  assert.match(status.reason, /登录/)
  assert.equal(status.runningTurnId, null)
  assert.deepEqual(await f.invoke('sessions'), [])
})

test('model errors on a known session keep the partial reply with the error attached', async t => {
  const f = fixture(t)
  const result = await f.invoke('send', { sessionId: null, text: '你好', model: '' })
  const child = f.turnChild()
  child.line(init(SESSION))
  child.line(delta('开了个头'))
  child.line({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'API Error: 529 overloaded', session_id: SESSION })
  child.exit(1)
  assert.deepEqual(f.events.at(-1), { type: 'turn-error', turnId: result.turnId, sessionId: SESSION, message: 'API Error: 529 overloaded', notLoggedIn: false })
  const transcript = await f.invoke('transcript', SESSION)
  assert.equal(transcript.length, 2)
  assert.equal(transcript[1].text, '开了个头')
  assert.equal(transcript[1].error, 'API Error: 529 overloaded')
  assert.equal((await f.invoke('sessions'))[0].turns, 0)
  assert.equal((await f.invoke('status')).loggedIn, null)
})

test('only one turn runs at a time and interrupt ends it as stopped with the partial text kept', async t => {
  const f = fixture(t)
  assert.deepEqual(await f.invoke('interrupt'), { ok: false, error: '没有正在进行的会话' })
  const result = await f.invoke('send', { sessionId: null, text: '慢慢写', model: 'haiku' })
  const busy = await f.invoke('send', { sessionId: null, text: '再来一条', model: '' })
  assert.deepEqual(busy, { ok: false, error: '上一轮还在进行，先停止它。' })
  assert.equal(f.children.filter(child => child.args[0] === '-p').length, 1)
  const child = f.turnChild()
  child.line(init(SESSION, 'claude-haiku-4-5-20251001'))
  child.line(delta('写到一半'))
  assert.deepEqual(await f.invoke('interrupt'), { ok: true })
  assert.deepEqual(child.signals, ['SIGTERM'])
  assert.deepEqual(f.events.at(-1), { type: 'turn-error', turnId: result.turnId, sessionId: SESSION, message: '已停止', notLoggedIn: undefined })
  assert.equal((await f.invoke('status')).runningTurnId, null)
  const transcript = await f.invoke('transcript', SESSION)
  assert.deepEqual(transcript.map(message => [message.role, message.text, message.error]), [['user', '慢慢写', undefined], ['assistant', '写到一半', '已停止']])
  const next = await f.invoke('send', { sessionId: SESSION, text: '继续', model: '' })
  assert.equal(next.ok, true)
})

test('a process that exits without a result reports its stderr tail without ANSI, or a plain message', async t => {
  const f = fixture(t)
  const first = await f.invoke('send', { sessionId: null, text: '你好', model: '' })
  let child = f.turnChild()
  child.line(init(SESSION))
  child.stderr.emit('data', Buffer.from('\u001b[31mError: \u001b[0m'))
  child.stderr.emit('data', Buffer.from('quota exceeded for today\u001b[0m\n'))
  child.exit(1)
  assert.deepEqual(f.events.at(-1), { type: 'turn-error', turnId: first.turnId, sessionId: SESSION, message: 'Error: quota exceeded for today', notLoggedIn: undefined })
  const second = await f.invoke('send', { sessionId: SESSION, text: '再试', model: '' })
  child = f.turnChild()
  child.exit(0)
  assert.deepEqual(f.events.at(-1), { type: 'turn-error', turnId: second.turnId, sessionId: SESSION, message: '会话进程退出了，没有返回结果。', notLoggedIn: undefined })
  const third = await f.invoke('send', { sessionId: SESSION, text: '崩', model: '' })
  child = f.turnChild()
  child.stderr.emit('data', Buffer.from(`${'x'.repeat(500)}TAIL`))
  child.exit(null, 'SIGSEGV')
  assert.equal(f.events.at(-1).turnId, third.turnId)
  assert.equal(f.events.at(-1).message.length, 300)
  assert.ok(f.events.at(-1).message.endsWith('TAIL'))
  const fourth = await f.invoke('send', { sessionId: SESSION, text: '起不来', model: '' })
  child = f.turnChild()
  child.emit('error', new Error('spawn ENOENT'))
  child.exit(-2)
  assert.equal(f.events.at(-1).turnId, fourth.turnId)
  assert.match(f.events.at(-1).message, /没起来.*ENOENT/)
  assert.equal((await f.invoke('status')).runningTurnId, null)
})

test('unparseable lines are skipped and logged once per turn, a trailing partial line still counts', async t => {
  const f = fixture(t)
  await f.invoke('send', { sessionId: null, text: '你好', model: '' })
  const child = f.turnChild()
  child.line(init(SESSION))
  child.stdout.emit('data', Buffer.from('not json\nstill not json\n'))
  child.stdout.emit('data', Buffer.from(JSON.stringify(success('尾巴没换行'))))
  child.exit(0)
  assert.equal(f.events.at(-1).type, 'turn-end')
  assert.equal(f.events.at(-1).message.text, '尾巴没换行')
  assert.equal(f.logs.filter(line => /读不懂/.test(line)).length, 1)
})

test('corrupt index and transcript files read as empty, log once and are overwritten atomically', async t => {
  const directory = mkdtempSync(path.join(temporary, 'corrupt-'))
  mkdirSync(path.join(directory, 'sessions'), { recursive: true })
  writeFileSync(path.join(directory, 'sessions.json'), '{ not json')
  writeFileSync(path.join(directory, 'sessions', `${SESSION}.json`), JSON.stringify({ v: 1, messages: 'nope' }))
  const f = fixture(t, { directory })
  assert.deepEqual(await f.invoke('sessions'), [])
  assert.deepEqual(await f.invoke('sessions'), [])
  assert.deepEqual(await f.invoke('transcript', SESSION), [])
  assert.equal(f.logs.filter(line => /sessions\.json/.test(line)).length, 1)
  assert.equal(f.logs.filter(line => new RegExp(`${SESSION}\\.json`).test(line)).length, 1)
  await f.invoke('send', { sessionId: SESSION, text: '继续', model: '' })
  const child = f.turnChild()
  child.line(init(SESSION))
  child.line(success('好'))
  child.exit(0)
  assert.equal(f.events.at(-1).type, 'turn-end')
  assert.equal((await f.invoke('sessions')).length, 1)
  assert.equal((await f.invoke('transcript', SESSION)).length, 2)
  assert.ok(!require('node:fs').readdirSync(directory).some(name => name.endsWith('.tmp')))
})

test('sessions are listed newest first and capped at 30', async t => {
  const directory = mkdtempSync(path.join(temporary, 'many-'))
  const sessions = Array.from({ length: 35 }, (_, index) => ({ id: `0000000${index.toString(16).padStart(1, '0')}-0000-4000-8000-${index.toString().padStart(12, '0')}`, title: `会话 ${index}`, model: '', createdAt: '2026-09-01T00:00:00.000Z', updatedAt: `2026-09-${String(1 + (index % 28)).padStart(2, '0')}T00:00:${String(index).padStart(2, '0')}.000Z`, turns: 1 }))
  mkdirSync(directory, { recursive: true })
  writeFileSync(path.join(directory, 'sessions.json'), JSON.stringify({ v: 1, sessions }))
  const f = fixture(t, { directory })
  const listed = await f.invoke('sessions')
  assert.equal(listed.length, 30)
  for (let index = 1; index < listed.length; index++) assert.ok(listed[index - 1].updatedAt >= listed[index].updatedAt)
})

test('shelving only accepts existing files inside the workspace and marks them shelved in the transcript', async t => {
  const f = fixture(t)
  await f.invoke('send', { sessionId: null, text: '产出', model: '' })
  const child = f.turnChild()
  const file = path.join(f.workspace, 'draft.md')
  const nested = path.join(f.workspace, 'sub', 'notes.md')
  mkdirSync(path.dirname(nested), { recursive: true })
  writeFileSync(file, 'draft')
  writeFileSync(nested, 'notes')
  child.line(init(SESSION))
  child.line({ type: 'assistant', message: { role: 'assistant', content: [
    { type: 'tool_use', id: 'toolu_1', name: 'Write', input: { file_path: file, content: 'draft' } },
    { type: 'tool_use', id: 'toolu_2', name: 'Write', input: { file_path: nested, content: 'notes' } },
  ] } })
  child.line(success('写了两个文件'))
  child.exit(0)
  const outside = path.join(f.directory, 'outside.md')
  writeFileSync(outside, 'outside')
  const link = path.join(f.workspace, 'link.md')
  symlinkSync(outside, link)
  for (const bad of [
    [outside], [path.join(f.workspace, '..', 'outside.md')], [link], [file, outside], ['draft.md'], [], 'draft.md', [`${file}\0`],
  ]) await assert.rejects(() => f.invoke('shelve', bad), /只能把会话工作目录里的文件放进暂存箱/, JSON.stringify(bad))
  await assert.rejects(() => f.invoke('shelve', [path.join(f.workspace, 'gone.md')]), /已经不在了/)
  assert.deepEqual(f.shelved, [])
  const result = await f.invoke('shelve', [file, nested])
  assert.equal(result.ok, true)
  assert.deepEqual(f.shelved, [[file, nested]])
  const transcript = await f.invoke('transcript', SESSION)
  assert.deepEqual(transcript[1].artifacts.map(artifact => [artifact.name, artifact.shelved]), [['draft.md', true], ['notes.md', true]])
})

test('a failed shelve leaves artifacts unmarked and a missing top window surfaces its error', async t => {
  const f = fixture(t, { shelve: async () => ({ ok: false, error: '暂存架已满，请先移除不再需要的内容。', state: {} }) })
  await f.invoke('send', { sessionId: null, text: '产出', model: '' })
  const child = f.turnChild()
  const file = path.join(f.workspace, 'draft.md')
  writeFileSync(file, 'draft')
  child.line(init(SESSION))
  child.line({ type: 'assistant', message: { role: 'assistant', content: [{ type: 'tool_use', id: 'toolu_1', name: 'Write', input: { file_path: file, content: 'draft' } }] } })
  child.line(success('写了'))
  child.exit(0)
  const result = await f.invoke('shelve', [file])
  assert.equal(result.ok, false)
  assert.equal((await f.invoke('transcript', SESSION))[1].artifacts[0].shelved, undefined)
  const g = fixture(t, { shelve: async () => { throw new Error('桌面浮条尚未就绪。') } })
  const other = path.join(g.workspace, 'draft.md')
  writeFileSync(other, 'draft')
  await assert.rejects(() => g.invoke('shelve', [other]), /桌面浮条尚未就绪/)
})

test('every handler authorizes the sender synchronously and dispose removes them and kills the child', async t => {
  const f = fixture(t)
  const names = ['agent:status', 'agent:sessions', 'agent:transcript', 'agent:send', 'agent:interrupt', 'agent:attach', 'agent:shelve']
  assert.deepEqual([...handlers.keys()].sort(), names.slice().sort())
  for (const name of names) {
    assert.throws(() => handlers.get(name)({ sender: {} }), /不允许从这个窗口调用会话/, name)
    assert.throws(() => handlers.get(name)(undefined), /不允许从这个窗口调用会话/, name)
  }
  await f.invoke('send', { sessionId: null, text: '你好', model: '' })
  const child = f.turnChild()
  f.contents.destroyed = true
  child.line(init(SESSION))
  assert.equal(f.events.filter(event => event.type === 'session').length, 0)
  f.contents.destroyed = false
  f.bridge.dispose()
  assert.deepEqual([...handlers.keys()], [])
  assert.deepEqual(child.signals, ['SIGTERM'])
  assert.equal(f.events.filter(event => event.type === 'turn-error').length, 0)
  f.bridge.dispose()
})


test('attach copies dropped files into workspace/附件 without overwriting, and refuses folders, missing files and too many', async t => {
  const { invoke, workspace, directory } = fixture(t)
  const source = path.join(directory, 'drop')
  mkdirSync(source)
  writeFileSync(path.join(source, '报价.pdf'), 'quote')
  writeFileSync(path.join(source, 'again.txt'), 'second')
  const first = await invoke('attach', [path.join(source, '报价.pdf')])
  assert.equal(first.ok, true)
  assert.deepEqual(first.attachments.map(a => [a.name, a.action]), [['报价.pdf', 'attach']])
  assert.equal(first.attachments[0].path, path.join(workspace, '附件', '报价.pdf'))
  assert.equal(readFileSync(first.attachments[0].path, 'utf8'), 'quote')
  const second = await invoke('attach', [path.join(source, '报价.pdf')])
  assert.equal(second.attachments[0].name, '报价-2.pdf', 'a same-named file gets a numbered copy, the first copy is kept')
  assert.equal(readFileSync(path.join(workspace, '附件', '报价.pdf'), 'utf8'), 'quote')
  const folder = await invoke('attach', [source])
  assert.equal(folder.ok, false)
  assert.match(folder.error, /只能带上文件/)
  const missing = await invoke('attach', [path.join(source, 'nope.txt')])
  assert.equal(missing.ok, false)
  assert.match(missing.error, /不在了/)
  const relative = await invoke('attach', ['again.txt'])
  assert.equal(relative.ok, false)
  const many = await invoke('attach', Array.from({ length: 21 }, () => path.join(source, 'again.txt')))
  assert.equal(many.ok, false)
  assert.match(many.error, /最多/)
  const partial = await invoke('attach', [path.join(source, 'again.txt'), path.join(source, 'nope.txt')])
  assert.equal(partial.ok, false)
  assert.equal(partial.attachments.length, 1, 'what was copied before the failure is still reported as attached')
})

test('a send with attachments lists them after the prompt and keeps them on the user message; outside paths are refused', async t => {
  const { invoke, workspace, directory, turnChild, events } = fixture(t)
  const source = path.join(directory, 'drop')
  mkdirSync(source)
  writeFileSync(path.join(source, 'notes.md'), 'hi')
  const attached = await invoke('attach', [path.join(source, 'notes.md')])
  const file = attached.attachments[0].path
  const outside = await invoke('send', { sessionId: null, text: '看看', model: '', attachments: [path.join(source, 'notes.md')] })
  assert.equal(outside.ok, false)
  assert.match(outside.error, /不在会话工作目录/)
  const sent = await invoke('send', { sessionId: null, text: '这份笔记讲了什么', model: '', attachments: [file] })
  assert.equal(sent.ok, true)
  const child = turnChild()
  await tick()
  assert.equal(child.written.join(''), `这份笔记讲了什么\n\n附件（已在工作目录里，可直接读取）：\n- ${file}`)
  child.line(init(SESSION))
  child.line(delta('讲了两件事。'))
  child.line(success('讲了两件事。'))
  child.exit(0)
  await tick(); await tick()
  assert.equal(events.at(-1).type, 'turn-end')
  const transcript = await invoke('transcript', SESSION)
  assert.equal(transcript[0].role, 'user')
  assert.equal(transcript[0].text, '这份笔记讲了什么', 'the stored question is what the user typed, not the prompt with the file list')
  assert.deepEqual(transcript[0].artifacts.map(a => [a.name, a.action]), [['notes.md', 'attach']])
  assert.ok(file.startsWith(path.join(workspace, '附件')))
})

test('an API error line is not mistaken for reply text', async t => {
  const { invoke, turnChild, events } = fixture(t)
  await invoke('send', { sessionId: null, text: '你好', model: '' })
  const child = turnChild()
  await tick()
  child.line(init(SESSION))
  child.line({ type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text: 'API Error: 529 overloaded' }] }, session_id: SESSION, is_api_error_message: true })
  child.line({ type: 'result', subtype: 'success', is_error: true, result: 'API Error: 529 overloaded', session_id: SESSION, total_cost_usd: 0, duration_ms: 5, num_turns: 1, permission_denials: [] })
  child.exit(1)
  await tick(); await tick()
  assert.equal(events.at(-1).type, 'turn-error')
  const transcript = await invoke('transcript', SESSION)
  const reply = transcript.find(message => message.role === 'assistant')
  assert.equal(reply.text, '', 'the error text lives in error, not in the reply body')
  assert.match(reply.error, /529/)
})
