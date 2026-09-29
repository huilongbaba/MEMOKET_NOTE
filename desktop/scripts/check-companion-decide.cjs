/** 「拿主意」热键的主进程一侧：globalShortcut / 剪贴板 / osascript / 辅助功能权限全换成假的。一次 ⌘C 都不发。 */
const assert = require('node:assert/strict')
const Module = require('node:module')
const { test } = require('node:test')

const handlers = new Map()
const untouchable = name => new Proxy({}, { get() { throw new Error(`real electron.${name} must not be used`) } })
const electron = {
  ipcMain: { handle: (channel, callback) => handlers.set(channel, callback), removeHandler: channel => handlers.delete(channel) },
  clipboard: untouchable('clipboard'),
  globalShortcut: untouchable('globalShortcut'),
  systemPreferences: untouchable('systemPreferences'),
}
const originalLoad = Module._load
Module._load = function (id, parent, isMain) { return id === 'electron' ? electron : originalLoad.call(this, id, parent, isMain) }
const { createDecideHotkey, DEFAULT_ACCELERATOR, ACCELERATOR_LADDER, MAX_SELECTION_CHARS } = require('../dist/decide.js')
Module._load = originalLoad

const PREVIOUS = '之前剪贴板里的东西'
const COPIED = '要不要接这个 offer，还是继续谈'
const AT = '2026-09-28T10:00:00.000Z'
const DATA_URL_PREFIX = 'data:image/png;base64,'
const tick = () => new Promise(resolve => setImmediate(resolve))

/** 像 Electron 的 NativeImage：getSize / resize / toPNG。resize 记下要的宽度，交回一张同样假的、更窄的图；
 *  `png` 可以是 Buffer，也可以是按宽度给字节的函数（模拟「缩小后才够小」）。calls 在原图和缩过的图之间共享。 */
function fakeImage({ width = 2400, height = 1200, png = Buffer.from('fake png bytes'), calls = { resized: [], encoded: [] } } = {}) {
  return {
    calls, isEmpty: () => false,
    getSize: () => ({ width, height }),
    resize: ({ width: target }) => { calls.resized.push(target); return fakeImage({ width: target, height: Math.round(height * target / width), png, calls }) },
    toPNG: () => { calls.encoded.push(width); return typeof png === 'function' ? png(width) : png },
  }
}
const decodeDataUrl = url => Buffer.from(url.slice(DATA_URL_PREFIX.length), 'base64')

