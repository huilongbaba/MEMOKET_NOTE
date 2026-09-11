import { useRef, useState } from 'react'
import { ingestAudio, transcribeOnly } from '../api'
import { toast } from '../toast'
import ContextMenu, { type MenuAt } from './ContextMenu'

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
  const [menuAt, setMenuAt] = useState<MenuAt | null>(null)
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
            // 静音/没转写出内容时之前是彻底没反应——用户录完音，点了停止，
            // 什么都没发生，分不清是没录上还是哪里坏了。
            if (text) onTranscript(text)
            else toast('没有转写出内容，可能是静音录音，检查一下麦克风', 'error')
          } else {
            setBusy('转写并入库')
            const { job_id, detail } = await ingestAudio(blob)
            // 后端在转写为空时会返回 job_id="" + detail="转写结果为空……"
            // （detail 这个字段在成功路径下装的是转写文字预览，不是错误信息，
            // 两种含义不一样，只在没有 job_id 的失败路径下才该当错误展示）。
            // 之前不管哪种情况都只是 onTranscript('') 插入一个空字符串
            // （等于什么也没做），detail 本身从没被展示过——用户录完音同样
            // 什么反应都看不到。
            if (job_id) onIngested(job_id)
            else toast(detail || '录音处理失败', 'error')
          }
        } catch (err) {
          toast(`语音处理失败：${err}`, 'error')
        } finally {
          setBusy('')
        }
      }
      mr.start()
      recorder.current = mr
      setRecording(true)
    } catch {
      toast('无法访问麦克风。浏览器要求 HTTPS 或 localhost 才允许录音。', 'error')
    }
  }

  function stop() {
    recorder.current?.stop()
    setRecording(false)
  }

  // 一个麦克风钮，两个去处在菜单里（正文右上角的浮动按钮位）。
  if (busy) return <button className="fb-btn" disabled><span className="spinner" /> {busy}…</button>
  if (recording) {
    return <button className="fb-btn rec" onClick={stop} title="停止录音"><i className="bx bx-stop-circle" /> 停止录音</button>
  }
  return (
    <>
      <button className="fb-btn" title="录音：转写后插入正文，或存进知识库"
              onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setMenuAt({ x: r.left, y: r.bottom + 4 }) }}>
        <i className="bx bx-microphone" /><i className="bx bx-chevron-down fb-caret" />
      </button>
      {menuAt && (
        <ContextMenu at={menuAt} onClose={() => setMenuAt(null)} items={[
          { label: '录音 → 插入正文', icon: 'bx-text', hint: '只转写', onSelect: () => void start('insert') },
          { label: '录音 → 存入知识库', icon: 'bx-brain', hint: '转写后抽成事实', onSelect: () => void start('memory') },
        ]} />
      )}
    </>
  )
}
