/**
 * P39 探针（只在 `--probe=` 启动时跑，生产路径不进）：**待处置的改动层落库**——
 * 在真实 app 上把「关掉再打开还在不在」拍下来。
 *
 * 每一条都分两趟：`make`（这一趟摆好姿势，然后 app 退出）→ `back`（下一趟重开，只看还剩什么）。
 * 「关掉重开」这件事没法在一趟里拍——那正是这一批要修的毛病。
 *
 *   p39:rounds:<id>:make    真跑智能续写（假模型三轮停）→ **一处都不处置** → 落库 → 截图
 *   p39:rounds:<id>:back    重开这篇：那一层还在不在、还是不是「待处置」
 *   p39:dispose:<id>:make   同上，再逐处「✓ 接受」两处、「↩ 撤回」一处 → 落库 → 截图
 *   p39:dispose:<id>:back   重开：三处的处置状态各自还在不在
 *   p39:pain8:<id>:make     痛点 8 原话：三层改动（第 1 / 2 / 3 轮）摆在那儿
 *   p39:pain8:<id>:back     重开 → 撤回第 3 轮那一层 → 正文里第 1 轮的还在、第 3 轮的没了
 *   p39:evict:<id>:make     摆出超过上限的局面 → 淘汰那条路真的会触发，而且**吵闹**
 *
 * P43 加的三条（前两条是 P42「留给下一批」⑦ 那三条淘汰闸里没摆过的两条）：
 *   p39:settled:<id>:make   一层里**每一处都**「✓ 接受」→ 一处活的都不剩 → 落库
 *   p39:settled:<id>:back   重开：页签还在不在、面板上那行「已处置…」在不在、toast 说了什么
 *   p39:evict:<id>:hunks    一次「格式化」在长文上切出 **501 处** → `CHANGE_LAYER_HUNKS` 整层不存
 *   p39:evict:<id>:age      库里躺着一层 40 天前的 → `CHANGE_LAYER_MAX_AGE_DAYS` 淘汰掉并说出来
 */
import { EditorView } from '@codemirror/view'
import * as api from './api'
import { acceptHunk, dropHunk, dropLayer, layersOf, roundDiffField, settledOf } from './editor/roundDiff'
import type { Note } from './api'

type Ctx = Record<string, any> & { notes: Note[] }
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
const log = (s: string) => void api.clientLog('warn', s, '', 'probe')

function view(): EditorView | null {
  const el = document.querySelector('.note-scroll .cm-content')
  return el ? EditorView.findFromDOM(el as HTMLElement) : null
}
const button = (text: string, root: ParentNode = document) =>
  Array.from(root.querySelectorAll<HTMLElement>('button')).find((e) => (e.textContent ?? '').replace(/\s+/g, '') === text)

/** 面板上现在写着什么（层 / 已处置 / 烧过的跑） */
function panelText(): string {
  return (document.querySelector('.right-pane-body')?.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 420)
}

function snapshot(v: EditorView, tag: string): string {
  const st = v.state.field(roundDiffField, false)
  const ls = layersOf(v).map((l) => `${l.label}·${l.count}处${l.off ? '·关着' : ''}`)
  const done = settledOf(v).map((x) => `${x.label}:${x.accepted}受/${x.reverted}撤`)
  return `${tag} layers=${JSON.stringify(ls)} settled=${JSON.stringify(done)} hunks=${st?.hunks.length ?? 0} len=${v.state.doc.length}`
}

async function runHarnessThreeRounds(v: EditorView, out: string[]) {
  const base = v.state.doc.length
  const btn = button('智能续写')
  btn?.click()
  out.push(`clicked 智能续写 button=${!!btn} base len=${base}`)
  let rounds = 0
  for (let i = 0; i < 400; i++) {
    await wait(500)
    const running = Array.from(document.querySelectorAll<HTMLElement>('button')).some((e) => e.classList.contains('running') && (e.textContent ?? '').includes('停止'))
    const status = (document.querySelector('.fb-status-text')?.textContent ?? '')
    const m = status.match(/第 (\d+) 轮/); if (m) rounds = Math.max(rounds, Number(m[1]))
    if (i > 6 && !running) break
  }
  await wait(2000)
  out.push(`harness done: rounds seen=${rounds} len ${base}→${v.state.doc.length}`)
}

