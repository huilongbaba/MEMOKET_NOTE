import { useSyncExternalStore } from 'react'
import { dismissToast, getSnapshot, subscribe } from '../toast'

export default function Toaster() {
  const toasts = useSyncExternalStore(subscribe, getSnapshot)
  if (toasts.length === 0) return null
  return (
    <div className="toaster">
      {toasts.map((t) => (
        <div key={t.id} className={'toast ' + t.kind}>
          <span onClick={() => dismissToast(t.id)} title="点击关闭" style={{ cursor: 'pointer' }}>
            {t.message}
          </span>
          {/* 真按钮：没有 href 的 <a> Tab 走不到，「撤销」这种 5 秒窗口的动作键盘用户按不着（第 507 轮） */}
          {t.action && (
            <button className="linklike" style={{ marginLeft: 10 }} onClick={t.action.onClick}>
              {t.action.label}
            </button>
          )}
        </div>
      ))}
    </div>
  )
}
