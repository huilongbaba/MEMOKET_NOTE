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
  /** 弹系统的选文件夹对话框（导回 Obsidian 选 vault）；取消返回空串 */
  pickDirectory(title: string): Promise<string> { return ipcRenderer.invoke('pick-directory', title) },
})