export async function runP39(probe: string, ctx: Ctx): Promise<boolean> {
  if (!probe.startsWith('p39:')) return false
  const [, what, id, phase] = probe.split(':')
  const n = ctx.notes.find((x) => x.id === id)
  if (!n) { log(`p39 note ${id} not found`); return true }
  if (ctx.harnessProbeDone.current) return true
  ctx.harnessProbeDone.current = true
  await wait(600)
  await ctx.switchTo(n)
  await wait(2200)                                    // 等层从库里放回来（App 那条 320ms + 网络）
  const v = view()
  if (!v) { log('p39: no editor'); return true }
  const out: string[] = []
  ctx.setPaneFocus({ id: 'changes', n: Date.now() })

  /** 正文 + 层都落库：探针下 App 自己的自动保存是关着的（往真实笔记塞假正文那条老规矩），
   *  所以这里显式存一次——不存的话下一趟重开时正文对不上，层全成了冲突。 */
  const persist = async (tag: string) => {
    await api.saveNote(id, n.title, v.state.doc.toString())
    ctx.actionsRef.current.flushChangeLayers()
    await wait(1200)
    out.push(snapshot(v, tag))
  }

  if (phase === 'back') {
    // **等层真的放回来再看**：读库 + App 那条 320ms 的等待 + 重新定位都在异步里，
    // 第一版实拍在这儿拍到的是 `layers=[] hunks=0`——不是没存下来，是拍早了。
    // 「放回来了」= 有活层**或者**有处置完的层（P43 #1：全处置完那一档 `layersOf` 恒为 0，
    // 只等它的话这儿要空等 10 秒，然后拍到的还是「什么都没有」——又一次拍早了）
    for (let i = 0; i < 40 && layersOf(v).length === 0 && settledOf(v).length === 0; i++) await wait(250)
    ctx.setPaneFocus({ id: 'changes', n: Date.now() })   // 「改动」页签是层回来之后才出现的
    await wait(900)
    out.push(snapshot(v, 'reopened'))
    out.push(`panel=${JSON.stringify(panelText())}`)
    if (what === 'pain8') {
      // 痛点 8 原话：「保留第一轮、丢掉第三轮」
      const ls = layersOf(v)
      const third = ls[ls.length - 1]
      out.push(`before drop: r1=${v.state.doc.toString().includes('第1轮改的这一句') ? 'in' : 'OUT'} r3=${v.state.doc.toString().includes('第3轮改的这一句') ? 'in' : 'OUT'}`)
      if (third) dropLayer(v, third.id)
      await wait(900)
      out.push(`after drop 第3层: r1=${v.state.doc.toString().includes('第1轮改的这一句') ? 'in' : 'OUT'} r3=${v.state.doc.toString().includes('第3轮改的这一句') ? 'in' : 'OUT'}`)
      out.push(snapshot(v, 'after-drop'))
      await persist('persisted')
    }
    log('p39 ' + out.join(' | '))
    return true
  }

  if (what === 'rounds' || what === 'dispose') {
    await runHarnessThreeRounds(v, out)
    ctx.setPaneFocus({ id: 'changes', n: Date.now() })
    await wait(1200)
    out.push(snapshot(v, 'after-run'))
    if (what === 'dispose') {
      // 智能续写那一层是一整段追加，只有一处。再叠一层三处的「润色」——
      // 「逐处接受两处、撤回一处」要的是三处，而这三处得**分得开**
      // （`toHunks` 的 MERGE_GAP 是 8，挨太近会并成一处）。
      const doc0 = v.state.doc.toString()
      const at = [0.75, 0.5, 0.25].map((f) => {
        const k = Math.floor(doc0.length * f)
        const stop = doc0.indexOf('。', k)
        return stop < 0 ? k : stop + 1
      })
      let next = doc0
      at.forEach((pos, i) => { next = next.slice(0, pos) + `（润色补的第${3 - i}处）` + next.slice(pos) })
      ctx.setContent(next)
      await wait(500)
      ctx.actionsRef.current.pushDiff('润色', doc0, next)
      await wait(800)
      out.push(snapshot(v, 'after-polish'))
      // 逐处「✓ 接受」两处、「↩ 撤回」一处——跟悬停工具条上那两个按钮走的是同一条路
      const layer = layersOf(v).find((l) => l.label === '润色')
      const hs = [...(v.state.field(roundDiffField, false)?.hunks ?? [])].filter((h) => !h.soft && !h.off && h.layer === layer?.id)
      if (hs.length >= 3) {
        v.dispatch({ effects: acceptHunk.of(hs[0].id) })
        v.dispatch({ effects: acceptHunk.of(hs[1].id) })
        const cur = v.state.field(roundDiffField).hunks.find((x) => x.id === hs[hs.length - 1].id)
        if (cur) v.dispatch({ changes: { from: cur.from, to: cur.to, insert: cur.del }, effects: dropHunk.of(cur.id) })
      }
      out.push(`disposed on ${hs.length} hunks`)
      await wait(800)
      out.push(snapshot(v, 'after-dispose'))
    }
    await persist('persisted')
    out.push(`panel=${JSON.stringify(panelText())}`)
    log('p39 ' + out.join(' | '))
    return true
  }

  /** **一层里每一处都处置完**（P43 #1，P42 问题 #1 实拍的那一档）。
   *  `dispose` 那一条留着一层活的（智能续写那层），这一条**一处活的都不剩**——
   *  它才是「toast 说有「改动」页签、页签根本不在」的那个局面。 */
  if (what === 'settled') {
    const doc0 = v.state.doc.toString()
    const at = [0.75, 0.5, 0.25].map((f) => {
      const k = Math.floor(doc0.length * f)
      const stop = doc0.indexOf('。', k)
      return stop < 0 ? k : stop + 1
    })
    let next = doc0
    at.forEach((pos, i) => { next = next.slice(0, pos) + `（润色补的第${3 - i}处）` + next.slice(pos) })
    ctx.setContent(next)
    await wait(500)
    ctx.actionsRef.current.pushDiff('润色', doc0, next)
    await wait(900)
    out.push(snapshot(v, 'after-polish'))
    // 逐处「✓ 接受」**每一处**——跟悬停工具条上那个按钮走的是同一条路
    const hs = [...(v.state.field(roundDiffField, false)?.hunks ?? [])].filter((h) => !h.soft && !h.off)
    for (const h of hs) v.dispatch({ effects: acceptHunk.of(h.id) })
    await wait(800)
    out.push(snapshot(v, 'all-settled'))
    await persist('persisted')
    out.push(`panel=${JSON.stringify(panelText())}`)
    log('p39 ' + out.join(' | '))
    return true
  }

  if (what === 'pain8') {
    // 三层改动。走的是每一次 AI 动作都走的那个 `pushDiff`——层是怎么生出来的，这里就怎么生
    const base = v.state.doc.toString()
    let cur = base
    for (const k of [1, 2, 3]) {
      const next = cur + `\n\n第${k}轮改的这一句，是这一层往正文里加的。`
      ctx.setContent(next)
      await wait(400)
      ctx.actionsRef.current.pushDiff('智能续写', cur, next)
      cur = next
      await wait(500)
    }
    await wait(1000)
    out.push(snapshot(v, 'three-layers'))
    await persist('persisted')
    out.push(`panel=${JSON.stringify(panelText())}`)
    log('p39 ' + out.join(' | '))
    return true
  }

  if (what === 'evict') {
    const readToasts = () => Array.from(document.querySelectorAll('.toast, .toasts > *'))
      .map((e) => (e.textContent ?? '').replace(/\s+/g, ' ').trim()).filter(Boolean)

    /** **一层最多几处**（`CHANGE_LAYER_HUNKS = 500`，P43 #4）：超了**整层不存**，回 `rejected`。
     *  走的是真路径——一次「格式化」在长文上切出 501 处，跟 P39 那句
     *  「47k 字长文点一次格式化能切出几千处」是同一件事。
     *  501 处要真的是 501 处：`toHunks` 的 MERGE_GAP 是 8，插入点之间留得远远够。 */
    if (phase === 'hunks') {
      const base = v.state.doc.toString()
      // 要的是**切出来 > 500 处**，不是「插 501 个记号」：`toHunks` 会把挨得近的并成一处，
      // 实拍插 501 个只切出 441 处（第一版就是这么差一点没摸到闸）。多插一些，
      // 真正作数的是下面 `snapshot` 里那个 hunks 数。
      const N = 700
      const gap = Math.max(12, Math.floor(base.length / (N + 1)))
      let next = ''
      for (let k = 0; k < N; k++) next += base.slice(k * gap, (k + 1) * gap) + `〔${k}〕`
      next += base.slice(N * gap)
      ctx.setContent(next)
      await wait(600)
      ctx.actionsRef.current.pushDiff('格式化', base, next)
      await wait(1500)
      out.push(snapshot(v, 'one-fat-layer'))
      ctx.setPaneFocus({ id: 'changes', n: Date.now() })
      await api.saveNote(id, n.title, v.state.doc.toString())
      ctx.actionsRef.current.flushChangeLayers()
      await wait(2500)
      out.push(`toasts=${JSON.stringify(readToasts())}`)
      out.push(`库里剩 ${(await api.listChangeLayers(id)).length} 层`)
      log('p39 ' + out.join(' | '))
      return true
    }

    /** **多久不留**（`CHANGE_LAYER_MAX_AGE_DAYS = 30`，P43 #4）。
     *  老的那一层是**库里本来就躺着的**（`at` 是 40 天前，落库时间也就是 40 天前那次），
     *  这一趟打开时它照常被放回编辑器；再随手叠一层新的逼出一次冲库——
     *  后端按 `at` 把老的那层淘汰掉，前端弹那句话。 */
    if (phase === 'age') {
      out.push(snapshot(v, 'reopened-with-old-layer'))
      const cur = v.state.doc.toString()
      const next = cur + '\n新叠的一层，只为逼出一次冲库。'
      ctx.setContent(next)
      await wait(400)
      ctx.actionsRef.current.pushDiff('润色', cur, next)
      await wait(900)
      ctx.setPaneFocus({ id: 'changes', n: Date.now() })
      ctx.actionsRef.current.flushChangeLayers()
      await wait(2500)
      out.push(`toasts=${JSON.stringify(readToasts())}`)
      out.push(`库里剩 ${(await api.listChangeLayers(id)).length} 层`)
      log('p39 ' + out.join(' | '))
      return true
    }

    // 超上限：后端只留 20 层，最早的几层淘汰掉——**而且要说出来**
    const base = v.state.doc.toString()
    let cur = base
    for (let k = 1; k <= 23; k++) {
      const next = cur + `\n第${k}层加的一句。`
      ctx.setContent(next)
      await wait(60)
      ctx.actionsRef.current.pushDiff(`格式化`, cur, next)
      cur = next
      await wait(60)
    }
    await wait(1200)
    out.push(snapshot(v, 'many-layers'))
    await api.saveNote(id, n.title, v.state.doc.toString())
    ctx.actionsRef.current.flushChangeLayers()
    await wait(2500)
    out.push(`toasts=${JSON.stringify(readToasts())}`)
    const rows = await api.listChangeLayers(id)
    out.push(`库里剩 ${rows.length} 层`)
    log('p39 ' + out.join(' | '))
    return true
  }

  log('p39 未知的 what=' + what)
  return true
}
