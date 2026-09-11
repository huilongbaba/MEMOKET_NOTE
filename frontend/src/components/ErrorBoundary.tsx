/**
 * 渲染进程的最后一道防线。React 在渲染中抛了未捕获异常会把整棵树卸掉——用户
 * 看到一片白，什么都点不了（实拍：打包版「挂了」，后端还在正常写库）。
 * 这里把错误摆出来、报给后端日志、给一个「重新加载」。
 */
import { Component, type ReactNode } from 'react'

import { clientLog } from '../api'

type S = { error: Error | null; info: string }

export default class ErrorBoundary extends Component<{ children: ReactNode }, S> {
  state: S = { error: null, info: '' }
  static getDerivedStateFromError(error: Error): Partial<S> { return { error } }
  componentDidCatch(error: Error, info: { componentStack?: string }) {
    this.setState({ info: info.componentStack ?? '' })
    void clientLog('error', error.message, (error.stack ?? '') + '\n--- component stack ---' + (info.componentStack ?? ''), 'render')
  }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div style={{ padding: 32, maxWidth: 760, margin: '0 auto', fontFamily: 'system-ui' }}>
        <h2 style={{ textTransform: 'none', fontSize: 18 }}>界面出错了，正文没丢</h2>
        <p style={{ color: '#666' }}>自动保存一直在跑，笔记在库里。重新加载就能回来；错误已经记进日志。</p>
        <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, background: 'rgba(127,127,127,.1)', padding: 12, borderRadius: 8 }}>
          {this.state.error.message}{'\n'}{this.state.info.split('\n').slice(0, 8).join('\n')}
        </pre>
        <button onClick={() => window.location.reload()}>重新加载</button>
      </div>
    )
  }
}
