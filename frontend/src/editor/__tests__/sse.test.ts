/**
 * SSE 流解析。
 *
 * 这段逻辑原本在 api.ts 里有**五份拷贝**，而且已经不一致了：块生成那一份
 * 把事件名放在帧循环里面（对的），另外四份放在外面——一个只有 data: 的帧
 * 会沿用上一帧的事件名。后端目前总是成对发所以没炸过，但那是颗哑弹。
 * 而且只有那一份会跳过解析不了的帧，另外四份直接抛，把整条流掐断。
 *
 * 合成一份之后，这里守住它：**跨 chunk 边界切帧**是这类代码最经典的坏法
 * ——一帧正好被网络切成两半，测不到的时候它就是随机丢事件。
 */
import { describe, expect, it } from 'vitest'

import { sseFrames } from '../../api'

/** 把若干段文字做成一个 Response，每段是一次 read() 返回的 chunk。 */
function streamOf(chunks: string[]): Response {
  const enc = new TextEncoder()
  let i = 0
  return {
    body: {
      getReader: () => ({
        read: async () =>
          i < chunks.length
            ? { done: false, value: enc.encode(chunks[i++]) }
            : { done: true, value: undefined },
      }),
    },
  } as unknown as Response
}

async function collect(chunks: string[]) {
  const out: { event: string; payload: any }[] = []
  for await (const f of sseFrames(streamOf(chunks))) out.push(f)
  return out
}

const frame = (event: string, data: unknown) =>
  `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`

describe('sseFrames', () => {
  it('一个 chunk 里的多帧按顺序出来', async () => {
    const got = await collect([frame('a', { n: 1 }) + frame('b', { n: 2 })])
    expect(got).toEqual([{ event: 'a', payload: { n: 1 } },
                         { event: 'b', payload: { n: 2 } }])
  })

  it('一帧被切在两个 chunk 中间也要完整拼回来', async () => {
    // 真实网络下这是常态。切点挑在 JSON 中间——最容易坏的地方
    const whole = frame('delta', { text: '一段中文正文' })
    const cut = Math.floor(whole.length / 2)
    const got = await collect([whole.slice(0, cut), whole.slice(cut)])
    expect(got).toEqual([{ event: 'delta', payload: { text: '一段中文正文' } }])
  })

  it('切在帧分隔的空行中间也不丢帧', async () => {
    const two = frame('a', { n: 1 }) + frame('b', { n: 2 })
    const cut = two.indexOf('\n\n') + 1        // 正好切在两个换行之间
    const got = await collect([two.slice(0, cut), two.slice(cut)])
    expect(got.map((f) => f.event)).toEqual(['a', 'b'])
  })

  it('一个字节一个字节地喂也拼得回来', async () => {
    const whole = frame('x', { 中文: '值', n: 42 })
    const got = await collect([...whole])
    expect(got).toEqual([{ event: 'x', payload: { 中文: '值', n: 42 } }])
  })

  it('每一帧的事件名各自独立', async () => {
    // 原来的写法里事件名是跨帧沿用的：一个只有 data: 的帧会顶着上一帧的
    // 名字被派发出去
    const got = await collect([frame('a', { n: 1 }) + 'data: {"n":2}\n\n'])
    expect(got).toEqual([{ event: 'a', payload: { n: 1 } },
                         { event: '', payload: { n: 2 } }])
  })

  it('解析不了的帧跳过，不掐断整条流', async () => {
    // 为一帧坏数据放弃整次生成，代价是几十秒的工作量
    const got = await collect([
      ': keep-alive\n\n',
      'event: a\ndata: {这不是合法 JSON\n\n',
      frame('b', { n: 2 }),
    ])
    expect(got).toEqual([{ event: 'b', payload: { n: 2 } }])
  })

  it('没有 body 的响应直接报错，不是静默什么都不干', async () => {
    await expect(async () => {
      for await (const _ of sseFrames({} as Response)) { /* 不该走到这儿 */ }
    }).rejects.toThrow('no stream')
  })

  it('最后一帧没有收尾空行时丢弃，不吐半截数据', async () => {
    const got = await collect([frame('a', { n: 1 }) + 'event: b\ndata: {"n":2'])
    expect(got).toEqual([{ event: 'a', payload: { n: 1 } }])
  })
})