function fixture(t, overrides = {}) {
  handlers.clear()
  const shortcuts = new Map()
  const globalShortcut = {
    register(accelerator, callback) { if (overrides.register === false || overrides.taken?.includes(accelerator)) return false; shortcuts.set(accelerator, callback); return true },
    unregister(accelerator) { shortcuts.delete(accelerator) },
  }
  let clip = overrides.previous ?? PREVIOUS
  const writes = []
  const restores = []
  // 剪贴板里可能不只是文字：图片、Finder 里的文件、富文本；假的把这些都记着，放回去时要一模一样。
  const board = { html: overrides.html ?? '', image: overrides.image ?? null, files: overrides.files ?? null }
  const blob = bytes => ({ size: bytes.length, arrayBuffer: async () => bytes, text: async () => bytes.toString() })
  // 像 Electron 44 的 W3C 剪贴板：read() 给一组 { types, getType → Blob }，write() 只收一组 ClipboardItem（这里由 createItem 拼成 { parts }），
  // 别的形状一律拒绝——旧版那套 readImage / write({ text }) 在真机上根本不存在。
  const entries = () => {
    const parts = {}
    if (clip) parts['text/plain'] = blob(Buffer.from(clip))
    if (board.html) parts['text/html'] = blob(Buffer.from(board.html))
    if (board.image) parts['image/png'] = blob(Buffer.from('png bytes on the board'))
    if (board.files) parts['text/uri-list'] = blob(Buffer.from(board.files))
    if (overrides.raw) parts[overrides.raw] = blob(Buffer.from('native bytes'))
    if (overrides.tiff) parts['electron application/osclipboard;format="public.tiff"'] = blob(Buffer.alloc(16, 1))
    const types = Object.keys(parts)
    return types.length ? [{ types, async getType(type) { if (!(type in parts)) throw new Error(`no ${type}`); return parts[type] } }] : []
  }
  const rich = {
    read: async () => entries(),
    has: async type => type.includes('file-url') && Boolean(board.files),
    async write(items) {
      if (!Array.isArray(items)) throw new Error('clipboard.write expects an array of ClipboardItem')
      if (overrides.writeFails) throw new Error('pasteboard busy')
      const parts = Object.assign({}, ...items.map(item => item.parts))
      const value = async key => (typeof parts[key] === 'string' ? parts[key] : parts[key].text())
      clip = parts['text/plain'] ? await value('text/plain') : ''
      board.html = parts['text/html'] ? await value('text/html') : ''
      board.image = parts['image/png'] ? overrides.image ?? null : null
      board.files = parts['text/uri-list'] ? await value('text/uri-list') : null
      const summary = {}
      if (clip) summary.text = clip
      if (board.html) summary.html = board.html
      if (board.image) summary.image = board.image
      if (board.files) summary.files = board.files
      for (const key of Object.keys(parts)) if (key.startsWith('electron application/osclipboard')) summary[key] = true
      restores.push(summary)
    },
    clear: () => { restores.push('clear'); clip = ''; board.html = ''; board.image = null; board.files = null },
  }
  // readText/writeText 是 Promise 的；`syncClipboard` 那条用同步的假的证明两种都收。
  const clipboard = overrides.syncClipboard
    ? { readText: () => clip, writeText(text) { writes.push(text); clip = text }, ...rich }
    : { readText: async () => clip, async writeText(text) { writes.push(text); clip = text }, ...rich }
  const isSentinel = text => typeof text === 'string' && text.includes('memoket-decide')
  const calls = []
  let releaseFront = null
  const exec = async (file, args, timeoutMs) => {
    calls.push({ file, args, timeoutMs })
    assert.equal(file, 'osascript')
    assert.equal(args[0], '-e')
    const script = args[1]
    if (!script.includes('keystroke')) return { stdout: 'Safari\n' }   // 截图那条只问前台是谁
    assert.ok(script.includes('frontmost') && script.includes('keystroke "c" using command down'), 'one script asks who is in front, then presses ⌘C')
    if (overrides.holdFront) await new Promise(resolve => { releaseFront = resolve })
    if (overrides.copyFails) throw new Error(overrides.copyError || 'osascript is not allowed to send keystrokes')
    if (overrides.copied !== undefined) clip = overrides.copied   // 没选中就什么都不改，剪贴板里还是哨兵
    if (overrides.copiedFiles) board.files = 'file:///Users/me/报告.pdf'   // Finder 里 ⌘C 的是文件：纯文字只是文件名
    return { stdout: overrides.frontFails ? '\n' : 'Safari\n' }   // 前台问不到：脚本里 try 过了，名字是空串
  }
  const shown = []
  const sent = []
  const pendings = []
  const pulsed = []
  const lives = []
  const captures = []
  const contents = { destroyed: false, isDestroyed() { return this.destroyed }, send(channel, payload) { if (channel === 'decide:pending') pendings.push(payload); else sent.push([channel, payload]) } }
  const deadCalls = []
  const dead = { isDestroyed: () => true, send() { deadCalls.push(1); throw new Error('sent to a destroyed webContents') } }
  const logs = []
  const hotkey = createDecideHotkey({
    companion: {
      show: (surface, panel) => shown.push([surface, panel]),
      setLive: live => lives.push(live),
      contents: () => [contents, dead],
      assertIsland: event => { if (!event || event.sender !== contents) throw new Error('不允许从这个窗口读取热键状态。') },
    },
    log: line => logs.push(line),
    exec,
    clipboard,
    createItem: parts => ({ parts }),
    decodeImage: () => overrides.image ?? { isEmpty: () => true },
    globalShortcut,
    isTrustedAccessibility: () => overrides.accessibility ?? true,
    now: () => new Date(AT),
    copyDelayMs: 1,
    cursor: () => ({ x: 100, y: 200 }),
    cue: { pulse: async at => { pulsed.push(at) } },
    capture: async file => { captures.push(file); return !overrides.cancelCapture },
    readFile: async () => Buffer.from('png file bytes'),
    ...(overrides.accelerator ? { accelerator: overrides.accelerator } : {}),
  })
  t.after(() => hotkey.dispose())
  const invoke = (channel, sender = contents) => Promise.resolve().then(() => handlers.get(channel)({ sender }))
  return { hotkey, shortcuts, clipboard: () => clip, writes, restores, board, isSentinel, deadCalls, calls, shown, sent, pendings, pulsed, lives, captures, logs, contents, invoke, releaseFront: () => releaseFront?.() }
}

