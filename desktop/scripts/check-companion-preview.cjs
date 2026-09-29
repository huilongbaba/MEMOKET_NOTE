/** Real queue/cache/filesystem, mocked Quick Look and PNG encoder. No OS app or private file access. */
const assert = require('node:assert/strict')
const { test, after } = require('node:test')
const { mkdtempSync, writeFileSync, appendFileSync, mkdirSync, readdirSync, rmSync, truncateSync, existsSync } = require('node:fs')
const fsAsync = require('node:fs/promises')
const { tmpdir } = require('node:os')
const path = require('node:path')
const { randomUUID } = require('node:crypto')
const { CompanionPreviewQueue } = require('../dist/companion-preview.js')

const temporary = mkdtempSync(path.join(tmpdir(), 'memoket-content-previews-'))
after(() => rmSync(temporary, { recursive: true, force: true }))
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII=', 'base64')
const tick = () => new Promise(resolve => setTimeout(resolve, 5))
async function until(predicate) {
  for (let count = 0; count < 200 && !predicate(); count++) await tick()
  assert.equal(predicate(), true, 'async work should reach its expected boundary')
}
function fixture(t, overrides = {}) {
  const directory = mkdtempSync(path.join(temporary, 'queue-'))
  const updates = []
  const calls = []
  let decodes = 0
  const output = args => writeFileSync(path.join(args[4], 'generated.png'), png)
  const queue = new CompanionPreviewQueue({
    directory: path.join(directory, 'cache'), platform: 'darwin',
    encodePng: bytes => { decodes++; assert.deepEqual(bytes, png); return `data:image/png;base64,${bytes.toString('base64')}` },
    update: (id, preview) => updates.push({ id, ...preview }),
    run: async (...args) => { calls.push(args); output(args[1]) },
    ...overrides,
  })
  t.after(() => queue.dispose())
  const item = (name = 'document.pdf') => {
    const file = path.join(directory, name)
    writeFileSync(file, 'synthetic local document fixture')
    return { id: randomUUID(), kind: 'file', title: name, createdAt: new Date().toISOString(), path: file }
  }
  return { directory, queue, updates, calls, item, output, decodes: () => decodes }
}

test('document filenames are literal execFile arguments, with content mode, bounded output and timeout', async t => {
  const { queue, calls, item, updates, directory } = fixture(t)
  const file = item('presentation "quotes" $(touch NEVER) ; `echo NEVER`.key')
  await queue.request(file)
  assert.equal(calls.length, 1)
  const [command, args, options] = calls[0]
  assert.equal(command, '/usr/bin/qlmanage')
  assert.deepEqual(args.slice(0, 4), ['-t', '-s', '512', '-o'])
  assert.equal(args[5], file.path)
  assert.equal(args.length, 6)
  assert.equal(args.includes('-i') || args.includes('-p'), false)
  assert.equal(options.timeout, 12_000)
  assert.equal(options.maxBuffer, 64 * 1024)
  assert.equal(options.signal instanceof AbortSignal, true)
  assert.equal(updates.at(-1).previewStatus, 'ready')
  assert.equal(readdirSync(path.join(directory, 'cache')).some(name => name.startsWith('working-')), false)
})

test('PDF, Office and image content use real-content thumbnails while plain text remains readable', async t => {
  const { queue, item, calls, updates } = fixture(t)
  for (const extension of ['pdf', 'docx', 'pptx', 'xlsx', 'txt', 'png', 'key']) await queue.request(item(`fixture.${extension}`))
  assert.equal(calls.length, 6)
  assert.equal(updates.filter(update => update.previewStatus === 'ready').length, 7)
  assert.equal(updates.find(update => update.previewText !== undefined).previewText, 'synthetic local document fixture')
})

