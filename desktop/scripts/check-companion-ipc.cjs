/** Actual controller/IPC code with native OS boundaries replaced. Never opens an OS window. */
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const Module = require('node:module')
const { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, unlinkSync, rmSync } = require('node:fs')
const { randomUUID } = require('node:crypto')
const { tmpdir } = require('node:os')
const path = require('node:path')
const { test, after } = require('node:test')

const temporary = mkdtempSync(path.join(tmpdir(), 'memoket-companion-ipc-'))
after(() => rmSync(temporary, { recursive: true, force: true }))
let appDirectory
const handlers = new Map()
const nativeCalls = { open: [], reveal: [], drag: [], copy: [], clipboardRead: [], fileIcon: [], nativeImages: [], previews: [] }
let previewOptions
let previewDisposed = false
class PreviewQueue {
  constructor(options) { previewOptions = options; previewDisposed = false }
  request(item, force = false) { nativeCalls.previews.push({ item, force }); return Promise.resolve() }
  dispose() { previewDisposed = true }
}
const windowAdapter = { listWindowCandidates: async () => ({ ok: true, candidates: [] }), recallWindow: async () => ({ ok: true }) }
const primary = { id: 1, workArea: { x: 0, y: 28, width: 1440, height: 872 } }
const fakeScreen = Object.assign(new EventEmitter(), { getPrimaryDisplay: () => primary, getAllDisplays: () => [primary], getDisplayNearestPoint: () => primary, getCursorScreenPoint: () => ({ x: 20, y: 40 }) })
const image = { isEmpty: () => false, getSize: () => ({ width: 64, height: 64 }), resize() { return this }, toDataURL: () => 'data:image/png;base64,aGVsbG8=', toPNG: () => Buffer.from('PNG fixture') }
class Window extends EventEmitter {
  static all = []
  constructor(options) {
    super()
    this.options = options
    this.destroyed = false
    this.focusCount = 0
    this.focused = false
    this.visible = false
    this.blurCount = 0
    this.hideCount = 0
    this.passiveCount = 0
    this.bounds = null
    this.sent = []
    this.timeline = []
    this.webContents = Object.assign(new EventEmitter(), {
      mainFrame: { url: '' }, isDestroyed: () => this.destroyed,
      send: (channel, state) => { this.sent.push({ channel, state }); this.timeline.push({ kind: 'state', state }) },
      setWindowOpenHandler: callback => { this.popupHandler = callback },
      startDrag: payload => nativeCalls.drag.push(payload),
    })
    Window.all.push(this)
  }
  isDestroyed() { return this.destroyed }
  setAlwaysOnTop() {}
  setVisibleOnAllWorkspaces() {}
  setBounds(bounds) { this.bounds = bounds; this.timeline.push({ kind: 'bounds', bounds }) }
  getBounds() { return { ...this.bounds } }
  loadURL(url) { this.webContents.mainFrame.url = url; return Promise.resolve() }
  showInactive() { this.passiveCount++; this.visible = true }
  show() { this.visible = true }
  hide() { this.hideCount++; this.visible = false }
  isVisible() { return this.visible }
  focus() { this.focusCount++; this.focused = true }
  isFocused() { return this.focused }
  blur() { this.blurCount++; this.focused = false }
  destroy() { this.destroyed = true }
}
const electron = {
  app: { getPath: () => appDirectory, getFileIcon: async file => { nativeCalls.fileIcon.push(file); return image } },
  BrowserWindow: Window,
  clipboard: { read: async () => { nativeCalls.clipboardRead.push('items'); return [] }, readText: async () => { nativeCalls.clipboardRead.push('text'); return 'explicit clipboard fixture' }, writeText: async text => nativeCalls.copy.push(text), write: async values => nativeCalls.copy.push(values) },
  ClipboardItem: class { constructor(data) { this.data = data } },
  ipcMain: { handle: (channel, callback) => handlers.set(channel, callback), removeHandler: channel => handlers.delete(channel) },
  nativeImage: {
    createFromPath: file => { nativeCalls.nativeImages.push(['path', file]); return image },
    createFromDataURL: () => { nativeCalls.nativeImages.push(['data-url']); return image },
    createFromBitmap: () => { nativeCalls.nativeImages.push(['bitmap']); return image },
    createFromBuffer: () => { nativeCalls.nativeImages.push(['buffer']); return image },
  },
  screen: fakeScreen,
  shell: { openPath: async file => { nativeCalls.open.push(file); return '' }, openExternal: async url => nativeCalls.open.push(url), showItemInFolder: file => nativeCalls.reveal.push(file) },
}
const originalLoad = Module._load
Module._load = function (id, parent, isMain) {
  if (id === 'electron') return electron
  if (id === './companion-windows' && parent.filename.endsWith(`${path.sep}companion.js`)) return windowAdapter
  if (id === './companion-preview' && parent.filename.endsWith(`${path.sep}companion.js`)) return { CompanionPreviewQueue: PreviewQueue }
  return originalLoad.call(this, id, parent, isMain)
}
const { createDesktopCompanion } = require('../dist/companion.js')
Module._load = originalLoad

