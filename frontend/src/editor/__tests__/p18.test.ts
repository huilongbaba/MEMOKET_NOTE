// @vitest-environment jsdom
/**
 * P18（`docs/TRACELOG-product.md` P18 节）：后端 harness 与导出的遗留，前端管得着的部分。
 *
 *   3. 「只撤第 N 轮」当后一轮改过它的句子：拿后几轮的快照把这一处**映射**过去再撤（`editor/undoRound` 的 `later`），
 *      映射不了（后一轮整个删了、原文要不要回来说不准）才报冲突；`util/runRounds` 给每轮带上「之后再往后」的行
 *   4. 飞书 mermaid → 图：`util/mermaidPng`——问后端要源码、渲成 PNG、按同一个键交回；任何失败不拦导回
 *   6. 网页版凭证存在这个浏览器里（`util/exportCreds`）；录音进托盘只放前 600 字要明说（`util/tray.trayAddNotice`）
 */
import { describe, expect, it, vi } from 'vitest'
import { diffParts } from '../roundDiff'
import { mapPos, undoRound } from '../undoRound'
import { groupRuns } from '../../util/runRounds'
import { collectMermaidRenders, exportMermaidRenders, sizedSvg, svgDataUrl, svgSize, withExportInit, EXPORT_INIT } from '../../util/mermaidPng'
import mermaidPngSrc from '../../util/mermaidPng.ts?raw'
import { WEB_CREDS_KEY, credsNote, credsPlace, loadCreds, pickCreds, saveCreds } from '../../util/exportCreds'
import { TRAY_EXCERPT_MAX, trayAddNotice } from '../../util/tray'
import exportBackSrc from '../../components/ExportBack.tsx?raw'
import exportPanelSrc from '../../components/ExportNotePanel.tsx?raw'
import trayPanelSrc from '../../components/TrayPanel.tsx?raw'
import appSrc from '../../App.tsx?raw'
import useExportSrc from '../../util/useExportBack.ts?raw'
import type { NoteRevision } from '../../api'

// 三轮：第 1 轮写 S1；第 2 轮**改了 S1 的几个字**再写 S2；第 3 轮写 S3
const v0 = '开头一段。'
const S1 = '第1轮写的第一句，讲的是众筹节奏。'
const v1 = v0 + '\n\n' + S1
const S1b = '第1轮写的第一句，讲的是众筹和预售的节奏。'
const v2 = v0 + '\n\n' + S1b + '\n\n第2轮写的第二句。'
const v3 = v2 + '\n\n第3轮写的第三句。'

describe('只撤第 N 轮：后一轮改过它的句子，沿后几轮映射过去（P18 #3）', () => {
  it('第 2 轮改了第 1 轮的句子：给了后几轮快照就能撤，改过的那句连同第 2 轮的修改一起走，第 2、3 轮自己写的留着', () => {
    const r = undoRound(v0, v1, v3, [v2, v3])
    expect(r.text).toBe(v0 + '\n\n第2轮写的第二句。\n\n第3轮写的第三句。')
    expect([r.undone, r.total, r.conflicts]).toEqual([1, 1, []])
  })
  it('不给后几轮快照：还是老规矩，改过就报冲突、正文不动（P16 那条闸不变）', () => {
    const r = undoRound(v0, v1, v3)
    expect(r.text).toBe(v3)
    expect(r.undone).toBe(0)
  })
  it('用户在最后一版之后又改了别处：映射到最后一版再按文字定位，照样撤得掉', () => {
    const edited = v3.replace('开头一段。', '开头一段（我改过）。')
    const r = undoRound(v0, v1, edited, [v2, v3])
    expect(r.text).toBe('开头一段（我改过）。\n\n第2轮写的第二句。\n\n第3轮写的第三句。')
    expect(r.conflicts).toEqual([])
  })
  it('第 N 轮把 A 改成 B、后一轮把 B 整个删了：原文 A 要不要回来说不准，报冲突', () => {
    const before = '一二三四五六七八九十。原来这句。甲乙丙丁戊己庚辛。'
    const after = '一二三四五六七八九十。改成这句。甲乙丙丁戊己庚辛。'
    const later = '一二三四五六七八九十。甲乙丙丁戊己庚辛。'
    const r = undoRound(before, after, later, [later])
    expect(r.undone).toBe(0)
    expect(r.conflicts[0]).toMatch(/整个删掉了/)
    expect(r.text).toBe(later)
  })
  it('第 N 轮纯插入、后一轮把它删了：没东西可撤，算撤完、正文不动', () => {
    const before = '一二三四五六七八九十。甲乙丙丁戊己庚辛。'
    const after = '一二三四五六七八九十。插进来的。甲乙丙丁戊己庚辛。'
    const r = undoRound(before, after, before, [before])
    expect([r.undone, r.conflicts]).toEqual([1, []])
    expect(r.text).toBe(before)
  })
  it('mapPos：后一轮在它前面插字 → 起点后移；在它后面接字 → 终点不动；删掉它中间几个字 → 区间收窄', () => {
    const a = '甲乙丙丁戊'
    expect(mapPos(diffParts(a, 'XX甲乙丙丁戊'), 0, 'start')).toBe(2)
    expect(mapPos(diffParts(a, '甲乙丙丁戊YY'), 5, 'end')).toBe(5)
    const p = diffParts(a, '甲戊')
    expect([mapPos(p, 0, 'start'), mapPos(p, 5, 'end')]).toEqual([0, 2])
    expect(mapPos(p, 2, 'start')).toBe(1)                    // 落在被删掉的段里：贴到它左边
  })
})

