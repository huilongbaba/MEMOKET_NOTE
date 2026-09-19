/**
 * 块产出**形状对不对**——不对就不落正文（P31 #7）。
 *
 * **这条修的是什么。** P31 实拍：`/` 智能插图拿到的是
 * `{"text": "...", "reason": "..."}`，**整串 JSON 原样落进正文**，还跟着进了目录和写作骨架。
 * P17 当时把它记成「假模型 canned 出的 artifact」——**那个归因是错的**：
 * 真模型一样会答得不合形状（JSON 模式没关干净、把思考过程当正文吐出来、
 * 该给围栏的图给了一段说明），而这条路上**从头到尾没有任何一层校过形状**。
 * `docs/edge-cases.md` 那九列里有「模型报错」，**没有「模型答得不对」**。
 *
 * **判据宁可窄。** 这里只认**明确**不合形状的三类，其余一律放行——
 * 误伤一次正常产出（用户眼睁睁看着跑完 100 秒然后被拦下）比漏掉一次贵得多：
 *   ① 整块是一个 JSON 对象 / 数组（`{...}` 或 `[...]`，且真能 parse）——
 *      markdown 正文不会长这样；只有模型把「结构化输出」漏出来才会。**P31 那条就死在这一档。**
 *   ② 该是表格的（`table`）没有一行 `|`。
 *   ③ 该是图的（`eda`，数据可视化）既没有围栏也没有一张图片。
 * **`chart`（智能插图）只过第 ① 档**：它的界面承诺就是「数据用图表、概念用文生图，自动判断」，
 * 产出可能是 mermaid 围栏、也可能是一张 `![](…)`、还可能是一段说明 + 图，**形状本来就不唯一**，
 * 拿围栏去卡它就是误伤。
 * **不判的**：长度、语言、有没有标题、像不像那回事——那些是打分器的事
 * （`harness.checks.rubric`），不是形状。
 *
 * 纯函数，`App.runBlock` 只负责调它 + 把那句人话摆到占位块上。
 */

/** 剥掉整块外面的代码围栏（模型爱把产出裹一层 ```），只用来判形状，不改落进正文的字。 */
function unfence(text: string): string {
  const s = text.trim()
  if (!s.startsWith('```')) return s
  const i = s.indexOf('\n')
  if (i < 0) return s
  const inner = s.slice(i + 1)
  const j = inner.lastIndexOf('```')
  return (j < 0 ? inner : inner.slice(0, j)).trim()
}

/** 整块是不是一个 JSON 对象 / 数组。**要真能 parse**——只看开头那个 `{`
 *  会把「{产品名} 的定价」这种正常句子误判成 JSON。 */
export function looksLikeJson(text: string): boolean {
  const s = unfence(text)
  if (!((s.startsWith('{') && s.endsWith('}')) || (s.startsWith('[') && s.endsWith(']')))) return false
  try {
    const v = JSON.parse(s)
    return typeof v === 'object' && v !== null
  } catch {
    return false
  }
}

const HAS_TABLE_ROW = /^\s*\|.*\|/m
const HAS_FENCE = /^\s*(```|~~~)/m
const HAS_IMAGE = /!\[[^\]]*\]\([^)]+\)/

/** 这一块该是什么形状：`table` = 得有 markdown 表格行；`figure` = 得有围栏或一张图；
 *  `markdown` = 只要不是整串 JSON 就行。**新模式默认落在 `markdown`**——
 *  漏判比误判便宜，而且 `/` 菜单加一项时不会静默地开出一道新闸。 */
export function shapeOf(key: string): 'table' | 'figure' | 'markdown' {
  if (key === 'table') return 'table'
  if (key === 'eda') return 'figure'
  return 'markdown'
}

// 占位块上那行是**纯文本**（`cm-run-phase` 的 textContent），写 `**粗体**` 会原样露出来——
// P32 第一版实拍到的正是这个。
const RETRY_TAIL = '——这一块没有落进正文。点「重试」再来一次。'

/** 不合形状就回一句**人话**（直接摆在占位块上），合就回空串。 */
export function blockShapeProblem(key: string, text: string): string {
  const s = (text || '').trim()
  if (!s) return ''                       // 空产出另有一条路（「没有产出内容」）
  if (looksLikeJson(s)) {
    return '模型这次答的是一串 JSON，不是能写进正文的内容' + RETRY_TAIL
  }
  const shape = shapeOf(key)
  if (shape === 'table' && !HAS_TABLE_ROW.test(s)) {
    return '这一块该是一张表格，模型这次答的里面一行表格都没有' + RETRY_TAIL
  }
  if (shape === 'figure' && !HAS_FENCE.test(s) && !HAS_IMAGE.test(s)) {
    return '这一块该是一张图（图表代码或一张图片），模型这次答的里面两样都没有' + RETRY_TAIL
  }
  return ''
}
