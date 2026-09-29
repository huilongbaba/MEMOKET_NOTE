/**
 * Pure window-adapter regression checks. Run after `npm run build`:
 *   node scripts/check-companion-windows.cjs
 * Every OS dependency is injected. The guards below make accidental native access fail.
 */
const Module = require('node:module')
const originalLoad = Module._load
Module._load = function (id, ...args) {
  if (id === 'electron') throw new Error('Regression checks must not load native Electron APIs')
  return originalLoad.call(this, id, ...args)
}
require('node:child_process').execFile = () => { throw new Error('Regression checks must not execute OS commands') }

const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createCompanionWindowAdapter, parseWindowRecallResult, windowRecallCommand } = require('../dist/companion-windows.js')

const source = (id = 'window:123:0', name = '设计稿', preview = 'data:image/png;base64,fixture') => ({ id, name, thumbnail: { isEmpty: () => !preview, getSize: () => ({ width: 720, height: 450 }), toDataURL: () => preview } })
function fixture(overrides = {}) {
  const calls = []
  const deps = {
    platform: 'darwin',
    screenAccess: async () => { calls.push({ kind: 'screen' }); return 'granted' },
    accessibilityAccess: async () => { calls.push({ kind: 'accessibility' }); return true },
    getSources: async options => { calls.push({ kind: 'sources', value: options }); return [source()] },
    run: async command => { calls.push({ kind: 'run', value: command }); return 'raised\n' },
    ...overrides,
  }
  return { ...createCompanionWindowAdapter(deps), calls }
}

test('list and recall reject unsupported platforms without touching native APIs', async () => {
  const adapter = fixture({ platform: 'win32' })
  assert.equal((await adapter.listWindowCandidates()).ok, false)
  assert.equal((await adapter.recallWindow('window:123:0', '设计稿')).ok, false)
  assert.deepEqual(adapter.calls, [])
})

for (const permission of ['not-determined', 'denied', 'restricted', 'unknown']) {
  test(`screen ${permission} never captures or raises a window`, async () => {
    const adapter = fixture({ screenAccess: async () => permission })
    const listed = await adapter.listWindowCandidates()
    assert.equal(listed.ok, false)
    if (!listed.ok) assert.match(listed.error, /屏幕录制权限/)
    const recalled = await adapter.recallWindow('window:123:0', '设计稿')
    assert.equal(recalled.ok, false)
    assert.deepEqual(adapter.calls, [])
  })
}

test('list returns exact titles and optional snapshots, excluding nonwindow and untitled sources', async () => {
  let requested
  const adapter = fixture({ getSources: async options => {
    requested = options
    return [source('window:1:0', '  原标题  '), source('window:2:0', '无预览', ''), source('screen:0:0', '整个屏幕'), source('window:3:0', ' '), source('window:1:0', '重复ID')]
  } })
  const result = await adapter.listWindowCandidates()
  assert.equal(result.ok, true)
  assert.deepEqual(result.candidates[0], { id: 'window:1:0', title: '  原标题  ', preview: 'data:image/png;base64,fixture' })
  assert.equal(result.candidates.length, 2)
  assert.equal(result.candidates[1].title, '无预览')
  assert.equal(result.candidates[1].preview, undefined)
  assert.match(result.candidates[1].previewError, /截图为空.*仅保存窗口引用/)
  assert.deepEqual(requested, { types: ['window'], thumbnailSize: { width: 720, height: 450 }, fetchWindowIcons: false })
})

test('missing, empty and unreadable snapshots keep honest errors and usable references', async () => {
  const adapter = fixture({ getSources: async () => [
    { ...source('window:1:0', '缺少截图'), thumbnail: undefined },
    source('window:2:0', '空截图', ''),
    { ...source('window:3:0', '编码失败'), thumbnail: { ...source().thumbnail, toDataURL: () => { throw Error('private screenshot detail') } } },
  ] })
  const result = await adapter.listWindowCandidates()
  assert.equal(result.ok, true)
  assert.equal(result.candidates.length, 3)
  for (const candidate of result.candidates) {
    assert.equal(candidate.preview, undefined)
    assert.match(candidate.previewError, /仅保存窗口引用/)
    assert.equal(candidate.previewError.includes('private'), false)
  }
  assert.match(result.candidates[0].previewError, /没有提供截图/)
  assert.match(result.candidates[1].previewError, /截图为空/)
  assert.match(result.candidates[2].previewError, /无法读取/)
})

