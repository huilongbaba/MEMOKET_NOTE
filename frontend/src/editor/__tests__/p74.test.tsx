// @vitest-environment jsdom
/**
 * P74 B①：**「让 `liveContentRef` 跟着回声更新」那条改动的副作用，量清楚再判动不动。**
 *
 * P70 A 量到 A④ 那一格（CM 真改了一道 + 新片先进队列）会把 `content` 退回旧的，
 * 然后 `content === lastEmitted` 一路 skip、CM 再也拿不到新片 —— 跟 P68 实拍的卡死一模一样。
 * P70 **闸住了触发器**（今天 `transactionFilter` / `changeFilter` / `transactionExtender` 是 0），
 * 并且写下一句：
 *
 * > 正解多半是「让 `liveContentRef` 也跟着回声更新」，**这一批没量过那条改动的副作用，没动**。
 *
 * 这一份就是量那个副作用。**先量再改**：量完再判动不动，不先动手。
 *
 * ── 要量的到底是什么 ────────────────────────────────────────────────────
 * 今天 `App.tsx` 的 `onEditorChange` 是两句：`servedRef.current.edits++` + `setContent(next)`。
 * 「跟着回声更新」= 再加一句把编辑器报上来的那一份写进镜像。**而这一句有两种写法，
 * 副作用完全不同**，因为 `liveContentRef` 不是一个裸 `useRef`：
 * 它是 P70 B 做的一个取值/赋值对象，**setter 里顺手换护栏的锚点，并且把 `edits` 清 0**。
 *
 *   变体①「走 setter」`liveContentRef.current = next`
 *       → 镜像跟上了，**但每一次用户敲字都会把 `edits` 清 0、并把锚点换成用户刚敲出来的那一份**。
 *   变体②「只写镜像、不碰锚点」
 *       → 镜像跟上了，锚点和 `edits` 不动。
 *
 * 三组（今天 / 变体① / 变体②）在同一套量具上跑同样 9 格，差在哪一格就是副作用在哪。
 * 量具跟 `p70.test.tsx` 是同一套（真 React 19 + 真 CodeMirror 6，`MarkdownEditor` 的两段逐字照抄）。
 *
 * ── 量出来的（下面每条断言都是这张表里的一格）────────────────────────────
 *
 * | | 今天 | 变体①（走 setter） | 变体②（只写镜像） | 第几条断言 |
 * |---|---|---|---|---|
 * | A② 镜像跟不跟得上 CM 那一道 | **跟不上** | 跟上 | 跟上 | 1 |
 * | A④ `content` 退不退回旧的 | 退回 | 退回 | 退回 | 2 |
 * | A④ 新片 `CCC` 丢不丢 | 丢 | **丢** | **丢** | 2 |
 * | A④ 卡不卡死（CM 比镜像短） | **卡死** | 不卡 | 不卡 | 3 |
 * | B1 用户删字 → `edits` | 1 | **0** ← ★副作用 | 1 | 4 |
 * | B2 程序化 dispatch → `edits` | 1 | **0** ← ★副作用 | 1 | 5 |
 * | B1 / B2 拦不拦 | 不拦 | 不拦 | 不拦 | 6 |
 * | B1 把 `edits` 按回 0 之后还拦不拦 | 拦 | **不拦** ← ★同一个洞 | 拦 | 6 |
 * | B3 过期镜像拉短 → 拦不拦（护栏的正题） | 拦 | 拦 | 拦 | 7 |
 *
 * ⚠️ **第 3 行我预测错了，留痕**：原以为变体②解不开卡死，实际**也解得开**
 * ——「卡不卡死」量的是 `cm.length < live.length`，而两个变体**都把回声写进了镜像**，
 * 差别只在锚点和 `edits`，那两样跟这条判据无关。
 * 更正之后的形状更干净：**收益两个变体共有，代价只有变体①有。**
 *
 * ── 结论：**量完了，不改。** ──────────────────────────────────────────────
 *
 * · **收益比 P70 猜的小。** 两个变体都只解开了 A④ 的**后遗症**（卡死），
 *   **`content` 照样退回旧的、进过 React 的那一片 `CCC` 照样丢**（第 2 条断言，三组一样）。
 *   A④ 的真伤是「新值被排在后面的回声顶掉了」——那是个**顺序**问题（P68 的原结论），
 *   再加一句镜像赋值治不了它。
 *
 * · **变体①（P70 原话那一种）有实打实的代价：护栏的承重条件被架空。**
 *   `edits` 是「用户一个字都没动」的唯一证据（P70 B 的原话：用户的每一次改动都经过
 *   CodeMirror、都会让 `onChange` 报一次）。走 setter 之后**每一次用户敲字都把 `edits` 清 0**
 *   （第 4 / 5 条）。B1 / B2 表面照样绿（第 6 条），但**靠的不再是同一条理由**
 *   ——把 `edits` 按回 0 再问一次，今天那两组该拦、变体①不拦（第 6 条后半）。
 *   护栏于是只剩「比锚点短」一条，而锚点被用户自己的每一次输入推着走。
 *
 * · **变体②在这 9 格里量不到代价**，代价在结构上：它要**绕开 setter 直接写镜像**，
 *   而那个 setter 正是 P70 B 为了「13 个赋值点一个都不许漏」才做出来的
 *   （漏一个的症状是护栏拿着过期锚点去挡一次**该存**的保存）。
 *   开一个绕过去的口子，等于把那一课再关一次门。
 *   换来的又只是「后遗症」那一格，而**触发器今天是 0**（P70 A⑤ 钉着）。
 *
 * 所以 P74 **不动 `onEditorChange`**，P70 那条「闸住触发器 + 兜住后果」的两头走法保留。
 * 哪天真有人加了 `transactionFilter` / `changeFilter` / `transactionExtender`，
 * P70 A⑤ 会红，那时候要想的是**顺序**，不是这两个变体。
 *
 * 这一份是**量具兼闸**：上面那张表里的每一格都是下面一条断言。表变了就得重新量。
 */
