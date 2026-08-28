import { useEffect, useRef, useState } from 'react'
import { ask, cancelJob, ingestBatch, ingestText, jobStatus, memoryStats, recall, watchJob } from '../api'
import type { Fact, JobOut } from '../api'
import MemoryBrowser from './MemoryBrowser'

const STATUS_LABEL: Record<string, string> = {
  queued: '排队中', extracting: '提取文本', transcribing: '转写中',
  chunking: '切块', remembering: '抽取入库', done: '完成',
  failed: '失败', cancelled: '已取消',
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
  const [busy, setBusy] = useState<'' | 'recall' | 'ask' | 'ingest'>('')
  const [paste, setPaste] = useState('')
  const [job, setJob] = useState('')
  const [batchJob, setBatchJob] = useState<JobOut | null>(null)
  const batchAbort = useRef<AbortController | null>(null)
  const [browsing, setBrowsing] = useState(false)

  const refresh = () => memoryStats().then(setStats).catch(() => {})
  useEffect(() => { refresh() }, [])
  useEffect(() => () => batchAbort.current?.abort(), [])

  // 入库是后台任务，轮询到 done 再刷新统计
  useEffect(() => {
    const id = pendingJob || job
    if (!id) return
    const timer = setInterval(async () => {
      try {
        const s = await jobStatus(id)
        if (s.status === 'done' || s.status === 'error') {
          clearInterval(timer)
          setJob('')
          refresh()
          if (s.status === 'error') alert(`入库失败：${s.detail}`)
        }
      } catch { clearInterval(timer) }
    }, 3000)
    return () => clearInterval(timer)
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

  async function doIngest() {
    if (!paste.trim()) return
    setBusy('ingest')
    try {
      const r = await ingestText(paste, '手动录入')
      setJob(r.job_id); setPaste('')
    } finally { setBusy('') }
  }

  async function doBatchIngest(files: FileList | null) {
    if (!files || files.length === 0) return
    batchAbort.current?.abort()
    const controller = new AbortController()
    batchAbort.current = controller
    const r = await ingestBatch(Array.from(files))
    setBatchJob(r)
    watchJob(r.job_id, setBatchJob, () => refresh(), controller.signal)
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

      <h2>手动入库</h2>
      <div className="stack">
        <textarea
          rows={4}
          placeholder="粘贴文档内容，抽取成事实存进知识库…"
          value={paste}
          onChange={(e) => setPaste(e.target.value)}
        />
        <button onClick={doIngest} disabled={!paste.trim() || !!busy}>
          {busy === 'ingest' ? <span className="spinner" /> : '存入知识库'}
        </button>
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
                {batchJob.status === 'running' || batchJob.status === 'queued'
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
                  {it.status === 'done' && ` · ${it.facts} 条`}
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