function fixture(t, beforeCreate) {
  appDirectory = mkdtempSync(path.join(temporary, 'profile-'))
  if (beforeCreate) beforeCreate(appDirectory)
  Window.all = []
  handlers.clear()
  for (const calls of Object.values(nativeCalls)) calls.length = 0
  let backendUrl = 'http://127.0.0.1:47232/?user=fixture'
  const opened = []
  const controller = createDesktopCompanion({ getUrl: () => { if (!backendUrl) throw new Error('backend restarting'); return backendUrl }, openWorkspace: destination => opened.push(destination), log: () => {} })
  const [top] = Window.all
  const event = window => ({ sender: window.webContents, senderFrame: window.webContents.mainFrame })
  const invoke = (window, name, ...args) => Promise.resolve().then(() => handlers.get(`companion:${name}`)(event(window), ...args))
  t.after(() => controller.dispose())
  return { controller, top, invoke, event, opened, setBackendUrl: value => { backendUrl = value } }
}

async function dragWhenReady(invoke, top, id) {
  for (let attempt = 0; attempt < 100; attempt++) {
    const result = await invoke(top, 'drag', id)
    if (result.ok) return result
    assert.match(result.error, /正在准备/, result.error)
    await new Promise(resolve => setTimeout(resolve, 5))
  }
  assert.fail('Synthetic export was not prepared within the bounded wait')
}

test('creates exactly one top island and hover expansion never steals focus', async t => {
  const { controller, top, invoke } = fixture(t)
  assert.equal(Window.all.length, 1)
  assert.equal(top.options.frame, false)
  assert.equal(top.options.transparent, true)
  assert.equal(top.options.alwaysOnTop, true)
  assert.equal(top.options.skipTaskbar, true)
  assert.equal(top.options.webPreferences.sandbox, true)
  assert.equal(top.options.webPreferences.contextIsolation, true)
  assert.equal(top.options.webPreferences.backgroundThrottling, false, 'passive focus timers and closing springs must keep rendering while unfocused')
  top.emit('ready-to-show')
  assert.equal(top.passiveCount, 1)
  assert.equal(top.focusCount, 0)
  assert.deepEqual([top.bounds.width, top.bounds.height], [240, 44])
  assert.equal(top.bounds.y, primary.workArea.y)
  assert.equal(top.bounds.x + top.bounds.width / 2, primary.workArea.x + primary.workArea.width / 2)
  const beforeEnter = top.timeline.length
  await invoke(top, 'expand', true, 'clipboard', false)
  assert.equal(top.focusCount, 0)
  assert.equal(top.passiveCount, 2)
  assert.deepEqual([top.bounds.width, top.bounds.height], [640, 460])
  assert.equal(top.timeline[beforeEnter].kind, 'bounds')
  assert.equal(top.timeline[beforeEnter + 1].state.expanded, true)
  controller.show('top', 'capture')
  assert.equal(top.focusCount, 1)
  assert.deepEqual([top.bounds.width, top.bounds.height], [640, 460])
  await invoke(top, 'expand', true, 'agent')
  assert.equal(top.focusCount, 2)
  assert.equal((await invoke(top, 'state')).surface, 'top')
  assert.equal((await invoke(top, 'state')).panel, 'agent')
  await invoke(top, 'expand', true, 'tasks', false)
  assert.equal((await invoke(top, 'state')).panel, 'tasks')
  controller.show('top', 'agent')
  assert.equal((await invoke(top, 'state')).panel, 'agent')
})

test('legacy shelf requests select the top clipboard panel without creating any side window', async t => {
  const { controller, top, invoke } = fixture(t)
  controller.show('shelf')
  assert.equal(Window.all.length, 1)
  assert.equal((await invoke(top, 'state')).surface, 'top')
  assert.equal((await invoke(top, 'state')).panel, 'clipboard')
  await invoke(top, 'show', 'shelf', 'windows')
  assert.equal(Window.all.length, 1)
  assert.equal((await invoke(top, 'state')).panel, 'windows')
  assert.equal(new URL(top.webContents.mainFrame.url).searchParams.get('surface'), 'top')
})

test('the initial island opens notes by default and later hover expansion preserves the selected panel', async t => {
  const { controller, top, invoke } = fixture(t)
  top.emit('ready-to-show')
  const initial = await invoke(top, 'state')
  assert.equal(initial.panel, 'capture')
  assert.equal(initial.expanded, false)
  const expanded = await invoke(top, 'expand', true, undefined, false)
  assert.equal(expanded.panel, 'capture', 'hover expands notes initially without a renderer-specified panel')
  assert.equal(expanded.expanded, true)
  assert.equal(top.focusCount, 0)
  await invoke(top, 'expand', true, 'clipboard', false)
  await invoke(top, 'expand', false, undefined, false)
  const reopened = await invoke(top, 'expand', true, undefined, false)
  assert.equal(reopened.panel, 'clipboard', 'the notes-first default does not override a later chosen destination')
  assert.equal(top.focusCount, 0)
  controller.show('top', 'capture')
  const capture = await invoke(top, 'state')
  assert.equal(capture.panel, 'capture')
  assert.equal(capture.expanded, true)
  assert.equal(top.focusCount, 1)
  controller.show()
  assert.deepEqual(await invoke(top, 'state'), capture, 'generic show keeps an active capture or save mounted')
})

