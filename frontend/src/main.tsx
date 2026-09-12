import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import { clientLog } from './api'
import { restoreTheme } from './theme'
import 'boxicons/css/boxicons.min.css'   // 图标字体（Trilium 同款，MIT）
import './shell.css'   // 先：定义令牌
import './styles.css'  // 后：老变量名指向那些令牌

restoreTheme()
// 探针下报一次首帧耗时（从文档开始加载到 React 首次渲染完成）——包体瘦身有没有效，看这个数
if (new URLSearchParams(location.search).get('probe')) requestAnimationFrame(() => void clientLog('warn', `first paint ${Math.round(performance.now())} ms · js ${Math.round((performance.getEntriesByType('resource') as PerformanceResourceTiming[]).filter((r) => r.name.endsWith('.js')).reduce((a, r) => a + (r.transferSize || r.encodedBodySize || 0), 0) / 1024)} KB`, '', 'first-paint'))
// 应用菜单「帮助 › 快捷键一览」→ 跟 ⌘/ 同一条路
// 退出前把没存的正文存完（App 里监听 flush-save，存完回 flushed）
window.memoketDesktop?.onFlush?.(() => window.dispatchEvent(new CustomEvent('flush-save')))
window.memoketDesktop?.onMenu?.((name) => {
  if (name === 'shortcuts') window.dispatchEvent(new CustomEvent('show-shortcuts'))
  if (name === 'export-all') window.dispatchEvent(new CustomEvent('export-all'))
})

// 没被任何 try 接住的错误也报上去
window.addEventListener('error', (e) => void clientLog('error', String(e.message), e.error?.stack ?? '', 'window'))
window.addEventListener('unhandledrejection', (e) => void clientLog('error', String(e.reason?.message ?? e.reason), e.reason?.stack ?? '', 'promise'))

// 红绿灯让位只在 macOS 需要（见 shell.css .tab-row-left-spacer）
if (/Mac/.test(navigator.platform)) document.documentElement.classList.add('is-mac')

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary><App /></ErrorBoundary>
  </React.StrictMode>,
)
