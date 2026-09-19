// @vitest-environment jsdom
import { describe, expect, it, beforeEach } from 'vitest'

import appSrc from '../../App.tsx?raw'
import { COMMANDS } from '../../components/CommandPalette'
import {
  JOURNEY_SPAN_DAYS, JOURNEY_SPAN_EVENT, openJourneySpan, takePendingJourneySpan,
} from '../../util/journeyOpen'

/**
 * P23 #7：⌘K 的「这一周的屏幕活动」——**它是导航，不是开跑**。
 *
 * 那份回顾是一次模型调用（几十秒到几分钟，还会在树上落一篇笔记），而 ⌘K 里挑中一条命令
 * 只是「敲两个字 + Enter」，没有第二次确认，它的「停止」又在屏幕活动那一页上。
 * 所以这一条只把人送到那一块、把「最近 7 天」指出来。
 */

beforeEach(() => { takePendingJourneySpan() })

describe('⌘K 的「这一周的屏幕活动」', () => {
  it('⌘K 里有这一条，名字里带着天数', () => {
    const c = COMMANDS.find((x) => x.label.includes('这一周的屏幕活动'))
    expect(c).toBeTruthy()
    expect(c!.label).toContain(`${JOURNEY_SPAN_DAYS} 天`)
  })

  it('按下去只发两个事件：开那一页 + 指出那个范围。**一个网络请求都没有**', () => {
    const seen: [string, unknown][] = []
    const onOpen = (e: Event) => seen.push(['open-virtual', (e as CustomEvent).detail])
    const onSpan = (e: Event) => seen.push([JOURNEY_SPAN_EVENT, (e as CustomEvent).detail])
    window.addEventListener('open-virtual', onOpen)
    window.addEventListener(JOURNEY_SPAN_EVENT, onSpan)
    COMMANDS.find((x) => x.label.includes('这一周的屏幕活动'))!.run()
    window.removeEventListener('open-virtual', onOpen)
    window.removeEventListener(JOURNEY_SPAN_EVENT, onSpan)
    expect(seen).toEqual([['open-virtual', 'app:journey'], [JOURNEY_SPAN_EVENT, JOURNEY_SPAN_DAYS]])
  })

  it('待提示的那个范围**取走只生效一次**（跟「待打开的那一天」同一条规矩）', () => {
    openJourneySpan()
    expect(takePendingJourneySpan()).toBe(JOURNEY_SPAN_DAYS)
    expect(takePendingJourneySpan()).toBe(0)
  })

  it('⌘K 那一条的天数跟页面上那个钮是同一个数（改一处就是改两处）', () => {
    const c = COMMANDS.find((x) => x.label.includes('这一周的屏幕活动'))!
    // 页面上摆的是 7 / 30 两个钮，⌘K 指的必须是其中一个
    expect([7, 30]).toContain(JOURNEY_SPAN_DAYS)
    expect(c.label).toContain(`最近 ${JOURNEY_SPAN_DAYS} 天`)
  })
})

/**
 * P23 #8：语音输入**一次只录一段**（临界条件表 A 组「语音输入 × 重复点击」那个 ？）。
 *
 * 真 app 上量到的是：修前 `voicetwice` 探针跑完**两个运行块**（两个 MediaRecorder、
 * 两条麦克风轨，而「停止」只停得了它自己那一个），修后一个
 * （`p23-voice-twice-before-light` / `-after-light`）。
 *
 * 这条闸**守的是来源**（P21）：判据不是「某个按钮禁没禁用」——`/`、右键、探针都走得到
 * 这一条路，守在 `runVoice` 的入口才守得住。`runVoice` 住在 App.tsx 里、挂在整套编辑器上，
 * 单测起不动它，所以这里读源码认那道闸；行为那一侧由真 app 的探针钉。
 */
describe('语音输入一次只录一段', () => {
  it('runVoice 一进门就看有没有正在录的', () => {
    const body = appSrc.slice(appSrc.indexOf('async function runVoice('))
    const guard = body.indexOf('voiceStopById.current.size > 0')
    const mic = body.indexOf('getUserMedia')
    expect(guard).toBeGreaterThan(-1)
    expect(guard).toBeLessThan(mic)        // 要在开麦之前拦
    expect(body.slice(guard, guard + 300)).toContain('已经在录一段了')
  })
})
