import { useEffect, useRef, useState } from 'react'
import {
  cancelJob, ingestBatch, jobStatus, listJobs, memoryFacts, memoryStats, resumeImportJob, watchJob,
  appleAvailable, importApple, importFeishu, importFiles, importNotion,
} from '../api'
import type { FactDetail, JobOut } from '../api'
import { toast } from '../toast'
import ExportBack from './ExportBack'

const STATUS_LABEL: Record<string, string> = {
  queued: '排队中', extracting: '提取文本', transcribing: '转写中',
  chunking: '切块', remembering: '抽取入库', done: '完成',
  failed: '失败', cancelled: '已取消', cancelling: '正在停止…', interrupted: '被打断（可继续）',
}

const fmtDur = (s: number) => (s < 60 ? `${s} 秒` : s < 3600 ? `${Math.round(s / 60)} 分钟` : `${(s / 3600).toFixed(1)} 小时`)
const fmtTokens = (n: number) => (n >= 10000 ? `${(n / 10000).toFixed(1)} 万` : String(n))

/** 进度条 + 预估 + 用量。批量导入是小时级的活，用户点下去之前、跑的过程中都该知道要多久、花多少。 */
function JobProgress({ j }: { j: JobOut }) {
  const total = j.chunks_total ?? 0
  const done = j.chunks_done ?? 0
  const running = j.status === 'running' || j.status === 'queued' || j.status === 'cancelling'
  return (
    <div className="stack" style={{ gap: 4, marginTop: 6 }}>
      {total > 0 && (
        <div className="progress" title={`${done}/${total} 块`}><div className="progress-bar" style={{ width: `${Math.min(100, Math.round(done / total * 100))}%` }} /></div>
      )}
      <div className="muted" style={{ fontSize: 12 }}>
        {total > 0 && <>{done}/{total} 块</>}
        {running && j.current && <> · 正在处理「{j.current}」</>}
        {running && (j.eta_s ?? 0) > 0 && <> · 预计还要 {fmtDur(j.eta_s!)}</>}
        {(j.elapsed_s ?? 0) > 0 && <> · 已用 {fmtDur(j.elapsed_s!)}</>}
        {(j.tokens_est ?? 0) > 0 && <> · 约 {fmtTokens(j.tokens_est!)} token</>}
      </div>
    </div>
  )
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
  const [feishuAppId, setFeishuAppId] = useState('')
  const [feishuSecret, setFeishuSecret] = useState('')
  const [feishuScope, setFeishuScope] = useState<'wiki' | 'drive'>('wiki')
  const [importing, setImporting] = useState(false)
  // 导到哪：一个几百篇的 vault 全抽进知识库要跑很久，得让人选
  const [importTo, setImportTo] = useState<'both' | 'kb' | 'notes'>('both')
  const [apple, setApple] = useState<{ available: boolean; reason: string } | null>(null)
  const [recentFacts, setRecentFacts] = useState<FactDetail[]>([])
  const lastSeenFactCount = useRef(-1)

  const refresh = () => memoryStats().then(setStats).catch(() => {})
  useEffect(() => { refresh() }, [])
  // 被服务重启打断、但内容落了盘的导入：列出来给「继续」
  const [interrupted, setInterrupted] = useState<JobOut[]>([])
  const loadInterrupted = () => listJobs(20).then((js) => setInterrupted(js.filter((j) => j.status === 'interrupted' && j.resumable))).catch(() => {})
  useEffect(() => { loadInterrupted() }, [])
  async function doResume(j: JobOut) {
    try {
      const r = await resumeImportJob(j.job_id)
      setInterrupted((xs) => xs.filter((x) => x.job_id !== j.job_id))
      setBatchJob(r)
      watchJob(r.job_id, (x) => { setBatchJob(x); pollRecentFacts(x.facts) }, () => { refresh(); setRecentFacts([]); loadInterrupted() })
    } catch (e) { toast('继续不了：' + (e instanceof Error ? e.message : String(e)), 'error') }
  }
  // 开始前的预估：这一批要跑多久、大概多少 token
  function announceEstimate(r: JobOut) {
    const e = r.estimate
    if (e && e.chunks > 0) toast(`${r.items.length} 篇 · ${e.chunks} 块 · 预计 ${fmtDur(e.seconds)} · 约 ${fmtTokens(e.tokens)} token`)
  }
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
      announceEstimate(r)
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
      announceEstimate(r)
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
      announceEstimate(r)
      setBatchJob(r)
      watchJob(r.job_id, (j) => { setBatchJob(j); pollRecentFacts(j.facts) },
        () => { refresh(); setRecentFacts([]) })
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    } finally {
      setImporting(false)
    }
  }

  async function doImportFeishu() {
    setImporting(true)
    try {
      const r = await importFeishu(feishuAppId.trim(), feishuSecret.trim(), feishuScope, importTo)
      announceEstimate(r)
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
        {' '}· <a href="#" onClick={(e) => { e.preventDefault(); window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb' })) }}>看总览</a>
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
          <span style={{ width: 88 }}>飞书</span>
          <input placeholder="App ID（cli_…）" value={feishuAppId} onChange={(e) => setFeishuAppId(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          <input type="password" placeholder="App Secret" value={feishuSecret} onChange={(e) => setFeishuSecret(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          <select value={feishuScope} onChange={(e) => setFeishuScope(e.target.value as 'wiki' | 'drive')}>
            <option value="wiki">知识库</option>
            <option value="drive">云空间</option>
          </select>
          <button onClick={doImportFeishu} disabled={!feishuAppId.trim() || !feishuSecret.trim() || importing}>
            {importing ? <span className="spinner" /> : '导入'}
          </button>
        </div>
        <p className="muted" style={{ fontSize: 11, margin: '0 0 6px 96px' }}>
          飞书开放平台建一个自建应用，开 docx / wiki / drive 的只读权限，再把要导的知识库或文档<strong>添加协作者</strong>给这个应用。凭证不会存下来。
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
        {interrupted.length > 0 && (
          <div className="card" style={{ borderColor: 'var(--warn)' }}>
            <strong style={{ fontSize: 13 }}>上次没跑完的导入</strong>
            {interrupted.map((j) => (
              <div key={j.job_id} className="row" style={{ justifyContent: 'space-between', marginTop: 6, gap: 8 }}>
                <span className="muted" style={{ fontSize: 12 }}>
                  {j.items.length} 篇 · 完成 {j.items.filter((it) => it.status === 'done').length} 篇 · {j.facts} 条事实{j.detail ? ` · ${j.detail}` : ''}
                </span>
                <button onClick={() => void doResume(j)} style={{ fontSize: 12, padding: '2px 10px' }}>继续</button>
              </div>
            ))}
          </div>
        )}
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
            <JobProgress j={batchJob} />
            {batchJob.items.map((it) => (
              <div key={it.id} className="row" style={{ justifyContent: 'space-between', marginTop: 6 }}>
                <span>{it.filename}</span>
                <span className="muted">
                  {STATUS_LABEL[it.status] ?? it.status}
                  {it.status === 'remembering' && (it.chunks_total ?? 0) > 0 && ` ${it.chunks_done ?? 0}/${it.chunks_total} 块`}
                  {(it.status === 'remembering' || it.status === 'done') && it.facts > 0 && ` · 已抽取 ${it.facts} 条`}
                  {it.status === 'failed' && it.detail && ` · ${it.detail}`}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
      <ExportBack />
    </div>
  )
}