test('registration succeeds by default and status carries the accelerator without a reason', t => {
  const { hotkey, shortcuts } = fixture(t)
  assert.deepEqual(hotkey.status(), { accelerator: DEFAULT_ACCELERATOR, registered: true, tap: false, reason: '', accessibility: true })
  assert.equal(DEFAULT_ACCELERATOR, 'Alt+D', '两个键；⌃⌥Space 是 macOS 切输入法的，⌥Space 这台机器上被占')
  assert.deepEqual(ACCELERATOR_LADDER, ['Alt+D', 'Alt+J', 'Control+Shift+Space'])
  assert.deepEqual([...shortcuts.keys()], [DEFAULT_ACCELERATOR])
  assert.equal(typeof shortcuts.get(DEFAULT_ACCELERATOR), 'function')
})

test('a taken default steps down the ladder, and the status names the key that actually works', t => {
  const { hotkey, shortcuts } = fixture(t, { taken: ['Alt+D'] })
  assert.equal(hotkey.status().registered, true)
  assert.equal(hotkey.status().accelerator, 'Alt+J')
  assert.deepEqual([...shortcuts.keys()], ['Alt+J'])
})

test('when every rung is taken the status says so and still names the default', t => {
  const { hotkey, shortcuts } = fixture(t, { taken: ['Alt+D', 'Alt+J', 'Control+Shift+Space'] })
  assert.equal(hotkey.status().registered, false)
  assert.equal(hotkey.status().accelerator, 'Alt+D')
  assert.match(hotkey.status().reason, /被其他应用占用/)
  assert.equal(shortcuts.size, 0)
})

test('a custom accelerator is the one registered', t => {
  const { hotkey, shortcuts } = fixture(t, { accelerator: 'Control+Alt+D' })
  assert.equal(hotkey.status().accelerator, 'Control+Alt+D')
  assert.deepEqual([...shortcuts.keys()], ['Control+Alt+D'])
})

test('a taken accelerator reports registered=false with the fixed reason', t => {
  const { hotkey, shortcuts, logs } = fixture(t, { register: false })
  const status = hotkey.status()
  assert.equal(status.registered, false)
  assert.equal(status.reason, '快捷键已被其他应用占用，或系统不允许注册。')
  assert.equal(shortcuts.size, 0)
  assert.ok(logs.some(line => line.includes('不可用')))
})

test('a register() that throws is reported the same way instead of crashing startup', t => {
  handlers.clear()
  const hotkey = createDecideHotkey({
    companion: { show() {}, contents: () => [], assertIsland() {} },
    log() {},
    exec: async () => ({ stdout: '' }),
    clipboard: { readText: () => '', writeText() {} },
    globalShortcut: { register() { throw new Error('bad accelerator') }, unregister() {} },
    isTrustedAccessibility: () => true,
  })
  t.after(() => hotkey.dispose())
  assert.equal(hotkey.status().registered, false)
  assert.equal(hotkey.status().reason, '快捷键已被其他应用占用，或系统不允许注册。')
})

test('without accessibility permission the reason says where to grant it, even when registered', t => {
  const { hotkey } = fixture(t, { accessibility: false })
  const status = hotkey.status()
  assert.equal(status.registered, true)
  assert.equal(status.accessibility, false)
  assert.match(status.reason, /辅助功能权限/)
  assert.match(status.reason, /系统设置 › 隐私与安全性 › 辅助功能/)
})

test('both problems at once: registration reason first, then the accessibility one', t => {
  const { hotkey } = fixture(t, { register: false, accessibility: false })
  const { reason } = hotkey.status()
  assert.ok(reason.startsWith('快捷键已被其他应用占用'))
  assert.ok(reason.includes('辅助功能权限'))
})

