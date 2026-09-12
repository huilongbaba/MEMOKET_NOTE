import { useEffect, useRef, useState } from 'react'
import {
  cancelJob, ingestBatch, jobStatus, memoryFacts, memoryStats, watchJob,
  appleAvailable, importApple, importFiles, importNotion,
} from '../api'
import type { FactDetail, JobOut } from '../api'
import { toast } from '../toast'

const STATUS_LABEL: Record<string, string> = {
  queued: '排队中', extracting: '提取文本', transcribing: '转写中',
  chunking: '切块', remembering: '抽取入库', done: '完成',
  failed: '失败', cancelled: '已取消', cancelling: '正在停止…',
}

/**
 * 导入面板：从其他应用导入 + 批量导入 + 抽取进度。原来是右栏的「知识库」
 * 面板，还塞着搜索（去 ⌘K）、阶段回顾（去树上「定期回顾」）、个人偏好（去设置）
 * ——五种不相干的东西叠在 300px 里。现在只剩「把东西导进来」这一件事，
 * 作为特殊笔记 app:import 占中栏。
 */
export default function MemoryPanel({ pendingJob }: { pendingJob: string }) {
  const [stats, setStats] = useState<{ facts: number; entities: number } | null>(null)
  const [job, setJob] = useState('')
  const [batchJob, setBatchJob] = useState<JobOut | null>(null)
  const batchAbort = useRef<AbortController | null>(null)
  const [notionToken, setNotionToken] = useState('')
  const [importing, setImporting] = useState(false)
  // 导到哪：一个几百篇的 vault 全抽进知识库要跑很久，得让人选
  const [importTo, setImportTo] = useState<'both' | 'kb' | 'notes'>('both')
  const [apple, setApple] = useState<{ available: boolean; reason: string } | null>(null)
  const [recentFacts, setRecentFacts] = useState<FactDetail[]>([])
  const lastSeenFactCount = useRef(-1)

  const refresh = () => memoryStats().then(setStats).catch(() => {})
  useEffect(() => { refresh() }, [])
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
      const r = await importFiles(files, source, importTo)
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
      const r = await importApple(importTo)
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
      const r = await importNotion(notionToken.trim(), importTo)
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
      <p className="muted" style={{ fontSize: 12 }}>
        知识库现在 {stats ? `${stats.facts} 条事实 · ${stats.entities} 个实体` : '…'}
        {working && <> · <span className="spinner" /> 抽取中</>}
        {' '}· <a href="#" onClick={(e) => { e.preventDefault(); window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb:overview' })) }}>看总览</a>
      </p>

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

      <h2>从其他应用导入</h2>
      <div className="stack">
        <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
          按来源清洗后导入：保留原始日期和文件夹结构，去掉各家的私有语法
          （<code>[[wiki 链接]]</code>、<code>![[附件]]</code>、dataview 块、
          Evernote 的附件占位）。<strong>重复导入是增量的</strong>——已经导过的
          内容会被跳过，不会翻倍也不会重新花抽取的时间。
        </p>

        <label className="row" style={{ gap: 8, alignItems: 'center' }}>
          <span style={{ width: 88 }}>导入到</span>
          <select value={importTo} onChange={(e) => setImportTo(e.target.value as 'both' | 'kb' | 'notes')} disabled={importing}>
            <option value="both">笔记 + 知识库（逐篇抽事实，篇数多会跑很久）</option>
            <option value="notes">只进笔记（之后可以对单篇「存入知识库」）</option>
            <option value="kb">只进知识库（不建笔记）</option>
          </select>
        </label>
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
