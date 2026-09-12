import { useEffect, useRef } from 'react'
import type { RefObject } from 'react'
import { EditorState } from '@codemirror/state'
import { EditorView, keymap, placeholder as cmPlaceholder } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { autocompletion, completionKeymap } from '@codemirror/autocomplete'
import { search, searchKeymap } from '@codemirror/search'
import { markdown } from '@codemirror/lang-markdown'
import { languages } from '@codemirror/language-data'
import { GFM } from '@lezer/markdown'
import { factPeek } from '../api'
import type { Revision } from '../api'
import { imageEmbed } from '../editor/imageEmbed'
import { imagePaste } from '../editor/imagePaste'
import { linkClick } from '../editor/linkClick'
import { markdownKeymap } from '../editor/markdownCommands'
import { factCite } from '../editor/factCite'
import { mermaidPreview } from '../editor/mermaid'
import { runningBlocks } from '../editor/runningBlocks'
import { tablePreview } from '../editor/tablePreview'
import { recallSource } from '../editor/recallCompletion'
import { noteLinkSource } from '../editor/noteLinkCompletion'
import { noteLinkChips } from '../editor/noteLink'
import { minimalChange } from '../editor/minimalChange'
import { getNote } from '../api'
import { taskCheckbox } from '../editor/taskCheckbox'
import { revisionField, setRevisions, revisionClickHandler } from '../editor/revisions'
import { pendingHunks, roundDiff as roundDiffExt, setRoundDiff, type DiffPart }
  from '../editor/roundDiff'
import { slashMenu, type SlashItem } from '../editor/slashMenu'
import { markdownHighlight, dimSyntaxMarks, editorTheme, syntaxHighlighting } from '../editor/theme'

/**
 * Markdown-native editor (CodeMirror 6): the document is always a single
 * plain string, same contract as the old plain <textarea> -- so the
 * anchor-based revision system (LLM returns an exact substring of `content`
 * to highlight) needed zero backend changes. On top of that plain string,
 * CM6 adds real markdown syntax styling, dimmed (not hidden) delimiter
 * characters, live-rendered mermaid diagrams under fenced ```mermaid
 * blocks, and revision highlights as native decorations instead of the old
 * transparent-textarea-over-backdrop hack.
 */
type Props = {
  content: string
  onChange?: (v: string) => void
  revisions?: Revision[]
  onAcceptInline?: (r: Revision) => void
  placeholder?: string
  viewRef?: RefObject<EditorView | null>
  /** Read-only rendering (e.g. a generated digest) -- still gets markdown
   * styling and rendered mermaid blocks, just no typing/completion/revisions. */
  readOnly?: boolean
  /** 「这一轮 harness 改了什么」的只读高亮：新增标绿、删掉的原文以删除线
   * 就地补出来。跟 revisions 不是一回事——那个是待接受的建议，这个是已经
   * 自动应用完的改动，用户否则完全不知道正文被动了哪里。 */
  roundDiff?: DiffPart[] | null
  /** 还剩几处 harness 改动没被接受/撤回。用来在编辑器上方显示「N 处改动 ·
   * 全部接受」——逐处点是主路径，但改动多的时候必须有个一次性收尾的出口。 */
  onPendingDiff?: (n: number) => void
  /** 右键选中一段文本。**监听装在这里而不是 App 里**：App 那版是
   * `useEffect(..., [current])` 里读 `editorViewRef.current` 再 addEventListener，
   * ref 还没填好就直接 return 且不再重试，编辑器一旦重挂（EditorView 被销毁重建）
   * 监听就留在了已销毁的旧 DOM 上，右键从此永远没反应。装在 view 自己的挂载
   * effect 里，生命周期天然对齐。 */
  onSelectionContextMenu?: (x: number, y: number, text: string) => void
  /** `/` 唤起的插入菜单选中了某一项。扩展只负责"选了哪一项、`/` 从哪到哪"，
   * 具体做什么（跑 harness、传图、录音）由上层决定——CM6 扩展里不该出现网络
   * 请求和文件上传。 */
  onSlash?: (item: SlashItem, from: number, to: number) => void
  /** 用户在某个「正在跑」的占位块上点了停止。 */
  onStopRun?: (id: string) => void
}