test('an accessibility probe that throws leaves accessibility null and adds no reason', t => {
  const { hotkey } = fixture(t)
  const probe = createDecideHotkey({
    companion: { show() {}, contents: () => [], assertIsland() {} },
    log() {},
    exec: async () => ({ stdout: '' }),
    clipboard: { readText: () => '', writeText() {} },
    globalShortcut: { register: () => true, unregister() {} },
    isTrustedAccessibility: () => { throw new Error('not on this platform') },
  })
  t.after(() => probe.dispose())
  assert.equal(probe.status().accessibility, null)
  assert.equal(probe.status().reason, '')
  assert.equal(hotkey.status().accessibility, true)
})

test('trigger with a changed clipboard shows the decide stage, broadcasts the selection and restores the clipboard', async t => {
  const { hotkey, shown, sent, writes, restores, isSentinel, clipboard, calls, logs } = fixture(t, { copied: `  ${COPIED}\n` })
  await hotkey.trigger()
  assert.deepEqual(sent, [['decide:selection', { text: COPIED, source: 'Safari', at: AT, origin: 'selection' }]])
  assert.equal(clipboard(), PREVIOUS, 'the previous clipboard text is back')
  assert.equal(writes.length, 1)
  assert.ok(isSentinel(writes[0]), 'writeText only ever carries the sentinel')
  assert.deepEqual(restores, [{ text: PREVIOUS }], 'the previous clipboard is put back once, as a whole')
  assert.equal(calls.length, 1, 'one osascript: who is in front, then ⌘C')
  assert.equal(calls[0].timeoutMs, 3000)
  assert.ok(logs.every(line => !line.includes(COPIED)), 'the selection never reaches the log')
  assert.ok(logs.some(line => line.includes('Safari') && line.includes(`读到选区 ${COPIED.length} 字`)))
})

test('a press tells the island it is reading and pulses at the cursor before anything is read; the island is never expanded from here', async t => {
  const { hotkey, shown, pendings, pulsed, sent } = fixture(t, { copied: COPIED })
  await hotkey.trigger()
  assert.deepEqual(shown, [], 'the island opens itself once the answer is ready')
  assert.deepEqual(pendings, [{ at: AT }])
  assert.deepEqual(pulsed, [{ x: 100, y: 200 }])
  assert.equal(sent.length, 1)
})

test('the collapsed window is widened at the press and narrowed again only when nothing was read', async t => {
  const read = fixture(t, { copied: COPIED })
  await read.hotkey.trigger()
  assert.deepEqual(read.lives, [true], 'read something: the renderer settles the width later')
  const empty = fixture(t, { previous: '' })
  await empty.hotkey.trigger()
  assert.deepEqual(empty.lives, [true, false])
})

test('an app-native clipboard format survives the grab; only image derivatives are dropped', async t => {
  const raw = 'electron application/osclipboard;format="com.apple.iWork.TSPNativeData"'
  const { hotkey, restores } = fixture(t, { raw, tiff: true, image: fakeImage({ width: 800, height: 600 }), copied: COPIED })
  await hotkey.trigger()
  assert.equal(restores.length, 1)
  assert.equal(restores[0][raw], true, 'the native format goes back')
  assert.equal(restores[0]['electron application/osclipboard;format="public.tiff"'], undefined, 'the TIFF derivative is not carried')
  assert.ok(restores[0].image, 'one PNG still goes back')
})

test('⌘C on a file in Finder is not passed off as a selection: the file name never reaches the backend', async t => {
  const { hotkey, sent, restores, logs } = fixture(t, { copied: '报告.pdf', copiedFiles: true })
  await hotkey.trigger()
  assert.deepEqual(sent, [['decide:selection', { text: '', source: 'Safari', at: AT, error: 'empty' }]])
  assert.deepEqual(restores, [{ text: PREVIOUS }], 'the pre-sentinel clipboard goes back')
  assert.ok(logs.some(line => line.includes('剪贴板里是文件')))
})

test('the pulse and the pending note happen even when nothing is read: they answer the key press, not the content', async t => {
  const { hotkey, pendings, pulsed } = fixture(t, { previous: '' })
  await hotkey.trigger()
  assert.equal(pendings.length, 1)
  assert.equal(pulsed.length, 1)
})