test('native pointer checks are read-only and report only the visible expanded window bounds', async t => {
  const { top, invoke } = fixture(t)
  let cursor = { x: 720, y: primary.workArea.y + 20 }
  let reads = 0
  t.mock.method(fakeScreen, 'getCursorScreenPoint', () => { reads++; return cursor })
  top.emit('ready-to-show')
  assert.equal(await invoke(top, 'pointer-inside'), false, 'a collapsed island is not an active drag destination')
  assert.equal(reads, 0)
  await invoke(top, 'expand', true, 'capture', false)
  const before = { state: await invoke(top, 'state'), sent: top.sent.length, focus: top.focusCount, bounds: { ...top.bounds } }
  assert.equal(await invoke(top, 'pointer-inside'), true)
  cursor = { x: top.bounds.x, y: top.bounds.y }
  assert.equal(await invoke(top, 'pointer-inside'), true, 'top and left edges belong to the window')
  for (const outside of [
    { x: top.bounds.x - 1, y: top.bounds.y },
    { x: top.bounds.x, y: top.bounds.y - 1 },
    { x: top.bounds.x + top.bounds.width, y: top.bounds.y },
    { x: top.bounds.x, y: top.bounds.y + top.bounds.height },
  ]) { cursor = outside; assert.equal(await invoke(top, 'pointer-inside'), false) }
  assert.deepEqual(await invoke(top, 'state'), before.state)
  assert.equal(top.sent.length, before.sent, 'checks do not broadcast or mutate state')
  assert.equal(top.focusCount, before.focus, 'checking the pointer never activates the island')
  assert.deepEqual(top.bounds, before.bounds)
  cursor = { x: 720, y: primary.workArea.y + 20 }
  const beforeHidden = reads
  top.hide()
  assert.equal(await invoke(top, 'pointer-inside'), false)
  assert.equal(reads, beforeHidden, 'hidden windows do not inspect the cursor')
  top.showInactive()
  await invoke(top, 'expand', false, undefined, false)
  assert.equal(top.bounds.width, 640, 'closing spring still owns the full canvas')
  assert.equal(await invoke(top, 'pointer-inside'), false, 'logical collapse wins over the remaining physical canvas')
})

test('generic show preserves an expanded panel without a collapse broadcast that could interrupt its save', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const { controller, top, invoke } = fixture(t)
  for (const panel of ['capture', 'clipboard', 'tasks']) {
    await invoke(top, 'expand', true, panel)
    const before = { state: await invoke(top, 'state'), bounds: { ...top.bounds }, timeline: top.timeline.length, focus: top.focusCount, blur: top.blurCount, passive: top.passiveCount }
    top.visible = false
    controller.show()
    controller.show('top')
    assert.equal(top.visible, true)
    assert.deepEqual(await invoke(top, 'state'), before.state, `${panel}: keep the renderer panel mounted`)
    assert.equal(top.timeline.length, before.timeline, `${panel}: no state broadcast or geometry change`)
    assert.equal(top.focusCount, before.focus, 'showing the island does not request keyboard focus')
    assert.equal(top.blurCount, before.blur, 'an active input is not blurred')
    assert.equal(top.passiveCount, before.passive + 2)
    t.mock.timers.tick(1200)
    assert.deepEqual(top.bounds, before.bounds, 'no delayed collapse is scheduled')
  }
})

test('generic show keeps an idle island compact and leaves explicit expansion and collapse available', async t => {
  const { controller, top, invoke } = fixture(t)
  top.emit('ready-to-show')
  controller.show()
  assert.equal((await invoke(top, 'state')).expanded, false)
  assert.deepEqual([top.bounds.width, top.bounds.height], [240, 44])
  assert.equal(top.focusCount, 0)
  controller.show('top', 'capture')
  assert.equal((await invoke(top, 'state')).expanded, true)
  assert.equal(top.focusCount, 1)
  await invoke(top, 'expand', false)
  await invoke(top, 'settle-collapsed')
  assert.equal((await invoke(top, 'state')).expanded, false)
  assert.deepEqual([top.bounds.width, top.bounds.height], [240, 44])
})

test('collapse keeps the native canvas until the renderer reports its spring settled', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const { top, invoke } = fixture(t)
  await invoke(top, 'expand', true, 'capture', false)
  const beforeExit = top.timeline.length
  await invoke(top, 'expand', false, undefined, false)
  assert.equal(top.timeline[beforeExit].kind, 'state')
  assert.equal(top.timeline[beforeExit].state.expanded, false)
  assert.equal(top.bounds.width, 640)
  t.mock.timers.tick(600)
  assert.equal(top.bounds.width, 640)
  await invoke(top, 'settle-collapsed')
  assert.deepEqual([top.bounds.width, top.bounds.height], [240, 44])
  assert.equal(top.focusCount, 0)
  const calls = top.timeline.length
  t.mock.timers.tick(1000)
  assert.equal(top.timeline.length, calls)
})

test('renderer loss has a 1000ms fallback instead of truncating the spring after 180ms', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const { top, invoke } = fixture(t)
  await invoke(top, 'expand', true, 'capture', false)
  await invoke(top, 'expand', false, undefined, false)
  t.mock.timers.tick(999)
  assert.equal(top.bounds.width, 640)
  t.mock.timers.tick(1)
  assert.deepEqual([top.bounds.width, top.bounds.height], [240, 44])
})

