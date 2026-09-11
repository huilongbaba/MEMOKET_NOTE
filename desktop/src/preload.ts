/**
 * 渲染进程唯一能碰到主进程的口子。只暴露一件事：换主题——界面的暗色
 * 全靠 `prefers-color-scheme`，而 Electron 里那个值由 nativeTheme.themeSource
 * 决定，所以「设置里选深色」必须绕到主进程去改它，CSS 一行不用动。
 */
import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('memoketDesktop', {
  setTheme(theme: 'system' | 'light' | 'dark') { ipcRenderer.send('set-theme', theme) },
})