import { act, useEffect, useRef, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { EditorState, type Extension, type TransactionSpec } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { afterEach, describe, expect, it } from 'vitest'
import { minimalChange } from '../minimalChange'
import { syncedFromApp, isAppEcho } from '../syncEcho'
import { isStaleShrink } from '../saveGuard'
import appSrc from '../../App.tsx?raw'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: Root | null = null
let host: HTMLDivElement | null = null
afterEach(() => { act(() => root?.unmount()); root = null; host?.remove(); host = null })

function codeOf(src: string): string {
  return src.split('\n').filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n')
}

/** `MarkdownEditor` 的两段，逐字照抄（跟 `p70.test.tsx` 同一份）。 */
function MiniEditor({ content, onChange, extra, viewOut }: {
  content: string; onChange: (t: string) => void; extra: Extension
  viewOut: { current: EditorView | null }
}) {
  const hostRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const lastEmitted = useRef(content)
  const liveRef = useRef({ onChange })
  liveRef.current.onChange = onChange
  useEffect(() => {
    const view = new EditorView({
      state: EditorState.create({
        doc: content,
        extensions: [extra, EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            const text = update.state.doc.toString()
            lastEmitted.current = text
            if (!isAppEcho(update, text)) liveRef.current.onChange?.(text)
          }
        })],
      }),
      parent: hostRef.current!,
    })
    viewRef.current = view; viewOut.current = view
    return () => { view.destroy(); viewRef.current = null; viewOut.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    const view = viewRef.current
    if (!view) return
    if (content === lastEmitted.current) return
    const cur = view.state.doc.toString()
    if (content === cur) { lastEmitted.current = content; return }
    const change = minimalChange(cur, content)
    if (change) {
      const spec: TransactionSpec = {}
      view.dispatch({ ...spec, changes: change,
        annotations: [...(spec.annotations ? [spec.annotations].flat() : []), syncedFromApp.of(content)] })
    }
    lastEmitted.current = content
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content])
  return <div ref={hostRef} />
}

/** 三组：今天 / 变体①（走 setter）/ 变体②（只写镜像、不碰锚点）。 */
type Variant = 'today' | 'setter' | 'mirror'
const VARIANTS: Variant[] = ['today', 'setter', 'mirror']