test('reentering cancels fallback, ignores stale settlement, and repeated leave does not prolong fallback', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const { top, invoke } = fixture(t)
  await invoke(top, 'expand', true, 'capture', false)
  await invoke(top, 'expand', false, undefined, false)
  t.mock.timers.tick(100)
  await invoke(top, 'expand', true, 'clipboard', false)
  await invoke(top, 'settle-collapsed')
  t.mock.timers.tick(1500)
  assert.equal(top.bounds.width, 640)
  assert.equal((await invoke(top, 'state')).expanded, true)
  assert.equal((await invoke(top, 'state')).panel, 'clipboard')
  await invoke(top, 'expand', false, undefined, false)
  t.mock.timers.tick(400)
  await invoke(top, 'expand', false, undefined, false)
  t.mock.timers.tick(599)
  assert.equal(top.bounds.width, 640)
  t.mock.timers.tick(1)
  assert.equal(top.bounds.width, 240)
})

test('Escape-style collapse releases keyboard focus while leaving the island visible', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const { top, invoke } = fixture(t)
  await invoke(top, 'expand', true, 'capture')
  assert.equal(top.isFocused(), true)
  await invoke(top, 'expand', false)
  assert.equal(top.isFocused(), false)
  assert.equal(top.blurCount, 1)
  assert.equal(top.hideCount, 0)
  assert.equal(top.bounds.width, 640)
  t.mock.timers.tick(450)
  assert.equal(top.bounds.width, 640)
  await invoke(top, 'settle-collapsed')
  assert.equal(top.bounds.width, 240)
  assert.equal(top.hideCount, 0)
})

test('all IPC handlers reject foreign windows, subframes and wrong origins before native work', async t => {
  const { top, event } = fixture(t)
  for (const [name, handler] of handlers) {
    assert.throws(() => handler({ sender: {}, senderFrame: {} }), /不允许/, name)
    assert.throws(() => handler({ ...event(top), senderFrame: {} }), /不允许/, name)
  }
  top.webContents.mainFrame.url = 'https://example.com/?surface=top'
  for (const [name, handler] of handlers) assert.throws(() => handler(event(top)), /不允许/, name)
  assert.equal(nativeCalls.open.length + nativeCalls.reveal.length + nativeCalls.drag.length + nativeCalls.copy.length + nativeCalls.clipboardRead.length, 0)
})

test('attachment popups open only generated asset URLs on the current backend origin and never navigate the island', async t => {
  const { controller, top, setBackendUrl } = fixture(t)
  const name = '0123456789abcdef01234567.pdf'
  const origin = 'http://127.0.0.1:47232'
  const asset = `${origin}/api/assets/${name}`
  assert.deepEqual(top.popupHandler({ url: asset }), { action: 'deny' })
  assert.deepEqual(nativeCalls.open, [asset], 'a real attachment opens in the system browser')
  for (const url of [
    `${origin}/`, `${origin}/api/assets/not-generated.pdf`, `${origin}/api/assets/${name}/extra`,
    `${asset}?download=1`, `${asset}#preview`, `${asset}?`, `${asset}#`,
    `${origin}/api/assets/${name.replace('.pdf', '.toolongextension')}`,
    `${origin}/api/assets/%30${name.slice(1)}`, `${origin}/other/../api/assets/${name}`,
    `http://name:password@127.0.0.1:47232/api/assets/${name}`,
    `http://127.0.0.1:47233/api/assets/${name}`, `https://127.0.0.1:47232/api/assets/${name}`,
    `https://example.com/api/assets/${name}`, `file:///api/assets/${name}`, 'javascript:alert(1)',
  ]) assert.deepEqual(top.popupHandler({ url }), { action: 'deny' }, url)
  assert.deepEqual(nativeCalls.open, [asset], 'all other URLs remain denied without invoking the OS')
  const navigation = { prevented: false, preventDefault() { this.prevented = true } }
  top.webContents.emit('will-navigate', navigation, asset)
  assert.equal(navigation.prevented, true, 'even valid assets must not replace the island renderer')
  setBackendUrl('http://127.0.0.1:47233/?user=fixture')
  controller.reload()
  top.popupHandler({ url: asset })
  const reloadedAsset = asset.replace(':47232', ':47233')
  top.popupHandler({ url: reloadedAsset })
  assert.deepEqual(nativeCalls.open, [asset, reloadedAsset], 'reload revokes the old backend origin')
})

test('passive capture peeks text without focus, mutation, history, broadcasts or image reads', async t => {
  const { top, invoke } = fixture(t)
  await invoke(top, 'expand', true, 'capture', false)
  assert.equal(top.isFocused(), false)
  const before = await invoke(top, 'state')
  const broadcasts = top.sent.length
  assert.deepEqual(await invoke(top, 'peek-clipboard'), { text: 'explicit clipboard fixture', truncated: false })
  assert.deepEqual(nativeCalls.clipboardRead, ['text'])
  assert.deepEqual(await invoke(top, 'state'), before)
  assert.equal(top.sent.length, broadcasts)
  assert.equal(existsSync(path.join(appDirectory, 'companion', 'shelf.json')), false)
  assert.deepEqual(nativeCalls.copy, [])
  assert.deepEqual(nativeCalls.nativeImages, [])
})

