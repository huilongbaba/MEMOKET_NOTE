// @vitest-environment jsdom
/**
 * P70 A：**回声那条路的第二半** —— 「CM 真改了一道」时那条**该报**的回声，
 * 会不会也排在后面盖掉新值。P68 修完之后留的就是这一格，**它自己说没量过**。
 *
 * P70 B：**`save()` 的护栏** —— 「别把更短的正文盖回刚交稿那一份」。
 *
 * 量具不是直接调函数，是**真 React 19 + 真 CodeMirror 6**：把 `App.tsx` 那一侧的
 * 三样东西照抄进一个最小 App（`content` 这个 state、`liveContentRef` 这个镜像、
 * `onDelta` 从镜像上算下一片），编辑器那一侧把 `MarkdownEditor` 的两段
 * （`[content]` 同步 effect + `updateListener` 的回声判据）逐字照抄。
 * **直接调 `isAppEcho` 是测不出这件事的**：要量的正是「报上去之后会怎么样」。
 *
 * 量到的（A①–A④，下面四条就是这四格）：
 *
 * | | 情形 | `content` | `liveContentRef` | CM |
 * |---|---|---|---|---|
 * | A① | 没有第二道（P68 修完的常态） | 一致 | 一致 | 一致 |
 * | A② | CM 真改了一道 | **报上去了** | **没跟上** | 带那一道 |
 * | A③ | 纯回声 + 新片先进队列（P68 那一格） | 新片 | 新片 | 新片 |
 * | A④ | CM 改了一道 + 新片先进队列 | **退回旧的** | 新片 | **退回旧的** |
 *
 * **结论：会。** A④ 那一格里那条该报的回声确实排在新值后面、把新片盖掉了，
 * 而且之后 `content === lastEmitted` 一路 skip —— 跟 P68 实拍的卡死一模一样。
 * `isAppEcho` **治不了它，也不该治**（那一份只有回声报得上去，判据宁可窄）。
 *
 * 所以这一批不去动 `syncEcho`，改的是两头：
 *   · **闸住触发器**：今天仓库里能让 A④ 成立的东西**一个都没有**
 *     （0 个 `transactionFilter` / `changeFilter` / `transactionExtender`），下面第 ⑤ 条钉着这个 0；
 *   · **兜住后果**：`editor/saveGuard.ts`（P70 B）——真出了这种退回，别让它写回库。
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
import editorSrc from '../../components/MarkdownEditor.tsx?raw'

/** `frontend/src/editor/` 底下每一份源码（**整目录**，不是点名几个文件）。 */
const EDITOR_SRC = import.meta.glob('../*.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: Root | null = null
let host: HTMLDivElement | null = null
afterEach(() => { act(() => root?.unmount()); root = null; host?.remove(); host = null })

/** 整行注释先摘掉再判——**闸拿整份文件 `includes` 判会把注释也算数**（P68 第 ⑤ 刀栽过）。 */
function codeOf(src: string): string {
  return src.split('\n').filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n')
}

/** `MarkdownEditor` 的两段，逐字照抄。 */
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

function mount(doc: string, extra: (rig: () => Rig) => Extension = () => []): Rig {
  host = document.createElement('div')
  document.body.appendChild(host)
  const view = { current: null as EditorView | null }
  const api: Partial<Rig> = { view }
  const ext = extra(() => api as Rig)
  const served = { id: NOTE, text: doc, edits: 0 }
  function App() {
    const [content, setContent] = useState(doc)
    const live = useRef(doc)
    // App.tsx 的 `onEditorChange`：编辑器报一次就记一笔「用户动过」
    const onChange = (t: string) => { served.edits++; setContent(t) }
    // App.tsx 的 `onDelta`：从镜像上算下一片，**不用 updater**
    api.onDelta = (t) => { const next = live.current + t; live.current = next; setContent(next) }
    // App.tsx 里 `liveContentRef.current = X` 那一类赋值（setter 顺手换锚点）
    api.serve = (t) => { live.current = t; served.text = t; served.edits = 0; setContent(t) }
    // 过期的那一份落回 React（不经 CM）——P68 实拍那一格的形状
    api.staleMirror = (t) => setContent(t)
    api.userDeletes = (n) => {
      const v = view.current!
      v.dispatch({ changes: { from: v.state.doc.length - n, to: v.state.doc.length }, userEvent: 'delete' })
    }
    api.progDispatch = (t) => {
      const v = view.current!
      v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: t } })
    }
    api.read = () => ({ content, live: live.current, cm: view.current?.state.doc.toString() ?? '' })
    api.served = () => ({ ...served })
    return <MiniEditor content={content} onChange={onChange} extra={ext} viewOut={view} />
  }
  root = createRoot(host)
  act(() => { root!.render(<App />) })
  return api as Rig
}

