/** 快捷键一览——只列真的在 App.tsx / 编辑器里接了的键。改键记得同步这里。 */
export const SHORTCUT_GROUPS: { title: string; items: { keys: string; what: string }[] }[] = [
  { title: '笔记', items: [
    { keys: '⌘N / ⌘T', what: '新建笔记' },
    { keys: '⌘S', what: '保存（自动保存已开，这只是个安心键）' },
    { keys: '⌘K / ⌘J', what: '搜索笔记与知识库、跳转、命令' },
    { keys: '⌘[ / ⌘]', what: '后退 / 前进' },
    { keys: 'F2', what: '在树上重命名' },
    { keys: '⌫', what: '在树上删除选中的笔记' },
  ] },
  { title: '标签与布局', items: [
    { keys: '⌘W', what: '关闭当前标签' },
    { keys: '⇧⌘T', what: '重新打开刚关掉的标签' },
    { keys: '⌘1 … ⌘9', what: '跳到第 n 个标签（⌘9 是最后一个）' },
    { keys: '⌃Tab / ⌃⇧Tab', what: '轮换标签' },
    { keys: '⌘\\ / ⇧⌘\\', what: '折叠左栏 / 右栏' },
    { keys: '⌘.', what: '专注模式' },
  ] },
  { title: '写作', items: [
    { keys: '/', what: '行首唤起 AI 菜单：用 AI 写、插图、表格、可视化、语音' },
    { keys: '@', what: '引用知识库里的一条事实' },
    { keys: '[[', what: '链接另一篇笔记（⌘点击链接跳过去）' },
    { keys: '⇧⌘F', what: '格式化整篇 Markdown' },
    { keys: '⌘B / ⌘I / ⇧⌘K', what: '粗体 / 斜体 / 插入链接' },
    { keys: '选中后右键', what: '校验 / 重写 / 润色 / 扩展 / 来龙去脉' },
    { keys: '⌥点击', what: '树上快速查看一篇（不切页）' },
    { keys: '⌘/', what: '这张表' },
  ] },
]