test('collapsed, hidden and unrelated panels reject peeks before reading any clipboard data', async t => {
  const { top, invoke } = fixture(t)
  await assert.rejects(() => invoke(top, 'peek-clipboard'), /仅在展开的随手记/)
  for (const panel of ['clipboard', 'windows', 'tasks']) {
    await invoke(top, 'expand', true, panel, false)
    await assert.rejects(() => invoke(top, 'peek-clipboard'), /仅在展开的随手记/)
  }
  await invoke(top, 'expand', true, 'capture', false)
  top.hide()
  await assert.rejects(() => invoke(top, 'peek-clipboard'), /仅在展开的随手记/)
  assert.deepEqual(nativeCalls.clipboardRead, [])
})

test('clipboard candidates preserve whitespace, report truncation and never split surrogate pairs', async t => {
  const { top, invoke } = fixture(t)
  await invoke(top, 'expand', true, 'capture', false)
  let value = '  indented\n\tfixture  '
  t.mock.method(electron.clipboard, 'readText', async () => value)
  assert.deepEqual(await invoke(top, 'peek-clipboard'), { text: value, truncated: false })
  value = ''
  assert.deepEqual(await invoke(top, 'peek-clipboard'), { text: '', truncated: false })
  value = 'a'.repeat(12_000)
  assert.deepEqual(await invoke(top, 'peek-clipboard'), { text: value, truncated: false })
  value += 'more'
  assert.deepEqual(await invoke(top, 'peek-clipboard'), { text: 'a'.repeat(12_000), truncated: true })
  value = `${'a'.repeat(11_999)}😀more`
  assert.deepEqual(await invoke(top, 'peek-clipboard'), { text: 'a'.repeat(11_999), truncated: true })
})

test('pending clipboard text is discarded after close, hide, panel change, navigation or disposal', async t => {
  for (const change of ['close', 'hide', 'panel', 'navigation', 'dispose']) await t.test(change, async context => {
    const { controller, top, invoke } = fixture(context)
    let resolveRead
    context.mock.method(electron.clipboard, 'readText', () => new Promise(resolve => { resolveRead = resolve }))
    await invoke(top, 'expand', true, 'capture', false)
    const pending = invoke(top, 'peek-clipboard')
    await Promise.resolve()
    assert.equal(typeof resolveRead, 'function')
    if (change === 'close') await invoke(top, 'expand', false)
    if (change === 'hide') top.hide()
    if (change === 'panel') await invoke(top, 'expand', true, 'tasks', false)
    if (change === 'navigation') top.webContents.mainFrame.url = 'https://example.com/?surface=top'
    if (change === 'dispose') controller.dispose()
    const rejected = assert.rejects(pending, /仅在展开的随手记|不允许/)
    resolveRead('fixture that must not be delivered')
    await rejected
    assert.equal(existsSync(path.join(appDirectory, 'companion', 'shelf.json')), false)
  })
})

test('clipboard read failure rejects honestly without creating an empty shelf item', async t => {
  const { top, invoke } = fixture(t)
  t.mock.method(electron.clipboard, 'readText', async () => { throw new Error('clipboard unavailable fixture') })
  await invoke(top, 'expand', true, 'capture', false)
  await assert.rejects(() => invoke(top, 'peek-clipboard'), /clipboard unavailable fixture/)
  assert.deepEqual((await invoke(top, 'state')).items, [])
})

