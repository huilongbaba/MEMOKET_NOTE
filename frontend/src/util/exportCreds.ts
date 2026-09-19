/**
 * 导回 Notion / 飞书的凭证记在哪。
 *
 * 桌面版：主进程的 `export-credentials.json`（identity.json 旁边，0600）。P2 验证
 * （docs/_research/export-verification-P2.md §4.5）：「凭证不落库、每次重填」对单用户桌面版是自找麻烦——
 * 每次导回都要重新抄三段，第一次用的人卡在「去哪拿 App Secret」。Obsidian 的 vault 路径早就存在
 * localStorage 里了，同一条理由。
 * 网页版（P18 #6）：跟 Obsidian 路径一个待遇——存在这个浏览器的 localStorage 里；弹层明说「存在这个浏览器里」，
 * 共用电脑的人自己决定填不填。以前是「不存、每次填」，P2-fix 留的尾巴。
 */
export type ExportCreds = {
  notion_token?: string
  notion_parent?: string
  feishu_app_id?: string
  feishu_app_secret?: string
  feishu_folder?: string
}

export type CredsPlace = 'desktop' | 'browser'
export const WEB_CREDS_KEY = 'memoket-note:export-creds'
const KEYS: (keyof ExportCreds)[] = ['notion_token', 'notion_parent', 'feishu_app_id', 'feishu_app_secret', 'feishu_folder']

/** 记在哪：桌面壳有 IPC 口子就记主进程；否则这个浏览器的 localStorage */
export const credsPlace = (): CredsPlace => (window.memoketDesktop?.exportCreds ? 'desktop' : 'browser')
/** 两种都记得住（P18 #6 起网页版也记）；留着这个名字是因为两个弹层都在用它挑文案 */
export const canRememberCreds = (): boolean => true

/** 弹层里那一句：记在哪、意味着什么 */
export function credsNote(place: CredsPlace = credsPlace()): string {
  return place === 'desktop'
    ? '凭证写成功后记在本机（应用数据目录），下次自动带出来。'
    : '凭证写成功后存在这个浏览器里（localStorage）：换浏览器要重填，清浏览器数据就没了；共用的电脑别存。'
}

/** 只留白名单里的键、只留字符串——跟桌面壳那边的白名单同一个口径 */
export function pickCreds(raw: unknown): ExportCreds {
  const out: ExportCreds = {}
  if (!raw || typeof raw !== 'object') return out
  for (const k of KEYS) {
    const v = (raw as Record<string, unknown>)[k]
    if (typeof v === 'string' && v) out[k] = v.slice(0, 512)
  }
  return out
}

function loadWeb(): ExportCreds {
  try { return pickCreds(JSON.parse(localStorage.getItem(WEB_CREDS_KEY) || '{}')) } catch { return {} }
}

function saveWeb(patch: ExportCreds): void {
  try { localStorage.setItem(WEB_CREDS_KEY, JSON.stringify({ ...loadWeb(), ...pickCreds(patch) })) } catch { /* 记不住就下次再填 */ }
}

export async function loadCreds(): Promise<ExportCreds> {
  if (credsPlace() === 'browser') return loadWeb()
  try { return pickCreds(await window.memoketDesktop?.exportCreds?.load()) } catch { return {} }
}

export async function saveCreds(patch: ExportCreds): Promise<void> {
  if (credsPlace() === 'browser') { saveWeb(patch); return }
  try { await window.memoketDesktop?.exportCreds?.save(pickCreds(patch) as Record<string, string>) } catch { /* 记不住就下次再填 */ }
}

/** 「怎么拿」——第一次用的人卡的就是这一步（P2 报告 §2.1 / §3.1 写了完整步骤，这里给入口） */
export const CRED_HOWTO = {
  notion: { url: 'https://www.notion.so/profile/integrations', text: 'notion.so → Settings → Connections → Develop or manage integrations → New integration → 复制 Internal Integration Secret；父页面 id 是页面链接末尾那 32 位，页面要先「⋯ → Connections」连上这个 integration' },
  feishu: { url: 'https://open.feishu.cn/app', text: 'open.feishu.cn → 应用 → 凭证与基础信息（App ID / App Secret）；权限管理开 docx:document、drive:drive；文件夹 token 是文件夹链接 /drive/folder/ 后面那串，文件夹要把应用加为可编辑的协作者' },
} as const
