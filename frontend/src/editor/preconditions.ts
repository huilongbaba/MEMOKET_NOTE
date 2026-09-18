/** 整篇动作开跑前规则能判死的临界条件（P3，`docs/edge-cases.md`）。
 *
 * **跟后端 `app/editor/preconditions.py` 是同一份**——每一句话那边原样有一份，
 * 后端测试逐句核对。前端先拦是为了**不发请求**（点了立刻看到那句话、不转圈），
 * 后端再拦是为了发了也不花一次模型调用。
 * 块生成那一组（空指令 / 空选区 / 超长）在 `slashMenu.blockPrecondition`，是 P1 立的同一套纪律。 */

export type NoteAction = 'skeleton' | 'tap' | 'harness' | 'polish' | 'restructure' | 'slides' | 'ingest'

/** 动作 → 空正文时给用户看的那句话。**说清楚要做什么**，不只说「空的」。 */
export const EMPTY_NOTE: Record<NoteAction, string> = {
  skeleton: '先写点内容（或标题）再生成骨架',
  tap: '先写点内容（或标题）再续写',
  harness: '先写个标题或几句话，智能续写才有东西可接',
  polish: '正文是空的——打磨没有可改的内容',
  restructure: '正文是空的——智能排版没有可排的内容',
  slides: '这篇还没有正文，没有可以做成幻灯片的内容',
  ingest: '正文是空的，先写点东西再存入知识库',
}

/** 这几样只看正文，不认标题：标题一句话排不了版、做不了幻灯片、抽不出事实。 */
const BODY_ONLY = new Set<NoteAction>(['polish', 'restructure', 'slides', 'ingest'])

/** 返回给用户看的那句话；空串 = 放行。纯函数，后端有同款。 */
export function notePrecondition(action: NoteAction, content: string, title = ''): string {
  const hasBody = !!content.trim()
  const hasTitle = !!title.trim() && !BODY_ONLY.has(action)
  return hasBody || hasTitle ? '' : EMPTY_NOTE[action]
}

/** 「模型不可达」这一档（`docs/edge-cases.md`「离线」那一列）：状态栏已经红着说
 *  「LLM 不可达」时，再点任何要模型的按钮都是发一个注定失败的请求——原来每个按钮都
 *  照发，转到连接超时才报错。健康检查结果就是判据：红着就先拦，那句话带着地址。 */
export function llmGateMessage(healthMsg: string): string {
  if (!healthMsg.startsWith('LLM 不可达')) return ''
  return healthMsg + '——先在设置里把模型地址 / key 修好，再点这个'
}
