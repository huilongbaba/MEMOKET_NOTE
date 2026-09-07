import { useEffect, useRef, useState } from 'react'
import {
  addProfileEntry, ask, cancelJob, deleteProfileEntry, ingestBatch, jobStatus, listProfile,
  memoryFacts, memoryStats, recall, watchJob,
  appleAvailable, importApple, importFiles, importNotion,
} from '../api'
import type { Fact, FactDetail, JobOut, ProfileEntry } from '../api'
import { toast } from '../toast'
import DigestPanel from './DigestPanel'
import MemoryBrowser from './MemoryBrowser'

const STATUS_LABEL: Record<string, string> = {
  queued: '排队中', extracting: '提取文本', transcribing: '转写中',
  chunking: '切块', remembering: '抽取入库', done: '完成',
  failed: '失败', cancelled: '已取消', cancelling: '正在停止…',
}

/**
 * 知识库面板。两条检索路径的差异在这里直接暴露给用户：
 *   「检索」 —— 零 LLM 符号查询，毫秒级，写作路径用的就是它
 *   「提问」 —— KITE 原生 planning，支持时序推理，但要几十秒
 */
export default function MemoryPanel({ pendingJob }: { pendingJob: string }) {
  const [stats, setStats] = useState<{ facts: number; entities: number } | null>(null)
  const [q, setQ] = useState('')
  const [facts, setFacts] = useState<Fact[]>([])
  const [took, setTook] = useState<number | null>(null)
  const [answer, setAnswer] = useState('')
  const [busy, setBusy] = useState<'' | 'recall' | 'ask'>('')
  const [job, setJob] = useState('')
  const [batchJob, setBatchJob] = useState<JobOut | null>(null)
  const batchAbort = useRef<AbortController | null>(null)
  const [notionToken, setNotionToken] = useState('')
  const [importing, setImporting] = useState(false)
  const [apple, setApple] = useState<{ available: boolean; reason: string } | null>(null)
  const [browsing, setBrowsing] = useState(false)
  const [profile, setProfile] = useState<ProfileEntry[]>([])
  const [newPref, setNewPref] = useState('')
  const [addingPref, setAddingPref] = useState(false)
  const [recentFacts, setRecentFacts] = useState<FactDetail[]>([])
  const lastSeenFactCount = useRef(-1)

  const refresh = () => memoryStats().then(setStats).catch(() => {})
  useEffect(() => { refresh() }, [])
  useEffect(() => { listProfile().then(setProfile).catch(() => {}) }, [])
  useEffect(() => () => batchAbort.current?.abort(), [])

  /** 抽取是分块跑的（一个 chunk 一次 LLM 调用），每跑完一块 facts 数就会
   * 涨一次——这里跟着那个数字走，数字一变就去把最新的几条 fact 拉过来，
   * 做出"边抽取边看见内容"的效果，不用等整个任务跑完才一次性刷出来。 */
  function pollRecentFacts(factCount: number) {
    if (factCount > 0 && factCount !== lastSeenFactCount.current) {
      lastSeenFactCount.current = factCount
      memoryFacts({ limit: 3 }).then((r) => setRecentFacts(r.facts)).catch(() => {})
    }
  }

  // 入库是后台任务，轮询到 done 再刷新统计
  useEffect(() => {
    const id = pendingJob || job
    if (!id) return
    const timer = setInterval(async () => {
      try {
        const s = await jobStatus(id)
        pollRecentFacts(s.facts)
        if (s.status === 'done' || s.status === 'error') {
          clearInterval(timer)
          setJob('')
          setRecentFacts([])
          refresh()
          if (s.status === 'error') toast(`入库失败：${s.detail}`, 'error')
        }
      } catch { clearInterval(timer) }
    }, 3000)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingJob, job])

  async function doRecall() {
    setBusy('recall'); setAnswer('')
    try {
      const r = await recall(q)
      setFacts(r.facts); setTook(r.took_ms)
    } finally { setBusy('') }
  }

  async function doAsk() {
    setBusy('ask'); setAnswer('')
    try {
      const r = await ask(q)
      setAnswer(r.answer); setFacts(r.facts); setTook(r.took_ms)
    } finally { setBusy('') }
  }

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

  async function doBatchIngest(files: FileList | null) {
    if (!files || files.length === 0) return
    batchAbort.current?.abort()
    const controller = new AbortController()
    batchAbort.current = controller
    const r = await ingestBatch(Array.from(files))
    setBatchJob(r)
    watchJob(r.job_id, (j) => { setBatchJob(j); pollRecentFacts(j.facts) },
      () => { refresh(); setRecentFacts([]) }, controller.signal)
  }

  useEffect(() => { appleAvailable().then(setApple).catch(() => setApple(null)) }, [])

  async function doImport(files: File[], source: 'obsidian' | 'evernote') {
    if (!files.length) return
    setImporting(true)
    try {
      const r = await importFiles(files, source)
      setBatchJob(r)
      watchJob(r.job_id, (j) => { setBatchJob(j); pollRecentFacts(j.facts) },
        () => { refresh(); setRecentFacts([]) })
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    } finally {
      setImporting(false)
    }
  }

  async function doImportApple() {
    setImporting(true)
    try {
      const r = await importApple()
      setBatchJob(r)
      watchJob(r.job_id, (j) => { setBatchJob(j); pollRecentFacts(j.facts) },
        () => { refresh(); setRecentFacts([]) })
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    } finally {
      setImporting(false)
    }
  }

  async function doImportNotion() {
    setImporting(true)
    try {
      const r = await importNotion(notionToken.trim())
      setBatchJob(r)
      watchJob(r.job_id, (j) => { setBatchJob(j); pollRecentFacts(j.facts) },
        () => { refresh(); setRecentFacts([]) })
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    } finally {
      setImporting(false)
    }
  }

  async function doCancelBatch() {
    if (!batchJob) return
    await cancelJob(batchJob.job_id)
  }

  const working = pendingJob || job

  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0 }}>知识库</h2>
        <button onClick={() => setBrowsing(true)}>浏览</button>
      </div>
      <p className="muted">
        {stats ? `${stats.facts} 条事实 · ${stats.entities} 个实体` : '加载中…'}
        {working && <> · <span className="spinner" /> 抽取中</>}
      </p>
      {browsing && <MemoryBrowser onClose={() => setBrowsing(false)} />}

      <DigestPanel />

      {recentFacts.length > 0 && (
        <div className="stack" style={{ marginBottom: 10 }}>
          <p className="muted" style={{ fontSize: 12, margin: 0 }}>
            刚抽取到（抽取是分块跑的，每跑完一块就会多几条）：
          </p>
          {recentFacts.map((f) => (
            <div className="card" key={f.id} style={{ fontSize: 12 }}>{f.text}</div>
          ))}
        </div>
      )}

      <div className="stack">
        <input
          placeholder="搜索或提问…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && q.trim() && doRecall()}
        />
        <div className="row">
          <button onClick={doRecall} disabled={!q.trim() || !!busy}>
            {busy === 'recall' ? <span className="spinner" /> : '检索'}
          </button>
          <button onClick={doAsk} disabled={!q.trim() || !!busy}>
            {busy === 'ask' ? <span className="spinner" /> : '提问'}
          </button>
          {took !== null && <span className="muted">{took} ms</span>}
        </div>
        <p className="muted" style={{ fontSize: 12 }}>
          检索是符号查询，毫秒级；提问会让模型编译查询计划，支持「现在谁负责」
          这类时序推理，但要等几十秒。
        </p>
      </div>

      {answer && (
        <div className="card" style={{ marginTop: 10 }}>
          <strong>{answer}</strong>
        </div>
      )}

      {facts.map((f) => (
        <div className="card" key={f.id}>
          <div>{f.text}</div>
          {f.when && <span className="badge">{f.when}</span>}
          {f.sources.map((s, i) => (
            <p className="muted" key={i} style={{ margin: '6px 0 0' }}>出处：{s}</p>
          ))}
        </div>
      ))}

      <h2>个人偏好</h2>
      <p className="muted" style={{ fontSize: 12 }}>
        跟知识库是两回事——这里不走抽取，写完立刻生效。写作骨架/智能编辑/magic tap
        续写都会读取，让输出贴合这些偏好。
      </p>
      <div className="stack">
        <div className="row">
          <input
            placeholder="比如：喜欢简洁的语言、写周报先说结论再列数据…"
            value={newPref}
            onChange={(e) => setNewPref(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && doAddPref()}
            style={{ flex: 1 }}
          />
          <button onClick={doAddPref} disabled={!newPref.trim() || addingPref}>
            {addingPref ? <span className="spinner" /> : '添加'}
          </button>
        </div>
        {profile.map((p) => (
          <div className="card" key={p.id}>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <span>{p.text}</span>
              <a className="link" onClick={() => doDeletePref(p.id)}>✕</a>
            </div>
          </div>
        ))}
      </div>

      <h2>从其他应用导入</h2>
      <div className="stack">
        <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
          按来源清洗后导入：保留原始日期和文件夹结构，去掉各家的私有语法
          （<code>[[wiki 链接]]</code>、<code>![[附件]]</code>、dataview 块、
          Evernote 的附件占位）。<strong>重复导入是增量的</strong>——已经导过的
          内容会被跳过，不会翻倍也不会重新花抽取的时间。
        </p>

        <label className="row" style={{ gap: 8, alignItems: 'center' }}>
          <span style={{ width: 88 }}>Obsidian</span>
          <input
            type="file"
            multiple
            /* 选整个 vault：浏览器会带上 webkitRelativePath，服务端靠它还原
               文件夹结构。React 不认识这两个属性，要用 ref 回调设上去。 */
            ref={(el) => {
              if (el) {
                el.setAttribute('webkitdirectory', '')
                el.setAttribute('directory', '')
              }
            }}
            onChange={(e) => doImport(Array.from(e.target.files ?? []), 'obsidian')}
          />
        </label>
        <p className="muted" style={{ fontSize: 11, margin: '0 0 6px 96px' }}>
          选整个 vault 目录。<code>.obsidian/</code> 和 <code>.trash/</code> 会自动跳过。
        </p>

        <label className="row" style={{ gap: 8, alignItems: 'center' }}>
          <span style={{ width: 88 }}>Evernote</span>
          <input
            type="file"
            multiple
            accept=".enex"
            onChange={(e) => doImport(Array.from(e.target.files ?? []), 'evernote')}
          />
        </label>
        <p className="muted" style={{ fontSize: 11, margin: '0 0 6px 96px' }}>
          在 Evernote 里「导出笔记本为 .enex」，然后把文件选进来。
        </p>

        <div className="row" style={{ gap: 8, alignItems: 'center' }}>
          <span style={{ width: 88 }}>Notion</span>
          <input
            type="password"
            placeholder="Integration token（ntn_… / secret_…）"
            value={notionToken}
            onChange={(e) => setNotionToken(e.target.value)}
            style={{ flex: 1, minWidth: 0 }}
          />
          <button onClick={doImportNotion} disabled={!notionToken.trim() || importing}>
            {importing ? <span className="spinner" /> : '导入'}
          </button>
        </div>
        <p className="muted" style={{ fontSize: 11, margin: '0 0 6px 96px' }}>
          要先在 Notion 里把目标页面 <strong>Connect 给这个 integration</strong>，
          否则会一条都取不到——这是最常见的「导了但是空的」原因。
        </p>

        <div className="row" style={{ gap: 8, alignItems: 'center' }}>
          <span style={{ width: 88 }}>Apple Notes</span>
          <button onClick={doImportApple} disabled={!apple?.available || importing}>
            {importing ? <span className="spinner" /> : '导入全部备忘录'}
          </button>
        </div>
        <p className="muted" style={{ fontSize: 11, margin: '0 0 6px 96px' }}>
          {apple?.available
            ? '第一次导入时 macOS 会弹一个「允许控制「备忘录」」的授权框，点允许即可。'
            : `这台机器上不可用：${apple?.reason || '检测中…'}`}
        </p>
      </div>

      <h2>批量导入</h2>
      <div className="stack">
        <input
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md,.markdown,.wav,.mp3,.m4a,.flac"
          onChange={(e) => doBatchIngest(e.target.files)}
        />
        <p className="muted" style={{ fontSize: 12 }}>
          支持 PDF / DOCX / TXT / MD / 音频混合上传，每个文件独立处理，某一个失败不影响其他文件。
        </p>
        {batchJob && (
          <div className="card">
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <strong>
                {batchJob.status === 'running' || batchJob.status === 'queued' || batchJob.status === 'cancelling'
                  ? <><span className="spinner" /> 处理中…</>
                  : STATUS_LABEL[batchJob.status] ?? batchJob.status}
                {' · '}{batchJob.facts} 条事实
              </strong>
              {(batchJob.status === 'running' || batchJob.status === 'queued') && (
                <button onClick={doCancelBatch}>取消</button>
              )}
            </div>
            {batchJob.items.map((it) => (
              <div key={it.id} className="row" style={{ justifyContent: 'space-between', marginTop: 6 }}>
                <span>{it.filename}</span>
                <span className="muted">
                  {STATUS_LABEL[it.status] ?? it.status}
                  {(it.status === 'remembering' || it.status === 'done') && it.facts > 0 && ` · 已抽取 ${it.facts} 条`}
                  {it.status === 'failed' && it.detail && ` · ${it.detail}`}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