test('a double tap frames a piece of the screen and sends it in as a screenshot image, no clipboard touched', async t => {
  const image = fakeImage({ width: 800, height: 600 })
  const { hotkey, sent, pendings, lives, captures, writes, restores, logs } = fixture(t, { image })
  await hotkey.screenshot()
  assert.equal(captures.length, 1)
  assert.ok(captures[0].endsWith('.png'))
  assert.deepEqual(pendings, [{ at: AT, phase: 'screenshot' }])
  assert.deepEqual(lives, [true], 'the pill grows for the thumbnail; the renderer settles the width later')
  assert.equal(sent.length, 1)
  const [, payload] = sent[0]
  assert.deepEqual({ ...payload, image: undefined }, { text: '', source: 'Safari', at: AT, origin: 'screenshot', image: undefined })
  assert.ok(payload.image.startsWith(DATA_URL_PREFIX))
  assert.deepEqual(writes, [], 'no sentinel: the clipboard is never involved')
  assert.deepEqual(restores, [])
  assert.ok(logs.some(line => line.includes('截图：Safari')))
})

test('Esc in the crosshair cancels quietly: pending then cancelled, the window narrows, nothing is sent', async t => {
  const { hotkey, sent, pendings, lives } = fixture(t, { cancelCapture: true })
  await hotkey.screenshot()
  assert.deepEqual(pendings.map(event => event.phase), ['screenshot', 'cancelled'])
  assert.deepEqual(lives, [true, false])
  assert.deepEqual(sent, [])
})

test('a synchronous clipboard fake works the same way', async t => {
  const { hotkey, sent, restores, clipboard } = fixture(t, { copied: COPIED, syncClipboard: true })
  await hotkey.trigger()
  assert.equal(sent[0][1].text, COPIED)
  assert.deepEqual(restores, [{ text: PREVIOUS }])
  assert.equal(clipboard(), PREVIOUS)
})

test('the registered shortcut runs trigger', async t => {
  const { shortcuts, sent, shown } = fixture(t, { copied: COPIED })
  shortcuts.get(DEFAULT_ACCELERATOR)()
  for (let i = 0; i < 20 && sent.length === 0; i++) { await tick(); await new Promise(resolve => setTimeout(resolve, 2)) }
  assert.equal(sent.length, 1)
  assert.equal(sent[0][1].text, COPIED)
})

test('an unchanged clipboard means nothing was selected: the text already on the clipboard is used instead, origin clipboard', async t => {
  const { hotkey, shown, sent, writes, restores, isSentinel, clipboard, logs } = fixture(t)
  await hotkey.trigger()
  assert.deepEqual(sent, [['decide:selection', { text: PREVIOUS, source: 'Safari', at: AT, origin: 'clipboard' }]])
  assert.equal(writes.length, 1)
  assert.ok(isSentinel(writes[0]), 'the sentinel still went in first: that is how "nothing selected" is detected')
  assert.deepEqual(restores, [{ text: PREVIOUS }], 'the sentinel is taken back out')
  assert.equal(clipboard(), PREVIOUS)
  assert.ok(logs.some(line => line.includes(`剪贴板文字 ${PREVIOUS.length} 字`)), 'the log says where the text came from')
  assert.ok(logs.every(line => !line.includes(PREVIOUS)), 'clipboard text never reaches the log either')
})

test('clipboard text is trimmed and capped exactly like a selection', async t => {
  const { hotkey, sent } = fixture(t, { previous: `\n  ${'字'.repeat(7000)}  ` })
  await hotkey.trigger()
  assert.equal(sent[0][1].origin, 'clipboard')
  assert.equal(sent[0][1].text, '字'.repeat(MAX_SELECTION_CHARS))
})

test('whitespace-only clipboard text counts as nothing on the clipboard', async t => {
  const { hotkey, sent, restores } = fixture(t, { previous: '  \n\t ' })
  await hotkey.trigger()
  assert.deepEqual(sent, [['decide:selection', { text: '', source: 'Safari', at: AT, error: 'empty' }]])
  assert.deepEqual(restores, [{ text: '  \n\t ' }], 'the whitespace still goes back untouched')
})

test('nothing selected and nothing on the clipboard: error empty, clipboard left empty', async t => {
  const { hotkey, shown, sent, restores, clipboard, logs } = fixture(t, { previous: '' })
  await hotkey.trigger()
  assert.deepEqual(sent, [['decide:selection', { text: '', source: 'Safari', at: AT, error: 'empty' }]])
  assert.deepEqual(restores, ['clear'], 'the sentinel is taken back out')
  assert.equal(clipboard(), '')
  assert.ok(logs.some(line => line.includes('没读到内容（empty）')))
})

