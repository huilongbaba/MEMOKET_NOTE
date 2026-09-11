import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import { clientLog } from './api'
import 'boxicons/css/boxicons.min.css'   // 图标字体（Trilium 同款，MIT）
import './shell.css'   // 先：定义令牌
import './styles.css'  // 后：老变量名指向那些令牌

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
