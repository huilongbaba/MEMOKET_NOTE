import { useState } from 'react'

import { exportFeishu, exportNotion, exportObsidian, type ExportBackOut, type NoteRemote } from '../api'
import { toast, toastAction } from '../toast'
import { exportMermaidRenders } from './mermaidPng'

/**
 * 导回的**逻辑**：三个平台各怎么调、跑起来什么状态、写完怎么报。
 *
 * 为什么单独拎出来：导回有两个场景——导入页整库导（整页宽、第一次配置），
 * 和某一篇从「⋯」里导（窄弹层、重复动作、只一篇）。第 628 轮我把整个组件
 * 原样塞进弹层，结果是那块 UI 的设计前提全不成立：标签列 + 行内输入 + 每行
 * 两行说明，在 560px 里读起来是一堵墙，说明比控件还多（用户实拍指出来的）。
 *
 * **复用逻辑，不复用排版。** 会漂的是「怎么调、memoket_id 怎么覆盖、冲突怎么
 * 报」这些，不是布局；两个场景各自排版，逻辑走这一份。
 *
 * P2-fix：成功的 toast 带「打开」（后端回 `url`）；`n=0` 不再一律解释成「没改过」
 * （note_id 对不上是 `missing`，对方改过是 `conflicts`）；失败的 toast 带「复制」、不 6 秒就没。
 */
export type ExportWhere = 'obsidian' | 'notion' | 'feishu'

export const WHERE_LABEL: Record<ExportWhere, string> = {
  obsidian: 'Obsidian', notion: 'Notion', feishu: '飞书',
}

export type ExportOutcome = { kind: 'ok' | 'none' | 'missing' | 'conflict'; text: string; url?: string }

/** 后端的回包 → 用户看到的那一句（纯函数，有测试）。 */
export function exportOutcome(out: ExportBackOut): ExportOutcome {
  const n = (out.written ?? 0) + (out.created ?? 0) + (out.updated ?? 0)
  const failed = out.failed?.length ?? 0
  if (n) {
    const tail = failed ? `，${failed} 篇失败` : (out.conflicts?.length ? `，${out.conflicts.length} 篇对方改过没动` : '')
    return { kind: 'ok', text: `导回 ${n} 篇${tail}`, url: out.url || undefined }
  }
  if (out.conflicts?.length) return { kind: 'conflict', text: `对方那边改过，跳过了 ${out.conflicts.length} 篇——勾上「覆盖对方改过的」再写一次` }
  if (!(out.skipped ?? 0) && out.missing?.length) return { kind: 'missing', text: '没有匹配的笔记——这篇可能已经删掉了，关掉弹层重开一次' }
  if (!(out.skipped ?? 0)) return { kind: 'none', text: '没有可导的笔记' }
  return { kind: 'none', text: '没有需要写的：上次导回之后没改过' }
}

/** 后端 4xx 的那句人话：状态码对用户没意义，只留那句话 */
export function exportErrorText(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e ?? '')
  return raw.replace(/^Error:\s*/i, '').replace(/^4\d\d\s+(?=\S)/, '') || '导回失败'
}

/** 打开对面那一篇。https 走系统浏览器（桌面壳的 setWindowOpenHandler），obsidian:// 走 Obsidian。 */
export function openRemote(url: string): void {
  window.open(url, '_blank', 'noopener')
}

/** 信息面板 / 弹层里「副本」那一行能点去哪：Notion / 飞书存的就是 URL；Obsidian 要拼 vault 路径。 */
export function remoteUrl(r: NoteRemote, vault = loadVault()): string {
  if (/^https?:\/\//.test(r.remote_path)) return r.remote_path
  if (r.platform === 'obsidian' && vault && r.remote_path) return 'obsidian://open?path=' + encodeURIComponent(vault.replace(/\/+$/, '') + '/' + r.remote_path)
  return ''
}

export function useExportBack(noteIds: string[] = []) {
  const [busy, setBusy] = useState<'' | ExportWhere>('')
  const [result, setResult] = useState<{ where: ExportWhere; out: ExportBackOut } | null>(null)

  async function run(where: ExportWhere, fn: () => Promise<ExportBackOut>): Promise<ExportBackOut | null> {
    setBusy(where)
    try {
      const out = await fn()
      setResult({ where, out })
      const o = exportOutcome(out)
      if (o.url) toastAction(o.text, '打开', () => openRemote(o.url!), 8000)
      else toast(o.text, o.kind === 'ok' || o.kind === 'none' ? 'info' : 'error')
      // 信息面板的「副本」一行跟着刷新
      window.dispatchEvent(new CustomEvent('note-remotes-changed'))
      return out
    } catch (e) {
      const msg = exportErrorText(e)
      // 6 秒消失、不能选中复制——那些带 code 的提示根本来不及看（P2 报告 §4.16）：给「复制」，多留一会儿
      toastAction(msg, '复制', () => { void navigator.clipboard?.writeText(msg) }, 15000, 'error')
      return null
    } finally {
      setBusy('')
    }
  }

  return {
    busy, result,
    toObsidian: (vaultDir: string, force: boolean) =>
      run('obsidian', () => exportObsidian(vaultDir.trim(), noteIds, force)),
    toNotion: (token: string, parentPageId: string, force = false) =>
      run('notion', () => exportNotion(token.trim(), parentPageId.trim().replace(/-/g, ''), noteIds, force)),
    // 飞书没有 mermaid：先把这批笔记里的图在这边渲成 PNG 交给后端（P18 #4；渲不出不拦导回）
    toFeishu: (appId: string, secret: string, folder: string, force = false) =>
      run('feishu', async () => { await exportMermaidRenders(noteIds); return exportFeishu(appId.trim(), secret.trim(), folder.trim(), noteIds, force) }),
  }
}

/** Obsidian 的 vault 路径不是密钥，记得住；Notion / 飞书的凭证桌面版记在主进程（util/exportCreds）。 */
export const VAULT_KEY = 'memoket-note:vault-dir'
export function loadVault(): string {
  try { return localStorage.getItem(VAULT_KEY) || '' } catch { return '' }
}
export function saveVault(dir: string): void {
  try { localStorage.setItem(VAULT_KEY, dir) } catch { /* 无所谓 */ }
}
