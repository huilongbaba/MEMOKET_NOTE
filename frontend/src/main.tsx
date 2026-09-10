import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './shell.css'   // 先：定义令牌
import './styles.css'  // 后：老变量名指向那些令牌

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
