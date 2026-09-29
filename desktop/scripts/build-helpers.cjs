#!/usr/bin/env node
/** 编「双击 ⌃ 截图」用的原生辅助进程（helpers/modtap.swift → dist/modtap）。
 *  没有 Swift 工具链（没装 Xcode Command Line Tools）就跳过并提示：⌥D 照旧可用，只是少了双击截图。 */
const { spawnSync } = require('node:child_process')
const { mkdirSync } = require('node:fs')
const path = require('node:path')

const root = path.join(__dirname, '..')
const source = path.join(root, 'helpers', 'modtap.swift')
const target = path.join(root, 'dist', 'modtap')
if (process.platform !== 'darwin') { console.log('[helpers] 不是 macOS：跳过 modtap（双击 ⌃ 截图只有 macOS 有）'); process.exit(0) }
const found = spawnSync('xcrun', ['--find', 'swiftc'], { encoding: 'utf8' })
if (found.status !== 0) {
  console.log('[helpers] 没找到 swiftc：跳过双击 ⌃ 截图（装 Xcode Command Line Tools 后再跑 npm run build:helpers）；⌥D 照旧可用')
  process.exit(0)
}
mkdirSync(path.dirname(target), { recursive: true })
const built = spawnSync('swiftc', ['-O', '-swift-version', '5', '-o', target, source], { stdio: 'inherit' })
if (built.status !== 0) { console.log('[helpers] modtap 没编出来：双击 ⌃ 截图不可用，⌥D 照旧'); process.exit(0) }
console.log(`[helpers] modtap 已编到 ${path.relative(root, target)}`)
