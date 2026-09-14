/**
 * 「到知识库里搜这个词」带过去的那个词。
 *
 * 侧栏搜笔记没搜到时给的是一条去处，点了要先打开知识库页、再把词填进它的
 * 搜索框。用 `setTimeout` + 事件去送这个词是**赌面板已经挂载**：慢一点就
 * 丢了，而且没有任何提示。改成放在这儿等着——面板挂载时自己来取（取走就
 * 清掉，返回一次之后不再返回），已经挂着的那种情况仍然收事件。
 */
let pending = ''

export function setPendingKbQuery(q: string): void { pending = q }

export function takePendingKbQuery(): string {
  const q = pending
  pending = ''
  return q
}
