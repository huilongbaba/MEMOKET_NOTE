/**
 * 个人偏好——跟知识库是两回事：不走抽取，写完立刻生效，写作骨架 / 智能编辑 /
 * magic tap 续写都会读。放在「设置」里（原来挤在右栏的知识库面板里）。
 */
import { useEffect, useState } from 'react'
import { addProfileEntry, deleteProfileEntry, listProfile } from '../api'
import type { ProfileEntry } from '../api'
import Icon from './Icon'

export default function PreferencesPanel() {
  const [profile, setProfile] = useState<ProfileEntry[]>([])
  const [newPref, setNewPref] = useState('')
  const [addingPref, setAddingPref] = useState(false)
  useEffect(() => { listProfile().then(setProfile).catch(() => {}) }, [])

  async function doAddPref() {
    if (!newPref.trim()) return
    setAddingPref(true)
    try {
      const entry = await addProfileEntry(newPref.trim())
      setProfile((prev) => [entry, ...prev])
      setNewPref('')
    } finally { setAddingPref(false) }
  }

  async function doDeletePref(id: string) {
    await deleteProfileEntry(id)
    setProfile((prev) => prev.filter((p) => p.id !== id))
  }

  return (
    <div className="stack">
      <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: 0 }}>
        跟知识库是两回事——这里不走抽取，写完立刻生效。写作骨架 / 智能编辑 / magic tap 续写都会读取。
      </p>
      <div className="stack">
        <div className="row">
          <input aria-label="写作偏好"
            maxLength={400}   /* 跟后端 profile.MAX_CHARS 一致：一条是一句话，不是一篇文章 */
            placeholder="比如：喜欢简洁的语言、写周报先说结论再列数据…"
            value={newPref}
            onChange={(e) => setNewPref(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && doAddPref()}
            style={{ flex: 1 }}
          />
          <button onClick={doAddPref} disabled={!newPref.trim() || addingPref} title={!newPref.trim() ? '先写一条偏好' : undefined}>
            {addingPref ? <span className="spinner" /> : '添加'}
          </button>
        </div>
        {profile.map((p) => (
          <div className="card" key={p.id}>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <span>{p.text}</span>
              <button className="icon-btn" aria-label="删掉这条" title="删掉这条" onClick={() => doDeletePref(p.id)}><Icon n="bx-x" /></button>
            </div>
          </div>
        ))}
      </div>

    </div>
  )
}
