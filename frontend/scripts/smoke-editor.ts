/**
 * Runtime smoke test for the CM6 editor extensions -- tsc/vite build only
 * check types, they do NOT catch CM6's runtime-only contracts (e.g. "block
 * decorations may not come from a ViewPlugin", which threw at render time
 * despite type-checking fine). This actually constructs an EditorView in a
 * jsdom document and exercises every extension against real content.
 *
 *     npx tsx scripts/smoke-editor.ts
 */
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>')
// CM6 reads these off the global scope at import time in several places.
;(globalThis as any).window = dom.window
;(globalThis as any).Window = dom.window.constructor
;(globalThis as any).document = dom.window.document
// Node 22+ ships a read-only global `navigator` getter -- direct assignment
// throws, defineProperty overrides it.
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true })
;(globalThis as any).getComputedStyle = dom.window.getComputedStyle
// EditorView reads these off `document.defaultView` (the jsdom Window
// instance itself), not off Node's globalThis -- both need patching.
const raf = (cb: FrameRequestCallback) => setTimeout(() => cb(Date.now()), 0) as unknown as number
const caf = (id: number) => clearTimeout(id)
;(globalThis as any).requestAnimationFrame = raf
;(globalThis as any).cancelAnimationFrame = caf
;(dom.window as any).requestAnimationFrame = raf
;(dom.window as any).cancelAnimationFrame = caf
;(globalThis as any).DocumentFragment = dom.window.DocumentFragment
;(globalThis as any).Node = dom.window.Node
;(globalThis as any).Text = dom.window.Text
;(globalThis as any).MutationObserver = dom.window.MutationObserver
;(globalThis as any).ResizeObserver = dom.window.ResizeObserver ?? class {
  observe() {} unobserve() {} disconnect() {}
}
;(globalThis as any).IntersectionObserver = dom.window.IntersectionObserver ?? class {
  observe() {} unobserve() {} disconnect() {}
}
;(globalThis as any).DOMRect = dom.window.DOMRect
;(globalThis as any).Range = dom.window.Range
// jsdom's layout engine doesn't compute real geometry -- CM6 uses these to
// measure text, so give it inert zero-size boxes rather than throwing.
dom.window.Range.prototype.getBoundingClientRect = () => ({
  top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0, x: 0, y: 0, toJSON() { return this },
})
dom.window.Range.prototype.getClientRects = () => ({ length: 0, item: () => null, [Symbol.iterator]: function* () {} }) as any
dom.window.HTMLElement.prototype.getBoundingClientRect = () => ({
  top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0, x: 0, y: 0, toJSON() { return this },
})

