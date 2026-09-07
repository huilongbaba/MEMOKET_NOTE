import type { RefObject } from 'react'
import type { EditorView } from '@codemirror/view'
import {
  boldCmd, italicCmd, inlineCodeCmd, heading1Cmd, heading2Cmd, heading3Cmd, quoteCmd,
  bulletListCmd, orderedListCmd, taskListCmd, linkCmd, codeBlockCmd, mermaidCmd,
  tableCmd,
} from '../editor/markdownCommands'

const BUTTONS: { label: string; title: string; cmd: (view: EditorView) => void }[] = [
  { label: 'B', title: '加粗 (⌘/Ctrl+B)', cmd: boldCmd },
  { label: 'I', title: '斜体 (⌘/Ctrl+I)', cmd: italicCmd },
  { label: 'H1', title: '一级标题', cmd: heading1Cmd },
  { label: 'H2', title: '二级标题', cmd: heading2Cmd },
  { label: 'H3', title: '三级标题', cmd: heading3Cmd },
  { label: '"', title: '引用', cmd: quoteCmd },
  { label: '•', title: '无序列表', cmd: bulletListCmd },
  { label: '1.', title: '有序列表', cmd: orderedListCmd },
  { label: '☑', title: '任务列表', cmd: taskListCmd },
  { label: '🔗', title: '链接 (⌘/Ctrl+K)', cmd: linkCmd },
  { label: '<>', title: '行内代码', cmd: inlineCodeCmd },
  { label: '{ }', title: '代码块', cmd: codeBlockCmd },
  { label: '表格', title: '插入 3 列空表格', cmd: tableCmd },
  { label: '流程图', title: '插入 mermaid 图表模板', cmd: mermaidCmd },
]

/**
 * Requested directly ("在编辑栏要加markdown的快捷键") -- a compact button
 * row above the editor for the markdown syntax people don't remember by
 * hand (task lists, mermaid template) as well as the ones they do but
 * don't want to type (bold/italic/link). Buttons operate on the live CM6
 * EditorView via viewRef rather than the content string, so selection state
 * and undo history stay correct (same approach as the right-click
 * SelectionMenu actions).
 */
export default function MarkdownToolbar(
  { viewRef, onFormat, onRestructure, restructuring }: {
    viewRef: RefObject<EditorView | null>
    onFormat?: () => void
    onRestructure?: () => void
    restructuring?: boolean
  },
) {
  return (
    <div className="row md-toolbar">
      {onFormat && (
        <button
          title="一键格式化整篇（⌘/Ctrl+⇧+F）：标题、列表、表格对齐、中西文空格。
纯规则不走模型，结果可以逐处接受或撤回。"
          style={{ marginRight: 6 }}
          onMouseDown={(e) => e.preventDefault()}
          onClick={onFormat}
        >
          ⌗ 格式化
        </button>
      )}
      {onRestructure && (
        <button
          title="智能排版：判断哪行该是标题、哪几行该是列表——规则算不出来的语义判断。
模型只决定结构，原文由代码搬运，改不到内容。"
          disabled={restructuring}
          style={{ marginRight: 6 }}
          onMouseDown={(e) => e.preventDefault()}
          onClick={onRestructure}
        >
          {restructuring ? <span className="spinner" /> : '✨ 智能排版'}
        </button>
      )}
      {BUTTONS.map((b) => (
        <button
          key={b.label}
          title={b.title}
          // Without this, the mousedown-then-click sequence steals focus
          // from the editor first, which collapses the very selection the
          // command is supposed to wrap.
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            const view = viewRef.current
            if (view) b.cmd(view)
          }}
        >
          {b.label}
        </button>
      ))}
    </div>
  )
}
