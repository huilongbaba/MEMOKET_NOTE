import { useEffect, useState } from 'react'
import * as api from '../api'
import type { Skill, SkillIn, SkillScope } from '../api'
import { parseSkillMd } from '../skillImport'
import { toast, toastAction } from '../toast'

const EMPTY_FORM: SkillIn = { name: '', description: '', scopes: [], content: '', enabled: true }

/**
 * 把写作 prompt 系统"skill 化"后的管理面板：每条 skill 是一段额外叠加在
 * 某个生成调用点（scope）基础 prompt 之后的指令，可以开关、可以排序、
 * 可以自建。请求的具体内容在哪些调用点生效由 scopes 决定——排序用上下
 * 箭头挪动，不是拖拽，够用且不用额外引入 DnD 依赖。
 */
export default function SkillsPanel({ onClose }: { onClose: () => void }) {
  const [skills, setSkills] = useState<Skill[]>([])
  const [scopes, setScopes] = useState<SkillScope[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<'new' | string | null>(null)
  const [form, setForm] = useState<SkillIn>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)

  // 导入第三方 skill：贴 SKILL.md 原文 / 传 URL 抓取 / 上传 .md 文件，三选
  // 一，解析完都落进同一个 review 表单，跟手动新建、AI 生成走的是同一套
  // "先预览再保存"流程，不会解析完就直接落库。
  const [showImport, setShowImport] = useState(false)
  const [importRaw, setImportRaw] = useState('')
  const [importUrl, setImportUrl] = useState('')
  const [importFetching, setImportFetching] = useState(false)

  const [showGenerate, setShowGenerate] = useState(false)
  const [generateGoal, setGenerateGoal] = useState('')
  const [generating, setGenerating] = useState(false)

  function reload() {
    Promise.all([api.listSkills(), api.listSkillScopes()]).then(([s, sc]) => {
      setSkills(s)
      setScopes(sc)
      setLoading(false)
    })
  }
  useEffect(reload, [])

  function scopeLabel(value: string) {
    return scopes.find((s) => s.value === value)?.label ?? value
  }

  async function toggle(skill: Skill) {
    const updated = await api.toggleSkill(skill.id)
    setSkills((prev) => prev.map((s) => (s.id === skill.id ? updated : s)))
  }

  async function move(skill: Skill, dir: -1 | 1) {
    const idx = skills.findIndex((s) => s.id === skill.id)
    const swapWith = idx + dir
    if (swapWith < 0 || swapWith >= skills.length) return
    const next = [...skills]
    ;[next[idx], next[swapWith]] = [next[swapWith], next[idx]]
    setSkills(next) // 乐观更新，先让面板看起来立刻挪动了
    await api.reorderSkills(next.map((s) => s.id))
  }

  function startEdit(skill: Skill) {
    setEditing(skill.id)
    setForm({ name: skill.name, description: skill.description, scopes: skill.scopes,
              content: skill.content, enabled: skill.enabled })
  }

  function startNew() {
    setEditing('new')
    setForm(EMPTY_FORM)
  }

  /** 解析完的三个入口（贴文本/传 URL/传文件）都走这一个函数——name/
   * description 能解析出来就填，scopes 永远留空：一份 SKILL.md 是写给
   * Claude Code 自己的 agent 循环用的，不知道 MEMOKET_NOTE 这边的哪个
   * scope 对应，必须用户自己选。 */
  function applyImportedText(raw: string) {
    const parsed = parseSkillMd(raw)
    setForm({ name: parsed.name, description: parsed.description, scopes: [],
              content: parsed.content, enabled: true })
    setShowImport(false)
    setImportRaw('')
    setImportUrl('')
    setEditing('new')
    if (!parsed.name) {
      toast('没解析到标准的 SKILL.md frontmatter，名称/描述留空了，正文已经填进去了，检查一下内容对不对')
    }
  }

  async function fetchImportUrl() {
    if (!importUrl.trim()) return
    setImportFetching(true)
    try {
      const res = await fetch(importUrl.trim())
      if (!res.ok) throw new Error(`${res.status}`)
      const text = await res.text()
      applyImportedText(text)
    } catch (e) {
      toast(`抓取失败：${e}——大概率是跨域限制，改成手动粘贴 SKILL.md 内容`, 'error')
    } finally {
      setImportFetching(false)
    }
  }

  function handleFileUpload(file: File | undefined) {
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => applyImportedText(String(reader.result ?? ''))
    reader.readAsText(file)
  }

  async function generate() {
    if (!generateGoal.trim()) return
    setGenerating(true)
    try {
      const draft = await api.generateSkill(generateGoal.trim())
      setForm(draft)
      setShowGenerate(false)
      setGenerateGoal('')
      setEditing('new')
    } catch (e) {
      toast('生成失败：' + e, 'error')
    } finally {
      setGenerating(false)
    }
  }

  function toggleFormScope(value: string) {
    setForm((f) => ({
      ...f,
      scopes: f.scopes.includes(value) ? f.scopes.filter((v) => v !== value) : [...f.scopes, value],
    }))
  }

  async function save() {
    if (!form.name.trim() || !form.content.trim() || form.scopes.length === 0) {
      toast('名称、生效范围、内容都不能为空', 'error')
      return
    }
    setSaving(true)
    try {
      if (editing === 'new') {
        await api.createSkill(form)
      } else if (editing) {
        await api.updateSkill(editing, form)
      }
      setEditing(null)
      reload()
    } catch (e) {
      toast('保存失败：' + e, 'error')
    } finally {
      setSaving(false)
    }
  }

  /** 同一套乐观删除+撤销 toast 模式，跟笔记/文件夹删除一致（见 App.tsx
   * 的 remove()/removeFolder()）——不用 confirm() 弹窗。 */
  function remove(skill: Skill) {
    setSkills((prev) => prev.filter((s) => s.id !== skill.id))
    let undone = false
    const timer = setTimeout(() => {
      if (!undone) api.deleteSkill(skill.id).catch(() => {})
    }, 5000)
    toastAction(`已删除「${skill.name}」`, '撤销', () => {
      undone = true
      clearTimeout(timer)
      reload()
    })
  }

  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div
        className="modal"
        style={{ background: 'var(--bg)', border: '1px solid var(--line)', borderRadius: 10,
                maxWidth: 720, width: '92vw', maxHeight: '84vh', overflowY: 'auto', padding: 24 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2 style={{ margin: 0 }}>🧩 写作 Skill</h2>
          <button onClick={onClose}>✕</button>
        </div>
        <p className="muted" style={{ fontSize: 13, margin: '6px 0 12px' }}>
          每条 skill 是叠加在某个生成动作（续写/校验/重写…）基础规则之后的额外指令，可以开关、排序、自建。
        </p>

        {loading ? (
          <span className="spinner" />
        ) : editing ? (
          <div className="stack">
            <input
              placeholder="名称"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
            <input
              placeholder="一句话描述（可选）"
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
            <div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>生效范围（至少选一个）</div>
              <div className="row" style={{ flexWrap: 'wrap', gap: 4 }}>
                {scopes.map((sc) => (
                  <label
                    key={sc.value}
                    className="badge"
                    style={{ cursor: 'pointer', background: form.scopes.includes(sc.value) ? 'var(--accent)' : undefined,
                            color: form.scopes.includes(sc.value) ? '#fff' : undefined }}
                  >
                    <input
                      type="checkbox"
                      checked={form.scopes.includes(sc.value)}
                      onChange={() => toggleFormScope(sc.value)}
                      style={{ display: 'none' }}
                    />
                    {sc.label}
                  </label>
                ))}
              </div>
            </div>
            <textarea
              rows={6}
              placeholder="具体的指令内容——会原样叠加在对应生成动作的基础规则之后"
              value={form.content}
              onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
            />
            <label className="row" style={{ fontSize: 13 }}>
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
              />
              启用
            </label>
            <div className="row">
              <button className="primary" onClick={save} disabled={saving}>
                {saving ? <span className="spinner" /> : '保存'}
              </button>
              <button onClick={() => setEditing(null)}>取消</button>
            </div>
          </div>
        ) : showImport ? (
          <div className="stack">
            <p className="muted" style={{ fontSize: 12 }}>
              导入 Claude Skill 的 SKILL.md（yaml frontmatter + markdown 正文）——只会用到 name/description/正文，
              技能包常带的脚本/参考文件用不上（MEMOKET_NOTE 调的是原始接口，没法"运行"那些）。
            </p>
            <div className="row">
              <input
                placeholder="SKILL.md 的原始文件 URL（比如 raw.githubusercontent.com/...）"
                value={importUrl}
                onChange={(e) => setImportUrl(e.target.value)}
                style={{ flex: 1 }}
              />
              <button onClick={fetchImportUrl} disabled={importFetching || !importUrl.trim()}>
                {importFetching ? <span className="spinner" /> : '抓取'}
              </button>
            </div>
            <label className="muted" style={{ fontSize: 12, cursor: 'pointer' }}>
              或上传本地 .md 文件
              <input type="file" accept=".md,.markdown,.txt" style={{ display: 'none' }}
                     onChange={(e) => handleFileUpload(e.target.files?.[0])} />
            </label>
            <textarea
              rows={8}
              placeholder="或者直接把 SKILL.md 的内容粘贴在这里"
              value={importRaw}
              onChange={(e) => setImportRaw(e.target.value)}
            />
            <div className="row">
              <button className="primary" onClick={() => applyImportedText(importRaw)} disabled={!importRaw.trim()}>
                解析并预览
              </button>
              <button onClick={() => { setShowImport(false); setImportRaw(''); setImportUrl('') }}>取消</button>
            </div>
          </div>
        ) : showGenerate ? (
          <div className="stack">
            <p className="muted" style={{ fontSize: 12 }}>用一两句话描述想要的写作行为，让模型草拟一条 skill——生成完还是会给你预览，改好、选好生效范围再保存。</p>
            <textarea
              rows={3}
              placeholder="比如：续写时遇到具体的会议决定要直接用原话，不要转述得太抽象"
              value={generateGoal}
              onChange={(e) => setGenerateGoal(e.target.value)}
            />
            <div className="row">
              <button className="primary" onClick={generate} disabled={generating || !generateGoal.trim()}>
                {generating ? <span className="spinner" /> : '生成'}
              </button>
              <button onClick={() => { setShowGenerate(false); setGenerateGoal('') }}>取消</button>
            </div>
          </div>
        ) : (
          <div className="stack">
            <div className="row">
              <button onClick={startNew}>+ 新建 skill</button>
              <button onClick={() => setShowImport(true)}>📥 导入第三方 Skill</button>
              <button onClick={() => setShowGenerate(true)}>🪄 AI 生成</button>
            </div>
            {skills.map((sk, i) => (
              <div key={sk.id} className="card">
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <div className="row" style={{ gap: 6 }}>
                    <button
                      title={sk.enabled ? '点击关闭' : '点击启用'}
                      onClick={() => toggle(sk)}
                      style={{ padding: '2px 8px', borderColor: sk.enabled ? 'var(--ins)' : undefined,
                              color: sk.enabled ? 'var(--ins)' : 'var(--muted)' }}
                    >
                      {sk.enabled ? '● 已启用' : '○ 已关闭'}
                    </button>
                    <strong>{sk.name}</strong>
                    {sk.builtin && <span className="muted" style={{ fontSize: 11 }}>内置</span>}
                  </div>
                  <div className="row" style={{ gap: 2 }}>
                    <button onClick={() => move(sk, -1)} disabled={i === 0} title="上移">↑</button>
                    <button onClick={() => move(sk, 1)} disabled={i === skills.length - 1} title="下移">↓</button>
                    <button onClick={() => startEdit(sk)} title="编辑">✎</button>
                    <button onClick={() => remove(sk)} title="删除（5 秒内可撤销）">✕</button>
                  </div>
                </div>
                {sk.description && <p className="muted" style={{ fontSize: 12, margin: '4px 0' }}>{sk.description}</p>}
                <div className="row" style={{ gap: 4, flexWrap: 'wrap' }}>
                  {sk.scopes.map((s) => <span key={s} className="badge">{scopeLabel(s)}</span>)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