test('files immediately enter loading and only generated content thumbnails are decoded and broadcast', async t => {
  const { top, invoke } = fixture(t)
  const file = path.join(temporary, 'preview-fixture.PNG')
  // Complete synthetic 1×1 PNG; native decoding itself stays mocked in this boundary test.
  writeFileSync(file, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII=', 'base64'))
  const result = await invoke(top, 'add-files', [file])
  assert.equal(result.ok, true)
  const item = result.state.items[0]
  assert.equal(item.kind, 'image')
  assert.notEqual(item.path, file)
  assert.equal(item.sourcePath, file)
  assert.equal(item.storage, 'copy')
  assert.equal(item.previewStatus, 'loading')
  assert.equal(item.thumbnail, undefined)
  assert.equal(nativeCalls.previews[0].item.id, item.id)
  assert.deepEqual(nativeCalls.nativeImages, [])
  const thumbnail = previewOptions.encodePng(Buffer.from('validated generated PNG fixture'))
  previewOptions.update(item.id, { previewStatus: 'ready', thumbnail })
  assert.equal((await invoke(top, 'state')).items[0].thumbnail, image.toDataURL())
  assert.equal(top.sent.at(-1).state.items[0].thumbnail, thumbnail)
  assert.equal(top.sent.at(-1).state.items[0].previewStatus, 'ready')
  assert.deepEqual(nativeCalls.nativeImages, [['buffer']])
  assert.deepEqual(nativeCalls.fileIcon, [])
  const invalid = path.join(temporary, 'unsupported-preview.png')
  writeFileSync(invalid, 'invalid PNG fixture')
  const fallback = await invoke(top, 'add-files', [invalid])
  assert.equal(fallback.state.items[0].kind, 'image')
  assert.equal(fallback.state.items[0].thumbnail, undefined)
  assert.equal(fallback.state.items[0].previewStatus, 'loading')
  previewOptions.update(fallback.state.items[0].id, { previewStatus: 'unavailable', previewError: '系统没有提供内容缩略图' })
  assert.match((await invoke(top, 'state')).items[0].previewError, /没有提供/)
  assert.deepEqual(nativeCalls.nativeImages, [['buffer']])
})

test('preview retry accepts only existing staged file ids and removed items cannot be restored by late previews', async t => {
  const { controller, top, invoke } = fixture(t)
  const file = path.join(temporary, 'retry-preview.txt')
  writeFileSync(file, 'preview fixture')
  const added = await invoke(top, 'add-files', [file])
  const id = added.state.items[0].id
  assert.equal((await invoke(top, 'refresh-preview', file)).ok, false)
  assert.equal((await invoke(top, 'refresh-preview', id)).ok, true)
  assert.equal(nativeCalls.previews.at(-1).force, true)
  await invoke(top, 'remove', id)
  previewOptions.update(id, { previewStatus: 'ready', thumbnail: image.toDataURL() })
  assert.deepEqual((await invoke(top, 'state')).items, [])
  controller.dispose()
  assert.equal(previewDisposed, true)
})

test('startup limits old-reference preview work and later opens advance to previously unattempted files', async t => {
  let saved
  const { top, invoke } = fixture(t, profile => {
    const files = Array.from({ length: 30 }, (_, index) => {
      const file = path.join(temporary, `backfill-${index}.pdf`)
      writeFileSync(file, 'backfill fixture')
      return file
    })
    saved = files.map(file => ({ id: randomUUID(), path: file, kind: 'file', title: path.basename(file), createdAt: new Date().toISOString() }))
    mkdirSync(path.join(profile, 'companion'))
    writeFileSync(path.join(profile, 'companion', 'shelf.json'), JSON.stringify({ version: 1, items: saved }))
  })
  assert.equal(nativeCalls.previews.length, 24)
  assert.deepEqual(nativeCalls.previews.map(call => call.item.id), saved.slice(0, 24).map(item => item.id))
  await invoke(top, 'expand', true, 'clipboard', false)
  assert.equal(nativeCalls.previews.length, 48)
  assert.deepEqual(nativeCalls.previews.slice(24, 30).map(call => call.item.id), saved.slice(24).map(item => item.id))
  assert.equal((await invoke(top, 'state')).items.every(item => item.previewStatus !== 'loading'), true, 'restored interrupted jobs are retryable until actually queued')
})

test('staged IDs open copied snapshots, drag independent exports and recover removed copies', async t => {
  const { top, invoke } = fixture(t)
  const file = path.join(temporary, 'drag-fixture.txt')
  writeFileSync(file, 'fixture')
  const added = await invoke(top, 'add-files', [file])
  assert.equal(added.ok, true)
  const item = added.state.items[0]
  assert.notEqual(item.path, file)
  assert.equal(item.sourcePath, file)
  assert.equal(item.storage, 'copy')
  assert.equal(item.thumbnail, undefined)
  assert.deepEqual(nativeCalls.fileIcon, [])
  assert.deepEqual(nativeCalls.nativeImages, [])
  assert.equal(top.sent.at(-1).state.items[0].id, item.id)
  assert.equal(top.sent.at(-1).state.surface, 'top')
  for (const method of ['open', 'reveal', 'drag', 'remove']) {
    const result = await invoke(top, method, file)
    assert.equal(result.ok, false, method)
  }
  assert.equal(nativeCalls.open.length + nativeCalls.reveal.length + nativeCalls.drag.length, 0)
  await dragWhenReady(invoke, top, item.id)
  const exported = nativeCalls.drag[0].file
  assert.notEqual(exported, file)
  assert.notEqual(exported, item.path)
  assert.equal(path.basename(exported), path.basename(file))
  writeFileSync(exported, 'target changes its delivered copy')
  assert.equal(readFileSync(file, 'utf8'), 'fixture')
  assert.equal(readFileSync(item.path, 'utf8'), 'fixture')
  assert.equal((await invoke(top, 'open', item.id)).ok, true)
  assert.equal(nativeCalls.open[0], item.path)
  assert.equal((await invoke(top, 'reveal', item.id)).ok, true)
  assert.equal(nativeCalls.reveal[0], item.path)
  const removed = await invoke(top, 'remove', item.id)
  assert.equal(removed.ok, true)
  assert.equal(readFileSync(removed.recoveryPath, 'utf8'), 'fixture')
  assert.equal(existsSync(item.path), false)
  assert.equal(existsSync(file), true)
  assert.equal((await invoke(top, 'drag', item.id)).ok, false)
  assert.equal((await invoke(top, 'reveal-removed')).ok, true)
  assert.equal(nativeCalls.open.at(-1), path.join(appDirectory, 'companion', 'removed'))
})

test('reopening prewarms only eight owned copies with two workers and never copies legacy references', async t => {
  const { CompanionStore } = require('../dist/companion-store.js')
  const prepared = []
  let active = 0
  let maximum = 0
  t.mock.method(CompanionStore.prototype, 'prepareExport', async function (id) {
    prepared.push(id)
    maximum = Math.max(maximum, ++active)
    await new Promise(resolve => setImmediate(resolve))
    active--
    return path.join(temporary, `prewarmed-${id}`)
  })
  let copies
  const { top, invoke } = fixture(t, profile => {
    const directory = path.join(profile, 'companion')
    mkdirSync(directory)
    copies = Array.from({ length: 10 }, (_, index) => {
      const id = randomUUID()
      const folder = path.join(directory, 'vault', id)
      mkdirSync(folder, { recursive: true })
      const file = path.join(folder, `owned-${index}.txt`)
      writeFileSync(file, 'owned fixture')
      return { id, path: file, storage: 'copy', kind: 'file', title: path.basename(file), createdAt: new Date().toISOString() }
    })
    const reference = path.join(temporary, 'prewarm-reference.txt')
    writeFileSync(reference, 'legacy fixture')
    writeFileSync(path.join(directory, 'shelf.json'), JSON.stringify({ version: 1, items: [{ id: randomUUID(), path: reference, kind: 'file', title: 'legacy', createdAt: new Date().toISOString() }, ...copies] }))
  })
  assert.deepEqual(prepared, [], 'a collapsed startup should not copy exports')
  await invoke(top, 'expand', true, 'clipboard', false)
  for (let index = 0; index < 12; index++) await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(prepared, copies.slice(0, 8).map(item => item.id))
  assert.equal(maximum, 2)
  await invoke(top, 'expand', false)
  await invoke(top, 'expand', true, 'clipboard', false)
  assert.equal(prepared.length, 8, 'ready exports are reused until a drag claims them')
  assert.equal(nativeCalls.drag.length, 0)
})

test('export preparation never starts a delayed native drag after the original gesture ended', async t => {
  const { CompanionStore } = require('../dist/companion-store.js')
  let finish
  const ready = new Promise(resolve => { finish = resolve })
  let copied
  const completed = new Promise(resolve => { copied = resolve })
  const originalPrepare = CompanionStore.prototype.prepareExport
  t.mock.method(CompanionStore.prototype, 'prepareExport', async function (id) {
    await ready
    const file = await originalPrepare.call(this, id)
    copied()
    return file
  })
  const { top, invoke } = fixture(t)
  const file = path.join(temporary, 'gesture-source.txt')
  writeFileSync(file, 'source')
  const added = await invoke(top, 'add-files', [file])
  const id = added.state.items[0].id
  const pending = await invoke(top, 'drag', id)
  assert.equal(pending.ok, false)
  assert.match(pending.error, /正在准备.*稍后再拖/)
  finish()
  await completed
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(nativeCalls.drag.length, 0, 'finishing a copy is not a new drag gesture')
  assert.equal((await invoke(top, 'drag', id)).ok, true)
  assert.notEqual(nativeCalls.drag[0].file, added.state.items[0].path)
  assert.equal(readFileSync(nativeCalls.drag[0].file, 'utf8'), 'source')
})

test('source deletion after a committed drop does not break open, preview or drag', async t => {
  const { top, invoke } = fixture(t)
  const file = path.join(temporary, 'source-can-go-away.txt')
  writeFileSync(file, 'independent snapshot')
  const added = await invoke(top, 'add-files', [file])
  const item = added.state.items[0]
  unlinkSync(file)
  assert.equal((await invoke(top, 'open', item.id)).ok, true)
  assert.equal((await invoke(top, 'refresh-preview', item.id)).ok, true)
  assert.equal(nativeCalls.previews.at(-1).item.path, item.path)
  await dragWhenReady(invoke, top, item.id)
  assert.equal(readFileSync(nativeCalls.drag[0].file, 'utf8'), 'independent snapshot')
  assert.equal((await invoke(top, 'state')).items[0].missing, false)
})

test('clipboard writes are awaited, text comes only from explicit paste, and external navigation uses stored HTTP links', async t => {
  const { top, invoke } = fixture(t)
  assert.equal((await invoke(top, 'state')).items.length, 0)
  const pasted = await invoke(top, 'paste')
  assert.equal(pasted.state.items[0].text, 'explicit clipboard fixture')
  await invoke(top, 'copy', pasted.state.items[0].id)
  assert.equal(nativeCalls.copy[0], 'explicit clipboard fixture')
  const link = await invoke(top, 'add-text', 'https://example.com/')
  await invoke(top, 'open', link.state.items[0].id)
  assert.equal(nativeCalls.open[0], 'https://example.com/')
  const unsafe = await invoke(top, 'add-text', 'javascript:alert(1)')
  assert.equal((await invoke(top, 'open', unsafe.state.items[0].id)).ok, false)
  assert.equal(nativeCalls.open.length, 1)
})

test('local shelf works during backend restart and reload switches the allowed origin', async t => {
  const { controller, top, invoke, setBackendUrl } = fixture(t)
  setBackendUrl(null)
  assert.equal((await invoke(top, 'add-text', 'offline shelf')).ok, true)
  setBackendUrl('http://127.0.0.1:47233/?user=fixture')
  controller.reload()
  assert.equal(new URL(top.webContents.mainFrame.url).port, '47233')
  assert.equal((await invoke(top, 'state')).items[0].text, 'offline shelf')
  top.webContents.mainFrame.url = 'http://127.0.0.1:47232/?surface=top'
  await assert.rejects(() => invoke(top, 'state'), /不允许/)
})

test('clipboard images become app-owned files and a failed copy returns a real error', async t => {
  const { top, invoke } = fixture(t)
  const originalRead = electron.clipboard.read
  const originalWrite = electron.clipboard.writeText
  t.after(() => { electron.clipboard.read = originalRead; electron.clipboard.writeText = originalWrite })
  electron.clipboard.read = async () => [{ types: ['image/png'], getType: async () => new Blob([new Uint8Array([137, 80, 78, 71])], { type: 'image/png' }) }]
  const pasted = await invoke(top, 'paste')
  assert.equal(pasted.ok, true)
  assert.equal(pasted.state.items[0].kind, 'image')
  assert.equal(existsSync(pasted.state.items[0].path), true)
  assert.equal(pasted.state.items[0].storage, 'copy')
  assert.equal(path.dirname(pasted.state.items[0].path), path.join(appDirectory, 'companion', 'vault', pasted.state.items[0].id))
  const text = await invoke(top, 'add-text', 'copy fixture')
  electron.clipboard.writeText = async () => { throw new Error('clipboard unavailable') }
  const copied = await invoke(top, 'copy', text.state.items[0].id)
  assert.deepEqual(copied, { ok: false, error: 'clipboard unavailable' })
})

test('a missing staged copy blocks every native file action without touching the original', async t => {
  const { top, invoke } = fixture(t)
  const file = path.join(temporary, 'missing-after-drop.txt')
  writeFileSync(file, 'fixture')
  const added = await invoke(top, 'add-files', [file])
  const id = added.state.items[0].id
  unlinkSync(added.state.items[0].path)
  for (const method of ['open', 'reveal', 'drag']) {
    const result = await invoke(top, method, id)
    assert.equal(result.ok, false)
    assert.match(result.error, /文件已移动/)
  }
  assert.equal(nativeCalls.open.length + nativeCalls.reveal.length + nativeCalls.drag.length, 0)
  assert.equal(top.sent.at(-1).state.items[0].missing, true)
  assert.equal(existsSync(file), true)
})

test('the top island remains inside the usable screen after display metrics change', t => {
  const { controller, top } = fixture(t)
  const previous = { ...primary.workArea }
  t.after(() => { primary.workArea = previous })
  controller.show('top', 'agent')
  primary.workArea = { x: -320, y: 40, width: 320, height: 360 }
  fakeScreen.emit('display-metrics-changed')
  assert.ok(top.bounds.x >= primary.workArea.x)
  assert.equal(top.bounds.y, primary.workArea.y)
  assert.ok(top.bounds.x + top.bounds.width <= primary.workArea.x + primary.workArea.width)
  assert.ok(top.bounds.y + top.bounds.height <= primary.workArea.y + primary.workArea.height)
})

test('only listed windows can be staged and recall receives the exact persisted title', async t => {
  const { top, invoke } = fixture(t)
  const previousList = windowAdapter.listWindowCandidates
  const previousRecall = windowAdapter.recallWindow
  t.after(() => { windowAdapter.listWindowCandidates = previousList; windowAdapter.recallWindow = previousRecall })
  const candidate = { id: 'window:123:0', title: 'long title '.repeat(30) + '\nexact ending' }
  const recalls = []
  windowAdapter.listWindowCandidates = async () => ({ ok: true, candidates: [candidate] })
  windowAdapter.recallWindow = async (id, title) => { recalls.push({ id, title }); return { ok: true } }
  assert.equal((await invoke(top, 'add-window', candidate.id)).ok, false)
  await invoke(top, 'list-windows')
  const saved = await invoke(top, 'add-window', candidate.id)
  assert.equal(saved.ok, true)
  assert.equal((await invoke(top, 'recall-window', candidate.id)).ok, false)
  await invoke(top, 'recall-window', saved.state.items[0].id)
  assert.deepEqual(recalls, [{ id: candidate.id, title: candidate.title }])
})

test('an older window-list completion cannot discard newer selectable window candidates', async t => {
  const { top, invoke } = fixture(t)
  const previousList = windowAdapter.listWindowCandidates
  t.after(() => { windowAdapter.listWindowCandidates = previousList })
  const pending = []
  windowAdapter.listWindowCandidates = () => new Promise(resolve => pending.push(resolve))
  const older = invoke(top, 'list-windows')
  await Promise.resolve()
  const newer = invoke(top, 'list-windows')
  await Promise.resolve()
  pending[1]({ ok: true, candidates: [{ id: 'window:222:0', title: 'Latest window' }] })
  assert.equal((await newer).ok, true)
  pending[0]({ ok: false, error: 'stale request' })
  assert.equal((await older).ok, false)
  assert.equal((await invoke(top, 'add-window', 'window:222:0')).ok, true)
})

test('disposal cancels pending collapse, removes IPC and display listeners, and destroys the only window', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const { controller, top, invoke } = fixture(t)
  await invoke(top, 'expand', true, 'capture', false)
  await invoke(top, 'expand', false, undefined, false)
  assert.equal(controller.owns(top.webContents), true)
  controller.dispose()
  assert.equal(handlers.size, 0)
  assert.equal(fakeScreen.listenerCount('display-metrics-changed'), 0)
  assert.equal(fakeScreen.listenerCount('display-removed'), 0)
  assert.equal(top.destroyed, true)
  assert.equal(controller.owns(top.webContents), false)
  const calls = top.timeline.length
  t.mock.timers.tick(1500)
  assert.equal(top.timeline.length, calls)
})