type Rig = {
  onDelta: (t: string) => void
  serve: (t: string) => void
  userDeletes: (n: number) => void
  progDispatch: (t: string) => void
  staleMirror: (t: string) => void
  read: () => { content: string; live: string; cm: string }
  served: () => { id: string; text: string; edits: number }
  view: { current: EditorView | null }
}

const NOTE = 'note-1'

function mount(variant: Variant, doc: string, extra: (rig: () => Rig) => Extension = () => []): Rig {
  host = document.createElement('div')
  document.body.appendChild(host)
  const view = { current: null as EditorView | null }
  const api: Partial<Rig> = { view }
  const ext = extra(() => api as Rig)
  const served = { id: NOTE, text: doc, edits: 0 }
  function App() {
    const [content, setContent] = useState(doc)
    const v = useRef(doc)
    // `liveContentRef` 那个取值/赋值对象，**setter 里换锚点 + 把 `edits` 清 0**
    //（`App.tsx:397-411` 逐字同形）。变体② 绕开 setter 直接写 `v`，
    // 差的就是这两件事——**那正是这一份要量的东西**。
    const live = {
      get current() { return v.current },
      set current(next: string) { v.current = next; served.text = next; served.edits = 0 },
    }
    const onChange = (t: string) => {
      served.edits++
      if (variant === 'setter') live.current = t
      if (variant === 'mirror') v.current = t
      setContent(t)
    }
    api.onDelta = (t) => { const next = v.current + t; live.current = next; setContent(next) }
    api.serve = (t) => { live.current = t; served.text = t; served.edits = 0; setContent(t) }
    api.staleMirror = (t) => setContent(t)
    api.userDeletes = (n) => {
      const vw = view.current!
      vw.dispatch({ changes: { from: vw.state.doc.length - n, to: vw.state.doc.length }, userEvent: 'delete' })
    }
    api.progDispatch = (t) => {
      const vw = view.current!
      vw.dispatch({ changes: { from: 0, to: vw.state.doc.length, insert: t } })
    }
    api.read = () => ({ content, live: v.current, cm: view.current?.state.doc.toString() ?? '' })
    api.served = () => ({ ...served })
    return <MiniEditor content={content} onChange={onChange} extra={ext} viewOut={view} />
  }
  root = createRoot(host)
  act(() => { root!.render(<App />) })
  return api as Rig
}

/** 「CM 在同一条事务上又改了一道」（跟 `p70.test.tsx` 同一份）。 */
function cmAddsAPass(once = false): Extension {
  let done = false
  return EditorState.transactionFilter.of((tr) => {
    if (tr.annotation(syncedFromApp) === undefined || !tr.docChanged) return tr
    if (once && done) return tr
    if (!once && tr.newDoc.toString().startsWith('#')) return tr
    done = true
    return [tr, { changes: { from: 0, insert: '#' } }]
  })
}

/** 「上一片的回声还没报上去，下一片就到了」（跟 `p70.test.tsx` 同一份）。 */
function chunkArrivesFirst(rig: () => Rig, piece: string) {
  let armed = true
  return EditorView.updateListener.of((u) => {
    if (!u.docChanged || !armed) return
    if (u.transactions.every((t) => t.annotation(syncedFromApp) === undefined)) return
    armed = false
    rig().onDelta(piece)
  })
}

