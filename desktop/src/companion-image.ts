import { closeSync, openSync, readSync, statSync } from 'node:fs'

const MAX_BYTES = 20 * 1024 * 1024
const MAX_EDGE = 8192
const MAX_PIXELS = 16_000_000
const JPEG_SOF = new Set([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf])

/** Bound allocation before any optional native decoding. Other formats keep the ordinary icon. */
export function previewDimensions(header: Buffer): { width: number; height: number } | null {
  let width = 0
  let height = 0
  if (header.length >= 24 && header.subarray(0, 8).equals(Buffer.from('89504e470d0a1a0a', 'hex'))
    && header.readUInt32BE(8) === 13 && header.toString('ascii', 12, 16) === 'IHDR') {
    width = header.readUInt32BE(16)
    height = header.readUInt32BE(20)
  } else if (header.length >= 4 && header[0] === 0xff && header[1] === 0xd8) {
    let offset = 2
    while (offset + 3 < header.length) {
      if (header[offset++] !== 0xff) return null
      while (header[offset] === 0xff) offset++
      const marker = header[offset++]
      if (marker === 0xda || marker === 0xd9) return null
      if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd8)) continue
      if (offset + 2 > header.length) return null
      const length = header.readUInt16BE(offset)
      if (length < 2 || offset + length > header.length) return null
      if (JPEG_SOF.has(marker)) {
        if (length < 8) return null
        height = header.readUInt16BE(offset + 3)
        width = header.readUInt16BE(offset + 5)
        break
      }
      offset += length
    }
  }
  return width > 0 && height > 0 && width <= MAX_EDGE && height <= MAX_EDGE && width * height <= MAX_PIXELS
    ? { width, height } : null
}

export function canPreviewImageFile(file: string): boolean {
  let descriptor: number | undefined
  try {
    const stat = statSync(file)
    if (!stat.isFile() || stat.size === 0 || stat.size > MAX_BYTES) return false
    descriptor = openSync(file, 'r')
    const header = Buffer.alloc(Math.min(stat.size, 512 * 1024))
    const size = readSync(descriptor, header, 0, header.length, 0)
    return previewDimensions(header.subarray(0, size)) !== null
  } catch { return false }
  finally { if (descriptor !== undefined) closeSync(descriptor) }
}