test('plain-text formats return exact bounded original text, never Quick Look or a stale cached PNG', async t => {
  const { queue, item, calls, updates, directory, decodes } = fixture(t)
  for (const extension of ['txt', 'MD', 'csv', 'tsv', 'log']) {
    const file = item(`fixture.${extension}`)
    const original = '  原文\t<em>literal, not markup</em>\r\nsecond line  \n'
    writeFileSync(file.path, original)
    await queue.request({ ...file, previewStatus: 'ready', thumbnail: `data:image/png;base64,${png.toString('base64')}` })
    assert.equal(updates.at(-1).previewStatus, 'ready')
    assert.equal(updates.at(-1).previewText, original)
    assert.equal(updates.at(-1).previewTextTruncated, false)
    assert.equal(updates.at(-1).thumbnail, undefined)
  }
  assert.equal(calls.length, 0)
  assert.equal(decodes(), 0)
  assert.equal(existsSync(path.join(directory, 'cache')), false)
})

test('large text files use at most a 16KiB FileHandle read, never a whole-file read', async t => {
  const { queue, item, updates } = fixture(t)
  const file = item('large.txt')
  writeFileSync(file.path, 'a'.repeat(32 * 1024))
  truncateSync(file.path, 64 * 1024 * 1024)
  const originalOpen = fsAsync.open
  let bytesRequested = 0
  t.mock.method(fsAsync, 'readFile', async () => assert.fail('text previews must not read the full file'))
  t.mock.method(fsAsync, 'open', async (...args) => {
    const handle = await originalOpen(...args)
    return {
      stat: () => handle.stat(), close: () => handle.close(),
      read: (...readArgs) => { bytesRequested += readArgs[2]; assert.ok(readArgs[0].length <= 16 * 1024); return handle.read(...readArgs) },
    }
  })
  await queue.request(file)
  assert.equal(bytesRequested, 16 * 1024)
  assert.equal(updates.at(-1).previewText, 'a'.repeat(16 * 1024))
  assert.equal(updates.at(-1).previewTextTruncated, true)
})

test('empty text and BOM encodings are readable, and the byte limit does not split UTF-8 characters', async t => {
  const { queue, item, updates } = fixture(t, { platform: 'linux' })
  const file = item('encoding.txt')
  for (const [bytes, expected, truncated] of [
    [Buffer.alloc(0), '', false],
    [Buffer.from('\uFEFF中文😀\n'), '中文😀\n', false],
    [Buffer.from('\uFEFF中文😀\n', 'utf16le'), '中文😀\n', false],
    [Buffer.from('\uFEFF中文😀\n', 'utf16le').swap16(), '中文😀\n', false],
    [Buffer.from('a'.repeat(16 * 1024 - 1) + '😀tail'), 'a'.repeat(16 * 1024 - 1), true],
  ]) {
    writeFileSync(file.path, bytes)
    await queue.request(file)
    assert.equal(updates.at(-1).previewStatus, 'ready')
    assert.equal(updates.at(-1).previewText, expected)
    assert.equal(updates.at(-1).previewTextTruncated, truncated)
    assert.equal(updates.at(-1).previewText.includes('\uFFFD'), false)
  }
})

test('invalid encodings, binary contents, missing files and read permission errors are explicit unavailable states', async t => {
  const { queue, item, updates, calls } = fixture(t)
  const file = item('unreadable.txt')
  writeFileSync(file.path, Buffer.from([0xff, 0xff, 0xff]))
  await queue.request(file)
  assert.match(updates.at(-1).previewError, /编码/)
  writeFileSync(file.path, 'not\0text')
  await queue.request(file)
  assert.match(updates.at(-1).previewError, /二进制/)
  t.mock.method(fsAsync, 'open', async () => { throw Object.assign(new Error('private details must not leak'), { code: 'EACCES' }) })
  await queue.request(file)
  assert.match(updates.at(-1).previewError, /权限/)
  assert.equal(updates.at(-1).previewError.includes('private'), false)
  rmSync(file.path)
  await queue.request(file)
  assert.match(updates.at(-1).previewError, /已移动/)
  assert.equal(updates.at(-1).previewStatus, 'unavailable')
  assert.equal(updates.at(-1).previewText, undefined)
  assert.equal(calls.length, 0)
})