test('larger native thumbnails fit inside 720 by 450 without changing aspect ratio or upscaling', async () => {
  for (const [size, expected] of [
    [{ width: 2560, height: 1440 }, { width: 720, height: 405 }],
    [{ width: 1440, height: 2560 }, { width: 253, height: 450 }],
    [{ width: 320, height: 200 }, null],
  ]) {
    let resized
    let encoded
    const image = dimensions => ({
      isEmpty: () => false,
      getSize: factor => { assert.equal(factor, 1); return dimensions },
      resize: options => { resized = options; return image({ width: options.width, height: options.height }) },
      toDataURL: options => { encoded = options; return 'data:image/png;base64,actualSnapshot' },
    })
    const adapter = fixture({ getSources: async () => [{ ...source(), thumbnail: image(size) }] })
    const result = await adapter.listWindowCandidates()
    assert.equal(result.ok, true)
    assert.equal(result.candidates[0].preview, 'data:image/png;base64,actualSnapshot')
    assert.equal(result.candidates[0].previewError, undefined)
    assert.deepEqual(resized, expected ? { ...expected, quality: 'best' } : undefined)
    assert.deepEqual(encoded, { scaleFactor: 1 })
  }
})

test('invalid image dimensions never get encoded as a pretend screenshot', async () => {
  for (const size of [{ width: 0, height: 450 }, { width: 720, height: NaN }, { width: Infinity, height: 450 }]) {
    const adapter = fixture({ getSources: async () => [{ ...source(), thumbnail: {
      isEmpty: () => false,
      getSize: () => size,
      toDataURL: () => { assert.fail('Invalid images must never be encoded') },
    } }] })
    const result = await adapter.listWindowCandidates()
    assert.equal(result.ok, true)
    assert.equal(result.candidates[0].preview, undefined)
    assert.match(result.candidates[0].previewError, /截图为空/)
  }
})

test('invalid or oversized encoded images return an explicit preview error', async () => {
  for (const preview of ['data:image/png;base64,', 'data:text/plain;base64,private', 'data:image/png;base64,' + 'A'.repeat(3_000_000)]) {
    const adapter = fixture({ getSources: async () => [source('window:123:0', '设计稿', preview)] })
    const result = await adapter.listWindowCandidates()
    assert.equal(result.ok, true)
    assert.equal(result.candidates[0].preview, undefined)
    assert.match(result.candidates[0].previewError, /仅保存窗口引用/)
  }
})

test('screen permission revoked during capture discards the captured candidate without any OS command', async () => {
  let checks = 0
  const adapter = fixture({ screenAccess: async () => ++checks === 1 ? 'granted' : 'denied' })
  const result = await adapter.listWindowCandidates()
  assert.equal(result.ok, false)
  assert.match(result.error, /屏幕录制权限/)
  assert.equal('candidates' in result, false)
  assert.deepEqual(adapter.calls.map(item => item.kind), ['sources'])
})

test('capture failures are actionable and never expose native error details or try to raise a window', async () => {
  const adapter = fixture({ getSources: async () => { throw Error('private title or native error') } })
  const result = await adapter.listWindowCandidates()
  assert.equal(result.ok, false)
  assert.match(result.error, /无法读取窗口列表.*屏幕录制权限/)
  assert.equal(result.error.includes('private'), false)
  assert.deepEqual(adapter.calls.map(item => item.kind), ['screen'])
})

test('an explicit list refresh returns the new snapshot instead of a cached image', async () => {
  let reads = 0
  const adapter = fixture({ getSources: async () => [source('window:123:0', '设计稿', `data:image/png;base64,${++reads === 1 ? 'first' : 'second'}`)] })
  const first = await adapter.listWindowCandidates()
  const second = await adapter.listWindowCandidates()
  assert.equal(first.ok, true)
  assert.equal(second.ok, true)
  assert.equal(first.candidates[0].preview, 'data:image/png;base64,first')
  assert.equal(second.candidates[0].preview, 'data:image/png;base64,second')
  assert.equal(reads, 2)
})

test('recall without cache or a persisted title fails without native calls', async () => {
  const adapter = fixture()
  assert.equal((await adapter.recallWindow('window:123:0')).ok, false)
  assert.deepEqual(adapter.calls, [])
})