describe('P74 B①：「让 liveContentRef 跟着回声更新」的副作用', () => {
  it('1. A②：今天镜像**跟不上** CM 那一道；两个变体都跟得上（这是那条改动的**收益**）', () => {
    const got: Record<Variant, { content: string; live: string }> = {} as never
    for (const v of VARIANTS) {
      const r = mount(v, 'AAAA', () => cmAddsAPass(true))
      act(() => { r.onDelta('BBB') })
      const { content, live } = r.read()
      got[v] = { content, live }
      act(() => { root?.unmount() }); root = null; host?.remove(); host = null
    }
    expect(got.today).toEqual({ content: '#AAAABBB', live: 'AAAABBB' })   // 镜像没跟上
    expect(got.setter).toEqual({ content: '#AAAABBB', live: '#AAAABBB' })
    expect(got.mirror).toEqual({ content: '#AAAABBB', live: '#AAAABBB' })
  })

  it('2. A④：**三组的 `content` 都退回旧的、新片 `CCC` 都丢** —— 那条改动治不了它本身', () => {
    const got: Record<Variant, { content: string; hasCCC: boolean }> = {} as never
    for (const v of VARIANTS) {
      const r = mount(v, 'AAAA', (rig) => [cmAddsAPass(), chunkArrivesFirst(rig, 'CCC')])
      act(() => { r.onDelta('BBB') })
      const { content, cm } = r.read()
      got[v] = { content, hasCCC: cm.includes('CCC') }
      act(() => { root?.unmount() }); root = null; host?.remove(); host = null
    }
    for (const v of VARIANTS) {
      expect(got[v].content).toBe('#AAAABBB')     // 退回旧的：三组一样
      expect(got[v].hasCCC).toBe(false)           // 进过 React 的那一片：三组都丢
    }
  })

  it('3. A④ 的**后遗症**（CM 比镜像短 = 卡死）：只有变体①解得开，变体②解不开', () => {
    const stuck: Record<Variant, boolean> = {} as never
    for (const v of VARIANTS) {
      const r = mount(v, 'AAAA', (rig) => [cmAddsAPass(), chunkArrivesFirst(rig, 'CCC')])
      act(() => { r.onDelta('BBB') })
      const { live, cm } = r.read()
      stuck[v] = cm.length < live.length
      act(() => { root?.unmount() }); root = null; host?.remove(); host = null
    }
    // ⚠️ **这一格我预测错了，留痕**：原以为变体②（只写镜像）解不开，实际**也解得开**。
    // 想岔的地方：「卡不卡死」量的是 `cm.length < live.length`，而两个变体
    // **都把回声写进了镜像**——差别只在锚点和 `edits`，那两样跟这条判据无关。
    // 也就是说：**收益是两个变体共有的，代价只有变体①有。**（结论见文件头）
    expect(stuck.today).toBe(true)
    expect(stuck.setter).toBe(false)
    expect(stuck.mirror).toBe(false)
  })

  it('4. ★副作用：变体①**每一次用户敲字都把 `edits` 清 0**（护栏的承重条件被架空）', () => {
    const edits: Record<Variant, number> = {} as never
    for (const v of VARIANTS) {
      const r = mount(v, 'AAAABBBBCCCC')
      act(() => { r.serve('AAAABBBBCCCC') })
      act(() => { r.userDeletes(4) })
      edits[v] = r.served().edits
      act(() => { root?.unmount() }); root = null; host?.remove(); host = null
    }
    expect(edits.today).toBe(1)
    expect(edits.setter).toBe(0)       // ★ 「用户动过」这件事的唯一证据没了
    expect(edits.mirror).toBe(1)
  })

  it('5. 同一个副作用在程序化 dispatch 那一格上也成立（B2）', () => {
    const edits: Record<Variant, number> = {} as never
    for (const v of VARIANTS) {
      const r = mount(v, 'AAAABBBBCCCC')
      act(() => { r.serve('AAAABBBBCCCC') })
      act(() => { r.progDispatch('AAAA') })
      edits[v] = r.served().edits
      act(() => { root?.unmount() }); root = null; host?.remove(); host = null
    }
    expect(edits.today).toBe(1)
    expect(edits.setter).toBe(0)
    expect(edits.mirror).toBe(1)
  })

  it('6. B1 / B2 三组**都不拦**——但变体①靠的不再是同一条理由（绿得一样，理由不一样）', () => {
    for (const v of VARIANTS) {
      const r = mount(v, 'AAAABBBBCCCC')
      act(() => { r.serve('AAAABBBBCCCC') })
      act(() => { r.userDeletes(4) })
      expect(isStaleShrink(r.served(), NOTE, r.read().content)).toBe(false)
      // 变体① 的「不拦」是因为**锚点跟着用户的输入一起变短了**，不是因为 `edits > 0`：
      // 把 `edits` 按回 0，今天那两组该拦（锚点还是长的那一份），变体① 照样不拦。
      const forced = isStaleShrink({ ...r.served(), edits: 0 }, NOTE, r.read().content)
      expect(forced).toBe(v === 'setter' ? false : true)
      act(() => { root?.unmount() }); root = null; host?.remove(); host = null
    }
  })

  it('7. B3（护栏的正题：过期镜像把正文拉短）三组**都拦得住** —— 收益不在这儿', () => {
    for (const v of VARIANTS) {
      const r = mount(v, 'AAAA')
      act(() => { r.serve('AAAABBBBCCCC') })
      act(() => { r.staleMirror('AAAA') })
      expect(r.served().edits).toBe(0)
      expect(isStaleShrink(r.served(), NOTE, r.read().content)).toBe(true)
      act(() => { root?.unmount() }); root = null; host?.remove(); host = null
    }
  })

  it('8. **判完没动**：`onEditorChange` 今天还是那两句（量完不改，这条钉着「不改」）', () => {
    const code = codeOf(appSrc)
    const m = code.match(/const onEditorChange = useCallback\(\(next: string\) => \{([\s\S]*?)\}, \[\]\)/)
    expect(m, 'App.tsx 里找不到 onEditorChange —— 它被改了，上面那张表就得重新量').toBeTruthy()
    const body = m![1].split('\n').map((l) => l.trim()).filter(Boolean)
    expect(body).toEqual(['servedRef.current.edits++', 'setContent(next)'])
  })
})

