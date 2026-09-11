import { useState } from 'react'
import * as api from '../api'
import { TextPrompt } from './Dialogs'

/**
 * 启动栏最底下的用户头像（对标 Trilium 启动栏底部的 GlobalMenu）。
 *
 * getUser() 第一次访问会随机分一个 `user-xxxxxx`，以前没有任何界面能改它——
 * 用脚本导进某个具名用户的知识库，从应用里永远看不到。切换后整页 reload，
 * 是把每一份按笔记的 React 状态一次清干净最省事也最正确的办法。
 */
export default function UserSwitcher() {
  const [asking, setAsking] = useState(false)
  const user = api.getUser()
  return (
    <>
      <button className="launcher-btn launcher-user" title={`当前用户：${user}\n点击切换`}
              onClick={() => setAsking(true)}>
        <span className="avatar">{(user[0] ?? '?').toUpperCase()}</span>
      </button>
      {asking && (
        <TextPrompt req={{ title: '切换用户（每个用户一个独立的笔记库和知识库）', initial: user,
          resolve: (v) => { setAsking(false); if (v && v.trim() && v.trim() !== user) { api.setUser(v.trim()); window.location.reload() } } }} />
      )}
    </>
  )
}
