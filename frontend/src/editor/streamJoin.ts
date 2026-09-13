/** 流式续写的增量落进正文时，把接缝处攒出来的多余空行压回段落分隔。
 *
 *  第 375 轮真跑实拍：本地「确认。\n\n\n\n还要把…」vs 服务端「确认。\n\n还要把…」——模型的流里
 *  一段结束多吐了两个换行，服务端那边 `join_round_text` 会压掉，客户端逐块拼进去不压，一轮下来
 *  差 2–4 字，轮末才被服务端的正文对齐。只处理插入点附近（前两个字到增量末尾），别碰正文别处。 */
export function insertStreamed(content: string, cursor: number | null, text: string): { next: string; cursor: number } {
  const cur = cursor != null && cursor <= content.length ? cursor : content.length
  const joined = content.slice(0, cur) + text + content.slice(cur)
  const from = Math.max(0, cur - 2)
  const to = cur + text.length
  const window = joined.slice(from, to).replace(/\n{3,}/g, '\n\n')
  return { next: joined.slice(0, from) + window + joined.slice(to), cursor: from + window.length }
}

/** 连续空行压回一个（照抄后端 `revision.tidy_blank_lines`）：服务端每应用一条修订就跑一遍，
 *  delete 留下的「前段\n\n」+「\n\n后段」会并成三个空行；客户端本地重放修订之后也得跑，
 *  不然到轮末两边差几个换行。代码块（``` 围栏）里的空行是内容，跳过；围栏外的行尾空白也剥。 */
export function tidyBlankLines(content: string): string {
  const out: string[] = []
  let inFence = false
  let blanks = 0
  for (const line of content.split('\n')) {
    if (line.trimStart().startsWith('```')) inFence = !inFence
    if (!inFence && !line.trim()) {
      blanks += 1
      if (blanks > 1) continue
    } else blanks = 0
    out.push(inFence ? line : line.replace(/\s+$/, ''))
  }
  return out.join('\n')
}