test('nothing selected and an image on the clipboard: a PNG data URL scaled to 1600 wide, origin clipboard, original image restored', async t => {
  const png = Buffer.from('fake png bytes')
  const image = fakeImage({ width: 2400, height: 1200, png })
  const { hotkey, shown, sent, restores, board, clipboard, logs } = fixture(t, { previous: '', image })
  await hotkey.trigger()
  assert.equal(sent.length, 1)
  const [channel, payload] = sent[0]
  assert.equal(channel, 'decide:selection')
  assert.deepEqual({ ...payload, image: undefined }, { text: '', source: 'Safari', at: AT, origin: 'clipboard', image: undefined })
  assert.ok(payload.image.startsWith(DATA_URL_PREFIX), 'the image travels as a PNG data URL')
  assert.deepEqual(decodeDataUrl(payload.image), png, 'the bytes are what toPNG produced')
  assert.deepEqual(image.calls.resized, [1600], 'a 2400px image is scaled to 1600 wide, once')
  assert.deepEqual(image.calls.encoded, [1600], 'only the scaled image is encoded')
  assert.deepEqual(restores, [{ image }], 'the original image, not the scaled copy, goes back')
  assert.equal(board.image, image)
  assert.equal(clipboard(), '')
  assert.ok(logs.some(line => line.includes('剪贴板图片')), 'the log says an image was used')
  assert.ok(logs.every(line => !line.includes('base64') && !line.includes(png.toString('base64'))), 'image data never reaches the log')
})

test('an image already narrower than 1600 is encoded as is, without resizing', async t => {
  const image = fakeImage({ width: 800, height: 600 })
  const { hotkey, sent } = fixture(t, { previous: '', image })
  await hotkey.trigger()
  assert.ok(sent[0][1].image.startsWith(DATA_URL_PREFIX))
  assert.equal(sent[0][1].origin, 'clipboard')
  assert.deepEqual(image.calls.resized, [])
  assert.deepEqual(image.calls.encoded, [800])
})

test('an image whose PNG is too large at 1600 is retried at 1200 then 900; still too large means error empty', async t => {
  // 5 MB 的 PNG 编成 base64 是 6.67 M 字符，每一档都超过 6 MB。
  const image = fakeImage({ width: 2400, height: 1200, png: Buffer.alloc(5_000_000, 1) })
  const { hotkey, sent, restores, board, logs } = fixture(t, { previous: '', image })
  await hotkey.trigger()
  assert.deepEqual(sent, [['decide:selection', { text: '', source: 'Safari', at: AT, error: 'empty' }]])
  assert.deepEqual(image.calls.resized, [1600, 1200, 900], 'each narrower width is tried in turn')
  assert.deepEqual(restores, [{ image }], 'the clipboard still gets its image back')
  assert.equal(board.image, image)
  assert.ok(logs.some(line => line.includes('剪贴板图片太大') && line.includes('900px')), 'one honest line about the size')
  assert.ok(logs.every(line => !line.includes('base64')), 'no image data in the log')
})

test('an image that only fits once narrower is delivered at that width', async t => {
  // 1600 那档还超 6 MB，1200 那档就够小了：交出去的是 1200 的那份，900 那档不用再试。
  const png = width => (width > 1200 ? Buffer.alloc(5_000_000, 1) : Buffer.from(`png at ${width}`))
  const image = fakeImage({ width: 2400, height: 1200, png })
  const { hotkey, sent } = fixture(t, { previous: '', image })
  await hotkey.trigger()
  assert.deepEqual(image.calls.resized, [1600, 1200])
  assert.deepEqual(image.calls.encoded, [1600, 1200])
  assert.equal(decodeDataUrl(sent[0][1].image).toString(), 'png at 1200')
})

test('an image too large that is already narrower than a retry width is not upscaled to it', async t => {
  const image = fakeImage({ width: 1000, height: 3000, png: Buffer.alloc(5_000_000, 1) })
  const { hotkey, sent } = fixture(t, { previous: '', image })
  await hotkey.trigger()
  assert.equal(sent[0][1].error, 'empty')
  assert.deepEqual(image.calls.resized, [900], 'only 900 is narrower than 1000; 1600 and 1200 would be upscales')
  assert.deepEqual(image.calls.encoded, [1000, 900])
})

