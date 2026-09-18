import { useRef, useState } from 'react'
import { ingestAudio, transcribeOnly } from '../api'
import { toast } from '../toast'
import { friendlyError } from '../util/friendlyError'
import { micError } from '../util/micError'
import { requestTrayAdd } from '../util/tray'
import { recordingTitle, trayByDefault } from '../util/trayDefaults'
import ContextMenu, { type MenuAt, type MenuItem } from './ContextMenu'
import Icon from './Icon'

type Props = {
  /** 转写结果插到编辑器光标处 */
  onTranscript: (text: string) => void
  /** 录音入库后返回 job id，由上层轮询 */
  onIngested: (jobId: string) => void
  /** 语音服务不可达时的地址（空串 = 在线）。离线时录音钮变成「离线」态：点了先说明，
   *  不让用户录完一段才在转写那一步失败。 */
  offline?: string
  /** 开着哪篇笔记（有 = 「进托盘」这个去处可用，P15 #3；托盘是按篇的） */
  noteId?: string
}

export type RecordTarget = 'insert' | 'memory' | 'tray'

/** 录音菜单的三个去处按什么顺序摆：开关开着且有笔记 → 「进托盘」排第一（默认去处）；否则它排最后 / 没有笔记就不给 */
export function recordMenuOrder(noteId: string | undefined, byDefault: boolean): RecordTarget[] {
  if (!noteId) return ['insert', 'memory']
  return byDefault ? ['tray', 'insert', 'memory'] : ['insert', 'memory', 'tray']
}

/**
 * 录音 -> Whisper。三种去处：
 *   进托盘 —— 转写后作为一条材料摊在桌上（不进正文；默认去处，托盘格里可关）
 *   插入正文 —— 只转写，当语音输入用
 *   存入知识库 —— 转写后后台抽取成 fact
 */
export default function AudioRecorder({ onTranscript, onIngested, offline = '', noteId }: Props) {
  const [recording, setRecording] = useState(false)
  const [busy, setBusy] = useState('')
  const [menuAt, setMenuAt] = useState<MenuAt | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const target = useRef<RecordTarget>('insert')
  // 转写中的「停止」（P3 遗留 ？：语音服务卡住原来按钮禁用、要等满 1800 秒）
  const abortRef = useRef<AbortController | null>(null)

  async function start(to: RecordTarget) {
    target.current = to
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      chunks.current = []
      const mr = new MediaRecorder(stream)
      mr.ondataavailable = (e) => e.data.size && chunks.current.push(e.data)
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunks.current, { type: 'audio/webm' })
        const ctrl = new AbortController()
        abortRef.current = ctrl
        try {
          if (target.current === 'insert' || target.current === 'tray') {
            setBusy('转写中')
            const { text } = await transcribeOnly(blob, 'recording.webm', ctrl.signal)
            // 静音/没转写出内容时之前是彻底没反应——用户录完音，点了停止，
            // 什么都没发生，分不清是没录上还是哪里坏了。
            if (!text) toast('没有转写出内容，可能是静音录音，检查一下麦克风', 'error')
            // 进托盘（P15 #3）：转写文字当一条 import 材料摊在桌上，不进正文；托盘那边收到就落库、说一声
            else if (target.current === 'tray') requestTrayAdd({ kind: 'import', title: recordingTitle(), excerpt: text, noteId })
            else onTranscript(text)
          } else {
            setBusy('转写并入库')
            const { job_id, detail } = await ingestAudio(blob, 'recording.webm', '', ctrl.signal)
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
          if ((err as Error).name === 'AbortError') toast('已停止，这段录音没有转写')
          else toast(`语音处理失败：${friendlyError(err)}`, 'error')
        } finally {
          abortRef.current = null
          setBusy('')
        }
      }
      mr.start()
      recorder.current = mr
      setRecording(true)
    } catch (e) {
      toast(micError(e), 'error')
    }
  }

  function stop() {
    recorder.current?.stop()
    setRecording(false)
  }

  // 一个麦克风钮，两个去处在菜单里（正文右上角的浮动按钮位）。
  if (busy) return <button className="fb-btn" title="撤掉这次转写；录下的这段就不要了" onClick={() => abortRef.current?.abort()}><span className="spinner" /> {busy}… 停止</button>
  if (recording) {
    return <button className="fb-btn rec" onClick={stop} title="停止录音"><Icon n="bx-stop-circle" /> 停止录音</button>
  }
  if (offline) {
    return (
      <button className="fb-btn" title={`语音服务不可达（${offline}）：录音转写用不了。在设置里检查语音服务地址`}
              onClick={() => toast(`语音服务不可达（${offline}），录音转写用不了；其它功能不受影响`, 'error')}>
        <Icon n="bx-microphone-off" style={{ opacity: .6 }} />
      </button>
    )
  }
  const order = recordMenuOrder(noteId, trayByDefault())
  const MENU: Record<RecordTarget, MenuItem> = {
    tray: { label: '录音 → 进托盘', icon: 'bx-layer-plus', hint: order[0] === 'tray' ? '默认：转写后摊在桌上，不进正文' : '转写后摊在桌上，不进正文', onSelect: () => void start('tray') },
    insert: { label: '录音 → 插入正文', icon: 'bx-text', hint: '只转写', onSelect: () => void start('insert') },
    memory: { label: '录音 → 存入知识库', icon: 'bx-brain', hint: '转写后抽成事实', onSelect: () => void start('memory') },
  }
  return (
    <>
      <button className="fb-btn" title={order[0] === 'tray' ? '录音：转写后先进托盘（默认），也可以插入正文或存进知识库' : '录音：转写后插入正文，或存进知识库'}
              onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setMenuAt({ x: r.left, y: r.bottom + 4 }) }}>
        <Icon n="bx-microphone" /><Icon n="bx-chevron-down" className="fb-caret" />
      </button>
      {menuAt && (
        <ContextMenu at={menuAt} onClose={() => setMenuAt(null)} items={order.map((k) => MENU[k])} />
      )}
    </>
  )
}
