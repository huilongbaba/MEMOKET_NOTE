import { getUser, type DesktopAIAction, type DesktopComposeSource } from '../api'
import type { CompanionItem } from '../desktop'

export const DESKTOP_AI_ACTIONS: ReadonlyArray<{ id: DesktopAIAction; label: string; description: string; icon: string }> = [
  { id: 'organize', label: '整理笔记', description: '梳理内容，保留来源', icon: 'bx-note' },
  { id: 'continue', label: '一键续写', description: '沿着已有内容继续写', icon: 'bx-pen' },
  { id: 'summarize', label: '提炼要点', description: '留下结论与关键细节', icon: 'bx-list-ul' },
  { id: 'diagram', label: '生成图表', description: '把流程或数据变成图', icon: 'bx-network-chart' },
  { id: 'table', label: '整理表格', description: '把材料变成清晰的对照表', icon: 'bx-table' },
  { id: 'tasks', label: '提取待办', description: '提取明确的下一步行动', icon: 'bx-list-check' },
]

/** Only text already available locally is eligible; a thumbnail/path is never file content. */
export function eligibleDesktopSource(item: CompanionItem): DesktopComposeSource | null {
  if (item.kind === 'text' && item.text?.trim()) return { id: item.id, kind: 'text', title: item.title || '暂存文字', text: item.text }
  if (item.kind === 'link' && item.url && /^https?:\/\//i.test(item.url)) return { id: item.id, kind: 'link', title: item.title || '暂存链接', text: item.text || '', url: item.url }
  if (item.kind === 'file' && !item.missing && item.previewStatus === 'ready' && item.previewText?.trim()) {
    return { id: item.id, kind: 'text', title: `${item.title || '暂存文件'}（文字节选）`, text: item.previewText }
  }
  return null
}

export function listCompanionAIDrafts(): Array<{ key: string; title: string }> {
  const base = `memoket.companion.ai-note.${encodeURIComponent(getUser())}`
  const drafts: Array<{ key: string; title: string }> = []
  try {
    for (let index = 0; index < localStorage.length; index++) {
      const key = localStorage.key(index)
      if (!key || (key !== base && !key.startsWith(`${base}::request::`))) continue
      try {
        const value = JSON.parse(localStorage.getItem(key) || 'null')
        if (value && (value.result || value.selectedIds?.length || value.instruction)) {
          drafts.push({ key, title: value.result?.title || value.snapshot?.[0]?.title || '未完成的材料草稿' })
        }
      } catch { /* A damaged draft must not hide other recoverable sessions. */ }
    }
  } catch { /* The live panel remains usable when storage is unavailable. */ }
  return drafts
}

export function hasCompanionAIDraft(): boolean { return listCompanionAIDrafts().length > 0 }
