/**
 * 渲染进程唯一能碰到主进程的口子。只暴露一件事：换主题——界面的暗色
 * 全靠 `prefers-color-scheme`，而 Electron 里那个值由 nativeTheme.themeSource
 * 决定，所以「设置里选深色」必须绕到主进程去改它，CSS 一行不用动。
 */
import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('memoketDesktop', {
  setTheme(theme: 'system' | 'light' | 'dark') { ipcRenderer.send('set-theme', theme) },
  /** 应用菜单里点了「帮助 › 快捷键」这类要界面响应的项 */
  onMenu(cb: (name: string) => void) { ipcRenderer.on('menu', (_e, name: string) => cb(name)) },
  /** 退出前主进程问一句「还有没存的吗」；界面存完回 flushed() */
  onFlush(cb: () => void) { ipcRenderer.on('flush', () => cb()) },
  flushed() { ipcRenderer.send('flushed') },
  /** 界面定下了当前身份：主进程记进 identity.json，localStorage 丢了也认得回来 */
  rememberUser(user: string) { ipcRenderer.send('remember-user', user) },
  /** **我这个窗口该连的是哪个后端**（P45 #2）：壳起的那个子进程的 pid / 端口 / 数据目录。
   *  界面拿它跟 `/api/health` 里后端自报的那一份对一次——对不上说明这一屏摆的是
   *  另一份实例的库（P44 问题 #2 实拍）。还没起来回 null。 */
  backendInfo(): Promise<{ port: number; pid: number; dataDir: string } | null> {
    return ipcRenderer.invoke('backend:info')
  },
  /** 弹系统的选文件夹对话框（导回 Obsidian 选 vault）；取消返回空串 */
  pickDirectory(title: string): Promise<string> { return ipcRenderer.invoke('pick-directory', title) },
  /** 导回 Notion / 飞书的凭证：记在主进程的 export-credentials.json（identity.json 旁边），网页版没有这个口子 */
  exportCreds: {
    load(): Promise<Record<string, string>> { return ipcRenderer.invoke('export-creds:load') },
    save(patch: Record<string, string>): Promise<void> { return ipcRenderer.invoke('export-creds:save', patch) },
  },

  /** 屏幕活动（Daily Journey）。**采集在主进程里**——它要常驻、要在窗口关掉之后
   *  继续、要响应锁屏，这些渲染层都做不到。界面只是这个状态的一个视图：
   *  菜单栏那个图标是另一个（docs/daily-journey-plan.md §8.3）。 */
  /** 幻灯片 → PDF：主进程在离屏窗口里 printToPDF（零新依赖）。
   *  返回存到哪；用户取消返回空串。 */
  slidesToPdf(html: string, name: string): Promise<string> {
    return ipcRenderer.invoke('slides:pdf', html, name)
  },
  journey: {
    state(): Promise<{ state: 'off' | 'running' | 'paused' | 'no-permission'; today: number }> {
      return ipcRenderer.invoke('journey:state')
    },
    start(): Promise<void> { return ipcRenderer.invoke('journey:start') },
    pause(minutes?: number): Promise<void> { return ipcRenderer.invoke('journey:pause', minutes) },
    resume(): Promise<void> { return ipcRenderer.invoke('journey:resume') },
    stop(): Promise<void> { return ipcRenderer.invoke('journey:stop') },
  },
})
