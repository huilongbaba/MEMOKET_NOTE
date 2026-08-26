import { useRef, useState } from 'react'
import { ingestAudio, transcribeOnly } from '../api'

type Props = {
  /** 转写结果插到编辑器光标处 */
  onTranscript: (text: string) => void
  /** 录音入库后返回 job id，由上层轮询 */
  onIngested: (jobId: string) => void
}

/**
 * 录音 -> Whisper。两种去处：
 *   插入正文 —— 只转写，当语音输入用
 *   存入知识库 —— 转写后后台抽取成 fact
 */
export default function AudioRecorder({ onTranscript, onIngested }: Props) {
  const [recording, setRecording] = useState(false)
  const [busy, setBusy] = useState('')
  const recorder = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const target = useRef<'insert' | 'memory'>('insert')

  async function start(to: 'insert' | 'memory') {
    target.current = to
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      chunks.current = []
      const mr = new MediaRecorder(stream)
      mr.ondataavailable = (e) => e.data.size && chunks.current.push(e.data)
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunks.current, { type: 'audio/webm' })
        try {
          if (target.current === 'insert') {
            setBusy('转写中')
            const { text } = await transcribeOnly(blob)
            if (text) onTranscript(text)
          } else {
            setBusy('转写并入库')
            const { job_id, detail } = await ingestAudio(blob)
            if (detail) onTranscript('')  // 只提示，不插入
            if (job_id) onIngested(job_id)
          }
        } catch (err) {
          alert(`语音处理失败：${err}`)
        } finally {
          setBusy('')
        }
      }
      mr.start()
      recorder.current = mr
      setRecording(true)
    } catch {
      alert('无法访问麦克风。浏览器要求 HTTPS 或 localhost 才允许录音。')
    }
  }

  function stop() {
    recorder.current?.stop()
    setRecording(false)
  }

  if (busy) return <span className="muted"><span className="spinner" /> {busy}…</span>

  return recording ? (
    <button className="rec" onClick={stop}>■ 停止录音</button>
  ) : (
    <div className="row">
      <button onClick={() => start('insert')}>● 录音插入</button>
      <button onClick={() => start('memory')}>● 录音入库</button>
    </div>
  )
}
