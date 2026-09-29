const assert = require('node:assert/strict')
const Module = require('node:module')
const { test } = require('node:test')

let exposed
const invocations = []
const listeners = new Map()
const electron = {
  contextBridge: { exposeInMainWorld: (name, bridge) => { assert.equal(name, 'memoketDesktop'); exposed = bridge } },
  webUtils: { getPathForFile: file => file.localPath ?? '' },
  ipcRenderer: {
    invoke: async (channel, ...args) => { invocations.push({ channel, args }); return { ok: true } },
    send() {},
    on: (channel, callback) => listeners.set(channel, callback),
    removeListener: (channel, callback) => { if (listeners.get(channel) === callback) listeners.delete(channel) },
  },
}
const originalLoad = Module._load
Module._load = function (id, parent, isMain) { return id === 'electron' ? electron : originalLoad.call(this, id, parent, isMain) }
require('../dist/preload.js')
Module._load = originalLoad

test('mixed native and pathless files fail as a whole before any IPC or partial save', async () => {
  invocations.length = 0
  await assert.rejects(() => exposed.companion.addFiles([{ localPath: '/fixture/photo.png' }, { name: 'web-image.png' }]), /此次尚未暂存/)
  assert.equal(invocations.length, 0)
})

test('valid drops resolve paths in preload and send paths only, not renderer File objects', async () => {
  invocations.length = 0
  await exposed.companion.addFiles([{ localPath: '/fixture/a.txt' }, { localPath: '/fixture/b.png' }])
  assert.deepEqual(invocations, [{ channel: 'companion:add-files', args: [['/fixture/a.txt', '/fixture/b.png']] }])
})

test('state listeners expose state only and remove the exact callback on unsubscribe', () => {
  let received
  const unsubscribe = exposed.companion.onState(state => { received = state })
  const state = { surface: 'top', items: [] }
  listeners.get('companion:changed')({ sender: 'private-native-event' }, state)
  assert.equal(received, state)
  unsubscribe()
  assert.equal(listeners.has('companion:changed'), false)
})

test('hover focus opt-out is forwarded to the main process without exposing a raw IPC method', async () => {
  invocations.length = 0
  await exposed.companion.setExpanded(true, 'capture', false)
  assert.deepEqual(invocations, [{ channel: 'companion:expand', args: [true, 'capture', false] }])
})

test('spring settlement uses the dedicated bounded IPC endpoint', async () => {
  invocations.length = 0
  await exposed.companion.settleCollapsed()
  assert.deepEqual(invocations, [{ channel: 'companion:settle-collapsed', args: [] }])
  invocations.length = 0
  await exposed.companion.settleCollapsed(320)   // 拿主意在想时弹簧停在 320：报给主进程，窗口先别收窄
  assert.deepEqual(invocations, [{ channel: 'companion:settle-collapsed', args: [320] }])
})

test('external drag pointer checks expose only a dedicated argument-free read-only endpoint', async () => {
  invocations.length = 0
  await exposed.companion.isPointerInside()
  assert.deepEqual(invocations, [{ channel: 'companion:pointer-inside', args: [] }])
  assert.equal(exposed.companion.invoke, undefined)
})

test('removed copies are revealed through a fixed target, never a renderer-supplied filesystem path', async () => {
  invocations.length = 0
  await exposed.companion.revealRemoved()
  assert.deepEqual(invocations, [{ channel: 'companion:reveal-removed', args: [] }])
})

test('clipboard candidates use a read-only endpoint without saving or exposing arbitrary IPC', async () => {
  invocations.length = 0
  await exposed.companion.peekClipboard()
  assert.deepEqual(invocations, [{ channel: 'companion:peek-clipboard', args: [] }])
  assert.equal(exposed.companion.invoke, undefined)
})

test('preview retry forwards only an existing item id through its dedicated endpoint', async () => {
  invocations.length = 0
  await exposed.companion.refreshPreview('fixture-item-id')
  assert.deepEqual(invocations, [{ channel: 'companion:refresh-preview', args: ['fixture-item-id'] }])
})