test('a toPNG that throws is treated as no image, never a crash, and the clipboard still goes back', async t => {
  const image = { ...fakeImage({ width: 800, height: 600 }), toPNG: () => { throw new Error('bitmap gone') } }
  const { hotkey, sent, restores, logs } = fixture(t, { previous: '', image })
  await hotkey.trigger()
  assert.deepEqual(sent, [['decide:selection', { text: '', source: 'Safari', at: AT, error: 'empty' }]])
  assert.deepEqual(restores, [{ image }])
  assert.ok(logs.some(line => line.includes('剪贴板图片编不出来') && line.includes('bitmap gone')))
})

test('a clipboard image without toPNG (a minimal fake) is simply not usable', async t => {
  const image = { isEmpty: () => false }
  const { hotkey, sent, restores } = fixture(t, { previous: '', image })
  await hotkey.trigger()
  assert.equal(sent[0][1].error, 'empty')
  assert.deepEqual(restores, [{ image }])
})

test('a selection still wins over an image on the clipboard: no image in the payload, nothing encoded', async t => {
  const image = fakeImage()
  const { hotkey, sent, restores, board } = fixture(t, { previous: '', image, copied: COPIED })
  await hotkey.trigger()
  assert.deepEqual(sent, [['decide:selection', { text: COPIED, source: 'Safari', at: AT, origin: 'selection' }]])
  assert.deepEqual(image.calls.resized, [])
  assert.deepEqual(image.calls.encoded, [])
  assert.deepEqual(restores, [{ image }])
  assert.equal(board.image, image)
})

test('clipboard text beats a clipboard image when both are there and nothing is selected', async t => {
  const image = fakeImage()
  const { hotkey, sent } = fixture(t, { image })
  await hotkey.trigger()
  assert.deepEqual(sent, [['decide:selection', { text: PREVIOUS, source: 'Safari', at: AT, origin: 'clipboard' }]])
  assert.deepEqual(image.calls.encoded, [])
})

test('files copied in Finder are not used yet: error empty, files go back, the file name is not passed off as text', async t => {
  const files = 'file:///Users/me/报告.pdf'
  const { hotkey, sent, restores, board, logs } = fixture(t, { previous: '报告.pdf', files })
  await hotkey.trigger()
  assert.deepEqual(sent, [['decide:selection', { text: '', source: 'Safari', at: AT, error: 'empty' }]])
  assert.deepEqual(restores, [{ text: '报告.pdf', files }])
  assert.equal(board.files, files)
  assert.ok(logs.some(line => line.includes('剪贴板里是文件')))
})

test('a whitespace-only selection is empty too, but the clipboard is still restored', async t => {
  const { hotkey, sent, restores } = fixture(t, { copied: '   \n\t ' })
  await hotkey.trigger()
  assert.equal(sent[0][1].error, 'empty')
  assert.equal(sent[0][1].text, '')
  assert.deepEqual(restores, [{ text: PREVIOUS }])
})

test('osascript failing without accessibility permission reports error accessibility', async t => {
  const { hotkey, sent, restores, shown } = fixture(t, { copyFails: true, accessibility: false })
  await hotkey.trigger()
  assert.equal(sent.length, 1)
  assert.equal(sent[0][1].error, 'accessibility')
  assert.equal(sent[0][1].text, '')
  assert.deepEqual(restores, [{ text: PREVIOUS }], 'even a failed copy puts the clipboard back')
})

test('osascript failing with accessibility granted is just an empty selection', async t => {
  const { hotkey, sent } = fixture(t, { copyFails: true, accessibility: true })
  await hotkey.trigger()
  assert.equal(sent[0][1].error, 'empty')
})

test('a frontmost lookup that fails leaves source empty and still delivers the selection', async t => {
  const { hotkey, sent } = fixture(t, { frontFails: true, copied: COPIED })
  await hotkey.trigger()
  assert.deepEqual(sent, [['decide:selection', { text: COPIED, source: '', at: AT, origin: 'selection' }]])
})

test('long selections are trimmed then capped at 6000 characters', async t => {
  const { hotkey, sent } = fixture(t, { copied: `\n  ${'字'.repeat(7000)}  ` })
  await hotkey.trigger()
  assert.equal(MAX_SELECTION_CHARS, 6000)
  assert.equal(sent[0][1].text.length, 6000)
  assert.equal(sent[0][1].text, '字'.repeat(6000))
})

