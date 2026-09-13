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

/** 服务端轮内删掉一句元话语（`scrub` 事件）时，本地照同一套规则删——照抄
 *  backend/app/harness/checks/grounding_rules.scrub_meta_sentences_v：
 *  按空行切段；表格 / 代码块 / 标题段不动；命中的段按「。！？」切句，删掉那句，**其余每句 strip 后无缝拼回**；
 *  最后连续空行压成一个、整篇 strip。之前本地只是把那句从字符串里抠掉，服务端却把同段其它句子的首尾空格
 *  也吃了（「。 [terrence-1833-10F1]」→「。[terrence-…]」），每轮都差 1 个字（第 492 轮真跑）。
 *  scripts/check-scrub-parity 拿样本跟 Python 那边对拍。 */
export function applyScrub(content: string, sentence: string): string {
  if (!content || !sentence || !content.includes(sentence)) return content
  const out: string[] = []
  let any = false
  for (const para of content.split(/(\n\s*\n)/)) {
    const t = para.trim()
    if (t.startsWith('|') || t.startsWith('```') || t.startsWith('#') || !para.includes(sentence)) { out.push(para); continue }
    const kept: string[] = []
    let hit = false
    for (const x of para.split(/(?<=[。！？])/)) {
      if (!x) continue
      if (x.trim() === sentence.trim()) { hit = true; continue }
      kept.push(x.trim() || x)
    }
    // 服务端发来的那句是按同一规则切出来再 strip 的（前面带引用 id 也算在句里）；对不上整句就别动这段
    if (hit) any = true
    out.push(hit ? kept.join('') : para)
  }
  if (!any) return content
  return out.join('').replace(/\n{3,}/g, '\n\n').trim()
}

/** `insert_at` 事件到了：在本地正文的 pos 处为这一轮续写腾位置（照服务端 `outline.insert_into`：
 *  前面收成一个空行、后面以一个空行开头，紧跟在插入点后的孤立标点去掉），返回新正文和之后 delta 该落的游标。
 *  文末为追加预留的空行先收回来。 */
export function prepareInsert(content: string, pos: number): { next: string; cursor: number } {
  const base = content.replace(/\n+$/, '\n')
  const at = Math.min(pos, base.length)
  const head = base.slice(0, at).replace(/\n*$/, '\n\n')
  const tail = base.slice(at).replace(/^\n*/, '').replace(/^[，、。；：,;:]+\s*/, '')
  return { next: head + '\n\n' + tail, cursor: head.length }
}
