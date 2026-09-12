/** 窗口不在前台时发一条系统通知——跑几分钟的智能续写 / 分段写作 / 摄入结束了，
 *  用户多半已经切去别的窗口。在前台时不发（toast 已经在眼前）。Electron 的渲染进程
 *  直接能用 Web Notification；拒绝了或不支持就静默。 */
export function notifyIfHidden(title: string, body = ''): void {
  try {
    if (typeof Notification === 'undefined') return
    if (!document.hidden && document.hasFocus()) return
    if (Notification.permission === 'denied') return
    const fire = () => { try { new Notification(title, { body, silent: true }) } catch { /* 无所谓 */ } }
    if (Notification.permission === 'granted') fire()
    else void Notification.requestPermission().then((p) => { if (p === 'granted') fire() })
  } catch { /* 无所谓 */ }
}
