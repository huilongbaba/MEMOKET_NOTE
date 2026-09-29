import { useState } from 'react'
import * as api from '../api'
import { toast } from '../toast'
import { TextPrompt } from './Dialogs'
import Icon from './Icon'

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
              aria-label={`切换工作空间，当前用户 ${user}`}
              onClick={() => setAsking(true)}>
        <span className="avatar">{(user[0] ?? '?').toUpperCase()}</span>
        <span className="ws-profile-copy"><strong>个人工作空间</strong><small>笔记 · 知识 · 行动</small></span>
        <Icon n="bx-chevron-down" />
      </button>
      {asking && (
        <TextPrompt req={{ title: '切换用户（每个用户一个独立的笔记库和知识库）', initial: user,
          resolve: (v) => {
            setAsking(false)
            const next = (v ?? '').trim()
            if (!next || next === user) return
            // 用户名要拼进后端的数据目录、还要塞进 HTTP 头：只认字母数字 _ . -（后端同一条正则，不然 400）
            if (!/^[A-Za-z0-9_.-]{1,64}$/.test(next)) { toast('用户名只能用字母、数字、_ . -，最长 64 个字符', 'error'); return }
            api.setUser(next)
            const url = new URL(window.location.href)
            url.searchParams.set('user', next)
            window.location.replace(url.href)
          } }} />
      )}
    </>
  )
}
