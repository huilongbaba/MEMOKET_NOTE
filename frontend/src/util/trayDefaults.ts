/**
 * 「导入 / 录音 / 网页剪藏默认进托盘」这个开关（P15 #3，`docs/agent-native-editor.md` §3.4 后半：
 * 「导入的东西默认先进托盘」「录音拖进托盘…它不进正文——它变成一份材料」）。
 *
 * 默认**开**：材料先摊在桌上，要进正文是用户自己的下一步；关了就回到 P14 之前的去处
 * （导入只进笔记树 / 知识库，录音只有「插入正文」「存入知识库」两个去处）。
 * 开关在右栏「记忆」的托盘格里（用户看得见它为什么进了托盘），存 localStorage——按机器记、跟着浏览器走，
 * 读写都兜 try（隐私模式写不了不值得报错）。
 */
const KEY = 'memoket.tray.default'

export function trayByDefault(): boolean {
  try {
    const v = localStorage.getItem(KEY)
    return v === null ? true : v === '1'
  } catch { return true }
}

export function setTrayByDefault(on: boolean): void {
  try { localStorage.setItem(KEY, on ? '1' : '0') } catch { /* 无所谓 */ }
  window.dispatchEvent(new CustomEvent('tray-default-changed', { detail: on }))
}

/** 录音 / 剪藏落成托盘项的标题：「录音 14:05」这种，用户在托盘里认得出是哪一段 */
export function recordingTitle(now: Date = new Date()): string {
  const hh = String(now.getHours()).padStart(2, '0')
  const mm = String(now.getMinutes()).padStart(2, '0')
  return `录音 ${hh}:${mm}`
}