test('cache is reused across queue instances and invalidated by file modification or explicit retry', async t => {
  const { queue, item, calls, directory } = fixture(t)
  const file = item()
  const first = queue.request(file)
  assert.equal(queue.request(file), first)
  await first
  await queue.request(file)
  assert.equal(calls.length, 1)
  const second = new CompanionPreviewQueue({ directory: path.join(directory, 'cache'), platform: 'darwin', encodePng: bytes => `data:image/png;base64,${bytes.toString('base64')}`, update() {}, run: async () => assert.fail('valid persisted cache must not invoke Quick Look') })
  t.after(() => second.dispose())
  await second.request(file)
  appendFileSync(file.path, 'changed')
  await queue.request(file)
  assert.equal(calls.length, 2)
  await queue.request(file, true)
  assert.equal(calls.length, 3)
})

test('at most two native jobs run concurrently; disposal aborts active work and drops queued work', async t => {
  const started = []
  const { queue, item, updates } = fixture(t, { run: (_command, args, options) => new Promise((resolve, reject) => {
    started.push({ args, options, finish: () => { writeFileSync(path.join(args[4], 'generated.png'), png); resolve() } })
    options.signal.addEventListener('abort', () => reject(new Error('aborted fixture')), { once: true })
  }) })
  const tasks = Array.from({ length: 5 }, (_, index) => queue.request(item(`${index}.pdf`)))
  await until(() => started.length === 2)
  started[0].finish()
  await until(() => started.length === 3)
  const beforeDispose = updates.length
  queue.dispose()
  await Promise.all(tasks)
  assert.equal(started.length, 3)
  assert.equal(started[1].options.signal.aborted, true)
  assert.equal(started[2].options.signal.aborted, true)
  assert.equal(updates.length, beforeDispose)
})

test('unsupported formats, platforms, missing files and ordinary folders return an explicit reason without native work', async t => {
  const { queue, item, calls, updates, directory } = fixture(t)
  const unknown = item('opaque.unrecognized')
  await queue.request(unknown)
  assert.match(updates.at(-1).previewError, /格式/)
  const missing = item('missing.pdf')
  rmSync(missing.path)
  await queue.request(missing)
  assert.match(updates.at(-1).previewError, /已移动/)
  const folder = path.join(directory, 'folder.pdf')
  mkdirSync(folder)
  await queue.request({ ...unknown, id: randomUUID(), path: folder })
  assert.match(updates.at(-1).previewError, /文件夹/)
  assert.equal(calls.length, 0)
  const other = fixture(t, { platform: 'linux' })
  await other.queue.request(other.item())
  assert.match(other.updates.at(-1).previewError, /此系统/)
  assert.equal(other.calls.length, 0)
})

test('timeout, no thumbnail and invalid output are visible unavailable states, never fabricated type icons', async t => {
  for (const scenario of ['timeout', 'empty', 'invalid', 'oversized']) await t.test(scenario, async context => {
    const current = fixture(context, { run: async (_command, args) => {
      if (scenario === 'timeout') throw Object.assign(new Error('fixture timeout'), { killed: true })
      if (scenario === 'invalid') writeFileSync(path.join(args[4], 'preview.png'), 'not PNG')
      if (scenario === 'oversized') writeFileSync(path.join(args[4], 'preview.png'), Buffer.alloc(2 * 1024 * 1024 + 1))
    } })
    await current.queue.request(current.item())
    const result = current.updates.at(-1)
    assert.equal(result.previewStatus, 'unavailable')
    assert.ok(result.previewError)
    assert.equal(result.thumbnail, undefined)
    assert.equal(current.decodes(), 0)
  })
})

test('source mutations during generation reject the outdated snapshot before any native PNG decode', async t => {
  const current = fixture(t, { run: async (_command, args) => {
    writeFileSync(path.join(args[4], 'preview.png'), png)
    appendFileSync(args[5], 'updated during Quick Look')
  } })
  await current.queue.request(current.item())
  assert.equal(current.updates.at(-1).previewStatus, 'unavailable')
  assert.match(current.updates.at(-1).previewError, /文件已更新/)
  assert.equal(current.decodes(), 0)
})