describe('P74 B②：护栏那一档「A④ 那种拦不到」——真实发生过吗', () => {
  // P70 留的第 ② 条：护栏只拦「编辑器一次都没报过」那一档，A④ 那种
  // 「编辑器自己报了一道、但报的是过期的」拦不到；**判据宁可窄，真要拦得先量到一次真实发生**。
  //
  // 这一批 A 那条走查（假壳上三步 / 35 条判据）跑下来，`save-guard` 这条 warn
  // **一条都没有**——沿用 P70 的办法核的：同一条 `clientLog` 通道上
  // `harness-sync` 有条数（通道是活的、不是哑的），`save-guard` 是 0。
  // 结论：**A④ 那一档仍然一次都没真实发生过**，所以这一批**不放宽护栏**。
  //
  // 这儿钉住的是「结论的前提」，不是行为（P72 B 那一课）：前提一变，结论就得重量。
  it('A④ 的触发器今天仍然是 0（前提①）—— 触发器一出现，P70 A⑤ 那条会红', () => {
    // 这条跟 `p70.test.tsx` 的 A⑤ 是同一件事，这儿只钉「那条闸还在」：
    // 删掉它，A④ 那条路就没人看着了，而这一节的结论正建立在「触发器是 0」上。
    const p70 = codeOf(
      (import.meta.glob('./p70.test.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>)['./p70.test.tsx'])
    expect(p70).toMatch(/transactionFilter\|changeFilter\|transactionExtender/)
    expect(p70).toMatch(/expect\(offenders\)\.toEqual\(\[\]\)/)
  })

  it('护栏的判据今天仍然是「编辑器一次都没报过」那一档（前提②）', () => {
    const guard = codeOf(
      (import.meta.glob('../saveGuard.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>)['../saveGuard.ts'])
    // 三条同时成立才算：① 锚点是这一篇的 ② `edits === 0` ③ 要存的这一份更短
    expect(guard).toMatch(/served\.edits\s*!==\s*0\) return false/)
    expect(guard).toMatch(/served\.id\s*!==\s*noteId\) return false/)
    expect(guard).toMatch(/content\.length\s*<\s*served\.text\.length/)
  })

  it('那条 warn 的通道名没变（前提③）—— 走查是拿这个名字在后端日志里数 0 的', () => {
    const code = codeOf(appSrc)
    expect(code).toMatch(/'save-guard'/)
    // 同通道的对照组：`harness-sync` 得还在，不然「0 条」跟「通道是哑的」分不开
    expect(code).toMatch(/'harness-sync'/)
  })
})
