// @vitest-environment jsdom
/**
 * P3（产品就绪计划 §2 B 线，`docs/edge-cases.md`）：临界条件表修的第一批里前端管得着的几条。
 *
 *   前后端同一份整篇前置判断（`editor/preconditions`）：空正文 → 骨架 / 续写 / 排版 / 幻灯片 / 存入知识库
 *   「LLM 不可达」时的闸（`llmGateMessage`）：状态栏红着就不发注定失败的请求
 *   `friendlyError` 三条新规则：后端没起来 ≠ 模型连不上；语音服务的错说语音服务；后端翻好的中文原样给
 *   SkeletonPanel 的按钮不能把鼠标事件当 background（实拍：三种失败全静默）
 *   SelectionMenu 忙的时候有「停止」
 */
import { describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { EMPTY_NOTE, llmGateMessage, notePrecondition } from '../preconditions'
import { friendlyError, isBackendDown, isLlmUnreachable } from '../../util/friendlyError'
import SkeletonPanel from '../../components/SkeletonPanel'
import SelectionMenu from '../../components/SelectionMenu'

describe('整篇动作的前置判断（P3）', () => {
  it('空正文：骨架 / 续写认标题，排版 / 幻灯片 / 打磨 / 存入知识库只认正文', () => {
    expect(notePrecondition('skeleton', '', '')).toBe(EMPTY_NOTE.skeleton)
    expect(notePrecondition('skeleton', '', '有标题')).toBe('')
    expect(notePrecondition('tap', ' \n', '标题')).toBe('')
    expect(notePrecondition('restructure', '', '有标题也不行')).toBe(EMPTY_NOTE.restructure)
    expect(notePrecondition('slides', '', '标题')).toBe(EMPTY_NOTE.slides)
    expect(notePrecondition('ingest', '一句', '')).toBe('')
  })
  it('每一句都说清要做什么，不是只说「空的」', () => {
    for (const text of Object.values(EMPTY_NOTE)) expect(text).toMatch(/骨架|续写|打磨|排版|幻灯片|知识库/)
  })
  it('LLM 不可达时的闸：状态栏红着才拦，那句话带着地址和「先修设置」', () => {
    expect(llmGateMessage('')).toBe('')
    expect(llmGateMessage('后端不可达')).toBe('')      // 后端连不上不是这条闸管的
    const m = llmGateMessage('LLM 不可达 (http://192.168.77.8:8080/v1)')
    expect(m).toContain('192.168.77.8:8080')
    expect(m).toContain('设置')
  })
})

describe('friendlyError（P3）', () => {
  it('浏览器连不上后端 ≠ 后端连不上模型', () => {
    const m = friendlyError(new TypeError('Failed to fetch'))
    expect(m).toContain('连不上应用后台')
    expect(m).not.toContain('LLM 供应商')
    expect(isBackendDown(new TypeError('Failed to fetch'))).toBe(true)
    expect(isLlmUnreachable(new TypeError('Failed to fetch'))).toBe(false)
    // 后端自己连不上模型（httpx 的话）还是指去设置页
    expect(friendlyError(new Error('All connection attempts failed'))).toContain('模型连不上')
  })
  it('后端翻好的中文（502 + describe_error）原样给，不被「5xx = 后端处理出错」盖掉', () => {
    const m = friendlyError(new Error('502 模型连不上：10 秒内没连上模型服务（http://x/v1）——去设置里检查 LLM 供应商的地址'))
    expect(m).toBe('模型连不上：10 秒内没连上模型服务（http://x/v1）——去设置里检查 LLM 供应商的地址')
    expect(isLlmUnreachable(new Error('502 模型服务返回 500（http://x/v1）——多半是那边出错了，稍后再试'))).toBe(true)
    // 光秃秃的 500 还是那句通用的
    expect(friendlyError(new Error('500 Internal Server Error'))).toContain('后端处理出错')
  })
  it('语音服务的错说语音服务，不指去 LLM 供应商', () => {
    expect(friendlyError(new Error('502 语音服务连不上（http://127.0.0.1:1）——去设置里检查语音服务地址'))).toContain('语音服务')
    expect(friendlyError(new Error('502 transcription failed: All connection attempts failed'))).toContain('语音服务')
  })
})

describe('按钮上的两个坑（P3）', () => {
  it('SkeletonPanel：点「生成骨架」调 onRun 时不带鼠标事件——不然它被当成 background，失败全静默', () => {
    // 服务端渲染拿到的是 React 的合成 onClick；直接调组件里那个包装函数最省事
    const onRun = vi.fn()
    const html = renderToStaticMarkup(createElement(SkeletonPanel, { spine: '', beats: [], beatCoverage: null, loading: false, onRun }))
    expect(html).toContain('生成骨架')
    // 源码层面钉死：不许再写 onClick={onRun}
    const src = SkeletonPanel.toString()
    expect(src).not.toMatch(/onClick:\s*onRun\b/)
  })
  it('SelectionMenu 忙的时候有「停止」，不忙时没有', () => {
    const busy = renderToStaticMarkup(createElement(SelectionMenu, { x: 0, y: 0, busy: 'rewrite', onAction: () => {}, onStop: () => {}, onClose: () => {} }))
    expect(busy).toContain('重写中…')
    expect(busy).toContain('停止')
    const idle = renderToStaticMarkup(createElement(SelectionMenu, { x: 0, y: 0, busy: false, onAction: () => {}, onStop: () => {}, onClose: () => {} }))
    expect(idle).not.toContain('停止')
    expect(idle).toContain('自定义提示')
  })
})