test('accessibility denial stops before window enumeration or execution', async () => {
  const adapter = fixture({ accessibilityAccess: async () => false })
  const result = await adapter.recallWindow('window:123:0', '设计稿')
  assert.equal(result.ok, false)
  if (!result.ok) assert.match(result.error, /辅助功能权限/)
  assert.deepEqual(adapter.calls.map(item => item.kind), ['screen'])
})

test('restart recall validates saved id and title without taking a new thumbnail', async () => {
  const adapter = fixture()
  assert.deepEqual(await adapter.recallWindow('window:123:0', '设计稿'), { ok: true })
  assert.deepEqual(adapter.calls.map(item => item.kind), ['screen', 'accessibility', 'sources', 'run'])
  assert.deepEqual(adapter.calls[2].value, { types: ['window'], thumbnailSize: { width: 0, height: 0 }, fetchWindowIcons: false })
})

test('cached selection is revalidated and renderer mutations cannot change its stored title', async () => {
  const adapter = fixture()
  const listed = await adapter.listWindowCandidates()
  assert.equal(listed.ok, true)
  if (listed.ok) listed.candidates[0].title = 'tampered'
  assert.deepEqual(await adapter.recallWindow('window:123:0'), { ok: true })
  const command = adapter.calls.find(item => item.kind === 'run').value
  assert.equal(command.args.at(-1), '设计稿')
})

test('closed or reused ids and changed titles never execute a command', async () => {
  for (const sources of [[], [source('window:124:0', '设计稿')], [source('window:123:0', '新的窗口')]]) {
    const adapter = fixture({ getSources: async () => sources })
    const result = await adapter.recallWindow('window:123:0', '设计稿')
    assert.equal(result.ok, false)
    if (!result.ok) assert.match(result.error, /已关闭或标题已变化/)
    assert.equal(adapter.calls.some(item => item.kind === 'run'), false)
  }
})

test('duplicate exact titles are ambiguous and never pick an arbitrary window', async () => {
  const adapter = fixture({ getSources: async () => [source(), source('window:999:0')] })
  const result = await adapter.recallWindow('window:123:0', '设计稿')
  assert.equal(result.ok, false)
  if (!result.ok) assert.match(result.error, /同名窗口/)
  assert.equal(adapter.calls.some(item => item.kind === 'run'), false)
})

test('titles are argv data, preserving quotes, whitespace, newlines and shell metacharacters', () => {
  const title = '  标题"\n$(touch /tmp/never) `echo nope` \\ --help  '
  const command = windowRecallCommand(title)
  assert.equal(command.file, '/usr/bin/osascript')
  assert.deepEqual(command.args.slice(2), ['--', title])
  assert.equal(command.args[1].includes(title), false)
  assert.equal(command.options.shell, false)
  assert.equal(command.options.timeout, 8000)
  assert.match(command.args[1], /considering case/)
  assert.match(command.args[1], /return "ambiguous"/)
  assert.throws(() => windowRecallCommand('bad\0title'))
  assert.throws(() => windowRecallCommand(''))
})

test('only an explicit raised result is success', () => {
  assert.deepEqual(parseWindowRecallResult('raised\n'), { ok: true })
  for (const response of ['not-found', 'ambiguous', 'failed', '', 'ok', 'raised\nfailed']) {
    assert.equal(parseWindowRecallResult(response).ok, false)
  }
})

test('permission command failure is actionable without leaking raw command data', async () => {
  const adapter = fixture({ run: async () => { throw Error('secret title -1743') } })
  const result = await adapter.recallWindow('window:123:0', '设计稿')
  assert.equal(result.ok, false)
  if (!result.ok) {
    assert.match(result.error, /自动化权限/)
    assert.equal(result.error.includes('secret'), false)
  }
})

test('later list requests win even when an older response arrives afterward', async () => {
  let release = () => {}
  let count = 0
  const adapter = fixture({ getSources: async () => {
    if (++count === 1) return new Promise(resolve => { release = resolve })
    return [source('window:234:0', '最新')]
  } })
  const old = adapter.listWindowCandidates()
  await Promise.resolve()
  const fresh = await adapter.listWindowCandidates()
  release([source()])
  assert.equal((await old).ok, false)
  assert.deepEqual(fresh, { ok: true, candidates: [{ id: 'window:234:0', title: '最新', preview: 'data:image/png;base64,fixture' }] })
  assert.equal((await adapter.recallWindow('window:123:0')).ok, false)
})