/** 「CM 在同一条事务上又改了一道」。`once` = 只改第一条同步事务（一次性的修补）。 */
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

/** 「上一片的回声还没报上去，下一片就到了」：排在 `updateListener` **之前**，
 *  这样 `setContent(新片)` 进 React 的队列**早于** `setContent(回声)`。 */
function chunkArrivesFirst(rig: () => Rig, piece: string) {
  let armed = true
  return EditorView.updateListener.of((u) => {
    if (!u.docChanged || !armed) return
    if (u.transactions.every((t) => t.annotation(syncedFromApp) === undefined)) return
    armed = false
    rig().onDelta(piece)
  })
}

describe('P70 A：回声那条路的第二半', () => {
  it('A① 没有第二道：回声被扔掉，三头一致（P68 修完的常态）', () => {
    const r = mount('AAAA')
    act(() => { r.onDelta('BBB') })
    expect(r.read()).toEqual({ content: 'AAAABBB', live: 'AAAABBB', cm: 'AAAABBB' })
  })

  it('A② CM 真改了一道：回声**报得上去**，但镜像没跟上，下一片就把那一道冲掉了', () => {
    const r = mount('AAAA', () => cmAddsAPass(true))
    act(() => { r.onDelta('BBB') })
    // 报上去了：React 那边拿到了带那一道的正文
    expect(r.read().content).toBe('#AAAABBB')
    // **但 `liveContentRef` 没跟上**——而流式 / 轮末 / 收工那行 / 服务端对齐读的都是它
    expect(r.read().live).toBe('AAAABBB')
    act(() => { r.onDelta('CCC') })
    // 下一片从过期的镜像上算，CM 那一道（`#`）**没了**
    expect(r.read().cm).toBe('AAAABBBCCC')
  })

  it('A③ 纯回声 + 新片先进队列：**不再盖掉新值**（P68 那一刀的反例，控制组）', () => {
    const r = mount('AAAA', (rig) => chunkArrivesFirst(rig, 'CCC'))
    act(() => { r.onDelta('BBB') })
    expect(r.read()).toEqual({ content: 'AAAABBBCCC', live: 'AAAABBBCCC', cm: 'AAAABBBCCC' })
  })

  it('A④ CM 改了一道 + 新片先进队列：**会，它确实盖掉了新值**（这一批要量的那一格）', () => {
    const r = mount('AAAA', (rig) => [cmAddsAPass(), chunkArrivesFirst(rig, 'CCC')])
    act(() => { r.onDelta('BBB') })
    const got = r.read()
    // 新片 `CCC` 进过 React，**又被排在后面的那条回声顶掉了**
    expect(got.live).toBe('AAAABBBCCC')
    expect(got.content).toBe('#AAAABBB')
    expect(got.cm).toBe('#AAAABBB')
    // 而且卡死：`content === lastEmitted` → 同步 effect 一路 skip，CM 再也拿不到新片
    expect(got.cm.length).toBeLessThan(got.live.length)
  })

  it('A⑤ **闸住触发器**：编辑器那一侧不许出现能改写同步事务的扩展点', () => {
    // A④ 要成立，得有人在**同步那一条事务**上追加改动。CM 里能干这件事的只有
    // 这三个扩展点，今天仓库里一个都没有——这条闸钉着这个 0。真要加，
    // 加的人会在这里红一次，然后必须连着把 A④ 那条路一起想清楚。
    const files = Object.entries(EDITOR_SRC)
    expect(files.length).toBeGreaterThan(20)                  // 别把目录读空了还绿（分母先断言）
    const offenders: string[] = []
    for (const [name, src] of [...files, ['MarkdownEditor.tsx', editorSrc] as const]) {
      // **注释里那一份不算数**：这一整个文件顶上就写着这三个词（P68 第 ⑤ 刀栽过）
      if (/transactionFilter|changeFilter|transactionExtender/.test(codeOf(src))) offenders.push(name)
    }
    expect(offenders).toEqual([])
  })
})

