import { useState } from 'react'
import * as api from '../api'

/**
 * getUser() auto-assigns a random `user-xxxxxx` id to a browser on first
 * visit (see api.ts) and there was previously no UI to change it -- every
 * knowledge base import via API/script (e.g. a named demo user) was
 * permanently invisible from the app itself. A full reload after switching
 * is the simplest correct way to reset every piece of per-note React state
 * without hand-auditing each one.
 */
export default function UserSwitcher() {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(api.getUser())

  function submit() {
    api.setUser(value)
    window.location.reload()
  }

  if (!editing) {
    return (
      <p className="muted" style={{ fontSize: 12 }}>
        用户 {api.getUser()}{' '}
        <a className="link" onClick={() => setEditing(true)}>切换</a>
      </p>
    )
  }

  return (
    <div className="row" style={{ marginBottom: 4 }}>
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && submit()}
        onFocus={(e) => e.target.select()}
        style={{ fontSize: 12, padding: '4px 6px' }}
        autoFocus
      />
      <button onClick={submit}>确定</button>
    </div>
  )
}