export default function MarkdownEditor({
  content, onChange, revisions = [], onAcceptInline, placeholder, viewRef, readOnly = false,
  roundDiff = null, onPendingDiff, onSelectionContextMenu, onSlash, onStopRun,
}: Props) {
  const hostRef = useRef<HTMLDivElement>(null)
  const lastPending = useRef(-1)
  const fallbackViewRef = useRef<EditorView | null>(null)
  const actualViewRef = viewRef ?? fallbackViewRef
  // The EditorView is long-lived and reads through this ref instead of
  // being torn down/recreated on every prop change -- only `content` and
  // `revisions` need an actual dispatch into CM6 state, callbacks don't.
  const liveRef = useRef({ onChange, onAcceptInline, revisions, onPendingDiff,
                          onSelectionContextMenu, onSlash, onStopRun })
  useEffect(() => {
    liveRef.current = { onChange, onAcceptInline, revisions, onPendingDiff,
                        onSelectionContextMenu, onSlash, onStopRun }
  })

  // Tracks the last doc text CM6 itself emitted via onChange, so the
  // content-sync effect below can tell "this update is React echoing our
  // own edit back" apart from "this is a genuinely external change" (note
  // switch, magic-tap streaming, revision accepted) without a feedback loop.
  const lastEmitted = useRef(content)

  useEffect(() => {
    if (!hostRef.current) return
    const state = EditorState.create({
      doc: content,
      extensions: [
        // 行内出处：`[terrence-1872-5F8]` 悬停看原话。判据 2——为了看一条
        // 旧记录而跳走，代价是那条思路；浮层的代价是移开鼠标。
        factCite(async (id) => {
          const f = await factPeek(id)
          return f && { text: f.text, when: f.when, sources: f.sources }
        }),
        history(),
        // ⌘[ / ⌘] 是外壳的后退 / 前进；defaultKeymap 把它们绑成缩进，排在前面截掉
        keymap.of([
          { key: 'Mod-[', run: () => { window.dispatchEvent(new CustomEvent('nav-history', { detail: -1 })); return true } },
          { key: 'Mod-]', run: () => { window.dispatchEvent(new CustomEvent('nav-history', { detail: 1 })); return true } },
        ]),
        keymap.of([...markdownKeymap, ...defaultKeymap, ...historyKeymap, ...completionKeymap, ...searchKeymap, indentWithTab]),
        // ⌘F 页内查找（Trilium 的 FindWidget）。长文档没有它是硬伤。
        search({ top: true }),
        autocompletion({ override: [recallSource, noteLinkSource], activateOnTyping: true }),
        markdown({ codeLanguages: languages, extensions: [GFM] }),
        syntaxHighlighting(markdownHighlight),
        dimSyntaxMarks,
        noteLinkChips(async (id) => { try { return await getNote(id) } catch { return null } }),
        mermaidPreview,
        tablePreview,
        runningBlocks((id) => liveRef.current.onStopRun?.(id)),
        imageEmbed,
        imagePaste,
        taskCheckbox,
        linkClick,
        revisionField,
        roundDiffExt,
        slashMenu((item, from, to) => liveRef.current.onSlash?.(item, from, to)),
        revisionClickHandler((id) => {
          const r = liveRef.current.revisions.find((x) => x.id === id)
          if (r) liveRef.current.onAcceptInline?.(r)
        }),
        editorTheme,
        cmPlaceholder(placeholder ?? ''),
        EditorView.lineWrapping,
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            const text = update.state.doc.toString()
            lastEmitted.current = text
            liveRef.current.onChange?.(text)
          }
          // 待处置的改动数：接受/撤回、用户自己编辑、下一轮写入都会让它变。
          // 只在变化时往上报，避免每次按键都触发一次 React 渲染。
          const n = pendingHunks(update.view)
          if (n !== lastPending.current) {
            lastPending.current = n
            liveRef.current.onPendingDiff?.(n)
          }
        }),
        ...(readOnly ? [EditorState.readOnly.of(true), EditorView.editable.of(false)] : []),
      ],
    })
    const view = new EditorView({ state, parent: hostRef.current })
    actualViewRef.current = view

    // **右键菜单要用的选区必须在 mousedown 时就抓下来。**
    //
    // 顺序是 mousedown(button 2) → contextmenu，而浏览器在右键点到**选区之外**
    // 时会先折叠选区、把光标移过去。等到 contextmenu 再读 state.selection，
    // 十有八九已经是空的了——表现就是「有时候右键出不来菜单」：点在选中文字
    // 正上方有，点偏一两个字就没有。
    let pending: string | null = null
    const onMouseDown = (e: MouseEvent) => {
      if (e.button !== 2) return
      const sel = view.state.selection.main
      pending = sel.empty ? null : view.state.sliceDoc(sel.from, sel.to)
    }
    const onContextMenu = (e: MouseEvent) => {
      // mousedown 那一刻没选区就让给浏览器原生菜单（复制/粘贴/拼写检查）。
      const text = pending
      pending = null
      if (!text) return
      e.preventDefault()
      liveRef.current.onSelectionContextMenu?.(e.clientX, e.clientY, text)
    }
    view.dom.addEventListener('mousedown', onMouseDown)
    view.dom.addEventListener('contextmenu', onContextMenu)

    return () => {
      view.dom.removeEventListener('mousedown', onMouseDown)
      view.dom.removeEventListener('contextmenu', onContextMenu)
      view.destroy()
      actualViewRef.current = null
    }
    // mount once; content/revisions after this are pushed via dispatch below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const view = actualViewRef.current
    if (!view) return
    if (content === lastEmitted.current) return
    const current = view.state.doc.toString()
    if (content === current) { lastEmitted.current = content; return }
    // 只改真正变了的那一段（editor/minimalChange.ts）。整篇替换会把光标和视口
    // 拽到文末，流式往中间插一段时用户根本看不到写在哪；选区交给 CM 映射。
    const change = minimalChange(current, content)
    if (change) view.dispatch({ changes: change })
    lastEmitted.current = content
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content])

  useEffect(() => {
    actualViewRef.current?.dispatch({ effects: setRevisions.of(revisions) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revisions])

  useEffect(() => {
    // 必须排在 content 那个 effect 之后：diff 的位置是针对新正文算的，
    // 文档还没换上去就 dispatch 会标到旧位置上（而且 roundDiffField 一见
    // docChanged 就会把高亮丢掉）。React 按 effect 声明顺序执行，这里靠
    // 声明位置保证顺序。
    actualViewRef.current?.dispatch({ effects: setRoundDiff.of(roundDiff) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roundDiff])

  return <div ref={hostRef} className="editor md-editor" />
}