describe('P70 B：`save()` 的护栏', () => {
  it('B1 用户自己删字 → 变短，**不许拦**', () => {
    const r = mount('AAAABBBBCCCC')
    act(() => { r.serve('AAAABBBBCCCC') })
    act(() => { r.userDeletes(4) })
    expect(r.served().edits).toBe(1)
    expect(isStaleShrink(r.served(), NOTE, r.read().content)).toBe(false)
  })

  it('B2 「全部撤回」那一类程序化 dispatch → 变短，也**不许拦**', () => {
    const r = mount('AAAABBBBCCCC')
    act(() => { r.serve('AAAABBBBCCCC') })
    act(() => { r.progDispatch('AAAA') })
    expect(r.served().edits).toBe(1)
    expect(isStaleShrink(r.served(), NOTE, r.read().content)).toBe(false)
  })

  it('B3 服务端刚交完，过期的镜像把 `content` 拉回短的 → **该拦**（P68 实拍那一格）', () => {
    const r = mount('AAAA')
    act(() => { r.serve('AAAABBBBCCCC') })
    expect(r.read()).toEqual({ content: 'AAAABBBBCCCC', live: 'AAAABBBBCCCC', cm: 'AAAABBBBCCCC' })
    act(() => { r.staleMirror('AAAA') })
    expect(r.served().edits).toBe(0)
    expect(isStaleShrink(r.served(), NOTE, r.read().content)).toBe(true)
  })

  it('B4 A④ 那一格（CM 改了一道）**落在不拦那一侧**——判据宁可窄', () => {
    const r = mount('AAAA', (rig) => [cmAddsAPass(), chunkArrivesFirst(rig, 'CCC')])
    act(() => { r.serve('AAAA') })
    act(() => { r.onDelta('BBB') })
    expect(r.served().edits).toBeGreaterThan(0)              // 编辑器自己报过 → 不拦
    expect(isStaleShrink(r.served(), NOTE, r.read().content)).toBe(false)
    // **承重的是哪一条，单独核一次**（突变验第 ① 刀量出来的：这一格的 `content`
    // 本来就比锚点长，光这一条断言核不住 `edits` 那一道——两个理由同时成立时，
    // 拿掉一个也还是绿的）。把 `edits` 按回 0、锚点换成更长的那一份：该拦。
    expect(isStaleShrink({ ...r.served(), text: 'AAAABBBCCC', edits: 0 }, NOTE, r.read().content)).toBe(true)
    expect(isStaleShrink({ ...r.served(), text: 'AAAABBBCCC' }, NOTE, r.read().content)).toBe(false)
  })

  it('B5 交完之后打开别的一篇（更短）→ 不许拦（锚点按篇分）', () => {
    const r = mount('AAAABBBBCCCC')
    act(() => { r.serve('AAAABBBBCCCC') })
    expect(isStaleShrink({ id: NOTE, text: 'AAAABBBBCCCC', edits: 0 }, 'note-2', 'BB')).toBe(false)
  })

  it('B6 服务端自己交了更短的一份（清洗 / 去重）→ 不许拦（锚点跟着换）', () => {
    const r = mount('AAAABBBBCCCC')
    act(() => { r.serve('AAAABBBBCCCC') })
    act(() => { r.serve('AAAA') })
    expect(r.served().text).toBe('AAAA')
    expect(isStaleShrink(r.served(), NOTE, r.read().content)).toBe(false)
  })

  it('B7 没有锚点（还没交过稿）→ 不拦', () => {
    expect(isStaleShrink({ id: '', text: '很长很长很长', edits: 0 }, NOTE, '短')).toBe(false)
  })

  it('B8 接线洞①：`App.tsx` 真的调了 `isStaleShrink`，并且拿它改写要存的那一份', () => {
    const code = codeOf(appSrc)
    expect(code).toMatch(/isStaleShrink\(served, current\.id, content\)/)
    expect(code).toMatch(/body = served\.text/)
    expect(code).toMatch(/api\.saveNote\(current\.id, title, body\)/)
    // 落草稿的也得是改写之后那一份，不然短的那一份从草稿这条路又回来了
    expect(code).toMatch(/writeDraft\(current\.id, title, body\)/)
  })

  it('B9 接线洞②：`edits` 真的在编辑器报上来的那一条路上加（不是裸 `setContent`）', () => {
    const code = codeOf(appSrc)
    expect(code).toMatch(/servedRef\.current\.edits\+\+/)
    expect(code).toMatch(/onChange=\{onEditorChange\}/)
    expect(code).not.toMatch(/onChange=\{setContent\}/)
  })

  it('B10 接线洞③：锚点写在 `liveContentRef` 的 setter 里（13 个赋值点一个都不许漏）', () => {
    const code = codeOf(appSrc)
    // setter 形态：`set current(next: string)` 里面换锚点
    expect(code).toMatch(/set current\(next: string\) \{/)
    expect(code).toMatch(/servedRef\.current = \{ id: servedRef\.current\.id, text: next, edits: 0 \}/)
    // 而且 `liveContentRef` 不许再退回成裸 `useRef`（退回去 = 13 个赋值点一个都不记）
    expect(code).not.toMatch(/const liveContentRef = useRef/)
    // 赋值点一个都没少：数一下还在不在（P68 量的是 13 处）
    expect((code.match(/liveContentRef\.current = /g) ?? []).length).toBeGreaterThanOrEqual(12)
  })

  it('B11 接线洞④：`open()` 换篇时换锚点（不换的话 B5 那一格会误拦）', () => {
    const code = codeOf(appSrc)
    expect(code).toMatch(/servedRef\.current = \{ id: n\.id, text: d\.content, edits: 0 \}/)
  })
})
