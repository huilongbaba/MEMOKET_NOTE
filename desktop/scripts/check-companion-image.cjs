const assert = require('node:assert/strict')
const { mkdtempSync, writeFileSync, truncateSync, rmSync } = require('node:fs')
const { tmpdir } = require('node:os')
const path = require('node:path')
const { test, after } = require('node:test')
const { previewDimensions, canPreviewImageFile } = require('../dist/companion-image.js')
const temporary = mkdtempSync(path.join(tmpdir(), 'memoket-companion-preview-'))
after(() => rmSync(temporary, { recursive: true, force: true }))

function png(width, height) {
  const header = Buffer.alloc(24)
  Buffer.from('89504e470d0a1a0a', 'hex').copy(header)
  header.writeUInt32BE(13, 8)
  header.write('IHDR', 12)
  header.writeUInt32BE(width, 16)
  header.writeUInt32BE(height, 20)
  return header
}
function jpeg(width, height) {
  const header = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0, 4, 0, 0, 0xff, 0xc2, 0, 8, 8, 0, 0, 0, 0, 1])
  header.writeUInt16BE(height, 13)
  header.writeUInt16BE(width, 15)
  return header
}

test('recognizes bounded PNG and JPEG dimensions without loading any native image API', () => {
  assert.deepEqual(previewDimensions(png(1200, 800)), { width: 1200, height: 800 })
  assert.deepEqual(previewDimensions(jpeg(600, 400)), { width: 600, height: 400 })
})

test('declines large pixel allocations, zero dimensions, unsupported and malformed headers', () => {
  for (const header of [png(8193, 1), png(5000, 4000), png(0, 40), png(40, 0), Buffer.from('not an image'), Buffer.from('GIF89a'), jpeg(120, 80).subarray(0, 15), Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0, 1])]) {
    assert.equal(previewDimensions(header), null)
  }
})

test('file preflight declines absent files, oversized compressed files and non-image content', () => {
  const file = path.join(temporary, 'small.png')
  writeFileSync(file, png(800, 600))
  assert.equal(canPreviewImageFile(file), true)
  truncateSync(file, 20 * 1024 * 1024 + 1)
  assert.equal(canPreviewImageFile(file), false)
  writeFileSync(file, 'plain text with an image extension')
  assert.equal(canPreviewImageFile(file), false)
  assert.equal(canPreviewImageFile(path.join(temporary, 'absent.png')), false)
  assert.equal(canPreviewImageFile(temporary), false)
})