async function main() {
  const { EditorState } = await import('@codemirror/state')
  const { EditorView, keymap } = await import('@codemirror/view')
  const { defaultKeymap, history, historyKeymap } = await import('@codemirror/commands')
  const { autocompletion, completionKeymap } = await import('@codemirror/autocomplete')
  const { markdown } = await import('@codemirror/lang-markdown')
  const { languages } = await import('@codemirror/language-data')
  const { GFM } = await import('@lezer/markdown')
  const { mermaidPreview, autoFixMermaid } = await import('../src/editor/mermaid')

  // Pure-function check for the autofix heuristic itself, independent of
  // jsdom's inability to actually lay out an SVG: the one confirmed real
  // mermaid syntax killer is a quote character inside a [...] label
  // (verified directly against mermaid.parse() -- colons/parens alone are
  // fine, quotes desync the parser). autoFixMermaid should strip quotes
  // found inside bracket labels and leave everything else untouched.
  const badMermaid = 'graph TD\nA[录制信任：从"随时录"到"一定录到且不尴尬"] --> B[下一步]'
  const fixedMermaid = autoFixMermaid(badMermaid)
  if (fixedMermaid.includes('"') || fixedMermaid.includes('“') || fixedMermaid.includes('”')) {
    throw new Error(`autoFixMermaid left a quote character in the label: ${fixedMermaid}`)
  }
  if (!fixedMermaid.includes('A[录制信任：从随时录到一定录到且不尴尬]')) {
    throw new Error(`autoFixMermaid mangled the label beyond just removing quotes: ${fixedMermaid}`)
  }
  const cleanMermaid = 'graph TD\nA[产品负责人] --> B[硬件工程]'
  if (autoFixMermaid(cleanMermaid) !== cleanMermaid) {
    throw new Error('autoFixMermaid changed already-clean mermaid source (should be a no-op)')
  }
  console.log('OK: autoFixMermaid strips quote characters from bracket labels, leaves clean source untouched')
  const { imageEmbed } = await import('../src/editor/imageEmbed')
  const { taskCheckbox } = await import('../src/editor/taskCheckbox')
  const { revisionField, setRevisions } = await import('../src/editor/revisions')
  const { markdownHighlight, dimSyntaxMarks, editorTheme, syntaxHighlighting } = await import('../src/editor/theme')

  const host = document.createElement('div')
  document.body.appendChild(host)

  const state = EditorState.create({
    doc: '# hello\n\nsome **bold** and *italic* text\n',
    extensions: [
      history(),
      keymap.of([...defaultKeymap, ...historyKeymap, ...completionKeymap]),
      autocompletion({ override: [], activateOnTyping: true }),
      markdown({ codeLanguages: languages, extensions: [GFM] }),
      syntaxHighlighting(markdownHighlight),
      dimSyntaxMarks,
      mermaidPreview,
      imageEmbed,
      taskCheckbox,
      revisionField,
      editorTheme,
      EditorView.lineWrapping,
    ],
  })

  const view = new EditorView({ state, parent: host })
  console.log('OK: mounted with heading/emphasis content')

  // Marks stay ALWAYS visible (styled gray via .cm-syntax-mark), regardless
  // of cursor position -- an earlier version hid them off-line entirely
  // (full live-preview), but that was reverted on direct request
  // ("markdown的格式还是灰色吧") since marks popping in/out while typing
  // nearby felt jumpy for such a small, frequent element. Move the cursor
  // to a different line and confirm the heading/bold marks are still there.
  view.dispatch({ selection: { anchor: view.state.doc.toString().indexOf('bold') } })
  if (!host.textContent?.includes('# hello')) {
    throw new Error('heading mark "#" got hidden while cursor is on a different line (should stay visible+gray)')
  }
  if (!host.textContent?.includes('**bold**')) {
    throw new Error('"**" marks got hidden while cursor is on a different line (should stay visible+gray)')
  }
  const headingMark = host.querySelector('.cm-syntax-mark')
  if (!headingMark) throw new Error('no .cm-syntax-mark element found -- marks not styled at all')
  console.log('OK: markdown marks (#, **) stay visible and gray-styled regardless of cursor position')

  // The bug that actually broke things: a ```mermaid fenced block, which
  // triggers mermaidPreview's block-widget decoration path.
  const mermaidFrom = view.state.doc.length
  view.dispatch({
    changes: {
      from: mermaidFrom,
      insert: '\n\n```mermaid\ngraph TD\nA-->B\n```\n\nmore text after\n',
    },
  })
  console.log('OK: inserted a ```mermaid block, no throw')

  // Mermaid live preview: cursor OUTSIDE the block -> raw source hidden,
  // only the rendered widget shows (never both -- reported directly:
  // "显示了mermaid图，为什么还显示mermaid的code"). Cursor starts at the end
  // of the doc (outside the block) after the insert above.
  if (host.textContent?.includes('graph TD')) {
    throw new Error('raw mermaid source still visible in DOM while cursor is outside the block')
  }
  if (!host.querySelector('.cm-mermaid-widget')) throw new Error('mermaid widget not shown while cursor is outside the block')
  console.log('OK: mermaid raw source hidden, only the rendered widget shows, while cursor is outside the block')

  // Cursor moved INSIDE the block -> raw source reappears (editable), widget
  // is suppressed so a stale diagram never sits next to source mid-edit.
  view.dispatch({ selection: { anchor: mermaidFrom + 20 } }) // inside "graph TD\nA-->B"
  if (!host.textContent?.includes('graph TD')) throw new Error('raw mermaid source not shown while cursor is inside the block')
  if (host.querySelector('.cm-mermaid-widget')) throw new Error('mermaid widget still shown while cursor is inside the block (should be suppressed)')
  console.log('OK: mermaid raw source shown, widget suppressed, while cursor is inside the block')

  // Move back out so the rest of the test (which asserts on the widget)
  // exercises the normal not-editing state again.
  view.dispatch({ selection: { anchor: view.state.doc.length } })

  // Table (GFM extension) + revision decoration together.
  view.dispatch({
    changes: {
      from: view.state.doc.length,
      insert: '\n\n| a | b |\n|---|---|\n| 1 | 2 |\n',
    },
  })
  view.dispatch({
    effects: setRevisions.of([
      { id: 'r1', op: 'replace', anchor: 'bold', text: 'BOLD', reason: '', sources: [] },
    ]),
  })
  console.log('OK: table content + revision decoration, no throw')

  // Image embed: a 1x1 PNG data URI, cursor moved away so the Decoration.replace
  // widget actually renders (it deliberately falls back to raw text while the
  // cursor sits inside the image's markdown range).
  const PIXEL = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
  const imageMd = `\n\n![test](${PIXEL})\n\nafter image\n`
  const imageFrom = view.state.doc.length
  view.dispatch({ changes: { from: imageFrom, to: imageFrom, insert: imageMd } })
  view.dispatch({ selection: { anchor: view.state.doc.length } }) // move cursor off the image line
  const img = host.querySelector('.cm-image-embed') as HTMLImageElement | null
  if (!img) throw new Error('image embed widget never rendered')
  if (!img.src.startsWith('data:image/png')) throw new Error(`image widget got wrong src: ${img.src.slice(0, 40)}`)
  console.log('OK: image embed renders <img> with correct src when cursor is elsewhere')

  // Move the cursor back inside the image's own range -- should fall back
  // to raw text (no widget), not throw.
  view.dispatch({ selection: { anchor: imageFrom + 5 } })
  console.log('OK: moving cursor into image markdown range, no throw')

  // GFM task list -- clicking the rendered checkbox widget should flip the
  // literal [ ]/[x] character in the document, same as the real click
  // handler does (bypassing DOM click dispatch, which jsdom's checkbox
  // doesn't reliably simulate -- calling the same handler directly is the
  // meaningful check: does toggling actually mutate the doc text).
  const taskFrom = view.state.doc.length
  view.dispatch({ changes: { from: taskFrom, to: taskFrom, insert: '\n\n- [ ] todo item\n' } })
  const checkbox = host.querySelector('.cm-task-checkbox') as HTMLInputElement | null
  if (!checkbox) throw new Error('task checkbox widget never rendered')
  if (checkbox.checked) throw new Error('unchecked task rendered as checked')
  checkbox.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))
  const textAfterClick = view.state.doc.toString()
  if (!textAfterClick.includes('- [x] todo item') && !textAfterClick.includes('- [X] todo item')) {
    throw new Error(`checkbox click did not toggle the doc text; got: ${JSON.stringify(textAfterClick.slice(taskFrom))}`)
  }
  console.log('OK: clicking task checkbox toggles [ ] -> [x] in the actual document text')

  // Markdown toolbar commands -- these dispatch directly against the
  // EditorView (same mechanism the toolbar buttons use), so this is the
  // actual code path, not a simulation of it.
  const {
    boldCmd, heading1Cmd, heading2Cmd, heading3Cmd, taskListCmd, linkCmd,
  } = await import('../src/editor/markdownCommands')

  // Bold: wrap a selection, then toggle it back off by running the same
  // command again on the now-wrapped range.
  const boldFrom = view.state.doc.length
  view.dispatch({ changes: { from: boldFrom, to: boldFrom, insert: '\n\ntarget' } })
  view.dispatch({ selection: { anchor: boldFrom + 2, head: boldFrom + 2 + 'target'.length } })
  boldCmd(view)
  if (!view.state.doc.toString().includes('**target**')) {
    throw new Error(`boldCmd did not wrap the selection; doc tail: ${JSON.stringify(view.state.doc.toString().slice(boldFrom))}`)
  }
  view.dispatch({ selection: { anchor: view.state.selection.main.from, head: view.state.selection.main.to } })
  boldCmd(view)
  if (view.state.doc.toString().includes('**target**')) {
    throw new Error('boldCmd did not toggle back off on an already-bolded selection')
  }
  console.log('OK: boldCmd wraps a selection with ** and toggles back off on repeat')

  // Heading: toggle a level on, then off, matching a repeat click.
  const headFrom = view.state.doc.length
  view.dispatch({ changes: { from: headFrom, to: headFrom, insert: '\n\nplain line' } })
  view.dispatch({ selection: { anchor: headFrom + 2 } })
  heading2Cmd(view)
  const afterHeading = view.state.doc.toString()
  if (!afterHeading.includes('## plain line')) throw new Error(`heading2Cmd did not add "## " prefix; got: ${JSON.stringify(afterHeading.slice(headFrom))}`)
  heading2Cmd(view)
  if (view.state.doc.toString().includes('## plain line')) throw new Error('heading2Cmd did not remove the prefix on repeat')
  console.log('OK: heading2Cmd toggles a "## " line prefix on and off')

  // Doesn't just asked for("head没有123级吗") -- also has to correctly
  // SWITCH levels, not stack a second "#" run in front of the first.
  heading1Cmd(view)
  if (!view.state.doc.toString().includes('# plain line')) throw new Error('heading1Cmd did not add "# " prefix')
  heading3Cmd(view)
  const afterSwitch = view.state.doc.toString()
  if (!afterSwitch.includes('### plain line')) throw new Error(`heading3Cmd did not switch to "### "; got: ${JSON.stringify(afterSwitch.slice(headFrom))}`)
  if (afterSwitch.includes('# ### plain line') || afterSwitch.includes('## ### plain line')) {
    throw new Error('heading level switch stacked prefixes instead of replacing the old one')
  }
  console.log('OK: switching heading levels (H1->H3) replaces the old prefix instead of stacking a new one in front')

  // Task list prefix, same toggle check with a longer multi-token prefix.
  const taskCmdFrom = view.state.doc.length
  view.dispatch({ changes: { from: taskCmdFrom, to: taskCmdFrom, insert: '\n\nbuy milk' } })
  view.dispatch({ selection: { anchor: taskCmdFrom + 2 } })
  taskListCmd(view)
  if (!view.state.doc.toString().includes('- [ ] buy milk')) throw new Error('taskListCmd did not add "- [ ] " prefix')
  console.log('OK: taskListCmd adds a "- [ ] " line prefix')

  // Link: empty selection -> "[]()" template with cursor placed inside the
  // brackets (position right after "[").
  const linkFrom = view.state.doc.length
  view.dispatch({ changes: { from: linkFrom, to: linkFrom, insert: '\n\n' } })
  view.dispatch({ selection: { anchor: view.state.doc.length } })
  linkCmd(view)
  if (!view.state.doc.toString().endsWith('[]()')) throw new Error('linkCmd did not insert "[]()" template')
  if (view.state.selection.main.from !== view.state.doc.length - 3) {
    throw new Error('linkCmd did not place the cursor inside the [] brackets')
  }
  console.log('OK: linkCmd inserts "[]()" with cursor positioned inside the brackets')

  // Give the async mermaid.render() a moment to resolve/reject inside the
  // widget so a failure there surfaces as an unhandled rejection too.
  await new Promise((r) => setTimeout(r, 800))

  // NOTE: mermaid's actual diagram layout (dagre) calls SVGElement.getBBox()
  // for text measurement, which jsdom cannot provide -- it isn't a partial
  // shim gap, jsdom does no real layout at all. So this only proves the
  // widget's own error path is reached cleanly (no uncaught exception, no
  // unhandled rejection); it can't prove mermaid renders a correct diagram
  // in an actual browser. That part still needs real-browser verification.
  const widget = host.querySelector('.cm-mermaid-widget')
  if (!widget) throw new Error('mermaid widget never mounted')
  console.log(`OK: mermaid widget resolved to some terminal state (${widget.className})`)

  // jsdom can't do real SVG layout (no getBBox), so even syntactically valid
  // mermaid ends up on the error path here -- which incidentally makes this
  // a fine place to check the error UI itself: raw source must be preserved
  // and visible, not just a dead "mermaid 语法错误" label (the old behavior,
  // reported as unhelpful -- a bomb icon with no way to see or fix the code).
  const errCode = host.querySelector('.cm-mermaid-error-code')
  const errMsg = host.querySelector('.cm-mermaid-error-msg')
  if (!errCode || !errMsg) throw new Error('mermaid error fallback did not render raw-code UI')
  if (!errCode.textContent?.includes('graph TD')) {
    throw new Error(`mermaid error fallback lost the original source; got: ${errCode.textContent}`)
  }
  console.log('OK: mermaid error fallback preserves and shows the raw ```mermaid source')

  view.destroy()
  console.log('ALL SMOKE CHECKS PASSED')
}

main().catch((err) => {
  console.error('SMOKE TEST FAILED:', err)
  process.exit(1)
})