test('a trigger while one is in flight is ignored, not queued', async t => {
  const { hotkey, sent, shown, calls, releaseFront } = fixture(t, { holdFront: true, copied: COPIED })
  const first = hotkey.trigger()
  await tick()
  const second = hotkey.trigger()
  await tick()
  assert.equal(calls.length, 1, 'the second press started nothing')
  releaseFront()
  await Promise.all([first, second])
  assert.equal(calls.length, 1, 'exactly one ⌘C was sent')
  assert.equal(sent.length, 1)
})

test('a destroyed webContents is skipped and the live one still gets the broadcast', async t => {
  const { hotkey, sent, contents } = fixture(t, { copied: COPIED })
  await hotkey.trigger()
  assert.equal(sent.length, 1)
  contents.destroyed = true
  await hotkey.trigger()
  assert.equal(sent.length, 1, 'nothing sent to a destroyed target')
})

test('a destroyed target is never even asked: isDestroyed is consulted before send', async t => {
  const { hotkey, deadCalls, logs } = fixture(t, { copied: COPIED })
  await hotkey.trigger()
  assert.equal(deadCalls.length, 0)
  assert.ok(logs.every(line => !line.includes('广播失败')))
})

test('an image on the clipboard survives the grab: the whole snapshot goes back, not an empty string', async t => {
  const image = { bytes: 'PNG', isEmpty: () => false }
  const { hotkey, sent, restores, board, clipboard } = fixture(t, { previous: '', image, copied: COPIED })
  await hotkey.trigger()
  assert.equal(sent[0][1].text, COPIED)
  assert.equal(sent[0][1].origin, 'selection')
  assert.equal(sent[0][1].image, undefined, 'a real selection never carries the clipboard image along')
  assert.deepEqual(restores, [{ image }])
  assert.equal(board.image, image)
  assert.equal(clipboard(), '')
})

test('files copied in Finder go back as files', async t => {
  const files = 'file:///Users/me/a.pdf'
  const { hotkey, restores, board } = fixture(t, { previous: '', files, copied: COPIED })
  await hotkey.trigger()
  assert.deepEqual(restores, [{ files }])
  assert.equal(board.files, files)
})

test('an empty clipboard is restored as empty, not as the selection', async t => {
  const { hotkey, restores, clipboard } = fixture(t, { previous: '', copied: COPIED })
  await hotkey.trigger()
  assert.deepEqual(restores, ['clear'])
  assert.equal(clipboard(), '')
})

test('a write that rejects still puts the text back: the sentinel never stays on the clipboard', async t => {
  const { hotkey, clipboard, isSentinel, sent, logs } = fixture(t, { copied: COPIED, writeFails: true })
  await hotkey.trigger()
  assert.equal(sent[0][1].text, COPIED)
  assert.equal(clipboard(), PREVIOUS)
  assert.ok(!isSentinel(clipboard()))
  assert.ok(logs.some(line => line.includes('没能整份放回去')))
})

test('a denied Automation permission reads as the permission error even when accessibility is granted', async t => {
  const { hotkey, sent } = fixture(t, { copyFails: true, copyError: 'execution error: Not authorized to send Apple events to System Events. (-1743)', accessibility: true })
  await hotkey.trigger()
  assert.equal(sent[0][1].error, 'accessibility')
})

test('decide:status authorizes the sender: the island gets status, anyone else gets the throw', async t => {
  const { hotkey, invoke } = fixture(t, { accessibility: false })
  assert.ok(handlers.has('decide:status'))
  const status = await invoke('decide:status')
  assert.deepEqual(status, hotkey.status())
  assert.equal(status.accessibility, false)
  await assert.rejects(invoke('decide:status', { other: true }), /不允许从这个窗口/)
})

test('dispose unregisters the shortcut, removes the handler and makes trigger a no-op', async t => {
  const { hotkey, shortcuts, sent, shown } = fixture(t, { copied: COPIED })
  hotkey.dispose()
  assert.equal(shortcuts.size, 0)
  assert.equal(handlers.has('decide:status'), false)
  assert.equal(hotkey.status().registered, false)
  await hotkey.trigger()
  assert.deepEqual(shown, [])
  assert.deepEqual(sent, [])
  hotkey.dispose()
})
