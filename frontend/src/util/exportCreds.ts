/**
 * 导回 Notion / 飞书的凭证记在哪。
 *
 * 桌面版：主进程的 `export-credentials.json`（identity.json 旁边，0600）。P2 验证
 * （docs/_research/export-verification-P2.md §4.5）：「凭证不落库、每次重填」对单用户桌面版是自找麻烦——
 * 每次导回都要重新抄三段，第一次用的人卡在「去哪拿 App Secret」。Obsidian 的 vault 路径早就存在
 * localStorage 里了，同一条理由。
 * 网页版：没有这个口子，仍然每次填（浏览器可能是共用的）。
 */
export type ExportCreds = {
  notion_token?: string
  notion_parent?: string
  feishu_app_id?: string
  feishu_app_secret?: string
  feishu_folder?: string
}

export const canRememberCreds = (): boolean => !!window.memoketDesktop?.exportCreds

export async function loadCreds(): Promise<ExportCreds> {
  try { return ((await window.memoketDesktop?.exportCreds?.load()) ?? {}) as ExportCreds } catch { return {} }
}

export async function saveCreds(patch: ExportCreds): Promise<void> {
  try { await window.memoketDesktop?.exportCreds?.save(patch as Record<string, string>) } catch { /* 记不住就下次再填 */ }
}

/** 「怎么拿」——第一次用的人卡的就是这一步（P2 报告 §2.1 / §3.1 写了完整步骤，这里给入口） */
export const CRED_HOWTO = {
  notion: { url: 'https://www.notion.so/profile/integrations', text: 'notion.so → Settings → Connections → Develop or manage integrations → New integration → 复制 Internal Integration Secret；父页面 id 是页面链接末尾那 32 位，页面要先「⋯ → Connections」连上这个 integration' },
  feishu: { url: 'https://open.feishu.cn/app', text: 'open.feishu.cn → 应用 → 凭证与基础信息（App ID / App Secret）；权限管理开 docx:document、drive:drive；文件夹 token 是文件夹链接 /drive/folder/ 后面那串，文件夹要把应用加为可编辑的协作者' },
} as const
