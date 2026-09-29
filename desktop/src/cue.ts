/**
 * 「拿主意」按下热键那一瞬间，在光标所在的位置点一下：一圈细细的强调色光环荡开、消失，不到半秒。
 * 只是「收到了，从这儿拿的」的确认，不是飞行——内容在岛里出现，岛自己长开来装它。
 *
 * 画在一个盖住当前显示器、全透明、不接鼠标、不抢焦点的窗口上，只在这几百毫秒里显示。
 * 页面是内联的一小段 HTML（不加载任何外部资源）；主进程用 executeJavaScript 递坐标、等它荡完。
 */
import { BrowserWindow, screen } from 'electron'

export type CuePoint = { x: number; y: number }
export type Cue = { pulse(at: CuePoint): Promise<void>; warm(): void; dispose(): void }
export type CueOptions = { log(line: string): void }

/** 光环荡开的时长。 */
export const PULSE_MS = 380

const PAGE = `<!doctype html><html><head><meta charset="utf-8"><style>
html, body { margin: 0; height: 100%; background: transparent; overflow: hidden; pointer-events: none; -webkit-user-select: none; }
.ring, .dot { position: absolute; left: 0; top: 0; border-radius: 50%; opacity: 0; will-change: transform, opacity; }
.ring { width: 44px; height: 44px; margin: -22px 0 0 -22px; border: 1.5px solid #A48CFF; box-shadow: 0 0 14px rgba(164, 140, 255, .5), inset 0 0 8px rgba(164, 140, 255, .25); }
.dot { width: 6px; height: 6px; margin: -3px 0 0 -3px; background: #A48CFF; box-shadow: 0 0 8px rgba(164, 140, 255, .9); }
</style></head><body><script>
window.pulse = p => new Promise(resolve => {
  document.body.textContent = ''
  const place = (cls) => { const el = document.createElement('div'); el.className = cls; el.style.transform = 'translate(' + p.x + 'px, ' + p.y + 'px)'; document.body.appendChild(el); return el }
  const ring = place('ring'), dot = place('dot')
  const at = (s) => 'translate(' + p.x + 'px, ' + p.y + 'px) scale(' + s + ')'
  const done = () => { ring.remove(); dot.remove(); resolve() }
  dot.animate([{ opacity: 1, transform: at(1) }, { opacity: 0, transform: at(.4) }], { duration: 300, easing: 'ease-out', fill: 'forwards' })
  ring.animate([{ opacity: .95, transform: at(.22) }, { opacity: 0, transform: at(1) }], { duration: ${PULSE_MS}, easing: 'cubic-bezier(.2, .7, .2, 1)', fill: 'forwards' })
    .finished.then(done, done)
})
</script></body></html>`

export function createCue(options: CueOptions): Cue {
  let window: BrowserWindow | null = null
  let loaded: Promise<void> | null = null
  let busy = 0
  let disposed = false
  const log = (line: string) => { try { options.log(`${line}\n`) } catch { /* 日志本身出错不影响。 */ } }

  /** 窗口只建一次、藏着复用；第一次用之前就预热，免得第一下要等页面加载。 */
  function ensure(): Promise<BrowserWindow | null> {
    if (disposed) return Promise.resolve(null)
    if (window && !window.isDestroyed() && loaded) return loaded.then(() => window)
    const win = new BrowserWindow({
      width: 800, height: 600, show: false, transparent: true, frame: false, hasShadow: false, resizable: false, movable: false,
      focusable: false, skipTaskbar: true, alwaysOnTop: true, fullscreenable: false, maximizable: false, minimizable: false,
      webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false },
    })
    win.setIgnoreMouseEvents(true)
    win.setAlwaysOnTop(true, 'screen-saver')
    if (process.platform === 'darwin') win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
    win.webContents.on('will-navigate', event => event.preventDefault())
    window = win
    loaded = win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(PAGE)}`)
      .catch(error => { log(`[cue] 光环页面没加载出来：${error instanceof Error ? error.message : String(error)}`) })
    return loaded.then(() => win)
  }

  async function pulse(at: CuePoint): Promise<void> {
    const win = await ensure()
    if (!win || win.isDestroyed()) return
    const { x, y, width, height } = screen.getDisplayNearestPoint(at).bounds
    win.setBounds({ x, y, width, height }, false)
    busy++
    try {
      win.showInactive()
      await win.webContents.executeJavaScript(`window.pulse(${JSON.stringify({ x: at.x - x, y: at.y - y })})`, true)
    } finally {
      if (--busy === 0 && !win.isDestroyed()) win.hide()
    }
  }

  return {
    pulse,
    warm() { void ensure() },
    dispose() {
      disposed = true
      if (window && !window.isDestroyed()) window.destroy()
      window = null
      loaded = null
    },
  }
}
