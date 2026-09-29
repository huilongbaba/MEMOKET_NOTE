/**
 * 双击修饰键（默认 ⌥⌥）：Electron 注册不了单独的修饰键，所以起一个很小的原生辅助进程
 * （helpers/modtap.swift 编出来的 dist/modtap）盯着全局按键，双击就往 stdout 打一行 "tap"。
 * 没有这个二进制（没装 Swift 工具链）就静静地不启用，⌥D 照旧；辅助功能权限跟着启动它的应用走。
 */
import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync } from 'node:fs'

export type ModifierTapOptions = {
  /** 编好的辅助进程；不存在就不启用。 */
  helper: string
  /** option | control | command | shift */
  key?: string
  log(line: string): void
  onTap(): void
}
export type ModifierTap = { active(): boolean; dispose(): void }

/** 默认双击 ⌃：⌥⌥ 是 Claude 桌面端的，⇧⇧ 是 JetBrains 的，Fn Fn 是听写。 */
export const DEFAULT_TAP_KEY = 'control'
export const TAP_LABELS: Record<string, string> = { option: '⌥⌥', control: '⌃⌃', command: '⌘⌘', shift: '⇧⇧' }

export function createModifierTap(options: ModifierTapOptions): ModifierTap {
  const key = options.key && options.key in TAP_LABELS ? options.key : DEFAULT_TAP_KEY
  const log = (line: string) => { try { options.log(`${line}\n`) } catch { /* 日志本身出错不影响。 */ } }
  let child: ChildProcess | null = null
  let active = false
  let disposed = false

  if (!existsSync(options.helper)) {
    log(`[modtap] 没有 ${options.helper}：双击 ${TAP_LABELS[key]} 截图不可用（npm run build:helpers 编一下）`)
  } else {
    try {
      child = spawn(options.helper, [key], { stdio: ['ignore', 'pipe', 'pipe'] })
      active = true
      let buffer = ''
      child.stdout?.setEncoding('utf8')
      child.stdout?.on('data', (chunk: string) => {
        buffer += chunk
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const raw of lines) {
          const line = raw.trim()
          if (line === 'tap') { if (!disposed) options.onTap() }
          else if (line.startsWith('ready')) {
            if (line.includes('trusted=false')) log(`[modtap] 辅助进程没有辅助功能权限，双击 ${TAP_LABELS[key]} 收不到：系统设置 › 隐私与安全性 › 辅助功能`)
            else log(`[modtap] 双击 ${TAP_LABELS[key]} 截图已就绪`)
          }
        }
      })
      child.stderr?.setEncoding('utf8')
      child.stderr?.on('data', (chunk: string) => { const line = String(chunk).trim(); if (line) log(`[modtap] ${line}`) })
      child.on('exit', (code, signal) => {
        active = false
        if (!disposed) log(`[modtap] 辅助进程退出了（${signal ?? code}）：双击 ${TAP_LABELS[key]} 截图不可用，⌥D 照旧`)
      })
      child.on('error', error => { active = false; log(`[modtap] 起不来：${error instanceof Error ? error.message : String(error)}`) })
    } catch (error) {
      active = false
      log(`[modtap] 起不来：${error instanceof Error ? error.message : String(error)}`)
    }
  }

  return {
    active: () => active,
    dispose() {
      if (disposed) return
      disposed = true
      active = false
      if (child && child.exitCode === null) { try { child.kill() } catch { /* 已经退出了。 */ } }
      child = null
    },
  }
}
