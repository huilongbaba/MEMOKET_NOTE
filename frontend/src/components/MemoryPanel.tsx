import { useEffect, useState } from 'react'
import { ask, ingestText, jobStatus, memoryStats, recall } from '../api'
import type { Fact } from '../api'

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

  const refresh = () => memoryStats().then(setStats).catch(() => {})
  useEffect(() => { refresh() }, [])

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

  const working = pendingJob || job

  return (
    <div>
      <h2>知识库</h2>
      <p className="muted">
        {stats ? `${stats.facts} 条事实 · ${stats.entities} 个实体` : '加载中…'}
        {working && <> · <span className="spinner" /> 抽取中</>}
      </p>

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
    </div>
  )
}
