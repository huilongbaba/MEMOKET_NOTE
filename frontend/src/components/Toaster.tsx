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
          {t.action && (
            <a className="link" style={{ marginLeft: 10 }} onClick={t.action.onClick}>
              {t.action.label}
            </a>
          )}
        </div>
      ))}
    </div>
  )
}
