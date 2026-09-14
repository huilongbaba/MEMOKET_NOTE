import { useState } from 'react'

import { exportFeishu, exportNotion, exportObsidian, type ExportBackOut } from '../api'
import { toast } from '../toast'

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
 */
export type ExportWhere = 'obsidian' | 'notion' | 'feishu'

export const WHERE_LABEL: Record<ExportWhere, string> = {
  obsidian: 'Obsidian', notion: 'Notion', feishu: '飞书',
}

export function useExportBack(noteIds: string[] = []) {
  const [busy, setBusy] = useState<'' | ExportWhere>('')
  const [result, setResult] = useState<{ where: ExportWhere; out: ExportBackOut } | null>(null)

  async function run(where: ExportWhere, fn: () => Promise<ExportBackOut>) {
    setBusy(where)
    try {
      const out = await fn()
      setResult({ where, out })
      const n = (out.written ?? 0) + (out.created ?? 0) + (out.updated ?? 0)
      toast(n ? `导回 ${n} 篇` : '没有需要写的：上次导回之后没改过')
      // 信息面板的「副本」一行跟着刷新
      window.dispatchEvent(new CustomEvent('note-remotes-changed'))
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    } finally {
      setBusy('')
    }
  }

  return {
    busy, result,
    toObsidian: (vaultDir: string, force: boolean) =>
      run('obsidian', () => exportObsidian(vaultDir.trim(), noteIds, force)),
    toNotion: (token: string, parentPageId: string) =>
      run('notion', () => exportNotion(token.trim(), parentPageId.trim().replace(/-/g, ''), noteIds)),
    toFeishu: (appId: string, secret: string, folder: string) =>
      run('feishu', () => exportFeishu(appId.trim(), secret.trim(), folder.trim(), noteIds)),
  }
}

/** Obsidian 的 vault 路径不是密钥，记得住；Notion / 飞书的凭证有意不落库。 */
export const VAULT_KEY = 'memoket-note:vault-dir'
export function loadVault(): string {
  try { return localStorage.getItem(VAULT_KEY) || '' } catch { return '' }
}
export function saveVault(dir: string): void {
  try { localStorage.setItem(VAULT_KEY, dir) } catch { /* 无所谓 */ }
}
