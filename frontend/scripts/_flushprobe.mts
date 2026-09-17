/** 探针：照 capture.ts 的 flush() 原样落一次盘。argv: <snapshot.json> <segments.json> */
import { readFileSync, writeFileSync } from 'node:fs'
import { keepBackendFields, mergeBlips, readSegments, type Segment } from '../../desktop/src/capture.ts'
import path from 'node:path'
const [snap, target] = process.argv.slice(2)
const segs = JSON.parse(readFileSync(snap, 'utf8')) as Segment[]
writeFileSync(target, JSON.stringify(
  keepBackendFields(mergeBlips(segs), readSegments(path.dirname(target))), null, 1), 'utf8')
console.log('flushed')