const rev = (id: string, reason: string, round_no: number, run_id: string, at: string, chars = 100): NoteRevision =>
  ({ id, note_id: 'n', title: 't', reason, round_no, run_id, created_at: at, chars })

describe('runRounds：每轮带上「之后再往后」的行；老数据 run_end + harness 两行都认（P18 #2 / #3）', () => {
  it('新数据：收尾只有一行 harness（带 round_no）——第 3 轮的之后是它、第 1 轮的 later 是 [r3, harness]', () => {
    const revs = [
      rev('h', 'harness', 3, 'runA', '2026-09-19T10:03:00', 400),
      rev('r3', 'round', 3, 'runA', '2026-09-19T10:02:00', 300),
      rev('r2', 'round', 2, 'runA', '2026-09-19T10:01:00', 200),
      rev('r1', 'round', 1, 'runA', '2026-09-19T10:00:00', 100),
    ]
    const [run] = groupRuns(revs)
    expect(run.finished).toBe(true)
    expect(run.rounds.map((r) => [r.after?.id, r.later.map((x) => x.id)])).toEqual([['r2', ['r3', 'h']], ['r3', ['h']], ['h', []]])
  })
  it('老数据：harness + run_end 同时在（同一份正文）——两行都列进 later，finished 仍是 true', () => {
    const revs = [
      rev('e', 'run_end', 2, 'runA', '2026-09-19T10:02:01', 300),
      rev('h', 'harness', 0, 'runA', '2026-09-19T10:02:00', 300),
      rev('r2', 'round', 2, 'runA', '2026-09-19T10:01:00', 200),
      rev('r1', 'round', 1, 'runA', '2026-09-19T10:00:00', 100),
    ]
    const [run] = groupRuns(revs)
    expect(run.rounds[0].later.map((x) => x.id)).toEqual(['h', 'e'])
    expect(run.rounds[1].after?.id).toBe('h')
    expect(run.finished).toBe(true)
  })
  it('App 把 later 的正文一起取来喂给 undoRound', () => {
    expect(appSrc).toMatch(/r\.later\]\.map\(\(x\) => api\.getRevision/)
    expect(appSrc).toMatch(/undoRound\(before\.content, after\.content, cur, later\.map/)
  })
})

describe('飞书 mermaid → 图（util/mermaidPng，P18 #4）', () => {
  it('导出用浅色主题 + 纯 SVG 标签的 init；已带 init 的不重复套', () => {
    expect(withExportInit('graph TD\nA-->B')).toBe(EXPORT_INIT + 'graph TD\nA-->B')
    expect(withExportInit('%%{init: {"theme":"forest"}}%%\ngraph TD')).toBe('%%{init: {"theme":"forest"}}%%\ngraph TD')
  })
  it('尺寸读 viewBox（mermaid 给的 width 是 100%），并写成明确的像素宽高', () => {
    const svg = '<svg id="m" width="100%" viewBox="0 0 320 180" xmlns="http://www.w3.org/2000/svg"><g/></svg>'
    expect(svgSize(svg)).toEqual({ w: 320, h: 180 })
    expect(sizedSvg(svg, { w: 320, h: 180 })).toMatch(/^<svg id="m" viewBox="0 0 320 180" xmlns="[^"]+" width="320" height="180">/)
    expect(svgSize('<svg width="10px" height="5px"></svg>')).toEqual({ w: 10, h: 5 })
    expect(svgSize('<svg></svg>')).toBeNull()
  })
  it('SVG 装进 <img> 走 data: URL，不走 blob:（真 Chromium 实拍：blob: 画上 canvas 之后 toDataURL 报 tainted）', () => {
    expect(svgDataUrl('<svg viewBox="0 0 1 1"/>')).toBe('data:image/svg+xml;charset=utf-8,' + encodeURIComponent('<svg viewBox="0 0 1 1"/>'))
    expect(mermaidPngSrc).not.toMatch(/createObjectURL/)
  })
  it('渲不出的那张不带；问后端 → 渲 → 按同一个键交回；一张都没渲出就不发第二个请求', async () => {
    const calls: { path: string; body: unknown }[] = []
    const fetcher = (async (path: string, init?: RequestInit) => {
      calls.push({ path, body: JSON.parse(String(init?.body)) })
      if (path === '/api/export/mermaid') return new Response(JSON.stringify({ k1: 'graph TD\nA-->B', k2: 'bad' }), { status: 200 })
      return new Response(JSON.stringify({ stored: 1, rejected: [] }), { status: 200 })
    }) as unknown as typeof fetch
    const render = vi.fn(async (code: string) => (code.startsWith('graph') ? 'data:image/png;base64,AAA' : null))
    expect(await collectMermaidRenders({ k1: 'graph TD', k2: 'bad' }, render)).toEqual({ k1: 'data:image/png;base64,AAA' })
    expect(await exportMermaidRenders(['n1'], render, fetcher)).toBe(1)
    expect(calls.map((c) => c.path)).toEqual(['/api/export/mermaid', '/api/export/renders'])
    expect(calls[0].body).toEqual({ note_ids: ['n1'] })
    expect(calls[1].body).toEqual({ renders: { k1: 'data:image/png;base64,AAA' } })
    // 一张都渲不出：不发 renders
    const none = vi.fn(async () => null)
    calls.length = 0
    expect(await exportMermaidRenders([], none, fetcher)).toBe(0)
    expect(calls.map((c) => c.path)).toEqual(['/api/export/mermaid'])
  })
  it('后端挂了 / 断网：回 0 不抛——图渲不出不拦导回', async () => {
    const boom = (async () => { throw new Error('offline') }) as unknown as typeof fetch
    await expect(exportMermaidRenders(['n1'], async () => null, boom)).resolves.toBe(0)
  })
  it('导回飞书那条路先渲图再发请求', () => {
    expect(useExportSrc).toMatch(/await exportMermaidRenders\(noteIds\); return exportFeishu\(/)
  })
})

describe('凭证与托盘（P18 #6）', () => {
  it('网页版：凭证存在这个浏览器的 localStorage 里、只留白名单键；弹层那句话明说', async () => {
    expect(credsPlace()).toBe('browser')
    await saveCreds({ notion_token: 'ntn_1', feishu_app_id: 'cli_1', junk: 'x' } as never)
    await saveCreds({ feishu_folder: 'fld' })
    expect(JSON.parse(localStorage.getItem(WEB_CREDS_KEY)!)).toEqual({ notion_token: 'ntn_1', feishu_app_id: 'cli_1', feishu_folder: 'fld' })
    expect(await loadCreds()).toEqual({ notion_token: 'ntn_1', feishu_app_id: 'cli_1', feishu_folder: 'fld' })
    expect(pickCreds({ notion_parent: 1, feishu_app_secret: '' })).toEqual({})
    expect(credsNote('browser')).toMatch(/这个浏览器里/)
    expect(credsNote('desktop')).toMatch(/本机/)
    expect(exportBackSrc).toMatch(/credsNote\(\)/)
    expect(exportPanelSrc).toMatch(/credsNote\(\)/)
  })
  it('录音 / 长段落进托盘只放前 600 字：放进去那一声明说全文多长；笔记 / 事实项不说', () => {
    const long = '字'.repeat(TRAY_EXCERPT_MAX + 150)
    expect(trayAddNotice([{ kind: 'import', excerpt: long }])).toMatch(/只保留前 600 字（全文 750 字）/)
    expect(trayAddNotice([{ kind: 'selection', excerpt: long }])).toMatch(/600/)
    expect(trayAddNotice([{ kind: 'import', excerpt: '短的' }, { kind: 'note', excerpt: long }])).toBe('')
    expect(trayPanelSrc).toMatch(/\+ trayAddNotice\(fresh\)/)
  })
})
